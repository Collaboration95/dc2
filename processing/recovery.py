"""DB-clock interruption recovery and repeated output cleanup.

V1 runs these from ``processing.recovery_v1`` on a schedule. Retain cleanup intents for the
demo lifetime so a late upload after the first scan is removed on a subsequent scan. Queue
repair for the retired Redis/RQ stack lives in ``legacy.processing_rq.recovery``.
"""

import asyncio
import logging
from datetime import timedelta

from sqlalchemy import or_, select

from processing.lifecycle import cleanup_intent, db_now, lock_pair, output_prefix
from processing.models import Attempt, CleanupIntent, Job
from processing.worker.storage import OutputStore

logger = logging.getLogger(__name__)


INTERRUPTED = "Processing interrupted; retry the stored source"


async def interrupt(session, job, attempt, now, message, on_change=None):
    """The one fenced failure transition for a processing attempt that can no longer finish.

    Caller holds the Job lock and has verified the attempt is current and processing.
    Lease expiry and an ECS STOPPED event both end here, so they cannot diverge. There is
    no automatic requeue: a retry reserves a new attempt (the owner asks for it), and the
    one-task-per-attempt binding would reject a second claim of this one anyway.
    """
    job.status, job.error, job.updated_at = "failed", message, now
    attempt.state, attempt.error, attempt.finished_at = "abandoned", message, now
    attempt.lease_expires_at = now
    await cleanup_intent(session, job.id, attempt.id, now)
    if on_change is not None:
        await on_change(session, job, attempt)


async def recover_expired(factory, *, limit=100, on_change=None, job_filter=None):
    async with factory() as session:
        ids = (
            await session.execute(
                select(Attempt.job_id, Attempt.id)
                .join(Job, Job.current_attempt_id == Attempt.id)
                .where(
                    job_filter if job_filter is not None else True,
                    Job.deleted_at.is_(None),
                    Job.status == "processing",
                    Attempt.state == "processing",
                    or_(
                        Attempt.lease_expires_at <= await db_now(session),
                        Attempt.deadline_at <= await db_now(session),
                    ),
                )
                .limit(limit)
            )
        ).all()
    recovered = 0
    for job_id, attempt_id in ids:
        async with factory() as session, session.begin():
            pair = await lock_pair(session, job_id, attempt_id)
            now = await db_now(session)
            if pair is None:
                continue
            job, attempt = pair
            if (
                job.status != "processing"
                or attempt.state != "processing"
                or (attempt.lease_expires_at > now and attempt.deadline_at > now)
            ):
                continue
            await interrupt(
                session,
                job,
                attempt,
                now,
                "Processing exceeded its time limit"
                if attempt.deadline_at <= now
                else INTERRUPTED,
                on_change,
            )
            recovered += 1
            logger.info("expired attempt job=%s attempt=%s", job_id, attempt_id)
    return recovered


class CleanupStore(OutputStore):
    # Entry point receives cleanup principal through the same PROCESSING_MINIO_*
    # fields. These methods require only output List/Delete, never Get or HEAD.
    async def delete_prefix(self, prefix):
        from minio.deleteobjects import DeleteObject

        def remove():
            objects = self.client.list_objects(self.bucket, prefix=prefix, recursive=True)
            errors = self.client.remove_objects(
                self.bucket, (DeleteObject(item.object_name) for item in objects)
            )
            if next(iter(errors), None) is not None:
                raise ValueError("output cleanup was not acknowledged")

        await asyncio.to_thread(remove)


CLEANUP_BASE_SECONDS = 60
CLEANUP_CAP_SECONDS = 3600
CLEANUP_HORIZON_SECONDS = 86400


def cleanup_delay(tries):
    """Early rescans catch the likely late write; later ones thin out to hourly."""
    return min(CLEANUP_CAP_SECONDS, CLEANUP_BASE_SECONDS * 2 ** min(max(tries - 1, 0), 6))


async def cleanup_outputs(
    factory, settings, *, store=None, limit=100, horizon_seconds=CLEANUP_HORIZON_SECONDS
):
    async with factory() as session:
        now = await db_now(session)
        ids = (
            await session.execute(
                select(CleanupIntent.job_id, CleanupIntent.attempt_id)
                .where(CleanupIntent.next_try_at <= now, CleanupIntent.retired_at.is_(None))
                .order_by(CleanupIntent.next_try_at, CleanupIntent.attempt_id)
                .limit(limit)
            )
        ).all()
    cleaned = 0
    target = store or CleanupStore(settings)
    for job_id, attempt_id in ids:
        async with factory() as session, session.begin():
            # Lock order matches worker/retry/cancel. Terminal attempts are never
            # reactivated: retries reserve a new UUID; deletion is irreversible.
            job = await session.scalar(select(Job).where(Job.id == job_id).with_for_update())
            attempt = await session.get(Attempt, attempt_id)
            intent = await session.get(CleanupIntent, attempt_id, with_for_update=True)
            now = await db_now(session)
            if (
                job is None
                or attempt is None
                or attempt.job_id != job_id
                or intent is None
                or intent.job_id != job_id
                or intent.retired_at is not None
                or intent.next_try_at > now
            ):
                continue
            if attempt.state not in {"failed", "abandoned", "cancelled", "succeeded"} or (
                job.deleted_at is None
                and (
                    attempt.state == "succeeded"
                    or (job.current_attempt_id == attempt_id and job.status == "done")
                )
            ):
                intent.next_try_at = now + timedelta(seconds=CLEANUP_BASE_SECONDS)
                continue
            intent.tries += 1
            # Reserve this scan durably before releasing every Job/Attempt lock.
            # A crash/cancellation still leaves an intent due for another scan.
            intent.next_try_at = now + timedelta(seconds=60)
            scan_try, scan_due = intent.tries, intent.next_try_at

        # No SQL session or transaction spans object listing/deletion. A healthy
        # current retry must be free to heartbeat and publish throughout this I/O.
        error = None
        try:
            await target.delete_prefix(output_prefix(job_id, attempt_id))
            cleaned += 1
        except Exception:
            error = "Output cleanup unavailable"

        async with factory() as session, session.begin():
            intent = await session.get(CleanupIntent, attempt_id, with_for_update=True)
            if (
                intent is not None
                and intent.job_id == job_id
                and intent.tries == scan_try
                and intent.next_try_at == scan_due
            ):
                # Fence late scan results against a newer reservation/reschedule.
                # Never change Job/Attempt state with the released authority.
                intent.last_error = error
                now = await db_now(session)
                # Retain even empty scans to catch later uploads, with growing gaps,
                # until a clean scan lands past the horizon. Errors never retire.
                intent.next_try_at = now + timedelta(seconds=cleanup_delay(intent.tries))
                if error is None and (now - intent.created_at).total_seconds() >= horizon_seconds:
                    intent.retired_at = now
    return cleaned
