from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from processing.config import Settings, get_settings
from runtime_support import lambda_db
from runtime_support.settings import credentials_rejected


class Base(DeclarativeBase):
    pass


async def get_session(
    request: Request, settings: Annotated[Settings, Depends(get_settings)]
) -> AsyncIterator[AsyncSession]:
    # Each application owns its pool; no import-time connections or MM globals.
    if getattr(request.app.state, "engine", None) is None:
        request.app.state.engine = create_async_engine(settings.postgres_dsn, pool_pre_ping=True)
    factory = async_sessionmaker(request.app.state.engine, expire_on_commit=False)
    async with factory() as session:
        yield session


def v1_connect_args(settings: Settings) -> dict:
    """Verify the RDS certificate and hostname; local emulators opt out explicitly."""
    import ssl

    from sqlalchemy.engine import make_url

    url = make_url(settings.postgres_dsn)
    if any(key in url.query for key in ("ssl", "sslmode", "sslrootcert")):
        raise ValueError("Configure database TLS through owned settings")
    context = (
        ssl.create_default_context(cafile=settings.database_ca_file)
        if settings.database_tls
        else False
    )
    return {
        "ssl": context,
        "timeout": settings.database_connect_timeout_seconds,
        "server_settings": lambda_db.SERVER_SETTINGS,
    }


def v1_engine_options(settings: Settings) -> dict:
    """One small pooled connection per warm Lambda environment (see runtime_support.lambda_db)."""
    return {
        **lambda_db.POOL_OPTIONS,
        "pool_pre_ping": True,
        "pool_recycle": lambda_db.POOL_RECYCLE_SECONDS,
        "connect_args": v1_connect_args(settings),
    }


async def v1_engine(settings: Settings):
    return await lambda_db.shared_engine(
        "processing",
        settings.postgres_dsn,
        lambda: create_async_engine(settings.postgres_dsn, **v1_engine_options(settings)),
    )


async def get_v1_session(
    request: Request, settings: Annotated[Settings, Depends(get_settings)]
) -> AsyncIterator[AsyncSession]:
    """Reuses the warm environment's engine; only the session is per-request."""
    engine = await v1_engine(settings)
    try:
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as session:
            yield session
    except Exception as error:
        # See media.database.invocation_session: rotated credentials self-heal on the
        # next invocation because the cached DSN and pooled engine are discarded.
        if credentials_rejected(error):
            get_settings.cache_clear()
        await lambda_db.release_after("processing", error)
        raise


async def database_ready(settings: Settings) -> dict:
    """Operator readiness: the one deliberate database touch, never reachable from Gateway.

    The result carries no driver text because the invocation payload is logged.
    """
    from sqlalchemy import text

    try:
        engine = await v1_engine(settings)
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
        return {"service": "processing", "ready": True}
    except Exception as error:
        if credentials_rejected(error):
            get_settings.cache_clear()
        await lambda_db.release_after("processing", error)
        return {"service": "processing", "ready": False, "error": "database unavailable"}
