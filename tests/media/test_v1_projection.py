"""No-network unit evidence; real SQL/SQS/encoding integration is separate."""

from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse

from media import projections
from media.api import deps, v1_hls, v1_jobs
from media.config import get_settings
from media.database import get_session
from media.errors import MediaError
from media.projection_models import ProcessingProjection
from media.repositories.assets import fingerprint
from media.schemas.edit import EditRequest
from media.services import v1_lifecycle
from media.services.storage import get_storage


@pytest.fixture
def event(asset):
    attempt = uuid4()
    return {
        "schema_version": 1,
        "message_id": str(uuid4()),
        "kind": "result",
        "owner_id": str(asset.owner_id),
        "asset_id": str(asset.id),
        "job_id": str(asset.processing_job_id),
        "attempt_id": str(attempt),
        "state_version": 3,
        "source": {
            "bucket": "sources",
            "key": asset.source_key,
            "version_id": "v1",
            "sha256": asset.source_sha256,
            "size_bytes": asset.source_size_bytes,
            "content_type": asset.source_media_type,
        },
        "payload": {
            "status": "done",
            "attempt_number": 1,
            "error": None,
            "outputs": [
                {
                    "kind": "primary",
                    "object_key": f"jobs/{asset.processing_job_id}/attempts/{attempt}/video.mp4",
                    "media_type": "video/mp4",
                    "size_bytes": 100,
                    "sha256": "b" * 64,
                },
                {
                    "kind": "hls_manifest",
                    "object_key": f"jobs/{asset.processing_job_id}/attempts/{attempt}/master.m3u8",
                    "media_type": "application/vnd.apple.mpegurl",
                },
            ],
        },
    }


def current(event):
    from uuid import UUID

    return ProcessingProjection(
        asset_id=UUID(event["asset_id"]),
        job_id=UUID(event["job_id"]),
        attempt_id=UUID(event["attempt_id"]),
        attempt_number=event["payload"]["attempt_number"],
        state_version=event["state_version"],
        status=event["payload"]["status"],
        source=event["source"],
        outputs=event["payload"]["outputs"],
        error=None,
        result_hash=fingerprint({k: v for k, v in event.items() if k != "message_id"}),
    )


def test_duplicate_conflicting_version_and_reordering(event):
    saved = current(event)
    duplicate = deepcopy(event)
    duplicate["message_id"] = str(uuid4())
    assert not projections.validate_transition(saved, duplicate)
    stale = deepcopy(event)
    stale["state_version"] -= 1
    assert not projections.validate_transition(saved, stale)
    conflict = deepcopy(event)
    conflict["payload"]["status"] = "failed"
    with pytest.raises(MediaError, match="conflicting result state version"):
        projections.validate_transition(saved, conflict)


def test_attempt_and_terminal_fencing(event):
    saved = current(event)
    event["state_version"] += 1
    event["payload"]["attempt_number"] = 0
    assert not projections.validate_transition(saved, event)
    event["payload"]["attempt_number"] = 1
    with pytest.raises(MediaError, match="terminal attempt"):
        projections.validate_transition(saved, event)
    event["attempt_id"] = str(uuid4())
    with pytest.raises(MediaError, match="conflicting result attempt"):
        projections.validate_transition(saved, event)
    event["payload"]["attempt_number"] = 2
    with pytest.raises(MediaError, match="cannot restart"):
        projections.validate_transition(saved, event)
    saved.status = "failed"
    assert projections.validate_transition(saved, event)


async def test_apply_owned_source_and_tombstone(session, asset, event, monkeypatch):
    monkeypatch.setattr(projections, "get_asset", AsyncMock(return_value=asset))
    monkeypatch.setattr(projections, "source_for_asset", AsyncMock(return_value=event["source"]))
    assert await projections.apply_result(session, event)
    saved = session.add.call_args.args[0]
    assert saved.status == "done" and saved.job_id == asset.processing_job_id
    session.get.return_value = saved
    assert not await projections.apply_result(session, event)
    asset.deleted_at = SimpleNamespace()
    event["state_version"] += 1
    assert not await projections.apply_result(session, event)
    assert saved.state_version == 3


async def test_wrong_owner_source_job_and_output_rejected(session, asset, event, monkeypatch):
    owned = AsyncMock(side_effect=MediaError(404, "not found"))
    monkeypatch.setattr(projections, "get_asset", owned)
    with pytest.raises(MediaError, match="not found"):
        await projections.apply_result(session, event)
    monkeypatch.setattr(projections, "get_asset", AsyncMock(return_value=asset))
    monkeypatch.setattr(projections, "source_for_asset", AsyncMock(return_value={}))
    with pytest.raises(MediaError, match="source differs"):
        await projections.apply_result(session, event)
    monkeypatch.setattr(projections, "source_for_asset", AsyncMock(return_value=event["source"]))
    original = event["job_id"]
    event["job_id"] = str(uuid4())
    with pytest.raises(MediaError, match="another Processing job"):
        await projections.apply_result(session, event)
    event["job_id"] = original
    event["payload"]["outputs"][0]["object_key"] = "other-owner/output.mp4"
    with pytest.raises(MediaError, match="outside the accepted attempt"):
        await projections.apply_result(session, event)
    session.add.assert_not_called()


async def test_local_status_hls_and_signed_range_capability(
    session,
    asset,
    event,
    storage,
    settings,
    user,
    monkeypatch,
):
    app = FastAPI()

    @app.exception_handler(MediaError)
    async def media_error(request, exc):
        return JSONResponse({"error": exc.message}, status_code=exc.status_code)

    app.include_router(v1_jobs.router)
    app.include_router(v1_hls.router)
    app.dependency_overrides[deps.current_user] = lambda: user
    app.dependency_overrides[get_session] = lambda: session
    app.dependency_overrides[get_storage] = lambda: storage
    app.dependency_overrides[get_settings] = lambda: settings
    session.get.return_value = current(event)
    monkeypatch.setattr(v1_jobs, "get_asset", AsyncMock(return_value=asset))
    monkeypatch.setattr(v1_jobs, "list_assets", AsyncMock(return_value=[asset]))
    monkeypatch.setattr(v1_hls, "get_asset", AsyncMock(return_value=asset))
    storage.read_playlist.return_value = b"#EXTM3U\nv0/index.m3u8\n"
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app),
        base_url="https://media.test",
    ) as client:
        response = await client.get(f"/jobs/{asset.id}")
        assert response.status_code == 200
        assert response.json()["status"] == "done"
        assert response.json()["processing_job_id"] == str(asset.processing_job_id)
        assert response.json()["output_url"].startswith("https://")
        assert (await client.get("/jobs")).json()[0]["id"] == str(asset.id)
        playlist = await client.get(f"/jobs/{asset.id}/hls/master.m3u8")
        assert playlist.content.startswith(b"#EXTM3U")
        segment = await client.get(f"/jobs/{asset.id}/hls/v0/seg001.ts")
        assert segment.status_code == 307
        # The signed S3 URL supports native Range; no MP4 bytes traverse Lambda.
        storage.sign_output.assert_awaited()
        assert (await client.get(f"/jobs/{asset.id}/hls/v0/invalid.txt")).status_code == 404


async def test_edit_local_projection_adoption_and_submit(
    session,
    asset,
    event,
    storage,
    user,
    monkeypatch,
):
    monkeypatch.setattr(v1_lifecycle, "get_asset", AsyncMock(return_value=asset))
    monkeypatch.setattr(v1_lifecycle, "replay", AsyncMock(return_value=None))
    monkeypatch.setattr(
        v1_lifecycle,
        "read_job",
        AsyncMock(
            return_value=projections.ProjectedJob(
                job_id=asset.processing_job_id,
                status="done",
                outputs=event["payload"]["outputs"],
            )
        ),
    )
    monkeypatch.setattr(v1_lifecycle, "pin_copied_source", AsyncMock(return_value=event["source"]))
    monkeypatch.setattr(v1_lifecycle, "stage", AsyncMock())
    submit = AsyncMock()
    monkeypatch.setattr(v1_lifecycle, "stage_submit", submit)
    session.get.return_value = SimpleNamespace()
    storage.copy_output_source.return_value = (100, "b" * 64)
    request = EditRequest.model_validate(
        {
            "operations": [{"operation": "clip", "params": {"start": 0, "end": 3}}],
        }
    )
    derived = await v1_lifecycle.edit(session, storage, user.id, asset.id, request, uuid4())
    assert derived.source_asset_id == asset.id and derived.id != asset.id
    assert derived.operations == request.stored_operations()
    submit.assert_awaited_once_with(session, derived, event["source"])


async def test_retry_and_cancel_are_commands(session, asset, event, user, monkeypatch):
    monkeypatch.setattr(v1_lifecycle, "get_asset", AsyncMock(return_value=asset))
    monkeypatch.setattr(v1_lifecycle, "replay", AsyncMock(return_value=None))
    monkeypatch.setattr(v1_lifecycle, "source_for_asset", AsyncMock(return_value=event["source"]))
    staged = AsyncMock()
    monkeypatch.setattr(v1_lifecycle, "command", staged)
    saved = current(event)
    saved.status = "failed"
    session.get.return_value = saved
    await v1_lifecycle.retry(session, user.id, asset.id, None)
    first = staged.call_args.kwargs["message_id"]
    await v1_lifecycle.retry(session, user.id, asset.id, None)
    assert staged.call_args.kwargs["message_id"] == first
    await v1_lifecycle.tombstone(session, user.id, asset.id)
    assert asset.deleted_at
    assert staged.call_args.args[2] == "cancel"
    calls = staged.await_count
    await v1_lifecycle.tombstone(session, user.id, asset.id)
    assert staged.await_count == calls


def test_processing_cancel_may_follow_terminal_result(event):
    saved = current(event)
    event["state_version"] += 1
    event["payload"]["status"] = "cancelled"
    event["payload"]["outputs"] = []
    assert projections.validate_transition(saved, event)
