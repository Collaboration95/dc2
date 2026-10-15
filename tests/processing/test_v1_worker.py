import asyncio
import hashlib
import subprocess
import sys
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest

from processing.config import Settings
from processing.worker import sqs
from processing.worker.source import SourceStore
from processing.worker.supervisor import LeaseLost, Supervisor


def settings():
    return Settings(postgres_dsn="postgresql://unused@unused/processing_db")


def envelope():
    return {"job_id": str(uuid4()), "attempt_id": str(uuid4())}


async def test_empty_poll_finite_and_one_delivery_per_task():
    client = Mock()
    client.receive_message.return_value = {}
    assert (
        await sqs.run(None, settings(), client, "local", end_epoch=time.time() + 60, name="task")
        == 0
    )
    assert client.receive_message.call_count == 2
    assert all(c.kwargs["WaitTimeSeconds"] == 20 for c in client.receive_message.call_args_list)
    client.receive_message.return_value = {
        "Messages": [{"Body": "work", "ReceiptHandle": "receipt"}]
    }
    execute = AsyncMock(return_value=True)
    assert (
        await sqs.run(
            None,
            settings(),
            client,
            "local",
            end_epoch=time.time() + 60,
            name="task",
            decode=lambda _: envelope(),
            execute=execute,
        )
        == 0
    )
    execute.assert_awaited_once()
    client.delete_message.assert_called_once_with(QueueUrl="local", ReceiptHandle="receipt")


@pytest.mark.parametrize("failure", [False, True])
async def test_no_ack_on_lease_loss_or_malformed_work(failure):
    client = Mock()
    client.receive_message.return_value = {
        "Messages": [{"Body": "bad", "ReceiptHandle": "receipt"}]
    }
    execute = AsyncMock(return_value=False)

    def decode(_):
        if failure:
            raise ValueError("invalid")
        return envelope()

    assert await sqs.run(
        None,
        settings(),
        client,
        "local",
        end_epoch=time.time() + 60,
        name="task",
        decode=decode,
        execute=execute,
    ) in {1, 2}
    client.delete_message.assert_not_called()


async def test_visibility_failure_revokes_sql_lease_authority(monkeypatch):
    monkeypatch.setattr("processing.worker.supervisor.heartbeat", AsyncMock(return_value=True))
    async with Supervisor(
        None, object(), settings(), renew=AsyncMock(side_effect=OSError())
    ) as sup:
        await asyncio.wait_for(sup.lost.wait(), 1)
        with pytest.raises(LeaseLost):
            sup.check()


async def test_claim_rejects_substitution_before_get_or_encode():
    claim = AsyncMock(return_value=None)
    source = SimpleNamespace(download=AsyncMock())
    finish = AsyncMock()
    body = envelope()
    assert not await sqs.execute_message(
        None,
        body,
        settings(),
        renew=AsyncMock(),
        deadline=time.monotonic() + 60,
        claim=claim,
        finish=finish,
        source=source,
    )
    assert claim.call_args.kwargs["envelope"] == body
    source.download.assert_not_awaited()
    finish.assert_not_awaited()


@pytest.mark.parametrize("loss_at", [1, 2])
async def test_no_completion_after_visibility_loss(monkeypatch, loss_at):
    monkeypatch.setattr("processing.worker.supervisor.heartbeat", AsyncMock(return_value=True))
    monkeypatch.setattr(sqs, "pipeline", AsyncMock(return_value=[{"kind": "primary"}]))
    work = SimpleNamespace(source={})
    finish = AsyncMock(return_value=True)
    renew = AsyncMock(side_effect=[None] * (loss_at - 1) + [OSError("receipt gone")])
    assert not await sqs.execute_message(
        None,
        envelope(),
        settings(),
        renew=renew,
        deadline=time.monotonic() + 60,
        claim=AsyncMock(return_value=work),
        finish=finish,
        source=SimpleNamespace(download=AsyncMock()),
        store=object(),
    )
    finish.assert_not_awaited()


async def test_completion_only_through_processing_owned_finish(monkeypatch):
    monkeypatch.setattr("processing.worker.supervisor.heartbeat", AsyncMock(return_value=True))
    monkeypatch.setattr(sqs, "pipeline", AsyncMock(return_value=[{"kind": "primary"}]))
    finish = AsyncMock(return_value=True)
    assert await sqs.execute_message(
        None,
        envelope(),
        settings(),
        renew=AsyncMock(),
        deadline=time.monotonic() + 60,
        claim=AsyncMock(return_value=SimpleNamespace(source={})),
        finish=finish,
        source=SimpleNamespace(download=AsyncMock()),
        store=object(),
    )
    assert finish.call_args.kwargs["outputs"] == [{"kind": "primary"}]


@pytest.mark.parametrize("changed", [None, "size", "digest", "version", "unversioned"])
def test_source_native_version_and_stream_verification(tmp_path, changed):
    data = b"accepted source"
    source = {
        "bucket": "sources",
        "key": "owners/one/source",
        "version_id": "immutable",
        "sha256": hashlib.sha256(data).hexdigest(),
        "size_bytes": len(data),
        "content_type": "video/mp4",
    }
    response = Mock()
    response.headers = {"x-amz-version-id": "immutable"}
    response.read.side_effect = [data[:4], data[4:], b""]
    if changed == "size":
        source["size_bytes"] -= 1
    if changed == "digest":
        source["sha256"] = "a" * 64
    if changed == "version":
        response.headers["x-amz-version-id"] = "other"
    if changed == "unversioned":
        source["version_id"] = "null"
    client = Mock()
    client.get_object.return_value = response
    store = SourceStore(settings(), client=client)
    if changed:
        with pytest.raises(ValueError):
            store._download(source, tmp_path / "source")
    else:
        store._download(source, tmp_path / "source")
        assert (tmp_path / "source").read_bytes() == data
    if changed != "unversioned":
        client.get_object.assert_called_once_with(
            "sources", "owners/one/source", version_id="immutable"
        )
        response.close.assert_called_once()
        response.release_conn.assert_called_once()
    else:
        client.get_object.assert_not_called()


def test_worker_import_graph_has_no_redis_or_rq():
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; import processing.worker.sqs; "
            "import processing.worker.finite; "
            "assert not {'redis', 'rq'}.intersection(sys.modules)",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


async def test_stop_before_poll_and_expired_deadline():
    stop = asyncio.Event()
    stop.set()
    client = Mock()
    assert (
        await sqs.run(
            None, settings(), client, "local", end_epoch=time.time() + 60, name="task", stop=stop
        )
        == 0
    )
    client.receive_message.assert_not_called()
    with pytest.raises(ValueError):
        await sqs.run(None, settings(), client, "local", end_epoch=time.time() - 1, name="task")
