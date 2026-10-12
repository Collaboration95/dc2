import json
from pathlib import Path

import pytest

from media_engine.operations import build_edit_command
from media_engine.probe import parse_probe, probe_command


def build(ops):
    return build_edit_command(
        ops,
        ffmpeg_binary="ffmpeg",
        source_path=Path("source"),
        output_path=Path("out"),
        preset="veryfast",
        crf=23,
    )


def test_fixed_order_and_codecs():
    cmd = build(
        [
            {"operation": "clip", "params": {"start": 1, "end": 2}},
            {"operation": "crop", "params": {"x": 0, "y": 0, "w": 32, "h": 32}},
            {"operation": "downscale", "params": {"height": 16}},
        ]
    )
    assert cmd.index("-ss") < cmd.index("-i")
    assert cmd[cmd.index("-vf") + 1] == "crop=32:32:0:0,scale=-2:16"
    assert "+faststart" in cmd
    assert "libx264" in build([])
    assert "libmp3lame" in build([{"operation": "convert", "params": {"format": "mp3"}}])
    assert "copy" in build([{"operation": "convert", "params": {"format": "mkv"}}])
    assert "scale=-2:720:flags=lanczos" in build(
        [{"operation": "upscale", "params": {"height": 720}}]
    )
    with pytest.raises(ValueError, match="MP3"):
        build(
            [
                {"operation": "convert", "params": {"format": "mp3"}},
                {"operation": "upscale", "params": {"height": 720}},
            ]
        )


@pytest.mark.parametrize(
    "payload",
    [
        "invalid",
        "{}",
        "null",
        '{"streams":[]}',
        json.dumps({"streams": [{"width": 0, "height": 2}], "format": {"duration": "1"}}),
        json.dumps({"streams": [{"width": 2, "height": 2}], "format": {"duration": "NaN"}}),
    ],
)
def test_bad_probe_is_safe(payload):
    with pytest.raises(ValueError, match="could not be read"):
        parse_probe(payload)


def test_probe_combined_spec_and_valid_output():
    cmd = probe_command(Path("source"), "custom")
    assert cmd[0] == "custom"
    assert cmd[cmd.index("-show_entries") + 1] == "stream=width,height:format=duration"
    assert (
        parse_probe(
            json.dumps({"streams": [{"width": 32, "height": 24}], "format": {"duration": "2.5"}})
        ).duration_seconds
        == 2.5
    )
