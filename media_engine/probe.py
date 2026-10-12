"""Source metadata extracted from app/worker/probe.py; execution is supervised."""

import json
import math
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class SourceProbe:
    width: int
    height: int
    duration_seconds: float


def probe_command(path: Path, binary: str = "ffprobe") -> list[str]:
    return [
        binary,
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=width,height:format=duration",
        "-of",
        "json",
        str(path),
    ]


def parse_probe(stdout: str) -> SourceProbe:
    try:
        payload = json.loads(stdout)
        stream = payload["streams"][0]
        result = SourceProbe(
            int(stream["width"]), int(stream["height"]), float(payload["format"]["duration"])
        )
        if (
            result.width <= 0
            or result.height <= 0
            or result.duration_seconds <= 0
            or not math.isfinite(result.duration_seconds)
        ):
            raise ValueError("invalid dimensions or duration")
        return result
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        raise ValueError("the video's dimensions and duration could not be read") from exc
