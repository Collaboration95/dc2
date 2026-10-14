"""Explicit, nonsecret preparation inputs. This module never discovers credentials."""

import ipaddress
import json
import re
from copy import deepcopy
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit

# The original Singapore calendar checkpoint, not a clock restarted on account receipt.
WINDOW_START = datetime(2026, 10, 14, 16, tzinfo=UTC)
WINDOW_END = datetime(2026, 10, 28, 16, tzinfo=UTC)
REQUIRED = {
    "mode",
    "region",
    "account_id",
    "environment_id",
    "public_url",
    "source_bucket",
    "output_bucket",
    "operator_station",
}
SECRET_KEYS = {
    "password",
    "secret",
    "access_key",
    "secret_key",
    "session_token",
    "cookie",
    "authorization",
    "dsn",
    "origin_header_value",
    "aws_profile",
    "profile",
    "token",
    "aws_access_key_id",
    "aws_secret_access_key",
    "aws_session_token",
}
SECRET_TEXT = re.compile(
    r"(?i)(?:postgres(?:ql)?(?:\+asyncpg)?://|redis://|rediss://|"
    r"x-amz-(?:signature|credential|security-token)|AWSAccessKeyId=|"
    r"(?:AKIA|ASIA)[A-Z0-9]{16}|bearer\s+|-----BEGIN .*PRIVATE KEY)"
)


def validate_nonsecret(value, *, references=False):
    """Reject sensitive inputs without echoing their values or key paths."""
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError("Configuration keys must be strings")
            normalized = key.lower()
            if not references and (
                normalized in SECRET_KEYS
                or normalized.endswith(
                    (
                        "_password",
                        "_secret",
                        "_dsn",
                        "_cookie",
                        "_token",
                        "_access_key",
                        "_secret_key",
                    )
                )
            ):
                raise ValueError("Configuration contains a forbidden private field")
            validate_nonsecret(item, references=references or key == "parameter_arns")
    elif isinstance(value, list):
        for item in value:
            validate_nonsecret(item, references=references)
    elif isinstance(value, str):
        if SECRET_TEXT.search(value):
            raise ValueError("Configuration contains private material")
        parsed = urlsplit(value) if "://" in value else None
        if parsed and (parsed.username or parsed.password or parsed.query or parsed.fragment):
            raise ValueError("Configuration URLs must contain no credentials or capabilities")
    elif value is not None and not isinstance(value, (int, float, bool)):
        raise ValueError("Configuration must contain plain JSON values")


def loopback_endpoint(value):
    parsed = urlsplit(value)
    try:
        loopback = (
            parsed.hostname == "localhost"
            or ipaddress.ip_address(parsed.hostname or "").is_loopback
        )
        port = parsed.port
    except ValueError:
        loopback, port = False, None
    if (
        not loopback
        or not port
        or parsed.scheme != "http"
        or parsed.path not in ("", "/")
        or parsed.query
        or parsed.fragment
        or parsed.username
        or parsed.password
    ):
        raise ValueError("Emulator endpoint must be an explicit HTTP loopback port")


@dataclass
class CloudConfig:
    mode: str = "plan"
    region: str = ""
    account_id: str = ""
    environment_id: str = ""
    public_url: str = ""
    source_bucket: str = ""
    output_bucket: str = ""
    operator_station: str = ""
    endpoint_url: str = ""
    cluster: str = ""
    services: dict = field(default_factory=dict)
    task_definitions: dict = field(default_factory=dict)
    network: dict = field(default_factory=dict)
    state_instance_id: str = ""
    cloudfront_distribution_id: str = ""
    image_digests: dict = field(default_factory=dict)
    parameter_arns: dict = field(default_factory=dict)
    session_end_utc: str = ""
    max_worker_tasks: int = 3
    worker_lifetime_seconds: int = 1800
    origin_transport_accepted: bool = False
    approval: dict = field(default_factory=dict)

    def __post_init__(self):
        validate_nonsecret(asdict(self))
        if self.mode not in ("plan", "emulator"):
            raise ValueError("Only preparation plan or explicit emulator mode is supported")
        if self.account_id and not re.fullmatch(r"\d{12}", self.account_id):
            raise ValueError("Account ID must be empty or twelve digits")
        if self.region and not re.fullmatch(r"[a-z]{2}-[a-z]+-\d", self.region):
            raise ValueError("Invalid region")
        if self.environment_id and not re.fullmatch(r"[a-z][a-z0-9-]{1,31}", self.environment_id):
            raise ValueError("Invalid environment ID")
        if type(self.max_worker_tasks) is not int or not 0 <= self.max_worker_tasks <= 3:
            raise ValueError("Maximum workers must be an integer from zero through three")
        if (
            type(self.worker_lifetime_seconds) is not int
            or not 60 <= self.worker_lifetime_seconds <= 14400
        ):
            raise ValueError("Worker lifetime must be finite, from 60 to 14400 seconds")
        if type(self.origin_transport_accepted) is not bool:
            raise ValueError("Origin transport disposition must be explicit boolean")
        for name in (self.source_bucket, self.output_bucket):
            if name and (
                not re.fullmatch(r"[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]", name)
                or ".." in name
                or re.fullmatch(r"[\d.]+", name)
            ):
                raise ValueError("Invalid bucket name")
        if self.source_bucket and self.source_bucket == self.output_bucket:
            raise ValueError("Source and output buckets must differ")
        if self.public_url:
            public = urlsplit(self.public_url)
            if (
                public.scheme != "https"
                or not public.hostname
                or public.port not in (None, 443)
                or public.path not in ("", "/")
            ):
                raise ValueError("Public URL must be an HTTPS origin")
            if self.mode == "plan" and not re.fullmatch(
                r"[a-z0-9]+\.cloudfront\.net", public.hostname
            ):
                raise ValueError("Planned public origin must use the generated CloudFront name")
        for name in (
            "services",
            "task_definitions",
            "network",
            "image_digests",
            "parameter_arns",
            "approval",
        ):
            if not isinstance(getattr(self, name), dict):
                raise ValueError("Resource mappings must be objects")
        for arn in self.parameter_arns.values():
            if not isinstance(arn, str) or not re.fullmatch(
                r"arn:aws:ssm:[a-z]{2}-[a-z]+-\d:\d{12}:parameter/[A-Za-z0-9_/.-]+", arn
            ):
                raise ValueError("Parameters must be exact SSM ARN references")
            parts = arn.split(":")
            if (
                self.region
                and parts[3] != self.region
                or self.account_id
                and parts[4] != self.account_id
            ):
                raise ValueError("Parameter reference belongs to another account or region")
        for digest in self.image_digests.values():
            if not isinstance(digest, str) or not re.fullmatch(r"sha256:[a-f0-9]{64}", digest):
                raise ValueError("Image identities must be immutable SHA256 digests")
        if self.network.get("assign_public_ip", "ENABLED") not in ("ENABLED", "DISABLED"):
            raise ValueError("Invalid public IP setting")
        if self.session_end_utc:
            try:
                end = datetime.fromisoformat(self.session_end_utc.replace("Z", "+00:00"))
            except ValueError:
                raise ValueError("Session deadline must be an ISO8601 timestamp") from None
            if end.tzinfo is None or not WINDOW_START < end <= WINDOW_END:
                raise ValueError("Session deadline must fit the anchored fourteen-day window")
        if self.endpoint_url:
            loopback_endpoint(self.endpoint_url)
        if self.mode == "emulator":
            if self.account_id != "000000000000" or not self.endpoint_url:
                raise ValueError("Emulator requires dummy account and loopback endpoint")

    @classmethod
    def from_dict(cls, value):
        if not isinstance(value, dict) or not REQUIRED <= value.keys():
            raise ValueError("Configuration is missing required explicit fields")
        unknown = value.keys() - cls.__dataclass_fields__.keys()
        if unknown:
            raise ValueError("Configuration contains unsupported fields")
        return cls(**deepcopy(value))

    def to_dict(self):
        return deepcopy(asdict(self))

    def require_real_action(self, *_args, **_kwargs):
        raise PermissionError("Real AWS operations are excluded from preparation")


def load_config(path):
    return CloudConfig.from_dict(json.loads(Path(path).read_text()))
