"""Full-content upload identities retain their digest with bounded allocation."""

import hashlib
import tracemalloc

import pytest

from publisher.state import file_identity


@pytest.mark.parametrize("size", [0, 17, 256 * 1024 + 1, 2 * 1024 * 1024 + 17])
def test_identity_hashes_every_byte_including_partial_final_blocks(tmp_path, size):
    path = tmp_path / "holiday.mp4"
    content = (bytes(range(256)) * (size // 256 + 1))[:size]
    path.write_bytes(content)

    assert file_identity(path) == [path.name, size, hashlib.sha256(content).hexdigest()]


def test_same_size_file_edit_changes_identity(tmp_path):
    path = tmp_path / "clip.mp4"
    path.write_bytes(b"first video")
    original = file_identity(path)
    path.write_bytes(b"other video")
    edited = file_identity(path)

    assert original[:2] == edited[:2]
    assert original[2] != edited[2]
    assert edited[2] == hashlib.sha256(b"other video").hexdigest()


def test_file_identity_keeps_peak_python_allocation_below_one_mib(tmp_path):
    path = tmp_path / "clip.mp4"
    size = 8 * 1024 * 1024
    with path.open("wb") as stream:
        stream.truncate(size)

    tracemalloc.start()
    try:
        identity = file_identity(path)
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()

    assert identity == [
        path.name,
        size,
        "2daeb1f36095b44b318410b3f4e8b5d989dcc7bb023d1426c492dab0a3053e74",
    ]
    # Excludes fixture creation; bounds Python allocations, rather than process RSS.
    assert peak < 1024 * 1024, f"file hashing allocated {peak} bytes at peak"
