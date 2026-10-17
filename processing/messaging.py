"""Processing command inbox, fenced lifecycle and result/work outboxes.

Legacy HTTP/RQ adapters keep their own entrypoints. V1 uses these exports, with
native immutable S3 descriptors stored on the owned Job before any worker GET.
"""

from datetime import timedelta
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from pydantic import TypeAdapter
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from delivery.envelope import document, fingerprint
from delivery.sql import accept, publish_due, stage
from processing import lifecycle, short_lane
from processing.errors import ProcessingError, TaskBindingError
from processing.messaging_models import AttemptTask, JobMessaging, ProcessingInbox, ProcessingOutbox
from processing.models import Attempt, Job, RetryRequest, SubmissionGuard
from processing.schemas import EditOperation

# Media writes accepted sources under one of these owner-scoped prefixes. A queue
# message naming any other key is rejected before it can reach a native S3 GET.
SOURCE_PREFIXES = ("sources", "staging")
# Lost-work repair must finish inside the 120s recovery gate while a session is open.
# A message can vanish right after a send, so the worst case is one full interval plus
# one wait for the next repair tick plus scheduling delay. The interval is therefore
# constant and sized from the gate: it never backs off. (Work that is deleted or terminal
# is not selected at all, so nothing needs a long backoff to be retired.) The cost of
# this is one duplicate work message per idle queued attempt per interval, which an encoder
# drops once the attempt is claimed; closing the session disables the repair schedule.
LOST_WORK_GATE_SECONDS = 120
REPAIR_TICK_SECONDS = 60  # the repair rule's `rate(1 minute)`; a test ties the two together
REPAIR_SCHEDULING_SLACK_SECONDS = 15  # EventBridge delivery plus Lambda start-up
REPAIR_INTERVAL_SECONDS = (
    LOST_WORK_GATE_SECONDS - REPAIR_TICK_SECONDS - REPAIR_SCHEDULING_SLACK_SECONDS
)
TERMINAL_ATTEMPTS = {"succeeded", "failed", "abandoned", "cancelled"}


def work_message_id(attempt_id, version):
    """Stable per (attempt, state version): a repair re-sends rather than re-stages."""
    return uuid5(NAMESPACE_URL, f"processing/work/{attempt_id}/{version}")


def assert_owned_source(body):
    source = body.get("source")
    if source is None:
        return
    key = source["key"]
    if (
        "\\" in key
        or ".." in key.split("/")
        or not any(key.startswith(f"{prefix}/{body['owner_id']}/") for prefix in SOURCE_PREFIXES)
    ):
        raise ValueError("Source is outside the owner's prefix")


def snapshot(job, attempt, version):
    return {
        "job_id": str(job.id),
        "asset_id": str(job.asset_id),
        "owner_id": str(job.owner_id),
        "status": "cancelled" if job.deleted_at else job.status,
        "source": job.source,
        "outputs": job.outputs or [],
        "error": job.error,
        "state_version": version,
        "current_attempt": {
            "attempt_id": str(attempt.id),
            "number": attempt.attempt_number,
            "state": attempt.state,
        },
    }


def envelope(job, attempt, version, kind):
    return {
        "schema_version": 1,
        "message_id": str(work_message_id(attempt.id, version) if kind == "work" else uuid4()),
        "kind": kind,
        "owner_id": str(job.owner_id),
        "asset_id": str(job.asset_id),
        "job_id": str(job.id),
        "attempt_id": str(attempt.id),
        "state_version": version,
        "source": job.source,
        "payload": (
            {"operations": job.operations}
            if kind == "work"
            else {
                "status": "cancelled" if job.deleted_at else job.status,
                "outputs": job.outputs or [],
                "error": job.error,
                "attempt_number": attempt.attempt_number,
            }
        ),
    }


async def emit_state(session, job, attempt):
    # All callers already hold the owning Job lock (or just inserted that Job).
    saved = await session.get(JobMessaging, job.id)
    if saved is None:
        saved = JobMessaging(job_id=job.id, state_version=0)
        session.add(saved)
    saved.state_version += 1
    await stage(
        session,
        ProcessingOutbox,
        envelope(job, attempt, saved.state_version, "result"),
        "media-results",
    )
    if job.deleted_at is None and job.status == "queued" and attempt.state == "queued":
        await stage(
            session,
            ProcessingOutbox,
            envelope(job, attempt, saved.state_version, "work"),
            # The standard lane unless the opt-in short lane admits this job (V2, #93).
            await short_lane.work_lane(session, job),
        )
        # The send itself is the first delivery; repair only needs to look again
        # after one period, not on the very next tick.
        attempt.next_dispatch_at = await lifecycle.db_now(session) + timedelta(
            seconds=REPAIR_INTERVAL_SECONDS
        )
    return saved.state_version


async def _guard(session, owner_id, asset_id):
    await session.execute(
        insert(SubmissionGuard)
        .values(asset_id=asset_id, owner_id=owner_id)
        .on_conflict_do_nothing(index_elements=[SubmissionGuard.asset_id])
    )
    guard = await session.scalar(
        select(SubmissionGuard).where(SubmissionGuard.asset_id == asset_id).with_for_update()
    )
    if guard.owner_id != owner_id:
        raise ProcessingError(404, "Job not found")
    return guard


def validate_identity(body, job, *, require_source=False):
    if (
        UUID(body["owner_id"]) != job.owner_id
        or UUID(body["asset_id"]) != job.asset_id
        or (body.get("job_id") and UUID(body["job_id"]) != job.id)
        or ((require_source or body.get("source") is not None) and body.get("source") != job.source)
    ):
        raise ValueError("Message does not match the durable owned job")


async def _retry_locked(session, job, request_id):
    if job.deleted_at is not None:
        raise ProcessingError(410, "Asset processing is deleted")
    attempt = await session.get(Attempt, job.current_attempt_id)
    replay = await session.scalar(
        select(RetryRequest).where(
            RetryRequest.job_id == job.id, RetryRequest.request_id == request_id
        )
    )
    if replay is not None:
        return attempt
    if job.status != "failed":
        raise ProcessingError(409, "Only failed jobs can be retried")
    now = await lifecycle.db_now(session)
    await lifecycle.cleanup_intent(session, job.id, attempt.id, now)
    attempt = Attempt(
        id=uuid4(),
        job_id=job.id,
        attempt_number=attempt.attempt_number + 1,
        state="queued",
        queued_at=now,
    )
    session.add(attempt)
    await session.flush()
    session.add(RetryRequest(job_id=job.id, request_id=request_id, attempt_id=attempt.id))
    job.current_attempt_id = attempt.id
    job.status, job.error, job.outputs, job.updated_at = "queued", None, [], now
    await emit_state(session, job, attempt)
    return attempt


async def _cancel_locked(session, guard, *, command_message_id=None):
    now = await lifecycle.db_now(session)
    was_deleted = guard.deleted_at is not None
    guard.deleted_at = guard.deleted_at or now
    if guard.job_id is None:
        if command_message_id is not None:
            await stage(
                session,
                ProcessingOutbox,
                {
                    "schema_version": 1,
                    "message_id": str(uuid4()),
                    "kind": "result",
                    "owner_id": str(guard.owner_id),
                    "asset_id": str(guard.asset_id),
                    "job_id": None,
                    "attempt_id": None,
                    "state_version": 0,
                    "source": None,
                    "payload": {
                        "status": "cancelled",
                        "cancellation_confirmed": True,
                        "command_message_id": str(command_message_id),
                    },
                },
                "media-results",
            )
        return
    job = await session.scalar(select(Job).where(Job.id == guard.job_id).with_for_update())
    if was_deleted and job.deleted_at is not None:
        # A new cancel command can follow a public Processing cancellation. Its
        # fresh result must confirm Media cleanup promptly, even if the earlier
        # result was already consumed before Media tombstoned the asset.
        if command_message_id is not None:
            await emit_state(session, job, await session.get(Attempt, job.current_attempt_id))
        return
    job.deleted_at = job.deleted_at or now
    job.outputs, job.updated_at = [], now
    attempts = (await session.scalars(select(Attempt).where(Attempt.job_id == job.id))).all()
    for attempt in attempts:
        if attempt.state in {"queued", "processing"}:
            attempt.state, attempt.finished_at, attempt.lease_expires_at = "cancelled", now, now
        await lifecycle.cleanup_intent(session, job.id, attempt.id, now)
    await emit_state(session, job, await session.get(Attempt, job.current_attempt_id))


async def handle_command(factory, message):
    body = document(message)
    if body["kind"] not in {"submit", "retry", "cancel"}:
        raise ValueError("Processing control accepts commands only")
    assert_owned_source(body)
    owner_id, asset_id = UUID(body["owner_id"]), UUID(body["asset_id"])
    async with factory() as session, session.begin():
        if not await accept(session, ProcessingInbox, body):
            return False
        guard = await _guard(session, owner_id, asset_id)
        if body["kind"] == "cancel":
            if guard.job_id is not None:
                job = await session.get(Job, guard.job_id)
                validate_identity(body, job)
            await _cancel_locked(session, guard, command_message_id=body["message_id"])
            return True
        # Cancel-before-submit is a durable accepted no-op, never resurrection.
        if guard.deleted_at is not None:
            return True
        job = None
        if guard.job_id is not None:
            job = await session.scalar(select(Job).where(Job.id == guard.job_id).with_for_update())
            validate_identity(body, job)
        if body["kind"] == "retry":
            if job is None:
                # Roll back inbox so a reordered retry may succeed after submit.
                raise ProcessingError(409, "Submission has not arrived")
            await _retry_locked(
                session, job, UUID(body["payload"].get("request_id") or body["message_id"])
            )
            return True
        operations = TypeAdapter(list[EditOperation]).validate_python(
            body["payload"].get("operations", [])
        )
        operations = [item.model_dump(mode="json") for item in operations]
        names = [item["operation"] for item in operations]
        if (
            len(names) > 5
            or len(names) != len(set(names))
            or {"upscale", "downscale"} <= set(names)
        ):
            raise ValueError("Invalid edit operations")
        digest = fingerprint({"source": body["source"], "operations": operations})
        if job is not None:
            if job.request_hash != digest:
                raise ProcessingError(409, "Asset already has a different processing request")
            return True
        now = await lifecycle.db_now(session)
        job_id, attempt_id = UUID(body["job_id"]) if body.get("job_id") else uuid4(), uuid4()
        job = Job(
            id=job_id,
            asset_id=asset_id,
            owner_id=owner_id,
            source=body["source"],
            operations=operations,
            request_hash=digest,
            source_url="",
            source_url_expires_at=now,
            status="queued",
            current_attempt_id=attempt_id,
            outputs=[],
            created_at=now,
            updated_at=now,
        )
        session.add(job)
        await session.flush()
        attempt = Attempt(
            id=attempt_id, job_id=job_id, attempt_number=1, state="queued", queued_at=now
        )
        session.add(attempt)
        guard.job_id = job_id
        await session.flush()
        await emit_state(session, job, attempt)
    return True


async def retry_job(session, owner_id, job_id, request_id):
    async with session.begin():
        job = await session.scalar(select(Job).where(Job.id == job_id).with_for_update())
        if job is None or job.owner_id != owner_id:
            raise ProcessingError(404, "Job not found")
        attempt = await _retry_locked(session, job, request_id)
        state = await session.get(JobMessaging, job.id)
        result = snapshot(job, attempt, state.state_version)
    return result


async def cancel_asset(session, owner_id, asset_id):
    async with session.begin():
        guard = await _guard(session, owner_id, asset_id)
        await _cancel_locked(session, guard)


async def claim(factory, job_id, attempt_id, settings, *, envelope=None, task_name):
    if (
        not isinstance(task_name, str)
        or not task_name
        or len(task_name) > 256
        or any(ord(char) < 32 for char in task_name)
    ):
        raise TaskBindingError("A finite worker task binding is required")
    body = document(envelope) if envelope is not None else None
    if body is not None:
        assert_owned_source(body)

    async def authorize(session):
        # Resolve immutable routing columns first, then match cancel/submit's
        # Guard -> Job lock order. No native GET is possible before this commits.
        identity = (
            await session.execute(select(Job.asset_id, Job.owner_id).where(Job.id == job_id))
        ).one_or_none()
        if identity is None:
            return False
        asset_id, owner_id = identity
        guard = await session.scalar(
            select(SubmissionGuard).where(SubmissionGuard.asset_id == asset_id).with_for_update()
        )
        return (
            guard is not None
            and guard.deleted_at is None
            and guard.owner_id == owner_id
            and guard.job_id == job_id
        )

    async def changed(session, job, attempt):
        if body is not None:
            if body["kind"] != "work" or UUID(body["attempt_id"]) != attempt.id:
                raise ValueError("Work attempt does not match")
            validate_identity(body, job, require_source=True)
            if body["payload"].get("operations", []) != job.operations:
                raise ValueError("Work operations do not match durable command")
        inserted = await session.scalar(
            insert(AttemptTask)
            .values(attempt_id=attempt.id, task_name=task_name)
            .on_conflict_do_nothing()
            .returning(AttemptTask.attempt_id)
        )
        if inserted is None:
            binding = await session.get(AttemptTask, attempt.id)
            if binding is None or binding.task_name != task_name:
                raise TaskBindingError("Finite task or attempt already bound")
        await emit_state(session, job, attempt)

    return await lifecycle.claim(
        factory, job_id, attempt_id, settings, on_change=changed, before_claim=authorize
    )


async def work_disposition(factory, job_id, attempt_id):
    """Return "stale" only when durable state proves this attempt can never be claimed.

    A claim that returned None is not proof by itself (it also covers a missing
    guard or transient mismatch). Unknown rows are left for the redrive policy.
    """
    async with factory() as session:
        job = await session.get(Job, job_id)
        attempt = await session.get(Attempt, attempt_id)
        if job is None or attempt is None or attempt.job_id != job.id:
            return "unknown"
        guard = await session.get(SubmissionGuard, job.asset_id)
        if (
            job.deleted_at is not None
            or (guard is not None and guard.deleted_at is not None)
            or job.current_attempt_id != attempt_id
            or attempt.state != "queued"
        ):
            # Cancelled, superseded, terminal, or already claimed. Recovery fails an
            # abandoned claim and a retry publishes its own work, so this receipt
            # carries no further obligation.
            return "stale"
        return "pending"


async def finish(factory, work, *, outputs=None, error=None):
    return await lifecycle.finish(factory, work, outputs=outputs, error=error, on_change=emit_state)


REDIRECTED = "Redirected to the standard encoder lane"


async def redirect_to_long_lane(factory, work):
    """Hand a claimed attempt the short lane cannot finish to the standard (Fargate) lane.

    Fenced exactly like finish: only the live lease holder may apply it, so a stale or timed-out
    invocation changes nothing. The claimed attempt ends as abandoned and a new queued attempt
    takes over, the same shape as a retry. A new attempt is needed because the one-task-per-
    attempt binding rejects a second executor on the old one. The binding also marks the job as
    having run on Lambda, which is what routes the new attempt to the standard lane.
    """
    async with factory() as session, session.begin():
        pair = await lifecycle.lock_pair(session, work.job_id, work.attempt_id)
        now = await lifecycle.db_now(session)
        if not lifecycle.live(pair, work.lease_token, now):
            return False
        job, attempt = pair
        attempt.state, attempt.error, attempt.finished_at = "abandoned", REDIRECTED, now
        attempt.lease_expires_at = now
        # Nothing was uploaded yet, but the late-output rescan is cheap and uniform.
        await lifecycle.cleanup_intent(session, job.id, attempt.id, now)
        successor = Attempt(
            id=uuid4(),
            job_id=job.id,
            attempt_number=attempt.attempt_number + 1,
            state="queued",
            queued_at=now,
        )
        session.add(successor)
        await session.flush()
        job.current_attempt_id = successor.id
        job.status, job.error, job.outputs, job.updated_at = "queued", None, [], now
        await emit_state(session, job, successor)
        return True


async def publish_outbox(factory, transport, **kwargs):
    return await publish_due(factory, ProcessingOutbox, transport, **kwargs)


async def consume_commands(event, factory, *, guard=None):
    """``guard`` returns a context manager around each message (credential self-heal)."""
    from contextlib import nullcontext

    from delivery.sqs import consume_batch

    async def handle(body):
        with (guard or nullcontext)():
            return await handle_command(factory, body)

    return await consume_batch(event, "processing-commands", handle)
