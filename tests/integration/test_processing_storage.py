"""Opt-in real MinIO encode using PUT-only worker and List/Delete cleanup roles.

Uses test-only MEDIA_MINIO_* fields to seed/read fixture data, never in worker
settings. No Media database or real Media service is involved.
"""

import asyncio
import hashlib
import io
import os
import subprocess
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import httpx
import pytest
import test_processing_lifecycle as lane
import test_processing_worker as worker_tests
from minio import Minio
from minio.error import S3Error
from pydantic import SecretStr

from legacy.processing_rq import tasks
from processing import lifecycle, recovery, service
from processing.worker.storage import OutputStore

asset_ids = lane.asset_ids
factory = lane.factory
postgres = lane.postgres
pytestmark = lane.pytestmark
reserve = lane.reserve
settings = lane.settings
submission = lane.submission
fixture_video = worker_tests.fixture_video


@pytest.fixture
def storage_settings():
    if os.getenv("RUN_PROCESSING_STORAGE_TESTS") != "1":
        pytest.skip("set RUN_PROCESSING_STORAGE_TESTS=1 for real private MinIO acceptance")
    required = (
        "PROCESSING_MINIO_ENDPOINT",
        "PROCESSING_MINIO_ACCESS_KEY",
        "PROCESSING_MINIO_SECRET_KEY",
        "PROCESSING_MINIO_OUTPUT_BUCKET",
        "MEDIA_MINIO_ACCESS_KEY",
        "MEDIA_MINIO_SECRET_KEY",
        "MEDIA_MINIO_SOURCE_BUCKET",
        "CLEANUP_MINIO_ACCESS_KEY",
        "CLEANUP_MINIO_SECRET_KEY",
    )
    for name in required:
        if not os.environ.get(name):
            pytest.fail("Storage acceptance requires " + name)
    return lane.Settings()


async def test_real_write_only_worker_encode_cleanup_and_privileges(
    factory, submission, fixture_video, storage_settings, tmp_path
):
    cfg = storage_settings.model_copy(update={"source_service_token": SecretStr("reverse-test")})
    media = Minio(
        cfg.minio_endpoint,
        secure=cfg.minio_use_ssl,
        region=cfg.minio_region,
        access_key=os.environ["MEDIA_MINIO_ACCESS_KEY"],
        secret_key=os.environ["MEDIA_MINIO_SECRET_KEY"],
    )
    source_bucket = os.environ["MEDIA_MINIO_SOURCE_BUCKET"]
    key = "processing-fixture/" + uuid4().hex
    await asyncio.to_thread(
        media.put_object, source_bucket, key, io.BytesIO(fixture_video), len(fixture_video)
    )
    writer = OutputStore(cfg)
    cleanup_cfg = cfg.model_copy(
        update={
            "minio_access_key": type(cfg.minio_access_key)(os.environ["CLEANUP_MINIO_ACCESS_KEY"]),
            "minio_secret_key": type(cfg.minio_secret_key)(os.environ["CLEANUP_MINIO_SECRET_KEY"]),
        }
    )
    cleaner = recovery.CleanupStore(cleanup_cfg)
    job = None
    network = httpx.AsyncHTTPTransport()

    async def peer(request):
        if request.method == "POST":
            assert request.headers["Authorization"] == "Bearer reverse-test"
            assert request.headers["X-Owner-Id"] == submission["owner_id"]
            url = media.presigned_get_object(source_bucket, key, expires=timedelta(minutes=5))
            return httpx.Response(
                200,
                json={
                    "source_url": url,
                    "expires_at": (datetime.now(UTC) + timedelta(minutes=5)).isoformat(),
                    "source": submission["source"],
                },
            )
        return await network.handle_async_request(request)

    try:
        submission["source"]["size_bytes"] = len(fixture_video)
        submission["source"]["sha256"] = hashlib.sha256(fixture_video).hexdigest()
        job = await reserve(factory, submission)
        async with httpx.AsyncClient(transport=httpx.MockTransport(peer)) as client:
            assert await tasks.execute(
                factory,
                job.job_id,
                job.current_attempt.attempt_id,
                cfg,
                client=client,
                store=writer,
            )
        async with factory() as session:
            result = await service.get_job(session, UUID(submission["owner_id"]), job.job_id)
        assert result.status == "done" and len(result.outputs) == 2
        primary = next(o for o in result.outputs if o.kind == "primary")
        reply = await asyncio.to_thread(
            media.get_object, cfg.minio_output_bucket, primary.object_key
        )
        try:
            path = tmp_path / "primary.mp4"
            path.write_bytes(reply.read())
        finally:
            reply.close()
            reply.release_conn()
        await asyncio.to_thread(
            subprocess.run,
            ["ffmpeg", "-v", "error", "-i", str(path), "-f", "null", "-"],
            check=True,
            timeout=10,
            capture_output=True,
        )
        # PUT succeeded above; output HEAD/Get and source Get must be denied.
        for call in (
            lambda: writer.client.stat_object(writer.bucket, primary.object_key),
            lambda: writer.client.get_object(writer.bucket, primary.object_key),
            lambda: writer.client.get_object(source_bucket, key),
            lambda: cleaner.client.get_object(cleaner.bucket, primary.object_key),
        ):
            with pytest.raises(S3Error) as denied:
                await asyncio.to_thread(call)
            assert denied.value.code == "AccessDenied"
        async with factory() as session:
            await lifecycle.cancel_asset(
                session, UUID(submission["owner_id"]), UUID(submission["asset_id"])
            )
        assert await recovery.cleanup_outputs(factory, cfg, store=cleaner) >= 1
        assert not await asyncio.to_thread(
            lambda: list(
                cleaner.client.list_objects(
                    cleaner.bucket,
                    prefix=lifecycle.output_prefix(job.job_id, job.current_attempt.attempt_id),
                )
            )
        )
        # A late PUT can outlive cancellation. The retained intent must scan again.
        prefix = lifecycle.output_prefix(job.job_id, job.current_attempt.attempt_id)
        await writer.put(prefix + "late.mp4", path, "video/mp4", "primary")
        async with factory() as session, session.begin():
            intent = await session.get(recovery.CleanupIntent, job.current_attempt.attempt_id)
            intent.next_try_at = await lifecycle.db_now(session)
        assert await recovery.cleanup_outputs(factory, cfg, store=cleaner) >= 1
        assert not await asyncio.to_thread(
            lambda: list(cleaner.client.list_objects(cleaner.bucket, prefix=prefix))
        )
        with pytest.raises(S3Error) as denied:
            await asyncio.to_thread(cleaner.client.remove_object, source_bucket, key)
        assert denied.value.code == "AccessDenied"
        # Cleanup cannot read/remove the seeded Media source; it remains intact.
        reply = await asyncio.to_thread(media.get_object, source_bucket, key)
        try:
            assert reply.read() == fixture_video
        finally:
            reply.close()
            reply.release_conn()
    finally:
        await network.aclose()
        await asyncio.to_thread(media.remove_object, source_bucket, key)
        if job is not None:
            await cleaner.delete_prefix(
                lifecycle.output_prefix(job.job_id, job.current_attempt.attempt_id)
            )
