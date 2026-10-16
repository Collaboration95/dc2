"""Shared canonical message validation and deterministic SQL dedupe hashes."""

import hashlib
import json

from contracts.v1 import Envelope


def document(value):
    if hasattr(value, "to_dict"):
        value = value.to_dict()
    elif hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    return Envelope.from_dict(value).to_dict()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def fingerprint(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()
