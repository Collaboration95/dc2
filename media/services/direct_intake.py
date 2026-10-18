"""Reserve outside byte transport; atomically adopt a verified immutable version."""

import asyncio
import time
from datetime import timedelta
from types import SimpleNamespace
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from media.errors import MediaError
from media.models import Asset, now
from media.repositories.assets import fingerprint
from media.services.intake import ALLOWED_CONTENT_TYPES, safe_filename
from media.services.storage import MAX_FILE_SIZE
from media.upload_models import SourceVersion, UploadReservation


class ReserveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: UUID
    filename: str = Field(min_length=1, max_length=255)
    content_type: str
    size_bytes: int = Field(strict=True, gt=0, le=MAX_FILE_SIZE)
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


class FinalizeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: UUID


def source(reservation):
    return {
        name: getattr(reservation, name)
        for name in ("bucket", "key", "version_id", "sha256", "size_bytes", "content_type")
    }


async def source_for_asset(session, asset_or_id):
    """The only sanctioned way to name an adopted source: always carries its VersionId.

    A staging key stays writable by a replayed grant until the grant expires, so a reader
    holding just the key could be served bytes that were never verified.
    """
    asset_id = getattr(asset_or_id, "id", asset_or_id)
    descriptor = await _stored_source(session, asset_id)
    adopted_key = getattr(asset_or_id, "source_key", None)
    if descriptor and adopted_key is not None and descriptor["key"] != adopted_key:
        raise MediaError(409, "accepted source does not match the asset")
    return descriptor


async def pinned_version(session, asset):
    """VersionId a legacy signed-URL reader must request, or None for unpinned history."""
    descriptor = await source_for_asset(session, asset)
    return descriptor["version_id"] if descriptor else None


async def _stored_source(session, asset_id):
    reservation = await session.scalar(
        select(UploadReservation).where(
            UploadReservation.asset_id == asset_id, UploadReservation.finalized_at.is_not(None)
        )
    )
    if reservation:
        return source(reservation)
    pin = await session.get(SourceVersion, asset_id)
    return source(pin) if pin else None


async def pin_copied_source(session, storage, asset):
    """Call after output->source copy, inside caller's adoption transaction.

    The output was already validated by the copy operation; reverify bytes and
    checksum while pinning S3 VersionId. Return descriptor for the same outbox tx.
    """
    from types import SimpleNamespace

    descriptor = SimpleNamespace(
        version_id=None,
        bucket=storage.settings.minio_source_bucket,
        key=asset.source_key,
        sha256=asset.source_sha256,
        size_bytes=asset.source_size_bytes,
        content_type=asset.source_media_type,
    )
    version = await storage.verify_direct_upload(descriptor, check_content=False)
    descriptor.version_id = version
    pin = SourceVersion(asset_id=asset.id, **source(descriptor))
    session.add(pin)
    await session.flush()
    return source(pin)


async def reserve(session, storage, owner_id, request):
    if request.content_type not in ALLOWED_CONTENT_TYPES:
        raise MediaError(415, "unsupported media type")
    digest = fingerprint(request.model_dump(mode="json"))
    query = select(UploadReservation).where(
        UploadReservation.owner_id == owner_id,
        UploadReservation.request_id == request.request_id,
    )
    try:
        async with session.begin():
            row = await session.scalar(query)
            if row is None:
                reservation_id, asset_id = uuid4(), uuid4()
                row = UploadReservation(
                    id=reservation_id,
                    owner_id=owner_id,
                    request_id=request.request_id,
                    request_hash=digest,
                    asset_id=asset_id,
                    filename=safe_filename(request.filename),
                    bucket=storage.settings.minio_source_bucket,
                    # An adopted upload keeps this key: the version pin, not a copy to sources/,
                    # is what makes it immutable, and a copy would cost a second 100 MiB object.
                    key=f"staging/{owner_id}/{reservation_id}/source",
                    content_type=request.content_type,
                    size_bytes=request.size_bytes,
                    sha256=request.sha256,
                    expires_at=now() + timedelta(minutes=15),
                )
                session.add(row)
                await session.flush()
    except IntegrityError:
        async with session.begin():
            row = await session.scalar(query)
        if row is None:
            raise MediaError(503, "reservation unavailable") from None
    if row.request_hash != digest:
        raise MediaError(409, "idempotency key used for a different request")
    if row.finalized_at is None and row.expires_at <= now():
        raise MediaError(410, "upload reservation expired")
    # Replayed finalized reservations need no new writable grant.
    upload = None if row.finalized_at else await storage.direct_upload_grant(row)
    return {
        "reservation_id": row.id,
        "asset_id": row.asset_id,
        "expires_at": row.expires_at,
        "upload": upload,
        "finalize_url": f"/uploads/reservations/{row.id}/finalize",
    }


async def finalize(session, storage, owner_id, reservation_id, request, *, enqueue=None):
    async with session.begin():
        row = await session.scalar(
            select(UploadReservation).where(
                UploadReservation.id == reservation_id, UploadReservation.owner_id == owner_id
            )
        )
        if row is None:
            raise MediaError(404, "not found")
        if row.request_id != request.request_id:
            raise MediaError(409, "reservation request does not match")
        if row.finalized_at:
            asset = await session.get(Asset, row.asset_id)
            if asset is None or asset.deleted_at:
                raise MediaError(410, "previously accepted item is deleted")
            return asset
        if row.expires_at <= now():
            raise MediaError(410, "upload reservation expired")
    # S3 HEAD + bounded streaming GET happen without holding SQL row locks.
    version_id = await storage.verify_direct_upload(row)
    async with session.begin():
        row = await session.scalar(
            select(UploadReservation)
            .where(UploadReservation.id == reservation_id, UploadReservation.owner_id == owner_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if row.finalized_at:
            asset = await session.get(Asset, row.asset_id)
            if asset is None or asset.deleted_at:
                raise MediaError(410, "previously accepted item is deleted")
            return asset
        if row.expires_at <= now():
            raise MediaError(410, "upload reservation expired")
        row.version_id = version_id
        row.finalized_at = now()
        asset = Asset(
            id=row.asset_id,
            owner_id=owner_id,
            filename=row.filename,
            source_key=row.key,
            source_revision=1,
            source_sha256=row.sha256,
            source_size_bytes=row.size_bytes,
            source_media_type=row.content_type,
            operations=[],
        )
        session.add(asset)
        await session.flush()
        if enqueue is None:
            from media.messaging import enqueue_submit

            enqueue = enqueue_submit
        await enqueue(session, asset, source(row))
    return asset


CLEANUP_BASE_SECONDS = 60
CLEANUP_CAP_SECONDS = 3600
CLEANUP_HORIZON = timedelta(days=1)


def cleanup_delay(attempts):
    """Early rescans catch the likely late write; later ones thin out to hourly."""
    return min(CLEANUP_CAP_SECONDS, CLEANUP_BASE_SECONDS * 2 ** min(max(attempts - 1, 0), 6))


async def cleanup_expired_uploads(
    factory, storage, limit=100, *, deadline=None, horizon=CLEANUP_HORIZON
):
    """Rescan expired grants for late writes, bounded, backing off, then retire them.

    A POST begun before expiry can finish after it, so the ledger row outlives expiry. It
    cannot outlive it forever: a scan that succeeds at least ``horizon`` after expiry
    retires the row (kept as audit). A failed scan never retires; it only backs off.
    Storage I/O runs between short transactions, never under a row lock.
    """
    async with factory() as session:
        due = now()
        ids = list(
            await session.scalars(
                select(UploadReservation.id)
                .where(
                    UploadReservation.expires_at < due,
                    UploadReservation.cleanup_retired_at.is_(None),
                    UploadReservation.cleanup_next_at <= due,
                )
                .order_by(UploadReservation.cleanup_next_at, UploadReservation.id)
                .limit(limit)
            )
        )
    completed = 0
    for reservation_id in ids:
        if deadline is not None and time.monotonic() >= deadline:
            break
        async with factory() as session, session.begin():
            row = await session.get(UploadReservation, reservation_id, with_for_update=True)
            current = now()
            if (
                row is None
                or row.cleanup_retired_at is not None
                or row.expires_at >= current
                or row.cleanup_next_at > current
            ):
                continue  # Another invocation scanned or retired it since the listing.
            # Reserve the scan: a concurrent or crashed invocation retries after this lease.
            row.cleanup_attempts += 1
            row.cleanup_next_at = current + timedelta(seconds=CLEANUP_BASE_SECONDS)
            target = SimpleNamespace(bucket=row.bucket, key=row.key)
            preserve, expires_at = row.version_id, row.expires_at
            scan, lease = row.cleanup_attempts, row.cleanup_next_at
        failed = False
        try:
            if deadline is None:
                await storage.delete_direct_upload(target, preserve_version=preserve)
            else:
                async with asyncio.timeout(max(0.001, deadline - time.monotonic())):
                    await storage.delete_direct_upload(target, preserve_version=preserve)
            completed += 1
        except Exception:
            failed = True  # The durable row and the next due time retain retry authority.
        async with factory() as session, session.begin():
            row = await session.get(UploadReservation, reservation_id, with_for_update=True)
            if row is None or row.cleanup_attempts != scan or row.cleanup_next_at != lease:
                continue
            finished = now()
            row.cleanup_checked_at = finished
            row.cleanup_next_at = finished + timedelta(seconds=cleanup_delay(scan))
            if not failed and finished >= expires_at + horizon:
                row.cleanup_retired_at = finished
    return completed
