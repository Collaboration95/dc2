"""Attempt pipeline: probe, edit, HLS ladder and output PUT around an injected downloader."""

import asyncio
import logging

from media_engine.hls import build_ladder_command, content_type_for, variants_for
from media_engine.operations import build_edit_command
from media_engine.probe import parse_probe, probe_command
from media_engine.validation import validate_clip, validate_crop
from processing import lifecycle
from processing.worker.supervisor import AttemptDeadline, LeaseLost

logger = logging.getLogger(__name__)


async def pipeline(
    work, settings, supervisor, client, store, directory, *, downloader, admit=None
):
    source = directory / "source"
    await supervisor.guard(downloader(client, work, settings, source))
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
