import asyncio
import os

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine

from media import messaging_models, models, projection_models, upload_models  # noqa: F401
from media.config import Settings, get_settings
from media.database import Base, engine_options

# ECS migration tasks receive only their owned migration DSN. Do not resolve or
# require the runtime's SSM secret merely to satisfy Settings' required field.
owned_dsn = os.environ.get("MEDIA_MIGRATION_DSN")
settings = Settings(postgres_dsn=owned_dsn) if owned_dsn else get_settings()
cloud = settings.runtime_mode == "lambda" or settings.storage_credential_mode in {"lambda", "ecs"}
if cloud and not settings.migration_dsn:
    raise ValueError("Cloud Media migrations require owned migration credentials")
dsn = settings.migration_dsn or settings.postgres_dsn
if cloud and any(key.lower().startswith("ssl") for key in make_url(dsn).query):
    raise ValueError("Migration TLS must be configured through owned settings")


def migrate(connection) -> None:
    context.configure(connection=connection, target_metadata=Base.metadata, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


async def online() -> None:
    # A one-shot migration task keeps the verified TLS arguments but not the warm-Lambda
    # pool sizing, which SQLAlchemy rejects alongside NullPool.
    options = {}
    if cloud:
        options["connect_args"] = engine_options(settings, invocation=True)["connect_args"]
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
