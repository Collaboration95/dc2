from pathlib import Path

from media_engine.hls import (
    MASTER_PLAYLIST_NAME,
    build_ladder_command,
    content_type_for,
    variants_for,
)

SOURCE = Path("/tmp/source.mp4")

# --- which rungs a source gets -------------------------------------------


def test_a_1080p_source_gets_all_three_rungs():
    assert variants_for(1080) == (360, 480, 720)


def test_a_720p_source_gets_all_three_rungs():
    assert variants_for(720) == (360, 480, 720)


def test_a_480p_source_is_never_given_a_720p_rendition():
    """The rule the whole ladder exists to respect: a rendition taller than
    the source costs encode time and storage to carry no extra detail.
    """
    assert variants_for(480) == (360, 480)


def test_an_in_between_height_only_gets_the_rungs_below_it():
    assert variants_for(600) == (360, 480)


def test_a_360p_source_gets_exactly_one_rendition():
    assert variants_for(360) == (360,)


def test_a_source_shorter_than_every_rung_gets_one_at_its_own_height():
    """A 240p upload must still get a playable ladder, and must still not be
    upscaled -- so the rung is the source's own height, not the lowest rung.
    """
    assert variants_for(240) == (240,)


# --- the command ----------------------------------------------------------


def test_split_count_and_var_stream_map_agree_with_the_variant_list():
    """These three have to describe the same number of renditions. A
    mismatch is an FFmpeg error rather than a quietly wrong output, which is
    the good case -- but only because this is built from the list rather
    than hardcoded at three.
    """
    command = build_ladder_command(SOURCE, Path("/tmp/out"), heights=(360, 480))

    filter_complex = command[command.index("-filter_complex") + 1]
    assert "split=2" in filter_complex
    assert filter_complex.count("scale=-2:") == 2

    var_stream_map = command[command.index("-var_stream_map") + 1]
    assert var_stream_map == "v:0,a:0 v:1,a:1"
    assert command.count("-map") == 4  # two video, two audio


def test_each_rendition_is_scaled_to_its_own_height():
    command = build_ladder_command(SOURCE, Path("/tmp/out"), heights=(360, 480, 720))
    filter_complex = command[command.index("-filter_complex") + 1]

    for height in (360, 480, 720):
        assert f"scale=-2:{height}" in filter_complex


def test_the_master_playlist_is_named():
    command = build_ladder_command(SOURCE, Path("/tmp/out"), heights=(360,))
    assert command[command.index("-master_pl_name") + 1] == MASTER_PLAYLIST_NAME


def test_audio_is_mapped_optionally_so_a_silent_source_does_not_fail_here():
    command = build_ladder_command(SOURCE, Path("/tmp/out"), heights=(360,))
    assert "a:0?" in command


def test_a_single_rung_still_produces_a_valid_two_stream_map():
    command = build_ladder_command(SOURCE, Path("/tmp/out"), heights=(240,))
    assert command[command.index("-var_stream_map") + 1] == "v:0,a:0"


# --- content types --------------------------------------------------------


def test_playlists_and_segments_get_different_content_types():
    """MinIO serves back whatever it was told. A manifest handed over as
    video/mp4 is a bug that looks fine in storage and only shows up as a
    player refusing to load it.
    """
    assert content_type_for("master.m3u8") == "application/vnd.apple.mpegurl"
    assert content_type_for("index.m3u8") == "application/vnd.apple.mpegurl"
    assert content_type_for("seg00001.ts") == "video/mp2t"
