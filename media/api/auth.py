from fastapi import APIRouter, Response
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from starlette.concurrency import run_in_threadpool

from media.api.deps import Config, CurrentUser, Session
from media.errors import MediaError
from media.models import User
from media.schemas.public import Credentials, UserResponse
from media.services.security import (
    COOKIE_NAME,
    DUMMY_HASH,
    hash_password,
    issue_token,
    verify_password,
)

router = APIRouter(prefix="/auth", tags=["auth"])


def set_cookie(response: Response, user: User, settings) -> None:
    response.set_cookie(
        COOKIE_NAME,
        issue_token(user.id, settings),
        max_age=settings.jwt_ttl_seconds,
        httponly=True,
        secure=True,
        samesite="strict",
        path="/",
    )


@router.post("/register", status_code=201, response_model=UserResponse)
async def register(body: Credentials, session: Session, response: Response, settings: Config):
    password_hash = await run_in_threadpool(hash_password, body.password)
    user = User(email=str(body.email).lower(), password_hash=password_hash)
    try:
        async with session.begin():
            session.add(user)
            await session.flush()
    except IntegrityError:
        return Response(status_code=409)
    set_cookie(response, user, settings)
    return user


@router.post("/login", response_model=UserResponse)
async def login(body: Credentials, session: Session, response: Response, settings: Config):
    # Release the read connection before bcrypt waits for CPU/thread-pool capacity.
    # Session expiry is disabled, so the selected identity/hash remain readable.
    async with session.begin():
        user = await session.scalar(select(User).where(User.email == str(body.email).lower()))
    valid = await run_in_threadpool(
        verify_password, body.password, user.password_hash if user else DUMMY_HASH
    )
    if not valid or user is None:
        raise MediaError(401, "invalid email or password")
    set_cookie(response, user, settings)
    return user


@router.post("/logout", status_code=204)
async def logout():
    response = Response(status_code=204)
    response.delete_cookie(COOKIE_NAME, path="/", httponly=True, secure=True, samesite="strict")
    return response


@router.get("/me", response_model=UserResponse)
async def me(user: CurrentUser):
    return user
