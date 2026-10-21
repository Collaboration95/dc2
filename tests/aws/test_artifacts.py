import copy
import hashlib
import json

import pytest
from test_transport_fixtures import NEW, artifact
from test_transport_fixtures import clock as clock
from test_transport_fixtures import config as config
from test_transport_fixtures import fake as fake
from test_transport_fixtures import journal as journal

from scripts.aws.artifacts import make_proof, scan_disposition, validate, validate_prepublication
from scripts.aws.transport import OperationError


@pytest.mark.parametrize("owner", ["media", "processing"])
def test_exact_registry_provenance(owner):
    proof = artifact(owner, NEW)
    assert validate(proof, owner=owner) == proof
    config_id = proof["config_id"]
    info = {
        "Id": config_id,
        "Os": "linux",
        "Architecture": "amd64",
        "Config": {"Labels": {"org.opencontainers.image.revision": proof["source_sha"]}},
    }
    raw = json.dumps({"schemaVersion": 2, "config": {"digest": config_id}}).encode()
    made = make_proof(
        owner=owner,
        source=proof["source_sha"],
        inspect=info,
        manifest_bytes=raw,
        tests=proof["tests"],
        artifact_test=proof["artifact_test"],
        trivy={
            "Metadata": {"ImageID": config_id},
            "Results": [
                {"Class": "os-pkgs", "Type": "debian", "Vulnerabilities": []},
                {"Class": "lang-pkgs", "Type": "python-pkg"},
            ],
        },
    )
    assert made["manifest_digest"] == "sha256:" + hashlib.sha256(raw).hexdigest()
    assert made["manifest_config_id"] == config_id


@pytest.mark.parametrize(
    "change",
    [
        "missing-test",
        "wrong-scan-image",
        "wrong-source",
        "fixable",
        "wrong-owner",
        "arm64",
        "config-as-manifest",
        "bad-config-link",
    ],
)
def test_bad_or_missing_provenance_rejected(change):
    proof = copy.deepcopy(artifact("processing", NEW))
    if change == "missing-test":
        del proof["tests"]
    elif change == "wrong-scan-image":
        proof["scan"]["config_id"] = "sha256:" + "f" * 64
    elif change == "wrong-source":
        proof["tests"]["source_sha"] = "d" * 40
    elif change == "fixable":
        proof["scan"]["fixable_high_critical"] = 1
    elif change == "wrong-owner":
        proof["owner"] = "media"
    elif change == "arm64":
        proof["platform"] = "linux/arm64"
    elif change == "config-as-manifest":
        proof["manifest_digest"] = proof["config_id"]
    else:
        proof["manifest_config_id"] = "sha256:" + "f" * 64
    with pytest.raises(OperationError):
        validate(proof, owner="processing")


def retained(owner="media"):
    """What a release plan records for a replaced rollback target that carries a fixable finding."""
    proof = copy.deepcopy(artifact(owner, NEW))
    proof["scan"].update(
        status="RETAINED_FIXABLE",
        fixable_high_critical=1,
        fixable_ids=["GHSA-6q48-6c7w-9gw2 certifi"],
    )
    return proof


def test_a_rollback_target_may_record_fixable_findings_but_never_be_a_candidate():
    proof = retained()
    assert validate(proof, owner="media", deployed=True) == proof
    # As a candidate (promote, the harness rollback, publication) it is refused.
    for check in (validate, validate_prepublication):
        with pytest.raises(OperationError, match="exact-artifact gate"):
            check(proof, owner="media")


@pytest.mark.parametrize(
    "change",
    [
        {"fixable_ids": []},
        {"fixable_high_critical": 0},
        {"fixable_high_critical": 2},
        {"fixable_ids": "GHSA-6q48-6c7w-9gw2"},
        {"status": "FAIL"},
        {"config_id": "sha256:" + "f" * 64},
    ],
)
def test_a_retained_scan_must_list_exactly_the_findings_it_counts(change):
    proof = retained()
    proof["scan"].update(change)
    with pytest.raises(OperationError):
        validate(proof, owner="media", deployed=True)


def test_deployed_does_not_relax_a_pass_receipt_with_fixable_findings():
    proof = copy.deepcopy(artifact("media", NEW))
    proof["scan"]["fixable_high_critical"] = 1
    with pytest.raises(OperationError, match="block promotion"):
        validate(proof, owner="media", deployed=True)


@pytest.mark.parametrize("outcome", ["executed", "skipped", "error"])
def test_truthful_scan_dispositions(outcome):
    result = scan_disposition(
        "zap",
        outcome=outcome,
        target="isolated-integrated-media-public",
        scope="authenticated-owner; private-contracts-prepared-only",
        report_retained=outcome == "executed",
    )
    assert result["disposition"] == outcome
    assert result["policy"] == "report-only-findings"
    with pytest.raises(OperationError):
        scan_disposition(
            "sonar",
            outcome="executed",
            target="media/processing",
            scope="source",
            report_retained=False,
        )


def test_inert_publish_plan_and_registry_receipt_are_separate():
    from scripts.aws.artifacts import publication_plan, registry_receipt

    proof = artifact("processing", NEW)
    plan = publication_plan(
        proof, repository="processing", account_id="123456789012", region="ap-southeast-1"
    )
    assert plan["production_execution"] == "DISABLED"
    assert plan["commands"][1][2] == proof["config_id"]
    raw = json.dumps({"config": {"digest": proof["config_id"]}, "schemaVersion": 2})
    receipt = {
        "images": [
            {
                "imageManifest": raw,
                "imageId": {"imageDigest": "sha256:" + hashlib.sha256(raw.encode()).hexdigest()},
            }
        ]
    }
    result = registry_receipt(proof, receipt)
    assert result["publication_status"] == "receipt-verified"
    receipt["images"][0]["imageId"]["imageDigest"] = NEW
    with pytest.raises(OperationError, match="manifest bytes"):
        registry_receipt(proof, receipt)


@pytest.mark.parametrize(
    "report",
    [{}, {"Metadata": {"ImageID": "wrong"}, "Results": []}, {"Results": [{"Class": "lang-pkgs"}]}],
)
def test_missing_or_fake_trivy_report_rejected(report):
    from scripts.aws.artifacts import prepublication_proof

    proof = artifact("processing", NEW)
    info = {
        "Id": proof["config_id"],
        "Os": "linux",
        "Architecture": "amd64",
        "Config": {"Labels": {"org.opencontainers.image.revision": proof["source_sha"]}},
    }
    with pytest.raises(OperationError, match="Trivy"):
        prepublication_proof(
            owner="processing",
            source=proof["source_sha"],
            inspect=info,
            tests=proof["tests"],
            artifact_test=proof["artifact_test"],
            trivy_bytes=json.dumps(report).encode(),
        )
