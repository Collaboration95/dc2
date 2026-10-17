"""Retired Redis/RQ recovery: DB-clock expiry, queue repair and output cleanup in one loop.

python -m legacy.processing_rq.recovery [--once]. The expiry and cleanup halves are shared
with V1 and stay in ``processing.recovery``; only the Redis re-enqueue is legacy.
"""

import argparse
import asyncio
import logging
from datetime import timedelta

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from legacy.processing_rq.config import get_settings
from legacy.processing_rq.queue import enqueue_attempt, get_queue
from processing.lifecycle import db_now, lock_pair
from processing.models import Attempt, Job
from processing.recovery import cleanup_outputs, recover_expired

logger = logging.getLogger(__name__)


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
