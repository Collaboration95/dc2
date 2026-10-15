"""Bounded SQL recovery independent of Redis, peer HTTP or unattended starts."""

import asyncio
import os
import time
from datetime import timedelta

from sqlalchemy import or_, select

from delivery.sql import stage
from processing import lifecycle
from processing.messaging import emit_state, envelope, publish_outbox
from processing.messaging_models import JobMessaging, ProcessingOutbox
from processing.models import Attempt, Job
from processing.recovery import cleanup_outputs, recover_expired


class NativeCleanupStore:
    """Native Lambda S3 List/Delete only, including overwritten private versions."""

    def __init__(self, settings, *, client=None):
        self.bucket = settings.minio_output_bucket
        if client is None:
            import boto3
            from botocore.config import Config

            endpoint = os.environ.get("PROCESSING_S3_ENDPOINT_URL") or os.environ.get(
                "S3_ENDPOINT_URL"
            )
            if endpoint:
                from urllib.parse import urlsplit

                if urlsplit(endpoint).hostname not in {
                    "localhost",
                    "127.0.0.1",
                    "moto",
                    "localstack",
                }:
                    raise ValueError("S3 emulator endpoint must be local")
            client = boto3.client(
                "s3",
                region_name=settings.minio_region,
                endpoint_url=endpoint,
                config=Config(
                    connect_timeout=2,
                    read_timeout=5,
                    retries={"total_max_attempts": 2, "mode": "standard"},
                ),
            )
        self.client = client

    async def delete_prefix(self, prefix):
        # Prefix comes only from Processing's persisted Job/Attempt UUID pair.
        if not prefix.startswith("jobs/") or not prefix.endswith("/"):
            raise ValueError("Owned attempt prefix required")
        paginator = self.client.get_paginator("list_object_versions")
        pages = paginator.paginate(Bucket=self.bucket, Prefix=prefix)
        iterator = iter(pages)
        while True:
            page = await asyncio.to_thread(next, iterator, None)
            if page is None:
                break
            objects = [
                {"Key": item["Key"], "VersionId": item["VersionId"]}
                for item in page.get("Versions", []) + page.get("DeleteMarkers", [])
            ]
            for offset in range(0, len(objects), 1000):
                response = await asyncio.to_thread(
                    self.client.delete_objects,
                    Bucket=self.bucket,
                    Delete={"Objects": objects[offset : offset + 1000], "Quiet": True},
                )
                if response.get("Errors"):
                    raise ValueError("Output version cleanup was not acknowledged")


async def repair_work(factory, *, limit=50, deadline=None):
    """Recreate work even after an acknowledged send, retention gap or lost delete."""
    async with factory() as session:
        now = await lifecycle.db_now(session)
        ids = (
            await session.execute(
                select(Job.id, Attempt.id)
                .join(Attempt, Job.current_attempt_id == Attempt.id)
                .join(JobMessaging, JobMessaging.job_id == Job.id)
                .where(
                    Job.deleted_at.is_(None),
                    Job.status == "queued",
                    Attempt.state == "queued",
                    or_(Attempt.next_dispatch_at.is_(None), Attempt.next_dispatch_at <= now),
                )
                .order_by(Attempt.queued_at, Job.id)
                .limit(limit)
            )
        ).all()
    repaired = 0
    for job_id, attempt_id in ids:
        if deadline is not None and time.monotonic() >= deadline:
            break
        async with factory() as session, session.begin():
            pair = await lifecycle.lock_pair(session, job_id, attempt_id)
            now = await lifecycle.db_now(session)
            if pair is None:
                continue
            job, attempt = pair
            if (
                job.status != "queued"
                or attempt.state != "queued"
                or (attempt.next_dispatch_at is not None and attempt.next_dispatch_at > now)
            ):
                continue
            saved = await session.get(JobMessaging, job.id)
            await stage(
                session,
                ProcessingOutbox,
                envelope(job, attempt, saved.state_version, "work"),
                "processing-work",
            )
            attempt.next_dispatch_at = now + timedelta(seconds=60)
            repaired += 1
    return repaired


async def run_once(factory, settings, transport, *, store=None, limit=25, deadline=None):
    """Invocation deadline cancels I/O; durable reservations ensure continuation.

    The session-scoped repair schedule invokes this again while open. A close
    disables that schedule, but never deletes SQL recovery/cleanup state.
    """
    deadline = deadline if deadline is not None else time.monotonic() + 20
    result = {
        "expired": 0,
        "repaired": 0,
        "published": 0,
        "cleaned": 0,
        "continuation_required": True,
    }
    try:
        async with asyncio.timeout(max(0.001, deadline - time.monotonic())):
            # Expiry is SQL-only and does not depend on queue availability.
            result["expired"] = await recover_expired(
                factory,
                limit=limit,
                on_change=emit_state,
                job_filter=Job.id.in_(select(JobMessaging.job_id)),
            )
            result["repaired"] = await repair_work(factory, limit=limit, deadline=deadline)
            # Reserve time for repeated late-output cleanup even on queue outage.
            publish_deadline = min(deadline, time.monotonic() + 5)
            result["published"] = await publish_outbox(
                factory, transport, limit=limit, deadline=publish_deadline
            )
            result["cleaned"] = await cleanup_outputs(
                factory, settings, store=store or NativeCleanupStore(settings), limit=limit
            )
    except TimeoutError:
        result["deadline_reached"] = True
    return result


async def terminal_event(factory, event):
    """An ECS notification is a repair hint, never authority to fail a live lease.

    No worker task ID can revoke another attempt. The SQL expiry/deadline fence
    decides interruption; duplicated/reordered STOPPED events are harmless.
    """
    if event.get("detail", {}).get("lastStatus") != "STOPPED":
        return 0
    return await recover_expired(
        factory,
        limit=25,
        on_change=emit_state,
        job_filter=Job.id.in_(select(JobMessaging.job_id)),
    )
