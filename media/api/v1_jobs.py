"""V1 public assets: local projections and trusted durable commands only."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, Response

from media.api.deps import Config, CurrentUser, Operator, Session
from media.api.uploads import Key
from media.projections import public_job
from media.repositories.assets import get_asset, list_assets
from media.schemas.edit import EditRequest
from media.schemas.public import Accepted, PublicJob
from media.services import v1_lifecycle
from media.services.storage import Store

router = APIRouter(prefix="/jobs", tags=["jobs"])
admin_router = APIRouter(prefix="/admin/jobs", tags=["admin"])
Limit = Annotated[int, Query(ge=1, le=200)]
Offset = Annotated[int, Query(ge=0)]


async def page(session, owner_id, storage, settings, limit, offset):
    assets = await list_assets(session, owner_id, limit, offset)
    return [await public_job(session, asset, storage, settings) for asset in assets]


@router.get("", response_model=list[PublicJob], response_model_exclude_none=True)
async def listing(
    user: CurrentUser,
    session: Session,
    storage: Store,
    settings: Config,
    limit: Limit = 50,
    offset: Offset = 0,
):
    return await page(session, user.id, storage, settings, limit, offset)


@router.get("/{job_id}", response_model=PublicJob, response_model_exclude_none=True)
async def read(job_id: UUID, user: CurrentUser, session: Session, storage: Store, settings: Config):
    asset = await get_asset(session, job_id, user.id)
    return await public_job(session, asset, storage, settings)


@router.post("/{job_id}/retry", status_code=202, response_model=Accepted)
async def retry(job_id: UUID, user: CurrentUser, session: Session, key: Key = None):
    asset = await v1_lifecycle.retry(session, user.id, job_id, key)
    return Accepted(job_id=asset.id)


@router.post("/{job_id}/edit", status_code=202, response_model=Accepted)
async def edit(
    job_id: UUID,
    request: EditRequest,
    user: CurrentUser,
    session: Session,
    storage: Store,
    key: Key = None,
):
    asset = await v1_lifecycle.edit(session, storage, user.id, job_id, request, key)
    return Accepted(job_id=asset.id)


@router.delete("/{job_id}", status_code=204)
async def remove(job_id: UUID, user: CurrentUser, session: Session):
    await v1_lifecycle.tombstone(session, user.id, job_id)
    return Response(status_code=204)


@admin_router.get("", response_model=list[PublicJob], response_model_exclude_none=True)
async def admin_listing(
    operator: Operator,
    session: Session,
    storage: Store,
    settings: Config,
    limit: Limit = 50,
    offset: Offset = 0,
):
    return await page(session, None, storage, settings, limit, offset)


@admin_router.delete("/{job_id}", status_code=204)
async def admin_remove(job_id: UUID, operator: Operator, session: Session):
    await v1_lifecycle.tombstone(session, None, job_id)
    return Response(status_code=204)
