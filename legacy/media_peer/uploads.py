"""The multipart upload route: media bytes through the API, then a synchronous Processing call."""

from typing import Annotated

from fastapi import APIRouter, File, Request, UploadFile

from legacy.media_peer import lifecycle
from legacy.media_peer.processing_client import Peer
from media.api.deps import CurrentUser, Session
from media.api.uploads import Key
from media.errors import MediaError
from media.schemas.public import Accepted
from media.services import intake
from media.services.storage import Store

router = APIRouter(tags=["upload"])


@router.post("/upload", status_code=202, response_model=Accepted, deprecated=True)
async def upload(
    request: Request,
    file: Annotated[UploadFile, File()],
    user: CurrentUser,
    session: Session,
    storage: Store,
    peer: Peer,
    key: Key = None,
):
    if getattr(request.state, "gateway_v1", False):
        raise MediaError(410, "V1 requires direct upload reservations")
    asset = await intake.upload(session, storage, user.id, file, key)
    await lifecycle.dispatch(session, peer, storage, asset.id)
    return Accepted(job_id=asset.id)
