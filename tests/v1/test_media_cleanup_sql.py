"""Real PostgreSQL locks/commits with fake versioned storage, no cloud calls.

Select Lead C's existing stack using V1_TEST_MEDIA_DSN. Each test creates and
removes a unique schema; it never touches shared application tables.
"""

import os
from datetime import timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from media import messaging_models, projection_models, upload_models  # noqa: F401
from media.database import Base
from media.errors import MediaError
from media.messaging import consume_result
from media.models import Asset, CleanupIntent, User, now
from media.projections import apply_result
from media.recovery_v1 import cleanup_tombstones
from media.services.v1_lifecycle import tombstone
from media.upload_models import SourceVersion

pytestmark = pytest.mark.integration


@pytest_asyncio.fixture
async def factory():
    dsn = os.environ.get("V1_TEST_MEDIA_DSN")
    if not dsn:
        pytest.skip("Lead C local Media PostgreSQL DSN not provided")
    schema = "b2_cleanup_" + uuid4().hex
    admin = create_async_engine(dsn)
    async with admin.begin() as connection:
        await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_async_engine(dsn, connect_args={"server_settings": {"search_path": schema}})
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    try:
        yield async_sessionmaker(engine, expire_on_commit=False)
    finally:
        await engine.dispose()
        async with admin.begin() as connection:
            await connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        await admin.dispose()


async def seed(factory):
    owner, asset_id = uuid4(), uuid4()
    descriptor = {
        "bucket": "owned-source",
        "key": f"sources/{owner}/{asset_id}/source",
        "version_id": "accepted-v1",
        "sha256": "a" * 64,
        "size_bytes": 10,
        "content_type": "video/mp4",
    }
    async with factory() as session, session.begin():
        session.add(User(id=owner, email=f"{owner}@test.invalid", password_hash="unused"))
        await session.flush()
        session.add(
            Asset(
                id=asset_id,
                owner_id=owner,
                filename="a.mp4",
                source_key=descriptor["key"],
                source_revision=1,
                source_sha256=descriptor["sha256"],
                source_size_bytes=10,
                source_media_type="video/mp4",
                operations=[],
            )
        )
        await session.flush()
        session.add(SourceVersion(asset_id=asset_id, **descriptor))
    return owner, asset_id, descriptor


async def cancel_and_ack(factory, owner, asset_id):
    from media.messaging_models import MediaOutbox

    async with factory() as session:
        await tombstone(session, owner, asset_id)
    async with factory() as session:
        command = await session.scalar(select(MediaOutbox))
        command_id = str(command.message_id)
    ack = {
        "schema_version": 1,
        "message_id": str(uuid4()),
        "kind": "result",
        "owner_id": str(owner),
        "asset_id": str(asset_id),
        "job_id": None,
        "attempt_id": None,
        "source": None,
        "state_version": 0,
        "payload": {
            "status": "cancelled",
            "cancellation_confirmed": True,
            "command_message_id": command_id,
        },
    }
    async with factory() as session:
        await consume_result(session, ack, apply_result)
    return ack


async def force_due(factory, asset_id):
    async with factory() as session, session.begin():
        intent = await session.get(CleanupIntent, asset_id)
        intent.next_try_at = now() - timedelta(seconds=1)


async def test_no_delete_from_published_command_without_ack(factory):
    owner, asset_id, _ = await seed(factory)
    async with factory() as session:
        await tombstone(session, owner, asset_id)
    from media.messaging_models import MediaOutbox

    async with factory() as session, session.begin():
        command = await session.scalar(select(MediaOutbox))
        command.sent_at = now()  # Queue publication is NOT Processing acknowledgement.
    calls = []

    async def remove(*args):
        calls.append(args)

    assert await cleanup_tombstones(factory, SimpleNamespace(remove_source_versions=remove)) == 0
    assert not calls
    async with factory() as session:
        assert (await session.get(CleanupIntent, asset_id)).processing_deleted_at is None


async def test_ack_then_delete_without_asset_or_intent_locks_and_late_replay(factory):
    owner, asset_id, descriptor = await seed(factory)
    ack = await cancel_and_ack(factory, owner, asset_id)
    versions = {"accepted-v1", "overwrite-v2"}
    calls = []

    async def remove(bucket, key):
        assert (bucket, key) == (descriptor["bucket"], descriptor["key"])
        async with factory() as other, other.begin():
            # NOWAIT fails immediately if cleanup retained either row lock.
            await other.scalar(
                select(Asset).where(Asset.id == asset_id).with_for_update(nowait=True)
            )
            intent = await other.scalar(
                select(CleanupIntent)
                .where(CleanupIntent.asset_id == asset_id)
                .with_for_update(nowait=True)
            )
            assert intent.processing_deleted_at is not None
        calls.append(set(versions))
        versions.clear()

    store = SimpleNamespace(remove_source_versions=remove)
    assert await cleanup_tombstones(factory, store) == 1
    assert not versions
    versions.add("late-post-v3")
    await force_due(factory, asset_id)
    assert await cleanup_tombstones(factory, store) == 1
    assert calls == [{"accepted-v1", "overwrite-v2"}, {"late-post-v3"}]
    # Duplicate acknowledgement is durably deduplicated and cannot revive data.
    async with factory() as session:
        assert not await consume_result(session, ack, apply_result)
        intent = await session.get(CleanupIntent, asset_id)
        assert intent.attempts == 2 and intent.source_deleted_at is not None
        assert (await session.get(Asset, asset_id)).deleted_at is not None


async def test_lost_delete_response_retains_retry_and_repeated_delete_is_safe(factory):
    owner, asset_id, _ = await seed(factory)
    await cancel_and_ack(factory, owner, asset_id)
    versions = {"accepted-v1"}
    calls = 0

    async def remove(bucket, key):
        nonlocal calls
        versions.clear()
        calls += 1
        if calls == 1:
            raise OSError("delete applied but reply lost")

    store = SimpleNamespace(remove_source_versions=remove)
    assert await cleanup_tombstones(factory, store) == 0
    async with factory() as session:
        intent = await session.get(CleanupIntent, asset_id)
        assert intent.source_deleted_at is None
        assert intent.last_error == "Source version cleanup unavailable"
    await force_due(factory, asset_id)
    assert await cleanup_tombstones(factory, store) == 1
    async with factory() as session:
        intent = await session.get(CleanupIntent, asset_id)
        assert intent.last_error is None and intent.attempts == 2


async def test_no_job_ack_must_match_persisted_cancel_command(factory):
    owner, asset_id, _ = await seed(factory)
    ack = await cancel_and_ack(factory, owner, asset_id)
    async with factory() as session, session.begin():
        intent = await session.get(CleanupIntent, asset_id)
        intent.processing_deleted_at = None
    ack["message_id"] = str(uuid4())
    ack["payload"]["command_message_id"] = str(uuid4())
    async with factory() as session:
        with pytest.raises(MediaError, match="does not match command"):
            await consume_result(session, ack, apply_result)
    async with factory() as session:
        assert (await session.get(CleanupIntent, asset_id)).processing_deleted_at is None


async def test_stale_scan_cannot_overwrite_new_cleanup_reservation(factory):
    owner, asset_id, _ = await seed(factory)
    await cancel_and_ack(factory, owner, asset_id)

    async def remove(bucket, key):
        async with factory() as session, session.begin():
            intent = await session.get(CleanupIntent, asset_id, with_for_update=True)
            intent.attempts += 1
            intent.next_try_at = now() + timedelta(seconds=120)
            intent.last_error = "Newer scan remains pending"

    assert await cleanup_tombstones(factory, SimpleNamespace(remove_source_versions=remove)) == 1
    async with factory() as session:
        intent = await session.get(CleanupIntent, asset_id)
        assert intent.attempts == 2
        assert intent.source_deleted_at is None
        assert intent.last_error == "Newer scan remains pending"


async def test_existing_job_cancellation_needs_current_version_before_cleanup(factory):
    from media.projection_models import ProcessingProjection
    from media.repositories.assets import fingerprint

    owner, asset_id, descriptor = await seed(factory)
    job_id, attempt_id = uuid4(), uuid4()
    original = {
        "schema_version": 1,
        "message_id": str(uuid4()),
        "kind": "result",
        "owner_id": str(owner),
        "asset_id": str(asset_id),
        "job_id": str(job_id),
        "attempt_id": str(attempt_id),
        "source": descriptor,
        "state_version": 3,
        "payload": {"status": "processing", "attempt_number": 1, "outputs": [], "error": None},
    }
    async with factory() as session:
        await consume_result(session, original, apply_result)
        await tombstone(session, owner, asset_id)
    cancelled = dict(original, message_id=str(uuid4()), state_version=2)
    cancelled["payload"] = {"status": "cancelled", "attempt_number": 1, "outputs": []}
    async with factory() as session:
        await consume_result(session, cancelled, apply_result)
        assert (await session.get(CleanupIntent, asset_id)).processing_deleted_at is None
    cancelled["message_id"], cancelled["state_version"] = str(uuid4()), 4
    async with factory() as session:
        await session.rollback()
        await consume_result(session, cancelled, apply_result)
        intent = await session.get(CleanupIntent, asset_id)
        assert intent.processing_deleted_at is not None
        projection = await session.get(ProcessingProjection, asset_id)
        assert projection.status == "cancelled" and projection.state_version == 4
        assert projection.result_hash == fingerprint(
            {k: v for k, v in cancelled.items() if k != "message_id"}
        )


async def test_native_source_version_deletion_and_late_object_with_moto(factory):
    """Real PostgreSQL + existing Moto + actual Minio delete implementation."""
    import asyncio
    from urllib.parse import urlsplit

    import boto3

    from media.config import Settings
    from media.services.storage import Storage

    endpoint = os.environ.get("V1_TEST_S3_ENDPOINT")
    if not endpoint:
        pytest.skip("Lead C local Moto S3 endpoint not provided")
    parsed = urlsplit(endpoint)
    if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost"}:
        raise ValueError("Cleanup emulator test requires explicit loopback HTTP endpoint")
    client = boto3.client(
        "s3",
        endpoint_url=endpoint,
        region_name="us-east-1",
        aws_access_key_id="local-test",
        aws_secret_access_key="local-test",
    )
    bucket = "b2-cleanup-" + uuid4().hex
    client.create_bucket(Bucket=bucket)
    client.put_bucket_versioning(Bucket=bucket, VersioningConfiguration={"Status": "Enabled"})
    owner, asset_id, descriptor = await seed(factory)
    key = descriptor["key"]
    accepted = client.put_object(Bucket=bucket, Key=key, Body=b"accepted")["VersionId"]
    client.put_object(Bucket=bucket, Key=key, Body=b"overwritten")
    client.put_object(Bucket=bucket, Key=key + "-sibling", Body=b"must-remain")
    storage = Storage(
        Settings(
            postgres_dsn="postgresql+asyncpg://unused:unused@invalid/media_db",
            minio_endpoint=parsed.netloc,
            minio_use_ssl=False,
            minio_region="us-east-1",
            minio_source_bucket=bucket,
            minio_access_key="local-test",
            minio_secret_key="local-test",
        )
    )
    try:
        async with factory() as session, session.begin():
            pin = await session.get(SourceVersion, asset_id)
            pin.bucket, pin.version_id = bucket, accepted
        await cancel_and_ack(factory, owner, asset_id)
        assert await cleanup_tombstones(factory, storage) == 1

        def exact_versions():
            return [
                v
                for v in client.list_object_versions(Bucket=bucket).get("Versions", [])
                if v["Key"] == key
            ]

        assert not await asyncio.to_thread(exact_versions)
        client.put_object(Bucket=bucket, Key=key, Body=b"late-after-delete")
        await force_due(factory, asset_id)
        assert await cleanup_tombstones(factory, storage) == 1
        assert not await asyncio.to_thread(exact_versions)
        sibling = client.get_object(Bucket=bucket, Key=key + "-sibling")
        assert sibling["Body"].read() == b"must-remain"
        sibling["Body"].close()
    finally:
        versions = client.list_object_versions(Bucket=bucket)
        items = versions.get("Versions", []) + versions.get("DeleteMarkers", [])
        if items:
            client.delete_objects(
                Bucket=bucket,
                Delete={
                    "Objects": [
                        {"Key": item["Key"], "VersionId": item["VersionId"]} for item in items
                    ]
                },
            )
        client.delete_bucket(Bucket=bucket)
