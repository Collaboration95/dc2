"""Opt-in Lambda lane for short encodes (V2, #93): the admission rule and the executor budget.

V1 stays the default. Without ``PROCESSING_SHORT_LANE=true`` nothing in this module changes a
routing decision, and a job is encoded by a finite Fargate task exactly as before. The rule is
fixed here, in code, and the template and docs are tested against these constants.

Admission is two-staged because the two facts it needs arrive at different times:

1. **Dispatch** (``admit_source``): only what the accepted source descriptor already says, its
   size. A source over the size bound never reaches the short queue. Duration is not known yet:
   Media does not probe, and the first probe is the executor's.
2. **Executor** (``check_probe``): the executor probes after its fenced claim and download. A
   source over the duration or height bound is handed back to the standard lane by
   ``messaging.redirect_to_long_lane``, which is the same fenced transition a retry uses.

Everything that is not admitted, or that failed once on Lambda, stays on (or returns to) Fargate.
This module imports no SQL at import time, so the template generator can read the constants.
"""

import math
import os

LANE_STANDARD = "processing-work"
LANE_SHORT = "processing-work-short"
# Lanes are routing; this prefix is how an executor identifies itself in attempt_tasks. The
# binding already exists for the Fargate worker, so no schema change is needed to know that an
# attempt ran on Lambda.
TASK_PREFIX = "lambda-"

# --- Admission rule ------------------------------------------------------------------------
# A source at or under ALL three bounds is short. The bounds are inclusive.
#
# Duration is the binding one: encode time scales with seconds of video, and 60 s of 1080p at
# veryfast on ~2 vCPU is about 1.5 minutes for the primary plus the HLS ladder (a measured
# local 24 s fixture was the only datum when this was set, so the margin is deliberately wide;
# the Lambda has about 1.7 vCPU, see MEMORY_MB, which stretches that by about 15 %).
MAX_DURATION_SECONDS = 60.0
# Size is a cheap pre-filter, not the constraint: it is the only bound knowable at dispatch.
# 64 MiB is 8.9 Mbit/s over a full 60 s, which covers an ordinary 1080p phone clip while
# keeping the worst /tmp footprint (source + primary + ladder, bounded at 5x the source) at
# 320 MiB against 2 GiB of ephemeral storage.
MAX_SOURCE_BYTES = 64 * 1024 * 1024
# Height bounds the ladder (variants_for gives up to three rungs below the source) and the
# per-second cost of the decode. Anything above 1080p is Fargate work.
MAX_HEIGHT = 1080

# --- Executor budget -----------------------------------------------------------------------
ACCOUNT_CONCURRENCY = 10  # the account limit; nothing is reservable at this size
LAMBDA_TIMEOUT_SECONDS = 900  # the service maximum
# The pipeline must end, and report, well inside the timeout. The remainder covers: killing
# an FFmpeg process group, one fenced failure write, temp-dir removal, and a database resume
# that has to reconnect. A pipeline deadline of 720 s is also ~6x the expected encode time.
HEADROOM_SECONDS = 180
PIPELINE_DEADLINE_SECONDS = LAMBDA_TIMEOUT_SECONDS - HEADROOM_SECONDS
# 3008 MB is the most this account may configure (CloudFormation on dc2-live, 21 October 2026:
# "'MemorySize' ... must have value less than or equal to 3008"; a higher limit needs a support
# request). 1769 MB is one vCPU, so this is about 1.7 vCPU against the 2 vCPU Fargate task: the
# comparison is no longer per equal CPU, and an encode is expected to take about 15 % longer
# than on 3584 MB (the design's first choice, never deployed). The 720 s pipeline deadline is
# about 6x the expected encode time, so the admission bounds keep their margin.
MEMORY_MB = 3008
EPHEMERAL_STORAGE_MB = 2048
# SQS refuses a mapping whose queue visibility is below the function timeout. The minimum
# plus a minute keeps a message from reappearing while its invocation can still be running.
QUEUE_VISIBILITY_SECONDS = LAMBDA_TIMEOUT_SECONDS + 60
# 2 is the SQS event source minimum. It is also the figure that fits the account limit.
ENCODER_MAX_CONCURRENCY = 2
FARGATE_ENCODER_CAP = 3  # unchanged: operator batches and the launcher
# Both executors may run at once. See docs/execution/aws/v2/lambda-short-encodes.md.
COMBINED_ENCODER_CAP = FARGATE_ENCODER_CAP + ENCODER_MAX_CONCURRENCY


class NotAdmitted(Exception):
    """The probe shows the source is not short; the attempt is handed to Fargate."""

    def __init__(self, reason):
        super().__init__(reason)
        self.reason = reason


def enabled(environ=None):
    """Dispatchers consult this; the template sets it only when LambdaShortEncodes is true."""
    return (environ if environ is not None else os.environ).get(
        "PROCESSING_SHORT_LANE", ""
    ).lower() == "true"


def admit_source(source):
    """Dispatch-time test on the accepted descriptor: a positive size within the bound."""
    size = source.get("size_bytes") if isinstance(source, dict) else None
    return type(size) is int and 0 < size <= MAX_SOURCE_BYTES


def check_probe(probe):
    """Executor-time test on the probe; raises NotAdmitted instead of encoding."""
    duration = probe.duration_seconds
    if not math.isfinite(duration) or duration <= 0 or duration > MAX_DURATION_SECONDS:
        raise NotAdmitted("duration")
    if probe.height > MAX_HEIGHT:
        raise NotAdmitted("height")


async def previously_ran_on_lambda(session, job_id):
    """True when an earlier attempt of this job was claimed by the Lambda executor.

    A Lambda attempt that ended any way but success sends the retry to Fargate: a timeout or
    a crash means the work was not short after all, and a plain failure is not worth a second
    Lambda attempt. The binding is the only state used, so this needs no new column.
    """
    from sqlalchemy import select

    from processing.messaging_models import AttemptTask
    from processing.models import Attempt

    found = await session.scalar(
        select(AttemptTask.attempt_id)
        .join(Attempt, Attempt.id == AttemptTask.attempt_id)
        .where(Attempt.job_id == job_id, AttemptTask.task_name.startswith(TASK_PREFIX))
        .limit(1)
    )
    return found is not None


async def work_lane(session, job):
    """The lane a queued attempt's work message is sent to. Caller holds the Job lock."""
    if not enabled() or not admit_source(job.source):
        return LANE_STANDARD
    if await previously_ran_on_lambda(session, job.id):
        return LANE_STANDARD
    return LANE_SHORT


def executor_name(request_id):
    """attempt_tasks name of a Lambda invocation: unique per invocation, prefix-identifiable."""
    return f"{TASK_PREFIX}{request_id}"[:256]
