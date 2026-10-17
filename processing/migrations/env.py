import asyncio

from alembic import context
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import create_async_engine

from processing import launcher_models, messaging_models, models  # noqa: F401
from processing.config import get_settings
from processing.database import Base, v1_connect_args

settings = get_settings()
if settings.database_ca_file and not settings.migration_dsn:
    raise ValueError("V1 migrations require owned migration credentials")
dsn = settings.migration_dsn or settings.postgres_dsn


def migrate(connection) -> None:
    context.configure(connection=connection, target_metadata=Base.metadata, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


async def online() -> None:
    options = {}
    if settings.database_ca_file:
        options["connect_args"] = v1_connect_args(settings.model_copy(update={"postgres_dsn": dsn}))
    engine = create_async_engine(dsn, poolclass=pool.NullPool, **options)
    try:
        async with engine.connect() as connection:
            await connection.run_sync(migrate)
    finally:
        await engine.dispose()


if context.is_offline_mode():
    context.configure(url=dsn, target_metadata=Base.metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()
else:
    asyncio.run(online())
