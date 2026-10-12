"""HLS commands extracted from app/worker/hls.py; see README.md."""

from pathlib import Path

# The rungs we offer, shortest first. A source is never given a rung taller
# than itself.
LADDER_HEIGHTS: tuple[int, ...] = (360, 480, 720)

# Video bitrate per rung. Not a formula: these are the conventional ladder
# figures for H.264 at these heights, and a formula fitted to three points
# would be a worse kind of magic.
BITRATES: dict[int, str] = {360: "800k", 480: "1400k", 720: "2800k"}
FALLBACK_BITRATE = "800k"

PLAYLIST_CONTENT_TYPE = "application/vnd.apple.mpegurl"
SEGMENT_CONTENT_TYPE = "video/mp2t"

MASTER_PLAYLIST_NAME = "master.m3u8"
SEGMENT_SECONDS = 6


def variants_for(height: int) -> tuple[int, ...]:
    """The rungs a source of this height should get, shortest first.

    Never taller than the source. A source shorter than the lowest rung
    still gets exactly one rendition, at its own height, rather than being
    upscaled into the 360p rung or being given no ladder at all.
    """
    rungs = {rung for rung in LADDER_HEIGHTS if rung <= height}
    return tuple(sorted(rungs)) if rungs else (height,)


def content_type_for(name: str) -> str:
    """A playlist is not a video, and MinIO serves back whatever it was told.

    Getting this wrong is invisible locally -- the bytes are the same either
    way -- and shows up only as a player refusing a manifest it was handed
    under a video content type.
    """
    return PLAYLIST_CONTENT_TYPE if name.endswith(".m3u8") else SEGMENT_CONTENT_TYPE


def build_ladder_command(
    source_path: Path,
    output_dir: Path,
    *,
    heights: tuple[int, ...],
    ffmpeg_binary: str = "ffmpeg",
    preset: str = "veryfast",
) -> list[str]:
    """One invocation producing every rendition and the master playlist.

    Built from `heights` rather than hardcoding three of everything: the
    `split` count, the per-rendition maps and `-var_stream_map` all have to
    agree, and a mismatch between them is an FFmpeg error rather than a
    quietly wrong output -- which is the good case, and the reason this
    function is what the tests cover.
    """
    count = len(heights)

    labels = "".join(f"[v{index}]" for index in range(count))
    scales = ";".join(
        f"[v{index}]scale=-2:{height}[v{index}out]" for index, height in enumerate(heights)
    )
    filter_complex = f"[0:v]split={count}{labels};{scales}"

    command = [
        ffmpeg_binary,
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(source_path),
        "-filter_complex",
        filter_complex,
    ]

    for index, height in enumerate(heights):
        command += [
            "-map",
            f"[v{index}out]",
            f"-c:v:{index}",
            "libx264",
            "-preset",
            preset,
            f"-b:v:{index}",
            BITRATES.get(height, FALLBACK_BITRATE),
        ]

    # `a:0?` rather than `a:0`: the trailing question mark makes the mapping
    # optional, so a source with no audio track does not fail here. It fails
    # a moment later in `-var_stream_map`, which names an audio stream that
    # does not exist -- deliberately left as a ladder failure rather than
    # special-cased, because the MP4 fallback already covers it and guessing
    # at a silent audio track would be worse.
    for _ in heights:
        command += ["-map", "a:0?"]
    command += ["-c:a", "aac", "-b:a", "128k"]

    var_stream_map = " ".join(f"v:{index},a:{index}" for index in range(count))
    command += [
        "-f",
        "hls",
        "-hls_time",
        str(SEGMENT_SECONDS),
        "-hls_playlist_type",
        "vod",
        "-hls_segment_filename",
        str(output_dir / "v%v" / "seg%05d.ts"),
        "-master_pl_name",
        MASTER_PLAYLIST_NAME,
        "-var_stream_map",
        var_stream_map,
        "-y",
        str(output_dir / "v%v" / "index.m3u8"),
    ]
    return command
