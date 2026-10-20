"""The Lambda short-encode executor (V2, #93) over fakes: no database, S3 or FFmpeg.

These prove the executor's decisions: what it claims, which deadline it sets, when it
acknowledges and when it leaves a message for the redrive policy. The fences themselves
(lease, attempt, one commit) are the shared lifecycle's and are exercised against real
PostgreSQL in tests/v1/test_short_encoder_sql.py.
"""

import json
import logging
import time
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from media_engine.probe import SourceProbe
from processing import short_encoder, short_lane
from processing.config import Settings
from processing.lifecycle import Claim
from processing.worker import sqs
from processing.worker.supervisor import AttemptDeadline
from tests.v1.test_delivery import message

OUTPUTS = [{"kind": "primary", "object_key": "jobs/j/attempts/a/primary.mp4"}]


@pytest.fixture(autouse=True)
def heartbeat_and_fresh_environment(monkeypatch):
    monkeypatch.setattr("processing.worker.supervisor.heartbeat", AsyncMock(return_value=True))
    monkeypatch.setattr(short_encoder, "_invocations", 0)  # a cold execution environment


def settings():
    return Settings(postgres_dsn="postgresql://unused@unused/processing_db")


def context(remaining_seconds=900.0, request_id="req-1"):
    return SimpleNamespace(
        aws_request_id=request_id, get_remaining_time_in_millis=lambda: remaining_seconds * 1000
    )


def record(body=None, message_id=None):
    return {
        "messageId": message_id or str(uuid4()),
        "body": json.dumps(body if body is not None else message("work")),
    }


def work():
    return Claim(
        job_id=uuid4(),
        attempt_id=uuid4(),
        lease_token=uuid4(),
        owner_id=uuid4(),
        source={"size_bytes": 1000},
        operations=[],
        source_url="",
        source_url_expires_at=datetime.now(UTC),
        deadline_at=datetime.now(UTC),
    )


class Rig:
    """execute_message's seams, with call recording."""

    def __init__(self, monkeypatch, *, claimed=True, finished=True, disposition="stale"):
        self.claimed = work() if claimed else None
        self.claim = AsyncMock(return_value=self.claimed)
        self.finish = AsyncMock(return_value=finished)
        self.disposition = AsyncMock(return_value=disposition)
        self.redirect = AsyncMock(return_value=True)
        monkeypatch.setattr(short_encoder.messaging, "redirect_to_long_lane", self.redirect)
        self.pipeline = AsyncMock(return_value=OUTPUTS)
        monkeypatch.setattr(sqs, "pipeline", self.pipeline)

    async def invoke(self, event, ctx=None):
        return await short_encoder.invoke(
            event,
            ctx or context(),
            factory=object(),
            settings=settings(),
            source=SimpleNamespace(download=AsyncMock()),
            store=object(),
            hooks={"claim": self.claim, "finish": self.finish, "disposition": self.disposition},
        )


async def test_a_short_job_is_claimed_encoded_finished_and_acknowledged(monkeypatch):
    rig = Rig(monkeypatch)
    assert await rig.invoke({"Records": [record()]}) == {"batchItemFailures": []}
    rig.claim.assert_awaited_once()
    # The executor binds the attempt under its own, prefix-identifiable name.
    assert rig.claim.call_args.kwargs["task_name"] == "lambda-req-1"
    rig.finish.assert_awaited_once()
    assert rig.finish.call_args.kwargs["outputs"] == OUTPUTS
    rig.redirect.assert_not_awaited()


async def test_the_pipeline_is_given_the_admission_check_and_the_native_source(monkeypatch):
    rig = Rig(monkeypatch)
    await rig.invoke({"Records": [record()]})
    kwargs = rig.pipeline.call_args.kwargs
    assert kwargs["admit"] is short_lane.check_probe
    assert callable(kwargs["downloader"])


async def test_the_durable_deadline_never_outlives_the_invocation(monkeypatch):
    rig = Rig(monkeypatch)
    await rig.invoke({"Records": [record()]}, context(remaining_seconds=900))
    claimed_with = rig.claim.call_args.args[3]
    assert claimed_with.attempt_timeout_seconds == short_lane.PIPELINE_DEADLINE_SECONDS == 720
    rig2 = Rig(monkeypatch)
    await rig2.invoke({"Records": [record()]}, context(remaining_seconds=400))
    # 400 s left, 180 s of headroom reserved: the attempt may use 220 s and no more.
    assert rig2.claim.call_args.args[3].attempt_timeout_seconds == 220


async def test_the_supervisor_deadline_leaves_the_documented_headroom(monkeypatch):
    seen = {}
    real = sqs.Supervisor

    class Spy(real):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            seen["left"] = self.deadline - time.monotonic()

    monkeypatch.setattr(sqs, "Supervisor", Spy)
    rig = Rig(monkeypatch)
    await rig.invoke({"Records": [record()]}, context(remaining_seconds=900))
    assert 700 < seen["left"] <= short_lane.PIPELINE_DEADLINE_SECONDS
    assert short_lane.LAMBDA_TIMEOUT_SECONDS - seen["left"] >= short_lane.HEADROOM_SECONDS


async def test_too_little_time_left_refuses_before_claiming_anything(monkeypatch):
    rig = Rig(monkeypatch)
    item = record()
    result = await rig.invoke({"Records": [item]}, context(remaining_seconds=200))
    assert result == {"batchItemFailures": [{"itemIdentifier": item["messageId"]}]}
    rig.claim.assert_not_awaited()


@pytest.mark.parametrize("body", ["{not json", json.dumps({"x": 1}), json.dumps(message("submit"))])
async def test_a_malformed_or_foreign_message_is_left_for_the_redrive_policy(monkeypatch, body):
    rig = Rig(monkeypatch)
    item = {"messageId": "m-1", "body": body}
    result = await rig.invoke({"Records": [item]})
    assert result == {"batchItemFailures": [{"itemIdentifier": "m-1"}]}
    rig.claim.assert_not_awaited()
    rig.finish.assert_not_awaited()


async def test_a_redelivered_message_for_a_claimed_attempt_is_acknowledged_as_stale(monkeypatch):
    # The first invocation died mid-encode and recovery has ended its attempt: a redelivery
    # finds the attempt not queued, claims nothing, and is deleted rather than encoded twice.
    rig = Rig(monkeypatch, claimed=False, disposition="stale")
    assert await rig.invoke({"Records": [record()]}) == {"batchItemFailures": []}
    rig.pipeline.assert_not_awaited()
    rig.finish.assert_not_awaited()


@pytest.mark.parametrize("verdict", ["pending", "unknown"])
async def test_work_sql_cannot_prove_dead_stays_on_the_queue(monkeypatch, verdict):
    rig = Rig(monkeypatch, claimed=False, disposition=verdict)
    item = record()
    assert await rig.invoke({"Records": [item]}) == {
        "batchItemFailures": [{"itemIdentifier": item["messageId"]}]
    }
    rig.pipeline.assert_not_awaited()


async def test_a_lost_lease_at_commit_is_not_acknowledged_and_writes_nothing_more(monkeypatch):
    rig = Rig(monkeypatch, finished=False)
    item = record()
    assert await rig.invoke({"Records": [item]}) == {
        "batchItemFailures": [{"itemIdentifier": item["messageId"]}]
    }
    rig.finish.assert_awaited_once()  # the fenced write was refused; nothing retried it


async def test_a_deadline_inside_the_pipeline_commits_nothing(monkeypatch):
    rig = Rig(monkeypatch)
    rig.pipeline.side_effect = AttemptDeadline()
    item = record()
    assert await rig.invoke({"Records": [item]}) == {
        "batchItemFailures": [{"itemIdentifier": item["messageId"]}]
    }
    rig.finish.assert_not_awaited()  # recovery owns the timeout; this invocation has no authority


async def test_an_ordinary_encode_failure_records_a_curated_error_and_is_acknowledged(monkeypatch):
    rig = Rig(monkeypatch)
    rig.pipeline.side_effect = ValueError("secret detail https://signed.example/?sig=abc")
    assert await rig.invoke({"Records": [record()]}) == {"batchItemFailures": []}
    error = rig.finish.call_args.kwargs["error"]
    assert error == "The source or edit could not be processed" and "secret" not in error


async def test_a_source_over_the_probe_bounds_is_handed_to_the_standard_lane(monkeypatch):
    rig = Rig(monkeypatch)

    async def probe_then_admit(*_args, admit, **_kwargs):
        admit(SourceProbe(width=1280, height=720, duration_seconds=61.0))
        raise AssertionError("an inadmissible source must not reach the encode")

    rig.pipeline.side_effect = probe_then_admit
    assert await rig.invoke({"Records": [record()]}) == {"batchItemFailures": []}
    rig.redirect.assert_awaited_once()
    assert rig.redirect.call_args.args[1] is rig.claimed
    rig.finish.assert_not_awaited()  # the attempt is abandoned by the redirect, not finished


async def test_a_redirect_that_loses_its_fence_is_not_acknowledged(monkeypatch):
    rig = Rig(monkeypatch)
    rig.redirect.return_value = False

    async def probe_then_admit(*_args, admit, **_kwargs):
        admit(SourceProbe(width=1280, height=2160, duration_seconds=10.0))

    rig.pipeline.side_effect = probe_then_admit
    item = record()
    assert await rig.invoke({"Records": [item]}) == {
        "batchItemFailures": [{"itemIdentifier": item["messageId"]}]
    }


async def test_only_the_first_record_is_encoded_and_the_rest_go_back(monkeypatch):
    rig = Rig(monkeypatch)
    first, second, third = record(), record(), record()
    result = await rig.invoke({"Records": [first, second, third]})
    assert result == {
        "batchItemFailures": [
            {"itemIdentifier": second["messageId"]},
            {"itemIdentifier": third["messageId"]},
        ]
    }
    rig.claim.assert_awaited_once()


async def test_an_empty_batch_is_a_no_op(monkeypatch):
    rig = Rig(monkeypatch)
    assert await rig.invoke({"Records": []}) == {"batchItemFailures": []}
    assert await rig.invoke({}) == {"batchItemFailures": []}
    rig.claim.assert_not_awaited()


async def test_each_invocation_logs_one_ids_only_line_and_marks_the_first_as_cold(
    monkeypatch, caplog
):
    rig = Rig(monkeypatch)
    body = message("work")
    with caplog.at_level(logging.INFO, logger="dc2.short_encoder"):
        await rig.invoke({"Records": [record(body)]})
        await rig.invoke({"Records": [record(body)]}, context(request_id="req-2"))
    lines = [json.loads(r.getMessage().split(" ", 1)[1]) for r in caplog.records]
    assert [line["cold"] for line in lines] == [True, False]
    assert [line["request_id"] for line in lines] == ["req-1", "req-2"]
    assert {line["outcome"] for line in lines} == {"finished"}
    assert lines[0]["job_id"] == body["job_id"] and lines[0]["source_bytes"] == 123
    text = json.dumps(lines)
    for forbidden in ("http", "token", "sha256", "key", "version"):
        assert forbidden not in text
