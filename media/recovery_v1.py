"""Bounded Media repair after durable Processing cancellation acknowledgements.

Media only deletes its source objects. Processing owns its output cleanup ledger.
Keep successful source scan intents forever: late writes and lost delete responses
must be retried. Tombstone and upload scans run no storage operation inside a SQL
transaction or row lock; staged-object recovery is the one deliberate exception.
"""

import asyncio
import time
from datetime import timedelta

from sqlalchemy import delete, func, or_, select

from media.messaging_models import MediaOutbox
from media.models import Asset, CleanupIntent, StagedObject, now
from media.projections import source_for_asset
from media.services.direct_intake import CLEANUP_HORIZON, cleanup_due, cleanup_expired_uploads
from media.upload_models import UploadReservation

# A staged copy no Asset adopted: the one predicate the staged cleanup and next_due share.
ORPHANED = ~select(Asset.id).where(Asset.source_key == StagedObject.key).exists()


def unretired(horizon):
    # No schema change: a tombstone retires once a scan succeeded at least one
    # horizon after Processing acknowledged the cancellation. Failed scans never retire.
    return or_(
        CleanupIntent.source_deleted_at.is_(None),
        CleanupIntent.source_deleted_at < CleanupIntent.processing_deleted_at + horizon,
    )


async def remove_source_versions(storage, bucket, key):
    # Every version and delete marker: a bare delete would only add a marker.
    await storage.remove_source_versions(bucket, key)


async def cleanup_tombstones(
    factory, storage, *, limit=100, deadline=None, horizon=CLEANUP_HORIZON
):
    """Reserve due acknowledged tombstones, scan outside locks, fence results.

    ``source_deleted_at`` records a successful scan, never permanent completion.
    The durable intent remains scheduled to collect versions arriving later.
    ``deadline`` is a monotonic invocation deadline; SDK work must also be bounded.
    """
    async with factory() as session:
        ids = list(
            await session.scalars(
                select(CleanupIntent.asset_id)
                .join(Asset, Asset.id == CleanupIntent.asset_id)
                .where(
                    Asset.deleted_at.is_not(None),
                    CleanupIntent.processing_deleted_at.is_not(None),
                    CleanupIntent.next_try_at <= now(),
                    unretired(horizon),
                )
                .order_by(CleanupIntent.next_try_at, CleanupIntent.asset_id)
                .limit(limit)
            )
        )
    cleaned = 0
    for asset_id in ids:
        if deadline is not None and time.monotonic() >= deadline:
            break
        async with factory() as session, session.begin():
            # Match result/delete lock order: Asset then CleanupIntent.
            asset = await session.scalar(
                select(Asset).where(Asset.id == asset_id).with_for_update()
            )
            intent = await session.get(CleanupIntent, asset_id, with_for_update=True)
            if (
                asset is None
                or not asset.deleted_at
                or intent is None
                or not intent.processing_deleted_at
                or intent.next_try_at > now()
                or (
                    intent.source_deleted_at is not None
                    and intent.source_deleted_at >= intent.processing_deleted_at + horizon
                )
            ):
                continue
            descriptor = await source_for_asset(session, asset)
            # Bind the cleanup to owned accepted metadata, never a message key.
            if descriptor["key"] != asset.source_key:
                raise ValueError("Accepted source does not match tombstone")
            bucket, key = descriptor["bucket"], descriptor["key"]
            intent.attempts += 1
            intent.next_try_at = now() + timedelta(seconds=60)
            scan_attempt, scan_due = intent.attempts, intent.next_try_at
        error = None
        try:
            if deadline is None:
                await remove_source_versions(storage, bucket, key)
            else:
                async with asyncio.timeout(max(0.001, deadline - time.monotonic())):
                    await remove_source_versions(storage, bucket, key)
            cleaned += 1
        except Exception:
            # Exception strings can contain signed URLs or credentials.
            error = "Source version cleanup unavailable"
        async with factory() as session, session.begin():
            intent = await session.get(CleanupIntent, asset_id, with_for_update=True)
            if (
                intent is not None
                and intent.attempts == scan_attempt
                and intent.next_try_at == scan_due
                and intent.processing_deleted_at
            ):
                intent.last_error = error
                intent.next_try_at = cleanup_due(now(), intent.attempts)
                if error is None:
                    intent.source_deleted_at = now()
    return cleaned


async def cleanup_staged_objects(
    factory, storage, bucket, *, grace_seconds, limit=100, deadline=None
):
    """Release source copies a failed edit or dead Lambda left behind, bounded per pass.

    A ``StagedObject`` is the intent to clean a key until an Asset adopts it. One that is
    older than ``grace_seconds`` and adopted by no Asset can never be used again, so every
    stored version goes, then the row. A write whose outcome is unknown (``write_uncertain``)
    keeps its row with a fresh clock: a late PUT may still land, so it is rescanned.

    Fence against adopters. Adoption (``accept`` and the edit commit) takes this row's lock,
    and refuses a row older than ``grace_seconds`` (``intake.assert_adoptable``), so a stale
    row is the cleanup's alone. The lock covers the deletion while it runs, but the blocking
    S3 thread outlives a timeout, so the lock is not the fence: staleness is. A row is only
    made fresh again (an uncertain write, rescanned later) after a deletion has returned; a
    failed or timed-out one is left stale, so no adopter can win while that thread runs.
    Each row is its own short transaction and the storage call is bounded by the deadline.
    """
    stale = StagedObject.created_at < now() - timedelta(seconds=grace_seconds)
    orphaned = ORPHANED
    async with factory() as session:
        keys = list(
            await session.scalars(
                select(StagedObject.key)
                .where(stale, orphaned)
                .order_by(StagedObject.created_at, StagedObject.key)
                .limit(limit)
            )
        )
    cleaned = 0
    for key in keys:
        if deadline is not None and time.monotonic() >= deadline:
            break
        async with factory() as session, session.begin():
            staged = await session.scalar(
                select(StagedObject)
                .where(StagedObject.key == key, stale, orphaned)
                .with_for_update(skip_locked=True)
            )
            if staged is None:
                continue  # Adopted, refreshed or taken by another pass since the listing.
            try:
                if deadline is None:
                    await remove_source_versions(storage, bucket, key)
                else:
                    async with asyncio.timeout(max(0.001, deadline - time.monotonic())):
                        await remove_source_versions(storage, bucket, key)
            except Exception:
                # The outcome is unknown, so the cleanup intent stays and the row stays
                # stale (unadoptable) while an abandoned deletion thread may still run.
                # Moving it just past the threshold sends it behind older rows, so a few
                # persistent failures cannot starve the batch; it is due on the next pass.
                staged.created_at = now() - timedelta(seconds=grace_seconds + 1)
                continue
            if staged.write_uncertain:
                staged.created_at = now()
            else:
                await session.execute(delete(StagedObject).where(StagedObject.key == key))
            cleaned += 1
    return cleaned


async def next_due(factory, settings):
    """When the Media repair pass next has SQL work: an epoch, or None if never.

    Each term uses the predicate of the pass it stands for (outbox publish and its scheduled
    replay, tombstone rescans, expired-upload rescans, orphaned staged copies), so a tick that
    skips SQL until then misses nothing (runtime_support.activity).
    """
    grace = timedelta(seconds=settings.orphan_grace_seconds)
    async with factory() as session:
        times = [
            await session.scalar(select(func.min(MediaOutbox.next_try_at))),
            await session.scalar(
                select(func.min(CleanupIntent.next_try_at))
                .join(Asset, Asset.id == CleanupIntent.asset_id)
                .where(
                    Asset.deleted_at.is_not(None),
                    CleanupIntent.processing_deleted_at.is_not(None),
                    unretired(CLEANUP_HORIZON),
                )
            ),
            await session.scalar(
                select(
                    func.min(
                        func.greatest(
                            UploadReservation.expires_at, UploadReservation.cleanup_next_at
                        )
                    )
                ).where(UploadReservation.cleanup_retired_at.is_(None))
            ),
        ]
        staged = await session.scalar(select(func.min(StagedObject.created_at)).where(ORPHANED))
    if staged is not None:
        times.append(staged + grace)
    found = [t.timestamp() for t in times if t is not None]
    return min(found) if found else None


async def run_once(factory, settings, storage, *, deadline=None):
    """B's repair handler calls this after publishing commands; no peer needed."""
    limit = min(settings.recovery_batch_size, 100)
    result = {"cleanup": 0, "uploads": 0, "staged": 0}
    if deadline is None or time.monotonic() < deadline:
        result["cleanup"] = await cleanup_tombstones(
            factory, storage, limit=limit, deadline=deadline
        )
    if deadline is None or time.monotonic() < deadline:
        # The scan reserves each row before storage I/O and bounds that I/O by the
        # deadline itself, so a cut-off pass leaves a lease, not a half-written state.
        result["uploads"] = await cleanup_expired_uploads(
            factory, storage, limit=limit, deadline=deadline
        )
    if deadline is None or time.monotonic() < deadline:
        result["staged"] = await cleanup_staged_objects(
            factory,
            storage,
            settings.minio_source_bucket,
            grace_seconds=settings.orphan_grace_seconds,
            limit=limit,
            deadline=deadline,
        )
    return result
