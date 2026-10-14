import gzip
import hashlib
import json
import tarfile

import pytest

from scripts.aws.evidence import Evidence, select


@pytest.mark.parametrize(
    "sentinel",
    [
        "postgresql://owner:private@db/name",
        "https://bucket/object?X-Amz-Signature=private",
        "Cookie private",
        "Authorization Bearer private",
        "session-token-private",
        "opaque-private-value",
    ],
)
def test_selected_redaction_precedes_persistence_and_archive(tmp_path, sentinel):
    evidence = Evidence(tmp_path / "records", secrets=(sentinel,))
    evidence.write(
        "cases.jsonl",
        {
            "mode": "offline",
            "status": "FAIL",
            "case": sentinel,
            "task_environment": sentinel,
            "failure_code": "request_failed",
        },
    )
    assert sentinel.encode() not in (evidence.directory / "cases.jsonl").read_bytes()
    # Private non-allowlisted additions cannot enter export.
    (evidence.directory / "raw-cli.txt").write_text(sentinel)
    (evidence.directory / "private-db.sql").write_text(sentinel)
    archive = tmp_path / "evidence.tar"
    index = evidence.archive(archive)
    assert set(index) == {"cases.jsonl"}
    with tarfile.open(archive) as tar:
        content = gzip.decompress(tar.extractfile("cases.jsonl.gz").read())
        assert sentinel.encode() not in content
        assert hashlib.sha256(content).hexdigest() == index["cases.jsonl"]["sha256"]
        assert len(content) == index["cases.jsonl"]["size_bytes"]


def test_reselect_manually_modified_artifact(tmp_path):
    evidence = Evidence(tmp_path / "records")
    (evidence.directory / "manifest.json").write_text(
        json.dumps({"case": "safe", "raw": "private"})
    )
    archive = tmp_path / "a.tar"
    evidence.archive(archive)
    with tarfile.open(archive) as tar:
        assert json.loads(gzip.decompress(tar.extractfile("manifest.json.gz").read())) == {
            "case": "safe"
        }


def test_filename_symlink_and_nonfinite_values_rejected(tmp_path):
    evidence = Evidence(tmp_path / "records")
    for name in ["../secret.json", "raw-cli.json", "task-env.json", "capture.har"]:
        with pytest.raises(ValueError):
            evidence.write(name, {"case": "safe"})
    with pytest.raises(ValueError):
        evidence.write("manifest.json", {"elapsed_ms": float("nan")})
    outside = tmp_path / "outside"
    outside.write_text("private")
    (evidence.directory / "manifest.json").symlink_to(outside)
    with pytest.raises(ValueError):
        evidence.write("manifest.json", {"case": "safe"})
    assert outside.read_text() == "private"


def test_modes_do_not_relabel_emulator_as_aws():
    assert select({"mode": "emulator", "status": "PASS"})["mode"] == "emulator"
    with pytest.raises(ValueError):
        select({"mode": "mock-aws", "status": "PASS"})


@pytest.mark.parametrize(
    "record",
    [
        {"elapsed_ms": "123"},
        {"elapsed_ms": -1},
        {"case": True},
        {"eligible": "yes"},
        {"task_ids": "task"},
    ],
)
def test_typed_schema_rejects_malformed_receipts_before_persistence(tmp_path, record):
    evidence = Evidence(tmp_path / "records")
    with pytest.raises(ValueError):
        evidence.write("cases.jsonl", record)
    assert not (evidence.directory / "cases.jsonl").exists()
