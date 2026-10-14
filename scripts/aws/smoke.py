"""Small API workflow and conservative fixture reservations; no local configure()."""

import hashlib
import json
import math
import time
from dataclasses import dataclass, field
from typing import Any

from scripts.aws.evidence import select
from scripts.dev.contracts import validate_response


@dataclass
class Ledger:
    upload_limit: int = 250_000_000
    task_hour_limit: float = 8
    records: list[dict] = field(default_factory=list)
    evidence: Any = None
    mode: str = "offline"

    def append(self, record):
        clean = select({**record, "mode": self.mode})
        if self.evidence:
            self.evidence.write("ledger.jsonl", clean)
        self.records.append(clean)

    @classmethod
    def resume(cls, evidence, *, mode="offline", upload_limit=250_000_000, task_hour_limit=8):
        path = evidence.directory / "ledger.jsonl"
        if path.is_symlink():
            raise ValueError("Ledger symlink rejected")
        records = (
            [select(json.loads(line)) for line in path.read_text().splitlines()]
            if path.exists()
            else []
        )
        ledger = cls(upload_limit, task_hour_limit, records, evidence, mode)
        if (
            ledger.upload_bytes > upload_limit
            or ledger.long_jobs > 6
            or sum(r.get("task_hours", 0) for r in records) > task_hour_limit
            or any(r.get("mode") != mode for r in records)
        ):
            raise ValueError("Stored ledger differs from current envelope")
        return ledger

    @property
    def upload_bytes(self):
        return sum(r.get("upload_bytes", 0) for r in self.records)

    @property
    def long_jobs(self):
        return sum(r.get("long_jobs", 0) for r in self.records)

    def reserve(self, fixture_id, payload, *, duration_seconds, batch=None):
        if duration_seconds <= 0 or duration_seconds > 60:
            raise ValueError("Fixture duration outside preparation envelope")
        long = duration_seconds > 10
        if long and (batch not in {1, 2, 3} or duration_seconds != 60):
            raise ValueError("Long fixtures require a prewarmed capacity batch")
        if self.long_jobs + int(long) > 6 or self.upload_bytes + len(payload) > self.upload_limit:
            raise ValueError("Fixture allowance exhausted")
        if (
            long
            and sum(r.get("long_jobs", 0) for r in self.records if r.get("batch") == batch) >= batch
        ):
            raise ValueError("Capacity batch upload allowance exhausted")
        record = {
            "fixture_id": fixture_id,
            "fixture_sha256": hashlib.sha256(payload).hexdigest(),
            "upload_bytes": len(payload),
            "long_jobs": int(long),
            "batch": batch,
            "duration_seconds": duration_seconds,
        }
        # Reservation precedes upload; failures consume allowance, never hidden retries.
        self.append(record)
        return record

    def task(self, task_id, hours):
        if (
            not task_id
            or not math.isfinite(hours)
            or hours < 0
            or any(r.get("task_id") == task_id for r in self.records)
        ):
            raise ValueError("Invalid or duplicate task accounting")
        if sum(r.get("task_hours", 0) for r in self.records) + hours > self.task_hour_limit:
            raise ValueError("Task-hour allowance exhausted")
        self.append({"task_id": task_id, "task_hours": hours})

    def job(self, job_id, fixture_id, status):
        if status not in {"queued", "running", "succeeded", "failed", "abandoned"}:
            raise ValueError("Invalid job outcome")
        if not any(r.get("fixture_id") == fixture_id for r in self.records):
            raise ValueError("Job references unreserved fixture")
        self.append({"job_id": job_id, "fixture_id": fixture_id, "job_status": status})


class Workflow:
    def __init__(self, client, ledger):
        self.client, self.ledger = client, ledger

    def json(self, method, path, *, expected=200, route=None, **kwargs):
        status, body, _ = self.client.request(method, path, **kwargs)
        if status != expected:
            raise ValueError("Unexpected public workflow status")
        try:
            data = json.loads(body) if body else None
            if route:
                validate_response("public", route, method, status, data)
        except Exception:
            raise ValueError("Public response contract invalid") from None
        return data

    def upload(self, fixture_id, payload, *, duration_seconds, filename="fixture.mp4"):
        self.ledger.reserve(fixture_id, payload, duration_seconds=duration_seconds)
        return self.json(
            "POST",
            "/api/upload",
            expected=202,
            route="/upload",
            files={"file": (filename, payload, "video/mp4")},
        )

    def login(self, email, password):
        return self.json("POST", "/api/auth/login", json={"email": email, "password": password})

    def poll(self, job_id, *, deadline, clock=time.monotonic, sleep=time.sleep):
        if not math.isfinite(deadline):
            raise ValueError("Finite public workflow deadline required")
        while clock() < deadline:
            data = self.json("GET", f"/api/jobs/{job_id}", route="/jobs/{job_id}")
            if data["status"] in {"done", "failed", "abandoned"}:
                return data
            sleep(min(1, max(0, deadline - clock())))
        raise ValueError("Public workflow polling deadline exceeded")

    def retry(self, job_id, key):
        # Existing stored source: no fixture reservation or video resubmission.
        return self.json(
            "POST",
            f"/api/jobs/{job_id}/retry",
            expected=202,
            route="/jobs/{job_id}/retry",
            headers={"Idempotency-Key": key},
        )

    def edit(self, job_id, operations, key):
        return self.json(
            "POST",
            f"/api/jobs/{job_id}/edit",
            expected=202,
            route="/jobs/{job_id}/edit",
            json={"operations": operations},
            headers={"Idempotency-Key": key},
        )

    def delete(self, job_id):
        return self.json("DELETE", f"/api/jobs/{job_id}", expected=204, route="/jobs/{job_id}")

    def hls_segment(self, path):
        # The authenticated facade alone may return a capability. Decode is observed
        # by the separately injected browser in web_playback, not inferred from bytes.
        status, _, headers = self.client.request("GET", path)
        if status != 307 or not headers.get("location"):
            raise ValueError("Expected HLS facade redirect")
        capability = headers["location"]
        status, body, _ = self.client.download(capability)
        if status != 200 or not body:
            raise ValueError("HLS segment unavailable")
        return {"status_code": status, "bytes": len(body)}

    def ownership_denied(self, job_id):
        for method, suffix in [("GET", ""), ("POST", "/retry"), ("GET", "/hls/master.m3u8")]:
            status, _, _ = self.client.request(method, f"/api/jobs/{job_id}{suffix}")
            if status not in {403, 404}:
                raise ValueError("Cross-owner operation was not denied")

    def range(self, capability):
        status, body, headers = self.client.download(capability, byte_range=(0, 31))
        if (
            status != 206
            or len(body) != 32
            or not headers.get("content-range", "").startswith("bytes 0-31/")
        ):
            raise ValueError("MP4 range proof failed")
        return {"status_code": status, "bytes": len(body)}
