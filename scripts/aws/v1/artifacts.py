"""V1 owner/API and finite worker artifact gates, built on exact AWS2 receipts."""

import hashlib
import json

from scripts.aws.artifacts import validate
from scripts.aws.transport import OperationError


def validate_bundle(bundle, *, owner, deployed=False):
    """`deployed` describes what runs now (a plan's baseline) rather than a release candidate.

    After a release that kept one of Processing's images, the API and the worker that run come
    from different commits. That is a valid baseline: each artifact is still checked on its own,
    and only a candidate must share one frozen source and rebuild something. A baseline may also
    record fixable findings (RETAINED_FIXABLE): it is only a rollback target, and no candidate can.
    """
    api = validate(bundle["api"], owner=owner, deployed=deployed)
    if api.get("runtime_kind") != "lambda-api":
        raise OperationError("Lambda API artifact required")
    expected = {"api", "worker"} if owner == "processing" else {"api"}
    if set(bundle) != expected:
        raise OperationError("Exactly the owning artifact set is required")
    # A release may keep one of Processing's two images exactly as it runs (its build inputs did
    # not change, V2-live). That companion is marked retained and keeps its own, older source;
    # every rebuilt artifact shares one frozen source, and at least one must be rebuilt.
    if any(type(proof.get("retained", False)) is not bool for proof in bundle.values()):
        raise OperationError("Retained must be a boolean")
    fresh = (
        {}
        if deployed
        else {kind: proof for kind, proof in bundle.items() if not proof.get("retained")}
    )
    if not fresh and not deployed:
        raise OperationError("A release needs at least one rebuilt artifact")
    source = next(iter(fresh.values()))["source_sha"] if fresh else None
    for kind, proof in bundle.items():
        validate(proof, owner=owner, deployed=deployed)
        if kind in fresh and proof["source_sha"] != source:
            raise OperationError("Owner artifacts must share frozen source")
        if proof.get("runtime_kind") != ("lambda-api" if kind == "api" else "finite-worker"):
            raise OperationError("Wrong execution artifact kind")
        contents = proof.get("runtime_contents", {})
        if contents.get("redis") is not False or contents.get("rq") is not False:
            raise OperationError("Executed no-Redis/RQ artifact checks required")
        if contents.get("ffmpeg") is not (kind == "worker"):
            raise OperationError("FFmpeg belongs only in the finite worker")
    if owner == "processing" and any(
        bundle["worker"][field] == api[field] for field in ("config_id", "manifest_digest")
    ):
        raise OperationError("API and finite worker require distinct artifacts")
    return bundle


class ScanPending(OperationError):
    """Only an explicitly pending registry scan may be retried."""


def registry_scan(aws, repository, digest, tag, accept_ids=()):
    """The same completed ECR policy for first deploy, resume and owner release."""
    request = {"repositoryName": repository.split("/", 1)[1], "imageId": {"imageDigest": digest}}
    reply = aws("ecr", "describe-image-scan-findings", request)
    if not isinstance(reply, dict):
        raise OperationError(f"The scan of {tag} returned no report")
    scan_status = reply.get("imageScanStatus")
    status = scan_status.get("status") if isinstance(scan_status, dict) else None
    image_id = reply.get("imageId")
    if not isinstance(image_id, dict) or image_id.get("imageDigest") != digest:
        raise OperationError(f"The scan of {tag} names a different or missing digest")
    if status in {"IN_PROGRESS", "PENDING"}:
        raise ScanPending(f"The scan of {tag} is not COMPLETE yet")
    if status != "COMPLETE":
        raise OperationError(f"The scan of {tag} is missing or failed (not COMPLETE)")
    data = reply.get("imageScanFindings")
    counts = data.get("findingSeverityCounts") if isinstance(data, dict) else None
    if not isinstance(counts, dict) or any(type(v) is not int or v < 0 for v in counts.values()):
        raise OperationError(
            f"The scan of {tag} severity counts are missing/invalid; cannot be matched to findings"
        )
    total = counts.get("HIGH", 0) + counts.get("CRITICAL", 0)
    merged = json.loads(json.dumps(reply, default=str))
    merged["imageScanFindings"].setdefault("findings", [])
    if not isinstance(merged["imageScanFindings"]["findings"], list):
        raise OperationError(f"The scan findings of {tag} are malformed")
    token, pages = merged.pop("nextToken", None), 1
    while token:
        pages += 1
        if pages > 200:
            raise OperationError(f"The scan findings of {tag} do not end")
        page = aws("ecr", "describe-image-scan-findings", {**request, "nextToken": token})
        if (
            not isinstance(page, dict)
            or not isinstance(page.get("imageScanStatus"), dict)
            or not isinstance(page.get("imageId"), dict)
            or page["imageScanStatus"].get("status") != "COMPLETE"
            or page.get("imageId", {}).get("imageDigest") != digest
        ):
            raise OperationError(f"The scan findings of {tag} changed during pagination")
        page_data = page.get("imageScanFindings")
        if not isinstance(page_data, dict) or not isinstance(page_data.get("findings", []), list):
            raise OperationError(f"The scan findings of {tag} are malformed")
        merged["imageScanFindings"]["findings"] += page_data.get("findings", [])
        if page_data.get("enhancedFindings"):
            merged["imageScanFindings"]["enhancedFindings"] = True
        token = page.get("nextToken")
    if merged["imageScanFindings"].get("enhancedFindings"):
        raise OperationError(
            f"The scan of {tag} uses enhanced findings, which this policy cannot match"
        )
    findings = merged["imageScanFindings"]["findings"]
    if not isinstance(findings, list) or any(not isinstance(f, dict) for f in findings):
        raise OperationError(f"The scan findings of {tag} are malformed")
    serious = [f for f in findings if f.get("severity") in ("HIGH", "CRITICAL")]
    if not accept_ids and (total or serious):
        raise OperationError(
            f"{tag} has {max(total, len(serious))} HIGH/CRITICAL scan findings; "
            "the release gate blocks it"
        )
    accepted = []
    if accept_ids:
        if len(serious) != total:
            raise OperationError(
                f"The scan of {tag} counts {total} HIGH/CRITICAL findings but "
                f"lists {len(serious)}, so they cannot be matched to the "
                "accept list"
            )
        names = {str(f.get("name")) for f in serious}
        blocked = sorted(names - set(accept_ids))
        if blocked:
            shown = ", ".join(blocked[:10]) + (" ..." if len(blocked) > 10 else "")
            raise OperationError(
                f"{tag} has {len(blocked)} HIGH/CRITICAL scan finding(s) not "
                f"on the accept list: {shown}"
            )
        accepted = sorted(names)
    return {
        "status": "COMPLETE",
        "severity_counts": counts,
        "blocking_high_critical": 0,
        "accepted_high_critical": accepted,
        "report_sha256": "sha256:"
        + hashlib.sha256(json.dumps(merged, sort_keys=True, default=str).encode()).hexdigest(),
    }
