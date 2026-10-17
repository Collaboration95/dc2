"""The retired RQ worker path: Media's HTTP source grant, the RQ task and its entrypoint."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import httpx
import pytest

from legacy.processing_rq import tasks
from legacy.processing_rq.config import LegacySettings as Settings
from processing.worker.supervisor import AttemptDeadline, LeaseLost


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
    from legacy.processing_rq.worker import __main__ as entry

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
    monkeypatch.setattr("sys.argv", ["legacy.processing_rq.worker", "--burst"])
    entry.main()
    worker.work.assert_called_once_with(burst=True)


