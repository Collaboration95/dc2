"""Lane fixtures for the D4 burst: N distinct copies of one short MP4, one folder each.

    python3 -m scripts.demo.fixtures SOURCE OUT --lane standard --count 5   # Fargate, 64-100 MiB
    python3 -m scripts.demo.fixtures SOURCE OUT --lane short --count 4      # Lambda, <= 64 MiB

Made the way the sl1021 Fargate arm's fixture was: the source's bytes unchanged, then one
top-level MP4 `free` box appended. The streams (and so the encode) are the source's; only the file
size changes. The dispatch admission rule reads the size alone (processing.short_lane), so a
padded file goes to the standard lane. Each copy's box starts with its own tag, so no two files
share a hash; the Publisher keys an upload intent on name, size and SHA-256 and the API keys a
reservation on its request id, so distinct bytes are cheap insurance rather than a requirement.

Writes OUT/<lane>-<n>/<stem>-<lane>-<n>.mp4 for n = 1..count, the folder layout the publish
commands in the recording notes expect. Standard library only.
"""

import argparse
import struct
import sys
from pathlib import Path

from processing.short_lane import MAX_SOURCE_BYTES

MIB = 1024 * 1024
# Media refuses a source above 100 MiB (media/services/storage.py MAX_FILE_SIZE; the worker checks
# the same bound in processing/worker/source.py). Not imported: storage needs the minio client.
MAX_UPLOAD_BYTES = 100 * MIB
PAD_MIB = 70  # sl1021: a 2.4 MiB clip + 70 MiB of free box = 75,923,783 bytes
CHUNK = 4 * MIB


class FixtureError(Exception):
    pass


def boxes(path):
    """Top-level ISO BMFF boxes as (type, offset, size); raises on any malformed header."""
    path = Path(path)
    total, found, offset = path.stat().st_size, [], 0
    with path.open("rb") as stream:
        while offset < total:
            stream.seek(offset)
            head = stream.read(8)
            if len(head) < 8:
                raise FixtureError(f"Truncated box header at {offset}")
            size, kind = struct.unpack(">I4s", head)
            if size == 1:  # 64-bit largesize follows the type
                large = stream.read(8)
                if len(large) < 8:
                    raise FixtureError(f"Truncated largesize at {offset}")
                size = struct.unpack(">Q", large)[0]
            elif size == 0:  # box runs to the end of the file
                size = total - offset
            if size < 8 or offset + size > total:
                raise FixtureError(f"Box {kind!r} at {offset} has an invalid size {size}")
            found.append((kind.decode("latin-1"), offset, size))
            offset += size
    return found


def check_mp4(path):
    """The source must be a plain MP4: ftyp first, moov and mdat present, boxes fill the file."""
    found = boxes(path)
    kinds = [k for k, _, _ in found]
    if not kinds or kinds[0] != "ftyp" or "moov" not in kinds or "mdat" not in kinds:
        raise FixtureError(f"{path} is not an MP4 with ftyp, moov and mdat (found {kinds})")
    return found


def padded_copy(source, target, *, tag, pad_bytes):
    """Copy `source` to `target` and append one `free` box of `pad_bytes` payload."""
    label = tag.encode()[:pad_bytes]
    with Path(source).open("rb") as src, Path(target).open("wb") as out:
        while chunk := src.read(CHUNK):
            out.write(chunk)
        out.write(struct.pack(">I4s", pad_bytes + 8, b"free"))
        out.write(label)
        left = pad_bytes - len(label)
        while left:
            step = min(CHUNK, left)
            out.write(bytes(step))
            left -= step


def make(source, out, *, lane, count, pad_mib=PAD_MIB):
    source, out = Path(source), Path(out)
    check_mp4(source)
    size = source.stat().st_size
    if lane == "standard":
        pad = pad_mib * MIB
        if not MAX_SOURCE_BYTES < size + 8 + pad < MAX_UPLOAD_BYTES:
            raise FixtureError(
                f"{size} + {pad_mib} MiB is outside the standard-lane window "
                f"({MAX_SOURCE_BYTES} < size < {MAX_UPLOAD_BYTES}); change --pad-mib"
            )
    else:
        pad = 64  # just the distinct tag
        if size + 8 + pad > MAX_SOURCE_BYTES:
            raise FixtureError(f"{source} is over the short lane's {MAX_SOURCE_BYTES}-byte bound")
    made = []
    for n in range(1, count + 1):
        folder = out / f"{lane}-{n}"
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / f"{source.stem}-{lane}-{n}.mp4"
        padded_copy(
            source, target, tag=f"dc2-demo-fixture {lane}-{n} of {source.name}", pad_bytes=pad
        )
        found = check_mp4(target)
        if found[-1][0] != "free" or target.stat().st_size != size + 8 + pad:
            raise FixtureError(f"{target} did not come out as source + one free box")
        made.append(target)
    return made


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("source", type=Path, help="short MP4 (<= 60 s, <= 1080p, with audio)")
    parser.add_argument("out", type=Path, help="private directory outside Git")
    parser.add_argument("--lane", choices=("standard", "short"), required=True)
    parser.add_argument("--count", type=int, default=5)
    parser.add_argument("--pad-mib", type=int, default=PAD_MIB, help="standard lane only")
    args = parser.parse_args(argv)
    if not 1 <= args.count <= 20:
        parser.error("--count is 1..20")
    try:
        made = make(args.source, args.out, lane=args.lane, count=args.count, pad_mib=args.pad_mib)
    except (FixtureError, OSError) as error:
        print(f"fixtures: {error}", file=sys.stderr)
        return 2
    for path in made:
        print(f"{path}\t{path.stat().st_size} bytes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
