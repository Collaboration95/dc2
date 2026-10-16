from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, File, Header, Request, UploadFile

from media.api.deps import CurrentUser, Session
from media.errors import MediaError
from media.schemas.public import Accepted
from media.services import direct_intake, intake, lifecycle
from media.services.processing_client import Peer
from media.services.storage import Store

router = APIRouter(tags=["upload"])
Key = Annotated[UUID | None, Header(alias="Idempotency-Key")]


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


# V1 never accepts media bytes through the API integration.


@router.post("/uploads/reservations", status_code=201)
async def reserve_upload(
    request: direct_intake.ReserveRequest, user: CurrentUser, session: Session, storage: Store
):
    return await direct_intake.reserve(session, storage, user.id, request)


@router.post(
    "/uploads/reservations/{reservation_id}/finalize", status_code=202, response_model=Accepted
)
async def finalize_upload(
    reservation_id: UUID,
    request: direct_intake.FinalizeRequest,
    user: CurrentUser,
    session: Session,
    storage: Store,
):
    asset = await direct_intake.finalize(session, storage, user.id, reservation_id, request)
    return Accepted(job_id=asset.id)
