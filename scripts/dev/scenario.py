"""Shared local acceptance helpers; public HTTP with real TLS and bounded waits."""

import hashlib
import json
import secrets
import ssl
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import httpx

from scripts.dev.common import ROOT
from scripts.dev.contracts import validate_response
from scripts.dev.runtime import configure


def utcnow():
    return datetime.now(UTC).isoformat()


def fixture(path: Path, seconds=3, width=640, height=360):
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"testsrc2=size={width}x{height}:rate=24",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=880:sample_rate=48000",
            "-t",
            str(seconds),
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-threads",
            "2",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-movflags",
            "+faststart",
            "-shortest",
            str(path),
        ],
        check=True,
        capture_output=True,
        timeout=max(60, seconds * 4),
    )
    return {
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "bytes": path.stat().st_size,
        "seconds": seconds,
        "width": width,
        "height": height,
    }


class Scenario:
    def __init__(self, run_id, name):
        self.run_id = run_id
        self.env, self.state = configure(run_id)
        self.name = name
        self.artifacts = (
            ROOT
            / "artifacts"
            / run_id
            / f"{name}-{datetime.now(UTC):%Y%m%dT%H%M%S}-{uuid4().hex[:8]}"
        )
        self.artifacts.mkdir(parents=True, exist_ok=True)
        self.started = time.monotonic()
        self.report = {
            "name": name,
            "started_at": utcnow(),
            "run_id": run_id,
            "revision": subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
            ).strip(),
            "events": [],
            "cases": {},
            "status": "running",
        }
        self.context = ssl.create_default_context(cafile=self.state["ca_file"])
        self.clients = []
        self.save()

    def client(self):
        client = httpx.Client(
            base_url=self.state["public_url"] + "/api/",
            verify=self.context,
            timeout=15,
            follow_redirects=False,
            trust_env=False,
        )
        self.clients.append(client)
        return client

    def record(self, event, **values):
        # Callers supply safe metrics/identifiers; never persist HTTP bodies,
        # cookie jars, Authorization or presigned URLs.
        forbidden = {"password", "token", "secret", "cookie", "source_url", "output_url"}
        if any(any(word in key.lower() for word in forbidden) for key in values):
            raise ValueError("Do not store credentials or capabilities in evidence")
        self.report["events"].append(
            {
                "event": event,
                "at": utcnow(),
                "elapsed_seconds": round(time.monotonic() - self.started, 3),
                **values,
            }
        )
        self.save()

    def request(self, client, method, path, expected, *, route=None, **kwargs):
        started = time.monotonic()
        response = client.request(method, path.lstrip("/"), **kwargs)
        self.record(
            "http",
            method=method,
            route=route or path.split("?")[0],
            status=response.status_code,
            seconds=round(time.monotonic() - started, 4),
        )
        if response.status_code != expected:
            raise AssertionError(
                f"{method} {path.split('?')[0]}: expected {expected}, "
                f"received {response.status_code}"
            )
        body = response.json() if response.content else None
        if route:
            validate_response("public", route, method, expected, body)
        return body

    def account(self, prefix="acceptance"):
        client = self.client()
        email = f"{prefix}-{uuid4().hex}@example.com"
        password = secrets.token_hex(16)
        user = self.request(
            client,
            "POST",
            "auth/register",
            201,
            route="/auth/register",
            json={"email": email, "password": password},
        )
        return client, user, {"email": email, "password": password}

    def upload(self, client, path, key=None, expected=202):
        with path.open("rb") as stream:
            return self.request(
                client,
                "POST",
                "upload",
                expected,
                route="/upload",
                headers={"Idempotency-Key": key or str(uuid4())},
                files={"file": (path.name, stream, "video/mp4")},
            )

    def wait(self, client, asset, states=("done",), timeout=180):
        deadline = time.monotonic() + timeout
        previous = None
        while time.monotonic() < deadline:
            reply = self.request(client, "GET", f"jobs/{asset}", 200, route="/jobs/{job_id}")
            if reply["status"] != previous:
                self.record("asset-state", asset_id=asset, state=reply["status"])
                previous = reply["status"]
            if reply["status"] in states:
                return reply
            if reply["status"] == "failed" and "failed" not in states:
                raise AssertionError(f"Asset {asset} failed: {reply.get('error', 'unspecified')}")
            time.sleep(0.5)
        raise TimeoutError(f"Asset {asset} did not reach {states} within {timeout}s")

    def processing_job(self, owner, asset):
        with httpx.Client(trust_env=False, timeout=10) as client:
            reply = client.get(
                f"http://127.0.0.1:{self.state['processing_port']}/internal/v1/jobs",
                params={"asset_ids": asset},
                headers={
                    "Authorization": "Bearer " + self.env["PROCESSING_SERVICE_TOKEN"],
                    "X-Owner-Id": owner,
                },
            )
        if reply.status_code != 200:
            raise AssertionError(f"Private status returned {reply.status_code}")
        data = reply.json()
        validate_response("processing", "/jobs", "GET", 200, data)
        if len(data) != 1:
            raise AssertionError("Expected exactly one owner-filtered Processing job")
        return data[0]

    def passed(self, case, evidence):
        self.report["cases"][case] = {"status": "PASS", "evidence": evidence}
        self.save()

    def save(self):
        (self.artifacts / "result.json").write_text(json.dumps(self.report, indent=2) + "\n")
        (self.artifacts.parent / f"{self.name}-latest.json").write_text(
            json.dumps(
                {"result": str(self.artifacts / "result.json"), "status": self.report["status"]}
            )
            + "\n"
        )

    def finish(self, error=None):
        self.report.update(
            status="FAIL" if error else "PASS",
            finished_at=utcnow(),
            duration_seconds=round(time.monotonic() - self.started, 3),
        )
        if error:
            # Exception text from network libraries can contain signed query URLs.
            self.report["failure_type"] = type(error).__name__
        self.save()
        for client in self.clients:
            client.close()
