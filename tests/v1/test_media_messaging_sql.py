"""Media inbox/outbox SQL atomicity; same Lead C PostgreSQL, unique schemas."""

import copy
import os
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from delivery.sql import MessageConflict
from media.database import Base
from media.messaging import consume_result, enqueue_submit
from media.messaging_models import MediaInbox, MediaOutbox
from tests.v1.test_delivery import message

pytestmark = pytest.mark.integration


@pytest_asyncio.fixture
async def factory():
    dsn = os.environ.get("V1_TEST_MEDIA_DSN")
    if not dsn:
        pytest.skip("Lead C's isolated Media PostgreSQL DSN not provided")
    schema = "b_media_messaging_" + uuid4().hex
    admin = create_async_engine(dsn)
    async with admin.begin() as connection:
        await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_async_engine(dsn, connect_args={"server_settings": {"search_path": schema}})
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
        await connection.execute(text("CREATE TABLE projection_probe (id uuid PRIMARY KEY)"))
    try:
        yield async_sessionmaker(engine, expire_on_commit=False)
    finally:
        await engine.dispose()
        async with admin.begin() as connection:
            await connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        await admin.dispose()


async def test_finalize_intent_rolls_back_with_adoption_and_commits_once(factory):
    from types import SimpleNamespace

    body = message()
    asset = SimpleNamespace(
        id=UUID(body["asset_id"]),
        owner_id=UUID(body["owner_id"]),
        processing_job_id=None,
        operations=[],
    )
    with pytest.raises(RuntimeError):
        async with factory() as session, session.begin():
            await enqueue_submit(session, asset, body["source"])
            raise RuntimeError("adoption rolled back")
    async with factory() as session:
        assert await session.scalar(select(func.count()).select_from(MediaOutbox)) == 0
    async with factory() as session, session.begin():
        identity = await enqueue_submit(session, asset, body["source"])
    async with factory() as session:
        row = await session.get(MediaOutbox, identity)
        assert row.body["source"] == body["source"]
        assert row.queue == "processing-commands"
        assert row.body["owner_id"] == str(asset.owner_id)


async def test_result_commit_dedupe_and_callback_rollback(factory):
    result = message("result")

    async def apply(session, body):
        await session.execute(
            text("INSERT INTO projection_probe VALUES (:id)"), {"id": UUID(body["message_id"])}
        )

    async with factory() as session:
        assert await consume_result(session, result, apply)
    async with factory() as session:
        assert not await consume_result(session, result, apply)
        assert await session.scalar(text("SELECT count(*) FROM projection_probe")) == 1
    conflict = copy.deepcopy(result)
    conflict["payload"] = {"status": "failed"}
    async with factory() as session:
        with pytest.raises(MessageConflict):
            await consume_result(session, conflict, apply)

    async def broken(session, body):
        await apply(session, body)
        raise RuntimeError("projection rollback")

    failed = {**result, "message_id": str(uuid4())}
    async with factory() as session:
        with pytest.raises(RuntimeError):
            await consume_result(session, failed, broken)
    async with factory() as session:
        assert await session.get(MediaInbox, UUID(failed["message_id"])) is None
        assert await session.scalar(text("SELECT count(*) FROM projection_probe")) == 1
    async with factory() as session:
        assert await consume_result(session, failed, apply)
