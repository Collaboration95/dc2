from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, File, Header, UploadFile

from media.api.deps import CurrentUser, Session
from media.schemas.public import Accepted
from media.services import intake, lifecycle
from media.services.processing_client import Peer
from media.services.storage import Store

router = APIRouter(tags=["upload"])
Key = Annotated[UUID | None, Header(alias="Idempotency-Key")]


@router.post("/upload", status_code=202, response_model=Accepted)
async def upload(
    file: Annotated[UploadFile, File()],
    user: CurrentUser,
    session: Session,
    storage: Store,
    peer: Peer,
    key: Key = None,
):
    asset = await intake.upload(session, storage, user.id, file, key)
    await lifecycle.dispatch(session, peer, storage, asset.id)
    return Accepted(job_id=asset.id)
