"""CT-23: prepared schema integrity and validators used by live acceptance."""

import json
from uuid import uuid4

import pytest
from jsonschema import ValidationError

from scripts.dev.common import ROOT
from scripts.dev.contracts import (
    check_document,
    check_examples,
    validate_request,
    validate_response,
)


@pytest.mark.parametrize("name", ["public", "processing", "media-internal"])
def test_prepared_contract_references_and_json_schemas_resolve(name):
    check_document(name)


def test_every_prepared_example_matches_its_owning_contract():
    check_examples()


@pytest.mark.parametrize(
    ("name", "field", "broken"),
    [
        ("submitJob", "asset_id", "not-a-uuid"),
        ("acceptedUpload", "job_id", "not-a-uuid"),
        ("pendingPublicAsset", "status", "succeeded"),
        ("processingJob", "current_attempt", {}),
        ("retryRequest", "retry_request_id", "not-a-uuid"),
        ("sourceAccessRequest", "revision", 0),
        ("ownerMismatch", "error", 404),
        ("payloadConflict", "error", 409),
    ],
)
def test_broken_prepared_example_fails_schema_validation(name, field, broken):
    examples = json.loads((ROOT / "project-roadmap/design/05-contracts/examples.json").read_text())
    examples[name][field] = broken
    with pytest.raises(ValidationError):
        check_examples(examples)


def test_unmapped_prepared_example_cannot_be_skipped():
    examples = json.loads((ROOT / "project-roadmap/design/05-contracts/examples.json").read_text())
    examples["unmappedRequest"] = {"invalid": True}
    with pytest.raises(ValueError, match="contract mappings"):
        check_examples(examples)


def test_public_validation_accepts_actual_shape_and_rejects_internal_id_shape():
    validate_response("public", "/upload", "post", 202, {"job_id": str(uuid4())})
    with pytest.raises(ValidationError):
        validate_response("public", "/upload", "post", 202, {"asset_id": str(uuid4())})
    with pytest.raises(ValidationError):
        validate_response("public", "/upload", "post", 202, {"job_id": "not-a-uuid"})


def test_status_and_empty_response_validation_cannot_hide_contract_drift():
    with pytest.raises(ValueError, match="Undocumented"):
        validate_response("public", "/upload", "post", 200, {})
    validate_response("public", "/jobs/{job_id}", "delete", 204, None)
    with pytest.raises(ValueError, match="empty body"):
        validate_response("public", "/jobs/{job_id}", "delete", 204, {"ok": True})


def test_reverse_source_request_rejects_extra_storage_authority():
    validate_request("media-internal", "/assets/{asset_id}/source-access", "post", {"revision": 1})
    with pytest.raises(ValidationError):
        validate_request(
            "media-internal",
            "/assets/{asset_id}/source-access",
            "post",
            {"revision": 1, "bucket": "other-owner"},
        )
