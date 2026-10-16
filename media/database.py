"""Owned Media SQL sessions; Lambda connections never survive an invocation."""

import ssl
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.pool import NullPool

from media.config import Settings, get_settings
from runtime_support.settings import credentials_rejected


class Base(DeclarativeBase):
    pass


def engine_options(settings: Settings, *, invocation: bool = False) -> dict:
    options = {"pool_pre_ping": True}
    if invocation or settings.runtime_mode == "lambda":
        if not settings.postgres_ssl_ca:
            raise ValueError("Lambda Media SQL requires a trusted PostgreSQL CA file")
        # create_default_context enables CERT_REQUIRED and hostname verification.
        tls = ssl.create_default_context(cafile=settings.postgres_ssl_ca)
        options.update(poolclass=NullPool, connect_args={"ssl": tls, "timeout": 10})
    return options


@asynccontextmanager
async def invocation_session(settings: Settings) -> AsyncIterator[AsyncSession]:
    engine = create_async_engine(settings.postgres_dsn, **engine_options(settings, invocation=True))
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            yield session
    except Exception as error:
        # A warm container caches the DSN it read from SSM. If the database now rejects
        # it, drop the cache so the next invocation re-reads the rotated secret instead
        # of failing until the environment is recycled. This invocation still fails.
        if credentials_rejected(error):
            get_settings.cache_clear()
        raise
    finally:
        await engine.dispose()


async def get_session(
    request: Request, settings: Annotated[Settings, Depends(get_settings)]
) -> AsyncIterator[AsyncSession]:
    if (
        getattr(getattr(request, "state", None), "gateway_v1", False)
        or settings.runtime_mode == "lambda"
    ):
        async with invocation_session(settings) as session:
            yield session
        return
    if getattr(request.app.state, "engine", None) is None:
        request.app.state.engine = create_async_engine(
            settings.postgres_dsn, **engine_options(settings)
        )
    async with async_sessionmaker(request.app.state.engine, expire_on_commit=False)() as session:
        yield session


async def database_ready(settings: Settings) -> dict:
    """Operator readiness: the one deliberate database touch, never reachable from Gateway.

    The result carries no driver text because the invocation payload is logged.
    """
    from sqlalchemy import text

    try:
        async with invocation_session(settings) as session:
            await session.execute(text("SELECT 1"))
        return {"service": "media", "ready": True}
    except Exception as error:
        if credentials_rejected(error):
            get_settings.cache_clear()
        return {"service": "media", "ready": False, "error": "database unavailable"}
