"""Lambda executor for the opt-in short lane (V2, #93): one fenced attempt per invocation.

This is the Fargate encoder's message path (``processing.worker.sqs.execute_message``) with a
different outer loop, not a second implementation. The SQL claim, the heartbeat, the lease and
deadline fences, the output prefix, the pure FFmpeg pipeline and the fenced finish are the same
objects. What differs is only what Lambda forces:

* the deadline comes from the invocation (``PIPELINE_DEADLINE_SECONDS`` or less, always with
  ``HEADROOM_SECONDS`` left before the function timeout), not from a task-lifetime argument;
* the message lifetime belongs to the event source mapping, so there is no visibility renewal;
* the executor name is ``lambda-<request id>``: the existing one-task-per-attempt binding then
  identifies the executor, and a redelivered message finds the attempt already claimed;
* after the probe, a source over the duration or height bound is handed to the standard lane.

A timeout or crash mid-encode needs no code here: the heartbeat stops, ``recover_expired`` ends
the attempt through the same fenced transition as for Fargate, its cleanup intent removes any
late output, and a redelivered message finds the attempt claimed and is acknowledged as stale.
"""

import asyncio
import json
import logging
import time

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from processing import messaging, short_lane
from processing.config import get_settings
from processing.database import v1_connect_args
from processing.worker import sqs as worker
from runtime_support.settings import heal_on_rejection

logger = logging.getLogger("dc2.short_encoder")
logger.setLevel(logging.INFO)

# Below this there is no point claiming: a claim that cannot finish only wastes an attempt.
MIN_BUDGET_SECONDS = 60
# Last-resort bound on the whole invocation; the pipeline deadline normally ends it earlier.
FINAL_GRACE_SECONDS = 30

_invocations = 0  # a warm execution environment keeps this value; a cold one starts at zero


def remaining_seconds(context):
    millis = getattr(context, "get_remaining_time_in_millis", None)
    return millis() / 1000 if callable(millis) else short_lane.LAMBDA_TIMEOUT_SECONDS


def _line(**fields):
    # Ids and numbers only: no URL, DSN, key or token ever reaches this line.
    logger.info("dc2.short_encode %s", json.dumps(fields, sort_keys=True))


async def encode_record(
    record, context, *, factory, settings, source=None, store=None, clock=time.monotonic, hooks=None
):
    """Run one SQS record. Returns (outcome, acknowledge).

    ``hooks`` is a test seam for execute_message's claim/finish/disposition; production passes none.
    """
    try:
        envelope = worker.decode_work(record["body"])
    except (ValueError, KeyError, TypeError):
        return "malformed", False  # left for the redrive policy, as for Fargate
    budget = min(
        remaining_seconds(context) - short_lane.HEADROOM_SECONDS,
        short_lane.PIPELINE_DEADLINE_SECONDS,
    )
    if budget < MIN_BUDGET_SECONDS:
        return "no_time", False
    # The durable deadline must not outlive the invocation that owns the attempt.
    bounded = settings.model_copy(
        update={"attempt_timeout_seconds": min(settings.attempt_timeout_seconds, int(budget))}
    )
    redirected = []

    async def redirect(factory, work):
        done = await messaging.redirect_to_long_lane(factory, work)
        redirected.append(done)
        return done

    result = await worker.execute_message(
        factory,
        envelope,
        bounded,
        renew=None,
        deadline=clock() + budget,
        task_name=short_lane.executor_name(getattr(context, "aws_request_id", None) or "local"),
        source=source,
        store=store,
        admit=short_lane.check_probe,
        redirect=redirect,
        **(hooks or {}),
    )
    if result is worker.STALE:
        return "stale", True
    if result is worker.SKIPPED:
        return "skipped", False
    if not result:
        return "lost", False
    return ("redirected" if redirected else "finished"), True


async def invoke(
    event,
    context,
    *,
    factory=None,
    settings=None,
    source=None,
    store=None,
    clock=time.monotonic,
    hooks=None,
):
    """SQS partial-batch response. One encode per invocation, whatever BatchSize says."""
    global _invocations
    cold, _invocations = _invocations == 0, _invocations + 1
    records = event.get("Records") or []
    # BatchSize is 1; a second record would share this invocation's deadline, so it goes back.
    failures = [{"itemIdentifier": r["messageId"]} for r in records[1:]]
    if not records:
        return {"batchItemFailures": failures}
    record, started = records[0], clock()
    engine = None
    if factory is None:
        settings = settings or get_settings()
        settings.require_storage()
        # A pool that lives and dies inside this invocation: no connection crosses a freeze.
        engine = create_async_engine(
            settings.postgres_dsn,
            pool_size=2,
            max_overflow=1,
            pool_pre_ping=True,
            connect_args=v1_connect_args(settings),
        )
        factory = async_sessionmaker(engine, expire_on_commit=False)
    outcome, acknowledge = "error", False
    try:
        with heal_on_rejection(get_settings):
            async with asyncio.timeout(max(1.0, remaining_seconds(context) - FINAL_GRACE_SECONDS)):
                outcome, acknowledge = await encode_record(
                    record,
                    context,
                    factory=factory,
                    settings=settings,
                    source=source,
                    store=store,
                    clock=clock,
                    hooks=hooks,
                )
    finally:
        if engine is not None:
            await engine.dispose()
        envelope = _identity(record)
        _line(
            event="short_encode",
            outcome=outcome,
            cold=cold,
            seconds=round(clock() - started, 3),
            request_id=getattr(context, "aws_request_id", None),
            **envelope,
        )
    if not acknowledge:
        failures.append({"itemIdentifier": record["messageId"]})
    return {"batchItemFailures": failures}


def _identity(record):
    try:
        body = json.loads(record["body"])
        source = body.get("source") or {}
        return {
            "job_id": body.get("job_id"),
            "attempt_id": body.get("attempt_id"),
            "source_bytes": source.get("size_bytes"),
        }
    except (ValueError, KeyError, TypeError, AttributeError):
        return {"job_id": None, "attempt_id": None, "source_bytes": None}
