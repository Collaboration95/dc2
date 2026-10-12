"""Media-owned persistence. Callers choose explicit transaction boundaries."""

import hashlib
import json
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from media.errors import MediaError
from media.models import Asset, RequestKey


def fingerprint(value: dict) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def source_descriptor(asset: Asset) -> dict:
    return {
        "asset_id": str(asset.id),
        "revision": asset.source_revision,
        "sha256": asset.source_sha256,
        "size_bytes": asset.source_size_bytes,
        "media_type": asset.source_media_type,
    }


async def get_asset(
    session: AsyncSession,
    asset_id: UUID,
    owner_id: UUID | None,
    *,
    include_deleted=False,
    lock=False,
) -> Asset:
    query = select(Asset).where(Asset.id == asset_id)
    if owner_id is not None:
        query = query.where(Asset.owner_id == owner_id)
    if not include_deleted:
        query = query.where(Asset.deleted_at.is_(None))
    if lock:
        query = query.with_for_update()
    asset = await session.scalar(query.execution_options(populate_existing=True))
    if asset is None:
        raise MediaError(404, "not found")
    return asset


async def replay(
    session: AsyncSession, owner_id: UUID, operation: str, key: UUID | None, digest: str
) -> Asset | None:
    if key is None:
        return None
    request = await session.get(RequestKey, (owner_id, operation, key))
    if request is None:
        return None
    asset = await get_asset(session, request.asset_id, owner_id, include_deleted=True)
    if asset.deleted_at:
        raise MediaError(410, "previously accepted item is deleted")
    if request.request_hash != digest:
        raise MediaError(409, "idempotency key used for a different request")
    return asset


async def list_assets(session, owner_id, limit, offset):
    query = select(Asset).where(Asset.deleted_at.is_(None))
    if owner_id is not None:
        query = query.where(Asset.owner_id == owner_id)
    return list(
        await session.scalars(
            query.order_by(Asset.created_at.desc(), Asset.id).limit(limit).offset(offset)
        )
    )
