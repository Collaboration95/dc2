"""Finite V1 encoder: python -m processing.worker.sqs --deadline EPOCH --name TASK.

A task encodes at most one claimed attempt. Messages that durable SQL proves stale
(cancelled, superseded, terminal or already claimed) are deleted and polling goes
on, so leftovers never spend a finite task or cycle to the DLQ. Empty receives,
handled messages and total runtime are bounded. Work arriving later requires
another explicit operator batch.
"""

import argparse
import asyncio
import json
import math
import os
import signal
import tempfile
import time
from contextlib import suppress
from pathlib import Path
from uuid import UUID

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from processing.config import get_settings
from processing.errors import TaskBindingError
from processing.worker.source import SourceStore
from processing.worker.storage import OutputStore
from processing.worker.supervisor import AttemptDeadline, LeaseLost, Supervisor
from processing.worker.tasks import pipeline


def native_sqs(region):
    """Use ECS credentials exclusively, or explicit local emulator credentials."""
    import boto3
    import botocore.session
    from botocore.config import Config
    from botocore.credentials import ContainerProvider

    endpoint = os.environ.get("PROCESSING_SQS_ENDPOINT_URL") or os.environ.get("SQS_ENDPOINT_URL")
    if endpoint:
        # Endpoint overrides are explicitly local, never alternate public accounts.
        from urllib.parse import urlsplit

        if urlsplit(endpoint).hostname not in {"localhost", "127.0.0.1", "moto", "localstack"}:
            raise ValueError("SQS emulator endpoint must be local")
        return boto3.client(
            "sqs",
            region_name=region,
            endpoint_url=endpoint,
            aws_access_key_id="local",
            aws_secret_access_key="local",
            config=Config(connect_timeout=3, read_timeout=25, retries={"total_max_attempts": 1}),
        )
    from processing.storage_credentials import validate_container_environment

    validate_container_environment()
    session = botocore.session.Session()
    credentials = ContainerProvider().load()
    if credentials is None:
        raise ValueError("Native ECS queue credentials unavailable")
    # Install only this provider; do not consult ambient keys, profiles or IMDS.
    session._credentials = credentials
    return boto3.Session(botocore_session=session).client(
        "sqs",
        region_name=region,
        config=Config(connect_timeout=3, read_timeout=25, retries={"total_max_attempts": 1}),
    )


class _Unencoded(str):
    """Falsy like False (nothing was encoded) yet distinguishable by identity."""

    def __bool__(self):
        return False


# Besides True/False, execute_message may report that no attempt was claimed and the
# poll loop should continue: STALE deletes the receipt (durable state proves it
# dead), SKIPPED keeps it for the redrive policy.
STALE = _Unencoded("stale")
SKIPPED = _Unencoded("skipped")


def decode_work(body):
    # Canonical validation is intentionally lazy so legacy engine helpers remain
    # independently importable. The transport receives only versioned V1 work.
    from contracts.v1 import Envelope

    envelope = Envelope.from_dict(json.loads(body)).to_dict()
    if envelope["kind"] != "work" or not envelope["job_id"] or not envelope["attempt_id"]:
        raise ValueError("A bound work envelope is required")
    return envelope


async def execute_message(
    factory,
    envelope,
    settings,
    *,
    renew,
    deadline,
    claim=None,
    finish=None,
    source=None,
    store=None,
    task_name="local",
    disposition=None,
):
    if claim is None or finish is None or disposition is None:
        from processing import messaging

        claim = claim or messaging.claim
        finish = finish or messaging.finish
        disposition = disposition or messaging.work_disposition
    job_id, attempt_id = UUID(envelope["job_id"]), UUID(envelope["attempt_id"])
    # This API atomically validates source/owner/asset/current attempt and the
    # SubmissionGuard fence in the owned database before any native GET.
    try:
        work = await claim(
            factory, job_id, attempt_id, settings, envelope=envelope, task_name=task_name
        )
    except TaskBindingError:
        # A reused task name fails every message, so polling on would only hide it.
        # Keep the receipt and end this task with a failure the operator can see.
        return False
    except ValueError:
        # Identity/source mismatch: never ACK, so the redrive policy quarantines
        # it, but do not let it spend this finite task.
        return SKIPPED
    if work is None:
        # Delete only what durable state proves dead. Anything else stays visible
        # to the redrive policy; SQL repair, not this receipt, recreates work.
        return STALE if await disposition(factory, job_id, attempt_id) == "stale" else SKIPPED
    async with Supervisor(factory, work, settings, renew=renew, deadline=deadline) as supervisor:
        try:
            await supervisor.renew_authority()
            with tempfile.TemporaryDirectory(prefix="processing-v1-") as temporary:
                outputs = await pipeline(
                    work,
                    settings,
                    supervisor,
                    None,
                    store or OutputStore(settings),
                    Path(temporary),
                    downloader=(source or SourceStore(settings)).download,
                )
            # Visibility uncertainty revokes authority before durable completion.
            await supervisor.renew_authority()
            supervisor.check()
            return await finish(factory, work, outputs=outputs)
        except (LeaseLost, asyncio.CancelledError):
            return False
        except AttemptDeadline:
            # An absolute task deadline cannot authorize another database write.
            return False
        except Exception:
            try:
                await supervisor.renew_authority()
                return await finish(
                    factory, work, error="The source or edit could not be processed"
                )
            except (LeaseLost, AttemptDeadline):
                return False


async def run(
    factory,
    settings,
    sqs,
    queue_url,
    *,
    end_epoch,
    name,
    empty_polls=2,
    decode=decode_work,
    execute=execute_message,
    stop=None,
    max_messages=25,
):
    if not math.isfinite(end_epoch) or not 0 < end_epoch - time.time() <= 3600:
        raise ValueError("A future absolute deadline within one hour is required")
    if not name or not 1 <= empty_polls <= 10:
        raise ValueError("Task name and bounded empty polls are required")
    deadline = time.monotonic() + end_epoch - time.time()
    stop = stop or asyncio.Event()
    visibility = max(2, min(240, settings.lease_seconds))

    async def call(method, **kwargs):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise AttemptDeadline()
        return await asyncio.wait_for(asyncio.to_thread(method, **kwargs), remaining)

    empties = handled = 0
    while empties < empty_polls and handled < max_messages:
        if stop.is_set() or deadline - time.monotonic() < 1:
            return 0
        received = await call(
            sqs.receive_message,
            QueueUrl=queue_url,
            MaxNumberOfMessages=1,
            WaitTimeSeconds=min(20, max(0, int(deadline - time.monotonic()) - 1)),
            VisibilityTimeout=visibility,
        )
        if stop.is_set():
            return 0
        messages = received.get("Messages", [])
        if not messages:
            empties += 1
            continue
        handled += 1
        message = messages[0]
        try:
            envelope = decode(message["Body"])
        except (ValueError, KeyError, TypeError):
            # Malformed/conflicting input stays for the redrive policy to quarantine.
            continue

        async def renew(receipt=message["ReceiptHandle"]):
            await call(
                sqs.change_message_visibility,
                QueueUrl=queue_url,
                ReceiptHandle=receipt,
                VisibilityTimeout=visibility,
            )

        complete = await execute(
            factory,
            envelope,
            settings,
            renew=renew,
            deadline=deadline,
            task_name=name,
        )
        if complete is SKIPPED:
            continue
        if complete is STALE or complete:
            await call(
                sqs.delete_message,
                QueueUrl=queue_url,
                ReceiptHandle=message["ReceiptHandle"],
            )
        if complete is STALE:
            continue
        # Exactly one encode per task, successful or uncertain.
        return 0 if complete else 1
    return 0


async def async_main(args):
    settings = get_settings()
    settings.require_storage()
    queue_url = os.environ.get("PROCESSING_WORK_QUEUE_URL") or os.environ.get("WORK_QUEUE_URL")
    if not queue_url:
        raise ValueError("Processing work queue is required")
    from processing.database import v1_connect_args

    engine = create_async_engine(
        settings.postgres_dsn, pool_pre_ping=True, connect_args=v1_connect_args(settings)
    )
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    active = asyncio.current_task()
    # First signal drains the current attempt; second signal revokes it. The
    # external essential-container watchdog enforces the final stop deadline.
    signals = 0

    def shutdown():
        nonlocal signals
        signals += 1
        stop.set()
        if signals > 1:
            active.cancel()

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, shutdown)
    try:
        return await run(
            async_sessionmaker(engine, expire_on_commit=False),
            settings,
            native_sqs(os.environ.get("AWS_REGION", settings.minio_region)),
            queue_url,
            end_epoch=args.deadline,
            name=args.name,
            empty_polls=args.empty_polls,
            stop=stop,
        )
    finally:
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.remove_signal_handler(sig)
        await engine.dispose()


def main():
    parser = argparse.ArgumentParser(description="Finite SQS Processing encoder")
    parser.add_argument("--deadline", type=float, required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("--empty-polls", type=int, default=2)
    args = parser.parse_args()

    # wait_for bounds startup, SDK calls, SQL disposal and the entire attempt.
    async def bounded():
        remaining = args.deadline - time.time()
        if not math.isfinite(remaining) or not 0 < remaining <= 3600:
            return 124
        try:
            return await asyncio.wait_for(async_main(args), remaining)
        except (TimeoutError, AttemptDeadline):
            return 124
        except Exception:
            # Do not emit SDK URLs, queue bodies, credentials or database DSNs.
            return 1

    with suppress(KeyboardInterrupt):
        raise SystemExit(asyncio.run(bounded()))


if __name__ == "__main__":
    main()
