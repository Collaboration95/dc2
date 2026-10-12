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
