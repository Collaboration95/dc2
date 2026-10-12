import copy
import json
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import ValidationError

from processing.schemas import SubmitJob
from processing.service import request_fingerprint

CONTRACT = json.loads(
    (
        Path(__file__).resolve().parents[2]
        / "project-roadmap/design/05-contracts/processing.openapi.json"
    ).read_text()
)


def test_submission_fields_track_prepared_contract(submission):
    schema = CONTRACT["components"]["schemas"]["SubmitJob"]
    assert set(SubmitJob.model_fields) == set(schema["properties"])
    assert {name for name, field in SubmitJob.model_fields.items() if field.is_required()} == set(
        schema["required"]
    )
    assert SubmitJob.model_validate(submission).operations == []


@pytest.mark.parametrize(
    "operation",
    [
        {"operation": "clip", "params": {"start": 0, "end": 10}},
        {"operation": "crop", "params": {"x": 0, "y": 2, "w": 640, "h": 360}},
        {"operation": "downscale", "params": {"height": 360}},
        {"operation": "upscale", "params": {"height": 1080}},
        {"operation": "convert", "params": {"format": "mp3"}},
        {"operation": "convert", "params": {"format": "mkv"}},
    ],
)
def test_accepts_contract_operation_shape(submission, operation):
    submission["operations"] = [operation]
    result = SubmitJob.model_validate(submission)
    assert result.operations[0].model_dump() == operation


@pytest.mark.parametrize(
    "operations",
    [
        [],
        None,
        [{"operation": "clip", "params": {"start": 10, "end": 10}}],
        [{"operation": "clip", "params": {"start": -1, "end": 10}}],
        [{"operation": "clip", "params": {"start": "0", "end": 10}}],
        [{"operation": "clip", "params": {"start": False, "end": 10}}],
        [{"operation": "clip", "params": {"start": 0, "end": float("inf")}}],
        [{"operation": "crop", "params": {"x": 0, "y": 0, "w": 0, "h": 10}}],
        [{"operation": "crop", "params": {"x": 0.5, "y": 0, "w": 10, "h": 10}}],
        [{"operation": "downscale", "params": {"height": True}}],
        [{"operation": "convert", "params": {"format": "mp4"}}],
        [{"operation": "convert", "params": {"format": "mp3", "extra": 1}}],
        [{"operation": "convert", "format": "mp3"}],
        [{"type": "convert", "params": {"format": "mp3"}}],
        [{"operation": "unknown", "params": {}}],
        [
            {"operation": "downscale", "params": {"height": 360}},
            {"operation": "upscale", "params": {"height": 1080}},
        ],
        [{"operation": "convert", "params": {"format": "mp3"}}] * 2,
        [{"operation": "convert", "params": {"format": "mp3"}}] * 6,
    ],
)
def test_rejects_invalid_operation_requests(submission, operations):
    submission["operations"] = operations
    with pytest.raises(ValidationError):
        SubmitJob.model_validate(submission)


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("source", "asset_id"), str(uuid4())),
        (("source", "revision"), 0),
        (("source", "revision"), True),
        (("source", "sha256"), "A" * 64),
        (("source", "size_bytes"), 0),
        (("source", "extra"), "unrecognized"),
        (("extra",), "unrecognized"),
        (("source_url",), "not-a-uri"),
        (("source_url_expires_at",), "2026-10-13T00:00:00"),
    ],
)
def test_rejects_invalid_source_and_envelope(submission, path, value):
    target = submission
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    with pytest.raises(ValidationError):
        SubmitJob.model_validate(submission)


def test_fingerprint_ignores_renewed_access_and_object_key_order(submission):
    original = request_fingerprint(SubmitJob.model_validate(submission))
    submission["source_url"] = "https://media.test/renewed?signature=new"
    submission["source_url_expires_at"] = "2026-10-14T00:00:00Z"
    submission["source"] = dict(reversed(list(submission["source"].items())))
    assert request_fingerprint(SubmitJob.model_validate(submission)) == original


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("owner_id",), str(uuid4())),
        (("source", "revision"), 2),
        (("source", "sha256"), "b" * 64),
        (("source", "size_bytes"), 5678),
        (("source", "media_type"), "video/webm"),
        (("operations",), [{"operation": "convert", "params": {"format": "mp3"}}]),
    ],
)
def test_fingerprint_covers_immutable_request(submission, path, value):
    original = request_fingerprint(SubmitJob.model_validate(submission))
    changed = copy.deepcopy(submission)
    target = changed
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    assert request_fingerprint(SubmitJob.model_validate(changed)) != original


def test_fingerprint_preserves_operation_order_but_normalizes_numbers(submission):
    submission["operations"] = [
        {"operation": "clip", "params": {"start": 0, "end": 10}},
        {"operation": "convert", "params": {"format": "mp3"}},
    ]
    original = request_fingerprint(SubmitJob.model_validate(submission))
    submission["operations"][0]["params"] = {"end": 10.0, "start": 0.0}
    assert request_fingerprint(SubmitJob.model_validate(submission)) == original
    submission["operations"].reverse()
    assert request_fingerprint(SubmitJob.model_validate(submission)) != original
