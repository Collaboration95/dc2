from contextlib import asynccontextmanager
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from _processing_doubles import NOW, Rows, Session, pair

from legacy.processing_rq import recovery as rq_recovery
from legacy.processing_rq.config import LegacySettings
from processing import lifecycle, recovery
from processing.models import Attempt, CleanupIntent


def cfg():
    return LegacySettings(
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
    monkeypatch.setattr(rq_recovery, "db_now", AsyncMock(return_value=NOW))
    monkeypatch.setattr(rq_recovery, "lock_pair", AsyncMock(return_value=(job, attempt)))
    enqueue = Mock(return_value=True)
    monkeypatch.setattr(rq_recovery, "enqueue_attempt", enqueue)
    assert await rq_recovery.repair_queued(lambda: session, cfg(), queue=object()) == 1
    assert attempt.next_dispatch_at == NOW + timedelta(seconds=15)
    assert await rq_recovery.repair_queued(lambda: session, cfg(), queue=object()) == 0
    attempt.next_dispatch_at = NOW
    enqueue.side_effect = OSError("sensitive")
    assert await rq_recovery.repair_queued(lambda: session, cfg(), queue=object()) == 0
    assert attempt.dispatch_error == "Queue delivery unavailable"
    attempt.next_dispatch_at = NOW
    job.status = "processing"
    assert await rq_recovery.repair_queued(lambda: session, cfg(), queue=object()) == 0
    monkeypatch.setattr(rq_recovery, "lock_pair", AsyncMock(return_value=None))
    assert await rq_recovery.repair_queued(lambda: session, cfg(), queue=object()) == 0


async def test_cleanup_only_terminal_prefix_repeats_and_protects_winner(monkeypatch):
    job, attempt, _, _ = pair("failed")
    intent = CleanupIntent(
        job_id=job.id, attempt_id=attempt.id, next_try_at=NOW, tries=0, created_at=NOW
    )
    session = Session()
    session.execute.return_value = Rows([(job.id, attempt.id)])
    session.scalar.return_value = job
    session.get.side_effect = lambda cls, _, **kw: intent if cls is CleanupIntent else attempt
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
    session.get.side_effect = lambda cls, _, **kw: None if cls is CleanupIntent else attempt
    assert await recovery.cleanup_outputs(lambda: session, cfg(), store=store) == 0


@pytest.mark.parametrize("state", ["queued", "processing", "succeeded"])
async def test_cleanup_protects_live_and_succeeded_attempts(monkeypatch, state):
    job, attempt, _, _ = pair("processing")
    # A noncurrent prefix still needs terminal-state validation. Even a corrupt
    # tombstone cannot make a live attempt eligible for deletion.
    job.current_attempt_id = None
    job.deleted_at = None if state == "succeeded" else NOW
    attempt.state = state
    intent = CleanupIntent(
        job_id=job.id, attempt_id=attempt.id, next_try_at=NOW, tries=0, created_at=NOW
    )
    session = Session()
    session.execute.return_value = Rows([(job.id, attempt.id)])
    session.scalar.return_value = job
    session.get.side_effect = lambda cls, _, **kw: intent if cls is CleanupIntent else attempt
    monkeypatch.setattr(recovery, "db_now", AsyncMock(return_value=NOW))
    store = SimpleNamespace(delete_prefix=AsyncMock())
    assert await recovery.cleanup_outputs(lambda: session, cfg(), store=store) == 0
    store.delete_prefix.assert_not_awaited()
    assert intent.tries == 0


@pytest.mark.parametrize("missing", ["job", "attempt", "intent", "attempt_owner", "intent_owner"])
async def test_cleanup_requires_matching_persisted_identity(monkeypatch, missing):
    job, attempt, _, _ = pair("failed")
    intent = CleanupIntent(
        job_id=job.id, attempt_id=attempt.id, next_try_at=NOW, tries=0, created_at=NOW
    )
    session = Session()
    session.execute.return_value = Rows([(job.id, attempt.id)])
    session.scalar.return_value = None if missing == "job" else job
    if missing == "attempt_owner":
        attempt.job_id = None
    if missing == "intent_owner":
        intent.job_id = None
    session.get.side_effect = lambda cls, _, **kw: (
        None
        if (cls is Attempt and missing == "attempt")
        or (cls is CleanupIntent and missing == "intent")
        else intent
        if cls is CleanupIntent
        else attempt
    )
    monkeypatch.setattr(recovery, "db_now", AsyncMock(return_value=NOW))
    store = SimpleNamespace(delete_prefix=AsyncMock())
    assert await recovery.cleanup_outputs(lambda: session, cfg(), store=store) == 0
    store.delete_prefix.assert_not_awaited()
    assert intent.tries == 0


async def test_cleanup_io_has_no_session_and_cancellation_retains_scan(monkeypatch):
    import asyncio

    job, attempt, _, _ = pair("failed")
    intent = CleanupIntent(
        job_id=job.id, attempt_id=attempt.id, next_try_at=NOW, tries=0, created_at=NOW
    )
    session = Session()
    session.execute.return_value = Rows([(job.id, attempt.id)])
    session.scalar.return_value = job
    session.get.side_effect = lambda cls, _, **kw: intent if cls is CleanupIntent else attempt
    monkeypatch.setattr(recovery, "db_now", AsyncMock(return_value=NOW))
    open_sessions = 0

    @asynccontextmanager
    async def factory():
        nonlocal open_sessions
        open_sessions += 1
        try:
            yield session
        finally:
            open_sessions -= 1

    async def delete_prefix(prefix):
        assert open_sessions == 0
        assert intent.tries == 1 and intent.next_try_at > NOW
        raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        await recovery.cleanup_outputs(
            factory, cfg(), store=SimpleNamespace(delete_prefix=delete_prefix)
        )
    assert intent.next_try_at == NOW + timedelta(seconds=60)


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
    monkeypatch.setattr(rq_recovery, "recover_expired", expire)
    monkeypatch.setattr(rq_recovery, "repair_queued", AsyncMock(side_effect=OSError("secret")))
    monkeypatch.setattr(rq_recovery, "cleanup_outputs", clean)
    assert await rq_recovery.run_once(None, cfg()) == {"expired": 2, "repaired": 0, "cleaned": 1}
    clean.assert_awaited_once()
    monkeypatch.setattr(rq_recovery, "repair_queued", AsyncMock(return_value=3))
    assert (await rq_recovery.run_once(None, cfg()))["repaired"] == 3


@pytest.mark.parametrize("error", [None, OSError("secret")])
async def test_recovery_once_entry_closes_pool_sanitizes_failure(monkeypatch, error):
    engine = SimpleNamespace(dispose=AsyncMock())
    monkeypatch.setattr(rq_recovery, "get_settings", cfg)
    monkeypatch.setattr(rq_recovery, "create_async_engine", Mock(return_value=engine))
    monkeypatch.setattr(rq_recovery, "async_sessionmaker", Mock(return_value=object()))
    callback = AsyncMock(side_effect=error, return_value={})
    monkeypatch.setattr(rq_recovery, "run_once", callback)
    if error:
        with pytest.raises(RuntimeError, match="Recovery pass unavailable"):
            await rq_recovery.run(once=True)
    else:
        await rq_recovery.run(once=True)
    engine.dispose.assert_awaited_once()


def test_recovery_main_once_arguments(monkeypatch):
    monkeypatch.setattr("sys.argv", ["legacy.processing_rq.recovery", "--once"])
    run = AsyncMock()
    monkeypatch.setattr(rq_recovery, "run", run)
    rq_recovery.main()
    run.assert_awaited_once_with(True)
