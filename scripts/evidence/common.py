"""Small bounded HTTP and safe artifact helpers for local evidence only."""

import asyncio
import csv
import json
import re
import ssl
import time
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import httpx


class EvidenceError(ValueError):
    """Safe, locally authored diagnostic; never contains an HTTP response body."""


def utc():
    return datetime.now(UTC).isoformat()


def redact(value, secrets=()):
    """Defense in depth: callers must still construct public records by selection."""
    if isinstance(value, dict):
        return {
            key: (
                "[redacted]"
                if re.search(
                    r"password|token|secret|authorization|cookie|dsn|access_key|source_url|output_url|hls_url",
                    str(key),
                    re.I,
                )
                else redact(item, secrets)
            )
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [redact(item, secrets) for item in value]
    if isinstance(value, str):
        for secret in sorted((s for s in secrets if s), key=len, reverse=True):
            value = value.replace(secret, "[redacted]")

        def clean_url(match):
            parts = urlsplit(match.group())
            if parts.scheme not in ("https", "http") or parts.username or parts.password:
                return "[redacted-url]"
            return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))

        return re.sub(r"[a-zA-Z][a-zA-Z0-9+.-]*://[^\s\"<>]+", clean_url, value)
    return value


class Artifacts:
    def __init__(self, directory, secrets=()):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=False)
        self.secrets = list(secrets)

    def write(self, name, value):
        path = self.directory / name
        path.write_text(json.dumps(redact(value, self.secrets), indent=2, allow_nan=False) + "\n")

    def append(self, name, value):
        with (self.directory / name).open("a") as stream:
            stream.write(json.dumps(redact(value, self.secrets), allow_nan=False) + "\n")

    def csv(self, name, rows):
        rows = redact(rows, self.secrets)
        if not rows:
            return
        with (self.directory / name).open("w", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)


class Client:
    """One owner, one cookie jar. No transport retry or redirects; explicit CA."""

    def __init__(self, origin, *, ca_file=None, headers=None, timeout=10, transport=None):
        self.timeout = timeout
        self.http = httpx.AsyncClient(
            base_url=origin,
            verify=ssl.create_default_context(cafile=ca_file) if ca_file else True,
            headers=headers,
            timeout=httpx.Timeout(timeout),
            follow_redirects=False,
            trust_env=False,
            transport=transport,
        )

    async def close(self):
        await self.http.aclose()

    async def request(self, method, path, *, expected=200, **kwargs):
        start = time.monotonic()
        result = {"elapsed_ms": 0, "status_code": None, "error": None}
        data = None
        try:
            reply = await asyncio.wait_for(
                self.http.request(method, path, **kwargs), timeout=self.timeout
            )
            result["status_code"] = reply.status_code
            if reply.status_code != expected:
                result["error"] = "unexpected_status"
            elif reply.content:
                try:
                    data = reply.json()
                except ValueError:
                    result["error"] = "invalid_json"
        except (TimeoutError, httpx.TimeoutException):
            result["error"] = "timeout"
        except httpx.HTTPError:
            result["error"] = "transport_error"
        result["elapsed_ms"] = (time.monotonic() - start) * 1000
        return data, result

    async def checked(self, method, path, *, expected=200, artifacts=None, record=None, **kwargs):
        data, sample = await self.request(method, path, expected=expected, **kwargs)
        if artifacts is not None:
            artifacts.append("operations.jsonl", {"utc": utc(), **(record or {}), **sample})
        if sample["error"]:
            raise EvidenceError(f"HTTP {method} operation failed: {sample['error']}")
        return data
