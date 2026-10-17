from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Header

from media.api.deps import CurrentUser, Session
from media.schemas.public import Accepted
from media.services import direct_intake
from media.services.storage import Store

router = APIRouter(tags=["upload"])
Key = Annotated[UUID | None, Header(alias="Idempotency-Key")]

# V1 never accepts media bytes through the API integration: sources are PUT straight to S3
# against a reservation, then finalized here.


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
