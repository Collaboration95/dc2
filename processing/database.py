from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from processing.config import Settings, get_settings


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
    return {"ssl": context, "timeout": settings.database_connect_timeout_seconds}


async def get_v1_session(
    request: Request, settings: Annotated[Settings, Depends(get_settings)]
) -> AsyncIterator[AsyncSession]:
    """No persistent pool across Lambda freeze, thaw or fresh asyncio loops."""
    from sqlalchemy.pool import NullPool

    engine = create_async_engine(
        settings.postgres_dsn, poolclass=NullPool, connect_args=v1_connect_args(settings)
    )
    try:
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as session:
            yield session
    finally:
        await engine.dispose()
