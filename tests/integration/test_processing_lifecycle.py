"""Processing lifecycle acceptance against a pre-migrated, real PostgreSQL database.

Run with RUN_PROCESSING_TESTS=1, PROCESSING_POSTGRES_DSN (runtime role), and
PROCESSING_SERVICE_TOKEN. No inherited PostgreSQL fixtures, migrations, queue,
or Media Management account rows are needed. Only this module's asset IDs are
removed. Processing imports are deferred so disabled tests can collect before
the new service is installed.
"""

import asyncio
import os
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import bindparam, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from processing import lifecycle, service
from processing.config import Settings
from processing.models import Attempt, Job
from processing.schemas import SubmitJob

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_PROCESSING_TESTS") != "1",
    reason="set RUN_PROCESSING_TESTS=1 to run Processing PostgreSQL acceptance tests",
)

JOBS = "/internal/v1/jobs"


@pytest.fixture
def asset_ids():
    return [uuid4()]


@pytest.fixture
def submission(asset_ids):
    asset_id = str(asset_ids[0])
    return {
        "asset_id": asset_id,
        "owner_id": str(uuid4()),
        "source": {
            "asset_id": asset_id,
            "revision": 1,
            "sha256": "a" * 64,
            "size_bytes": 1024,
            "media_type": "video/mp4",
        },
        "source_url": f"https://source.example.test/{asset_id}?signature=original",
        "source_url_expires_at": (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
    }


@pytest_asyncio.fixture
async def postgres(asset_ids):
    for name in ("PROCESSING_POSTGRES_DSN", "PROCESSING_SERVICE_TOKEN"):
        if not os.environ.get(name):
            pytest.fail(f"RUN_PROCESSING_TESTS=1 requires {name}", pytrace=False)
    url = make_url(os.environ["PROCESSING_POSTGRES_DSN"])
    assert url.get_backend_name() in {"postgres", "postgresql"}, "PostgreSQL is required"
    engine = create_async_engine(url.set(drivername="postgresql+asyncpg"), poolclass=NullPool)
    try:
        # Fail on missing migrations; these tests must not create their own schema.
        async with engine.connect() as connection:
            await connection.execute(text("SELECT id, current_attempt_id FROM jobs LIMIT 0"))
            await connection.execute(text("SELECT id, job_id FROM attempts LIMIT 0"))
            await connection.execute(text("SELECT asset_id FROM submission_guards LIMIT 0"))
        try:
            yield engine
        finally:
            # The current-attempt FK is deferred. Delete both sides in one commit.
            async with engine.begin() as connection:
                for sql in (
                    "DELETE FROM cleanup_intents WHERE job_id IN "
                    "(SELECT id FROM jobs WHERE asset_id IN :asset_ids)",
                    "DELETE FROM retry_requests WHERE job_id IN "
                    "(SELECT id FROM jobs WHERE asset_id IN :asset_ids)",
                    "DELETE FROM submission_guards WHERE asset_id IN :asset_ids",
                    "DELETE FROM attempts WHERE job_id IN "
                    "(SELECT id FROM jobs WHERE asset_id IN :asset_ids)",
                    "DELETE FROM jobs WHERE asset_id IN :asset_ids",
                ):
                    await connection.execute(
                        text(sql).bindparams(bindparam("asset_ids", expanding=True)),
                        {"asset_ids": asset_ids},
                    )
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def application(postgres):
    from legacy.processing_rq.main import create_app
    from processing.config import get_settings

    get_settings.cache_clear()
    app = create_app()
    try:
        async with app.router.lifespan_context(app):
            yield app
    finally:
        engine = getattr(app.state, "engine", None)
        if engine is not None:
            await engine.dispose()
        get_settings.cache_clear()


@pytest.fixture
def headers(submission):
    return {
        "Authorization": f"Bearer {os.environ['PROCESSING_SERVICE_TOKEN']}",
        "X-Owner-Id": submission["owner_id"],
    }


@pytest_asyncio.fixture
async def client(application, headers):
    async with AsyncClient(
        transport=ASGITransport(app=application), base_url="http://processing.test", headers=headers
    ) as client:
        yield client


@pytest.fixture
def factory(postgres):
    return async_sessionmaker(postgres, expire_on_commit=False)


async def reserve(factory, submission):
    request = SubmitJob.model_validate(submission)
    async with factory() as session:
        job, _ = await service.submit_job(session, request.owner_id, request)
    return job


def settings(**kw):
    return Settings(postgres_dsn="postgresql://unused@localhost/processing_db", **kw)


def output(work):
    return [
        {
            "kind": "primary",
            "object_key": lifecycle.output_prefix(work.job_id, work.attempt_id) + "primary.mp4",
            "media_type": "video/mp4",
            "size_bytes": 42,
            "sha256": "b" * 64,
        }
    ]


async def test_claim_once_current_live_fences_and_db_clock(factory, submission):
    job = await reserve(factory, submission)
    claims = await asyncio.gather(
        *(
            lifecycle.claim(factory, job.job_id, job.current_attempt.attempt_id, settings())
            for _ in range(8)
        )
    )
    assert sum(x is not None for x in claims) == 1
    work = next(x for x in claims if x is not None)
    assert await lifecycle.heartbeat(factory, work, settings())
    with pytest.raises(ValueError):
        await lifecycle.finish(factory, work, outputs=[])
    with pytest.raises(ValueError):
        await lifecycle.finish(
            factory, work, outputs=[{**output(work)[0], "object_key": "foreign"}]
        )
    assert await lifecycle.finish(factory, work, outputs=output(work))
    assert not await lifecycle.finish(factory, work, error="late failure")
    assert not await lifecycle.heartbeat(factory, work, settings())
    async with factory() as session:
        read = await service.get_job(session, UUID(submission["owner_id"]), job.job_id)
    assert read.status == "done" and len(read.outputs) == 1


async def test_retry_replay_concurrent_and_stale_failure(factory, submission):
    job = await reserve(factory, submission)
    old = await lifecycle.claim(factory, job.job_id, job.current_attempt.attempt_id, settings())
    assert await lifecycle.finish(factory, old, error="Processing interrupted")
    owner, retry_id = UUID(submission["owner_id"]), uuid4()

    async def retry():
        async with factory() as session:
            return await lifecycle.retry_job(session, owner, job.job_id, retry_id)

    results = await asyncio.gather(*(retry() for _ in range(8)))
    assert len({x.current_attempt.attempt_id for x in results}) == 1
    current = results[0]
    assert current.current_attempt.number == 2
    work = await lifecycle.claim(
        factory, current.job_id, current.current_attempt.attempt_id, settings()
    )
    assert not await lifecycle.finish(factory, old, outputs=output(old))
    assert not await lifecycle.finish(factory, old, error="stale failure")
    assert await lifecycle.finish(factory, work, outputs=output(work))
    replay = await retry()
    assert replay.status == "done" and replay.current_attempt.number == 2
    async with factory() as session:
        with pytest.raises(Exception, match="Only failed jobs"):
            await lifecycle.retry_job(session, owner, job.job_id, uuid4())
    async with factory() as session:
        assert (
            len((await session.scalars(select(Attempt).where(Attempt.job_id == job.job_id))).all())
            == 2
        )


@pytest.mark.parametrize("first", ["cancel", "submit", "concurrent"])
async def test_cancel_guard_in_both_race_orders(factory, submission, first):
    owner, asset = UUID(submission["owner_id"]), UUID(submission["asset_id"])

    async def cancel():
        async with factory() as session:
            await lifecycle.cancel_asset(session, owner, asset)

    async def submit():
        try:
            return await reserve(factory, submission)
        except Exception as exc:
            assert getattr(exc, "status_code", None) == 410

    if first == "submit":
        await submit()
        await cancel()
    elif first == "cancel":
        await cancel()
    else:
        await asyncio.gather(cancel(), submit())
    await cancel()
    assert await submit() is None
    async with factory() as session:
        job = await session.scalar(select(Job).where(Job.asset_id == asset))
        if job is not None:
            assert job.deleted_at is not None
            assert (
                await lifecycle.claim(factory, job.id, job.current_attempt_id, settings()) is None
            )
    async with factory() as session:
        with pytest.raises(Exception) as exc:
            await lifecycle.cancel_asset(session, uuid4(), asset)
        assert exc.value.status_code == 404


async def test_retry_cancel_http_auth_and_contract(client, factory, submission):
    created = await client.post(JOBS, json=submission)
    jid = created.json()["job_id"]
    aid = created.json()["current_attempt"]["attempt_id"]
    bad = await client.post(f"{JOBS}/{jid}/retry", json={"retry_request_id": str(uuid4())})
    assert bad.status_code == 409
    hidden = await client.post(
        f"{JOBS}/{jid}/retry",
        json={"retry_request_id": str(uuid4())},
        headers={"X-Owner-Id": str(uuid4())},
    )
    assert hidden.status_code == 404
    work = await lifecycle.claim(factory, UUID(jid), UUID(aid), settings())
    assert await lifecycle.finish(factory, work, error="Processing interrupted")
    response = await client.post(f"{JOBS}/{jid}/retry", json={"retry_request_id": str(uuid4())})
    assert response.status_code == 202 and response.json()["current_attempt"]["number"] == 2
    deleted = await client.delete(f"/internal/v1/assets/{submission['asset_id']}/job")
    assert deleted.status_code == 204 and not deleted.content
    assert (await client.get(f"{JOBS}/{jid}")).status_code == 404
    assert (await client.post(JOBS, json=submission)).status_code == 410


async def test_lease_expiry_fences_success_failure_and_heartbeat(factory, submission):
    job = await reserve(factory, submission)
    work = await lifecycle.claim(factory, job.job_id, job.current_attempt.attempt_id, settings())
    async with factory() as session, session.begin():
        await session.execute(
            text(
                "UPDATE attempts SET lease_expires_at = clock_timestamp() "
                "- interval '1 second' WHERE id=:id"
            ),
            {"id": work.attempt_id},
        )
    assert not await lifecycle.finish(factory, work, outputs=output(work))
    assert not await lifecycle.finish(factory, work, error="late")
    assert not await lifecycle.heartbeat(factory, work, settings())
