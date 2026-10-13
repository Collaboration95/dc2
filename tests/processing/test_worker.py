import asyncio
import json
import sys
import time
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import httpx
import pytest

from processing.config import Settings
from processing.worker import tasks
from processing.worker.storage import OutputStore
from processing.worker.supervisor import AttemptDeadline, LeaseLost, Supervisor


def cfg(**kw):
    return Settings(postgres_dsn="postgresql://unused@unused/processing_db", **kw)


def work():
    return SimpleNamespace(
        job_id=uuid4(),
        attempt_id=uuid4(),
        lease_token=uuid4(),
        owner_id=uuid4(),
        source={
            "asset_id": str(uuid4()),
            "revision": 1,
            "sha256": "a" * 64,
            "size_bytes": 10,
            "media_type": "video/mp4",
        },
        operations=[],
        source_url="http://original.test",
        source_url_expires_at=datetime.now(UTC),
    )


@pytest.mark.parametrize("exception", [LeaseLost, AttemptDeadline, asyncio.CancelledError])
async def test_hls_does_not_swallow_control_flow(monkeypatch, tmp_path, exception):
    monkeypatch.setattr(tasks, "download", AsyncMock())
    sup = Mock()
    sup.guard = AsyncMock(side_effect=lambda op: op)

    async def guard(op):
        return await op

    sup.guard.side_effect = guard
    sup.run = AsyncMock(
        side_effect=[
            json.dumps({"streams": [{"width": 32, "height": 24}], "format": {"duration": "1"}}),
            "",
            exception(),
        ]
    )
    store = SimpleNamespace(put=AsyncMock(return_value={"kind": "primary"}))
    with pytest.raises(exception):
        await tasks.pipeline(work(), cfg(), sup, None, store, tmp_path)


async def test_hls_failure_retains_primary(monkeypatch, tmp_path):
    monkeypatch.setattr(tasks, "download", AsyncMock())
    sup = Mock()

    async def guard(op):
        return await op

    sup.guard = guard
    sup.run = AsyncMock(
        side_effect=[
            json.dumps({"streams": [{"width": 32, "height": 24}], "format": {"duration": "1"}}),
            "",
            ValueError("HLS"),
        ]
    )
    store = SimpleNamespace(put=AsyncMock(return_value={"kind": "primary"}))
    assert await tasks.pipeline(work(), cfg(), sup, None, store, tmp_path) == [{"kind": "primary"}]


async def test_guard_loss_interrupts_download_or_upload(monkeypatch):
    monkeypatch.setattr("processing.worker.supervisor.heartbeat", AsyncMock(return_value=True))
    sup = Supervisor(None, work(), cfg())
    cancelled = asyncio.Event()

    async def blocked():
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    async with sup:
        task = asyncio.create_task(sup.guard(blocked()))
        await asyncio.sleep(0)
        sup.lost.set()
        with pytest.raises(LeaseLost):
            await task
    assert cancelled.is_set()


async def test_process_group_stopped_on_loss(monkeypatch, tmp_path):
    monkeypatch.setattr("processing.worker.supervisor.heartbeat", AsyncMock(return_value=True))
    sup = Supervisor(None, work(), cfg())
    marker = tmp_path / "started"
    # Subprocess is local and deliberately alive until lease loss.
    script = f"import time,pathlib; pathlib.Path({str(marker)!r}).touch(); time.sleep(60)"
    async with sup:
        task = asyncio.create_task(sup.run([sys.executable, "-c", script]))
        async with asyncio.timeout(2):
            while not marker.exists():  # noqa: ASYNC110 - bounded subprocess readiness
                await asyncio.sleep(0.01)
        sup.lost.set()
        with pytest.raises(LeaseLost):
            await asyncio.wait_for(task, 2)


async def test_supervisor_deadline_and_bad_subprocess(monkeypatch):
    monkeypatch.setattr("processing.worker.supervisor.heartbeat", AsyncMock(return_value=True))
    async with Supervisor(None, work(), cfg()) as sup:
        with pytest.raises(ValueError, match="could not be processed"):
            await sup.run([sys.executable, "-c", "raise SystemExit(1)"])
        sup.deadline = time.monotonic() + 0.01
        with pytest.raises(AttemptDeadline):
            await sup.guard(asyncio.sleep(1))


@pytest.mark.parametrize("alive", [False, RuntimeError("secret")])
async def test_heartbeat_revokes_on_failure(monkeypatch, alive):
    callback = (
        AsyncMock(side_effect=alive)
        if isinstance(alive, Exception)
        else AsyncMock(return_value=alive)
    )
    monkeypatch.setattr("processing.worker.supervisor.heartbeat", callback)
    async with Supervisor(None, work(), cfg()) as sup:
        await asyncio.wait_for(sup.lost.wait(), 0.5)
        with pytest.raises(LeaseLost):
            sup.check()


@pytest.mark.parametrize("changed", ["revision", "owner", "expired"])
async def test_reverse_grant_full_descriptor_verified(changed):
    attempt = work()
    source = dict(attempt.source)
    if changed in {"revision", "owner"}:
        source["revision" if changed == "revision" else "asset_id"] = (
            2 if changed == "revision" else str(uuid4())
        )
    expires = datetime.now(UTC) + timedelta(minutes=-1 if changed == "expired" else 1)
    transport = httpx.MockTransport(
        lambda _: httpx.Response(
            200,
            json={
                "source_url": "http://source.test",
                "expires_at": expires.isoformat(),
                "source": source,
            },
        )
    )
    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(ValueError):
            await tasks.renew_source(client, attempt, cfg())


async def test_output_put_acknowledgment_without_head(monkeypatch, tmp_path):
    client = Mock()

    def upload(_bucket, _key, stream, length, **_kwargs):
        assert stream.read(length) == b"output"
        return SimpleNamespace(etag=etag)

    etag = "ack"
    client.put_object.side_effect = upload
    monkeypatch.setattr("processing.worker.storage.Minio", Mock(return_value=client))
    store = OutputStore(cfg(minio_access_key="writer", minio_secret_key="secret"))
    path = tmp_path / "out"
    path.write_bytes(b"output")
    output = await store.put("key", path, "video/mp4", "primary")
    assert output["size_bytes"] == 6 and len(output["sha256"]) == 64
    assert not client.stat_object.called and not client.get_object.called
    etag = ""
    with pytest.raises(ValueError):
        await store.put("key", path, "video/mp4", "primary")


def test_entrypoint_specific_config_requirements():
    with pytest.raises(ValueError, match="Worker requires"):
        cfg().require_worker()
    with pytest.raises(ValueError, match="Recovery requires"):
        cfg().require_recovery()
    configured = cfg(
        redis_url="redis://unused",
        source_service_token="reverse",
        minio_access_key="principal",
        minio_secret_key="secret",
    )
    configured.require_worker()
    configured.require_recovery()
    with pytest.raises(ValueError, match="heartbeat interval"):
        cfg(lease_seconds=10, heartbeat_seconds=10)


@pytest.mark.parametrize("error", [None, LeaseLost(), AttemptDeadline(), OSError("secret")])
async def test_execute_success_and_fenced_failures(monkeypatch, tmp_path, error):
    attempt = work()
    monkeypatch.setattr(tasks.lifecycle, "claim", AsyncMock(return_value=attempt))
    complete = AsyncMock(return_value=True)
    monkeypatch.setattr(tasks.lifecycle, "finish", complete)
    monkeypatch.setattr("processing.worker.supervisor.heartbeat", AsyncMock(return_value=True))
    monkeypatch.setattr(
        tasks, "pipeline", AsyncMock(side_effect=error, return_value=[{"output": "ack"}])
    )
    if error is None:
        assert await tasks.execute(
            None, attempt.job_id, attempt.attempt_id, cfg(), client=object(), store=object()
        )
        assert complete.call_args.kwargs["outputs"] == [{"output": "ack"}]
    elif isinstance(error, LeaseLost):
        assert not await tasks.execute(
            None, attempt.job_id, attempt.attempt_id, cfg(), client=object(), store=object()
        )
        complete.assert_not_awaited()
    else:
        assert await tasks.execute(
            None, attempt.job_id, attempt.attempt_id, cfg(), client=object(), store=object()
        )
        assert "secret" not in complete.call_args.kwargs["error"]
    monkeypatch.setattr(tasks.lifecycle, "claim", AsyncMock(return_value=None))
    assert not await tasks.execute(None, uuid4(), uuid4(), cfg())


async def test_execute_owns_transport(monkeypatch):
    attempt = work()
    monkeypatch.setattr(tasks.lifecycle, "claim", AsyncMock(return_value=attempt))
    monkeypatch.setattr(tasks.lifecycle, "finish", AsyncMock(return_value=True))
    monkeypatch.setattr("processing.worker.supervisor.heartbeat", AsyncMock(return_value=True))
    monkeypatch.setattr(tasks, "pipeline", AsyncMock(return_value=[]))
    monkeypatch.setattr(tasks, "OutputStore", Mock())
    assert await tasks.execute(None, attempt.job_id, attempt.attempt_id, cfg())


def test_rq_task_entry_closes_owned_pool(monkeypatch):
    engine = SimpleNamespace(dispose=AsyncMock())
    monkeypatch.setattr(tasks, "get_settings", cfg)
    monkeypatch.setattr(tasks, "create_async_engine", Mock(return_value=engine))
    monkeypatch.setattr(tasks, "async_sessionmaker", Mock(return_value=object()))
    execute = AsyncMock(return_value=True)
    monkeypatch.setattr(tasks, "execute", execute)
    assert tasks.process_attempt(str(uuid4()), str(uuid4()))
    execute.assert_awaited_once()
    engine.dispose.assert_awaited_once()


def test_worker_main_uses_forking_rq_worker(monkeypatch):
    from processing.worker import __main__ as entry

    cfg = Settings(
        postgres_dsn="postgresql://unused@unused/db",
        redis_url="redis://unused",
        source_service_token="reverse",
        minio_access_key="writer",
        minio_secret_key="test",
    )
    monkeypatch.setattr(entry, "get_settings", lambda: cfg)
    target = SimpleNamespace(connection=object())
    monkeypatch.setattr(entry, "get_queue", lambda: target)
    worker = Mock()
    monkeypatch.setattr("rq.Worker", Mock(return_value=worker))
    monkeypatch.setattr("sys.argv", ["processing.worker", "--burst"])
    entry.main()
    worker.work.assert_called_once_with(burst=True)


async def test_total_deadline_is_not_reset_between_stages(monkeypatch):
    monkeypatch.setattr("processing.worker.supervisor.heartbeat", AsyncMock(return_value=True))
    async with Supervisor(None, work(), cfg()) as sup:
        sup.deadline = time.monotonic() + 0.03
        await sup.guard(asyncio.sleep(0.02))
        with pytest.raises(AttemptDeadline):
            await sup.guard(asyncio.sleep(0.02))


async def test_cancel_stops_descendant_when_process_leader_already_exited(monkeypatch, tmp_path):
    import os

    monkeypatch.setattr("processing.worker.supervisor.heartbeat", AsyncMock(return_value=True))
    pid_file = tmp_path / "child-pid"
    child_script = (
        f"import os,time,pathlib; pathlib.Path({str(pid_file)!r}).write_text(str(os.getpid())); "
        "time.sleep(60)"
    )
    script = f"import subprocess,sys; subprocess.Popen([sys.executable, '-c', {child_script!r}])"
    async with Supervisor(None, work(), cfg()) as sup:
        task = asyncio.create_task(sup.run([sys.executable, "-c", script]))
        async with asyncio.timeout(2):
            while not pid_file.exists():  # noqa: ASYNC110 - bounded process readiness
                await asyncio.sleep(0.01)
        sup.lost.set()
        with pytest.raises(LeaseLost):
            await asyncio.wait_for(task, 2)
        child_pid = int(pid_file.read_text())
        # Reaping orphaned children can lag; distinguish a zombie from a live process.
        async with asyncio.timeout(2):
            while True:  # noqa: ASYNC110 - bounded process death polling
                process = await asyncio.create_subprocess_exec(
                    "ps", "-o", "stat=", "-p", str(child_pid), stdout=asyncio.subprocess.PIPE
                )
                output, _ = await process.communicate()
                if not output.strip() or output.strip().startswith(b"Z"):
                    break
                await asyncio.sleep(0.01)
        with pytest.raises(ProcessLookupError):
            # On macOS the adopted process is already reaped; Linux may retain
            # zombies briefly, so this final assertion applies only there.
            if sys.platform == "darwin":
                os.kill(child_pid, 0)
            else:
                raise ProcessLookupError
