"""Bounded durable intent reconciler; run continuously or with --once."""

import argparse
import asyncio
import logging
from datetime import timedelta

import httpx
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from legacy.media_peer import lifecycle
from legacy.media_peer.config import get_settings
from legacy.media_peer.processing_client import ProcessingClient
from media.errors import MediaError
from media.models import Asset, CleanupIntent, RetryIntent, StagedObject, now
from media.services.storage import Storage

logger = logging.getLogger(__name__)


async def reconcile(factory, peer, storage, settings):
    counts = {"submission": 0, "retry": 0, "cleanup": 0, "orphan": 0}
    async with factory() as session:
        pending = list(
            await session.scalars(
                select(Asset.id)
                .where(
                    Asset.deleted_at.is_(None),
                    Asset.submission_state == "pending",
                    Asset.next_submit_at <= now(),
                )
                .order_by(Asset.next_submit_at)
                .limit(settings.recovery_batch_size)
            )
        )
        retries = list(
            await session.scalars(
                select(RetryIntent.id)
                .join(Asset)
                .where(
                    Asset.deleted_at.is_(None),
                    RetryIntent.confirmed_at.is_(None),
                    RetryIntent.rejected_at.is_(None),
                    RetryIntent.next_try_at <= now(),
                )
                .order_by(RetryIntent.next_try_at)
                .limit(settings.recovery_batch_size)
            )
        )
        cleanups = list(
            await session.scalars(
                select(CleanupIntent.asset_id)
                .where(
                    CleanupIntent.source_deleted_at.is_(None), CleanupIntent.next_try_at <= now()
                )
                .order_by(CleanupIntent.next_try_at)
                .limit(settings.recovery_batch_size)
            )
        )
    for kind, ids in (("cleanup", cleanups), ("retry", retries), ("submission", pending)):
        for identifier in ids:
            try:
                async with factory() as session:
                    if kind == "submission":
                        await lifecycle.dispatch(session, peer, storage, identifier)
                    elif kind == "retry":
                        await lifecycle.dispatch_retry(session, peer, identifier)
                    else:
                        await lifecycle.cleanup(session, peer, storage, identifier)
            except MediaError:
                # A delete/rejection can race selection. Its durable state wins.
                pass
            except Exception:
                # Never log exception text: HTTP/SQL exceptions can carry secrets.
                logger.warning("media %s intent %s deferred", kind, identifier)
            counts[kind] += 1
    async with factory() as session:
        async with session.begin():
            stages = list(
                await session.scalars(
                    select(StagedObject)
                    .where(
                        StagedObject.created_at
                        < now() - timedelta(seconds=settings.orphan_grace_seconds),
                        ~select(Asset.id).where(Asset.source_key == StagedObject.key).exists(),
                    )
                    .order_by(StagedObject.created_at, StagedObject.key)
                    .limit(settings.recovery_batch_size)
                    .with_for_update(skip_locked=True)
                )
            )
            for stage in stages:
                try:
                    await storage.delete_source(stage.key)
                except Exception:
                    continue
                if stage.write_uncertain:
                    # No finite quiet period proves that a timed-out remote PUT
                    # stopped. Retain its key for later DELETEs, even if absent.
                    stage.created_at = now()
                else:
                    await session.execute(delete(StagedObject).where(StagedObject.key == stage.key))
                counts["orphan"] += 1
    return counts


async def run(once=False):
    settings = get_settings()
    engine = create_async_engine(settings.postgres_dsn, pool_pre_ping=True)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    storage = Storage(settings)
    try:
        async with httpx.AsyncClient(
            base_url=settings.processing_url, timeout=settings.processing_timeout_seconds
        ) as client:
            peer = ProcessingClient(client, settings.processing_service_token.get_secret_value())
            while True:
                try:
                    counts = await reconcile(factory, peer, storage, settings)
                    logger.info("media reconciliation %s", counts)
                except Exception:
                    if once:
                        raise RuntimeError("Media reconciliation failed") from None
                    logger.warning("media reconciliation deferred")
                if once:
                    return
                await asyncio.sleep(settings.recovery_interval_seconds)
    finally:
        await engine.dispose()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run(args.once))


if __name__ == "__main__":
    main()
