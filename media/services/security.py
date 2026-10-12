"""Cookie JWT/bcrypt behavior extracted from app/services/security.py."""

from datetime import UTC, datetime, timedelta
from uuid import UUID

import bcrypt
import jwt

from media.config import Settings

COOKIE_NAME = "access_token"
# A valid cost-12 dummy hash prevents unknown-user login from skipping bcrypt work.
DUMMY_HASH = "$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TtxM.yzBAbZs7H/.N5/uFs2FkW8K"


def hash_password(password: str) -> str:
    if len(password.encode()) > 72:
        raise ValueError("password must be at most 72 bytes")
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode(), password_hash.encode())
    except (ValueError, TypeError):
        return False


def secret(settings: Settings) -> str:
    value = settings.jwt_secret.get_secret_value()
    if len(value.encode()) < 32:
        raise RuntimeError("MEDIA_JWT_SECRET must contain at least 32 bytes")
    return value


def issue_token(user_id: UUID, settings: Settings) -> str:
    now = datetime.now(UTC)
    return jwt.encode(
        {"sub": str(user_id), "iat": now, "exp": now + timedelta(seconds=settings.jwt_ttl_seconds)},
        secret(settings),
        algorithm="HS256",
    )


def read_token(token: str, settings: Settings) -> UUID:
    try:
        data = jwt.decode(
            token,
            secret(settings),
            algorithms=["HS256"],
            options={"require": ["sub", "exp", "iat"]},
        )
        return UUID(data["sub"])
    except (jwt.PyJWTError, ValueError, TypeError, KeyError) as exc:
        raise ValueError("not authenticated") from exc
