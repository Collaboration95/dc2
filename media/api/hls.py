"""Playlist-body/segment-redirect behavior extracted from app/api/hls.py."""

import re
from uuid import UUID

from fastapi import APIRouter
from fastapi.responses import RedirectResponse, Response

from media.api.deps import CurrentUser, Session
from media.errors import MediaError
from media.repositories.assets import get_asset
from media.services.lifecycle import live_job
from media.services.processing_client import Peer
from media.services.storage import Store

router = APIRouter(prefix="/jobs", tags=["hls"])
_HLS_PATH = re.compile(r"^(?:v[0-9]{1,2}/)?[A-Za-z0-9_-]+\.(?:m3u8|ts)$")


def safe_hls_path(path):
    if not _HLS_PATH.fullmatch(path):
        raise MediaError(404, "not found")
    return path


@router.get("/{job_id}/hls/{path:path}")
async def part(
    job_id: UUID, path: str, user: CurrentUser, session: Session, storage: Store, peer: Peer
):
    asset = await get_asset(session, job_id, user.id, lock=True)
    safe = safe_hls_path(path)
    if asset.submission_state != "submitted":
        raise MediaError(404, "not found")
    job = await live_job(peer, asset)
    output = next((o for o in job.outputs if o.kind == "hls_manifest"), None)
    if job.status != "done" or output is None:
        raise MediaError(404, "not found")
    prefix = output.object_key.rsplit("/", 1)[0]
    key = f"{prefix}/{safe}"
    if safe.endswith(".m3u8"):
        try:
            body = await storage.read_playlist(key)
        except Exception as exc:
            raise MediaError(404, "not found") from exc
        return Response(
            body,
            media_type="application/vnd.apple.mpegurl",
            headers={"Cache-Control": "private, no-store"},
        )
    return RedirectResponse(await storage.sign_output(key, inline=True), status_code=307)
