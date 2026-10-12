"""Reserved Attempt UUID delivery; Redis hashes alone are not runnable work."""

import asyncio
import logging
from uuid import UUID

from processing.config import get_settings

TASK = "processing.worker.tasks.process_attempt"
logger = logging.getLogger(__name__)


def get_queue(settings=None):
    from redis import Redis
    from rq import Queue

    settings = settings or get_settings()
    connection = Redis.from_url(
        settings.redis_url.get_secret_value(), socket_connect_timeout=2, socket_timeout=2
    )
    return Queue(
        settings.queue_name,
        connection=connection,
        default_timeout=settings.attempt_timeout_seconds + 30,
    )


def enqueue_attempt(job_id: UUID, attempt_id: UUID, *, queue=None):
    from rq.registry import StartedJobRegistry

    target = queue or get_queue()
    identifier = str(attempt_id)  # RQ forbids colon in custom IDs.
    # Scoped lock serializes API/recovery publication; failed writes remain durable.
    with target.connection.lock(
        f"processing-delivery-{identifier}", timeout=10, blocking_timeout=2
    ):
        if target.connection.lpos(target.key, identifier) is not None:
            return False
        started = StartedJobRegistry(target.name, connection=target.connection)
        if identifier in started.get_job_ids(cleanup=False):
            return False
        # Recreate reserved payload even when a surviving hash reports queued/failed.
        # Never trust that hash as proof of list/started-registry membership.
        task = target.create_job(
            TASK,
            args=(str(job_id), str(attempt_id)),
            job_id=identifier,
            timeout=target.default_timeout,
            result_ttl=3600,
            failure_ttl=3600,
        )
        target.enqueue_job(task)
        return True


async def publish(job):
    if job.status != "queued":
        return
    settings = get_settings()
    if not settings.redis_url.get_secret_value():
        return
    try:
        await asyncio.to_thread(enqueue_attempt, job.job_id, job.current_attempt.attempt_id)
    except Exception:
        logger.warning(
            "queue delivery pending job=%s attempt=%s", job.job_id, job.current_attempt.attempt_id
        )
