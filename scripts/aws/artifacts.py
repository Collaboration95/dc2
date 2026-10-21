"""Selected-owner immutable amd64 provenance, config IDs != registry digests."""

import argparse
import hashlib
import json
import re
from pathlib import Path

from scripts.aws.transport import OperationError, safe_record
from scripts.ci.v1_scan import RETAINED, findings, validate_report

DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")
SOURCE = re.compile(r"[0-9a-f]{40}\Z")


def digest(value):
    if not isinstance(value, str) or not DIGEST.fullmatch(value):
        raise OperationError("Exact sha256 digest required")
    return value


def validate(proof, *, owner=None, deployed=False):
    safe_record(proof)
    if proof.get("owner") not in {"media", "processing"} or owner and proof["owner"] != owner:
        raise OperationError("Wrong artifact owner")
    if proof.get("platform") != "linux/amd64" or not SOURCE.fullmatch(proof.get("source_sha", "")):
        raise OperationError("Frozen source and linux/amd64 artifact required")
    validate_prepublication(proof, owner=owner, deployed=deployed)
    image = digest(proof.get("config_id"))
    manifest = digest(proof.get("manifest_digest"))
    if image == manifest:
        raise OperationError("Config ID is not the registry manifest digest")
    if proof.get("manifest_config_id") != image:
        raise OperationError("Registry manifest does not reference tested config")
    return proof


def validate_prepublication(proof, *, owner=None, deployed=False):
    """`deployed` is a release plan's baseline, the image that runs now and that a release
    replaces. It alone may carry a scan that recorded fixable findings (RETAINED_FIXABLE): a
    rollback target cannot be rebuilt, and nothing that carries one can be promoted."""
    safe_record(proof)
    if proof.get("owner") not in {"media", "processing"} or owner and proof["owner"] != owner:
        raise OperationError("Wrong artifact owner")
    if proof.get("platform") != "linux/amd64" or not SOURCE.fullmatch(proof.get("source_sha", "")):
        raise OperationError("Frozen source and linux/amd64 artifact required")
    image = digest(proof.get("config_id"))
    retained = deployed and proof.get("scan", {}).get("status") == RETAINED
    for name in ("tests", "artifact_test", "scan"):
        receipt = proof.get(name, {})
        if (
            receipt.get("status") != (RETAINED if retained and name == "scan" else "PASS")
            or receipt.get("config_id") != image
            or receipt.get("source_sha") != proof["source_sha"]
        ):
            raise OperationError("Missing or mismatched exact-artifact gate")
    found = proof["scan"].get("fixable_high_critical")
    if retained:
        ids = proof["scan"].get("fixable_ids")
        if type(found) is not int or not isinstance(ids, list) or not ids or found != len(ids):
            raise OperationError("A retained scan must list the fixable findings it records")
    elif found != 0:
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
    try:
        trivy = validate_report(json.loads(trivy_bytes), image)
    except ValueError as error:
        raise OperationError(str(error)) from None
    fixable, _ = findings(trivy)
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
            "fixable_high_critical": len(fixable),
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


def registry_receipt(proof, response, *, deployed=False):
    """Bind raw registry manifest bytes and reported registry digest to tested ID."""
    validate_prepublication(proof, deployed=deployed)
    receipt = manifest_receipt(proof["config_id"], response)
    return validate({**proof, **receipt}, deployed=deployed)


def manifest_receipt(config_id, response):
    """The raw-byte/config binding shared by deploy and full artifact receipts."""
    digest(config_id)
    if (
        not isinstance(response, dict)
        or response.get("failures")
        or not isinstance(response.get("images"), list)
        or len(response["images"]) != 1
    ):
        raise OperationError("Missing or ambiguous registry receipt")
    try:
        image = response["images"][0]
        raw = image["imageManifest"].encode()
        reported = digest(image["imageId"]["imageDigest"])
        manifest = json.loads(raw)
    except (KeyError, TypeError, AttributeError, ValueError):
        raise OperationError("Malformed registry manifest receipt") from None
    if "sha256:" + hashlib.sha256(raw).hexdigest() != reported:
        raise OperationError("Registry digest does not match returned manifest bytes")
    if (
        not isinstance(manifest, dict)
        or "manifests" in manifest
        or not isinstance(manifest.get("config"), dict)
        or manifest["config"].get("digest") != config_id
    ):
        raise OperationError("Registry manifest/index does not reference tested config")
    return {
        "manifest_digest": reported,
        "manifest_config_id": config_id,
        "publication_status": "receipt-verified",
    }


if __name__ == "__main__":
    main()
