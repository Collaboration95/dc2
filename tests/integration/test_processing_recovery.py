"""Real PostgreSQL recovery plus explicitly gated Redis runnable repair."""

import asyncio
import os
import time
from uuid import UUID, uuid4

import pytest
import test_processing_lifecycle as lane
from redis import Redis
from rq import Queue
from sqlalchemy import text

from processing import lifecycle, recovery, service
from processing.models import Attempt, CleanupIntent
from processing.queue import enqueue_attempt
from processing.worker import supervisor as supervision

asset_ids = lane.asset_ids
factory = lane.factory
postgres = lane.postgres
pytestmark = lane.pytestmark
reserve = lane.reserve
settings = lane.settings
submission = lane.submission


@pytest.fixture
def redis_queue():
    if os.getenv("RUN_PROCESSING_REDIS_TESTS") != "1":
        pytest.skip("set RUN_PROCESSING_REDIS_TESTS=1 for real Redis acceptance")
    if not os.getenv("PROCESSING_REDIS_URL"):
        pytest.fail("RUN_PROCESSING_REDIS_TESTS=1 requires PROCESSING_REDIS_URL")
    conn = Redis.from_url(
        os.environ["PROCESSING_REDIS_URL"], socket_connect_timeout=2, socket_timeout=2
    )
    assert conn.ping()
    queue = Queue("processing-test-" + uuid4().hex, connection=conn)
    try:
        yield queue
    finally:
        # Only this test's registered job/queue keys. Never FLUSHDB or wildcard delete.
        queue.empty()
        queue.delete(delete_jobs=True)
        conn.close()


async def test_lost_queue_list_entry_with_surviving_rq_hash(factory, submission, redis_queue):
    job = await reserve(factory, submission)
    identifier = str(job.current_attempt.attempt_id)
    assert await asyncio.to_thread(
        enqueue_attempt, job.job_id, job.current_attempt.attempt_id, queue=redis_queue
    )
    assert redis_queue.connection.exists("rq:job:" + identifier)
    assert not await asyncio.to_thread(
        enqueue_attempt, job.job_id, job.current_attempt.attempt_id, queue=redis_queue
    )
    redis_queue.connection.lrem(redis_queue.key, 0, identifier)
    assert redis_queue.connection.exists("rq:job:" + identifier)
    started = time.monotonic()
    assert await recovery.repair_queued(factory, settings(), queue=redis_queue) == 1
    assert time.monotonic() - started < 2
    assert redis_queue.get_job_ids() == [identifier]
    payload = redis_queue.fetch_job(identifier)
    assert payload.args == (str(job.job_id), identifier)
    assert await recovery.repair_queued(factory, settings(), queue=redis_queue) == 0
    async with factory() as session:
        attempt = await session.get(Attempt, job.current_attempt.attempt_id)
        assert attempt.dispatch_count == 1 and attempt.dispatch_error is None
    # Ensure the surviving job hash is removed through its own reserved identifier.
    payload.delete()


async def test_queue_failure_has_durable_bounded_backoff(factory, submission):
    job = await reserve(factory, submission)
    from unittest.mock import Mock

    broken = Mock()
    broken.connection.lock.side_effect = OSError("redacted")
    assert await recovery.repair_queued(factory, settings(), queue=broken) == 0
    async with factory() as session:
        attempt = await session.get(Attempt, job.current_attempt.attempt_id)
        assert (
            attempt.dispatch_count == 1 and attempt.dispatch_error == "Queue delivery unavailable"
        )
        assert attempt.next_dispatch_at is not None


async def test_interrupted_attempt_visible_failed_then_retry(factory, submission):
    job = await reserve(factory, submission)
    work = await lifecycle.claim(factory, job.job_id, job.current_attempt.attempt_id, settings())
    async with factory() as session, session.begin():
        await session.execute(
            text(
                "UPDATE attempts SET lease_expires_at=clock_timestamp() "
                "- interval '1 second' WHERE id=:id"
            ),
            {"id": work.attempt_id},
        )
    start = time.monotonic()
    assert await recovery.recover_expired(factory) == 1
    assert time.monotonic() - start < 2
    assert await recovery.recover_expired(factory) == 0
    assert not await lifecycle.finish(factory, work, error="late failure")
    async with factory() as session:
        current = await service.get_job(session, UUID(submission["owner_id"]), job.job_id)
    assert current.status == "failed" and current.current_attempt.state == "abandoned"
    async with factory() as session:
        current = await lifecycle.retry_job(
            session, UUID(submission["owner_id"]), job.job_id, uuid4()
        )
    assert current.current_attempt.number == 2


async def test_healthy_heartbeat_is_not_reaped(factory, submission):
    job = await reserve(factory, submission)
    work = await lifecycle.claim(factory, job.job_id, job.current_attempt.attempt_id, settings())
    assert await lifecycle.heartbeat(factory, work, settings())
    assert await recovery.recover_expired(factory) == 0


class Cleaner:
    def __init__(self):
        self.objects = set()
        self.deleted = []

    async def delete_prefix(self, prefix):
        self.deleted.append(prefix)
        self.objects = {key for key in self.objects if not key.startswith(prefix)}


async def test_old_cleanup_does_not_revoke_healthy_retry(factory, submission, monkeypatch):
    cfg = settings(heartbeat_seconds=0.5)
    job = await reserve(factory, submission)
    old = await lifecycle.claim(factory, job.job_id, job.current_attempt.attempt_id, cfg)
    assert await lifecycle.finish(factory, old, error="Processing interrupted")
    async with factory() as session:
        retry = await lifecycle.retry_job(session, old.owner_id, old.job_id, uuid4())
    work = await lifecycle.claim(factory, job.job_id, retry.current_attempt.attempt_id, cfg)
    old_prefix = lifecycle.output_prefix(old.job_id, old.attempt_id)
    current_key = lane.output(work)[0]["object_key"]
    source_key = "sources/" + submission["asset_id"]
    entered, release_cleanup = asyncio.Event(), asyncio.Event()
    started, release_work, cancelled = asyncio.Event(), asyncio.Event(), asyncio.Event()
    heartbeats_observed = asyncio.Event()
    timestamps = []
    store = Cleaner()
    store.objects = {old_prefix + "partial.mp4", current_key, source_key}
    delete_prefix = store.delete_prefix

    async def blocked_delete(prefix):
        assert prefix == old_prefix
        entered.set()
        await release_cleanup.wait()
        await delete_prefix(prefix)

    async def observed_heartbeat(factory, claim, settings):
        # Observe committed timestamps from the real heartbeat in a new SQL session.
        alive = await lifecycle.heartbeat(factory, claim, settings)
        if alive:
            async with factory() as session:
                attempt = await session.get(Attempt, claim.attempt_id)
                assert attempt.lease_expires_at > await lifecycle.db_now(session)
                timestamps.append(attempt.heartbeat_at)
            if len(timestamps) == 3:
                heartbeats_observed.set()
        return alive

    async def blocked_work():
        started.set()
        try:
            await release_work.wait()
        except asyncio.CancelledError:
            cancelled.set()
            raise

    store.delete_prefix = blocked_delete
    monkeypatch.setattr(supervision, "heartbeat", observed_heartbeat)
    cleanup = asyncio.create_task(recovery.cleanup_outputs(factory, cfg, store=store))
    guarded_work = None
    try:
        await asyncio.wait_for(entered.wait(), timeout=5)
        blocked_at = time.monotonic()
        async with supervision.Supervisor(factory, work, cfg) as supervisor:
            guarded_work = asyncio.create_task(supervisor.guard(blocked_work()))
            await asyncio.wait_for(started.wait(), timeout=5)
            await asyncio.wait_for(supervisor.guard(heartbeats_observed.wait()), timeout=5)
            # Real supervisor intervals span more than its heartbeat timeout;
            # Events order the race, with no test sleeps or timestamp polling.
            assert time.monotonic() - blocked_at > cfg.heartbeat_seconds
            assert timestamps[0] < timestamps[1] < timestamps[2]
            assert not cleanup.done() and not release_cleanup.is_set()
            assert not supervisor.lost.is_set() and not cancelled.is_set()
            assert not guarded_work.done()
            release_cleanup.set()
            assert await asyncio.wait_for(cleanup, timeout=5) == 1
            release_work.set()
            await asyncio.wait_for(guarded_work, timeout=5)
            supervisor.check()
        assert await lifecycle.finish(factory, work, outputs=lane.output(work))
        async with factory() as session:
            result = await service.get_job(session, work.owner_id, work.job_id)
            intent = await session.get(CleanupIntent, old.attempt_id)
            assert result.status == "done" and result.outputs[0].object_key == current_key
            assert result.current_attempt.attempt_id == work.attempt_id
            assert intent.tries == 1 and intent.last_error is None
        assert store.deleted == [old_prefix]
        assert store.objects == {source_key, current_key}
        assert not await lifecycle.finish(factory, old, outputs=lane.output(old))
    finally:
        release_cleanup.set()
        release_work.set()
        await asyncio.gather(
            cleanup, *([guarded_work] if guarded_work else []), return_exceptions=True
        )


async def due(factory, attempt_id):
    async with factory() as session, session.begin():
        await session.execute(
            text("UPDATE cleanup_intents SET next_try_at=clock_timestamp() WHERE attempt_id=:id"),
            {"id": attempt_id},
        )


async def test_repeat_cleanup_removes_late_outputs_preserves_source_and_active(factory, submission):
    job = await reserve(factory, submission)
    work = await lifecycle.claim(factory, job.job_id, job.current_attempt.attempt_id, settings())
    store = Cleaner()
    prefix = lifecycle.output_prefix(work.job_id, work.attempt_id)
    source = "sources/" + submission["asset_id"]
    store.objects = {prefix + "first.mp4", source}
    async with factory() as session:
        await lifecycle.cancel_asset(session, work.owner_id, UUID(submission["asset_id"]))
    assert await recovery.cleanup_outputs(factory, settings(), store=store) == 1
    assert store.objects == {source}
    store.objects.add(prefix + "late.mp4")
    await due(factory, work.attempt_id)
    assert await recovery.cleanup_outputs(factory, settings(), store=store) == 1
    assert store.objects == {source}
    async with factory() as session:
        intent = await session.get(CleanupIntent, work.attempt_id)
        assert intent.tries == 2 and intent.last_error is None
    assert not await lifecycle.finish(factory, work, outputs=lane.output(work))


async def test_erroneous_cleanup_intent_never_deletes_active_or_winning(factory, submission):
    job = await reserve(factory, submission)
    work = await lifecycle.claim(factory, job.job_id, job.current_attempt.attempt_id, settings())
    async with factory() as session, session.begin():
        await lifecycle.cleanup_intent(
            session, work.job_id, work.attempt_id, await lifecycle.db_now(session)
        )
    store = Cleaner()
    assert await recovery.cleanup_outputs(factory, settings(), store=store) == 0
    assert await lifecycle.finish(factory, work, outputs=lane.output(work))
    await due(factory, work.attempt_id)
    assert await recovery.cleanup_outputs(factory, settings(), store=store) == 0
    assert not store.deleted


async def test_cleanup_failure_persists_safe_error(factory, submission):
    job = await reserve(factory, submission)
    async with factory() as session:
        await lifecycle.cancel_asset(
            session, UUID(submission["owner_id"]), UUID(submission["asset_id"])
        )
    from unittest.mock import AsyncMock

    store = Cleaner()
    store.delete_prefix = AsyncMock(side_effect=OSError("secret"))
    assert await recovery.cleanup_outputs(factory, settings(), store=store) == 0
    async with factory() as session:
        intent = await session.get(CleanupIntent, job.current_attempt.attempt_id)
        assert intent.tries == 1 and intent.last_error == "Output cleanup unavailable"


@pytest.mark.parametrize("first_fails", [False, True])
async def test_late_cleanup_result_cannot_overwrite_newer_scan(factory, submission, first_fails):
    job = await reserve(factory, submission)
    work = await lifecycle.claim(factory, job.job_id, job.current_attempt.attempt_id, settings())
    assert await lifecycle.finish(factory, work, error="Processing interrupted")
    entered, release = asyncio.Event(), asyncio.Event()

    class FirstScan(Cleaner):
        async def delete_prefix(self, prefix):
            entered.set()
            await release.wait()
            if first_fails:
                raise OSError("secret")
            await super().delete_prefix(prefix)

    class SecondScan(Cleaner):
        async def delete_prefix(self, prefix):
            if not first_fails:
                raise OSError("secret")
            await super().delete_prefix(prefix)

    first = asyncio.create_task(recovery.cleanup_outputs(factory, settings(), store=FirstScan()))
    try:
        await asyncio.wait_for(entered.wait(), timeout=5)
        # Advance only this test's durable intent instead of waiting 60 seconds.
        await asyncio.wait_for(due(factory, work.attempt_id), timeout=5)
        assert await recovery.cleanup_outputs(factory, settings(), store=SecondScan()) == int(
            first_fails
        )
        async with factory() as session:
            intent = await session.get(CleanupIntent, work.attempt_id)
            next_try = intent.next_try_at
            assert intent.tries == 2
        release.set()
        assert await asyncio.wait_for(first, timeout=5) == int(not first_fails)
        async with factory() as session:
            intent = await session.get(CleanupIntent, work.attempt_id)
            assert intent.tries == 2 and intent.next_try_at == next_try
            assert intent.last_error == (None if first_fails else "Output cleanup unavailable")
    finally:
        release.set()
        await asyncio.gather(first, return_exceptions=True)


async def test_cancelled_cleanup_keeps_durable_reservation(factory, submission):
    job = await reserve(factory, submission)
    work = await lifecycle.claim(factory, job.job_id, job.current_attempt.attempt_id, settings())
    assert await lifecycle.finish(factory, work, error="Processing interrupted")
    entered, release = asyncio.Event(), asyncio.Event()

    class BlockedScan(Cleaner):
        async def delete_prefix(self, prefix):
            entered.set()
            await release.wait()

    cleanup = asyncio.create_task(
        recovery.cleanup_outputs(factory, settings(), store=BlockedScan())
    )
    try:
        await asyncio.wait_for(entered.wait(), timeout=5)
        cleanup.cancel()
        with pytest.raises(asyncio.CancelledError):
            await cleanup
        async with factory() as session:
            intent = await session.get(CleanupIntent, work.attempt_id)
            assert intent.tries == 1 and intent.next_try_at > await lifecycle.db_now(session)
        await due(factory, work.attempt_id)
        assert await recovery.cleanup_outputs(factory, settings(), store=Cleaner()) == 1
        async with factory() as session:
            intent = await session.get(CleanupIntent, work.attempt_id)
            assert intent.tries == 2 and intent.last_error is None
    finally:
        cleanup.cancel()
        await asyncio.gather(cleanup, return_exceptions=True)
