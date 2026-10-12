from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from media.config import Settings, get_settings


class Base(DeclarativeBase):
    pass


async def get_session(
    request: Request, settings: Annotated[Settings, Depends(get_settings)]
) -> AsyncIterator[AsyncSession]:
    if getattr(request.app.state, "engine", None) is None:
        request.app.state.engine = create_async_engine(settings.postgres_dsn, pool_pre_ping=True)
    async with async_sessionmaker(request.app.state.engine, expire_on_commit=False)() as session:
        yield session
