"""Processing intake acceptance against a pre-migrated, real PostgreSQL database.

Run with RUN_PROCESSING_TESTS=1, PROCESSING_POSTGRES_DSN (runtime role), and
PROCESSING_SERVICE_TOKEN. No inherited PostgreSQL fixtures, migrations, queue,
or Media Management account rows are needed. Only this module's asset IDs are
removed. Processing imports are deferred so disabled tests can collect before
the new service is installed.
"""

import asyncio
import os
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import bindparam, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

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
    from processing.config import get_settings
    from processing.main import create_app

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


async def committed_rows(postgres, asset_id):
    """Read through a fresh SQL session, never the application's transaction/cache."""
    async with async_sessionmaker(postgres)() as session:
        params = {"asset_id": UUID(asset_id)}
        jobs = (
            (await session.execute(text("SELECT * FROM jobs WHERE asset_id = :asset_id"), params))
            .mappings()
            .all()
        )
        attempts = (
            (
                await session.execute(
                    text(
                        "SELECT a.* FROM attempts a JOIN jobs j ON j.id = a.job_id "
                        "WHERE j.asset_id = :asset_id ORDER BY a.attempt_number"
                    ),
                    params,
                )
            )
            .mappings()
            .all()
        )
    return jobs, attempts


async def assert_single_committed_job(postgres, submission, body):
    jobs, attempts = await committed_rows(postgres, submission["asset_id"])
    assert len(jobs) == len(attempts) == 1
    job, attempt = jobs[0], attempts[0]
    assert str(job["id"]) == body["job_id"]
    assert str(job["owner_id"]) == submission["owner_id"]
    assert job["source"] == submission["source"]
    assert job["operations"] == submission.get("operations", [])
    assert job["status"] == "queued"
    assert job["current_attempt_id"] == attempt["id"]
    assert attempt["job_id"] == job["id"]
    assert str(attempt["id"]) == body["current_attempt"]["attempt_id"]
    assert attempt["attempt_number"] == body["current_attempt"]["number"] == 1
    assert attempt["state"] == body["current_attempt"]["state"] == "queued"
    assert attempt["queued_at"] is not None


async def test_created_response_means_job_and_first_attempt_are_committed(
    client, postgres, submission
):
    response = await client.post(JOBS, json=submission)
    assert response.status_code == 201, response.text
    body = response.json()
    UUID(body["job_id"])
    UUID(body["current_attempt"]["attempt_id"])
    assert body["asset_id"] == submission["asset_id"]
    assert body["owner_id"] == submission["owner_id"]
    assert body["source"] == submission["source"]
    assert body["status"] == "queued"
    assert body["outputs"] == []
    for value in (body["created_at"], body["updated_at"], body["current_attempt"]["queued_at"]):
        assert datetime.fromisoformat(value).tzinfo is not None
    await assert_single_committed_job(postgres, submission, body)
    read = await client.get(f"{JOBS}/{body['job_id']}")
    assert read.status_code == 200, read.text
    assert read.json() == body


async def test_concurrent_identical_submissions_reserve_one_job_and_one_attempt(
    client, postgres, submission
):
    barrier = asyncio.Barrier(8)

    async def submit():
        await barrier.wait()
        return await client.post(JOBS, json=submission)

    # Each request uses the real get_session dependency and its own transaction.
    responses = await asyncio.wait_for(asyncio.gather(*(submit() for _ in range(8))), timeout=30)
    statuses = [response.status_code for response in responses]
    assert sorted(statuses) == [200] * 7 + [201], [response.text for response in responses]
    bodies = [response.json() for response in responses]
    assert len({body["job_id"] for body in bodies}) == 1
    assert len({body["current_attempt"]["attempt_id"] for body in bodies}) == 1
    await assert_single_committed_job(postgres, submission, bodies[0])


async def test_renewed_source_url_and_json_key_order_replay_existing_attempt(
    client, postgres, submission
):
    created = await client.post(JOBS, json=submission)
    assert created.status_code == 201, created.text
    renewed = deepcopy(submission)
    renewed["source_url"] = f"https://renewed.example.test/{submission['asset_id']}?signature=new"
    renewed["source_url_expires_at"] = (datetime.now(UTC) + timedelta(hours=2)).isoformat()
    renewed["source"] = dict(reversed(list(renewed["source"].items())))
    replay = await client.post(JOBS, json=dict(reversed(list(renewed.items()))))
    assert replay.status_code == 200, replay.text
    assert replay.json()["job_id"] == created.json()["job_id"]
    assert replay.json()["current_attempt"] == created.json()["current_attempt"]
    await assert_single_committed_job(postgres, submission, replay.json())


async def test_changed_immutable_source_fields_conflict_without_mutating_job(
    client, postgres, submission
):
    created = await client.post(JOBS, json=submission)
    assert created.status_code == 201, created.text
    for field, changed_value in (
        ("revision", 2),
        ("sha256", "b" * 64),
        ("size_bytes", 2048),
        ("media_type", "video/webm"),
    ):
        changed = deepcopy(submission)
        changed["source"][field] = changed_value
        conflict = await client.post(JOBS, json=changed)
        assert conflict.status_code == 409, (field, conflict.text)
        assert conflict.json()["error"]
    replay = await client.post(JOBS, json=submission)
    assert replay.status_code == 200, replay.text
    assert replay.json() == created.json()
    await assert_single_committed_job(postgres, submission, replay.json())


async def test_changed_operation_parameters_or_order_conflict(client, postgres, submission):
    submission["operations"] = [
        {"operation": "clip", "params": {"start": 0, "end": 3}},
        {"operation": "downscale", "params": {"height": 360}},
    ]
    created = await client.post(JOBS, json=submission)
    assert created.status_code == 201, created.text
    changed = deepcopy(submission)
    changed["operations"][0]["params"]["end"] = 4
    reordered = deepcopy(submission)
    reordered["operations"].reverse()
    for payload in (changed, reordered):
        conflict = await client.post(JOBS, json=payload)
        assert conflict.status_code == 409, conflict.text
    await assert_single_committed_job(postgres, submission, created.json())


async def test_existing_asset_cannot_be_replayed_by_another_owner(client, postgres, submission):
    created = await client.post(JOBS, json=submission)
    assert created.status_code == 201, created.text
    other = deepcopy(submission)
    other["owner_id"] = str(uuid4())
    response = await client.post(JOBS, json=other, headers={"X-Owner-Id": other["owner_id"]})
    assert response.status_code == 404, response.text
    assert created.json()["job_id"] not in response.text
    await assert_single_committed_job(postgres, submission, created.json())


async def test_header_and_body_owner_must_match_before_inserting(client, postgres, submission):
    response = await client.post(JOBS, json=submission, headers={"X-Owner-Id": str(uuid4())})
    assert response.status_code == 404, response.text
    assert await committed_rows(postgres, submission["asset_id"]) == ([], [])
    # A rejected owner must not bind the submission guard to the wrong owner.
    accepted = await client.post(JOBS, json=submission)
    assert accepted.status_code == 201, accepted.text
    await assert_single_committed_job(postgres, submission, accepted.json())


async def test_source_asset_must_match_submission_asset(client, postgres, submission):
    malformed = deepcopy(submission)
    malformed["source"]["asset_id"] = str(uuid4())
    response = await client.post(JOBS, json=malformed)
    assert response.status_code == 422, response.text
    assert response.json()["detail"]
    assert await committed_rows(postgres, submission["asset_id"]) == ([], [])


async def test_new_app_and_session_pool_read_and_replay_durable_job(
    client, application, postgres, headers, submission
):
    from processing.config import get_settings
    from processing.main import create_app

    created = await client.post(JOBS, json=submission)
    assert created.status_code == 201, created.text
    await assert_single_committed_job(postgres, submission, created.json())
    # Drop all of this app's connections and cached settings before reconstructing it.
    await application.state.engine.dispose()
    application.state.engine = None
    get_settings.cache_clear()
    restarted = create_app()
    assert restarted is not application
    try:
        async with restarted.router.lifespan_context(restarted):
            async with AsyncClient(
                transport=ASGITransport(app=restarted),
                base_url="http://processing.test",
                headers=headers,
            ) as fresh_client:
                read = await fresh_client.get(f"{JOBS}/{created.json()['job_id']}")
                replay = await fresh_client.post(JOBS, json=submission)
        assert read.status_code == 200, read.text
        assert replay.status_code == 200, replay.text
        assert read.json() == replay.json() == created.json()
        await assert_single_committed_job(postgres, submission, replay.json())
    finally:
        engine = getattr(restarted.state, "engine", None)
        if engine is not None:
            await engine.dispose()


@pytest.mark.parametrize("malformation", ["source", "operations", "unknown-field"])
async def test_malformed_input_is_rejected_without_rows(client, postgres, submission, malformation):
    malformed = deepcopy(submission)
    if malformation == "source":
        malformed["source"].update(revision=0, size_bytes=0, sha256="invalid")
    elif malformation == "operations":
        malformed["operations"] = [{"operation": "clip", "params": {"start": 5, "end": 2}}]
    else:
        malformed["unexpected"] = "not in the SubmitJob contract"
    response = await client.post(JOBS, json=malformed)
    assert response.status_code == 422, response.text
    assert response.json()["detail"]
    assert await committed_rows(postgres, submission["asset_id"]) == ([], [])


async def test_service_authentication_is_required_for_submit_and_read(
    application, postgres, submission
):
    async with AsyncClient(
        transport=ASGITransport(app=application), base_url="http://processing.test"
    ) as unauthenticated:
        for authorization in (None, "Bearer invalid-acceptance-test-token"):
            request_headers = {"X-Owner-Id": submission["owner_id"]}
            if authorization is not None:
                request_headers["Authorization"] = authorization
            submitted = await unauthenticated.post(JOBS, json=submission, headers=request_headers)
            read = await unauthenticated.get(f"{JOBS}/{uuid4()}", headers=request_headers)
            assert submitted.status_code == 401, submitted.text
            assert read.status_code == 401, read.text
    assert await committed_rows(postgres, submission["asset_id"]) == ([], [])


async def test_get_hides_other_owners_jobs_and_unknown_ids(client, submission):
    created = await client.post(JOBS, json=submission)
    assert created.status_code == 201, created.text
    hidden = await client.get(
        f"{JOBS}/{created.json()['job_id']}", headers={"X-Owner-Id": str(uuid4())}
    )
    absent = await client.get(f"{JOBS}/{uuid4()}")
    assert hidden.status_code == absent.status_code == 404
    assert hidden.json() == absent.json()
    assert submission["owner_id"] not in hidden.text


async def test_batch_read_filters_owners_and_omits_missing_assets(client, submission, asset_ids):
    created = await client.post(JOBS, json=submission)
    assert created.status_code == 201, created.text
    asset_ids.append(uuid4())
    other = deepcopy(submission)
    other["asset_id"] = other["source"]["asset_id"] = str(asset_ids[-1])
    other["owner_id"] = str(uuid4())
    other_created = await client.post(JOBS, json=other, headers={"X-Owner-Id": other["owner_id"]})
    assert other_created.status_code == 201, other_created.text
    query = {"asset_ids": f"{submission['asset_id']},{other['asset_id']},{uuid4()}"}
    response = await client.get(JOBS, params=query)
    assert response.status_code == 200, response.text
    assert response.json() == [created.json()]
    other_response = await client.get(JOBS, params=query, headers={"X-Owner-Id": other["owner_id"]})
    assert other_response.status_code == 200, other_response.text
    assert other_response.json() == [other_created.json()]
