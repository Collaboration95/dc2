from uuid import UUID

from fastapi import APIRouter

from media.api.deps import Session, SourceOwner
from media.errors import MediaError
from media.repositories.assets import get_asset, source_descriptor
from media.schemas.public import SourceAccessRequest
from media.services.storage import Store

router = APIRouter(prefix="/internal/v1/assets", tags=["source-access"])


@router.post("/{asset_id}/source-access")
async def source_access(
    asset_id: UUID, body: SourceAccessRequest, owner: SourceOwner, session: Session, storage: Store
):
    async with session.begin():
        asset = await get_asset(session, asset_id, owner, lock=True)
        if asset.source_revision != body.revision:
            raise MediaError(409, "source revision does not match")
        try:
            url, expires = await storage.source_grant(asset.source_key)
        except Exception as exc:
            raise MediaError(503, "source access unavailable") from exc
        return {"source_url": url, "expires_at": expires, "source": source_descriptor(asset)}
