"""Real PostgreSQL locks/commits with fake versioned storage, no cloud calls.

Select Lead C's existing stack using V1_TEST_MEDIA_DSN. Each test creates and
removes a unique schema; it never touches shared application tables.
"""

import asyncio
import os
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from media import messaging_models, projection_models, upload_models  # noqa: F401
from media.database import Base
from media.errors import MediaError
from media.messaging import consume_result
from media.models import Asset, CleanupIntent, StagedObject, User, now
from media.projections import apply_result
from media.recovery_v1 import cleanup_staged_objects, cleanup_tombstones, run_once
from media.services.v1_lifecycle import tombstone
from media.upload_models import SourceVersion, UploadReservation

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
        command = await session.scalar(
            select(MediaOutbox).where(MediaOutbox.body["asset_id"].astext == str(asset_id))
        )
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
        orphan_key = f"sources/{owner}/{uuid4()}/unfinalized"
        client.put_object(Bucket=bucket, Key=orphan_key, Body=b"orphan-version")
        async with factory() as session, session.begin():
            session.add(
                UploadReservation(
                    id=uuid4(),
                    owner_id=owner,
                    request_id=uuid4(),
                    request_hash="b" * 64,
                    asset_id=uuid4(),
                    filename="orphan.mp4",
                    bucket=bucket,
                    key=orphan_key,
                    content_type="video/mp4",
                    size_bytes=14,
                    sha256="c" * 64,
                    expires_at=now() - timedelta(seconds=1),
                )
            )
        settings = SimpleNamespace(
            recovery_batch_size=25, orphan_grace_seconds=3600, minio_source_bucket=bucket
        )
        repaired = await run_once(factory, settings, storage)
        assert repaired == {"cleanup": 1, "uploads": 1, "staged": 0}
        assert not [
            v
            for v in client.list_object_versions(Bucket=bucket).get("Versions", [])
            if v["Key"] == orphan_key
        ]

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


async def test_wrong_owner_ack_cannot_grant_cleanup(factory):
    owner, asset_id, _ = await seed(factory)
    ack = await cancel_and_ack(factory, owner, asset_id)
    async with factory() as session, session.begin():
        intent = await session.get(CleanupIntent, asset_id)
        intent.processing_deleted_at = None
    ack["owner_id"], ack["message_id"] = str(uuid4()), str(uuid4())
    async with factory() as session:
        with pytest.raises(MediaError, match="not found"):
            await consume_result(session, ack, apply_result)
    async with factory() as session:
        assert (await session.get(CleanupIntent, asset_id)).processing_deleted_at is None


async def scan_ok(factory, asset_id, calls=None):
    async def remove(bucket, key):
        if calls is not None:
            calls.append(key)

    await force_due(factory, asset_id)
    return await cleanup_tombstones(factory, SimpleNamespace(remove_source_versions=remove))


async def test_tombstone_rescans_back_off_then_retire_after_the_horizon(factory):
    owner, asset_id, _ = await seed(factory)
    await cancel_and_ack(factory, owner, asset_id)
    for attempts, expected in ((1, 60), (2, 120), (3, 240), (4, 480)):
        assert await scan_ok(factory, asset_id) == 1
        async with factory() as session:
            intent = await session.get(CleanupIntent, asset_id)
            wait = (intent.next_try_at - now()).total_seconds()
        assert intent.attempts == attempts and expected - 2 <= wait <= expected + 1
    # Inside the horizon a clean scan keeps the tombstone scheduled for late writes.
    async with factory() as session, session.begin():
        intent = await session.get(CleanupIntent, asset_id)
        intent.processing_deleted_at = now() - timedelta(hours=12)
    assert await scan_ok(factory, asset_id) == 1
    # A clean scan one horizon after the acknowledgement retires it for good.
    async with factory() as session, session.begin():
        intent = await session.get(CleanupIntent, asset_id)
        intent.processing_deleted_at = now() - timedelta(days=2)
    calls = []
    assert await scan_ok(factory, asset_id, calls) == 0 and not calls
    async with factory() as session:
        assert (await session.get(CleanupIntent, asset_id)).source_deleted_at is not None


async def test_failed_tombstone_scans_never_retire_however_old(factory):
    owner, asset_id, _ = await seed(factory)
    await cancel_and_ack(factory, owner, asset_id)
    async with factory() as session, session.begin():
        intent = await session.get(CleanupIntent, asset_id)
        intent.processing_deleted_at = now() - timedelta(days=30)

    async def broken(bucket, key):
        raise OSError("store unavailable")

    await force_due(factory, asset_id)
    store = SimpleNamespace(remove_source_versions=broken)
    assert await cleanup_tombstones(factory, store) == 0
    assert await scan_ok(factory, asset_id) == 1  # still scheduled; recovers when healthy


async def test_tombstone_batches_are_bounded_and_oldest_first(factory):
    assets = []
    for offset in (30, 10, 20):
        owner, asset_id, _ = await seed(factory)
        await cancel_and_ack(factory, owner, asset_id)
        async with factory() as session, session.begin():
            intent = await session.get(CleanupIntent, asset_id)
            intent.next_try_at = now() - timedelta(seconds=offset)
        assets.append(asset_id)
    keys = []

    async def remove(bucket, key):
        keys.append(key)

    store = SimpleNamespace(remove_source_versions=remove)
    assert await cleanup_tombstones(factory, store, limit=2) == 2
    assert [k.split("/")[2] for k in keys] == [str(assets[0]), str(assets[2])]
    assert await cleanup_tombstones(factory, store, limit=2) == 1
    assert keys[-1].split("/")[2] == str(assets[1])


async def test_poisoned_result_does_not_block_a_later_version(factory):
    owner, asset_id, descriptor = await seed(factory)
    job_id, attempt_id = uuid4(), uuid4()

    def result(version, status, outputs=()):
        return {
            "schema_version": 1,
            "message_id": str(uuid4()),
            "kind": "result",
            "owner_id": str(owner),
            "asset_id": str(asset_id),
            "job_id": str(job_id),
            "attempt_id": str(attempt_id),
            "source": descriptor,
            "state_version": version,
            "payload": {
                "status": status,
                "attempt_number": 1,
                "outputs": list(outputs),
                "error": None if status != "failed" else "Processing failed",
            },
        }

    async with factory() as session:
        assert await consume_result(session, result(1, "processing"), apply_result)
    # A done result whose primary output lies outside the attempt namespace is poison.
    poison = result(
        2,
        "done",
        [
            {
                "kind": "primary",
                "object_key": f"jobs/{uuid4()}/attempts/{uuid4()}/primary.mp4",
                "media_type": "video/mp4",
                "size_bytes": 5,
                "sha256": "e" * 64,
            }
        ],
    )
    for _ in range(2):  # every redelivery fails the same way and records nothing
        async with factory() as session:
            with pytest.raises(MediaError, match="outside the accepted attempt"):
                await consume_result(session, poison, apply_result)
    from media.messaging_models import MediaInbox
    from media.projection_models import ProcessingProjection

    async with factory() as session:
        assert await session.get(MediaInbox, UUID(poison["message_id"])) is None
        assert (await session.get(ProcessingProjection, asset_id)).state_version == 1
    # Processing's re-emitted snapshot at a higher version applies normally.
    async with factory() as session:
        assert await consume_result(session, result(3, "failed"), apply_result)
        projection = await session.get(ProcessingProjection, asset_id)
        assert (projection.state_version, projection.status) == (3, "failed")


# --- Staged source copies a failed edit or dead Lambda left behind (#117) -------------------

GRACE = 3600
ADOPTER_VIEW = SimpleNamespace(settings=SimpleNamespace(orphan_grace_seconds=GRACE))


async def stage_rows(factory, *keys, age=timedelta(hours=2), uncertain=False):
    """Staged intents ``age`` old, oldest first so the batch order is observable."""
    async with factory() as session, session.begin():
        for index, key in enumerate(keys):
            session.add(
                StagedObject(
                    key=key,
                    created_at=now() - age - timedelta(seconds=len(keys) - index),
                    write_uncertain=uncertain,
                )
            )


async def staged_keys(factory):
    async with factory() as session:
        return set(await session.scalars(select(StagedObject.key)))


def removals():
    removed, state = [], {"fail": False}

    async def remove(bucket, key):
        removed.append((bucket, key))
        if state["fail"]:
            raise RuntimeError("store unavailable https://signed.example/?X-Amz-Signature=secret")

    return SimpleNamespace(remove_source_versions=remove), removed, state


async def clean_staged(factory, storage, **options):
    return await cleanup_staged_objects(
        factory, storage, "owned-source", grace_seconds=GRACE, **options
    )


async def test_stale_unadopted_stages_lose_every_version_and_their_row(factory):
    storage, removed, _ = removals()
    await stage_rows(factory, "sources/o/a/source", "sources/o/b/source")
    assert await clean_staged(factory, storage) == 2
    assert removed == [
        ("owned-source", "sources/o/a/source"),
        ("owned-source", "sources/o/b/source"),
    ]
    assert await staged_keys(factory) == set()


async def test_recent_and_adopted_stages_are_never_touched(factory):
    storage, removed, _ = removals()
    _, _, descriptor = await seed(factory)
    await stage_rows(factory, descriptor["key"])  # stale, but an Asset adopted it
    await stage_rows(factory, "sources/o/fresh/source", age=timedelta(minutes=5))
    assert await clean_staged(factory, storage) == 0
    assert removed == []
    assert await staged_keys(factory) == {descriptor["key"], "sources/o/fresh/source"}


async def test_staged_recovery_is_bounded_per_pass_and_oldest_first(factory):
    storage, removed, _ = removals()
    keys = [f"sources/o/{n}/source" for n in range(5)]
    await stage_rows(factory, *keys)
    assert await clean_staged(factory, storage, limit=2) == 2
    assert [key for _, key in removed] == keys[:2]
    assert await staged_keys(factory) == set(keys[2:])
    assert await clean_staged(factory, storage, limit=10) == 3
    assert await staged_keys(factory) == set()


async def test_an_uncertain_removal_keeps_the_intent_and_stays_unadoptable_until_it_returns(
    factory,
):
    from media.errors import MediaError
    from media.services.intake import assert_adoptable

    storage, removed, state = removals()
    state["fail"] = True
    await stage_rows(factory, "sources/o/a/source")
    assert await clean_staged(factory, storage) == 0
    assert await staged_keys(factory) == {"sources/o/a/source"}
    # Still stale, so an adopter is refused while an abandoned deletion may still run,
    # and the next pass retries it (behind any older rows).
    async with factory() as session:
        staged = await session.get(StagedObject, "sources/o/a/source")
        with pytest.raises(MediaError):
            assert_adoptable(staged, ADOPTER_VIEW)
    state["fail"] = False
    assert await clean_staged(factory, storage) == 1
    assert len(removed) == 2
    assert await staged_keys(factory) == set()


async def test_a_timed_out_deletion_leaves_the_row_stale_and_the_bytes_unadoptable(factory):
    import time

    from media.errors import MediaError
    from media.services.intake import assert_adoptable

    started = []

    async def slow(bucket, key):
        started.append(key)
        await asyncio.sleep(5)

    storage = SimpleNamespace(remove_source_versions=slow)
    await stage_rows(factory, "sources/o/a/source", uncertain=True)
    # The invocation deadline cuts the deletion off mid-flight.
    assert await clean_staged(factory, storage, deadline=time.monotonic() + 0.2) == 0
    assert started == ["sources/o/a/source"]
    async with factory() as session:
        staged = await session.get(StagedObject, "sources/o/a/source")
        assert staged.write_uncertain
        with pytest.raises(MediaError):
            assert_adoptable(staged, ADOPTER_VIEW)


async def test_a_write_of_unknown_outcome_is_rescanned_instead_of_retired(factory):
    storage, removed, _ = removals()
    await stage_rows(factory, "sources/o/late/source", uncertain=True)
    assert await clean_staged(factory, storage) == 1
    # A late PUT may still land, so the row stays, with a fresh clock.
    assert await staged_keys(factory) == {"sources/o/late/source"}
    assert await clean_staged(factory, storage) == 0
    assert len(removed) == 1


async def test_an_adopter_holding_the_stage_lock_is_not_overtaken_by_cleanup(factory):
    storage, removed, _ = removals()
    await stage_rows(factory, "sources/o/a/source")
    async with factory() as holder, holder.begin():
        await holder.scalar(
            select(StagedObject).where(StagedObject.key == "sources/o/a/source").with_for_update()
        )
        assert await clean_staged(factory, storage) == 0
        assert removed == []
    assert await clean_staged(factory, storage) == 1


async def test_run_once_includes_staged_recovery_with_the_repair_settings(factory):
    storage, removed, _ = removals()
    storage.delete_direct_upload = AsyncMock()
    await stage_rows(factory, "sources/o/a/source")
    settings = SimpleNamespace(
        recovery_batch_size=25, orphan_grace_seconds=GRACE, minio_source_bucket="owned-source"
    )
    assert await run_once(factory, settings, storage) == {"cleanup": 0, "uploads": 0, "staged": 1}
    assert removed == [("owned-source", "sources/o/a/source")]


async def test_staged_copy_with_versions_and_delete_marker_is_fully_released_with_moto(factory):
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
    bucket = "stage-recovery-" + uuid4().hex
    client.create_bucket(Bucket=bucket)
    client.put_bucket_versioning(Bucket=bucket, VersioningConfiguration={"Status": "Enabled"})
    orphan = f"sources/{uuid4()}/{uuid4()}/source"
    _, _, descriptor = await seed(factory)
    kept = descriptor["key"]
    for key in (orphan, kept):
        client.put_object(Bucket=bucket, Key=key, Body=b"first")
        client.put_object(Bucket=bucket, Key=key, Body=b"second")
    client.put_object(Bucket=bucket, Key=orphan + "-sibling", Body=b"must-remain")
    # A plain delete is what the old discard did: it only adds a marker over the bytes.
    client.delete_object(Bucket=bucket, Key=orphan)
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

    def versions_of(key):
        listing = client.list_object_versions(Bucket=bucket, Prefix=key)
        return [
            item
            for item in listing.get("Versions", []) + listing.get("DeleteMarkers", [])
            if item["Key"] == key
        ]

    try:
        assert len(versions_of(orphan)) == 3  # two versions plus the marker
        await stage_rows(factory, orphan, kept)
        assert (
            await cleanup_staged_objects(factory, storage, bucket, grace_seconds=GRACE, limit=10)
            == 1
        )
        assert not await asyncio.to_thread(versions_of, orphan)
        assert len(await asyncio.to_thread(versions_of, kept)) == 2  # adopted: untouched
        assert len(await asyncio.to_thread(versions_of, orphan + "-sibling")) == 1
        assert await staged_keys(factory) == {kept}
    finally:
        listing = client.list_object_versions(Bucket=bucket)
        items = listing.get("Versions", []) + listing.get("DeleteMarkers", [])
        if items:
            client.delete_objects(
                Bucket=bucket,
                Delete={"Objects": [{"Key": i["Key"], "VersionId": i["VersionId"]} for i in items]},
            )
        client.delete_bucket(Bucket=bucket)
