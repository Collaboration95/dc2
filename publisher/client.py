"""Cookie-authenticated Media public API with explicit trust and bounded requests."""

import os
import ssl
import tempfile
import time
from http.cookiejar import MozillaCookieJar
from pathlib import Path
from uuid import UUID

import httpx


class PublisherError(Exception):
    """Safe diagnostic: never includes response bodies, cookies or request URLs."""

    def __init__(self, message, *, uncertain=False, status=None):
        super().__init__(message)
        self.uncertain = uncertain
        self.status = status


def private_write(path, writer):
    """Atomically replace private client state, including session cookies."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, name = tempfile.mkstemp(dir=path.parent)
    os.close(fd)
    try:
        writer(name)
        os.chmod(name, 0o600)
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def asset_id(value):
    return str(UUID(value))


class PublicClient:
    def __init__(self, base_url, cookie_file, ca_file=None, timeout=20, *, transport=None):
        url = httpx.URL(base_url)
        if url.scheme != "https" or not url.host or url.userinfo or url.query or url.fragment:
            raise ValueError("Use an HTTPS API base URL without credentials, query or fragment.")
        self.cookie_file = Path(cookie_file)
        self.jar = MozillaCookieJar()
        if self.cookie_file.exists():
            self.jar.load(str(self.cookie_file), ignore_discard=True)
        trust = ssl.create_default_context(cafile=ca_file)
        self.http = httpx.Client(
            base_url=base_url.rstrip("/") + "/",
            verify=trust,
            timeout=timeout,
            cookies=self.jar,
            transport=transport,
            follow_redirects=False,
            trust_env=False,
        )

    def close(self):
        try:
            private_write(self.cookie_file, lambda name: self.jar.save(name, ignore_discard=True))
        finally:
            self.http.close()

    def request(self, method, path, **kwargs):
        try:
            response = self.http.request(method, path, **kwargs)
        except httpx.TransportError as exc:
            raise PublisherError(
                "Transport failed; delivery is uncertain. Replay this intent.", uncertain=True
            ) from exc
        if not response.is_success:
            status = response.status_code
            message = {
                401: "Session expired or credentials rejected. Log in again.",
                404: "Asset absent or unavailable to this owner.",
                409: "State or idempotency conflict.",
                410: "Previously accepted asset was deleted.",
                413: "File exceeds the 100 MiB limit.",
                415: "Unsupported media.",
                422: "Request validation failed.",
                503: "Service temporarily unavailable; no success confirmed.",
            }.get(status, f"HTTP request failed ({status}).")
            raise PublisherError(message, status=status, uncertain=status >= 500)
        try:
            data = response.json()
            if not isinstance(data, dict):
                raise ValueError
            return data
        except ValueError as exc:
            raise PublisherError(
                "Invalid API response; delivery is uncertain.", uncertain=True
            ) from exc

    def authenticate(self, command, email, password):
        data = self.request("POST", f"auth/{command}", json={"email": email, "password": password})
        return {key: data[key] for key in ("id", "email", "role")}

    def identity(self):
        return self.request("GET", "auth/me")["id"]

    def upload(self, path, key):
        # Reopen on every replay so the multipart stream always starts at byte zero.
        import mimetypes

        with Path(path).open("rb") as stream:
            data = self.request(
                "POST",
                "upload",
                headers={"Idempotency-Key": key},
                files={
                    "file": (
                        Path(path).name,
                        stream,
                        mimetypes.guess_type(str(path))[0] or "application/octet-stream",
                    )
                },
            )
        return self.accepted(data)

    @staticmethod
    def accepted(data):
        try:
            return asset_id(data["job_id"])
        except (KeyError, ValueError, TypeError, AttributeError) as exc:
            raise PublisherError(
                "Invalid acceptance response; replay this intent.", uncertain=True
            ) from exc

    def retry(self, job_id, key):
        return self.accepted(
            self.request("POST", f"jobs/{asset_id(job_id)}/retry", headers={"Idempotency-Key": key})
        )

    def status(self, job_id):
        data = self.request("GET", f"jobs/{asset_id(job_id)}")
        if (
            data.get("id") != asset_id(job_id)
            or not isinstance(data.get("filename"), str)
            or data.get("status") not in {"queued", "processing", "done", "failed"}
        ):
            raise PublisherError("Invalid status response.")
        # Deliberate whitelist: arbitrary server diagnostics must not leak credentials.
        return {
            key: data[key]
            for key in ("id", "filename", "status", "submission_status", "output_url", "hls_url")
            if key in data
        }

    def poll(self, job_id, max_polls, interval, *, sleep=time.sleep):
        for attempt in range(max_polls):
            try:
                data = self.status(job_id)
            except PublisherError as exc:
                if exc.status != 503:
                    raise
                data = {"id": job_id, "status": "unavailable"}
            if data["status"] in {"done", "failed"}:
                return data
            if attempt + 1 < max_polls:
                sleep(interval)
        return {**data, "poll_exhausted": True}
