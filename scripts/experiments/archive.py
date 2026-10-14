"""Archive allowlisted safe raw records with stored and decompressed hashes."""

import argparse
import gzip
import hashlib
import json
from pathlib import Path


def archive(source, destination):
    source, destination = Path(source), Path(destination)
    destination.mkdir(parents=True, exist_ok=False)
    records = []
    for path in sorted(source.rglob("*")):
        if not path.is_file() or path.suffix not in (".json", ".jsonl", ".csv"):
            continue
        # Neither runtime configurations nor release credential state are inputs.
        raw = path.read_bytes()
        relative = path.relative_to(source)
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if path.suffix == ".jsonl" or len(raw) > 200_000:
            target = target.with_suffix(target.suffix + ".gz")
            with target.open("wb") as output:
                with gzip.GzipFile(fileobj=output, mode="wb", mtime=0) as compressor:
                    compressor.write(raw)
        else:
            target.write_bytes(raw)
        stored = target.read_bytes()
        checked = gzip.decompress(stored) if target.suffix == ".gz" else stored
        assert checked == raw
        records.append(
            {
                "source": str(relative),
                "stored": str(target.relative_to(destination)),
                "stored_bytes": len(stored),
                "stored_sha256": hashlib.sha256(stored).hexdigest(),
                "decompressed_bytes": len(raw),
                "decompressed_sha256": hashlib.sha256(raw).hexdigest(),
            }
        )
    (destination / "index.json").write_text(
        json.dumps(
            {"scope": "LOCAL experimental", "source_directory": str(source), "files": records},
            indent=2,
        )
        + "\n"
    )
    return len(records)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source")
    parser.add_argument("destination")
    args = parser.parse_args()
    print("Archived", archive(args.source, args.destination), "records")


if __name__ == "__main__":
    main()
