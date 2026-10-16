"""Source, image and emulation-boundary provenance for the V1 run manifest.

Everything here is read-only evidence about what a verification run exercised. A label
such as NOT_BUILT or NOT_RUN is a result, not a gap to paper over: no consumer may treat
a missing image or an emulated boundary as cloud evidence.
"""

import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# Built by the recipes in deploy/v1/README.md. The local verification imports the
# handlers from source, so these digests identify candidate artifacts, not what ran.
V1_IMAGES = ("dc2-v1-media", "dc2-v1-processing", "dc2-v1-worker")

# Every AWS service the local run replaces, and what replaces it. The wording is part of
# the evidence: complete_v1_acceptance must never read as a cloud PASS.
BOUNDARIES = {
    "real": {
        "postgresql": "PostgreSQL 16 container, owner roles, TLS and migrations",
        "ffmpeg": "inherited engine encoding real MP4 and HLS bytes",
        "domain_code": "media/, processing/, delivery/, contracts/ handlers and SQL",
        "clients": "Publisher PublicClient and, when V1_BROWSER=1, the real frontend in Chromium",
    },
    "emulated": {
        "api_gateway": "scripts.dev.v1_gateway loopback bridge; not HTTP API, IAM or CloudFront",
        "s3_sqs": "Moto HTTP server on loopback; not AWS S3/SQS semantics, IAM or KMS",
        "event_source_mapping": "scripts.dev.v1_acceptance.pump delivers SQS batches by hand",
        "lambda": "handlers imported in-process; no Lambda runtime, cold start or concurrency",
        "fargate": "processing.v1_worker runs as a local subprocess; no ECS task or image",
        "release_transport": "fake Lambda/ECS transport; alias moves are not AWS API calls",
        "tls": "generated local certificate trusted only by the test process",
    },
    "not_run": [
        "AWS IAM and resource policies",
        "Aurora networking and pause",
        "public DNS, TLS and CloudFront",
        "Lambda and Fargate images in a registry",
        "billing",
    ],
}


def _run(argv, runner=subprocess.run):
    return runner(argv, cwd=ROOT, capture_output=True, text=True, timeout=30)


def source(runner=subprocess.run):
    """Commit plus a dirty flag that also binds uncommitted bytes by hash."""
    sha = _run(["git", "rev-parse", "HEAD"], runner).stdout.strip()
    tracked = _run(["git", "diff", "HEAD", "--binary"], runner).stdout
    untracked = _run(["git", "ls-files", "--others", "--exclude-standard"], runner).stdout.split()
    dirty = bool(tracked.strip() or untracked)
    evidence = {"sha": sha, "dirty": dirty, "untracked_files": len(untracked)}
    if dirty:
        # Without this a dirty manifest cannot be tied to the bytes that produced it.
        digest = hashlib.sha256(tracked.encode())
        for name in sorted(untracked):
            digest.update(name.encode())
            try:
                digest.update((ROOT / name).read_bytes())
            except OSError:
                digest.update(b"<unreadable>")
        evidence["dirty_sha256"] = digest.hexdigest()
    return evidence


EVIDENCE = ROOT / "docs/execution/aws/v1/evidence"


def built_evidence(name, sha, folder=None):
    """This commit's deploy/v1/build_and_verify.py receipt for one image, if there is one.

    Only a receipt whose source SHA equals the verified commit counts; an older build of
    different bytes would be a false claim about what this run covered.
    """
    owner = name.removeprefix("dc2-v1-")
    path = (folder or EVIDENCE) / f"local-images-{sha[:12]}.json"
    if not path.is_file():
        return None
    receipt = json.loads(path.read_text())
    entry = receipt.get("images", {}).get(owner)
    if receipt.get("source_sha") != sha or not entry or entry.get("build_exit_code") != 0:
        return None
    return {
        "status": "BUILT",
        "source": "deploy/v1/build_and_verify.py receipt",
        "receipt": str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else path.name,
        "receipt_status": receipt.get("status"),
        "config_id": entry["config_id"],
        "repo_digests": entry.get("repo_digests", []),
        "revision_label": sha,
        "matches_source_sha": True,
        "working_tree_dirty": receipt.get("working_tree_dirty"),
        "exercised_by_this_run": False,
    }


def image(name, context, sha, runner=subprocess.run, evidence_folder=None):
    """Config ID, registry digests and revision label, or NOT_BUILT when absent."""
    recorded = built_evidence(name, sha, evidence_folder)
    if recorded:
        return recorded
    reference = f"{name}:latest"
    reply = runner(
        ["docker", "--context", context, "image", "inspect", reference],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if reply.returncode:
        return {"status": "NOT_BUILT", "reference": reference}
    inspected = json.loads(reply.stdout)[0]
    revision = (inspected.get("Config", {}).get("Labels") or {}).get(
        "org.opencontainers.image.revision"
    )
    return {
        "status": "BUILT",
        "reference": reference,
        "config_id": inspected["Id"],
        "repo_digests": inspected.get("RepoDigests", []),
        "revision_label": revision,
        "matches_source_sha": revision == sha,
        # The run imports handlers from source; an image here was not exercised.
        "exercised_by_this_run": False,
    }


def postgres_image(data, runner=subprocess.run):
    """The image the real PostgreSQL container was created from."""
    reply = runner(
        [
            "docker",
            "--context",
            data["docker_context"],
            "inspect",
            "--format",
            "{{.Image}} {{.Config.Image}}",
            f"{data['project']}-postgres-1",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if reply.returncode:
        return {"status": "UNKNOWN"}
    config_id, _, reference = reply.stdout.strip().partition(" ")
    return {"status": "RUNNING", "reference": reference, "config_id": config_id}


def tools(moto_python, runner=subprocess.run):
    """Versions of the emulator and encoder that produced the evidence."""

    def first_line(argv):
        try:
            return runner(argv, capture_output=True, text=True, timeout=15).stdout.splitlines()[0]
        except (OSError, IndexError, subprocess.SubprocessError):
            return "UNKNOWN"

    return {
        "python": sys.version.split()[0],
        "ffmpeg": first_line(["ffmpeg", "-version"]),
        "moto": first_line([moto_python, "-c", "import moto; print(moto.__version__)"]),
    }


def collect(data, moto_python, runner=subprocess.run):
    """Everything the manifest records before any flow runs."""
    src = source(runner)
    return {
        "source": src,
        "images": {
            "v1_artifacts": {
                name: image(name, data["docker_context"], src["sha"], runner) for name in V1_IMAGES
            },
            "postgres": postgres_image(data, runner),
        },
        "tools": tools(moto_python, runner),
        "boundaries": BOUNDARIES,
    }
