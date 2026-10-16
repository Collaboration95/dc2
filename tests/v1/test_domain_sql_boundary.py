"""Real owned SQL transactions across the command/result boundary.

Opt in with both V1_TEST_{MEDIA,PROCESSING}_DSN pointing to Lead C's sole
PostgreSQL stack. Each test owns temporary schemas and drops them. Storage is
explicitly a fake: these tests certify neither bytes, queues, Gateway nor AWS.
Metadata creates tables; migration-chain acceptance is tested separately.
"""

import os
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from media import messaging_models, projection_models, upload_models  # noqa: F401
from media.database import Base as MediaBase
from media.messaging import consume_result
from media.messaging_models import MediaInbox, MediaOutbox
from media.models import Asset, User
from media.projection_models import ProcessingProjection
from media.projections import apply_result
from media.services import direct_intake, v1_lifecycle
from processing.database import Base as ProcessingBase
from processing.messaging import claim, finish, handle_command
from processing.messaging_models import ProcessingOutbox
from processing.models import Attempt, Job

pytestmark = pytest.mark.integration
SETTINGS = SimpleNamespace(attempt_timeout_seconds=180, lease_seconds=60)


@asynccontextmanager
async def owned_factory(owner, base):
    dsn = os.environ.get(f"V1_TEST_{owner.upper()}_DSN")
    if not dsn:
        pytest.skip(f"Lead C's isolated {owner} DSN not provided")
    if not dsn.startswith("postgresql+asyncpg://"):
        raise ValueError("Explicit asyncpg DSN required")
    schema = "verify_domain_" + uuid4().hex
    admin = create_async_engine(dsn)
    engine = create_async_engine(dsn, connect_args={"server_settings": {"search_path": schema}})
    try:
        async with admin.begin() as connection:
            await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        async with engine.begin() as connection:
            await connection.run_sync(base.metadata.create_all)
        yield async_sessionmaker(engine, expire_on_commit=False)
    finally:
        await engine.dispose()
        async with admin.begin() as connection:
            await connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        await admin.dispose()


@pytest_asyncio.fixture
async def domains():
    async with owned_factory("media", MediaBase) as media:
        async with owned_factory("processing", ProcessingBase) as processing:
            yield media, processing


async def adopt(media):
    owner = uuid4()
    async with media() as session, session.begin():
        session.add(User(id=owner, email=f"{owner}@example.test", password_hash="fake"))
    store = SimpleNamespace(
        settings=SimpleNamespace(minio_source_bucket="sources"),
        direct_upload_grant=AsyncMock(
            return_value={"method": "POST", "url": "local", "fields": {}}
        ),
        verify_direct_upload=AsyncMock(return_value="fake-immutable-version"),
    )
    request = direct_intake.ReserveRequest(
        request_id=uuid4(),
        filename="clip.mp4",
        content_type="video/mp4",
        size_bytes=123,
        sha256="a" * 64,
    )
    async with media() as session:
        reservation = await direct_intake.reserve(session, store, owner, request)
    async with media() as session:
        asset = await direct_intake.finalize(
            session,
            store,
            owner,
            reservation["reservation_id"],
            direct_intake.FinalizeRequest(request_id=request.request_id),
        )
    async with media() as session:
        command = await session.scalar(select(MediaOutbox))
        assert command.body["source"]["version_id"] == "fake-immutable-version"
        assert await session.get(Asset, asset.id) is not None
    return owner, asset.id, command.body


async def project_results(media, processing):
    async with processing() as session:
        rows = list(
            await session.scalars(
                select(ProcessingOutbox).where(ProcessingOutbox.queue == "media-results")
            )
        )
    # Deliver newest first, then all stale versions, then exact duplicates.
    rows.sort(key=lambda row: row.body["state_version"], reverse=True)
    for row in rows + rows:
        async with media() as session:
            await consume_result(session, row.body, apply_result)
    async with media() as session:
        projection = await session.scalar(select(ProcessingProjection))
        assert len(list(await session.scalars(select(MediaInbox)))) == len(rows)
        return projection


async def test_finalize_command_completion_and_reordered_projection(domains):
    media, processing = domains
    owner, asset_id, command = await adopt(media)
    assert await handle_command(processing, command)
    assert not await handle_command(processing, command)
    async with processing() as session:
        work = await session.scalar(
            select(ProcessingOutbox).where(ProcessingOutbox.queue == "processing-work")
        )
    body = work.body
    bound = await claim(
        processing,
        UUID(body["job_id"]),
        UUID(body["attempt_id"]),
        SETTINGS,
        envelope=body,
        task_name="domain-boundary",
    )
    output = {
        "kind": "primary",
        "object_key": f"jobs/{bound.job_id}/attempts/{bound.attempt_id}/video.mp4",
        "media_type": "video/mp4",
        "size_bytes": 100,
        "sha256": "b" * 64,
    }
    assert await finish(processing, bound, outputs=[output])
    projection = await project_results(media, processing)
    assert projection.asset_id == asset_id and projection.status == "done"
    assert projection.outputs == [output]
    async with media() as session:
        asset = await session.get(Asset, asset_id)
        assert asset.owner_id == owner and asset.processing_job_id == bound.job_id


async def test_stored_source_retry_then_media_delete_dominates_late_results(domains):
    media, processing = domains
    owner, asset_id, command = await adopt(media)
    await handle_command(processing, command)
    async with processing() as session:
        job = await session.scalar(select(Job))
    bound = await claim(
        processing, job.id, job.current_attempt_id, SETTINGS, task_name="domain-boundary-retry"
    )
    assert await finish(processing, bound, error="Curated failure")
    assert (await project_results(media, processing)).status == "failed"
    async with media() as session:
        await v1_lifecycle.retry(session, owner, asset_id, uuid4())
    async with media() as session:
        retry = await session.scalar(
            select(MediaOutbox).where(MediaOutbox.message_id != UUID(command["message_id"]))
        )
    assert retry.body["source"] == command["source"]
    await handle_command(processing, retry.body)
    async with processing() as session:
        job = await session.get(Job, job.id)
        attempt = await session.get(Attempt, job.current_attempt_id)
        assert attempt.attempt_number == 2 and job.status == "queued"
    async with media() as session:
        await v1_lifecycle.tombstone(session, owner, asset_id)
    await project_results(media, processing)
    async with media() as session:
        assert (await session.get(Asset, asset_id)).deleted_at is not None
        cancel = await session.scalar(
            select(MediaOutbox).where(
                MediaOutbox.queue == "processing-commands",
                MediaOutbox.body["kind"].astext == "cancel",
            )
        )
    await handle_command(processing, cancel.body)
    async with processing() as session:
        assert (await session.get(Job, job.id)).deleted_at is not None
