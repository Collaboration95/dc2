"""Validate actual HTTP payloads against the prepared OpenAPI 3.1 contracts."""

import json
from functools import lru_cache

from jsonschema import Draft202012Validator, FormatChecker

from scripts.dev.common import ROOT


@lru_cache
def document(name: str) -> dict:
    if name not in {"public", "processing", "media-internal"}:
        raise ValueError("Unknown service contract")
    return json.loads(
        (ROOT / f"project-roadmap/design/05-contracts/{name}.openapi.json").read_text()
    )


def validate_schema(name: str, schema: dict, value) -> None:
    # Keep the document's component namespace for local $refs, while evaluating
    # just the selected request/response schema. Network resolution is unnecessary.
    root = {"components": document(name)["components"], **schema}
    Draft202012Validator(root, format_checker=FormatChecker()).validate(value)


def validate_response(name: str, route: str, method: str, status: int, body) -> None:
    operation = document(name)["paths"][route][method.lower()]
    response = operation["responses"].get(str(status))
    if response is None:
        raise ValueError(f"Undocumented {name} {method} {route} response: {status}")
    schema = response.get("content", {}).get("application/json", {}).get("schema")
    if schema is not None:
        validate_schema(name, schema, body)
    elif body not in (None, "", b""):
        raise ValueError(f"{name} {method} {route} {status} requires an empty body")


def validate_request(name: str, route: str, method: str, body) -> None:
    schema = document(name)["paths"][route][method.lower()]["requestBody"]["content"][
        "application/json"
    ]["schema"]
    validate_schema(name, schema, body)


def check_examples(examples: dict | None = None) -> None:
    """Validate every prepared payload at its owning request/response boundary."""
    if examples is None:
        examples = json.loads(
            (ROOT / "project-roadmap/design/05-contracts/examples.json").read_text()
        )
    # The prepared documents share component names. Select the owning operation,
    # so an example cannot silently validate against another service's schema.
    boundaries = {
        "submitJob": ("processing", "/jobs", "post", None),
        "acceptedUpload": ("public", "/upload", "post", 202),
        "pendingPublicAsset": ("public", "/jobs/{job_id}", "get", 200),
        "processingJob": ("processing", "/jobs/{job_id}", "get", 200),
        "retryRequest": ("processing", "/jobs/{job_id}/retry", "post", None),
        "sourceAccessRequest": ("media-internal", "/assets/{asset_id}/source-access", "post", None),
        "ownerMismatch": ("processing", "/jobs/{job_id}", "get", 404),
        "payloadConflict": ("processing", "/jobs", "post", 409),
    }
    # Only note is metadata. Add a deliberate mapping when a new example appears.
    if set(examples) != set(boundaries) | {"note"}:
        raise ValueError("Prepared example names differ from the contract mappings")
    if not isinstance(examples["note"], str):
        raise ValueError("Prepared example note must be text")
    for key, (name, route, method, status) in boundaries.items():
        if status is None:
            validate_request(name, route, method, examples[key])
        else:
            validate_response(name, route, method, status, examples[key])


def check_document(name: str) -> None:
    data = document(name)
    if data["openapi"] != "3.1.0":
        raise ValueError("Contract validator expects OpenAPI 3.1")

    def walk(value):
        if isinstance(value, dict):
            if "$ref" in value:
                reference = value["$ref"]
                if not reference.startswith("#/"):
                    raise ValueError(f"Unexpected external contract reference: {reference}")
                resolved = data
                for component in reference[2:].split("/"):
                    resolved = resolved[component.replace("~1", "/").replace("~0", "~")]
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)

    walk(data)
    for schema in data["components"]["schemas"].values():
        Draft202012Validator.check_schema(schema)
