"""The opt-in short lane's admission rule and routing (V2, #93), with no services.

The SQL consequences (outbox lane, redirect, sticky fallback) are in
tests/v1/test_short_encoder_sql.py against real PostgreSQL.
"""

from types import SimpleNamespace
from uuid import uuid4

import pytest

from delivery.sqs import FALLBACK_LANE, LANES, SQS
from media_engine.probe import SourceProbe
from processing import short_lane
from processing.short_lane import NotAdmitted

MIB = 1024 * 1024


def source(size):
    return {
        "bucket": "sources",
        "key": "sources/o/a/source",
        "version_id": "v1",
        "sha256": "a" * 64,
        "size_bytes": size,
        "content_type": "video/mp4",
    }


# --- Admission rule: the three bounds are inclusive and each one is enforced ---------------


def test_the_bounds_are_the_ones_the_design_documents():
    assert short_lane.MAX_DURATION_SECONDS == 60
    assert short_lane.MAX_SOURCE_BYTES == 64 * MIB
    assert short_lane.MAX_HEIGHT == 1080
    # A smaller bound than the platform's own upload limit, so the pre-filter does something.
    assert short_lane.MAX_SOURCE_BYTES < 100 * MIB


@pytest.mark.parametrize(
    ("size", "admitted"),
    [
        (1, True),
        (short_lane.MAX_SOURCE_BYTES - 1, True),
        (short_lane.MAX_SOURCE_BYTES, True),
        (short_lane.MAX_SOURCE_BYTES + 1, False),
        (100 * MIB, False),
        (0, False),
        (-5, False),
        (None, False),
        (True, False),  # bool is an int subclass but never a size
        ("1000", False),
        (12.5, False),
    ],
)
def test_a_source_is_admitted_at_dispatch_only_within_the_size_bound(size, admitted):
    assert short_lane.admit_source(source(size)) is admitted


def test_a_missing_or_malformed_descriptor_is_never_admitted():
    assert not short_lane.admit_source(None)
    assert not short_lane.admit_source({})
    assert not short_lane.admit_source("sources/o/a")


@pytest.mark.parametrize(
    ("duration", "height", "reason"),
    [
        (60.0, 1080, None),
        (59.99, 720, None),
        (0.5, 144, None),
        (60.001, 720, "duration"),
        (61.0, 480, "duration"),
        (3600.0, 360, "duration"),
        (30.0, 1081, "height"),
        (30.0, 2160, "height"),
        (float("inf"), 720, "duration"),
        (float("nan"), 720, "duration"),
        (0.0, 720, "duration"),
        (-1.0, 720, "duration"),
    ],
)
def test_a_probe_is_admitted_at_the_executor_only_within_duration_and_height(
    duration, height, reason
):
    probe = SourceProbe(width=16 * height // 9, height=height, duration_seconds=duration)
    if reason is None:
        short_lane.check_probe(probe)
        return
    with pytest.raises(NotAdmitted) as raised:
        short_lane.check_probe(probe)
    assert raised.value.reason == reason


def test_the_executor_budget_leaves_headroom_inside_the_lambda_timeout():
    assert short_lane.LAMBDA_TIMEOUT_SECONDS <= 900
    assert short_lane.PIPELINE_DEADLINE_SECONDS == (
        short_lane.LAMBDA_TIMEOUT_SECONDS - short_lane.HEADROOM_SECONDS
    )
    # Enough to kill FFmpeg, write one fenced failure and clean up, and then some.
    assert short_lane.HEADROOM_SECONDS >= 120
    # The SQS mapping refuses a queue whose visibility is below the function timeout.
    assert short_lane.QUEUE_VISIBILITY_SECONDS > short_lane.LAMBDA_TIMEOUT_SECONDS


# --- Routing ----------------------------------------------------------------------------------


class FakeSession:
    """Only the one scalar the sticky-fallback query needs; records that it was asked."""

    def __init__(self, ran_on_lambda=False):
        self.ran_on_lambda, self.queries = ran_on_lambda, 0

    async def scalar(self, _statement):
        self.queries += 1
        return uuid4() if self.ran_on_lambda else None


def job(size=1000):
    return SimpleNamespace(id=uuid4(), source=source(size))


async def test_the_flag_off_routes_every_job_to_the_standard_lane_without_a_query(monkeypatch):
    monkeypatch.delenv("PROCESSING_SHORT_LANE", raising=False)
    session = FakeSession()
    assert await short_lane.work_lane(session, job()) == short_lane.LANE_STANDARD
    assert session.queries == 0, "the default path must cost V1 nothing"


@pytest.mark.parametrize("value", ["", "false", "0", "yes", "TRUEISH"])
async def test_only_the_word_true_enables_the_lane(monkeypatch, value):
    monkeypatch.setenv("PROCESSING_SHORT_LANE", value)
    assert not short_lane.enabled()
    assert await short_lane.work_lane(FakeSession(), job()) == short_lane.LANE_STANDARD


async def test_an_admitted_job_goes_to_the_short_lane_when_enabled(monkeypatch):
    monkeypatch.setenv("PROCESSING_SHORT_LANE", "TRUE")
    assert await short_lane.work_lane(FakeSession(), job(1000)) == short_lane.LANE_SHORT
    edge = job(short_lane.MAX_SOURCE_BYTES)
    assert await short_lane.work_lane(FakeSession(), edge) == short_lane.LANE_SHORT


async def test_a_job_over_the_size_bound_stays_on_the_standard_lane_without_a_query(monkeypatch):
    monkeypatch.setenv("PROCESSING_SHORT_LANE", "true")
    session = FakeSession()
    big = job(short_lane.MAX_SOURCE_BYTES + 1)
    assert await short_lane.work_lane(session, big) == short_lane.LANE_STANDARD
    assert session.queries == 0


async def test_a_job_that_already_ran_on_lambda_is_retried_on_the_standard_lane(monkeypatch):
    monkeypatch.setenv("PROCESSING_SHORT_LANE", "true")
    assert (
        await short_lane.work_lane(FakeSession(ran_on_lambda=True), job())
        == short_lane.LANE_STANDARD
    )


def test_the_executor_name_is_prefix_identifiable_unique_and_bounded():
    assert short_lane.executor_name("req-1").startswith(short_lane.TASK_PREFIX)
    assert short_lane.executor_name("req-1") != short_lane.executor_name("req-2")
    assert len(short_lane.executor_name("x" * 1000)) == 256
    # A Fargate task name (startedBy is "v1-u" + a token) is never mistaken for a Lambda one.
    assert not ("v1-u" + "a" * 32).startswith(short_lane.TASK_PREFIX)


# --- Transport: the lane exists, is producer-only for Processing, and falls back safely ---------


class Client:
    def __init__(self):
        self.sent = []

    def send_message(self, **kwargs):
        self.sent.append(kwargs["QueueUrl"])
        return {"MessageId": "id"}


def work_body():
    from tests.v1.test_delivery import message

    return message("work")


async def test_work_for_the_short_lane_is_sent_to_the_short_queue_when_it_exists():
    client = Client()
    urls = {"processing-work": "std", "processing-work-short": "short"}
    queue = SQS(urls, producer="processing", client=client)
    await queue.send("processing-work-short", work_body())
    assert client.sent == ["short"]


@pytest.mark.parametrize("configured", ["", None])
async def test_short_lane_work_falls_back_to_the_standard_queue_when_the_lane_is_not_deployed(
    configured,
):
    # The experiment was switched off while a short-lane row was still queued or being repaired.
    client = Client()
    urls = {"processing-work": "std", "processing-work-short": configured}
    queue = SQS(urls, producer="processing", client=client)
    await queue.send("processing-work-short", work_body())
    assert client.sent == ["std"]


async def test_only_processing_may_produce_to_the_short_lane():
    client = Client()
    urls = {"processing-work": "std", "processing-work-short": "short"}
    for producer in ("media", None):
        queue = SQS(urls, producer=producer, client=client)
        with pytest.raises(ValueError):
            await queue.send("processing-work-short", work_body())
    assert not client.sent


def test_only_the_short_lane_has_a_fallback_and_it_leads_to_the_standard_lane():
    assert FALLBACK_LANE == {"processing-work-short": "processing-work"}


def test_the_short_lane_carries_work_messages_only():
    assert LANES["processing-work-short"] == LANES["processing-work"] == {"work"}
