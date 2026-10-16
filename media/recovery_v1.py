"""Bounded Media repair after durable Processing cancellation acknowledgements.

Media only deletes its source objects. Processing owns its output cleanup ledger.
Keep successful source scan intents forever: late writes and lost delete responses
must be retried. No storage operation runs inside a SQL transaction or row lock.
"""

import asyncio
import time
from datetime import timedelta
from types import SimpleNamespace

from sqlalchemy import or_, select

from media.models import Asset, CleanupIntent, now
from media.projections import source_for_asset
from media.services.direct_intake import (
    CLEANUP_HORIZON,
    cleanup_delay,
    cleanup_expired_uploads,
)


def unretired(horizon):
    # No schema change: a tombstone retires once a scan succeeded at least one
    # horizon after Processing acknowledged the cancellation. Failed scans never retire.
    return or_(
        CleanupIntent.source_deleted_at.is_(None),
        CleanupIntent.source_deleted_at < CleanupIntent.processing_deleted_at + horizon,
    )


async def remove_source_versions(storage, bucket, key):
    # A2's primitive is the only source-version deletion authority. Compatibility
    # with its initial export allows this commit to integrate independently.
    remove = getattr(storage, "remove_source_versions", None)
    if remove is not None:
        await remove(bucket, key)
    else:
        await storage.delete_direct_upload(SimpleNamespace(bucket=bucket, key=key))


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
                intent.next_try_at = now() + timedelta(seconds=cleanup_delay(intent.attempts))
                if error is None:
                    intent.source_deleted_at = now()
    return cleaned


async def run_once(factory, settings, storage, *, deadline=None):
    """B's repair handler calls this after publishing commands; no peer needed."""
    limit = min(settings.recovery_batch_size, 100)
    result = {"cleanup": 0, "uploads": 0}
    if deadline is None or time.monotonic() < deadline:
        result["cleanup"] = await cleanup_tombstones(
            factory,
            storage,
            limit=limit,
            deadline=deadline,
        )
    if deadline is None or time.monotonic() < deadline:
        # The scan reserves each row before storage I/O and bounds that I/O by the
        # deadline itself, so a cut-off pass leaves a lease, not a half-written state.
        result["uploads"] = await cleanup_expired_uploads(
            factory, storage, limit=limit, deadline=deadline
        )
    return result
