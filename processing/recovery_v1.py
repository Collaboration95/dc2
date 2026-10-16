"""Bounded SQL recovery independent of Redis, peer HTTP or unattended starts."""

import asyncio
import os
import time
from datetime import timedelta

from sqlalchemy import or_, select

from delivery.sql import stage
from processing import lifecycle
from processing.messaging import (
    REPAIR_INTERVAL_SECONDS,
    emit_state,
    envelope,
    publish_outbox,
    work_message_id,
)
from processing.messaging_models import AttemptTask, JobMessaging, ProcessingOutbox
from processing.models import Attempt, Job
from processing.recovery import INTERRUPTED, cleanup_outputs, interrupt, recover_expired


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
    """Recreate work even after an acknowledged send, retention gap or lost delete.

    The work message ID is stable per (attempt, state version). A repair therefore
    never grows the outbox: it re-arms the one row for another send and skips while
    that row is still unsent or being published. The look-again interval is fixed and
    short (see REPAIR_INTERVAL_SECONDS): backing off would let a message lost late in
    the backoff wait far past the 120s recovery gate.
    """
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
                .order_by(Attempt.next_dispatch_at.nulls_first(), Attempt.queued_at, Job.id)
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
            row = await session.get(
                ProcessingOutbox,
                work_message_id(attempt.id, saved.state_version),
                with_for_update=True,
            )
            if row is None:
                await stage(
                    session,
                    ProcessingOutbox,
                    envelope(job, attempt, saved.state_version, "work"),
                    "processing-work",
                )
                attempt.dispatch_count += 1
                repaired += 1
            elif row.sent_at is not None and row.claim_token is None:
                # The queue accepted this message earlier; it is missing or too
                # old to trust (retention gap, purge, lost delete). Send it again.
                row.next_try_at = now
                attempt.dispatch_count += 1
                repaired += 1
            # An unsent or in-flight row is the publisher's job; look again later.
            attempt.next_dispatch_at = now + timedelta(seconds=REPAIR_INTERVAL_SECONDS)
    return repaired


async def reemit_result(factory, job_id):
    """Operator action after Media quarantined a result: publish a fresh higher version.

    Media applies by state version, so a snapshot that supersedes the poisoned one
    unfreezes the projection without redriving the original message.
    """
    async with factory() as session, session.begin():
        job = await session.scalar(select(Job).where(Job.id == job_id).with_for_update())
        if job is None:
            return False
        await emit_state(session, job, await session.get(Attempt, job.current_attempt_id))
    return True


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


def stopped_task_names(event):
    """Every name a finite worker may have been bound under for this STOPPED task.

    RunTask names the worker after ``startedBy`` (scripts/aws/v1/session.py batch), which
    ECS echoes in the event. An operator-run task may use its task ARN or ID instead.
    """
    detail = event.get("detail") if isinstance(event, dict) else None
    if not isinstance(detail, dict) or detail.get("lastStatus") != "STOPPED":
        return set()
    arn = detail.get("taskArn")
    names = {detail.get("startedBy"), arn, arn.rsplit("/", 1)[-1] if isinstance(arn, str) else None}
    return {name for name in names if isinstance(name, str) and name}


async def terminal_event(factory, event):
    """A STOPPED task fails the attempt it claimed now, not at lease expiry.

    The binding written at claim time (attempt_tasks) is the only correlation. A task
    that stopped before claiming binds nothing, and an event for an attempt that is no
    longer current finds no live pair, so neither can touch newer work. A duplicate finds
    the attempt already terminal. All three are no-ops; only the same fenced transition
    that lease expiry applies ever runs.
    """
    names = stopped_task_names(event)
    if not names:
        return 0
    async with factory() as session:
        bound = (
            await session.execute(
                select(Attempt.job_id, AttemptTask.attempt_id)
                .join(Attempt, Attempt.id == AttemptTask.attempt_id)
                .where(
                    AttemptTask.task_name.in_(names),
                    Attempt.job_id.in_(select(JobMessaging.job_id)),
                )
            )
        ).all()
    stopped = 0
    for job_id, attempt_id in bound:
        async with factory() as session, session.begin():
            pair = await lifecycle.lock_pair(session, job_id, attempt_id)
            if pair is None:
                continue
            job, attempt = pair
            if job.status != "processing" or attempt.state != "processing":
                continue
            now = await lifecycle.db_now(session)
            await interrupt(session, job, attempt, now, INTERRUPTED, emit_state)
            stopped += 1
    return stopped
