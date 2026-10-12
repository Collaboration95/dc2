"""Real PostgreSQL and FFmpeg; HTTP peer is controlled, not full Media integration."""

import asyncio
import hashlib
import shutil
import subprocess
from datetime import UTC, datetime, timedelta
from uuid import UUID

import httpx
import pytest
import test_processing_lifecycle as lane

from processing import service
from processing.worker import tasks

asset_ids = lane.asset_ids
factory = lane.factory
postgres = lane.postgres
pytestmark = lane.pytestmark
reserve = lane.reserve
settings = lane.settings
submission = lane.submission


class Recorder:
    def __init__(self, directory):
        self.directory = directory
        self.keys = []

    async def put(self, key, path, media_type, kind):
        self.keys.append(key)
        destination = self.directory / key
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(path, destination)
        return {
            "kind": kind,
            "object_key": key,
            "media_type": media_type,
            "size_bytes": path.stat().st_size,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }


@pytest.fixture
def fixture_video(tmp_path):
    path = tmp_path / "source.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=160x120:rate=10",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:sample_rate=44100",
            "-t",
            "0.6",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-y",
            str(path),
        ],
        check=True,
        timeout=10,
        capture_output=True,
    )
    return path.read_bytes()


def peer(submission, content, requests, deny_first=False):
    def respond(request):
        requests.append(request)
        if request.method == "POST":
            assert request.headers["X-Owner-Id"] == submission["owner_id"]
            assert request.headers["Authorization"] == "Bearer reverse-test"
            return httpx.Response(
                200,
                json={
                    "source_url": "http://source.test/private",
                    "expires_at": (datetime.now(UTC) + timedelta(minutes=5)).isoformat(),
                    "source": submission["source"],
                },
            )
        if deny_first and sum(x.method == "GET" for x in requests) == 1:
            return httpx.Response(403)
        return httpx.Response(200, content=content)

    return httpx.MockTransport(respond)


@pytest.mark.parametrize("conversion", [None, "mkv", "mp3"])
async def test_real_worker_short_encode_outputs(
    factory, submission, fixture_video, tmp_path, conversion
):
    submission["source"]["size_bytes"] = len(fixture_video)
    submission["source"]["sha256"] = hashlib.sha256(fixture_video).hexdigest()
    submission["source_url_expires_at"] = "2020-01-01T00:00:00Z"
    if conversion:
        submission["operations"] = [{"operation": "convert", "params": {"format": conversion}}]
    job = await reserve(factory, submission)
    requests = []
    store = Recorder(tmp_path / "output")
    cfg = settings(source_service_token="reverse-test")
    async with httpx.AsyncClient(
        transport=peer(submission, fixture_video, requests, True)
    ) as client:
        assert await tasks.execute(
            factory, job.job_id, job.current_attempt.attempt_id, cfg, client=client, store=store
        )
    async with factory() as session:
        result = await service.get_job(session, UUID(submission["owner_id"]), job.job_id)
    assert result.status == "done"
    assert sum(r.method == "POST" for r in requests) == 2
    primary = next(o for o in result.outputs if o.kind == "primary")
    encoded = store.directory / primary.object_key
    await asyncio.to_thread(
        subprocess.run,
        ["ffmpeg", "-v", "error", "-i", str(encoded), "-f", "null", "-"],
        check=True,
        capture_output=True,
        timeout=10,
    )
    if conversion is None:
        manifest = next(o for o in result.outputs if o.kind == "hls_manifest")
        playlist = store.directory / manifest.object_key
        assert "#EXTM3U" in playlist.read_text()
        await asyncio.to_thread(
            subprocess.run,
            ["ffmpeg", "-v", "error", "-i", str(playlist), "-f", "null", "-"],
            check=True,
            capture_output=True,
            timeout=10,
        )
    else:
        assert len(result.outputs) == 1
    assert await tasks.execute(factory, job.job_id, job.current_attempt.attempt_id, cfg) is False


async def test_real_worker_source_digest_failure(factory, submission, fixture_video, tmp_path):
    submission["source"]["size_bytes"] = len(fixture_video)
    job = await reserve(factory, submission)
    store = Recorder(tmp_path / "output")
    async with httpx.AsyncClient(transport=peer(submission, fixture_video, [])) as client:
        assert await tasks.execute(
            factory,
            job.job_id,
            job.current_attempt.attempt_id,
            settings(source_service_token="reverse-test"),
            client=client,
            store=store,
        )
    async with factory() as session:
        read = await service.get_job(session, UUID(submission["owner_id"]), job.job_id)
    assert read.status == "failed" and not store.keys
