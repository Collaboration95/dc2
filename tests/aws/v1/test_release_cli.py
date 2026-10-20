"""Release CLI wiring and the real release hooks, against fakes; no AWS, no network."""

import io
import json
import time

import pytest
from test_session_operations import Cloud
from test_v1_release import NEW, proof
from v1_support import outputs

from scripts.aws.transport import OperationError
from scripts.aws.v1 import release_cli
from scripts.aws.v1.hooks import compatibility_from_evidence, owner_quiescence, schema_reader
from scripts.aws.v1.operations import config_from_outputs
from scripts.aws.v1.release_cli import main

SCOPE = ("--profile", "operator", "--region", "ap-southeast-1", "--account", "123456789012")
MIGRATION = "arn:aws:ecs:ap-southeast-1:123456789012:task-definition/migrate:3"
WORKER = "arn:aws:ecs:ap-southeast-1:123456789012:task-definition/worker:4"
CREDENTIALS = {"email": "smoke@example.invalid", "password": "correct horse battery"}


def private(path, data):
    path.write_text(json.dumps(data))
    path.chmod(0o600)
    return str(path)


@pytest.fixture
def files(tmp_path):
    base = tmp_path / "ops"
    base.mkdir(mode=0o700)
    (base / "outputs.json").write_text(json.dumps(outputs()))
    config = {
        "operator_station": "s",
        "environment_id": "e2e",
        "journal": str(base / "session.json"),
        "outputs_file": str(base / "outputs.json"),
        "sql": {
            "ca_file": str(base / "ca.pem"),
            "media_dsn_file": str(base / "media.dsn"),
            "processing_dsn_file": str(base / "processing.dsn"),
        },
    }
    paths = {
        "config": private(base / "config.json", config),
        "creds": private(base / "creds.json", CREDENTIALS),
        "compat": private(
            base / "compat.json",
            {
                "owner": "processing",
                "source_sha": "d" * 40,
                "target_revision": "0002",
                "additive_only": True,
                "current_image_compatible": True,
                "prior_image_compatible": True,
            },
        ),
        "bundle": private(
            base / "bundle.json",
            {
                "api": proof("processing", "lambda-api"),
                "worker": proof("processing", "finite-worker"),
            },
        ),
    }
    return paths


def promote_args(files, *extra, image=NEW):
    return [
        "promote",
        "--config",
        files["config"],
        *SCOPE,
        "--owner",
        "processing",
        "--bundle",
        files["bundle"],
        "--image-uri",
        image,
        "--migration-definition",
        MIGRATION,
        "--worker-definition",
        WORKER,
        "--target-revision",
        "0002",
        "--compat-evidence",
        files["compat"],
        "--smoke-url",
        "https://gw.example.invalid",
        "--smoke-credentials",
        files["creds"],
        *extra,
    ]


def run(argv, **kwargs):
    out = io.StringIO()
    code = main(argv, stdout=out, **kwargs)
    return code, json.loads(out.getvalue())


def test_dry_run_validates_artifact_pins_offline_and_prints_the_planned_calls(files):
    def forbidden(scope):
        raise AssertionError("dry-run must not build a live transport")

    code, out = run(promote_args(files, "--dry-run"), transport_factory=forbidden)
    assert code == 0 and out["result"]["digest"] == NEW.split("@")[1]
    steps = out["result"]["planned_calls"]
    operations = [s.get("operation") for s in steps]
    assert operations.index("run-task") < operations.index("update-function-code")
    assert operations.index("publish-version") < operations.index("update-alias")
    assert steps[-2]["step"] == "public-smoke" and steps[-1]["step"] == "peer-unchanged"
    assert {s["function"] for s in steps if s["step"] == "promote"} == {
        "fn-ProcessingApi",
        "fn-ProcessingCommands",
        "fn-ProcessingRepair",
        "fn-ProcessingEcsEvents",
        "fn-ProcessingS3Events",
    }


def test_dry_run_still_rejects_a_digest_that_differs_from_the_tested_bundle(files):
    code, out = run(promote_args(files, "--dry-run", image="repo@sha256:" + "f" * 64))
    assert code == 1 and "pin tested registry manifest" in out["error"]


@pytest.mark.parametrize("missing", ["--owner", "--bundle", "--image-uri", "--compat-evidence"])
def test_promote_requires_every_release_input(files, missing):
    argv = promote_args(files, "--dry-run")
    index = argv.index(missing)
    del argv[index : index + 2]
    with pytest.raises(SystemExit):
        main(argv)


@pytest.mark.parametrize("action", ["promote", "restore", "status"])
def test_release_cli_requires_explicit_profile_and_region(files, action):
    with pytest.raises(SystemExit):
        main([action, "--config", files["config"], "--region", "ap-southeast-1"])
    with pytest.raises(SystemExit):
        main(
            [
                action,
                "--config",
                files["config"],
                "--profile",
                "default",
                "--region",
                "ap-southeast-1",
                "--account",
                "123456789012",
            ]
        )


def test_live_promote_wires_real_hooks_and_reports_only_check_names(files, monkeypatch):
    seen = {}

    def fake_promote(config, transport, journal, **kwargs):
        seen.update(kwargs)
        assert kwargs["public_smoke"].base == "https://gw.example.invalid"
        return {"owner": kwargs["owner"], "status": "promoted"}

    monkeypatch.setattr(release_cli, "promote", fake_promote)
    code, out = run(promote_args(files), transport_factory=lambda scope: Cloud())
    assert code == 0 and out["result"]["status"] == "promoted"
    assert {"quiescent", "schema_revision", "public_smoke", "compatibility"} <= seen.keys()
    assert seen["worker_definition"] == WORKER and seen["target_revision"] == "0002"
    assert CREDENTIALS["password"] not in json.dumps(out)


def abandon_argv(files, *extra):
    return [
        "abandon",
        "--config",
        files["config"],
        *SCOPE,
        "--owner",
        "processing",
        "--migration-definition",
        MIGRATION,
        *extra,
    ]


def test_abandon_dry_run_prints_the_plan_and_touches_nothing(files):
    def forbidden(scope):
        raise AssertionError("dry-run must not build a live transport")

    code, out = run(abandon_argv(files, "--dry-run"), transport_factory=forbidden)
    assert code == 0 and out["result"]["planned_calls"][0]["operation"] == "get-alias"
    assert out["result"]["planned_calls"][-1]["journal"].endswith("abandoned_releases")


def test_abandon_gets_only_the_schema_and_quiescence_hooks_and_the_reason(files, monkeypatch):
    seen = {}

    def fake_abandon(config, transport, journal, **kwargs):
        seen.update(kwargs)
        return {"owner": "processing", "status": "abandoned", "versions_published_unaliased": []}

    monkeypatch.setattr(release_cli, "abandon", fake_abandon)
    argv = abandon_argv(
        files,
        "--reason",
        "migration failed",
        "--smoke-url",
        "https://gw.example.invalid",
        "--smoke-credentials",
        files["creds"],
    )
    code, out = run(argv, transport_factory=lambda scope: Cloud())
    assert code == 0 and out["result"]["status"] == "abandoned"
    assert set(seen) == {"schema_revision", "quiescent", "deadline", "reason"}
    assert seen["reason"] == "migration failed"
    assert out["result"]["schema_revision_source"] == "sql-station"


def test_abandon_without_a_journal_is_a_refusal_not_a_crash(files):
    argv = ["abandon", "--config", files["config"], *SCOPE]
    code, out = run(argv, transport_factory=lambda scope: Cloud())
    assert code == 1 and "journal" in out["error"]


def test_status_names_the_aliases_a_pending_release_already_moved(files):
    from scripts.aws.journal import Journal

    base = {
        "v1_request": {"owner": "processing"},
        "phase": "preparing",
        "versions": {},
        "moved": {"fn": {"version": "2"}},
    }
    path = json.loads(open(files["config"]).read())["journal"]
    journal = Journal(path, station="s", environment="e2e")
    journal.initialize(verified_empty=True, exclusive_station=True)
    with journal.locked() as state:
        state["pending_release"] = base
        journal.save(state)

    class Aliases(Cloud):
        def call(self, service, operation, payload, *, deadline):
            if operation == "get-alias":
                return {"FunctionVersion": "7", "RevisionId": "r"}
            return super().call(service, operation, payload, deadline=deadline)

    code, out = run(
        ["status", "--config", files["config"], *SCOPE], transport_factory=lambda scope: Aliases()
    )
    assert code == 0 and out["result"]["pending_release"]["moved"] == ["fn"]
    assert out["result"]["pending_release"]["migration_complete"] is False


def test_failed_live_promotion_reports_the_failing_smoke_checks_not_secrets(files, monkeypatch):
    def fake_promote(config, transport, journal, *, public_smoke, **kwargs):
        public_smoke.receipt = {"checks": {"login": "FAIL"}, "failures": ["login:401"]}
        raise OperationError("Release incomplete; private intent retained for restore")

    monkeypatch.setattr(release_cli, "promote", fake_promote)
    code, out = run(promote_args(files), transport_factory=lambda scope: Cloud())
    assert code == 1 and out["smoke"]["failures"] == ["login:401"]
    assert CREDENTIALS["password"] not in json.dumps(out)


def test_status_reads_aliases_and_summarizes_the_journal_intent(files):
    class Aliases(Cloud):
        def call(self, service, operation, payload, *, deadline):
            if operation == "get-alias":
                return {"FunctionVersion": "7", "RevisionId": "r"}
            return super().call(service, operation, payload, deadline=deadline)

    factory = lambda scope: Aliases()  # noqa: E731
    assert run(["status", "--config", files["config"], *SCOPE], transport_factory=factory)[0] == 1
    # The journal must be initialized deliberately before any release command reads it.
    from scripts.aws.v1 import session_cli

    out = io.StringIO()
    assert (
        session_cli.main(
            ["init", "--config", files["config"], *SCOPE, "--confirm-empty", "--confirm-exclusive"],
            stdout=out,
            transport_factory=factory,
        )
        == 0
    )
    code, out = run(["status", "--config", files["config"], *SCOPE], transport_factory=factory)
    assert code == 0 and out["result"]["pending_release"] is None
    assert {a["version"] for a in out["result"]["aliases"].values()} == {"7"}
    assert {a["owner"] for a in out["result"]["aliases"].values()} == {"media", "processing"}


# -- real hooks ---------------------------------------------------------------------------


def quiescence(**state):
    config, _, _ = config_from_outputs(outputs(), station="s", environment="e")
    cloud = Cloud(**state)
    return owner_quiescence(config, cloud), cloud, config


def test_owner_is_quiescent_only_when_its_consumers_rules_and_tasks_are_off():
    check, cloud, config = quiescence()
    deadline = time.monotonic() + 30
    assert check("processing", deadline=deadline) and check("media", deadline=deadline)
    cloud.mappings[config["owner_consumers"]["media"]["mappings"][0]] = "Enabled"
    assert check("media", deadline=deadline) is False
    assert check("processing", deadline=deadline) is True  # the peer is judged separately
    cloud.rules[config["owner_consumers"]["processing"]["schedules"][0]] = "ENABLED"
    assert check("processing", deadline=deadline) is False


def test_a_running_encoder_blocks_processing_quiescence_but_not_media():
    check, cloud, _ = quiescence()
    cloud.tasks["arn:t"] = {
        "taskArn": "arn:t",
        "taskDefinitionArn": "worker:1",
        "lastStatus": "RUNNING",
    }
    deadline = time.monotonic() + 30
    assert check("processing", deadline=deadline) is False
    assert check("media", deadline=deadline) is True
    cloud.tasks["arn:t"]["lastStatus"] = "STOPPED"
    assert check("processing", deadline=deadline) is True


def test_schema_revision_reads_exactly_one_head_over_verified_tls(tmp_path, monkeypatch):
    dsn = tmp_path / "dsn"
    dsn.write_text("postgresql://u:pw@host/db")
    dsn.chmod(0o600)
    monkeypatch.setattr("ssl.create_default_context", lambda **kw: object())
    rows = [("0002",)]

    class Connection:
        async def fetch(self, sql):
            assert sql == "SELECT version_num FROM alembic_version"
            return rows

        async def close(self):
            pass

    async def connect(dsn, **kwargs):
        assert kwargs["ssl"] is not None
        return Connection()

    read = schema_reader({"media": dsn}, "ca.pem", connect=connect)
    assert read("media", deadline=time.monotonic() + 5) == "0002"
    rows[:] = [("0001",), ("0002",)]
    with pytest.raises(OperationError, match="Exactly one"):
        read("media", deadline=time.monotonic() + 5)
    with pytest.raises(OperationError, match="No schema DSN"):
        read("processing", deadline=time.monotonic() + 5)


def test_compatibility_evidence_is_bound_to_owner_source_and_revision(tmp_path):
    bundle = {"api": {"source_sha": "d" * 40}}
    good = {
        "owner": "processing",
        "source_sha": "d" * 40,
        "target_revision": "0002",
        "additive_only": True,
        "current_image_compatible": True,
        "prior_image_compatible": True,
    }
    path = tmp_path / "evidence.json"

    def verdict(**override):
        path.write_text(json.dumps({**good, **override}))
        return compatibility_from_evidence(path)(
            "processing", {}, bundle, "0002", deadline=time.monotonic() + 5
        )

    assert verdict() is True
    for stale in (
        {"source_sha": "e" * 40},
        {"target_revision": "0001"},
        {"owner": "media"},
        {"additive_only": False},
        {"prior_image_compatible": False},
        {"prior_image_compatible": "yes"},
    ):
        assert verdict(**stale) is False
    path.write_text("not json")
    with pytest.raises(OperationError):
        compatibility_from_evidence(path)("processing", {}, bundle, "0002", deadline=1)
