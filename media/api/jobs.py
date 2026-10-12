from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, Response

from media.api.deps import Config, CurrentUser, Operator, Session
from media.api.uploads import Key
from media.repositories.assets import get_asset, list_assets
from media.schemas.edit import EditRequest
from media.schemas.public import Accepted, PublicJob
from media.services import lifecycle
from media.services.processing_client import Peer
from media.services.storage import Store

router = APIRouter(prefix="/jobs", tags=["jobs"])
admin_router = APIRouter(prefix="/admin/jobs", tags=["admin"])
Limit = Annotated[int, Query(ge=1, le=200)]
Offset = Annotated[int, Query(ge=0)]


@router.get("", response_model=list[PublicJob], response_model_exclude_none=True)
async def listing(
    user: CurrentUser,
    session: Session,
    peer: Peer,
    storage: Store,
    settings: Config,
    limit: Limit = 50,
    offset: Offset = 0,
):
    assets = await list_assets(session, user.id, limit, offset, lock=True)
    return await lifecycle.project_page(assets, peer, storage, settings)


@router.get("/{job_id}", response_model=PublicJob, response_model_exclude_none=True)
async def read(
    job_id: UUID, user: CurrentUser, session: Session, peer: Peer, storage: Store, settings: Config
):
    asset = await get_asset(session, job_id, user.id, lock=True)
    job = await lifecycle.live_job(peer, asset) if asset.submission_state == "submitted" else None
    return await lifecycle.projection(asset, job, storage, settings)


@router.post("/{job_id}/retry", status_code=202, response_model=Accepted)
async def retry(job_id: UUID, user: CurrentUser, session: Session, peer: Peer, key: Key = None):
    retry_id = await lifecycle.reserve_retry(session, user.id, job_id, key)
    asset_id = await lifecycle.dispatch_retry(session, peer, retry_id)
    return Accepted(job_id=asset_id)


@router.post("/{job_id}/edit", status_code=202, response_model=Accepted)
async def edit(
    job_id: UUID,
    request: EditRequest,
    user: CurrentUser,
    session: Session,
    peer: Peer,
    storage: Store,
    key: Key = None,
):
    asset = await lifecycle.edit(session, peer, storage, user.id, job_id, request, key)
    await lifecycle.dispatch(session, peer, storage, asset.id)
    return Accepted(job_id=asset.id)


async def delete(session, peer, storage, job_id, owner_id):
    await lifecycle.tombstone(session, job_id, owner_id)
    try:
        await lifecycle.cleanup(session, peer, storage, job_id)
    except Exception:
        # A durable tombstone is already accepted; reconciliation owns later errors.
        await session.rollback()
    return Response(status_code=204)


@router.delete("/{job_id}", status_code=204)
async def remove(job_id: UUID, user: CurrentUser, session: Session, peer: Peer, storage: Store):
    return await delete(session, peer, storage, job_id, user.id)


@admin_router.get("", response_model=list[PublicJob], response_model_exclude_none=True)
async def admin_listing(
    operator: Operator,
    session: Session,
    peer: Peer,
    storage: Store,
    settings: Config,
    limit: Limit = 50,
    offset: Offset = 0,
):
    assets = await list_assets(session, None, limit, offset, lock=True)
    return await lifecycle.project_page(assets, peer, storage, settings)


@admin_router.delete("/{job_id}", status_code=204)
async def admin_remove(
    job_id: UUID, operator: Operator, session: Session, peer: Peer, storage: Store
):
    return await delete(session, peer, storage, job_id, None)
