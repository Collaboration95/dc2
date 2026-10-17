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

from media.config import Settings as MediaSettings
from media.models import Asset
from media.services.lifecycle import projection
from processing import service
from processing.models import Attempt, Job
from processing.worker import tasks
from scripts.dev.contracts import validate_request, validate_response

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


@pytest.mark.parametrize(
    "operation",
    [
        pytest.param(
            {"operation": "crop", "params": {"x": 150, "y": 0, "w": 20, "h": 20}},
            id="out-of-source-crop",
        ),
        pytest.param(
            {"operation": "clip", "params": {"start": 0, "end": 3}},
            id="over-duration-clip",
        ),
    ],
)
async def test_real_worker_source_invalid_edit_has_failed_attempt_and_public_projection(
    factory, submission, fixture_video, tmp_path, operation, monkeypatch
):
    # Static schemas accept these edits; the real 160x120, 0.6s source does not.
    submission["operations"] = [operation]
    submission["source"].update(
        size_bytes=len(fixture_video), sha256=hashlib.sha256(fixture_video).hexdigest()
    )
    validate_request("public", "/jobs/{job_id}/edit", "post", {"operations": [operation]})
    validate_request("processing", "/jobs", "post", submission)
    job = await reserve(factory, submission)
    assert job.status == "queued" and job.current_attempt.state == "queued"
    # Observe the real validator's source-specific error. A generic download or
    # ffprobe failure must not satisfy this geometry regression.
    validator_name = f"validate_{operation['operation']}"
    validator = getattr(tasks, validator_name)
    rejected = []

    def observe_validation(params, probe):
        assert probe.width == 160 and probe.height == 120
        assert 0 < probe.duration_seconds < 3
        try:
            validator(params, probe)
        except ValueError as exc:
            rejected.append(str(exc))
            raise

    monkeypatch.setattr(tasks, validator_name, observe_validation)
    store, requests = Recorder(tmp_path / "output"), []
    async with httpx.AsyncClient(transport=peer(submission, fixture_video, requests)) as client:
        assert await tasks.execute(
            factory,
            job.job_id,
            job.current_attempt.attempt_id,
            settings(source_service_token="reverse-test"),
            client=client,
            store=store,
        )
    expected_error = (
        "crop must fit within the source video's frame"
        if operation["operation"] == "crop"
        else "clip end must not exceed the source video's duration"
    )
    assert rejected == [expected_error]
    async with factory() as session:
        read = await service.get_job(session, UUID(submission["owner_id"]), job.job_id)
        stored_job = await session.get(Job, job.job_id)
        attempt = await session.get(Attempt, job.current_attempt.attempt_id)
        assert stored_job.current_attempt_id == attempt.id == read.current_attempt.attempt_id
        assert attempt.state == "failed" and attempt.error
        assert attempt.started_at is not None and attempt.finished_at is not None
        assert stored_job.status == "failed" and stored_job.outputs == []
    assert read.status == "failed" and read.current_attempt.number == 1
    assert read.error == read.current_attempt.error == attempt.error
    assert read.outputs == [] and store.keys == []
    assert [request.method for request in requests] == ["POST", "GET"]
    validate_response(
        "processing",
        "/jobs/{job_id}",
        "get",
        200,
        read.model_dump(mode="json", exclude_none=True),
    )
    # Exercise the actual MM public projection of the persisted current P result.
    # The MM Asset is in memory here; this is not a live MM database/HTTP claim.
    source = read.source
    asset = Asset(
        id=read.asset_id,
        owner_id=read.owner_id,
        filename="source-edited.mp4",
        source_revision=source.revision,
        source_sha256=source.sha256,
        source_size_bytes=source.size_bytes,
        source_media_type=source.media_type,
        processing_job_id=read.job_id,
        submission_state="submitted",
    )
    public = await projection(
        asset,
        read,
        store,
        MediaSettings(postgres_dsn="postgresql://unused@localhost/media_db", _env_file=None),
    )
    body = public.model_dump(mode="json", exclude_none=True)
    assert body == {
        "id": submission["asset_id"],
        "filename": "source-edited.mp4",
        "status": "failed",
        "submission_status": "submitted",
        "error": attempt.error,
    }
    assert public.output_url is None and public.hls_url is None
    validate_response("public", "/jobs/{job_id}", "get", 200, body)

# Controlled CI selection sample for #165; no test behavior changes.
