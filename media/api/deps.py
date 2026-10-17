import secrets
from typing import Annotated
from uuid import UUID

from fastapi import Depends, Header, Request
from sqlalchemy.ext.asyncio import AsyncSession

from media.config import Settings, get_settings
from media.database import get_session
from media.errors import MediaError
from media.models import User
from media.services.security import COOKIE_NAME, read_token

Session = Annotated[AsyncSession, Depends(get_session)]
Config = Annotated[Settings, Depends(get_settings)]


async def current_user(request: Request, settings: Config) -> User:
    gateway = getattr(request.state, "gateway_v1", False)
    if settings.runtime_mode == "lambda" and not gateway:
        raise MediaError(401, "trusted gateway context required")
    actor = getattr(request.state, "actor", None)
    if gateway and actor is None:
        raise MediaError(401, "trusted gateway context required")
    token = request.cookies.get(COOKIE_NAME)
    try:
        user_id = read_token(token or "", settings)
    except ValueError as exc:
        raise MediaError(401, "not authenticated") from exc
    # A separate dependency session avoids auth SELECT autobegin colliding with
    # domain transactions. Never trust token roles; read the current database role.
    async for session in get_session(request, settings):
        user = await session.get(User, user_id)
    if user is None:
        raise MediaError(401, "not authenticated")
    if gateway:
        from media.authorizer import gateway_role

        if str(user.id) != str(actor.owner_id) or gateway_role(user) != actor.role:
            raise MediaError(401, "gateway identity no longer current")
    return user


CurrentUser = Annotated[User, Depends(current_user)]


async def operator_user(user: CurrentUser) -> User:
    if user.role != "operator":
        raise MediaError(403, "operator role required")
    return user


Operator = Annotated[User, Depends(operator_user)]


async def source_owner(
    settings: Config,
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
