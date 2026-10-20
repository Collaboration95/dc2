"""The Lambda short-encode lane against real PostgreSQL (V2, #93).

Set V1_TEST_PROCESSING_DSN to an admin asyncpg DSN, as for test_messaging_sql.py. Each test owns
an ephemeral SQL schema. The pipeline and storage are in-process fakes here: these tests prove
routing, the fenced redirect, interruption recovery and the one-commit guarantee. The last two
tests run the handler for real against loopback Moto and FFmpeg (V1_TEST_S3_ENDPOINT).

What none of this proves: Lambda timeouts, event-source-mapping retries, IAM, VPC reachability or
cold-start behaviour. Those are the cloud measurement plan in docs/execution/aws/v2/.
"""

import asyncio
import hashlib
import json
import os
import shutil
import subprocess
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from urllib.parse import urlsplit
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from delivery.sql import publish_due
from media_engine.probe import SourceProbe
from processing import lifecycle, messaging, short_encoder, short_lane
from processing.config import Settings
from processing.database import Base
from processing.messaging import REDIRECTED, handle_command, redirect_to_long_lane, retry_job
from processing.messaging_models import AttemptTask, JobMessaging, ProcessingOutbox
from processing.models import Attempt, CleanupIntent, Job
from processing.recovery import INTERRUPTED
from processing.recovery_v1 import repair_work, run_once
from processing.worker import sqs
from tests.v1.test_delivery import message

pytestmark = pytest.mark.integration

MIB = 1024 * 1024


class Crash(BaseException):
    """A killed or timed-out invocation: unlike Exception, nothing in the executor catches it."""


@pytest.fixture(autouse=True)
def short_lane_on(monkeypatch):
    monkeypatch.setenv("PROCESSING_SHORT_LANE", "true")
    monkeypatch.setattr(short_encoder, "_invocations", 0)


@pytest_asyncio.fixture
async def dsn():
    value = os.environ.get("V1_TEST_PROCESSING_DSN")
    if not value:
        pytest.skip("Lead C's isolated PostgreSQL DSN not provided")
    if not value.startswith("postgresql+asyncpg://"):
        raise ValueError("V1_TEST_PROCESSING_DSN must select asyncpg explicitly")
    return value


@pytest_asyncio.fixture
async def factory(dsn):
    schema = "v2_short_" + uuid4().hex
    admin = create_async_engine(dsn)
    async with admin.begin() as connection:
        await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_async_engine(dsn, connect_args={"server_settings": {"search_path": schema}})
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    try:
        yield async_sessionmaker(engine, expire_on_commit=False)
    finally:
        await engine.dispose()
        async with admin.begin() as connection:
            await connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        await admin.dispose()


@pytest.fixture
def settings(dsn):
    return Settings(postgres_dsn=dsn, lease_seconds=60, heartbeat_seconds=10)


def context(request_id="req-1", remaining=900.0):
    return SimpleNamespace(
        aws_request_id=request_id, get_remaining_time_in_millis=lambda: remaining * 1000
    )


def submit(size=123):
    body = message()
    body["source"] = {**body["source"], "size_bytes": size}
    return body


async def work_rows(factory):
    async with factory() as session:
        rows = (
            await session.scalars(
                select(ProcessingOutbox)
                .where(ProcessingOutbox.queue.in_(["processing-work", "processing-work-short"]))
                .order_by(ProcessingOutbox.body["state_version"].as_integer())
            )
        ).all()
        return [(row.queue, row.body) for row in rows]


async def state(factory):
    async with factory() as session:
        job = await session.scalar(select(Job))
        attempts = (await session.scalars(select(Attempt).order_by(Attempt.attempt_number))).all()
        return job, attempts


def sqs_record(body):
    return {"messageId": str(uuid4()), "body": json.dumps(body)}


def outputs_for(work):
    prefix = lifecycle.output_prefix(work.job_id, work.attempt_id)
    return [
        {
            "kind": "primary",
            "object_key": prefix + "primary.mp4",
            "media_type": "video/mp4",
            "size_bytes": 10,
            "sha256": "b" * 64,
        }
    ]


async def good_pipeline(work, *_args, admit=None, **_kwargs):
    return outputs_for(work)


async def invoke(
    factory, settings, record, *, pipeline=good_pipeline, request="req-1", monkeypatch
):
    monkeypatch.setattr(sqs, "pipeline", pipeline)
    return await short_encoder.invoke(
        {"Records": [record]},
        context(request),
        factory=factory,
        settings=settings,
        source=SimpleNamespace(download=AsyncMock()),
        store=object(),
    )


# --- Routing is decided where work is dispatched --------------------------------------------


async def test_an_admitted_job_is_staged_on_the_short_lane_and_the_rest_on_the_standard_lane(
    factory, monkeypatch
):
    await handle_command(factory, submit(size=short_lane.MAX_SOURCE_BYTES))
    await handle_command(factory, submit(size=short_lane.MAX_SOURCE_BYTES + 1))
    lanes = sorted(queue for queue, _ in await work_rows(factory))
    assert lanes == ["processing-work", "processing-work-short"]
    monkeypatch.delenv("PROCESSING_SHORT_LANE")
    await handle_command(factory, submit(size=100))
    assert sorted(queue for queue, _ in await work_rows(factory)).count("processing-work") == 2


async def test_repair_resends_on_the_lane_the_work_was_staged_on(factory):
    await handle_command(factory, submit())
    transport = SimpleNamespace(send=AsyncMock())
    assert await publish_due(factory, ProcessingOutbox, transport, limit=5) == 2
    sent = [call.args[0] for call in transport.send.call_args_list]
    assert "processing-work-short" in sent and "processing-work" not in sent
    async with factory() as session, session.begin():
        attempt = await session.scalar(select(Attempt))
        attempt.next_dispatch_at = await session.scalar(select(func.clock_timestamp())) - timedelta(
            days=8
        )
    assert await repair_work(factory) == 1
    transport.send.reset_mock()
    assert await publish_due(factory, ProcessingOutbox, transport, limit=5) == 1
    assert transport.send.call_args.args[0] == "processing-work-short"


async def test_repair_that_must_recreate_the_row_routes_it_again(factory):
    await handle_command(factory, submit())
    async with factory() as session, session.begin():
        await session.execute(
            text("DELETE FROM message_outbox WHERE queue = 'processing-work-short'")
        )
        attempt = await session.scalar(select(Attempt))
        attempt.next_dispatch_at = None
    assert await repair_work(factory) == 1
    assert [queue for queue, _ in await work_rows(factory)] == ["processing-work-short"]


# --- The executor runs the same fenced lifecycle ----------------------------------------------


async def test_the_handler_claims_binds_commits_once_and_ignores_the_redelivery(
    factory, settings, monkeypatch
):
    await handle_command(factory, submit())
    ((lane, body),) = await work_rows(factory)
    assert lane == "processing-work-short"
    record = sqs_record(body)
    assert await invoke(factory, settings, record, monkeypatch=monkeypatch) == {
        "batchItemFailures": []
    }
    job, (attempt,) = await state(factory)
    assert job.status == "done" and attempt.state == "succeeded"
    assert [o["kind"] for o in job.outputs] == ["primary"]
    async with factory() as session:
        binding = await session.get(AttemptTask, attempt.id)
        results = await session.scalar(select(func.count()).select_from(ProcessingOutbox))
        version = (await session.get(JobMessaging, job.id)).state_version
    assert binding.task_name == "lambda-req-1"
    # A redelivery of the same message (SQS is at-least-once) is acknowledged and commits nothing.
    again = await invoke(factory, settings, record, request="req-2", monkeypatch=monkeypatch)
    assert again == {"batchItemFailures": []}
    async with factory() as session:
        assert await session.scalar(select(func.count()).select_from(ProcessingOutbox)) == results
        assert (await session.get(JobMessaging, job.id)).state_version == version
    job_after, (attempt_after,) = await state(factory)
    assert job_after.outputs == job.outputs and attempt_after.finished_at == attempt.finished_at


async def test_two_invocations_racing_for_one_message_encode_and_commit_exactly_once(
    factory, settings, monkeypatch
):
    await handle_command(factory, submit())
    ((_, body),) = await work_rows(factory)
    started = asyncio.Event()
    encodes = []

    async def slow_pipeline(work, *_args, **_kwargs):
        encodes.append(work.attempt_id)
        started.set()
        await asyncio.sleep(0.3)
        return outputs_for(work)

    monkeypatch.setattr(sqs, "pipeline", slow_pipeline)

    async def go(name):
        return await short_encoder.invoke(
            {"Records": [sqs_record(body)]},
            context(name),
            factory=factory,
            settings=settings,
            source=SimpleNamespace(download=AsyncMock()),
            store=object(),
        )

    results = await asyncio.gather(go("req-a"), go("req-b"))
    assert results == [{"batchItemFailures": []}, {"batchItemFailures": []}]
    assert len(encodes) == 1, "the SQL claim admits one invocation per attempt"
    job, (attempt,) = await state(factory)
    assert job.status == "done" and attempt.state == "succeeded"


# --- Admission at the executor: a long source goes to Fargate through the fenced transition ----


async def test_a_source_the_probe_rejects_becomes_a_new_attempt_on_the_standard_lane(
    factory, settings, monkeypatch
):
    await handle_command(factory, submit())
    ((_, body),) = await work_rows(factory)

    async def long_source(work, *_args, admit, **_kwargs):
        admit(SourceProbe(width=1280, height=720, duration_seconds=120.0))
        raise AssertionError("not reached")

    record = sqs_record(body)
    assert await invoke(
        factory, settings, record, pipeline=long_source, monkeypatch=monkeypatch
    ) == {"batchItemFailures": []}
    job, (first, second) = await state(factory)
    assert (first.state, first.error) == ("abandoned", REDIRECTED)
    assert (second.attempt_number, second.state) == (2, "queued")
    assert job.status == "queued" and job.current_attempt_id == second.id and job.outputs == []
    rows = await work_rows(factory)
    assert [queue for queue, _ in rows] == ["processing-work-short", "processing-work"]
    assert rows[1][1]["attempt_id"] == str(second.id)
    assert rows[1][1]["state_version"] > rows[0][1]["state_version"]
    async with factory() as session:
        assert await session.get(CleanupIntent, first.id) is not None
    # The old message is now stale; a Fargate encoder can claim the successor attempt.
    assert await invoke(factory, settings, record, request="req-2", monkeypatch=monkeypatch) == {
        "batchItemFailures": []
    }
    claimed = await messaging.claim(
        factory, job.id, second.id, settings, envelope=rows[1][1], task_name="v1-u" + "c" * 32
    )
    assert claimed is not None and claimed.attempt_id == second.id


async def test_a_stale_attempt_can_neither_redirect_nor_finish(factory, settings):
    await handle_command(factory, submit())
    job, (attempt,) = await state(factory)
    work = await messaging.claim(
        factory, job.id, attempt.id, settings, task_name=short_lane.executor_name("old")
    )
    async with factory() as session, session.begin():
        row = await session.get(Attempt, attempt.id)
        row.lease_expires_at = await session.scalar(select(func.clock_timestamp())) - timedelta(
            seconds=1
        )
    result = await run_once(factory, settings, SimpleNamespace(send=AsyncMock()), store=_NoStore())
    assert result["expired"] == 1
    assert not await redirect_to_long_lane(factory, work)
    assert not await messaging.finish(factory, work, outputs=outputs_for(work))
    job, attempts = await state(factory)
    assert len(attempts) == 1 and (job.status, attempts[0].state) == ("failed", "abandoned")


async def test_a_redirect_by_a_superseded_lease_token_changes_nothing(factory, settings):
    await handle_command(factory, submit())
    job, (attempt,) = await state(factory)
    work = await messaging.claim(
        factory, job.id, attempt.id, settings, task_name=short_lane.executor_name("live")
    )
    forged = SimpleNamespace(job_id=work.job_id, attempt_id=work.attempt_id, lease_token=uuid4())
    assert not await redirect_to_long_lane(factory, forged)
    job, attempts = await state(factory)
    assert len(attempts) == 1 and job.status == "processing"


class _NoStore:
    def __init__(self):
        self.deleted = []

    async def delete_prefix(self, prefix):
        self.deleted.append(prefix)


# --- Interruption: repair and redelivery recover it; nothing commits twice ----------------------


async def test_a_crash_mid_encode_is_recovered_cleaned_and_retried_on_fargate_without_double_commit(
    factory, settings, monkeypatch
):
    await handle_command(factory, submit())
    ((_, body),) = await work_rows(factory)
    record = sqs_record(body)
    uploaded = []

    async def dies_after_uploading(work, *_args, **_kwargs):
        # An output reaches storage, then the environment is killed before it can finish.
        uploaded.append(lifecycle.output_prefix(work.job_id, work.attempt_id) + "primary.mp4")
        raise Crash()

    with pytest.raises(Crash):
        await invoke(
            factory, settings, record, pipeline=dies_after_uploading, monkeypatch=monkeypatch
        )
    job, (attempt,) = await state(factory)
    assert (job.status, attempt.state) == ("processing", "processing")
    work_name = (await _binding(factory, attempt.id)).task_name
    assert work_name.startswith(short_lane.TASK_PREFIX)

    # The heartbeat stopped with the process. When the lease runs out, repair ends the attempt
    # through the same fenced transition it uses for a dead Fargate task.
    async with factory() as session, session.begin():
        row = await session.get(Attempt, attempt.id)
        row.lease_expires_at = await session.scalar(select(func.clock_timestamp())) - timedelta(
            seconds=1
        )
    store = _NoStore()
    result = await run_once(factory, settings, SimpleNamespace(send=AsyncMock()), store=store)
    assert result["expired"] == 1 and result["cleaned"] == 1
    job, (attempt,) = await state(factory)
    assert (job.status, job.error, attempt.state) == ("failed", INTERRUPTED, "abandoned")
    assert store.deleted == [lifecycle.output_prefix(job.id, attempt.id)]

    # The message reappears after its visibility timeout: stale, acknowledged, never re-encoded.
    again = await invoke(factory, settings, record, request="req-2", monkeypatch=monkeypatch)
    assert again == {"batchItemFailures": []}
    # A zombie that outlived its lease cannot commit what it uploaded.
    zombie = SimpleNamespace(job_id=job.id, attempt_id=attempt.id, lease_token=attempt.lease_token)
    assert not await lifecycle.finish(factory, zombie, outputs=outputs_for(zombie))
    job, (attempt,) = await state(factory)
    assert job.status == "failed" and job.outputs == []

    # A late upload after the first scan is caught by the retained cleanup intent.
    async with factory() as session, session.begin():
        intent = await session.get(CleanupIntent, attempt.id)
        intent.next_try_at = await session.scalar(select(func.clock_timestamp())) - timedelta(
            seconds=1
        )
    assert (await run_once(factory, settings, SimpleNamespace(send=AsyncMock()), store=store))[
        "cleaned"
    ] == 1
    assert len(store.deleted) == 2

    # The owner retries the stored source. The failed Lambda attempt sends it to Fargate.
    async with factory() as session:
        await retry_job(session, job.owner_id, job.id, uuid4())
    job, (first, second) = await state(factory)
    assert (second.attempt_number, second.state) == (2, "queued")
    rows = await work_rows(factory)
    assert [queue for queue, _ in rows][-1] == "processing-work"
    fargate = await messaging.claim(
        factory, job.id, second.id, settings, envelope=rows[-1][1], task_name="v1-u" + "d" * 32
    )
    assert await messaging.finish(factory, fargate, outputs=outputs_for(fargate))
    job, (first, second) = await state(factory)
    assert job.status == "done" and (first.state, second.state) == ("abandoned", "succeeded")
    # Exactly one attempt's outputs are committed, and they are the successful attempt's.
    assert {o["object_key"].split("/")[3] for o in job.outputs} == {str(second.id)}


async def _binding(factory, attempt_id):
    async with factory() as session:
        return await session.get(AttemptTask, attempt_id)


async def test_a_plain_lambda_failure_also_sends_the_retry_to_fargate(
    factory, settings, monkeypatch
):
    await handle_command(factory, submit())
    ((_, body),) = await work_rows(factory)

    async def broken(*_args, **_kwargs):
        raise ValueError("corrupt")

    assert await invoke(
        factory, settings, sqs_record(body), pipeline=broken, monkeypatch=monkeypatch
    ) == {"batchItemFailures": []}
    job, (attempt,) = await state(factory)
    assert (job.status, attempt.state) == ("failed", "failed")
    async with factory() as session:
        await retry_job(session, job.owner_id, job.id, uuid4())
    assert [queue for queue, _ in await work_rows(factory)][-1] == "processing-work"


async def test_a_job_that_never_ran_on_lambda_is_retried_on_the_lane_it_qualifies_for(
    factory, settings
):
    await handle_command(factory, submit())
    job, (attempt,) = await state(factory)
    fargate = await messaging.claim(
        factory, job.id, attempt.id, settings, task_name="v1-u" + "e" * 32
    )
    error = "The source or edit could not be processed"
    assert await messaging.finish(factory, fargate, error=error)
    async with factory() as session:
        await retry_job(session, job.owner_id, job.id, uuid4())
    assert [queue for queue, _ in await work_rows(factory)][-1] == "processing-work-short"


# --- A real run: the handler against loopback Moto and FFmpeg -----------------------------------


@pytest.fixture
def moto():
    endpoint = os.environ.get("V1_TEST_S3_ENDPOINT")
    if not endpoint:
        pytest.skip("V1_TEST_S3_ENDPOINT (loopback Moto) not provided")
    if not (shutil.which("ffmpeg") and shutil.which("ffprobe")):
        pytest.skip("FFmpeg is not installed")
    parsed = urlsplit(endpoint)
    if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost"}:
        raise ValueError("The local handler run requires an explicit loopback HTTP endpoint")
    import boto3

    client = boto3.client(
        "s3",
        endpoint_url=endpoint,
        region_name="us-east-1",
        aws_access_key_id="local-test",
        aws_secret_access_key="local-test",
    )
    sources, outputs = "v2-src-" + uuid4().hex[:16], "v2-out-" + uuid4().hex[:16]
    for name in (sources, outputs):
        client.create_bucket(Bucket=name)
        client.put_bucket_versioning(Bucket=name, VersioningConfiguration={"Status": "Enabled"})
    yield SimpleNamespace(client=client, netloc=parsed.netloc, sources=sources, outputs=outputs)
    for name in (sources, outputs):
        for page in client.get_paginator("list_object_versions").paginate(Bucket=name):
            for item in page.get("Versions", []) + page.get("DeleteMarkers", []):
                client.delete_object(Bucket=name, Key=item["Key"], VersionId=item["VersionId"])
        client.delete_bucket(Bucket=name)


def make_clip(path, seconds, rate):
    # The HLS ladder maps an audio stream, so the clip needs one or the ladder is skipped.
    subprocess.run(
        [
            "ffmpeg", "-v", "error",
            "-f", "lavfi", "-i", f"testsrc=duration={seconds}:size=640x360:rate={rate}",
            "-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(path),
        ],
        check=True,
    )  # fmt: skip
    return path.read_bytes()


async def submit_real(factory, moto, data):
    body = message()
    key = f"sources/{body['owner_id']}/{body['asset_id']}/source"
    put = moto.client.put_object(Bucket=moto.sources, Key=key, Body=data)
    body["source"] = {
        "bucket": moto.sources,
        "key": key,
        "version_id": put["VersionId"],
        "sha256": hashlib.sha256(data).hexdigest(),
        "size_bytes": len(data),
        "content_type": "video/mp4",
    }
    assert await handle_command(factory, body)
    ((lane, work),) = await work_rows(factory)
    assert lane == "processing-work-short"
    return work


def real_settings(dsn, moto):
    return Settings(
        postgres_dsn=dsn,
        storage_credential_mode="static",
        minio_endpoint=moto.netloc,
        minio_use_ssl=False,
        minio_region="us-east-1",
        minio_access_key="local-test",
        minio_secret_key="local-test",
        minio_output_bucket=moto.outputs,
        ffmpeg_preset="ultrafast",
    )


def stored_keys(moto):
    pages = moto.client.get_paginator("list_object_versions").paginate(Bucket=moto.outputs)
    return sorted(v["Key"] for page in pages for v in page.get("Versions", []))


async def test_local_run_encodes_a_short_clip_for_real_and_commits_one_attempt(
    factory, dsn, moto, tmp_path
):
    work = await submit_real(factory, moto, make_clip(tmp_path / "clip.mp4", 3, 10))
    config = real_settings(dsn, moto)
    result = await short_encoder.invoke(
        {"Records": [sqs_record(work)]}, context("req-real"), factory=factory, settings=config
    )
    assert result == {"batchItemFailures": []}
    job, (attempt,) = await state(factory)
    assert (job.status, attempt.state) == ("done", "succeeded")
    keys = stored_keys(moto)
    prefix = lifecycle.output_prefix(job.id, attempt.id)
    assert keys and all(key.startswith(prefix) for key in keys)
    assert prefix + "primary.mp4" in keys and prefix + "hls/master.m3u8" in keys
    assert (await _binding(factory, attempt.id)).task_name == "lambda-req-real"


async def test_local_run_hands_a_long_clip_to_the_standard_lane_before_encoding_anything(
    factory, dsn, moto, tmp_path
):
    # 70 s at 1 fps is a tiny file, so it is admitted by size at dispatch and refused by duration.
    work = await submit_real(factory, moto, make_clip(tmp_path / "long.mp4", 70, 1))
    result = await short_encoder.invoke(
        {"Records": [sqs_record(work)]},
        context("req-long"),
        factory=factory,
        settings=real_settings(dsn, moto),
    )
    assert result == {"batchItemFailures": []}
    job, (first, second) = await state(factory)
    assert (first.state, second.state, job.status) == ("abandoned", "queued", "queued")
    assert stored_keys(moto) == [], "nothing was encoded or uploaded"
    assert [queue for queue, _ in await work_rows(factory)][-1] == "processing-work"
