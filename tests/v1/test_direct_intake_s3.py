"""Direct intake against a real S3-compatible store (Moto) and real PostgreSQL.

Opt in with V1_TEST_S3_ENDPOINT (loopback Moto from `make v1-up`) and V1_TEST_MEDIA_DSN
(an asyncpg DSN that may create schemas). Each test owns one bucket and one SQL schema.

What this does NOT prove: Moto stores presigned-POST fields but does not enforce the signed
policy, so expiry and content-length-range are asserted on the grant itself and on the
server-side finalize/cleanup that must hold even if S3 enforcement were absent. Real S3
policy enforcement, IAM and TLS remain cloud checks (#45, #63-#67).
"""

import base64
import hashlib
import json
import os
from datetime import UTC, datetime, timedelta
from urllib.parse import urlsplit
from uuid import uuid4

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import func, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from media import messaging_models, projection_models, upload_models  # noqa: F401
from media.config import Settings
from media.database import Base
from media.errors import MediaError
from media.messaging_models import MediaOutbox
from media.models import Asset, User, now
from media.services import direct_intake
from media.services.direct_intake import FinalizeRequest, ReserveRequest
from media.services.storage import Storage
from media.upload_models import UploadReservation

pytestmark = pytest.mark.integration

VIDEO = b"\x00\x00\x00\x18ftypisom" + b"video" * 20


def digest(body):
    return hashlib.sha256(body).hexdigest()


@pytest.fixture
def s3():
    endpoint = os.environ.get("V1_TEST_S3_ENDPOINT")
    if not endpoint:
        pytest.skip("V1_TEST_S3_ENDPOINT (loopback Moto) not provided")
    parsed = urlsplit(endpoint)
    if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost"}:
        raise ValueError("Direct-intake S3 tests require an explicit loopback HTTP endpoint")
    import boto3

    return parsed.netloc, boto3.client(
        "s3",
        endpoint_url=endpoint,
        region_name="us-east-1",
        aws_access_key_id="testing",
        aws_secret_access_key="testing",
    )


@pytest.fixture
def bucket(s3):
    _, client = s3
    name = "v1-intake-" + uuid4().hex[:20]
    client.create_bucket(Bucket=name)
    client.put_bucket_versioning(Bucket=name, VersioningConfiguration={"Status": "Enabled"})
    yield name
    for page in client.get_paginator("list_object_versions").paginate(Bucket=name):
        for item in page.get("Versions", []) + page.get("DeleteMarkers", []):
            client.delete_object(Bucket=name, Key=item["Key"], VersionId=item["VersionId"])
    client.delete_bucket(Bucket=name)


@pytest.fixture
def storage(s3, bucket):
    netloc, _ = s3
    return Storage(
        Settings(
            postgres_dsn="postgresql+asyncpg://unused:unused@invalid/media_db",
            minio_endpoint=netloc,
            minio_use_ssl=False,
            minio_public_endpoint=netloc,
            minio_public_use_ssl=False,
            minio_region="us-east-1",
            minio_access_key="testing",
            minio_secret_key="testing",
            minio_source_bucket=bucket,
        )
    )


@pytest_asyncio.fixture
async def factory():
    dsn = os.environ.get("V1_TEST_MEDIA_DSN")
    if not dsn:
        pytest.skip("V1_TEST_MEDIA_DSN (real Media PostgreSQL) not provided")
    schema = "intake_s3_" + uuid4().hex
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


async def make_user(factory):
    owner = uuid4()
    async with factory() as session, session.begin():
        session.add(User(id=owner, email=f"{owner}@example.test", password_hash="unused"))
    return owner


async def reserve(factory, storage, owner, body=VIDEO, **overrides):
    request = ReserveRequest(
        request_id=overrides.pop("request_id", uuid4()),
        filename="clip.mp4",
        content_type="video/mp4",
        size_bytes=overrides.pop("size_bytes", len(body)),
        sha256=overrides.pop("sha256", digest(body)),
    )
    async with factory() as session:
        return await direct_intake.reserve(session, storage, owner, request), request


def post(grant, body, **form_overrides):
    """What a browser does with the grant: one multipart POST, no cookies."""
    fields = dict(grant["fields"]) | form_overrides
    response = httpx.post(grant["url"], data=fields, files={"file": ("clip.mp4", body)})
    assert response.status_code in (200, 201, 204), response.text
    return response.headers.get("x-amz-version-id")


async def finalize(factory, storage, owner, reserved, request):
    async with factory() as session:
        return await direct_intake.finalize(
            session,
            storage,
            owner,
            reserved["reservation_id"],
            FinalizeRequest(request_id=request.request_id),
        )


def versions_of(client, bucket, key):
    page = client.list_object_versions(Bucket=bucket, Prefix=key)
    return [v["VersionId"] for v in page.get("Versions", []) if v["Key"] == key]


def read_version(client, bucket, key, version):
    return client.get_object(Bucket=bucket, Key=key, VersionId=version)["Body"].read()


async def expire(factory, reservation_id):
    async with factory() as session, session.begin():
        await session.execute(
            update(UploadReservation)
            .where(UploadReservation.id == reservation_id)
            .values(expires_at=now() - timedelta(seconds=5))
        )


async def make_due(factory, reservation_id):
    async with factory() as session, session.begin():
        await session.execute(
            update(UploadReservation)
            .where(UploadReservation.id == reservation_id)
            .values(cleanup_next_at=now() - timedelta(seconds=1))
        )


async def stored(factory, reservation_id):
    async with factory() as session:
        return await session.get(UploadReservation, reservation_id)


async def test_grant_binds_key_type_size_and_a_short_expiry(factory, storage):
    owner = await make_user(factory)
    reserved, _ = await reserve(factory, storage, owner)
    policy = json.loads(base64.b64decode(reserved["upload"]["fields"]["policy"]))
    conditions = [c for c in policy["conditions"] if isinstance(c, (list, dict))]
    key = f"staging/{owner}/{reserved["reservation_id"]}/source"
    assert ["eq", "$key", key] in conditions
    assert ["eq", "$Content-Type", "video/mp4"] in conditions
    assert ["content-length-range", 1, len(VIDEO)] in conditions
    expiry = datetime.strptime(policy["expiration"], "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=UTC)
    assert expiry <= datetime.now(UTC) + timedelta(minutes=15, seconds=5)


async def test_replayed_grant_after_finalize_cannot_change_the_served_source(
    s3, bucket, storage, factory
):
    _, client = s3
    owner = await make_user(factory)
    reserved, request = await reserve(factory, storage, owner)
    key = f"staging/{owner}/{reserved["reservation_id"]}/source"
    post(reserved["upload"], VIDEO)

    asset = await finalize(factory, storage, owner, reserved, request)
    row = await stored(factory, reserved["reservation_id"])
    pinned = row.version_id
    assert pinned and pinned != "null"

    # The grant is still valid: the attacker uploads different bytes to the same key.
    post(reserved["upload"], b"attacker bytes that were never verified")
    assert len(versions_of(client, bucket, key)) == 2
    assert client.get_object(Bucket=bucket, Key=key)["Body"].read().startswith(b"attacker")

    # An unversioned reader is fooled; every Media/worker reader must name the pin instead.
    async with factory() as session:
        descriptor = await direct_intake.source_for_asset(session, asset)
    assert descriptor["version_id"] == pinned
    assert read_version(client, bucket, descriptor["key"], pinned) == VIDEO
    assert digest(read_version(client, bucket, key, pinned)) == descriptor["sha256"]

    # Replaying finalize returns the original adoption and emits no second command.
    replay = await finalize(factory, storage, owner, reserved, request)
    assert replay.id == asset.id
    async with factory() as session:
        assert await session.scalar(select(func.count()).select_from(MediaOutbox)) == 1
        command = await session.scalar(select(MediaOutbox))
    assert command.body["source"]["version_id"] == pinned
    assert (await stored(factory, reserved["reservation_id"])).version_id == pinned


async def test_finalize_pins_the_exact_version_it_verified(s3, bucket, storage, factory):
    _, client = s3
    owner = await make_user(factory)
    reserved, request = await reserve(factory, storage, owner)
    key = f"staging/{owner}/{reserved["reservation_id"]}/source"
    post(reserved["upload"], VIDEO)
    post(reserved["upload"], VIDEO)  # An identical re-upload before finalize is legitimate.
    newest, older = versions_of(client, bucket, key)  # S3 lists the newest version first.

    await finalize(factory, storage, owner, reserved, request)

    pinned = (await stored(factory, reserved["reservation_id"])).version_id
    assert pinned == newest != older
    assert digest(read_version(client, bucket, key, pinned)) == digest(VIDEO)


async def test_wrong_owner_cannot_finalize_or_observe_a_reservation(s3, storage, factory):
    owner, intruder = await make_user(factory), await make_user(factory)
    reserved, request = await reserve(factory, storage, owner)
    post(reserved["upload"], VIDEO)
    with pytest.raises(MediaError) as refusal:
        await finalize(factory, storage, intruder, reserved, request)
    assert refusal.value.status_code == 404
    async with factory() as session:
        assert await session.scalar(select(func.count()).select_from(Asset)) == 0
    # The intruder reusing the same request id gets a separate, intruder-owned reservation.
    other, _ = await reserve(factory, storage, intruder, request_id=request.request_id)
    assert other["reservation_id"] != reserved["reservation_id"]
    assert str(intruder) in other["upload"]["fields"]["key"]


async def test_oversized_and_truncated_objects_are_refused_at_finalize(
    s3, bucket, storage, factory
):
    owner = await make_user(factory)
    for body in (VIDEO + b"extra", VIDEO[:-5]):
        reserved, request = await reserve(
            factory, storage, owner, size_bytes=len(VIDEO), sha256=digest(VIDEO)
        )
        post(reserved["upload"], body)  # Moto does not enforce content-length-range.
        with pytest.raises(MediaError) as refusal:
            await finalize(factory, storage, owner, reserved, request)
        assert refusal.value.status_code == 422
        assert (await stored(factory, reserved["reservation_id"])).finalized_at is None
    async with factory() as session:
        assert await session.scalar(select(func.count()).select_from(Asset)) == 0
        assert await session.scalar(select(func.count()).select_from(MediaOutbox)) == 0


async def test_same_size_different_bytes_fail_the_checksum(s3, storage, factory):
    owner = await make_user(factory)
    reserved, request = await reserve(factory, storage, owner)
    tampered = VIDEO[:-1] + bytes([VIDEO[-1] ^ 1])
    post(reserved["upload"], tampered)
    with pytest.raises(MediaError) as refusal:
        await finalize(factory, storage, owner, reserved, request)
    assert refusal.value.status_code == 422
    async with factory() as session:
        assert await session.scalar(select(func.count()).select_from(Asset)) == 0


async def test_missing_object_is_retryable_not_adopted(s3, storage, factory):
    owner = await make_user(factory)
    reserved, request = await reserve(factory, storage, owner)
    with pytest.raises(MediaError) as refusal:
        await finalize(factory, storage, owner, reserved, request)
    assert refusal.value.status_code == 503
    post(reserved["upload"], VIDEO)
    assert (await finalize(factory, storage, owner, reserved, request)).id == reserved["asset_id"]


async def test_an_unversioned_bucket_is_refused_because_nothing_could_be_pinned(
    s3, bucket, storage, factory
):
    _, client = s3
    client.put_bucket_versioning(Bucket=bucket, VersioningConfiguration={"Status": "Suspended"})
    owner = await make_user(factory)
    reserved, request = await reserve(factory, storage, owner)
    post(reserved["upload"], VIDEO)
    with pytest.raises(MediaError) as refusal:
        await finalize(factory, storage, owner, reserved, request)
    assert refusal.value.status_code == 503


async def test_expired_reservation_is_refused_and_its_bytes_are_reclaimed(
    s3, bucket, storage, factory
):
    _, client = s3
    owner = await make_user(factory)
    reserved, request = await reserve(factory, storage, owner)
    key = f"staging/{owner}/{reserved["reservation_id"]}/source"
    post(reserved["upload"], VIDEO)
    await expire(factory, reserved["reservation_id"])

    with pytest.raises(MediaError) as refusal:
        await finalize(factory, storage, owner, reserved, request)
    assert refusal.value.status_code == 410
    async with factory() as session:
        with pytest.raises(MediaError) as replay:
            await direct_intake.reserve(session, storage, owner, request)
    assert replay.value.status_code in (409, 410)

    assert await direct_intake.cleanup_expired_uploads(factory, storage) >= 1
    assert versions_of(client, bucket, key) == []


async def test_cleanup_keeps_the_pin_removes_late_writes_and_stays_armed(
    s3, bucket, storage, factory
):
    _, client = s3
    owner = await make_user(factory)
    reserved, request = await reserve(factory, storage, owner)
    key = f"staging/{owner}/{reserved["reservation_id"]}/source"
    post(reserved["upload"], VIDEO)
    asset = await finalize(factory, storage, owner, reserved, request)
    pinned = (await stored(factory, reserved["reservation_id"])).version_id

    post(reserved["upload"], b"replayed before expiry")
    await expire(factory, reserved["reservation_id"])
    await direct_intake.cleanup_expired_uploads(factory, storage)
    assert versions_of(client, bucket, key) == [pinned]

    # A POST begun before expiry can complete late; the retained ledger removes it too.
    post(reserved["upload"], b"late write after the first sweep")
    assert len(versions_of(client, bucket, key)) == 2
    await make_due(factory, reserved["reservation_id"])  # skip the rescan backoff
    await direct_intake.cleanup_expired_uploads(factory, storage)
    assert versions_of(client, bucket, key) == [pinned]
    async with factory() as session:
        assert (await direct_intake.source_for_asset(session, asset))["version_id"] == pinned
    assert read_version(client, bucket, key, pinned) == VIDEO


async def test_database_refuses_a_finalized_reservation_without_a_real_version(
    s3, storage, factory
):
    owner = await make_user(factory)
    reserved, _ = await reserve(factory, storage, owner)
    for version in (None, "", "null"):
        with pytest.raises(IntegrityError):
            async with factory() as session, session.begin():
                await session.execute(
                    update(UploadReservation)
                    .where(UploadReservation.id == reserved["reservation_id"])
                    .values(finalized_at=now(), version_id=version)
                )
