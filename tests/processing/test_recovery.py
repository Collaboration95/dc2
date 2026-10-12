from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from _processing_doubles import NOW, Rows, Session, pair

from processing import lifecycle, recovery
from processing.config import Settings
from processing.models import CleanupIntent


def cfg():
    return Settings(
        postgres_dsn="postgresql://unused@unused/processing_db",
        redis_url="redis://unused",
        minio_access_key="cleanup",
        minio_secret_key="test",
    )


async def test_expired_and_raced_heartbeat_decisions(monkeypatch):
    job, attempt, _, _ = pair()
    session = Session()
    session.execute.return_value = Rows([(job.id, attempt.id)])
    monkeypatch.setattr(recovery, "db_now", AsyncMock(return_value=NOW))
    monkeypatch.setattr(recovery, "lock_pair", AsyncMock(return_value=(job, attempt)))
    assert await recovery.recover_expired(lambda: session) == 0
    attempt.deadline_at = NOW - timedelta(seconds=1)
    assert await recovery.recover_expired(lambda: session) == 1
    assert job.status == "failed" and attempt.state == "abandoned"
    assert job.error == "Processing exceeded its time limit"
    assert await recovery.recover_expired(lambda: session) == 0
    monkeypatch.setattr(recovery, "lock_pair", AsyncMock(return_value=None))
    assert await recovery.recover_expired(lambda: session) == 0


async def test_queue_repair_backoff_and_race_decisions(monkeypatch):
    job, attempt, _, _ = pair("queued")
    session = Session()
    session.execute.return_value = Rows([(job.id, attempt.id)])
    monkeypatch.setattr(recovery, "db_now", AsyncMock(return_value=NOW))
    monkeypatch.setattr(recovery, "lock_pair", AsyncMock(return_value=(job, attempt)))
    enqueue = Mock(return_value=True)
    monkeypatch.setattr(recovery, "enqueue_attempt", enqueue)
    assert await recovery.repair_queued(lambda: session, cfg(), queue=object()) == 1
    assert attempt.next_dispatch_at == NOW + timedelta(seconds=15)
    assert await recovery.repair_queued(lambda: session, cfg(), queue=object()) == 0
    attempt.next_dispatch_at = NOW
    enqueue.side_effect = OSError("sensitive")
    assert await recovery.repair_queued(lambda: session, cfg(), queue=object()) == 0
    assert attempt.dispatch_error == "Queue delivery unavailable"
    attempt.next_dispatch_at = NOW
    job.status = "processing"
    assert await recovery.repair_queued(lambda: session, cfg(), queue=object()) == 0
    monkeypatch.setattr(recovery, "lock_pair", AsyncMock(return_value=None))
    assert await recovery.repair_queued(lambda: session, cfg(), queue=object()) == 0


async def test_cleanup_only_terminal_prefix_repeats_and_protects_winner(monkeypatch):
    job, attempt, _, _ = pair("failed")
    intent = CleanupIntent(job_id=job.id, attempt_id=attempt.id, next_try_at=NOW, tries=0)
    session = Session()
    session.execute.return_value = Rows([(job.id, attempt.id)])
    session.scalar.return_value = job
    session.get.side_effect = lambda cls, _: intent if cls is CleanupIntent else attempt
    monkeypatch.setattr(recovery, "db_now", AsyncMock(return_value=NOW))
    store = SimpleNamespace(delete_prefix=AsyncMock())
    assert await recovery.cleanup_outputs(lambda: session, cfg(), store=store) == 1
    store.delete_prefix.assert_awaited_once_with(lifecycle.output_prefix(job.id, attempt.id))
    assert intent.tries == 1 and intent.next_try_at > NOW
    assert await recovery.cleanup_outputs(lambda: session, cfg(), store=store) == 0
    intent.next_try_at = NOW
    job.status = "done"
    assert await recovery.cleanup_outputs(lambda: session, cfg(), store=store) == 0
    intent.next_try_at = NOW
    job.deleted_at = NOW
    store.delete_prefix.side_effect = OSError("sensitive")
    assert await recovery.cleanup_outputs(lambda: session, cfg(), store=store) == 0
    assert intent.last_error == "Output cleanup unavailable"
    session.get.side_effect = lambda cls, _: None if cls is CleanupIntent else attempt
    assert await recovery.cleanup_outputs(lambda: session, cfg(), store=store) == 0


async def test_cleanup_store_list_delete_only(monkeypatch):
    client = Mock()
    client.list_objects.return_value = [SimpleNamespace(object_name="prefix/out")]
    client.remove_objects.side_effect = lambda _, objects: [] if list(objects) else []
    monkeypatch.setattr("processing.worker.storage.Minio", Mock(return_value=client))
    store = recovery.CleanupStore(cfg())
    await store.delete_prefix("prefix/")
    assert not client.get_object.called and not client.stat_object.called
    client.remove_objects.return_value = [SimpleNamespace(code="error")]
    client.remove_objects.side_effect = None
    with pytest.raises(ValueError):
        await store.delete_prefix("prefix/")


async def test_queue_outage_does_not_prevent_expiry_or_cleanup(monkeypatch):
    expire = AsyncMock(return_value=2)
    clean = AsyncMock(return_value=1)
    monkeypatch.setattr(recovery, "recover_expired", expire)
    monkeypatch.setattr(recovery, "repair_queued", AsyncMock(side_effect=OSError("secret")))
    monkeypatch.setattr(recovery, "cleanup_outputs", clean)
    assert await recovery.run_once(None, cfg()) == {"expired": 2, "repaired": 0, "cleaned": 1}
    clean.assert_awaited_once()
    monkeypatch.setattr(recovery, "repair_queued", AsyncMock(return_value=3))
    assert (await recovery.run_once(None, cfg()))["repaired"] == 3


@pytest.mark.parametrize("error", [None, OSError("secret")])
async def test_recovery_once_entry_closes_pool_sanitizes_failure(monkeypatch, error):
    engine = SimpleNamespace(dispose=AsyncMock())
    monkeypatch.setattr(recovery, "get_settings", cfg)
    monkeypatch.setattr(recovery, "create_async_engine", Mock(return_value=engine))
    monkeypatch.setattr(recovery, "async_sessionmaker", Mock(return_value=object()))
    callback = AsyncMock(side_effect=error, return_value={})
    monkeypatch.setattr(recovery, "run_once", callback)
    if error:
        with pytest.raises(RuntimeError, match="Recovery pass unavailable"):
            await recovery.run(once=True)
    else:
        await recovery.run(once=True)
    engine.dispose.assert_awaited_once()


def test_recovery_main_once_arguments(monkeypatch):
    monkeypatch.setattr("sys.argv", ["processing.recovery", "--once"])
    run = AsyncMock()
    monkeypatch.setattr(recovery, "run", run)
    recovery.main()
    run.assert_awaited_once_with(True)
