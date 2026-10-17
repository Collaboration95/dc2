"""Native ECS and Lambda MinIO providers; no metadata/profile/static fallback."""

import os
from datetime import UTC, datetime
from threading import Lock
from urllib.parse import urlsplit

from minio.credentials import Credentials, IamAwsProvider, Provider, StaticProvider
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


class LambdaProvider(Provider):
    """Read the runtime-provided temporary tuple afresh for every operation.

    Used only by the opt-in short-encode executor (V2, #93), whose invocation outlives the
    handlers that never touch MinIO. Lambda supplies execution-role credentials in the
    environment; reading only those prevents profile or metadata fallback, and not caching the
    tuple means a long encode never signs its final upload with a value it read minutes ago.
    """

    def retrieve(self):
        try:
            if not os.environ.get("AWS_LAMBDA_FUNCTION_NAME"):
                raise ValueError("not a Lambda runtime")
            access = os.environ["AWS_ACCESS_KEY_ID"]
            secret = os.environ["AWS_SECRET_ACCESS_KEY"]
            token = os.environ["AWS_SESSION_TOKEN"]
            if not all((access, secret, token)):
                raise ValueError("incomplete temporary credentials")
            raw_expiration = os.environ.get("AWS_CREDENTIAL_EXPIRATION")
            expiration = None
            if raw_expiration:
                expiration = datetime.fromisoformat(raw_expiration.replace("Z", "+00:00"))
                if expiration.tzinfo is None:
                    raise ValueError("invalid credential expiration")
                if (expiration - datetime.now(UTC)).total_seconds() < 40:
                    raise ValueError("credentials expire too soon")
            return Credentials(access, secret, token, expiration)
        except Exception:
            raise ValueError("Lambda storage credentials unavailable") from None


def credential_provider(settings):
    def reveal(value):
        return value.get_secret_value() if hasattr(value, "get_secret_value") else value

    access = reveal(settings.minio_access_key)
    secret = reveal(settings.minio_secret_key)
    mode = getattr(settings, "storage_credential_mode", "static")
    if mode not in {"static", "ecs", "lambda"}:
        raise ValueError("Invalid storage credential mode")
    if mode == "lambda":
        if access or secret:
            raise ValueError("Lambda storage rejects static credential overrides")
        return LambdaProvider()
    if mode == "ecs":
        if access or secret:
            raise ValueError("ECS storage rejects static credential overrides")
        return ContainerProvider()
    if bool(access) != bool(secret):
        raise ValueError("Static storage requires a complete credential pair")
    # Preserve existing test construction; entrypoint guards require static keys.
    return StaticProvider(access, secret) if access else None
