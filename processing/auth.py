from secrets import compare_digest
from typing import Annotated
from uuid import UUID

from fastapi import Depends, Header, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from processing.config import Settings, get_settings
from processing.errors import ProcessingError

bearer = HTTPBearer(auto_error=False, scheme_name="MediaServiceToken")


def require_service_token(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> None:
    expected = settings.service_token.get_secret_value()
    if not expected.strip():
        raise ProcessingError(503, "Processing service authentication is not configured")
    if credentials is None or not compare_digest(
        credentials.credentials.encode(), expected.encode()
    ):
        raise ProcessingError(401, "Missing or invalid service credentials")


def get_owner_id(
    _: Annotated[None, Depends(require_service_token)],
    owner_id: Annotated[UUID, Header(alias="X-Owner-Id")],
) -> UUID:
    return owner_id


def gateway_actor(request: Request):
    """Resolve only adapter-injected identity; HTTP headers confer no authority."""
    from contracts.v1 import Actor, ContractError

    actor = getattr(request.state, "actor", None)
    if getattr(request.state, "gateway_v1", False) is not True or not isinstance(actor, Actor):
        raise ProcessingError(401, "Missing or invalid trusted context")
    try:
        Actor.from_context(actor.to_context())
    except ContractError as exc:
        raise ProcessingError(401, "Missing or invalid trusted context") from exc
    return actor
