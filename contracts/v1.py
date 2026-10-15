"""Versioned V1 identities and durable messages.

Only the Media authorizer emits actors. Queue policies establish producer authority;
validation alone does not authenticate a message. Consumers commit inbox/domain/outbox
before ACK and bind work to their persisted accepted source before S3 GET.
"""

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from typing import Any
from uuid import UUID

SCHEMA_VERSION = 1
INTEGRATION_MARKER = "dc2-gateway-v1"
MAX_UPLOAD_BYTES = 100 * 1024 * 1024
COOKIE_OPTIONS = {"path": "/", "secure": True, "httponly": True, "samesite": "strict"}
PRODUCERS = {
    "submit": "media",
    "retry": "media",
    "cancel": "media",
    "work": "processing-dispatch",
    "result": "processing-completion",
}


class ContractError(ValueError):
    """Invalid wire data. Messages intentionally do not include input values."""


def uuid_text(value: Any) -> str:
    if not isinstance(value, str):
        raise ContractError("Invalid UUID")
    try:
        return str(UUID(value))
    except ValueError as exc:
        raise ContractError("Invalid UUID") from exc


@dataclass(frozen=True)
class Actor:
    owner_id: str
    role: str

    @classmethod
    def from_context(cls, context: Any) -> "Actor":
        if not isinstance(context, dict):
            raise ContractError("Missing trusted actor")
        if (
            type(context.get("schema_version")) is not int
            or context["schema_version"] != SCHEMA_VERSION
            or context.get("integration") != INTEGRATION_MARKER
            or context.get("role") not in ("publisher", "viewer")
        ):
            raise ContractError("Invalid trusted actor")
        return cls(uuid_text(context.get("owner_id")), context["role"])

    def to_context(self) -> dict:
        context = {
            "schema_version": SCHEMA_VERSION,
            "integration": INTEGRATION_MARKER,
            "owner_id": self.owner_id,
            "role": self.role,
        }
        self.from_context(context)
        return context


@dataclass(frozen=True)
class Source:
    bucket: str
    key: str
    version_id: str
    sha256: str
    size_bytes: int
    content_type: str

    @classmethod
    def from_dict(cls, value: Any) -> "Source":
        if not isinstance(value, dict) or set(value) != set(cls.__dataclass_fields__):
            raise ContractError("Invalid immutable source")
        for key in ("bucket", "key", "version_id", "content_type"):
            if (
                not isinstance(value[key], str)
                or not value[key]
                or any(ord(c) < 32 for c in value[key])
            ):
                raise ContractError("Invalid immutable source")
        if (
            "://" in value["bucket"]
            or "://" in value["key"]
            or value["version_id"] == "null"
            or not re.fullmatch(r"[a-f0-9]{64}", str(value["sha256"]))
            or type(value["size_bytes"]) is not int
            or not 0 < value["size_bytes"] <= MAX_UPLOAD_BYTES
        ):
            raise ContractError("Invalid immutable source")
        return cls(**value)


def _safe_payload(value: Any) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if not isinstance(key, str) or any(
                word in key.lower()
                for word in (
                    "secret",
                    "credential",
                    "password",
                    "token",
                    "signed_url",
                    "source_url",
                    "media_bytes",
                    "authorization",
                )
            ):
                raise ContractError("Forbidden message payload")
            _safe_payload(child)
    elif isinstance(value, list):
        for child in value:
            _safe_payload(child)
    elif isinstance(value, str) and ("https://" in value.lower() or "http://" in value.lower()):
        raise ContractError("URLs are forbidden in messages")


@dataclass(frozen=True)
class Envelope:
    schema_version: int
    message_id: str
    kind: str
    owner_id: str
    asset_id: str
    job_id: str | None
    attempt_id: str | None
    state_version: int
    source: Source | None
    payload: dict

    @classmethod
    def from_dict(cls, value: Any) -> "Envelope":
        if not isinstance(value, dict) or set(value) != set(cls.__dataclass_fields__):
            raise ContractError("Invalid message fields")
        if (
            type(value["schema_version"]) is not int
            or value["schema_version"] != 1
            or value["kind"] not in PRODUCERS
            or type(value["state_version"]) is not int
            or value["state_version"] < 0
            or not isinstance(value["payload"], dict)
        ):
            raise ContractError("Invalid message version or kind")
        data = dict(value)
        for key in ("message_id", "owner_id", "asset_id"):
            data[key] = uuid_text(data[key])
        for key in ("job_id", "attempt_id"):
            if data[key] is not None:
                data[key] = uuid_text(data[key])
        data["source"] = Source.from_dict(data["source"]) if data["source"] is not None else None
        if data["kind"] in ("submit", "work") and data["source"] is None:
            raise ContractError("Source required")
        if data["kind"] in ("work", "result") and (
            data["job_id"] is None or data["attempt_id"] is None
        ):
            raise ContractError("Job and attempt required")
        _safe_payload(data["payload"])
        try:
            json.dumps(data["payload"], allow_nan=False)
        except (TypeError, ValueError) as exc:
            raise ContractError("Invalid JSON payload") from exc
        return cls(**data)

    def to_dict(self) -> dict:
        return asdict(self)

    def fingerprint(self) -> str:
        encoded = json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"), allow_nan=False)
        return hashlib.sha256(encoded.encode()).hexdigest()

    def assert_bound(
        self,
        *,
        owner_id: str,
        asset_id: str,
        source: Source,
        job_id: str | None = None,
        attempt_id: str | None = None,
    ) -> None:
        if (
            self.owner_id != str(owner_id)
            or self.asset_id != str(asset_id)
            or self.source != source
            or (job_id is not None and self.job_id != str(job_id))
            or (attempt_id is not None and self.attempt_id != str(attempt_id))
        ):
            raise ContractError("Message does not match accepted state")
