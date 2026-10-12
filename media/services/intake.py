import hashlib
import re
from pathlib import PurePosixPath
from uuid import uuid4

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from starlette.concurrency import run_in_threadpool

from media.errors import MediaError
from media.models import Asset, RequestKey, StagedObject, now
from media.repositories.assets import fingerprint, replay
from media.services.media_type import SNIFF_LENGTH, sniff_video_type
from media.services.storage import MAX_FILE_SIZE

ALLOWED_CONTENT_TYPES = frozenset(
    {
        "video/mp4",
        "video/mpeg",
        "video/quicktime",
        "video/webm",
        "video/x-matroska",
        "video/x-msvideo",
    }
)


def safe_filename(raw):
    name = re.sub(r"[^A-Za-z0-9._-]", "_", PurePosixPath(raw or "").name).lstrip(".")
    return name[:100] or "upload.bin"


def inspect_upload(file):
    claimed = (file.content_type or "").split(";")[0].strip().lower()
    if claimed not in ALLOWED_CONTENT_TYPES:
        raise MediaError(415, "unsupported media type")
    file.file.seek(0, 2)
    size = file.file.tell()
    file.file.seek(0)
    if size > MAX_FILE_SIZE:
        raise MediaError(413, "file too large")
    media_type = sniff_video_type(file.file.read(SNIFF_LENGTH))
    file.file.seek(0)
    if media_type is None:
        raise MediaError(415, "file content is not a recognized video format")
    digest = hashlib.sha256()
    while chunk := file.file.read(1024 * 1024):
        digest.update(chunk)
    file.file.seek(0)
    return size, media_type, digest.hexdigest()


async def stage(session, key):
    async with session.begin():
        session.add(StagedObject(key=key))


async def discard_stage(session, storage, key):
    # An intake commit acknowledgement can be lost after the Asset was adopted.
    # Lock its reservation and verify non-adoption before deleting any bytes.
    # Missing reservation means adoption or completed cleanup, never permission
    # to discard a durable source. DB unavailability leaves janitor evidence.
    try:
        async with session.begin():
            staged = await session.get(StagedObject, key, with_for_update=True)
            if staged is None:
                return
            adopted = await session.scalar(select(Asset.id).where(Asset.source_key == key))
            if adopted is None:
                await storage.delete_source(key)
            await session.execute(delete(StagedObject).where(StagedObject.key == key))
    except Exception:
        return


async def accept(session, storage, asset, operation, key, digest):
    try:
        async with session.begin():
            session.add(asset)
            await session.flush()
            if key:
                session.add(
                    RequestKey(
                        owner_id=asset.owner_id,
                        operation=operation,
                        request_key=key,
                        request_hash=digest,
                        asset_id=asset.id,
                    )
                )
                await session.flush()
            await session.execute(delete(StagedObject).where(StagedObject.key == asset.source_key))
    except IntegrityError:
        # A concurrent request won the unique request key. Discard only our staged object.
        await discard_stage(session, storage, asset.source_key)
        async with session.begin():
            prior = await replay(session, asset.owner_id, operation, key, digest)
            if prior is None:
                raise MediaError(503, "source intake could not be committed") from None
        return prior
    except Exception:
        await discard_stage(session, storage, asset.source_key)
        raise
    return asset


async def upload(session, storage, owner_id, file, key):
    size, media_type, sha256 = await run_in_threadpool(inspect_upload, file)
    filename = safe_filename(file.filename)
    digest = fingerprint(
        {"filename": filename, "size_bytes": size, "media_type": media_type, "sha256": sha256}
    )
    async with session.begin():
        prior = await replay(session, owner_id, "upload", key, digest)
    if prior:
        return prior
    asset_id = uuid4()
    source_key = f"sources/{owner_id}/{asset_id}/{filename}"
    await stage(session, source_key)
    try:
        async with session.begin():
            staged = await session.get(StagedObject, source_key, with_for_update=True)
            await storage.put_source(source_key, file.file, size, media_type)
            staged.created_at = now()
    except Exception as exc:
        await discard_stage(session, storage, source_key)
        raise MediaError(503, "source storage unavailable") from exc
    asset = Asset(
        id=asset_id,
        owner_id=owner_id,
        filename=filename,
        source_key=source_key,
        source_revision=1,
        source_sha256=sha256,
        source_size_bytes=size,
        source_media_type=media_type,
        operations=[],
    )
    return await accept(session, storage, asset, "upload", key, digest)
