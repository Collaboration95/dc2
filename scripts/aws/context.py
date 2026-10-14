"""Explicit API trust and a separate bounded regional S3 capability transport."""

import time
from dataclasses import dataclass
from urllib.parse import urlsplit

import httpx


class ContextError(ValueError):
    """Messages are fixed strings; response bodies and capabilities stay private."""


def _parts(url):
    try:
        parts = urlsplit(url)
        _ = parts.port
        return parts
    except (ValueError, TypeError):
        raise ContextError("Invalid HTTP URL") from None


@dataclass(frozen=True)
class Context:
    public_url: str
    region: str
    buckets: tuple[str, ...]
    mode: str = "aws"
    timeout_seconds: float = 10
    max_response_bytes: int = 2 * 1024 * 1024
    capability_limit_bytes: int = 100 * 1024 * 1024

    def __post_init__(self):
        p = _parts(self.public_url)
        if (
            p.username
            or p.password
            or p.query
            or p.fragment
            or p.path not in {"", "/"}
            or not p.hostname
            or self.mode not in {"aws", "local-fixture"}
        ):
            raise ContextError("Invalid API context")
        if self.mode == "aws":
            if (
                p.scheme != "https"
                or not p.hostname.endswith(".cloudfront.net")
                or p.port not in {None, 443}
            ):
                raise ContextError("Production context requires generated CloudFront HTTPS")
        elif p.hostname not in {"localhost", "127.0.0.1", "::1"} or p.scheme != "https":
            raise ContextError("Local fixtures require explicit loopback HTTPS")
        import re

        if (
            not re.fullmatch(r"[a-z]{2}-[a-z]+-\d", self.region)
            or not self.buckets
            or any(not re.fullmatch(r"[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]", b) for b in self.buckets)
        ):
            raise ContextError("Invalid regional bucket context")
        if not (
            0 < self.timeout_seconds <= 30
            and 0 < self.max_response_bytes <= 4 * 1024**2
            and 0 < self.capability_limit_bytes <= 100 * 1024**2
        ):
            raise ContextError("Invalid HTTP bounds")

    def capability_allowed(self, url):
        p = _parts(url)
        return (
            p.scheme == "https"
            and not p.username
            and not p.password
            and not p.fragment
            and p.port in {None, 443}
            and p.hostname in {f"{b}.s3.{self.region}.amazonaws.com" for b in self.buckets}
        )


class Client:
    def __init__(self, context, *, api_transport=None, object_transport=None, ca_file=None):
        if ca_file and context.mode != "local-fixture":
            raise ContextError("Production API uses normal system trust")
        self.context = context
        import ssl

        verify = ssl.create_default_context(cafile=ca_file) if ca_file else True
        self.api = httpx.Client(
            base_url=context.public_url,
            verify=verify,
            follow_redirects=False,
            trust_env=False,
            timeout=context.timeout_seconds,
            transport=api_transport,
        )
        # A separate jar and no API auth/default headers, even when redirects return S3 URLs.
        self.objects = httpx.Client(
            verify=True,
            follow_redirects=False,
            trust_env=False,
            timeout=context.timeout_seconds,
            transport=object_transport,
        )

    def close(self):
        self.api.close()
        self.objects.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def _read(self, client, method, url, limit, **kwargs):
        start = time.monotonic()
        try:
            with client.stream(method, url, **kwargs) as reply:
                body = bytearray()
                for chunk in reply.iter_bytes():
                    if len(body) + len(chunk) > limit:
                        raise ContextError("HTTP body limit exceeded")
                    if time.monotonic() - start > self.context.timeout_seconds:
                        raise ContextError("HTTP deadline exceeded")
                    body.extend(chunk)
                if time.monotonic() - start > self.context.timeout_seconds:
                    raise ContextError("HTTP deadline exceeded")
                return reply.status_code, bytes(body), dict(reply.headers)
        except httpx.HTTPError:
            raise ContextError("HTTP transport failed") from None

    def request(self, method, path, **kwargs):
        if (
            not path.startswith("/")
            or path.startswith("//")
            or "\\" in path
            or urlsplit(path).netloc
            or "follow_redirects" in kwargs
        ):
            raise ContextError("API path must stay on configured origin")
        return self._read(self.api, method, path, self.context.max_response_bytes, **kwargs)

    def download(self, capability, *, byte_range=None):
        if not self.context.capability_allowed(capability):
            raise ContextError("Capability host is not an approved regional bucket")
        headers = {}
        if byte_range is not None:
            start, end = byte_range
            if not (0 <= start <= end and end - start + 1 <= self.context.capability_limit_bytes):
                raise ContextError("Invalid byte range")
            headers["Range"] = f"bytes={start}-{end}"
        # Never reuse Set-Cookie from object hosts; no headers/cookies/tokens from API.
        self.objects.cookies.clear()
        result = self._read(
            self.objects, "GET", capability, self.context.capability_limit_bytes, headers=headers
        )
        self.objects.cookies.clear()
        if result[0] in {301, 302, 303, 307, 308}:
            raise ContextError("Object redirect rejected")
        return result
