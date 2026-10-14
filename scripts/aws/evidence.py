"""Selected schemas are sanitized before writing; archive only these known files."""

import gzip
import hashlib
import io
import json
import os
import re
import tarfile
from pathlib import Path

from scripts.evidence.common import redact

MODES = {"offline", "emulator", "local-services", "aws"}
STATUSES = {"PASS", "FAIL", "NOT_RUN"}
FILES = {"manifest.json", "cases.jsonl", "samples.jsonl", "ledger.jsonl", "cost.json"}
# Values are scalars or typed identifier lists. Unknown fields never reach disk.
FIELDS = {
    "mode",
    "status",
    "issue",
    "case",
    "source_sha",
    "config_sha256",
    "fixture_sha256",
    "fixture_id",
    "task_id",
    "job_id",
    "attempt_id",
    "image_digest",
    "owner",
    "error",
    "elapsed_ms",
    "status_code",
    "bytes",
    "upload_bytes",
    "long_jobs",
    "task_hours",
    "vcpu",
    "memory_gb",
    "hash_cost",
    "users",
    "duration_seconds",
    "p90_ms",
    "error_rate",
    "eligible",
    "sample_count",
    "sha256",
    "size_bytes",
    "started_at",
    "ended_at",
    "pull_started_at",
    "stopped_at",
    "kind",
    "amount_usd",
    "billed_seconds",
    "billing_status",
    "limits",
    "commands",
    "sdk_version",
    "authorization_id",
    "environment_id",
    "task_ids",
    "fixture_ids",
    "retained_ids",
    "generator_id",
    "failure_code",
    "measurement",
    "user",
    "phase",
    "job_status",
    "batch",
    "session_end_utc",
    "minimum_seconds",
    "core_hours",
    "overlap_hours",
    "window_started_at",
    "window_ended_at",
    "warmup_started_at",
    "warmup_ended_at",
    "booked_deadline",
}
LIMIT_FIELDS = {
    "max_worker_tasks",
    "upload_bytes",
    "long_jobs",
    "session_end_utc",
    "worker_lifetime_seconds",
    "duration_seconds",
    "users",
}
IDENTIFIER = re.compile(r"^[A-Za-z0-9_.:/@+ -]{1,256}$")
SENSITIVE = re.compile(
    r"password|secret|cookie|authorization|token|dsn|signature|credential"
    r"|(?:AKIA|ASIA)[A-Z0-9]{16}",
    re.I,
)

NUMERIC_FIELDS = {
    "issue",
    "elapsed_ms",
    "status_code",
    "bytes",
    "upload_bytes",
    "long_jobs",
    "task_hours",
    "vcpu",
    "memory_gb",
    "hash_cost",
    "users",
    "duration_seconds",
    "p90_ms",
    "error_rate",
    "sample_count",
    "size_bytes",
    "amount_usd",
    "billed_seconds",
    "minimum_seconds",
    "core_hours",
    "overlap_hours",
    "user",
    "batch",
    "window_started_at",
    "window_ended_at",
    "warmup_started_at",
    "warmup_ended_at",
    "booked_deadline",
}
BOOLEAN_FIELDS = {"eligible"}
LIST_FIELDS = {"task_ids", "fixture_ids", "retained_ids", "commands"}


def select(record, *, secrets=()):
    if not isinstance(record, dict):
        raise ValueError("Evidence requires a selected record")
    clean = {}
    for key in record.keys() & FIELDS:
        value = record[key]
        if key in NUMERIC_FIELDS and value is not None:
            if not isinstance(value, (int, float)) or isinstance(value, bool) or value < 0:
                raise ValueError("Invalid numeric evidence field")
        elif key in BOOLEAN_FIELDS and not isinstance(value, bool):
            raise ValueError("Invalid boolean evidence field")
        elif key in LIST_FIELDS and not isinstance(value, list):
            raise ValueError("Invalid evidence identifier list")
        elif (
            key not in NUMERIC_FIELDS | BOOLEAN_FIELDS | LIST_FIELDS | {"limits"}
            and value is not None
            and not isinstance(value, str)
        ):
            # Monotonic sample boundaries are the only numeric timestamp exception.
            if key not in {"started_at", "ended_at"} or not isinstance(value, (int, float)):
                raise ValueError("Invalid textual evidence field")
        if key == "limits":
            if not isinstance(value, dict):
                raise ValueError("Invalid evidence limits")
            clean[key] = select(
                {k: v for k, v in value.items() if k in LIMIT_FIELDS}, secrets=secrets
            )
            # Limit-only keys are checked explicitly below.
            for k in value.keys() & LIMIT_FIELDS:
                v = value[k]
                if isinstance(v, (int, float)) and not isinstance(v, bool) and v >= 0:
                    clean[key][k] = v
        elif isinstance(value, str):
            safe = redact(value, secrets)
            if (
                safe != value
                or SENSITIVE.search(value)
                or "://" in value
                or not IDENTIFIER.fullmatch(value)
                or "?" in value
                or "=" in value
            ):
                safe = "REDACTED"
            clean[key] = safe
        elif isinstance(value, (int, float, bool)) or value is None:
            clean[key] = value
        elif isinstance(value, list) and key in {
            "task_ids",
            "fixture_ids",
            "retained_ids",
            "commands",
        }:
            clean[key] = [select({"case": v}, secrets=secrets)["case"] for v in value]
        else:
            raise ValueError("Invalid selected evidence field")
    if "mode" in clean and clean["mode"] not in MODES:
        raise ValueError("Invalid evidence mode")
    if "status" in clean and clean["status"] not in STATUSES:
        raise ValueError("Invalid evidence status")
    # JSON encoder rejects NaN/Infinity; do this before any persistence.
    json.dumps(clean, allow_nan=False)
    return clean


class Evidence:
    def __init__(self, directory, *, secrets=()):
        self.directory = Path(directory)
        self.secrets = tuple(secrets)
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)

    def write(self, name, record):
        if name not in FILES:
            raise ValueError("Evidence filename is not allowlisted")
        clean = select(record, secrets=self.secrets)
        payload = (json.dumps(clean, sort_keys=True, allow_nan=False) + "\n").encode()
        path = self.directory / name
        if path.is_symlink():
            raise ValueError("Evidence symlink rejected")
        with path.open("ab" if name.endswith("jsonl") else "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        path.chmod(0o600)
        return clean

    def archive(self, destination):
        # Re-select and re-encode: manual/private additions cannot hitchhike into export.
        index = {}
        buffer = io.BytesIO()
        with tarfile.open(fileobj=buffer, mode="w") as tar:
            for name in sorted(FILES):
                path = self.directory / name
                if not path.exists():
                    continue
                if path.is_symlink() or not path.is_file():
                    raise ValueError("Evidence file is not regular")
                if path.stat().st_size > 8 * 1024**2:
                    raise ValueError("Evidence file too large")
                raw = path.read_bytes()
                records = (
                    [json.loads(line) for line in raw.splitlines()]
                    if name.endswith("jsonl")
                    else [json.loads(raw)]
                )
                selected = [select(r, secrets=self.secrets) for r in records]
                payload = b"".join(
                    (json.dumps(r, sort_keys=True) + "\n").encode() for r in selected
                )
                compressed = gzip.compress(payload, mtime=0)
                index[name] = {
                    "sha256": hashlib.sha256(payload).hexdigest(),
                    "size_bytes": len(payload),
                    "compressed_sha256": hashlib.sha256(compressed).hexdigest(),
                    "compressed_size_bytes": len(compressed),
                }
                info = tarfile.TarInfo(name + ".gz")
                info.size, info.mode = len(compressed), 0o600
                tar.addfile(info, io.BytesIO(compressed))
            payload = json.dumps(index, sort_keys=True).encode()
            info = tarfile.TarInfo("index.json")
            info.size, info.mode = len(payload), 0o600
            tar.addfile(info, io.BytesIO(payload))
        if Path(destination).is_symlink():
            raise ValueError("Evidence archive symlink rejected")
        Path(destination).write_bytes(buffer.getvalue())
        Path(destination).chmod(0o600)
        return index
