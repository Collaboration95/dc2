"""Auditable CI selection and fail-closed aggregate validation (standard library only)."""

import argparse
import json
import os
import re
import subprocess
from pathlib import Path, PurePosixPath

LANES = (
    "policy-checks",
    "planning",
    "lint-and-unit",
    "frontend",
    "legacy-integration",
    "processing-intake",
    "media-integration",
    "publisher-https",
    "browser-trust",
    "v1_offline",
    "v1_live",
    "images",
    "coverage-gate",
    "security",
    "dast",
)
V1_LANES = {"v1_offline", "v1_live", "images"}
IMAGE_RECIPES = {
    "app": ("Dockerfile", "flickpond-api:ci"),
    "processing": ("deploy/processing.Dockerfile", "dc2-processing:ci"),
    "media": ("deploy/media.Dockerfile", "dc2-media:ci"),
}
# These are the actual COPY/build inputs, including shared runtime imports. V1 is
# deliberately all-three: the reusable workflow verifies their joint isolation contract.
V1_INPUTS = (
    "media/",
    "processing/",
    "media_engine/",
    "contracts/",
    "delivery/",
    "runtime_support/",
    "deploy/v1/",
    "deploy/aws/v1/template.json",
    "scripts/aws/v1/bootstrap.py",
)
COMMON_IMAGE_INPUTS = {"pyproject.toml", "uv.lock", ".dockerignore"}
DAST_INPUTS = (
    "media/", "processing/", "legacy/", "media_engine/", "runtime_support/", "delivery/",
    "contracts/", "app/", "frontend/", "tests/contracts/", "compose/local/",
    "tests/media/test_contract_security.py", "tests/processing/test_contracts.py",
    "tests/publisher/test_https.py", "scripts/dev/runtime.py", "scripts/dev/tls.py",
    "docker-compose.yml", "docker-compose.processing.yml", "nginx.conf",
    "deploy/media.Dockerfile", "deploy/processing.Dockerfile", "deploy/nginx/",
    "deploy/nginx-tls/", "deploy/dast/", "deploy/minio/", "deploy/postgres/",
)
LEGACY_INPUTS = {
    "app": ("app/", "migrations/", "Dockerfile", "alembic.ini"),
    "processing": (
        "processing/",
        "legacy/",
        "media_engine/",
        "contracts/",
        "delivery/",
        "runtime_support/",
        "deploy/processing.Dockerfile",
    ),
    "media": (
        "media/",
        "legacy/",
        "contracts/",
        "delivery/",
        "runtime_support/",
        "deploy/media.Dockerfile",
    ),
}
DOC_SUFFIXES = {".md", ".txt", ".pdf", ".png", ".jpg", ".jpeg", ".svg", ".tldr"}
PLANNING_INPUTS = {
    "docs/execution/aws/v1/backlog.json",
    "docs/execution/aws/v1/github-map.json",
    "docs/execution/aws/v1/price-sources.json",
}


def matches(path, entries):
    return any(
        path.startswith(entry) if entry.endswith("/") else path == entry for entry in entries
    )


def image_inputs(path):
    common = path in COMMON_IMAGE_INPUTS
    return (
        common or matches(path, V1_INPUTS),
        {name for name, inputs in LEGACY_INPUTS.items() if common or matches(path, inputs)},
    )


def classify(paths, *, full=False, reason="routine dev PR", source_sha="", base_sha=""):
    """None means unavailable diff; [] is a proven empty diff, never the same thing."""
    selected = {lane: False for lane in LANES}
    selected["policy-checks"] = True
    reasons = [reason]
    images = set()

    def select(*lanes):
        for lane in lanes:
            selected[lane] = True

    if paths is None:
        full, reason = True, "diff unavailable/unreadable: conservative full verification"
        reasons.append(reason)
    for path in paths or []:
        if not path or path.startswith("/") or ".." in PurePosixPath(path).parts:
            full = True
            reasons.append(f"invalid path: {path!r}")
            continue
        if (
            path.startswith((".github/", "scripts/ci/", "tests/ci/"))
            or path in COMMON_IMAGE_INPUTS
            or path in {"Makefile", ".python-version", "sonar-project.properties"}
            or path.endswith(("package.json", "package-lock.json"))
        ):
            full = True
            reasons.append(f"workflow/dependency/policy input: {path}")
            continue
        v1_images, legacy_images = image_inputs(path)
        if matches(path, DAST_INPUTS):
            select("dast")
        if v1_images:
            select("images")
        images.update(legacy_images)
        if legacy_images:
            select("security")
        if path in PLANNING_INPUTS or path.startswith("docs/execution/aws/v1/prices/"):
            select("planning")
        elif path.startswith("scripts/planning/"):
            select("planning", "lint-and-unit")
        elif path.startswith(("media/", "tests/media/")):
            select("lint-and-unit", "media-integration", "v1_offline", "v1_live")
            # Both legacy.media_peer.app and the Lambda facade import this package.
            select("browser-trust", "publisher-https")
        elif path.startswith("legacy/"):
            # The retired local stack: ships only in the legacy images, never in a V1 image.
            select("lint-and-unit", "media-integration", "processing-intake")
            select("browser-trust", "publisher-https")
        elif path.startswith(("processing/", "tests/processing/")):
            select("lint-and-unit", "processing-intake", "v1_offline", "v1_live", "browser-trust")
        elif path.startswith(
            (
                "media_engine/",
                "runtime_support/",
                "delivery/",
                "contracts/",
                "tests/media_engine/",
                "tests/runtime_support/",
                "tests/delivery/",
            )
        ):
            select(
                "lint-and-unit",
                "legacy-integration",
                "processing-intake",
                "media-integration",
                "publisher-https",
                "browser-trust",
                "v1_offline",
                "v1_live",
            )
        elif path.startswith(("app/", "migrations/")) or path in {"alembic.ini", "Dockerfile"}:
            select("lint-and-unit", "legacy-integration", "browser-trust")
        elif path.startswith("frontend/"):
            select("frontend", "browser-trust", "v1_offline", "v1_live")
        elif path.startswith(("publisher/", "tests/publisher/")):
            select("lint-and-unit", "publisher-https", "browser-trust", "v1_live")
        elif path.startswith("tests/integration/"):
            select("lint-and-unit")
            name = PurePosixPath(path).name
            if name.startswith("test_media_"):
                select("media-integration")
            elif name.startswith("test_processing_") or name == "test_database_ownership.py":
                select("processing-intake")
            else:
                select("legacy-integration", "processing-intake", "media-integration")
        elif path.startswith("tests/contracts/"):
            select(
                "lint-and-unit",
                "media-integration",
                "processing-intake",
                "browser-trust",
                "v1_offline",
                "v1_live",
            )
        elif path.startswith(("tests/v1/", "tests/aws/", "scripts/aws/")):
            select("lint-and-unit", "v1_offline")
            if path.startswith("tests/v1/"):
                select("v1_live")
        elif path.startswith("scripts/dev/v1_"):
            select("lint-and-unit", "v1_offline", "v1_live")
        elif path.startswith(("scripts/dev/", "tests/dev/", "tests/e2e/", "scripts/evidence/")):
            select(
                "lint-and-unit",
                "legacy-integration",
                "processing-intake",
                "media-integration",
                "publisher-https",
                "browser-trust",
                "v1_offline",
                "v1_live",
            )
        elif (
            PurePosixPath(path).parent == PurePosixPath("tests")
            and (
                PurePosixPath(path).name.startswith("test_")
                or PurePosixPath(path).name == "conftest.py"
            )
            and path.endswith(".py")
        ):
            select("lint-and-unit", "legacy-integration", "browser-trust")
        elif path.startswith(("deploy/v1/", "deploy/v1-local/", "deploy/aws/")):
            select("lint-and-unit", "v1_offline", "v1_live")
        elif path.startswith(
            (
                "deploy/dast/",
                "deploy/postgres/",
                "deploy/nginx/",
                "deploy/nginx-tls/",
                "deploy/minio/",
                "compose/local/",
            )
        ) or path in {
            "deploy/media.Dockerfile",
            "deploy/processing.Dockerfile",
            "docker-compose.yml",
            "docker-compose.processing.yml",
            "nginx.conf",
            ".env.example",
        }:
            select(
                "lint-and-unit",
                "legacy-integration",
                "media-integration",
                "processing-intake",
                "publisher-https",
                "browser-trust",
            )
        elif (
            path.startswith(("docs/", "project-documentation/", "project-roadmap/"))
            and PurePosixPath(path).suffix in DOC_SUFFIXES
        ) or path in {"README.md", "AGENTS.md", "CLAUDE.md", "HANDOFF.md", "LICENSE"}:
            pass
        else:
            full = True
            reasons.append(f"unclassified input: {path}")
            continue
        reasons.append(f"classified: {path}")
    if full:
        selected = dict.fromkeys(LANES, True)
        images = set(IMAGE_RECIPES)
    matrix = [
        {"name": name, "file": IMAGE_RECIPES[name][0], "tag": IMAGE_RECIPES[name][1]}
        for name in sorted(images)
    ]
    return {
        "mode": "full" if full else "dev",
        "selected": selected,
        "reasons": reasons,
        "source_sha": source_sha,
        "base_sha": base_sha,
        "paths": paths,
        # A nonempty fallback prevents an invalid empty Actions matrix on a skipped job.
        "security_matrix": {
            "include": matrix or [{"name": "app", "file": "Dockerfile", "tag": "flickpond-api:ci"}]
        },
    }


def git(*args):
    return subprocess.run(["git", *args], check=True, capture_output=True, timeout=30).stdout


def changed_paths(base, candidate):
    """Compare the intended base to the tested merge commit, not base...PR head."""
    ancestor = git("merge-base", base, candidate).decode().strip()
    # --no-renames represents a rename as delete + add, so BOTH owners are selected.
    raw = git("diff", "--name-only", "--no-renames", "-z", ancestor, candidate, "--")
    return [name.decode("utf-8", errors="strict") for name in raw.split(b"\0") if name]


def event_selection(event_name, event, source_sha, candidate_sha=""):
    if event_name == "workflow_dispatch":
        if (
            not re.fullmatch(r"[0-9a-fA-F]{40}", candidate_sha)
            or candidate_sha.lower() != source_sha
        ):
            raise ValueError(
                "Full dispatch requires candidate_sha equal to the dispatched ref's exact SHA"
            )
        return True, "explicit exact-candidate full dispatch", ""
    if event_name == "pull_request":
        pr = event.get("pull_request", {})
        base = pr.get("base", {})
        return (
            base.get("ref") != "dev/v1-integration",
            f"PR base {base.get('ref', 'unknown')}; tested merge {source_sha}",
            base.get("sha", ""),
        )
    return True, f"{event_name}: full verification at {source_sha}", ""


def expected_jobs(plan, scope):
    if set(plan["selected"]) != set(LANES) or plan["mode"] not in {"dev", "full"}:
        raise ValueError("Invalid selection schema")
    if any(type(value) is not bool for value in plan["selected"].values()):
        raise ValueError("Selections must be booleans")
    if plan["mode"] == "full" and not all(plan["selected"].values()):
        raise ValueError("Full mode cannot deselect a lane")
    selected = plan["selected"]
    result = {job: selected[job] for job in LANES if job not in V1_LANES}
    result["v1-local"] = any(selected[lane] for lane in V1_LANES)
    if scope == "dev":
        for advisory in ("security", "dast", "coverage-gate"):
            result.pop(advisory)
    return result


def validate_gate(plan, needs, scope):
    """Only deselected jobs may skip. Cancellation is never an intentional skip."""
    errors = []
    if needs.get("classify", {}).get("result") != "success":
        errors.append("classify did not succeed")
    for job, requested in expected_jobs(plan, scope).items():
        actual = needs.get(job, {}).get("result", "missing")
        if actual != ("success" if requested else "skipped"):
            errors.append(f"{job}: requested={requested}, result={actual}")
    return errors


def emit(plan):
    output = os.environ.get("GITHUB_OUTPUT")
    if output:
        values = {
            "mode": plan["mode"],
            "plan": json.dumps(plan, separators=(",", ":")),
            "source_sha": plan["source_sha"],
            "security_matrix": json.dumps(plan["security_matrix"]),
        }
        values.update(
            {key.replace("-", "_"): str(value).lower() for key, value in plan["selected"].items()}
        )
        values["v1"] = str(any(plan["selected"][lane] for lane in V1_LANES)).lower()
        with open(output, "a") as stream:
            for key, value in values.items():
                stream.write(f"{key}={value}\n")
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a") as stream:
            stream.write(
                f"### CI policy: {plan['mode']}\n\nTested source: `{plan['source_sha']}`\n\n"
            )
            stream.write(
                "Selected lanes: " + ", ".join(k for k, v in plan["selected"].items() if v)
            )
            stream.write("\n\n" + "\n".join(f"- {reason}" for reason in plan["reasons"]) + "\n")
            stream.write(
                "\nDev gate excludes advisory scans and full combined coverage. "
                "Full verification requires both. Cloud acceptance remains separate.\n"
            )
    print(json.dumps(plan, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("classify", "gate"))
    parser.add_argument("--scope", choices=("dev", "full"), default="dev")
    args = parser.parse_args()
    if args.action == "gate":
        plan = json.loads(os.environ["CI_PLAN"])
        needs = json.loads(os.environ["CI_NEEDS"])
        errors = validate_gate(plan, needs, args.scope)
        if errors:
            raise SystemExit("\n".join(errors))
        print(f"{args.scope} aggregate: all requested jobs succeeded; only declared skips accepted")
        return
    source = git("rev-parse", "HEAD").decode().strip()
    if source != os.environ["GITHUB_SHA"]:
        raise SystemExit("Checkout differs from event SHA; refusing mixed-source evidence")
    event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text())
    full, reason, base = event_selection(
        os.environ["GITHUB_EVENT_NAME"], event, source, os.environ.get("CANDIDATE_SHA", "")
    )
    paths = None
    if not full:
        try:
            paths = changed_paths(base, source) if base else None
        except (subprocess.SubprocessError, UnicodeError):
            pass  # An unreadable diff selects full, never empty/docs-only.
    plan = classify(
        paths if not full else [], full=full, reason=reason, source_sha=source, base_sha=base
    )
    plan.update(
        run_id=os.environ.get("GITHUB_RUN_ID", ""),
        run_attempt=os.environ.get("GITHUB_RUN_ATTEMPT", ""),
        event=os.environ["GITHUB_EVENT_NAME"],
        head_sha=event.get("pull_request", {}).get("head", {}).get("sha", source),
    )
    emit(plan)


if __name__ == "__main__":
    main()
