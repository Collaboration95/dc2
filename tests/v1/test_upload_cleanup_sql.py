"""Expired-upload rescans against real PostgreSQL: ordered, bounded, backing off, retiring.

Opt in with V1_TEST_MEDIA_DSN (an asyncpg DSN that may create schemas). Storage is a fake
so each test states the SQL behaviour it protects; S3 behaviour has its own tests in
test_direct_intake_s3.py. Time moves by rewriting stored timestamps, never by sleeping.
"""

import asyncio
import importlib.util
import os
import time
from datetime import timedelta
from pathlib import Path
from uuid import uuid4

import pytest
import pytest_asyncio
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from sqlalchemy import inspect, select, text, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from media import messaging_models, projection_models, upload_models  # noqa: F401
from media.database import Base
from media.models import User, now
from media.services import direct_intake
from media.upload_models import UploadReservation

pytestmark = pytest.mark.integration

MIGRATIONS = Path(direct_intake.__file__).parents[1] / "migrations"


@pytest_asyncio.fixture
async def database():
    dsn = os.environ.get("V1_TEST_MEDIA_DSN")
    if not dsn:
        pytest.skip("V1_TEST_MEDIA_DSN (real Media PostgreSQL) not provided")
    schema = "upload_cleanup_" + uuid4().hex
    admin = create_async_engine(dsn)
    async with admin.begin() as connection:
        await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_async_engine(dsn, connect_args={"server_settings": {"search_path": schema}})
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    try:
        yield engine
    finally:
        await engine.dispose()
        async with admin.begin() as connection:
            await connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        await admin.dispose()


@pytest.fixture
def factory(database):
    return async_sessionmaker(database, expire_on_commit=False)


class FakeStorage:
    def __init__(self, observe=None):
        self.scanned, self.failing, self.observe = [], False, observe

    async def delete_direct_upload(self, target, *, preserve_version=None):
        if self.observe:
            await self.observe(target)
        self.scanned.append((target.key, preserve_version))
        if self.failing:
            raise RuntimeError("storage unavailable with https://signed.example/?X-Amz=secret")


def scanned_ids(storage):
    return [key.split("/")[2] for key, _ in storage.scanned]


async def seed(factory, count, *, expired_for=timedelta(minutes=5)):
    """Expired, never-scanned reservations; staggered so the batch order is observable."""
    owner = uuid4()
    async with factory() as session, session.begin():
        session.add(User(id=owner, email=f"{owner}@example.com", password_hash="unused"))
    ids = []
    async with factory() as session, session.begin():
        current = now()
        for index in range(count):
            row_id = uuid4()
            ids.append(str(row_id))
            session.add(
                UploadReservation(
                    id=row_id,
                    owner_id=owner,
                    request_id=uuid4(),
                    request_hash="a" * 64,
                    asset_id=uuid4(),
                    filename="clip.mp4",
                    bucket="source",
                    key=f"staging/{owner}/{row_id}/source",
                    content_type="video/mp4",
                    size_bytes=1,
                    sha256="b" * 64,
                    expires_at=current - expired_for,
                    cleanup_next_at=current - timedelta(seconds=100 - index),
                )
            )
    return ids


async def row(factory, row_id):
    async with factory() as session:
        return await session.get(UploadReservation, row_id)


async def make_due(factory):
    async with factory() as session, session.begin():
        await session.execute(
            update(UploadReservation).values(cleanup_next_at=now() - timedelta(seconds=1))
        )


async def test_batch_is_ordered_by_due_time_and_bounded_by_the_limit(factory):
    ids = await seed(factory, 4)
    storage = FakeStorage()
    assert await direct_intake.cleanup_expired_uploads(factory, storage, limit=2) == 2
    assert scanned_ids(storage) == ids[:2]
    # The unscanned rows are next in line; the scanned pair is backing off.
    assert await direct_intake.cleanup_expired_uploads(factory, storage, limit=2) == 2
    assert scanned_ids(storage)[2:] == ids[2:]
    assert await direct_intake.cleanup_expired_uploads(factory, storage, limit=2) == 0


async def test_an_unexpired_reservation_is_never_scanned(factory):
    (early,) = await seed(factory, 1, expired_for=timedelta(minutes=-10))
    storage = FakeStorage()
    assert await direct_intake.cleanup_expired_uploads(factory, storage) == 0
    assert storage.scanned == []
    assert (await row(factory, early)).cleanup_attempts == 0


async def test_rescans_back_off_until_the_row_is_made_due_again(factory):
    (row_id,) = await seed(factory, 1)
    storage = FakeStorage()
    for attempt, wait in enumerate((60, 120, 240), start=1):
        assert await direct_intake.cleanup_expired_uploads(factory, storage) == 1
        saved = await row(factory, row_id)
        assert saved.cleanup_attempts == attempt
        remaining = (saved.cleanup_next_at - now()).total_seconds()
        assert wait - 5 < remaining <= wait
        # Immediately again: not due, however often the repair tick fires.
        assert await direct_intake.cleanup_expired_uploads(factory, storage) == 0
        await make_due(factory)
    assert len(storage.scanned) == 3


async def test_a_clean_scan_past_the_horizon_retires_and_a_failed_one_never_does(factory):
    (row_id,) = await seed(factory, 1, expired_for=direct_intake.CLEANUP_HORIZON * 2)
    storage = FakeStorage()
    storage.failing = True
    assert await direct_intake.cleanup_expired_uploads(factory, storage) == 0
    failed = await row(factory, row_id)
    assert failed.cleanup_retired_at is None
    assert failed.cleanup_attempts == 1
    assert failed.cleanup_next_at > now()  # Failures back off too.

    await make_due(factory)
    storage.failing = False
    assert await direct_intake.cleanup_expired_uploads(factory, storage) == 1
    assert (await row(factory, row_id)).cleanup_retired_at is not None
    await make_due(factory)
    assert await direct_intake.cleanup_expired_uploads(factory, storage) == 0
    assert len(storage.scanned) == 2


async def test_a_clean_scan_before_the_horizon_keeps_the_row_armed(factory):
    (row_id,) = await seed(factory, 1, expired_for=direct_intake.CLEANUP_HORIZON / 2)
    assert await direct_intake.cleanup_expired_uploads(factory, FakeStorage()) == 1
    assert (await row(factory, row_id)).cleanup_retired_at is None


async def test_storage_io_runs_without_holding_the_row_lock(factory, database):
    (row_id,) = await seed(factory, 1)
    seen = []

    async def observe(target):
        # A second connection must be able to lock the row while the scan is in flight.
        async with async_sessionmaker(database)() as other, other.begin():
            await other.execute(
                select(UploadReservation.id)
                .where(UploadReservation.id == row_id)
                .with_for_update(nowait=True)
            )
            seen.append(target.key)

    assert await direct_intake.cleanup_expired_uploads(factory, FakeStorage(observe)) == 1
    assert len(seen) == 1


async def test_concurrent_invocations_scan_a_row_once(factory):
    await seed(factory, 1)
    gate = asyncio.Event()

    async def hold(_):
        await gate.wait()

    storage = FakeStorage(hold)
    first = asyncio.create_task(direct_intake.cleanup_expired_uploads(factory, storage))
    await asyncio.sleep(0.3)  # The first invocation now holds a lease and is in storage I/O.
    assert await direct_intake.cleanup_expired_uploads(factory, storage) == 0
    gate.set()
    assert await first == 1
    assert len(storage.scanned) == 1


async def test_a_scan_cut_off_by_the_deadline_leaves_a_lease_not_a_retirement(factory):
    (row_id,) = await seed(factory, 1, expired_for=direct_intake.CLEANUP_HORIZON * 2)

    async def hang(_):
        await asyncio.sleep(30)

    result = await direct_intake.cleanup_expired_uploads(
        factory, FakeStorage(hang), deadline=time.monotonic() + 0.2
    )
    saved = await row(factory, row_id)
    assert result == 0
    assert saved.cleanup_retired_at is None
    assert saved.cleanup_attempts == 1
    assert saved.cleanup_next_at > now()


async def test_migration_0008_upgrades_downgrades_and_matches_the_model(database):
    spec = importlib.util.spec_from_file_location(
        "media_0008", MIGRATIONS / "versions/0008_upload_cleanup_schedule.py"
    )
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    new = {"cleanup_next_at", "cleanup_attempts", "cleanup_retired_at"}

    def columns(connection):
        return {c["name"] for c in inspect(connection).get_columns("upload_reservations")}

    def indexes(connection):
        return {i["name"] for i in inspect(connection).get_indexes("upload_reservations")}

    def run(connection, step):
        with Operations.context(MigrationContext.configure(connection)):
            getattr(migration, step)()

    async with database.begin() as connection:
        assert new <= await connection.run_sync(columns)  # create_all follows the model
        assert "ix_upload_reservations_cleanup_due" in await connection.run_sync(indexes)
        await connection.run_sync(run, "downgrade")
        assert not new & await connection.run_sync(columns)
        # A row from before the migration must come out due, un-retired and un-attempted.
        owner = uuid4()
        await connection.execute(
            text(
                "INSERT INTO users (id, email, password_hash, role, created_at) "
                "VALUES (:i, :e, 'x', 'user', now())"
            ),
            {"i": owner, "e": f"{owner}@example.com"},
        )
        await connection.execute(
            text(
                "INSERT INTO upload_reservations (id, owner_id, request_id, request_hash, "
                "asset_id, filename, bucket, key, content_type, size_bytes, sha256, "
                "expires_at, created_at, cleanup_checked_at) "
                "VALUES (:i, :o, :r, 'h', :a, 'f', 'b', :k, 'video/mp4', 1, 's', "
                "now(), now(), now())"
            ),
            {"i": uuid4(), "o": owner, "r": uuid4(), "a": uuid4(), "k": f"k/{uuid4()}"},
        )
        await connection.run_sync(run, "upgrade")
        assert new <= await connection.run_sync(columns)
        assert "ix_upload_reservations_cleanup_due" in await connection.run_sync(indexes)
        old = (
            await connection.execute(
                text(
                    "SELECT cleanup_attempts, cleanup_retired_at, cleanup_next_at <= now() "
                    "FROM upload_reservations"
                )
            )
        ).one()
        assert tuple(old) == (0, None, True)
