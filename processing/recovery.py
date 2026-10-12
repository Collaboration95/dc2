"""DB-clock interruption recovery, durable queue repair and repeated output cleanup.

python -m processing.recovery [--once]. Retain cleanup intents for the demo
lifetime so a late upload after the first scan is removed on a subsequent scan.
"""

import argparse
import asyncio
import logging
from datetime import timedelta

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from processing.config import get_settings
from processing.lifecycle import cleanup_intent, db_now, lock_pair, output_prefix
from processing.models import Attempt, CleanupIntent, Job
from processing.queue import enqueue_attempt, get_queue
from processing.worker.storage import OutputStore

logger = logging.getLogger(__name__)


async def recover_expired(factory, *, limit=100):
    async with factory() as session:
        ids = (
            await session.execute(
                select(Attempt.job_id, Attempt.id)
                .join(Job, Job.current_attempt_id == Attempt.id)
                .where(
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
            message = (
                "Processing exceeded its time limit"
                if attempt.deadline_at <= now
                else "Processing interrupted; retry the stored source"
            )
            job.status, job.error, job.updated_at = "failed", message, now
            attempt.state, attempt.error, attempt.finished_at = "abandoned", message, now
            attempt.lease_expires_at = now
            await cleanup_intent(session, job_id, attempt_id, now)
            recovered += 1
            logger.info("expired attempt job=%s attempt=%s", job_id, attempt_id)
    return recovered


async def repair_queued(factory, settings, *, queue=None, limit=100):
    async with factory() as session:
        now = await db_now(session)
        ids = (
            await session.execute(
                select(Attempt.job_id, Attempt.id)
                .join(Job, Job.current_attempt_id == Attempt.id)
                .where(
                    Job.deleted_at.is_(None),
                    Job.status == "queued",
                    Attempt.state == "queued",
                    or_(Attempt.next_dispatch_at.is_(None), Attempt.next_dispatch_at <= now),
                )
                .order_by(Attempt.queued_at)
                .limit(limit)
            )
        ).all()
    repaired = 0
    target = queue or get_queue(settings)
    for job_id, attempt_id in ids:
        async with factory() as session, session.begin():
            pair = await lock_pair(session, job_id, attempt_id)
            now = await db_now(session)
            if pair is None:
                continue
            job, attempt = pair
            if (
                job.status != "queued"
                or attempt.state != "queued"
                or (attempt.next_dispatch_at is not None and attempt.next_dispatch_at > now)
            ):
                continue
            attempt.dispatch_count += 1
            try:
                changed = await asyncio.to_thread(enqueue_attempt, job_id, attempt_id, queue=target)
                attempt.dispatch_error = None
                # Every queued record remains discoverable, even a lost delivery
                # whose first enqueue was acknowledged. Cap interval below 2min.
                delay = settings.recovery_interval_seconds
                repaired += int(changed)
            except Exception:
                attempt.dispatch_error = "Queue delivery unavailable"
                delay = min(settings.queue_retry_cap_seconds, 2 ** min(attempt.dispatch_count, 8))
            attempt.next_dispatch_at = now + timedelta(seconds=delay)
    return repaired


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


async def cleanup_outputs(factory, settings, *, store=None, limit=100):
    async with factory() as session:
        now = await db_now(session)
        ids = (
            await session.execute(
                select(CleanupIntent.job_id, CleanupIntent.attempt_id)
                .where(CleanupIntent.next_try_at <= now)
                .limit(limit)
            )
        ).all()
    cleaned = 0
    target = store or CleanupStore(settings)
    for job_id, attempt_id in ids:
        async with factory() as session, session.begin():
            # Lock order matches worker/retry/cancel. Never delete active or
            # winning outputs, even if an erroneous intent has been introduced.
            job = await session.scalar(select(Job).where(Job.id == job_id).with_for_update())
            intent = await session.get(CleanupIntent, attempt_id)
            attempt = await session.get(Attempt, attempt_id)
            now = await db_now(session)
            if intent is None or intent.next_try_at > now:
                continue
            if job.deleted_at is None and (
                attempt.state in {"queued", "processing"}
                or (job.current_attempt_id == attempt_id and job.status == "done")
            ):
                intent.next_try_at = now + timedelta(seconds=60)
                continue
            intent.tries += 1
            try:
                await target.delete_prefix(output_prefix(job_id, attempt_id))
                intent.last_error = None
                cleaned += 1
            except Exception:
                intent.last_error = "Output cleanup unavailable"
            # Intents are never removed after an empty scan: late uploads may arrive.
            intent.next_try_at = now + timedelta(seconds=60)
    return cleaned


async def run_once(factory, settings, *, queue=None, store=None):
    # A Redis outage must not prevent DB interruption detection or S3 cleanup.
    expired = await recover_expired(factory)
    try:
        repaired = await repair_queued(factory, settings, queue=queue)
    except Exception:
        logger.warning("queue repair unavailable")
        repaired = 0
    cleaned = await cleanup_outputs(factory, settings, store=store)
    result = {"expired": expired, "repaired": repaired, "cleaned": cleaned}
    logger.info("recovery pass %s", result)
    return result


async def run(once=False):
    settings = get_settings()
    settings.require_recovery()
    engine = create_async_engine(settings.postgres_dsn, pool_pre_ping=True)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        while True:
            try:
                await run_once(factory, settings)
            except Exception:
                logger.warning("recovery pass unavailable")
                if once:
                    raise RuntimeError("Recovery pass unavailable") from None
            if once:
                return
            await asyncio.sleep(settings.recovery_interval_seconds)
    finally:
        await engine.dispose()


def main():
    parser = argparse.ArgumentParser(description="Processing recovery and cleanup")
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run(args.once))


if __name__ == "__main__":
    main()
