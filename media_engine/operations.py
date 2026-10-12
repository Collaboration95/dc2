"""Command builder extracted from app/worker/operations.py; see README.md."""

from pathlib import Path


def _params(item) -> dict:
    return item["params"]


def build_edit_command(
    operations: list[dict],
    *,
    ffmpeg_binary: str,
    source_path: Path,
    output_path: Path,
    preset: str,
    crf: int,
) -> list[str]:
    by_name = {op["operation"]: op for op in operations}
    command = [ffmpeg_binary, "-hide_banner", "-loglevel", "error"]

    clip = by_name.get("clip")
    if clip is not None:
        params = _params(clip)
        command.extend(["-ss", str(params["start"]), "-to", str(params["end"])])
    command.extend(["-i", str(source_path)])

    filters: list[str] = []
    crop = by_name.get("crop")
    if crop is not None:
        params = _params(crop)
        filters.append(f"crop={params['w']}:{params['h']}:{params['x']}:{params['y']}")
    downscale = by_name.get("downscale")
    upscale = by_name.get("upscale")
    if downscale is not None:
        filters.append(f"scale=-2:{downscale['params']['height']}")
    elif upscale is not None:
        filters.append(f"scale=-2:{upscale['params']['height']}:flags=lanczos")

    convert = by_name.get("convert")
    output_format = convert["params"]["format"] if convert is not None else "mp4"
    if output_format == "mp3":
        # Video-only operations cannot change an audio-only result. The API
        # accepts the common clip+MP3 case; crop/scale combinations are caught
        # here as invalid persisted requests rather than silently ignored.
        if filters:
            raise ValueError("crop and scale cannot be combined with MP3 conversion")
        command.extend(["-vn", "-c:a", "libmp3lame"])
    elif output_format == "mkv" and not filters:
        command.extend(["-c", "copy"])
    else:
        if filters:
            command.extend(["-vf", ",".join(filters)])
        command.extend(["-c:v", "libx264", "-preset", preset, "-crf", str(crf), "-c:a", "aac"])
        if output_format == "mp4":
            command.extend(["-movflags", "+faststart"])

    command.extend(["-y", str(output_path)])
    return command
