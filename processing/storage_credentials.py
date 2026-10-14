"""ECS-only native MinIO provider; no metadata/profile/static fallback."""

import os
from datetime import UTC, datetime
from threading import Lock
from urllib.parse import urlsplit

from minio.credentials import IamAwsProvider, Provider, StaticProvider
from urllib3 import PoolManager, Timeout


def validate_container_environment():
    relative = os.environ.get("AWS_CONTAINER_CREDENTIALS_RELATIVE_URI")
    full = os.environ.get("AWS_CONTAINER_CREDENTIALS_FULL_URI")
    if bool(relative) == bool(full) or os.environ.get("AWS_WEB_IDENTITY_TOKEN_FILE"):
        raise ValueError("ECS storage requires exactly one container credential endpoint")
    if relative and (
        not relative.startswith("/")
        or relative.startswith("//")
        or "?" in relative
        or "#" in relative
    ):
        raise ValueError("Invalid container credential endpoint")
    if full:
        parts = urlsplit(full)
        if (
            parts.scheme != "http"
            or parts.hostname not in {"127.0.0.1", "localhost", "::1"}
            or parts.username
            or parts.password
            or parts.query
            or parts.fragment
        ):
            raise ValueError("Invalid container credential endpoint")


class ContainerProvider(Provider):
    def __init__(self, *, factory=None, clock=None):
        validate_container_environment()
        self._lock = Lock()
        self._clock = clock or (lambda: datetime.now(UTC))
        self._factory = factory or (
            lambda: IamAwsProvider(
                http_client=PoolManager(timeout=Timeout(connect=1, read=2), retries=False)
            )
        )
        self._native = self._factory()

    def retrieve(self):
        # Serialize native cache refresh: credentials/token are one immutable value.
        with self._lock:
            try:
                credential = self._native.retrieve()
                if not credential.session_token or not credential.expiration:
                    raise ValueError("Incomplete task credentials")
                remaining = credential.expiration.replace(tzinfo=UTC) - self._clock()
                if remaining.total_seconds() < 40:
                    # Public API only: a fresh native provider forces one bounded fetch.
                    validate_container_environment()
                    self._native = self._factory()
                    credential = self._native.retrieve()
                    if (
                        not credential.session_token
                        or not credential.expiration
                        or (
                            credential.expiration.replace(tzinfo=UTC) - self._clock()
                        ).total_seconds()
                        < 40
                    ):
                        raise ValueError("Task credentials expire too soon")
                return credential
            except Exception:
                raise ValueError("Task storage credentials unavailable") from None


def credential_provider(settings):
    def reveal(value):
        return value.get_secret_value() if hasattr(value, "get_secret_value") else value

    access = reveal(settings.minio_access_key)
    secret = reveal(settings.minio_secret_key)
    mode = getattr(settings, "storage_credential_mode", "static")
    if mode not in {"static", "ecs"}:
        raise ValueError("Invalid storage credential mode")
    if mode == "ecs":
        if access or secret:
            raise ValueError("ECS storage rejects static credential overrides")
        return ContainerProvider()
    if bool(access) != bool(secret):
        raise ValueError("Static storage requires a complete credential pair")
    # Preserve existing test construction; entrypoint guards require static keys.
    return StaticProvider(access, secret) if access else None
