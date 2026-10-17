"""Actual worker-process death with DB lease expiry; controlled source peer."""

import asyncio
import hashlib
import os
import sys
import time
from uuid import UUID, uuid4

import httpx
import test_processing_lifecycle as lane
import test_processing_worker as worker_tests
from sqlalchemy import select

from legacy.processing_rq import tasks
from processing import lifecycle, recovery, service
from processing.models import Attempt, Job

asset_ids = lane.asset_ids
factory = lane.factory
postgres = lane.postgres
pytestmark = lane.pytestmark
reserve = lane.reserve
settings = lane.settings
submission = lane.submission
fixture_video = worker_tests.fixture_video


async def test_killed_worker_expires_and_stored_source_retry_encodes(
    factory, submission, fixture_video, tmp_path
):
    submission["source"]["size_bytes"] = len(fixture_video)
    submission["source"]["sha256"] = hashlib.sha256(fixture_video).hexdigest()
    job = await reserve(factory, submission)
    # Exact execute() entry in a separate OS process. Source renewal is held to
    # prove its independent heartbeat while the processing stage cannot finish.
    script = """
import asyncio, httpx, sys
from uuid import UUID
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from legacy.processing_rq.config import get_settings
from legacy.processing_rq.tasks import execute
async def run():
    settings = get_settings().model_copy(update={'lease_seconds': 2, 'heartbeat_seconds': .2})
    engine = create_async_engine(settings.postgres_dsn)
    async def hold(request):
        await asyncio.Event().wait()
    async with httpx.AsyncClient(transport=httpx.MockTransport(hold)) as client:
        await execute(async_sessionmaker(engine, expire_on_commit=False),
                      UUID(sys.argv[1]), UUID(sys.argv[2]), settings, client=client)
    await engine.dispose()
asyncio.run(run())
"""
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-c",
        script,
        str(job.job_id),
        str(job.current_attempt.attempt_id),
        env={
            "PATH": os.environ.get("PATH", ""),
            "PROCESSING_POSTGRES_DSN": os.environ["PROCESSING_POSTGRES_DSN"],
        },
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        async with asyncio.timeout(5):
            while True:  # noqa: ASYNC110 - bounded external DB polling
                async with factory() as session:
                    attempt = await session.get(Attempt, job.current_attempt.attempt_id)
                    if attempt.state == "processing" and attempt.heartbeat_at > attempt.started_at:
                        break
                if process.returncode is not None:
                    raise AssertionError("worker exited before live heartbeat")
                await asyncio.sleep(0.05)
        process.kill()
        await process.wait()
        killed = time.monotonic()
        async with asyncio.timeout(5):
            while not await recovery.recover_expired(factory):  # noqa: ASYNC110
                await asyncio.sleep(0.05)
        assert time.monotonic() - killed < 5
        async with factory() as session:
            retried = await lifecycle.retry_job(
                session, UUID(submission["owner_id"]), job.job_id, uuid4()
            )
        store = worker_tests.Recorder(tmp_path / "outputs")
        async with httpx.AsyncClient(
            transport=worker_tests.peer(submission, fixture_video, [])
        ) as client:
            assert await tasks.execute(
                factory,
                job.job_id,
                retried.current_attempt.attempt_id,
                settings(source_service_token="reverse-test"),
                client=client,
                store=store,
            )
        async with factory() as session:
            result = await service.get_job(session, UUID(submission["owner_id"]), job.job_id)
            attempts = (
                await session.scalars(select(Attempt).where(Attempt.job_id == job.job_id))
            ).all()
            persisted = await session.get(Job, job.job_id)
        assert result.status == "done"
        assert sorted(a.state for a in attempts) == ["abandoned", "succeeded"]
        assert len([o for o in persisted.outputs if o["kind"] == "primary"]) == 1
        assert all(str(retried.current_attempt.attempt_id) in k for k in store.keys)
    finally:
        if process.returncode is None:
            process.kill()
            await process.wait()
