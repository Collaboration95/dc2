"""Selected-owner immutable amd64 provenance, config IDs != registry digests."""

import argparse
import hashlib
import json
import re
from pathlib import Path

from scripts.aws.transport import OperationError, safe_record

DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")
SOURCE = re.compile(r"[0-9a-f]{40}\Z")


def digest(value):
    if not isinstance(value, str) or not DIGEST.fullmatch(value):
        raise OperationError("Exact sha256 digest required")
    return value


def validate(proof, *, owner=None):
    safe_record(proof)
    if proof.get("owner") not in {"media", "processing"} or owner and proof["owner"] != owner:
        raise OperationError("Wrong artifact owner")
    if proof.get("platform") != "linux/amd64" or not SOURCE.fullmatch(proof.get("source_sha", "")):
        raise OperationError("Frozen source and linux/amd64 artifact required")
    validate_prepublication(proof, owner=owner)
    image = digest(proof.get("config_id"))
    manifest = digest(proof.get("manifest_digest"))
    if image == manifest:
        raise OperationError("Config ID is not the registry manifest digest")
    if proof.get("manifest_config_id") != image:
        raise OperationError("Registry manifest does not reference tested config")
    return proof


def validate_prepublication(proof, *, owner=None):
    safe_record(proof)
    if proof.get("owner") not in {"media", "processing"} or owner and proof["owner"] != owner:
        raise OperationError("Wrong artifact owner")
    if proof.get("platform") != "linux/amd64" or not SOURCE.fullmatch(proof.get("source_sha", "")):
        raise OperationError("Frozen source and linux/amd64 artifact required")
    image = digest(proof.get("config_id"))
    for name in ("tests", "artifact_test", "scan"):
        receipt = proof.get(name, {})
        if (
            receipt.get("status") != "PASS"
            or receipt.get("config_id") != image
            or receipt.get("source_sha") != proof["source_sha"]
        ):
            raise OperationError("Missing or mismatched exact-artifact gate")
    if proof["scan"].get("fixable_high_critical") != 0:
        raise OperationError("Fixable HIGH/CRITICAL findings block promotion")
    if not isinstance(proof["tests"].get("passed"), int) or proof["tests"]["passed"] < 1:
        raise OperationError("Executed source tests required")
    if not proof["artifact_test"].get("kind"):
        raise OperationError("Artifact execution receipt required")
    digest(proof["scan"].get("report_sha256"))
    return proof


def prepublication_proof(*, owner, source, inspect, tests, artifact_test, trivy_bytes):
    info = inspect[0] if isinstance(inspect, list) and len(inspect) == 1 else inspect
    if (
        info["Os"] != "linux"
        or info["Architecture"] != "amd64"
        or info.get("Config", {}).get("Labels", {}).get("org.opencontainers.image.revision")
        != source
    ):
        raise OperationError("Image architecture/source label mismatch")
    image = digest(info["Id"])
    trivy = json.loads(trivy_bytes)
    if (
        trivy.get("Metadata", {}).get("ImageID") != image
        or not trivy.get("Results")
        or not any(r.get("Class") == "os-pkgs" for r in trivy["Results"])
    ):
        raise OperationError("Trivy OS package report must identify scanned config ID")
    findings = sum(
        1
        for r in trivy["Results"]
        for v in r.get("Vulnerabilities", [])
        if v.get("Severity") in {"HIGH", "CRITICAL"} and v.get("FixedVersion")
    )
    proof = {
        "owner": owner,
        "platform": "linux/amd64",
        "source_sha": source,
        "config_id": image,
        "tests": tests,
        "artifact_test": artifact_test,
        "scan": {
            "status": "PASS",
            "config_id": image,
            "source_sha": source,
            "report_sha256": "sha256:" + hashlib.sha256(trivy_bytes).hexdigest(),
            "fixable_high_critical": findings,
        },
        "publication_status": "NOT_RUN",
        "deployment_status": "NOT_RUN",
    }
    return validate_prepublication(proof, owner=owner)


def make_proof(*, owner, source, inspect, manifest_bytes, tests, artifact_test, trivy):
    info = inspect[0] if isinstance(inspect, list) and len(inspect) == 1 else inspect
    if (
        info["Os"] != "linux"
        or info["Architecture"] != "amd64"
        or info.get("Config", {}).get("Labels", {}).get("org.opencontainers.image.revision")
        != source
    ):
        raise OperationError("Image architecture/source label mismatch")
    image = digest(info["Id"])
    manifest = json.loads(manifest_bytes)
    if "manifests" in manifest or manifest.get("config", {}).get("digest") != image:
        raise OperationError("Require the amd64 image manifest, not an index/tag")
    proof = prepublication_proof(
        owner=owner,
        source=source,
        inspect=inspect,
        tests=tests,
        artifact_test=artifact_test,
        trivy_bytes=json.dumps(trivy).encode(),
    )
    proof.update(
        manifest_digest="sha256:" + hashlib.sha256(manifest_bytes).hexdigest(),
        manifest_config_id=manifest["config"]["digest"],
        publication_status="receipt-verified",
    )
    return validate(proof)


def scan_disposition(engine, *, outcome, target, scope, report_retained):
    if engine not in {"sonar", "zap"} or outcome not in {"executed", "skipped", "error"}:
        raise OperationError("Unknown scan disposition")
    if outcome == "executed" and not report_retained:
        raise OperationError("Executed scan requires retained report")
    record = {
        "engine": engine,
        "disposition": outcome,
        "target": target,
        "scope": scope,
        "report_retained": bool(report_retained),
        "policy": "report-only-findings" if engine == "zap" else "reported-quality-gate",
    }
    safe_record(record)
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("proof", type=Path)
    args = parser.parse_args()
    validate(json.loads(args.proof.read_text()))
    print("Artifact gates valid; production publish/apply remains disabled")


def publication_plan(proof, *, repository, account_id, region):
    """Future commands only; registry authentication/approval is external and gated."""
    validate_prepublication(proof)
    if (
        not re.fullmatch(r"\d{12}", account_id)
        or not re.fullmatch(r"[a-z]{2}-[a-z]+-\d", region)
        or not re.fullmatch(r"[a-z0-9]+(?:[._/-][a-z0-9]+)*", repository)
    ):
        raise OperationError("Explicit approved registry coordinates required to plan publish")
    tag = proof["source_sha"] + "-" + proof["config_id"].split(":")[1][:12]
    reference = f"{account_id}.dkr.ecr.{region}.amazonaws.com/{repository}:{tag}"
    return {
        "owner": proof["owner"],
        "production_execution": "DISABLED",
        "commands": [
            ["docker", "image", "inspect", "--format", "{{.Id}}", proof["config_id"]],
            ["docker", "tag", proof["config_id"], reference],
            ["docker", "push", reference],
        ],
        "receipt_request": {
            "service": "ecr",
            "operation": "batch-get-image",
            "payload": {
                "registryId": account_id,
                "repositoryName": repository,
                "imageIds": [{"imageTag": tag}],
            },
        },
        "requirement": (
            "Load retained same config ID; never rebuild after scan; verify registry receipt"
        ),
    }


def registry_receipt(proof, response):
    """Bind raw registry manifest bytes and reported registry digest to tested ID."""
    validate_prepublication(proof)
    if response.get("failures") or len(response.get("images", [])) != 1:
        raise OperationError("Missing or ambiguous registry receipt")
    image = response["images"][0]
    raw = image["imageManifest"].encode()
    reported = digest(image["imageId"]["imageDigest"])
    if "sha256:" + hashlib.sha256(raw).hexdigest() != reported:
        raise OperationError("Registry digest does not match returned manifest bytes")
    manifest = json.loads(raw)
    if "manifests" in manifest or manifest.get("config", {}).get("digest") != proof["config_id"]:
        raise OperationError("Registry manifest/index does not reference tested config")
    result = {
        **proof,
        "manifest_digest": reported,
        "manifest_config_id": proof["config_id"],
        "publication_status": "receipt-verified",
    }
    return validate(result)


if __name__ == "__main__":
    main()
