"""Repair, cleanup and finite-worker behaviour against real PostgreSQL (and Moto SQS).

Time is simulated by rewinding stored timestamps, never by sleeping, and each
assertion states the bound it protects (120s lost work, 300s interrupted work).
Select the stack with V1_TEST_PROCESSING_DSN / V1_TEST_SQS_ENDPOINT as in
test_messaging_sql.py; without them every test here skips.
"""

import asyncio
import os
import time
from datetime import timedelta
from functools import partial
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from delivery.sql import publish_due
from delivery.sqs import SQS
from processing import messaging
from processing.config import Settings
from processing.database import Base
from processing.messaging import claim, finish, handle_command, work_disposition
from processing.messaging_models import JobMessaging, ProcessingOutbox
from processing.models import Attempt, CleanupIntent, Job
from processing.recovery import cleanup_outputs
from processing.recovery_v1 import reemit_result, repair_work, run_once, terminal_event
from processing.worker import sqs as worker
from tests.v1.test_delivery import message
from tests.v1.test_messaging_sql import SETTINGS, count, state

pytestmark = pytest.mark.integration


@pytest_asyncio.fixture
async def factory():
    dsn = os.environ.get("V1_TEST_PROCESSING_DSN")
    if not dsn:
        pytest.skip("Lead C's isolated PostgreSQL DSN not provided")
    schema = "b_recovery_" + uuid4().hex
    admin = create_async_engine(dsn)
    async with admin.begin() as connection:
        await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_async_engine(dsn, connect_args={"server_settings": {"search_path": schema}})
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    try:
        yield async_sessionmaker(engine, expire_on_commit=False)
    finally:
        await engine.dispose()
        async with admin.begin() as connection:
            await connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        await admin.dispose()


async def rewind(factory, seconds):
    """Pretend ``seconds`` elapsed: every stored deadline moves earlier together."""
    async with factory() as session, session.begin():
        for table, columns in {
            "message_outbox": ("next_try_at", "sent_at"),
            "attempts": (
                "next_dispatch_at",
                "lease_expires_at",
                "heartbeat_at",
                "deadline_at",
                "started_at",
                "queued_at",
            ),
            "cleanup_intents": ("next_try_at", "created_at"),
        }.items():
            assignments = ", ".join(f"{c} = {c} - :s * interval '1 second'" for c in columns)
            await session.execute(text(f"UPDATE {table} SET {assignments}"), {"s": seconds})


async def work_row(factory, attempt_id):
    async with factory() as session:
        return await session.scalar(
            select(ProcessingOutbox).where(
                ProcessingOutbox.message_id == messaging.work_message_id(attempt_id, 1)
            )
        )


def recorder():
    sent = []

    async def send(queue, body):
        sent.append((queue, body["kind"], body["message_id"]))

    return SimpleNamespace(send=send), sent


async def submitted(factory):
    """A committed, published submission: returns (job, attempt, transport, sent)."""
    await handle_command(factory, message())
    transport, sent = recorder()
    assert await publish_due(factory, ProcessingOutbox, transport, limit=5) == 2
    job, attempt = await state(factory)
    return job, attempt, transport, sent


async def test_repair_resends_one_stable_work_message_on_a_growing_backoff(factory):
    job, attempt, transport, sent = await submitted(factory)
    original = next(item for item in sent if item[1] == "work")
    assert original[2] == str(messaging.work_message_id(attempt.id, 1))
    rows = await count(factory, ProcessingOutbox)
    # The send itself was the first delivery: nothing to repair for the first minute.
    assert await repair_work(factory) == 0
    await rewind(factory, 50)
    assert await repair_work(factory) == 0
    await rewind(factory, 20)
    assert await repair_work(factory) == 1
    # Re-armed, not re-staged: the outbox does not grow and the ID is unchanged.
    assert await count(factory, ProcessingOutbox) == rows
    assert await publish_due(factory, ProcessingOutbox, transport, limit=5) == 1
    assert sent[-1] == original
    async with factory() as session:
        saved = await session.get(Attempt, attempt.id)
        remaining = await session.scalar(
            select(func.extract("epoch", saved.next_dispatch_at - func.clock_timestamp()))
        )
        assert saved.dispatch_count == 1
    assert 110 <= remaining <= 121
    await rewind(factory, 100)
    assert await repair_work(factory) == 0
    await rewind(factory, 30)
    assert await repair_work(factory) == 1
    async with factory() as session:
        saved = await session.get(Attempt, attempt.id)
        remaining = await session.scalar(
            select(func.extract("epoch", saved.next_dispatch_at - func.clock_timestamp()))
        )
    assert 230 <= remaining <= 241


async def test_repair_skips_work_that_is_still_unsent_or_mid_publication(factory):
    await handle_command(factory, message())
    job, attempt = await state(factory)
    rows = await count(factory, ProcessingOutbox)
    await rewind(factory, 90)
    # Unsent (queue down): the publisher's own backoff owns it, repair adds nothing.
    assert await repair_work(factory) == 0
    assert await count(factory, ProcessingOutbox) == rows
    transport, _ = recorder()
    await publish_due(factory, ProcessingOutbox, transport, limit=5)
    async with factory() as session, session.begin():
        row = await session.get(ProcessingOutbox, messaging.work_message_id(attempt.id, 1))
        row.claim_token = uuid4()  # another invocation is replaying it right now
        saved = await session.get(Attempt, attempt.id)
        saved.next_dispatch_at = await session.scalar(select(func.clock_timestamp()))
    assert await repair_work(factory) == 0
    async with factory() as session:
        row = await session.get(ProcessingOutbox, messaging.work_message_id(attempt.id, 1))
        assert row.claim_token is not None


async def test_lost_committed_work_is_requeued_within_120_seconds(factory):
    await submitted(factory)
    transport, sent = recorder()
    store = SimpleNamespace(delete_prefix=AsyncMock())
    elapsed = 0
    # The queue silently lost the work message. Repair ticks every 15 simulated seconds.
    while not any(kind == "work" for _, kind, _ in sent):
        assert elapsed < 120, "lost work was not re-enqueued inside the 120s gate"
        await rewind(factory, 15)
        elapsed += 15
        await run_once(factory, SETTINGS, transport, store=store)
    assert 45 <= elapsed <= 120


@pytest.mark.parametrize("lease_seconds", [60, 240])
async def test_interrupted_work_is_resolved_within_300_seconds(factory, lease_seconds):
    settings = SimpleNamespace(attempt_timeout_seconds=900, lease_seconds=lease_seconds)
    job, attempt, transport, _ = await submitted(factory)
    assert await claim(factory, job.id, attempt.id, settings, task_name="dead-task")
    store = SimpleNamespace(delete_prefix=AsyncMock())
    elapsed = 0
    # The worker died without a final heartbeat; a repair tick runs every 30s.
    while True:
        job, attempt = await state(factory)
        if job.status == "failed":
            break
        assert elapsed < 300, "interrupted work stayed processing past the 300s gate"
        await rewind(factory, 30)
        elapsed += 30
        await run_once(factory, settings, transport, store=store)
    assert attempt.state == "abandoned" and attempt.error.startswith("Processing interrupted")
    assert lease_seconds <= elapsed <= lease_seconds + 60 <= 300


async def test_mixed_success_publish_batch_keeps_failed_rows_for_a_later_pass(factory):
    await handle_command(factory, message())

    async def flaky(queue, body):
        if queue == "processing-work":
            raise TimeoutError("work queue unavailable")

    assert await publish_due(factory, ProcessingOutbox, SimpleNamespace(send=flaky), limit=5) == 1
    async with factory() as session:
        rows = {row.queue: row for row in (await session.scalars(select(ProcessingOutbox))).all()}
        assert rows["media-results"].sent_at is not None
        assert rows["processing-work"].sent_at is None
        assert rows["processing-work"].last_error == "Queue publication unavailable"
        assert rows["processing-work"].tries == 1
    transport, sent = recorder()
    assert await publish_due(factory, ProcessingOutbox, transport, limit=5) == 0
    await rewind(factory, 120)
    assert await publish_due(factory, ProcessingOutbox, transport, limit=5) == 1
    assert [queue for queue, _, _ in sent] == ["processing-work"]


@pytest.mark.parametrize("terminal", ["cancelled", "succeeded", "failed", "superseded"])
async def test_disposition_marks_only_provably_dead_attempts_stale(factory, terminal):
    from processing.messaging import cancel_asset, retry_job

    job, attempt, _, _ = await submitted(factory)
    assert await work_disposition(factory, job.id, attempt.id) == "pending"
    assert await work_disposition(factory, uuid4(), attempt.id) == "unknown"
    assert await work_disposition(factory, job.id, uuid4()) == "unknown"
    work = await claim(factory, job.id, attempt.id, SETTINGS, task_name="holder")
    # Claimed elsewhere: the duplicate carries no obligation (recovery owns the lease).
    assert await work_disposition(factory, job.id, attempt.id) == "stale"
    if terminal == "cancelled":
        async with factory() as session:
            await cancel_asset(session, job.owner_id, job.asset_id)
    elif terminal == "succeeded":
        output = {
            "kind": "primary",
            "object_key": f"jobs/{job.id}/attempts/{attempt.id}/primary.mp4",
            "media_type": "video/mp4",
            "size_bytes": 5,
            "sha256": "c" * 64,
        }
        assert await finish(factory, work, outputs=[output])
    else:
        assert await finish(factory, work, error="Controlled failure")
        if terminal == "superseded":
            async with factory() as session:
                await retry_job(session, job.owner_id, job.id, uuid4())
            job, current = await state(factory)
            assert current.id != attempt.id
            assert await work_disposition(factory, job.id, current.id) == "pending"
    assert await work_disposition(factory, job.id, attempt.id) == "stale"


async def test_delayed_ecs_and_s3_events_cannot_touch_a_newer_attempt(factory):
    from processing.messaging import retry_job

    job, first, transport, _ = await submitted(factory)
    old = await claim(factory, job.id, first.id, SETTINGS, task_name="task-one")
    assert await finish(factory, old, error="Controlled failure")
    async with factory() as session:
        await retry_job(session, job.owner_id, job.id, uuid4())
    job, second = await state(factory)
    live = await claim(factory, job.id, second.id, SETTINGS, task_name="task-two")
    store = SimpleNamespace(delete_prefix=AsyncMock())
    # A STOPPED notification for task one arrives after attempt two started.
    stopped = {"detail": {"lastStatus": "STOPPED", "taskArn": "arn:task-one"}}
    assert await terminal_event(factory, stopped) == 0
    # A late S3 notification triggers the generic tick; only attempt one is scanned.
    await run_once(factory, SETTINGS, transport, store=store)
    scanned = [call.args[0] for call in store.delete_prefix.call_args_list]
    assert scanned == [f"jobs/{job.id}/attempts/{first.id}/"]
    job, current = await state(factory)
    assert (job.status, current.id, current.state) == ("processing", second.id, "processing")
    assert await finish(factory, live, error="Controlled failure")


async def seed_intents(factory, count_):
    ids = []
    for _ in range(count_):
        await handle_command(factory, message())
    async with factory() as session:
        jobs = (await session.scalars(select(Job).order_by(Job.created_at))).all()
    for job in jobs:
        work = await claim(
            factory, job.id, job.current_attempt_id, SETTINGS, task_name="t-" + uuid4().hex
        )
        assert await finish(factory, work, error="Controlled failure")
        ids.append(job.current_attempt_id)
    return ids


async def test_cleanup_is_ordered_bounded_and_backs_off_between_rescans(factory):
    ids = await seed_intents(factory, 3)
    # Stagger due times so ordering is observable: ids[2] oldest, then ids[0], ids[1].
    async with factory() as session, session.begin():
        for offset, attempt_id in zip((30, 20, 40), ids, strict=True):
            intent = await session.get(CleanupIntent, attempt_id)
            intent.next_try_at = await session.scalar(select(func.clock_timestamp())) - timedelta(
                seconds=offset
            )
    order = []

    async def record(prefix):
        order.append(prefix.split("/")[3])

    store = SimpleNamespace(delete_prefix=record)
    assert await cleanup_outputs(factory, SETTINGS, store=store, limit=2) == 2
    assert order == [str(ids[2]), str(ids[0])]
    # Only the unscanned intent is still due; scanned ones were rescheduled.
    assert await cleanup_outputs(factory, SETTINGS, store=store, limit=5) == 1
    assert order[-1] == str(ids[1])
    # Rescans thin out: 60s after the first, then 120s, then 240s.
    await rewind(factory, 61)
    assert await cleanup_outputs(factory, SETTINGS, store=store, limit=5) == 3
    await rewind(factory, 61)
    assert await cleanup_outputs(factory, SETTINGS, store=store, limit=5) == 0
    await rewind(factory, 60)
    assert await cleanup_outputs(factory, SETTINGS, store=store, limit=5) == 3
    await rewind(factory, 121)
    assert await cleanup_outputs(factory, SETTINGS, store=store, limit=5) == 0
    await rewind(factory, 120)
    assert await cleanup_outputs(factory, SETTINGS, store=store, limit=5) == 3
    async with factory() as session:
        assert {(await session.get(CleanupIntent, i)).tries for i in ids} == {4}


async def test_cleanup_retires_after_the_horizon_but_never_after_an_error(factory):
    [attempt_id] = await seed_intents(factory, 1)
    store = SimpleNamespace(delete_prefix=AsyncMock())

    async def due():
        async with factory() as session, session.begin():
            intent = await session.get(CleanupIntent, attempt_id)
            intent.next_try_at = await session.scalar(select(func.clock_timestamp())) - timedelta(
                seconds=1
            )

    await rewind(factory, 7200)
    await due()
    store.delete_prefix.side_effect = OSError("sensitive endpoint detail")
    assert await cleanup_outputs(factory, SETTINGS, store=store, horizon_seconds=3600) == 0
    async with factory() as session:
        intent = await session.get(CleanupIntent, attempt_id)
        assert intent.retired_at is None and intent.last_error == "Output cleanup unavailable"
    store.delete_prefix.side_effect = None
    await due()
    assert await cleanup_outputs(factory, SETTINGS, store=store, horizon_seconds=3600) == 1
    async with factory() as session:
        assert (await session.get(CleanupIntent, attempt_id)).retired_at is not None
    calls = store.delete_prefix.await_count
    await due()
    assert await cleanup_outputs(factory, SETTINGS, store=store, horizon_seconds=3600) == 0
    assert store.delete_prefix.await_count == calls


async def test_reemitted_result_supersedes_a_quarantined_version(factory):
    job, attempt, _, _ = await submitted(factory)
    async with factory() as session:
        before = (await session.get(JobMessaging, job.id)).state_version
    assert await reemit_result(factory, job.id)
    assert not await reemit_result(factory, uuid4())
    async with factory() as session:
        after = (await session.get(JobMessaging, job.id)).state_version
        results = (
            await session.scalars(
                select(ProcessingOutbox).where(ProcessingOutbox.queue == "media-results")
            )
        ).all()
    assert after == before + 1
    assert max(row.body["state_version"] for row in results) == after


class ShortPoll:
    """The fixture client times out at 3s, so never long-poll an empty queue."""

    def __init__(self, client):
        self.client = client

    def receive_message(self, **kwargs):
        return self.client.receive_message(**{**kwargs, "WaitTimeSeconds": 0})

    def __getattr__(self, name):
        return getattr(self.client, name)


def worker_settings():
    return Settings(
        postgres_dsn="postgresql://unused@unused/processing_db",
        lease_seconds=60,
        attempt_timeout_seconds=180,
    )


def finishing_pipeline(monkeypatch):
    async def pipeline(work, *_args, **_kwargs):
        return [
            {
                "kind": "primary",
                "object_key": f"jobs/{work.job_id}/attempts/{work.attempt_id}/primary.mp4",
                "media_type": "video/mp4",
                "size_bytes": 5,
                "sha256": "d" * 64,
            }
        ]

    monkeypatch.setattr(worker, "pipeline", pipeline)


async def test_close_then_reopen_processes_retained_work_and_drops_stale_leftovers(
    sqs_local, factory, monkeypatch
):
    from processing.messaging import cancel_asset

    client, urls = sqs_local
    queue = urls["processing-work"]
    finishing_pipeline(monkeypatch)
    sender = SQS(urls, producer="processing", client=client)
    # A cancelled job leaves a stale work message behind (the verify-v1 re-run failure).
    await handle_command(factory, message())
    stale_job, stale_attempt = await state(factory)
    assert await publish_due(factory, ProcessingOutbox, sender, limit=5) == 2
    async with factory() as session:
        await cancel_asset(session, stale_job.owner_id, stale_job.asset_id)
    # The live job whose work is also queued.
    await handle_command(factory, message())
    async with factory() as session:
        live_job = await session.scalar(select(Job).where(Job.id != stale_job.id))
    assert await publish_due(factory, ProcessingOutbox, sender, limit=10) >= 1
    # Session closed: mappings disabled, no consumer, no repair. Nothing is lost.
    attrs = client.get_queue_attributes(QueueUrl=queue, AttributeNames=["All"])["Attributes"]
    assert int(attrs["ApproximateNumberOfMessages"]) == 2
    dlq = client.get_queue_attributes(QueueUrl=urls["processing-work-dlq"], AttributeNames=["All"])
    assert int(dlq["Attributes"]["ApproximateNumberOfMessages"]) == 0
    async with factory() as session:
        assert (await session.get(Job, live_job.id)).status == "queued"
    await asyncio.sleep(1.2)  # fixture visibility timeout: all messages visible again
    # Reopen: one finite task drains the stale message and encodes the live job.
    execute = partial(
        worker.execute_message, store=object(), source=SimpleNamespace(download=AsyncMock())
    )
    code = await worker.run(
        factory,
        worker_settings(),
        ShortPoll(client),
        queue,
        end_epoch=time.time() + 60,
        name="reopen-task",
        empty_polls=1,
        execute=execute,
    )
    assert code == 0
    async with factory() as session:
        done = await session.get(Job, live_job.id)
        assert done.status == "done"
        assert (await session.get(Job, stale_job.id)).deleted_at is not None
        assert (await session.get(Attempt, stale_attempt.id)).state == "cancelled"


async def test_duplicate_work_after_completion_is_acked_not_cycled_to_the_dlq(
    sqs_local, factory, monkeypatch
):
    client, urls = sqs_local
    queue = urls["processing-work"]
    finishing_pipeline(monkeypatch)
    await handle_command(factory, message())
    sender = SQS(urls, producer="processing", client=client)
    assert await publish_due(factory, ProcessingOutbox, sender, limit=5) == 2
    _, attempt = await state(factory)
    # Repair re-sends the identical message: two copies of one work item are queued.
    async with factory() as session, session.begin():
        saved = await session.get(Attempt, attempt.id)
        saved.next_dispatch_at = await session.scalar(select(func.clock_timestamp()))
    assert await repair_work(factory) == 1
    assert await publish_due(factory, ProcessingOutbox, sender, limit=5) == 1
    execute = partial(
        worker.execute_message, store=object(), source=SimpleNamespace(download=AsyncMock())
    )
    first = await worker.run(
        factory,
        worker_settings(),
        ShortPoll(client),
        queue,
        end_epoch=time.time() + 60,
        name="finite-one",
        empty_polls=1,
        execute=execute,
    )
    assert first == 0
    assert (await state(factory))[0].status == "done"
    await asyncio.sleep(1.2)
    # A second finite task meets only the duplicate: it deletes it and ends normally.
    second = await worker.run(
        factory,
        worker_settings(),
        ShortPoll(client),
        queue,
        end_epoch=time.time() + 60,
        name="finite-two",
        empty_polls=1,
        execute=execute,
    )
    assert second == 0
    attrs = client.get_queue_attributes(QueueUrl=queue, AttributeNames=["All"])["Attributes"]
    assert int(attrs["ApproximateNumberOfMessages"]) == 0
    assert int(attrs["ApproximateNumberOfMessagesNotVisible"]) == 0
    dlq = client.get_queue_attributes(QueueUrl=urls["processing-work-dlq"], AttributeNames=["All"])
    assert int(dlq["Attributes"]["ApproximateNumberOfMessages"]) == 0
