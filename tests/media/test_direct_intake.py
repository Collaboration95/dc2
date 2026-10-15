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
