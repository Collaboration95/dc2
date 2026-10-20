import copy
import hashlib
import json

import pytest
from test_transport_fixtures import NEW, artifact
from test_transport_fixtures import clock as clock
from test_transport_fixtures import config as config
from test_transport_fixtures import fake as fake
from test_transport_fixtures import journal as journal

from scripts.aws.artifacts import make_proof, scan_disposition, validate
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
            "Results": [{"Class": "os-pkgs", "Type": "debian", "Vulnerabilities": []},
                        {"Class": "lang-pkgs", "Type": "python-pkg"}],
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
