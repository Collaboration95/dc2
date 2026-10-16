"""Media mutations with durable commands, without an HTTP Processing peer."""

from pathlib import PurePosixPath
from uuid import NAMESPACE_URL, uuid4, uuid5

from sqlalchemy import delete
from sqlalchemy.exc import IntegrityError

from media.errors import MediaError
from media.models import Asset, CleanupIntent, RequestKey, StagedObject, now
from media.projection_models import ProcessingProjection
from media.projections import read_job, source_for_asset
from media.repositories.assets import fingerprint, get_asset, replay
from media.services.intake import discard_stage, stage


async def command(session, asset, kind, *, message_id=None, source=None):
    from contracts.v1 import Envelope
    from media.messaging import stage_command

    current = await session.get(ProcessingProjection, asset.id)
    envelope = Envelope.from_dict(
        {
            "schema_version": 1,
            "message_id": str(message_id or uuid4()),
            "kind": kind,
            "owner_id": str(asset.owner_id),
            "asset_id": str(asset.id),
            "job_id": str(asset.processing_job_id) if asset.processing_job_id else None,
            "attempt_id": None,
            "state_version": current.state_version if current else 0,
            "source": source,
            "payload": {"operations": asset.operations} if kind == "submit" else {},
        }
    )
    await stage_command(session, envelope.to_dict())


async def stage_submit(session, asset, source):
    """Caller owns transaction: source adoption and command are one SQL commit."""
    await command(
        session,
        asset,
        "submit",
        source=source,
        message_id=uuid5(NAMESPACE_URL, f"media/submit/{asset.id}"),
    )


async def retry(session, owner_id, asset_id, key):
    async with session.begin():
        asset = await get_asset(session, asset_id, owner_id, lock=True)
        digest = fingerprint({"asset_id": str(asset_id)})
        # Resolve replay before current status: a retried attempt may already run.
        prior = await replay(session, owner_id, "retry", key, digest)
        if prior:
            return prior
        current = await session.get(ProcessingProjection, asset.id)
        if current is None or current.status != "failed":
            raise MediaError(409, "only failed jobs can be retried")
        if key:
            session.add(
                RequestKey(
                    owner_id=owner_id,
                    operation="retry",
                    request_key=key,
                    request_hash=digest,
                    asset_id=asset.id,
                )
            )
        # Without a public key, all requests for this failed version share identity.
        identity = (
            f"media/retry/{owner_id}/{key}"
            if key
            else (f"media/retry/{asset.id}/version/{current.state_version}")
        )
        await command(
            session,
            asset,
            "retry",
            message_id=uuid5(NAMESPACE_URL, identity),
            source=await source_for_asset(session, asset),
        )
    return asset


async def tombstone(session, owner_id, asset_id):
    async with session.begin():
        asset = await get_asset(
            session,
            asset_id,
            owner_id,
            include_deleted=True,
            lock=True,
        )
        if asset.deleted_at:
            return
        asset.deleted_at = now()
        session.add(CleanupIntent(asset_id=asset.id))
        await command(
            session,
            asset,
            "cancel",
            message_id=uuid5(NAMESPACE_URL, f"media/cancel/{asset.id}"),
        )


async def pin_copied_source(session, storage, asset):
    from media.services.direct_intake import pin_copied_source as pin

    return await pin(session, storage, asset)


async def edit(session, storage, owner_id, parent_id, request, key):
    operations = request.stored_operations()
    digest = fingerprint({"parent_id": str(parent_id), "operations": operations})
    async with session.begin():
        prior = await replay(session, owner_id, "edit", key, digest)
        if prior:
            return prior
        parent = await get_asset(session, parent_id, owner_id)
        job = await read_job(session, parent)
        output = next((o for o in job.outputs if o.kind == "primary"), None) if job else None
        if job is None or job.status != "done" or output is None:
            raise MediaError(409, "only completed jobs can be edited")
        filename_stem = PurePosixPath(parent.filename).stem[:80] or "video"
    convert = request.operation("convert")
    extension = convert.params.format if convert else "mp4"
    asset_id = uuid4()
    source_key = f"sources/{owner_id}/{asset_id}/source"
    await stage(session, source_key)
    try:
        async with session.begin():
            # Parent lock serializes output copy with Media deletion acceptance.
            await get_asset(session, parent_id, owner_id, lock=True)
            staged = await session.get(StagedObject, source_key, with_for_update=True)
            size, digest_sha256 = await storage.copy_output_source(output, source_key)
            staged.created_at = now()
            # The copy returned, so no late write can follow: recovery may now retire the
            # row once every version is gone instead of rescanning it forever.
            staged.write_uncertain = False
        asset = Asset(
            id=asset_id,
            owner_id=owner_id,
            filename=f"{filename_stem}-edited.{extension}",
            source_key=source_key,
            source_revision=1,
            source_sha256=digest_sha256,
            source_size_bytes=size,
            source_media_type=output.media_type,
            source_asset_id=parent_id,
            operations=operations,
        )
        async with session.begin():
            # Keep replay serialized with other creates using the owner RequestKey
            # unique constraint. A losing concurrent copy is durably discarded.
            staged = await session.get(StagedObject, source_key, with_for_update=True)
            if staged is None:
                raise MediaError(503, "source intake reservation expired")
            session.add(asset)
            await session.flush()
            descriptor = await pin_copied_source(session, storage, asset)
            staged.write_uncertain = False
            if key:
                session.add(
                    RequestKey(
                        owner_id=owner_id,
                        operation="edit",
                        request_key=key,
                        request_hash=digest,
                        asset_id=asset.id,
                    )
                )
            await session.flush()
            await stage_submit(session, asset, descriptor)
            await session.execute(delete(StagedObject).where(StagedObject.key == source_key))
        return asset
    except IntegrityError:
        await discard_stage(session, storage, source_key)
        async with session.begin():
            prior = await replay(session, owner_id, "edit", key, digest)
            if prior:
                return prior
        raise MediaError(503, "edit adoption unavailable") from None
    except Exception:
        await discard_stage(session, storage, source_key)
        raise
