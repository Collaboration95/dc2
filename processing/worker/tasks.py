"""Attempt-aware worker; private HTTP source grant, pure FFmpeg helpers, output PUT."""

import asyncio
import hashlib
import logging
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import httpx
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from media_engine.hls import build_ladder_command, content_type_for, variants_for
from media_engine.operations import build_edit_command
from media_engine.probe import parse_probe, probe_command
from media_engine.validation import validate_clip, validate_crop
from processing import lifecycle
from processing.config import get_settings
from processing.schemas import SourceAccess
from processing.worker.storage import OutputStore
from processing.worker.supervisor import AttemptDeadline, LeaseLost, Supervisor

logger = logging.getLogger(__name__)
# HTTPX INFO messages contain request URLs, including signed capabilities.
logging.getLogger("httpx").setLevel(logging.WARNING)


async def renew_source(client, work, settings):
    response = await client.post(
        f"{settings.media_url.rstrip('/')}/internal/v1/assets/{work.source['asset_id']}/source-access",
        headers={
            "Authorization": "Bearer " + settings.source_service_token.get_secret_value(),
            "X-Owner-Id": str(work.owner_id),
        },
        json={"revision": work.source["revision"]},
    )
    response.raise_for_status()
    grant = SourceAccess.model_validate(response.json())
    if grant.source.model_dump(mode="json") != work.source or grant.expires_at <= datetime.now(UTC):
        raise ValueError("the stored source descriptor changed or access expired")
    return str(grant.source_url)


async def download(client, work, settings, path):
    url = work.source_url
    # Renew on every claim: the durable original grant may be expired or signed
    # for a browser-only endpoint. Replay identity does not replace that grant.
    url = await renew_source(client, work, settings)
    for number in range(2):
        async with client.stream("GET", url) as response:
            if response.status_code in {401, 403} and number == 0:
                retry = True
            else:
                retry = False
                response.raise_for_status()
                checksum, size = hashlib.sha256(), 0
                with path.open("wb") as handle:
                    async for chunk in response.aiter_bytes():
                        size += len(chunk)
                        if size > work.source["size_bytes"]:
                            raise ValueError("the source length does not match its descriptor")
                        checksum.update(chunk)
                        handle.write(chunk)
                if (
                    size != work.source["size_bytes"]
                    or checksum.hexdigest() != work.source["sha256"]
                ):
                    raise ValueError("the source digest or length does not match its descriptor")
                return
        if retry:
            url = await renew_source(client, work, settings)


async def pipeline(
    work, settings, supervisor, client, store, directory, *, downloader=None, admit=None
):
    source = directory / "source"
    await supervisor.guard((downloader or download)(client, work, settings, source))
    operations = work.operations
    by_name = {item["operation"]: item for item in operations}
    extension = by_name.get("convert", {}).get("params", {}).get("format", "mp4")
    primary = directory / f"primary.{extension}"
    # Probe source-dependent edits; MP3 still requires video source admission.
    probe = parse_probe(await supervisor.run(probe_command(source, settings.ffprobe_binary)))
    if admit is not None:
        # The opt-in Lambda lane learns the duration only here; it may refuse before encoding.
        admit(probe)
    if "clip" in by_name:
        validate_clip(by_name["clip"]["params"], probe)
    if "crop" in by_name:
        validate_crop(by_name["crop"]["params"], probe)
    command = build_edit_command(
        operations,
        ffmpeg_binary=settings.ffmpeg_binary,
        source_path=source,
        output_path=primary,
        preset=settings.ffmpeg_preset,
        crf=settings.ffmpeg_crf,
    )
    await supervisor.run(command)
    prefix = lifecycle.output_prefix(work.job_id, work.attempt_id)
    media_type = {"mp4": "video/mp4", "mkv": "video/x-matroska", "mp3": "audio/mpeg"}[extension]
    outputs = [
        await supervisor.guard(store.put(prefix + primary.name, primary, media_type, "primary"))
    ]
    if not operations:
        try:
            hls = directory / "hls"
            heights = variants_for(probe.height)
            for i in range(len(heights)):
                (hls / f"v{i}").mkdir(parents=True)
            await supervisor.run(
                build_ladder_command(
                    source,
                    hls,
                    heights=heights,
                    ffmpeg_binary=settings.ffmpeg_binary,
                    preset=settings.ffmpeg_preset,
                )
            )
            master = None
            # Upload master last; references remain invisible until fenced finish.
            paths = sorted(hls.rglob("*"), key=lambda p: p.name == "master.m3u8")
            for path in paths:
                if path.is_file():
                    item = await supervisor.guard(
                        store.put(
                            prefix + "hls/" + path.relative_to(hls).as_posix(),
                            path,
                            content_type_for(path.name),
                            "hls_manifest",
                        )
                    )
                    if path.name == "master.m3u8":
                        master = item
            if master is not None:
                outputs.append(master)
        except (LeaseLost, AttemptDeadline, asyncio.CancelledError):
            raise
        except Exception:
            logger.info("optional HLS unavailable job=%s attempt=%s", work.job_id, work.attempt_id)
    return outputs


async def execute(factory, job_id, attempt_id, settings, *, client=None, store=None):
    work = await lifecycle.claim(factory, job_id, attempt_id, settings)
    if work is None:
        return False
    async with Supervisor(factory, work, settings) as supervisor:
        try:
            with tempfile.TemporaryDirectory(prefix="processing-") as temporary:
                if client is None:
                    async with httpx.AsyncClient(
                        timeout=settings.http_timeout_seconds, follow_redirects=False
                    ) as transport:
                        outputs = await pipeline(
                            work,
                            settings,
                            supervisor,
                            transport,
                            store or OutputStore(settings),
                            Path(temporary),
                        )
                else:
                    outputs = await pipeline(
                        work,
                        settings,
                        supervisor,
                        client,
                        store or OutputStore(settings),
                        Path(temporary),
                    )
            return await lifecycle.finish(factory, work, outputs=outputs)
        except (LeaseLost, asyncio.CancelledError):
            # Recovery/cancellation owns the terminal state; this worker has lost authority.
            return False
        except AttemptDeadline:
            # DB deadline fences this failure too; recovery records the visible timeout.
            return await lifecycle.finish(factory, work, error="Processing exceeded its time limit")
        except Exception:
            logger.warning("processing failed job=%s attempt=%s", work.job_id, work.attempt_id)
            return await lifecycle.finish(
                factory, work, error="The source or edit could not be processed"
            )


def process_attempt(job_id: str, attempt_id: str):
    async def run():
        settings = get_settings()
        engine = create_async_engine(settings.postgres_dsn, pool_pre_ping=True)
        try:
            return await execute(
                async_sessionmaker(engine, expire_on_commit=False),
                UUID(job_id),
                UUID(attempt_id),
                settings,
            )
        finally:
            await engine.dispose()

    return asyncio.run(run())
