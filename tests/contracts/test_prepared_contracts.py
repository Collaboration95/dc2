"""CT-23: prepared schema integrity and validators used by live acceptance."""

from uuid import uuid4

import pytest
from jsonschema import ValidationError

from scripts.dev.contracts import check_document, validate_request, validate_response


@pytest.mark.parametrize("name", ["public", "processing", "media-internal"])
def test_prepared_contract_references_and_json_schemas_resolve(name):
    check_document(name)


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
