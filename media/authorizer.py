"""Media-owned HTTP API simple authorizer. Configure Gateway cache TTL to zero."""

import asyncio
from http.cookies import CookieError, SimpleCookie

from contracts.v1 import Actor
from media.config import get_settings
from media.database import invocation_session
from media.models import User
from media.services.security import COOKIE_NAME, read_token


def gateway_role(user: User) -> str:
    # Existing users and operators both publish. Operator privilege is checked
    # independently against the current owned row, never a Gateway role claim.
    if user.role not in {"user", "operator"}:
        raise ValueError("unsupported current role")
    return "publisher"


def session_token(event: dict) -> str:
    cookies = event.get("cookies", [])
    if not isinstance(cookies, list) or not all(isinstance(value, str) for value in cookies):
        raise ValueError("invalid cookies")
    jar = SimpleCookie()
    seen = []
    for value in cookies:
        part = SimpleCookie()
        part.load(value)
        if COOKIE_NAME in part:
            seen.append(part[COOKIE_NAME].value)
        jar.load(value)
    if len(seen) != 1:
        raise ValueError("missing or ambiguous session cookie")
    return jar[COOKIE_NAME].value


async def authorize(event: dict) -> dict:
    denied = {"isAuthorized": False}
    try:
        if event.get("version") != "2.0" or not isinstance(event.get("requestContext"), dict):
            return denied
        settings = get_settings()
        owner_id = read_token(session_token(event), settings)
        async with invocation_session(settings) as session:
            user = await session.get(User, owner_id)
            if user is None:
                return denied
            actor = Actor(owner_id=str(user.id), role=gateway_role(user))
        return {"isAuthorized": True, "context": actor.to_context()}
    except (ValueError, CookieError):
        return denied
    except Exception:
        # Fail closed without leaking credentials, cookies or database errors.
        return denied


def handler(event, context=None):
    return asyncio.run(authorize(event))
