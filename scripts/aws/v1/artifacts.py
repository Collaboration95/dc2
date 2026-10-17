"""V1 owner/API and finite worker artifact gates, built on exact AWS2 receipts."""

from scripts.aws.artifacts import validate
from scripts.aws.transport import OperationError


def validate_bundle(bundle, *, owner):
    api = validate(bundle["api"], owner=owner)
    if api.get("runtime_kind") != "lambda-api":
        raise OperationError("Lambda API artifact required")
    expected = {"api", "worker"} if owner == "processing" else {"api"}
    if set(bundle) != expected:
        raise OperationError("Exactly the owning artifact set is required")
    for kind, proof in bundle.items():
        validate(proof, owner=owner)
        if proof["source_sha"] != api["source_sha"]:
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
