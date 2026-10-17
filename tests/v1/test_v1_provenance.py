"""Run-manifest provenance: honest about dirt, images and every emulated boundary."""

import json
from types import SimpleNamespace

from scripts.dev import v1_provenance as provenance

SHA = "a" * 40


def reply(stdout="", code=0):
    return SimpleNamespace(stdout=stdout, stderr="", returncode=code)


def git(diff="", untracked=""):
    def runner(argv, **kwargs):
        if argv[:2] == ["git", "rev-parse"]:
            return reply(SHA + "\n")
        if argv[:2] == ["git", "diff"]:
            return reply(diff)
        return reply(untracked)

    return runner


def test_clean_tree_is_reported_clean_without_a_dirty_hash():
    found = provenance.source(git())
    assert found == {"sha": SHA, "dirty": False, "untracked_files": 0}


def test_modified_tracked_bytes_mark_the_tree_dirty_and_are_bound_by_hash():
    first = provenance.source(git(diff="diff one"))
    second = provenance.source(git(diff="diff two"))
    assert first["dirty"] and len(first["dirty_sha256"]) == 64
    assert first["dirty_sha256"] != second["dirty_sha256"]


def test_an_untracked_file_alone_makes_the_tree_dirty():
    found = provenance.source(git(untracked="no-such-file.py\n"))
    assert found["dirty"] and found["untracked_files"] == 1


def test_missing_image_is_labelled_not_built_rather_than_omitted(tmp_path):
    absent = lambda argv, **kwargs: reply(code=1)  # noqa: E731
    found = provenance.image("dc2-v1-media", "ctx", SHA, absent, evidence_folder=tmp_path)
    assert found == {"status": "NOT_BUILT", "reference": "dc2-v1-media:latest"}


def test_local_image_records_config_id_and_whether_its_revision_matches_the_source():
    label = {"org.opencontainers.image.revision": SHA}
    inspected = [{"Id": "sha256:abc", "Config": {"Labels": label}}]
    runner = lambda argv, **kwargs: reply(json.dumps(inspected))  # noqa: E731
    found = provenance.image("dc2-v1-worker", "ctx", SHA, runner)
    assert found["status"] == "BUILT" and found["matches_source_sha"] is True
    assert found["config_id"] == "sha256:abc"
    assert found["exercised_by_this_run"] is False
    other = provenance.image("dc2-v1-worker", "ctx", "b" * 40, runner)
    assert other["matches_source_sha"] is False


def write_receipt(folder, sha, **entry):
    receipt = {
        "source_sha": sha,
        "status": "PASS",
        "images": {"media": {"build_exit_code": 0, "config_id": "sha256:feed", **entry}},
    }
    (folder / f"local-images-{sha[:12]}.json").write_text(json.dumps(receipt))


def test_build_receipt_for_this_exact_commit_supplies_the_image_identity(tmp_path):
    write_receipt(tmp_path, SHA)
    forbidden = lambda *a, **k: (_ for _ in ()).throw(AssertionError("docker not needed"))  # noqa: E731
    found = provenance.image("dc2-v1-media", "ctx", SHA, forbidden, evidence_folder=tmp_path)
    assert found["status"] == "BUILT" and found["config_id"] == "sha256:feed"
    assert found["source"].startswith("deploy/v1/build_and_verify.py")


def test_receipt_for_a_different_commit_or_a_failed_build_is_not_used(tmp_path):
    write_receipt(tmp_path, SHA, build_exit_code=1)
    assert provenance.built_evidence("dc2-v1-media", SHA, tmp_path) is None
    assert provenance.built_evidence("dc2-v1-media", "c" * 40, tmp_path) is None


def test_every_emulated_aws_boundary_is_named_and_cloud_checks_are_listed_not_run():
    emulated = provenance.BOUNDARIES["emulated"]
    for boundary in ("api_gateway", "s3_sqs", "lambda", "fargate", "release_transport"):
        assert boundary in emulated
    assert "Moto" in emulated["s3_sqs"] and "in-process" in emulated["lambda"]
    assert "AWS IAM and resource policies" in provenance.BOUNDARIES["not_run"]
