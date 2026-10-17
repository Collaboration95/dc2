"""Durable dispatch, retry and cancel intents. No Processing persistence imports."""

import asyncio
from collections import defaultdict
from datetime import timedelta
from pathlib import PurePosixPath
from uuid import NAMESPACE_URL, uuid4, uuid5

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from legacy.media_peer.errors import PeerError
from media.errors import MediaError
from media.models import Asset, CleanupIntent, RequestKey, RetryIntent, StagedObject, now
from media.repositories.assets import fingerprint, get_asset, replay, source_descriptor
from media.schemas.public import PublicJob
from media.services import direct_intake
from media.services.intake import accept, discard_stage, stage


def next_try(attempts):
    return now() + timedelta(seconds=min(60, 2 ** min(attempts, 6)))


async def dispatch(session, peer, storage, asset_id):
    async with session.begin():
        # Bounded network operation under local guard serializes dispatch/delete.
        # P's asset guard is still required for lost acknowledgements and late delivery.
        asset = await get_asset(session, asset_id, None, include_deleted=True, lock=True)
        if asset.deleted_at or asset.submission_state != "pending":
            return
        asset.submit_attempts += 1
        try:
            version = await direct_intake.pinned_version(session, asset)
            url, expires = await storage.source_grant(asset.source_key, version)
            payload = {
                "asset_id": str(asset.id),
                "owner_id": str(asset.owner_id),
                "source": source_descriptor(asset),
                "source_url": url,
                "source_url_expires_at": expires.isoformat(),
            }
            if asset.operations:
                payload["operations"] = asset.operations
            job = await peer.submit(asset.owner_id, payload)
        except PeerError as exc:
            asset.last_submit_error = "Processing submission unavailable"
            asset.next_submit_at = next_try(asset.submit_attempts)
            if exc.status_code in (409, 410):
                asset.submission_state = "error"
                asset.last_submit_error = "Processing rejected the immutable submission"
        except Exception:
            asset.last_submit_error = "source access unavailable"
            asset.next_submit_at = next_try(asset.submit_attempts)
        else:
            asset.processing_job_id = job.job_id
            asset.submission_state = "submitted"
            asset.submitted_at = now()
            asset.last_submit_error = None


def verify_link(asset, job):
    if (
        job.owner_id != asset.owner_id
        or job.asset_id != asset.id
        or job.job_id != asset.processing_job_id
        or job.source.model_dump(mode="json") != source_descriptor(asset)
    ):
        raise MediaError(503, "Processing status unavailable")
    return job


async def live_job(peer, asset):
    try:
        job = await peer.read(asset.owner_id, asset.processing_job_id)
    except PeerError as exc:
        raise MediaError(503, "Processing status unavailable") from exc
    return verify_link(asset, job)


async def projection(asset, job, storage, settings):
    result = PublicJob(
        id=asset.id,
        filename=asset.filename,
        status="queued",
        submission_status=asset.submission_state,
    )
    if asset.submission_state == "error":
        result.status = "failed"
        result.error = asset.last_submit_error
    elif job is not None:
        verify_link(asset, job)
        result.status = job.status
        if job.status == "failed":
            result.error = job.error or job.current_attempt.error or "processing failed"
        if job.status == "done":
            primary = next((o for o in job.outputs if o.kind == "primary"), None)
            if primary is None:
                raise MediaError(503, "Processing output unavailable")
            result.output_url = await storage.sign_output(primary.object_key)
            hls = next((o for o in job.outputs if o.kind == "hls_manifest"), None)
            if hls:
                master = PurePosixPath(hls.object_key).name
                result.hls_url = (
                    f"{settings.api_public_prefix.rstrip('/')}/jobs/{asset.id}/hls/{master}"
                )
    return result


async def project_page(assets, peer, storage, settings):
    owners = defaultdict(list)
    for asset in assets:
        if asset.submission_state == "submitted":
            owners[asset.owner_id].append(asset.id)

    async def read(owner, ids):
        try:
            jobs = await peer.batch(owner, ids)
        except PeerError as exc:
            raise MediaError(503, "Processing status unavailable") from exc
        if {j.asset_id for j in jobs} != set(ids):
            raise MediaError(503, "Processing status unavailable")
        return jobs

    batches = await asyncio.gather(*(read(owner, ids) for owner, ids in owners.items()))
    jobs = {job.asset_id: job for batch in batches for job in batch}
    return list(
        await asyncio.gather(*(projection(a, jobs.get(a.id), storage, settings) for a in assets))
    )


async def reserve_retry(session, owner_id, asset_id, key):
    async with session.begin():
        asset = await get_asset(session, asset_id, owner_id, include_deleted=True, lock=True)
        if asset.deleted_at:
            raise MediaError(410, "previously accepted item is deleted")
        digest = fingerprint({"asset_id": str(asset_id)})
        # Deterministic internal identity is owner+operation+public request key.
        if key:
            await session.execute(
                insert(RequestKey)
                .values(
                    owner_id=owner_id,
                    operation="retry",
                    request_key=key,
                    request_hash=digest,
                    asset_id=asset_id,
                    created_at=now(),
                )
                .on_conflict_do_nothing()
            )
            request = await session.get(RequestKey, (owner_id, "retry", key))
            if request.request_hash != digest:
                raise MediaError(409, "idempotency key used for a different request")
            retry_id = uuid5(NAMESPACE_URL, f"media/retry/{owner_id}/{key}")
            intent = await session.get(RetryIntent, retry_id)
        else:
            # A bodyless legacy retry following transport loss reuses the unresolved
            # intent. A confirmed/rejected request ends that logical operation.
            intent = await session.scalar(
                select(RetryIntent)
                .where(
                    RetryIntent.asset_id == asset_id,
                    RetryIntent.confirmed_at.is_(None),
                    RetryIntent.rejected_at.is_(None),
                )
                .order_by(RetryIntent.created_at.desc())
            )
            retry_id = uuid4()
        if asset.submission_state != "submitted" or not asset.processing_job_id:
            raise MediaError(409, "only submitted failed jobs can be retried")
        if intent is None:
            intent = RetryIntent(id=retry_id, asset_id=asset_id)
            session.add(intent)
        await session.flush()
        return intent.id


async def dispatch_retry(session, peer, retry_id):
    error = None
    async with session.begin():
        intent = await session.get(RetryIntent, retry_id)
        asset = await get_asset(session, intent.asset_id, None, include_deleted=True, lock=True)
        intent = await session.get(RetryIntent, retry_id, populate_existing=True)
        if asset.deleted_at:
            raise MediaError(410, "previously accepted item is deleted")
        if intent.rejected_at:
            raise MediaError(409, "only failed jobs can be retried")
        if intent.confirmed_at:
            return asset.id
        intent.attempts += 1
        try:
            job = await peer.retry(asset.owner_id, asset.processing_job_id, intent.id)
            verify_link(asset, job)
        except (PeerError, MediaError) as exc:
            intent.last_error = "retry could not be confirmed"
            intent.next_try_at = next_try(intent.attempts)
            if isinstance(exc, PeerError) and exc.status_code in (409, 410):
                intent.rejected_at = now()
                error = MediaError(exc.status_code, "only failed jobs can be retried")
            else:
                error = MediaError(503, "retry could not be confirmed; repeat the same request")
        else:
            intent.confirmed_at = now()
            intent.last_error = None
        asset_id = asset.id
    # Persist the identity and outcome before returning a public error.
    if error:
        raise error
    return asset_id


async def tombstone(session, asset_id, owner_id):
    async with session.begin():
        asset = await get_asset(session, asset_id, owner_id, include_deleted=True, lock=True)
        if asset.deleted_at is None:
            asset.deleted_at = now()
            session.add(CleanupIntent(asset_id=asset_id))
    return asset


async def cleanup(session, peer, storage, asset_id):
    async with session.begin():
        asset = await get_asset(session, asset_id, None, include_deleted=True, lock=True)
        intent = await session.get(CleanupIntent, asset_id)
        if intent is None or not asset.deleted_at or intent.source_deleted_at:
            return
        intent.attempts += 1
        intent.next_try_at = next_try(intent.attempts)
        try:
            if not intent.processing_deleted_at:
                # Never require a job ID. An absent submit ACK is exactly why
                # cancellation must reserve P's owner-bound Asset guard.
                await peer.cancel(asset.owner_id, asset.id)
                intent.processing_deleted_at = now()
            await storage.delete_source(asset.source_key)
        except Exception:
            intent.last_error = "asset cleanup not yet confirmed"
        else:
            intent.source_deleted_at = now()
            intent.last_error = None


async def edit(session, peer, storage, owner_id, parent_id, request, key):
    operations = request.stored_operations()
    digest = fingerprint({"parent_id": str(parent_id), "operations": operations})
    async with session.begin():
        # Replay before resolving parent: its deletion cannot invalidate a child.
        prior = await replay(session, owner_id, "edit", key, digest)
        if prior:
            return prior
        parent = await get_asset(session, parent_id, owner_id)
    if parent.submission_state != "submitted":
        raise MediaError(409, "only completed jobs can be edited")
    job = await live_job(peer, parent)
    output = next((o for o in job.outputs if o.kind == "primary"), None)
    if job.status != "done" or output is None:
        raise MediaError(409, "only completed jobs can be edited")
    convert = request.operation("convert")
    extension = convert.params.format if convert else "mp4"
    filename = f"{PurePosixPath(parent.filename).stem[:80] or 'video'}-edited.{extension}"

    asset_id = uuid4()
    source_key = f"sources/{owner_id}/{asset_id}/source"
    await stage(session, source_key)
    try:
        # Guard parent during copy: deletion cannot clean its output while we copy.
        async with session.begin():
            await get_asset(session, parent_id, owner_id, lock=True)
            staged = await session.get(StagedObject, source_key, with_for_update=True)
            size, sha256 = await storage.copy_output_source(output, source_key)
            staged.created_at = now()
            staged.write_uncertain = False
    except Exception as exc:
        await discard_stage(session, storage, source_key)
        if isinstance(exc, MediaError):
            raise
        raise MediaError(503, "independent source copy unavailable") from exc
    asset = Asset(
        id=asset_id,
        owner_id=owner_id,
        filename=filename,
        source_key=source_key,
        source_revision=1,
        source_sha256=sha256,
        source_size_bytes=size,
        source_media_type=output.media_type,
        source_asset_id=parent_id,
        operations=operations,
    )
    return await accept(session, storage, asset, "edit", key, digest)
