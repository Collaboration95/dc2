"""Private edge preparation and verified wake prerequisites; never applies AWS changes."""

import copy
import hashlib
import json
import re

from scripts.aws.transport import OperationError, config_value

ORIGIN_ID = "state"
HEADER_NAME = "X-DC2-Origin-Gate"


def gate_digest(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{48,128}", value):
        raise OperationError("A private bounded origin gate is required")
    return hashlib.sha256(value.encode()).hexdigest()


def prepare_activation(config, current, *, private_gate, nginx_gate_sha256, public_dns):
    """Return private payload plus a selected receipt; caller must keep payload private."""
    if config_value(config, "origin_transport_accepted") is not True:
        raise OperationError("Origin interpretation remains gated")
    fingerprint = gate_digest(private_gate)
    if fingerprint != nginx_gate_sha256:
        raise OperationError("Origin gate does not match prepared nginx")
    if not re.fullmatch(r"[A-Za-z0-9.-]{1,253}", public_dns) or not current.get("ETag"):
        raise OperationError("Current public DNS and optimistic concurrency are required")
    settings = copy.deepcopy(current["DistributionConfig"])
    origins = [o for o in settings["Origins"]["Items"] if o["Id"] == ORIGIN_ID]
    if len(origins) != 1:
        raise OperationError("Prepared origin identity differs from the distribution")
    origin = origins[0]
    if origin.get("CustomOriginConfig", {}).get("OriginProtocolPolicy") != "http-only":
        raise OperationError("Origin protocol requires a separately reviewed definition")
    origin["DomainName"] = public_dns
    origin["CustomHeaders"] = {
        "Quantity": 1,
        "Items": [{"HeaderName": HEADER_NAME, "HeaderValue": private_gate}],
    }
    settings["Enabled"] = True
    payload = {
        "Id": config_value(config, "cloudfront_distribution_id"),
        "IfMatch": current["ETag"],
        "DistributionConfig": settings,
    }
    receipt = {
        "status": "PREPARED",
        "applied": False,
        "environment_id": config_value(config, "environment_id"),
        "distribution_id": payload["Id"],
        "origin_id": ORIGIN_ID,
        "gate_sha256": fingerprint,
        "config_sha256": hashlib.sha256(json.dumps(settings, sort_keys=True).encode()).hexdigest(),
    }
    return payload, receipt


def validate_activation(config, current):
    """Validate observed distribution against a separately observed nginx gate receipt."""
    receipt = config_value(config, "edge_activation", {})
    if (
        receipt.get("status") != "VERIFIED"
        or receipt.get("environment_id") != config_value(config, "environment_id")
        or receipt.get("distribution_id") != config_value(config, "cloudfront_distribution_id")
        or receipt.get("origin_id") != ORIGIN_ID
        or receipt.get("nginx_gate_observed") is not True
        or not current.get("ETag")
    ):
        raise OperationError("A matched observed private edge activation is required")
    settings = current.get("DistributionConfig", {})
    if settings.get("Enabled") is not True:
        raise OperationError("Disabled edge cannot be treated as an activated wake")
    origins = [o for o in settings.get("Origins", {}).get("Items", []) if o.get("Id") == ORIGIN_ID]
    if len(origins) != 1:
        raise OperationError("Known prepared origin identity required")
    headers = origins[0].get("CustomHeaders", {})
    items = headers.get("Items", [])
    if headers.get("Quantity") != 1 or len(items) != 1 or items[0].get("HeaderName") != HEADER_NAME:
        raise OperationError("Expected private origin gate header is absent")
    if gate_digest(items[0].get("HeaderValue")) != receipt.get("gate_sha256"):
        raise OperationError("Observed edge and nginx gates do not match")
    return origins[0]
