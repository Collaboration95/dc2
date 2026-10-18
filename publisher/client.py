"""Cookie-authenticated Media public API with explicit trust and bounded requests."""

import hashlib
import mimetypes
import os
import ssl
import tempfile
import time
from http.cookiejar import MozillaCookieJar
from pathlib import Path
from uuid import UUID

import httpx

# Every status Media's public schema can answer (media/schemas/public.py). "accepted" is what a
# V1 job shows until Processing has acknowledged its command; the first live bulk publish
# (r1018b) failed on it with "Invalid status response." although every upload had succeeded.
STATUSES = {"accepted", "queued", "processing", "done", "failed", "cancelled"}


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
        self.direct = httpx.Client(
            verify=trust,
            timeout=timeout,
            transport=transport,
            follow_redirects=False,
            trust_env=False,
        )
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
            self.direct.close()

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
        if response.status_code == 204:
            return {}
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
        path = Path(path)
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            while chunk := stream.read(1024 * 1024):
                digest.update(chunk)
        reservation = self.request(
            "POST",
            "uploads/reservations",
            json={
                "request_id": key,
                "filename": path.name,
                "size_bytes": path.stat().st_size,
                "sha256": digest.hexdigest(),
                "content_type": mimetypes.guess_type(str(path))[0] or "application/octet-stream",
            },
        )
        if reservation.get("upload"):
            grant = reservation["upload"]
            url = httpx.URL(grant["url"])
            if url.scheme != "https" or url.userinfo or url.fragment:
                raise PublisherError("Invalid storage upload URL.")
            with path.open("rb") as stream:
                try:
                    # Separate jar and explicit cookie removal even after a storage Set-Cookie.
                    request = self.direct.build_request(
                        "POST", url, data=grant["fields"], files={"file": (path.name, stream)}
                    )
                    request.headers.pop("cookie", None)
                    response = self.direct.send(request)
                except httpx.TransportError as exc:
                    raise PublisherError(
                        "Storage delivery uncertain; replay this intent.", uncertain=True
                    ) from exc
                if not response.is_success:
                    raise PublisherError(
                        "Storage upload failed; replay this intent.", uncertain=True
                    )
        return self.accepted(
            self.request(
                "POST",
                f"uploads/reservations/{asset_id(reservation['reservation_id'])}/finalize",
                json={"request_id": key},
            )
        )

    def edit(self, job_id, operations, key):
        return self.accepted(
            self.request(
                "POST",
                f"jobs/{asset_id(job_id)}/edit",
                headers={"Idempotency-Key": key},
                json={"operations": operations},
            )
        )

    def delete(self, job_id):
        self.request("DELETE", f"jobs/{asset_id(job_id)}")
        return asset_id(job_id)

    def legacy_upload(self, path, key):
        """Frozen pre-Gateway regression only; V1 callers use upload()."""
        with Path(path).open("rb") as stream:
            return self.accepted(
                self.request(
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
            )

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
            or data.get("status") not in STATUSES
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
            if data["status"] in {"done", "failed", "cancelled"}:
                return data
            if attempt + 1 < max_polls:
                sleep(interval)
        return {**data, "poll_exhausted": True}
