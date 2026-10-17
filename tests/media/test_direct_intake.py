"""Offline direct-intake ownership, replay, immutable-byte and failure tests."""

import hashlib
from datetime import timedelta
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from pydantic import ValidationError

from media.errors import MediaError
from media.models import now
from media.services import direct_intake as intake
from media.services.storage import MAX_FILE_SIZE, Storage
from media.upload_models import UploadReservation


@pytest.fixture
def reservation(user, video):
    return UploadReservation(
        id=uuid4(),
        owner_id=user.id,
        request_id=uuid4(),
        request_hash="a" * 64,
        asset_id=uuid4(),
        filename="clip.mp4",
        bucket="source",
        key=f"staging/{user.id}/{uuid4()}/source",
        content_type="video/mp4",
        size_bytes=len(video),
        sha256=hashlib.sha256(video).hexdigest(),
        expires_at=now() + timedelta(minutes=15),
        finalized_at=None,
    )


def request(row):
    return intake.FinalizeRequest(request_id=row.request_id)


@pytest.mark.parametrize(
    "field,value",
    [
        ("size_bytes", 0),
        ("size_bytes", True),
        ("size_bytes", MAX_FILE_SIZE + 1),
        ("sha256", "bad"),
        ("key", "forged"),
    ],
)
def test_reservation_rejects_invalid_inputs(field, value):
    data = dict(
        request_id=uuid4(),
        filename="x.mp4",
        content_type="video/mp4",
        size_bytes=1,
        sha256="a" * 64,
    )
    data[field] = value
    with pytest.raises(ValidationError):
        intake.ReserveRequest(**data)


async def test_reserve_persists_owner_key_before_grant(session, storage, user):
    storage.settings.minio_source_bucket = "source"
    body = intake.ReserveRequest(
        request_id=uuid4(),
        filename="../bad file.mp4",
        content_type="video/mp4",
        size_bytes=12,
        sha256="a" * 64,
    )
    result = await intake.reserve(session, storage, user.id, body)
    row = session.add.call_args.args[0]
    assert row.key == f"staging/{user.id}/{row.id}/source"
    assert row.filename == "bad_file.mp4"
    assert result["asset_id"] == row.asset_id
    storage.direct_upload_grant.assert_awaited_once_with(row)
    session.flush.assert_awaited_once()


async def test_reserve_replay_and_conflict(session, storage, user, reservation):
    body = intake.ReserveRequest(
        request_id=reservation.request_id,
        filename="clip.mp4",
        content_type="video/mp4",
        size_bytes=reservation.size_bytes,
        sha256=reservation.sha256,
    )
    reservation.request_hash = intake.fingerprint(body.model_dump(mode="json"))
    session.scalar.return_value = reservation
    assert (await intake.reserve(session, storage, user.id, body))[
        "asset_id"
    ] == reservation.asset_id
    session.add.assert_not_called()
    body.filename = "different.mp4"
    with pytest.raises(MediaError) as error:
        await intake.reserve(session, storage, user.id, body)
    assert error.value.status_code == 409


async def test_finalize_atomic_adoption_and_replay(session, storage, reservation):
    session.scalar.return_value = reservation
    storage.verify_direct_upload.return_value = "immutable-v1"
    enqueue = AsyncMock()
    asset = await intake.finalize(
        session,
        storage,
        reservation.owner_id,
        reservation.id,
        request(reservation),
        enqueue=enqueue,
    )
    assert asset.id == reservation.asset_id
    assert reservation.version_id == "immutable-v1"
    assert enqueue.await_args.args[2]["version_id"] == "immutable-v1"
    session.get.return_value = asset
    replay = await intake.finalize(
        session,
        storage,
        reservation.owner_id,
        reservation.id,
        request(reservation),
        enqueue=enqueue,
    )
    assert replay.id == asset.id
    assert enqueue.await_count == storage.verify_direct_upload.await_count == 1


@pytest.mark.parametrize("failure", ["owner", "expired", "request"])
async def test_finalize_denies_invalid_reservation(session, storage, reservation, failure):
    session.scalar.return_value = reservation
    body = request(reservation)
    if failure == "owner":
        session.scalar.return_value = None
    elif failure == "expired":
        reservation.expires_at = now() - timedelta(seconds=1)
    else:
        body.request_id = uuid4()
    with pytest.raises(MediaError) as error:
        await intake.finalize(session, storage, reservation.owner_id, reservation.id, body)
    assert error.value.status_code == {"owner": 404, "expired": 410, "request": 409}[failure]
    storage.verify_direct_upload.assert_not_awaited()


async def test_finalize_rechecks_expiry_after_slow_storage(session, storage, reservation):
    session.scalar.return_value = reservation

    async def verify(row):
        row.expires_at = now() - timedelta(seconds=1)
        return "v1"

    storage.verify_direct_upload.side_effect = verify
    enqueue = AsyncMock()
    with pytest.raises(MediaError) as error:
        await intake.finalize(
            session,
            storage,
            reservation.owner_id,
            reservation.id,
            request(reservation),
            enqueue=enqueue,
        )
    assert error.value.status_code == 410
    enqueue.assert_not_awaited()
    session.add.assert_not_called()


async def test_source_export_accepts_asset_or_uuid(session, reservation):
    reservation.version_id = "v1"
    session.scalar.return_value = reservation
    expected = intake.source(reservation)
    assert await intake.source_for_asset(session, reservation.asset_id) == expected
    assert (
        await intake.source_for_asset(session, SimpleNamespace(id=reservation.asset_id)) == expected
    )


@pytest.fixture
def native_store(settings, reservation, video):
    store = Storage(settings)
    store.internal = MagicMock()
    store.internal.stat_object.return_value = SimpleNamespace(
        version_id="verified-v1", size=len(video), content_type="video/mp4"
    )
    response = MagicMock()
    response.read.side_effect = BytesIO(video).read
    store.internal.get_object.return_value = response
    return store


async def test_verify_reads_exact_head_version(native_store, reservation):
    assert await native_store.verify_direct_upload(reservation) == "verified-v1"
    native_store.internal.get_object.assert_called_once_with(
        reservation.bucket, reservation.key, version_id="verified-v1"
    )


@pytest.mark.parametrize("failure", ["size", "digest", "mime", "bytes", "unversioned"])
async def test_verify_rejects_changed_or_unversioned_object(native_store, reservation, failure):
    stat = native_store.internal.stat_object.return_value
    if failure == "size":
        stat.size += 1
    if failure == "digest":
        reservation.sha256 = "f" * 64
    if failure == "mime":
        stat.content_type = "text/plain"
    if failure == "bytes":
        body = b"x" * reservation.size_bytes
        native_store.internal.get_object.return_value.read.side_effect = BytesIO(body).read
        reservation.sha256 = hashlib.sha256(body).hexdigest()
    if failure == "unversioned":
        stat.version_id = "null"
    with pytest.raises(MediaError):
        await native_store.verify_direct_upload(reservation)


async def test_post_policy_limits_key_type_and_size(native_store, reservation):
    native_store.public = MagicMock()
    native_store.public.presigned_post_policy.return_value = {"policy": "signed"}
    grant = await native_store.direct_upload_grant(reservation)
    policy = native_store.public.presigned_post_policy.call_args.args[0]
    assert policy._conditions["eq"]["key"] == reservation.key
    assert policy._conditions["eq"]["Content-Type"] == "video/mp4"
    assert policy._lower_limit == 1 and policy._upper_limit == reservation.size_bytes
    assert grant["method"] == "POST"


async def test_cleanup_preserves_pin_deletes_all_other_exact_key_versions(
    native_store, reservation
):
    native_store.internal.list_objects.return_value = [
        SimpleNamespace(object_name=reservation.key, version_id="accepted"),
        SimpleNamespace(object_name=reservation.key, version_id="late"),
        SimpleNamespace(object_name=reservation.key + "-other", version_id="foreign"),
    ]
    removed = []

    def remove(bucket, objects):
        removed.extend(objects)
        return []

    native_store.internal.remove_objects.side_effect = remove
    await native_store.delete_direct_upload(reservation, preserve_version="accepted")
    assert len(removed) == 1
    assert removed[0].version_id == "late"


async def test_finalized_reservation_replay_does_not_issue_new_write_grant(
    session, storage, user, reservation
):
    body = intake.ReserveRequest(
        request_id=reservation.request_id,
        filename="clip.mp4",
        content_type="video/mp4",
        size_bytes=reservation.size_bytes,
        sha256=reservation.sha256,
    )
    reservation.request_hash = intake.fingerprint(body.model_dump(mode="json"))
    reservation.finalized_at = now()
    reservation.expires_at = now() - timedelta(minutes=1)
    session.scalar.return_value = reservation
    result = await intake.reserve(session, storage, user.id, body)
    assert result["upload"] is None
    assert result["asset_id"] == reservation.asset_id
    storage.direct_upload_grant.assert_not_awaited()


async def test_uncertain_reservation_insert_replays_winner(session, storage, user, reservation):
    from sqlalchemy.exc import IntegrityError

    body = intake.ReserveRequest(
        request_id=reservation.request_id,
        filename="clip.mp4",
        content_type="video/mp4",
        size_bytes=reservation.size_bytes,
        sha256=reservation.sha256,
    )
    reservation.request_hash = intake.fingerprint(body.model_dump(mode="json"))
    session.scalar.side_effect = [None, reservation]
    session.flush.side_effect = IntegrityError("duplicate", None, None)
    result = await intake.reserve(session, storage, user.id, body)
    assert result["reservation_id"] == reservation.id


async def test_finalize_lost_commit_response_replays_without_storage_or_enqueue(
    session, storage, reservation, asset
):
    reservation.finalized_at = now()
    reservation.version_id = "already-adopted"
    session.scalar.return_value = reservation
    session.get.return_value = asset
    enqueue = AsyncMock()
    assert (
        await intake.finalize(
            session,
            storage,
            reservation.owner_id,
            reservation.id,
            request(reservation),
            enqueue=enqueue,
        )
        is asset
    )
    storage.verify_direct_upload.assert_not_awaited()
    enqueue.assert_not_awaited()


async def test_finalize_deleted_asset_cannot_resurrect(session, storage, reservation, asset):
    reservation.finalized_at = now()
    asset.deleted_at = now()
    session.scalar.return_value = reservation
    session.get.return_value = asset
    with pytest.raises(MediaError) as error:
        await intake.finalize(
            session,
            storage,
            reservation.owner_id,
            reservation.id,
            request(reservation),
            enqueue=AsyncMock(),
        )
    assert error.value.status_code == 410
    session.add.assert_not_called()


async def test_owner_is_in_finalize_sql_predicate(session, storage, reservation):
    with pytest.raises(MediaError):
        await intake.finalize(
            session, storage, reservation.owner_id, reservation.id, request(reservation)
        )
    query = session.scalar.await_args.args[0]
    params = query.compile().params
    assert reservation.owner_id in params.values()
    assert reservation.id in params.values()
    assert "owner_id" in str(query)


async def test_pin_derived_source_reverifies_version_before_staging_command(
    session, storage, asset
):
    storage.settings.minio_source_bucket = "source"
    storage.verify_direct_upload.return_value = "derived-v1"
    result = await intake.pin_copied_source(session, storage, asset)
    assert result == {
        "bucket": "source",
        "key": asset.source_key,
        "version_id": "derived-v1",
        "sha256": asset.source_sha256,
        "size_bytes": asset.source_size_bytes,
        "content_type": asset.source_media_type,
    }
    assert session.add.call_args.args[0].asset_id == asset.id
    assert storage.verify_direct_upload.await_args.kwargs == {"check_content": False}


def expired_for_scan(reservation, *, age=timedelta(minutes=5)):
    """Make the unit-test reservation look like a persisted, expired, due ledger row."""
    reservation.expires_at = now() - age
    reservation.version_id = "accepted"
    reservation.finalized_at = reservation.expires_at - timedelta(minutes=1)
    reservation.cleanup_attempts = 0
    reservation.cleanup_next_at = now() - timedelta(seconds=1)
    reservation.cleanup_retired_at = None


@pytest.fixture
def scan(session, reservation):
    from contextlib import asynccontextmanager

    expired_for_scan(reservation)
    session.scalars.return_value = [reservation.id]
    session.get.return_value = reservation

    @asynccontextmanager
    async def factory():
        yield session

    return factory


async def test_cleanup_repeats_authority_after_late_write_and_preserves_version(
    scan, storage, reservation
):
    assert await intake.cleanup_expired_uploads(scan, storage, limit=1) == 1
    # Not due again until the backoff elapses, however often the repair tick fires.
    assert await intake.cleanup_expired_uploads(scan, storage, limit=1) == 0
    reservation.cleanup_next_at = now() - timedelta(seconds=1)
    assert await intake.cleanup_expired_uploads(scan, storage, limit=1) == 1
    assert storage.delete_direct_upload.await_count == 2
    assert storage.delete_direct_upload.await_args.kwargs == {"preserve_version": "accepted"}
    assert reservation.cleanup_attempts == 2
    assert reservation.cleanup_retired_at is None  # Early scans keep the authority armed.


async def test_cleanup_backs_off_between_rescans_and_caps_the_interval(scan, storage, reservation):
    waits = []
    for _ in range(9):
        before = now()
        await intake.cleanup_expired_uploads(scan, storage)
        waits.append(round((reservation.cleanup_next_at - before).total_seconds() / 10) * 10)
        reservation.cleanup_next_at = now() - timedelta(seconds=1)
    assert waits == [60, 120, 240, 480, 960, 1920, 3600, 3600, 3600]


async def test_cleanup_retires_only_after_a_clean_scan_past_the_horizon(scan, storage, reservation):
    reservation.expires_at = now() - intake.CLEANUP_HORIZON - timedelta(minutes=1)
    storage.delete_direct_upload.side_effect = MediaError(503, "source cleanup deferred")
    assert await intake.cleanup_expired_uploads(scan, storage) == 0
    assert reservation.cleanup_retired_at is None  # A failed scan never retires.
    reservation.cleanup_next_at = now() - timedelta(seconds=1)
    storage.delete_direct_upload.side_effect = None
    assert await intake.cleanup_expired_uploads(scan, storage) == 1
    assert reservation.cleanup_retired_at is not None


async def test_cleanup_skips_a_row_another_invocation_already_retired(scan, storage, reservation):
    reservation.cleanup_retired_at = now()
    assert await intake.cleanup_expired_uploads(scan, storage) == 0
    storage.delete_direct_upload.assert_not_awaited()


async def test_cleanup_stops_at_the_invocation_deadline_without_touching_storage(
    scan, storage, reservation
):
    import time

    assert await intake.cleanup_expired_uploads(scan, storage, deadline=time.monotonic()) == 0
    storage.delete_direct_upload.assert_not_awaited()
    assert reservation.cleanup_attempts == 0


async def test_absent_object_does_not_adopt_or_enqueue(session, storage, reservation):
    session.scalar.return_value = reservation
    storage.verify_direct_upload.side_effect = MediaError(503, "missing")
    enqueue = AsyncMock()
    with pytest.raises(MediaError):
        await intake.finalize(
            session,
            storage,
            reservation.owner_id,
            reservation.id,
            request(reservation),
            enqueue=enqueue,
        )
    assert reservation.finalized_at is None
    session.add.assert_not_called()
    enqueue.assert_not_awaited()


async def test_finalize_uses_shared_enqueue_in_adoption_transaction(
    session, storage, reservation, monkeypatch
):
    import sys
    from contextlib import asynccontextmanager

    active = False

    @asynccontextmanager
    async def transaction():
        nonlocal active
        active = True
        try:
            yield
        finally:
            active = False

    session.begin.side_effect = transaction
    session.scalar.return_value = reservation
    storage.verify_direct_upload.return_value = "v1"
    emitted = []

    async def enqueue(session, asset, descriptor):
        assert active
        assert reservation.finalized_at is not None
        assert asset.id == reservation.asset_id
        emitted.append(descriptor)

    monkeypatch.setitem(sys.modules, "media.messaging", SimpleNamespace(enqueue_submit=enqueue))
    await intake.finalize(
        session, storage, reservation.owner_id, reservation.id, request(reservation)
    )
    assert len(emitted) == 1 and emitted[0]["version_id"] == "v1"
