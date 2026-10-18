import secrets
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header

from legacy.media_peer.config import LegacyMediaSettings
from media.api.deps import Session
from media.config import get_settings
from media.errors import MediaError
from media.repositories.assets import get_asset, source_descriptor
from media.schemas.public import SourceAccessRequest
from media.services import direct_intake
from media.services.storage import Store

router = APIRouter(prefix="/internal/v1/assets", tags=["source-access"])


async def source_owner(
    settings: Annotated[LegacyMediaSettings, Depends(get_settings)],
    authorization: Annotated[str | None, Header()] = None,
    x_owner_id: Annotated[UUID | None, Header()] = None,
) -> UUID:
    expected = settings.source_service_token.get_secret_value()
    if not expected or not secrets.compare_digest(authorization or "", "Bearer " + expected):
        raise MediaError(401, "invalid service token")
    if x_owner_id is None:
        raise MediaError(401, "owner header required")
    return x_owner_id


SourceOwner = Annotated[UUID, Depends(source_owner)]


@router.post("/{asset_id}/source-access")
async def source_access(
    asset_id: UUID, body: SourceAccessRequest, owner: SourceOwner, session: Session, storage: Store
):
    async with session.begin():
        asset = await get_asset(session, asset_id, owner, lock=True)
        if asset.source_revision != body.revision:
            raise MediaError(409, "source revision does not match")
        try:
            version = await direct_intake.pinned_version(session, asset)
            url, expires = await storage.source_grant(asset.source_key, version)
        except Exception as exc:
            raise MediaError(503, "source access unavailable") from exc
        return {"source_url": url, "expires_at": expires, "source": source_descriptor(asset)}
