"""Static guards for the V1 image recipes; the executed proof is deploy/v1/build_and_verify.py.

No Docker is needed here. These keep the three Dockerfiles, the pyproject extras, the deployed
template and the retained local evidence from drifting apart between image builds.
"""

import importlib.util
import json
import re
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
RECIPES = {
    o: (ROOT / f"deploy/v1/{o}.Dockerfile").read_text() for o in ("media", "processing", "worker")
}
API = ("media", "processing")
LEGACY_SERVER = {"uvicorn", "uvloop", "httptools", "watchfiles", "websockets", "pyyaml", "click"}
TEMPLATE = json.loads((ROOT / "deploy/aws/v1/template.json").read_text())


def load_verifier():
    spec = importlib.util.spec_from_file_location(
        "v1_build_and_verify", ROOT / "deploy/v1/build_and_verify.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_recipes_share_one_digest_pinned_base_and_stamp_the_source_revision():
    bases = {re.search(r"^FROM (\S+)", text, re.M).group(1) for text in RECIPES.values()}
    assert len(bases) == 1 and "@sha256:" in bases.pop()
    for text in RECIPES.values():
        assert "ARG SOURCE_SHA" in text
        assert "org.opencontainers.image.revision=$SOURCE_SHA" in text


@pytest.mark.parametrize("owner", RECIPES)
def test_recipe_installs_only_the_owners_locked_extra_with_hashes(owner):
    text = RECIPES[owner]
    assert f"--extra v1-{owner}" in text
    assert "--require-hashes" in text and "--frozen" in text and "--no-dev" in text
    assert "legacy" not in text.replace("legacy compose", "")
    for package in LEGACY_SERVER:
        assert f"--no-emit-package {package}" in text


def test_v1_extras_exclude_the_queue_stack_which_only_the_legacy_extra_carries():
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]
    extras = project["optional-dependencies"]
    queue = ("redis", "rq")

    def names(requirements):
        return {re.split(r"[<>=\[ ]", item, maxsplit=1)[0] for item in requirements}

    assert names(project["dependencies"]).isdisjoint(queue)
    for extra in ("v1-media", "v1-processing", "v1-worker"):
        assert names(extras[extra]).isdisjoint(queue)
    assert set(queue) <= names(extras["legacy"])


@pytest.mark.parametrize("owner", RECIPES)
def test_recipe_runs_the_runtime_gate_offline_before_dropping_privileges(owner):
    text = RECIPES[owner]
    kind = "finite-worker" if owner == "worker" else "lambda-api"
    gate = f"RUN --network=none python /opt/check_runtime.py {kind} {owner}"
    assert gate in text
    assert text.index(gate) < text.index("USER flickpond") < text.index("ENTRYPOINT")


def test_ffmpeg_is_installed_only_in_the_worker_image():
    assert "ffmpeg" in RECIPES["worker"]
    assert all("ffmpeg" not in RECIPES[owner] for owner in API)


@pytest.mark.parametrize("owner", API)
def test_lambda_images_use_the_runtime_client_and_precompile_bytecode(owner):
    text = RECIPES[owner]
    assert 'ENTRYPOINT ["python", "-m", "awslambdaric"]' in text
    # Lambda's filesystem is read-only: bytecode missing from the image costs every cold start.
    assert "--compile-bytecode" in text and "compileall" in text
    default = {
        "media": "media.lambda_handler.handler",
        "processing": "processing.lambda_handler.handler",
    }
    assert f'CMD ["{default[owner]}"]' in text


def test_template_handlers_resolve_to_callables_in_the_owning_source():
    functions, _ = load_verifier().template_contract()
    assert len(functions) == 10  # nine V1 handlers plus the opt-in launcher (#68)
    for name, function in functions.items():
        module, _, attribute = function["handler"].rpartition(".")
        path = ROOT / (module.replace(".", "/") + ".py")
        assert path.is_file(), name
        assert path.parts[len(ROOT.parts)] == function["owner"], name
        assert re.search(rf"\b{attribute}\b", path.read_text()), name
        assert (ROOT / function["owner"]).is_dir() and function["memory_mb"] >= 512


def test_worker_image_carries_the_bootstrap_script_the_template_task_executes():
    _, tasks = load_verifier().template_contract()
    bootstrap = tasks["BootstrapTaskDefinition"]
    assert bootstrap["owner"] == "worker"
    target = bootstrap["entrypoint"][-1]
    assert f"COPY scripts/aws/v1/bootstrap.py {target}" in RECIPES["worker"]
    assert (ROOT / "scripts/aws/v1/bootstrap.py").is_file()
    assert all(target not in RECIPES[owner] for owner in API)


def test_migration_tasks_point_at_alembic_configs_the_api_images_copy():
    _, tasks = load_verifier().template_contract()
    for name, owner in (
        ("MediaMigrationTaskDefinition", "media"),
        ("ProcessingMigrationTaskDefinition", "processing"),
    ):
        task = tasks[name]
        assert task["owner"] == owner
        config = task["command"][task["command"].index("-c") + 1]
        assert config == f"{owner}/alembic.ini" and (ROOT / config).is_file()
        assert f"COPY {owner} ./{owner}" in RECIPES[owner]


def test_verifier_policy_forbids_every_distribution_the_recipes_exclude():
    verifier = load_verifier()
    assert {"redis", "rq", *LEGACY_SERVER} <= verifier.FORBIDDEN_EVERYWHERE
    assert verifier.PLATFORM == "linux/amd64"


def _invocation(function_error, message=None, *, seconds=1.0, body=None):
    if body is None:
        body = {"errorType": function_error, "errorMessage": message}
    return {"body": body, "function_error": function_error, "seconds": seconds}


@pytest.mark.parametrize(
    "result",
    [
        _invocation("ConnectionRefusedError", "[Errno 111] refused"),
        _invocation("OSError", "unreachable"),
        _invocation("TimeoutError", "timed out"),
        _invocation("SanitizedHandlerError", "media.repair failed (ConnectionRefusedError)"),
        _invocation("SanitizedHandlerError", "processing.ecs failed (OSError)"),
        _invocation("SanitizedHandlerError", "processing.s3 failed (TimeoutError)"),
        _invocation(None, body={"batchItemFailures": [{"itemIdentifier": "m1"}]}),
    ],
)
def test_database_down_accepts_a_retryable_connection_failure_raw_or_sanitized(result):
    assert load_verifier().database_down(result)


@pytest.mark.parametrize(
    "result",
    [
        _invocation("SanitizedHandlerError", "media.repair failed (KeyError)"),
        _invocation(
            "SanitizedHandlerError", "media.repair failed (ConnectionRefusedError) at 127.0.0.1:1"
        ),
        _invocation("SanitizedHandlerError", "ConnectionRefusedError"),
        _invocation("SanitizedHandlerError", "other.repair failed (OSError)"),
        _invocation("SanitizedHandlerError", "media.repair failed (OSError) unused"),
        _invocation("SanitizedHandlerError", "media.repair failed (OSError)", seconds=61),
        _invocation("ValueError", "media.repair failed (OSError)"),
        _invocation("SanitizedHandlerError", None, body="media.repair failed (OSError)"),
        _invocation(None, body={"statusCode": 200}),
    ],
)
def test_database_down_rejects_other_failures_and_green_results(result):
    assert not load_verifier().database_down(result)


EVIDENCE = sorted((ROOT / "docs/execution/aws/v1/evidence").glob("local-images-*.json"))


@pytest.mark.parametrize("path", EVIDENCE, ids=[p.name for p in EVIDENCE])
def test_retained_local_image_evidence_never_claims_cloud_or_registry_results(path):
    evidence = json.loads(path.read_text())
    assert evidence["scope"].lower().startswith("local")
    assert evidence["status"] == "LOCAL_ARTIFACT_PASS" and evidence["failures"] == []
    assert evidence["platform"] == "linux/amd64"
    assert (evidence["aws"], evidence["scan"], evidence["registry_manifest_receipt"]) == (
        "NOT_RUN",
    ) * 3
    assert evidence["promotion_eligible"] is False
    assert len(evidence["source_sha"]) == 40
    assert evidence["source_sha"].startswith(path.stem.rsplit("-", 1)[1])
    for owner, image in evidence["images"].items():
        assert image["config_id"].startswith("sha256:") and image["build_exit_code"] == 0
        assert (
            image["runtime_contents"]["redis"] is False and image["runtime_contents"]["rq"] is False
        )
        assert image["runtime_contents"]["ffmpeg"] is (owner == "worker")
