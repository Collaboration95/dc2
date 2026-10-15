"""Real PostgreSQL durable messaging checks, against Lead C's single local stack.

Set V1_TEST_PROCESSING_DSN explicitly. Each test owns an ephemeral SQL schema;
no tables outside that schema are touched. No S3, FFmpeg or extra stack is used.
"""

import copy
import os
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from delivery.sql import MessageConflict, publish_due
from processing.database import Base
from processing.errors import ProcessingError
from processing.messaging import claim, finish, handle_command
from processing.messaging_models import JobMessaging, ProcessingInbox, ProcessingOutbox
from processing.models import Attempt, CleanupIntent, Job, SubmissionGuard
from processing.recovery import cleanup_outputs
from processing.recovery_v1 import repair_work, run_once
from tests.v1.test_delivery import message

pytestmark = pytest.mark.integration
SETTINGS = SimpleNamespace(attempt_timeout_seconds=180, lease_seconds=60)


@pytest_asyncio.fixture
async def factory():
    dsn = os.environ.get("V1_TEST_PROCESSING_DSN")
    if not dsn:
        pytest.skip("Lead C's isolated PostgreSQL DSN not provided")
    if not dsn.startswith("postgresql+asyncpg://"):
        raise ValueError("V1_TEST_PROCESSING_DSN must select asyncpg explicitly")
    schema = "b_messaging_" + uuid4().hex
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


async def count(factory, model):
    async with factory() as session:
        return await session.scalar(select(func.count()).select_from(model))


async def state(factory):
    async with factory() as session:
        job = await session.scalar(select(Job))
        attempt = await session.get(Attempt, job.current_attempt_id)
        return job, attempt


async def test_submit_duplicate_conflict_and_rollback(factory):
    body = message()
    assert await handle_command(factory, body)
    assert not await handle_command(factory, body)
    assert await count(factory, Job) == 1
    assert await count(factory, ProcessingInbox) == 1
    assert await count(factory, ProcessingOutbox) == 2
    conflict = copy.deepcopy(body)
    conflict["payload"] = {"operations": [{"operation": "downscale", "params": {"height": 240}}]}
    with pytest.raises(MessageConflict):
        await handle_command(factory, conflict)
    conflict["message_id"] = str(uuid4())
    with pytest.raises(ProcessingError):
        await handle_command(factory, conflict)
    # Conflict failure must not mark the command handled.
    assert await count(factory, ProcessingInbox) == 1
    job, _ = await state(factory)
    assert job.source == body["source"]


async def test_cancel_before_submit_is_permanent(factory):
    submit = message()
    cancel = {**submit, "message_id": str(uuid4()), "kind": "cancel", "source": None}
    assert await handle_command(factory, cancel)
    assert await handle_command(factory, submit)
    assert await count(factory, Job) == 0
    async with factory() as session:
        guard = await session.get(SubmissionGuard, UUID(submit["asset_id"]))
        assert guard.deleted_at is not None
    assert await count(factory, ProcessingOutbox) == 1
    async with factory() as session:
        ack = await session.scalar(select(ProcessingOutbox))
        assert ack.body["job_id"] is None and ack.body["attempt_id"] is None
        assert ack.body["payload"]["cancellation_confirmed"] is True
        assert ack.body["payload"]["command_message_id"] == cancel["message_id"]


async def test_cross_owner_submit_rejected_before_mutation(factory):
    submit = message()
    await handle_command(factory, submit)
    attack = {**submit, "message_id": str(uuid4()), "owner_id": str(uuid4())}
    with pytest.raises(ProcessingError):
        await handle_command(factory, attack)
    assert await count(factory, ProcessingInbox) == 1


async def test_claim_source_substitution_rolls_back_and_completion_is_fenced(factory):
    await handle_command(factory, message())
    async with factory() as session:
        work = await session.scalar(
            select(ProcessingOutbox).where(ProcessingOutbox.queue == "processing-work")
        )
        body = work.body
    bad = copy.deepcopy(body)
    bad["source"]["key"] = "another-owner/existing-object"
    with pytest.raises(ValueError):
        await claim(
            factory,
            UUID(body["job_id"]),
            UUID(body["attempt_id"]),
            SETTINGS,
            envelope=bad,
            task_name="source-substitution-test",
        )
    job, attempt = await state(factory)
    assert job.status == attempt.state == "queued"
    claimed = await claim(
        factory, job.id, attempt.id, SETTINGS, envelope=body, task_name="bound-worker"
    )
    assert claimed.source == body["source"]
    assert (
        await claim(factory, job.id, attempt.id, SETTINGS, envelope=body, task_name="bound-worker")
        is None
    )
    stale = SimpleNamespace(job_id=job.id, attempt_id=attempt.id, lease_token=uuid4())
    assert not await finish(factory, stale, error="Processing failed")
    assert await finish(factory, claimed, error="Processing failed")
    assert not await finish(factory, claimed, error="Processing failed")
    job, attempt = await state(factory)
    assert job.status == attempt.state == "failed"
    assert await count(factory, CleanupIntent) == 1
    async with factory() as session:
        saved = await session.get(JobMessaging, job.id)
        assert saved.state_version == 3
        results = (
            await session.scalars(
                select(ProcessingOutbox).where(ProcessingOutbox.queue == "media-results")
            )
        ).all()
        assert sorted(row.body["state_version"] for row in results) == [1, 2, 3]


async def test_lost_send_response_replays_after_commit_outside_locks(factory):
    await handle_command(factory, message())

    async def inspect_send(_queue, _body):
        # NOWAIT proves the publisher released its row lock before network I/O.
        async with factory() as session, session.begin():
            rows = (
                await session.scalars(select(ProcessingOutbox).with_for_update(nowait=True))
            ).all()
            assert rows
        raise TimeoutError("send succeeded but reply was lost")

    lost = SimpleNamespace(send=AsyncMock(side_effect=inspect_send))
    assert await publish_due(factory, ProcessingOutbox, lost, limit=2) == 0
    async with factory() as session, session.begin():
        rows = (await session.scalars(select(ProcessingOutbox))).all()
        for row in rows:
            assert row.sent_at is None
            row.next_try_at = await session.scalar(select(func.clock_timestamp())) - timedelta(
                seconds=1
            )
    successful = SimpleNamespace(send=AsyncMock())
    assert await publish_due(factory, ProcessingOutbox, successful, limit=2) == 2
    assert successful.send.await_count == 2
    assert {call.args[1]["message_id"] for call in successful.send.call_args_list} == {
        call.args[1]["message_id"] for call in lost.send.call_args_list
    }


async def test_sent_work_retention_gap_and_interrupted_lease_repair(factory):
    await handle_command(factory, message())
    transport = SimpleNamespace(send=AsyncMock())
    assert await publish_due(factory, ProcessingOutbox, transport, limit=2) == 2
    job, attempt = await state(factory)
    async with factory() as session, session.begin():
        saved = await session.get(Attempt, attempt.id)
        saved.next_dispatch_at = await session.scalar(select(func.clock_timestamp())) - timedelta(
            days=8
        )
    assert await repair_work(factory) == 1
    assert await repair_work(factory) == 0
    assert await publish_due(factory, ProcessingOutbox, transport, limit=2) == 1
    work = await claim(factory, job.id, attempt.id, SETTINGS, task_name="local-" + uuid4().hex)
    async with factory() as session, session.begin():
        saved = await session.get(Attempt, attempt.id)
        saved.lease_expires_at = await session.scalar(select(func.clock_timestamp())) - timedelta(
            seconds=1
        )
    store = SimpleNamespace(delete_prefix=AsyncMock())
    result = await run_once(factory, SETTINGS, transport, store=store)
    assert result["expired"] == 1
    job, attempt = await state(factory)
    assert job.status == "failed" and attempt.state == "abandoned"
    assert not await finish(factory, work, error="Late completion")


async def test_cleanup_retains_late_write_intent_without_holding_sql_locks(factory):
    await handle_command(factory, message())
    job, attempt = await state(factory)
    work = await claim(factory, job.id, attempt.id, SETTINGS, task_name="local-" + uuid4().hex)
    await finish(factory, work, error="Processing interrupted")

    async def delete(_prefix):
        async with factory() as session, session.begin():
            await session.scalar(select(Job).where(Job.id == job.id).with_for_update(nowait=True))

    store = SimpleNamespace(delete_prefix=AsyncMock(side_effect=delete))
    assert await cleanup_outputs(factory, SETTINGS, store=store) == 1
    assert await count(factory, CleanupIntent) == 1
    async with factory() as session, session.begin():
        intent = await session.get(CleanupIntent, attempt.id)
        intent.next_try_at = await session.scalar(select(func.clock_timestamp())) - timedelta(
            seconds=1
        )
    assert await cleanup_outputs(factory, SETTINGS, store=store) == 1
    assert store.delete_prefix.await_count == 2


async def test_concurrent_duplicate_and_distinct_submit_ids_serialize(factory):
    import asyncio

    body = message()
    assert sorted(
        await asyncio.gather(handle_command(factory, body), handle_command(factory, body))
    ) == [False, True]
    redelivery = {**body, "message_id": str(uuid4())}
    other = {**body, "message_id": str(uuid4())}
    assert await asyncio.gather(handle_command(factory, redelivery), handle_command(factory, other))
    assert await count(factory, Job) == 1
    assert await count(factory, Attempt) == 1
    assert await count(factory, ProcessingInbox) == 3
    assert await count(factory, ProcessingOutbox) == 2


async def test_retry_idempotency_and_cancel_fence_old_and_current_attempts(factory):
    from processing.messaging import retry_job

    submit = message()
    await handle_command(factory, submit)
    job, first = await state(factory)
    old_work = await claim(factory, job.id, first.id, SETTINGS, task_name="local-" + uuid4().hex)
    await finish(factory, old_work, error="Processing interrupted")
    request_id = uuid4()
    async with factory() as session:
        retried = await retry_job(session, job.owner_id, job.id, request_id)
    async with factory() as session:
        repeated = await retry_job(session, job.owner_id, job.id, request_id)
    assert retried["current_attempt"] == repeated["current_attempt"]
    job, current = await state(factory)
    assert current.id != first.id and current.attempt_number == 2
    assert await count(factory, Attempt) == 2
    assert not await finish(factory, old_work, error="Stale worker")
    current_work = await claim(
        factory, job.id, current.id, SETTINGS, task_name="local-" + uuid4().hex
    )
    cancel = {**submit, "message_id": str(uuid4()), "kind": "cancel", "source": None}
    await handle_command(factory, cancel)
    assert not await finish(factory, current_work, error="Cancelled worker")
    job, current = await state(factory)
    assert job.deleted_at is not None and current.state == "cancelled"
    assert await count(factory, CleanupIntent) == 2
    # A later submit with another message ID cannot undo the tombstone.
    await handle_command(factory, {**submit, "message_id": str(uuid4())})
    assert await count(factory, Attempt) == 2


async def test_success_output_namespace_validation_and_atomic_terminal_result(factory):
    await handle_command(factory, message())
    job, attempt = await state(factory)
    work = await claim(factory, job.id, attempt.id, SETTINGS, task_name="local-" + uuid4().hex)
    output = {
        "kind": "primary",
        "object_key": "another-job/primary.mp4",
        "media_type": "video/mp4",
        "size_bytes": 456,
        "sha256": "b" * 64,
    }
    with pytest.raises(ValueError):
        await finish(factory, work, outputs=[output])
    output["object_key"] = f"jobs/{job.id}/attempts/{attempt.id}/primary.mp4"
    assert await finish(factory, work, outputs=[output])
    job, attempt = await state(factory)
    assert job.status == "done" and attempt.state == "succeeded"
    assert job.outputs == [output]
    async with factory() as session:
        results = (
            await session.scalars(
                select(ProcessingOutbox).where(ProcessingOutbox.queue == "media-results")
            )
        ).all()
        latest = max(results, key=lambda row: row.body["state_version"])
        assert latest.body["payload"]["status"] == "done"
        assert latest.body["payload"]["outputs"] == [output]
    # Healthy output has no cleanup authority.
    assert await count(factory, CleanupIntent) == 0


async def test_sql_outbox_to_emulator_work_and_terminal_result(sqs_local, factory):
    from delivery.sqs import SQS, decode

    client, urls = sqs_local
    await handle_command(factory, message())
    sender = SQS(urls, producer="processing", client=client)
    worker = SQS(urls, consumer="encoder", client=client)
    media = SQS(urls, consumer="media-projection", client=client)
    assert await publish_due(factory, ProcessingOutbox, sender, limit=2) == 2
    delivery = (await worker.receive("processing-work", wait_seconds=0))[0]
    body = decode(delivery, "processing-work")
    job, attempt = await state(factory)
    work = await claim(
        factory, job.id, attempt.id, SETTINGS, envelope=body, task_name="bound-worker"
    )
    assert await finish(factory, work, error="Controlled local failure")
    # Only after SQL terminal state/result outbox commit may this receipt be ACKed.
    await worker.delete("processing-work", delivery["ReceiptHandle"])
    assert await publish_due(factory, ProcessingOutbox, sender, limit=2) == 2
    observed = []
    for _ in range(3):
        record = (await media.receive("media-results", wait_seconds=0))[0]
        observed.append(decode(record, "media-results"))
        await media.delete("media-results", record["ReceiptHandle"])
    assert sorted(result["state_version"] for result in observed) == [1, 2, 3]
    terminal = max(observed, key=lambda result: result["state_version"])
    assert terminal["payload"]["status"] == "failed"
    assert terminal["source"] == job.source


async def test_finite_task_binding_persists_and_cannot_claim_second_job(factory):
    from processing.messaging_models import AttemptTask

    first, second = message(), message()
    await handle_command(factory, first)
    await handle_command(factory, second)
    async with factory() as session:
        jobs = (await session.scalars(select(Job).order_by(Job.created_at))).all()
    a, b = jobs
    claimed = await claim(factory, a.id, a.current_attempt_id, SETTINGS, task_name="finite-token")
    async with factory() as session:
        binding = await session.get(AttemptTask, a.current_attempt_id)
        assert binding.task_name == "finite-token"
    await finish(factory, claimed, error="Controlled finish")
    with pytest.raises(ValueError, match="already bound"):
        await claim(factory, b.id, b.current_attempt_id, SETTINGS, task_name="finite-token")
    async with factory() as session:
        saved = await session.get(Job, b.id)
        attempt = await session.get(Attempt, b.current_attempt_id)
        assert saved.status == attempt.state == "queued"
        assert await session.get(AttemptTask, attempt.id) is None
    assert await claim(factory, b.id, b.current_attempt_id, SETTINGS, task_name="second-token")


async def test_new_cancel_after_prior_public_cancel_emits_fresh_cleanup_confirmation(factory):
    from processing.messaging import cancel_asset

    submit = message()
    await handle_command(factory, submit)
    job, _ = await state(factory)
    async with factory() as session:
        await cancel_asset(session, job.owner_id, job.asset_id)
    before = await count(factory, ProcessingOutbox)
    cancel = {**submit, "message_id": str(uuid4()), "kind": "cancel", "source": None}
    assert await handle_command(factory, cancel)
    assert await count(factory, ProcessingOutbox) == before + 1
    async with factory() as session:
        results = (
            await session.scalars(
                select(ProcessingOutbox).where(ProcessingOutbox.queue == "media-results")
            )
        ).all()
        latest = max(results, key=lambda item: item.body["state_version"])
        assert latest.body["payload"]["status"] == "cancelled"
    assert not await handle_command(factory, cancel)
    assert await count(factory, ProcessingOutbox) == before + 1
