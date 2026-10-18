"""Versioned V1 identities and durable messages.

Only the Media authorizer emits actors. Queue policies establish producer authority;
validation alone does not authenticate a message. Consumers commit inbox/domain/outbox
before ACK and bind work to their persisted accepted source before S3 GET.

Versioning (see contracts/README.md): producers emit SCHEMA_VERSION; consumers accept it and
the one before it, and ignore fields they do not know, so either service can be released
first when a change is additive.
"""

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from typing import Any
from uuid import UUID

# N: the newest version this copy of the contract can read. Consumers accept N and N-1.
SCHEMA_VERSION = 1
# The version producers stamp on what they send. It may trail SCHEMA_VERSION by one: raise
# SCHEMA_VERSION first and release every service, and only in a later release raise this, so
# no producer emits a version a deployed consumer would refuse (contracts/README.md).
EMIT_VERSION = 1
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


def accepted_versions() -> frozenset[int]:
    """Versions a consumer reads: the one it emits and its predecessor, never a newer one."""
    return frozenset(v for v in (SCHEMA_VERSION, SCHEMA_VERSION - 1) if v >= 1)


def accepts_version(value: Any) -> bool:
    # bool is an int subclass in Python, but the wire says integer.
    return type(value) is int and value in accepted_versions()


def _known(value: dict, fields) -> dict:
    """The fields this version defines. A newer producer may add more; they are not ours to read.

    Dropping them (rather than carrying them) keeps the replay fingerprint stable across
    producer versions and keeps unreviewed data out of the inbox and the domain.
    """
    return {name: value[name] for name in fields}


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
            not accepts_version(context.get("schema_version"))
            or context.get("integration") != INTEGRATION_MARKER
            # "viewer" is accepted so a read-only role can be added without a contract bump, but
            # Media never issues it in V1 (media/authorizer.py:gateway_role).
            or context.get("role") not in ("publisher", "viewer")
        ):
            raise ContractError("Invalid trusted actor")
        return cls(uuid_text(context.get("owner_id")), context["role"])

    def to_context(self) -> dict:
        context = {
            "schema_version": EMIT_VERSION,
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
        if not isinstance(value, dict) or not set(cls.__dataclass_fields__) <= set(value):
            raise ContractError("Invalid immutable source")
        value = _known(value, cls.__dataclass_fields__)
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
        if not isinstance(value, dict) or not set(cls.__dataclass_fields__) <= set(value):
            raise ContractError("Invalid message fields")
        value = _known(value, cls.__dataclass_fields__)
        if (
            not accepts_version(value["schema_version"])
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
            # A committed cancel-before-submit guard has no Job or Attempt. Its
            # acknowledgement must describe only that durable tombstone, never
            # invent job identifiers or masquerade as a normal job result.
            payload = data["payload"]
            if (
                data["kind"] != "result"
                or data["job_id"] is not None
                or data["attempt_id"] is not None
                or data["source"] is not None
                or set(payload) != {"status", "cancellation_confirmed", "command_message_id"}
                or payload["status"] != "cancelled"
                or payload["cancellation_confirmed"] is not True
            ):
                raise ContractError("Job and attempt required outside cancellation acknowledgement")
            data["payload"] = {
                **payload,
                "command_message_id": uuid_text(payload["command_message_id"]),
            }
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
