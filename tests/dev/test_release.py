"""Offline safety/lifecycle tests; these do not claim the integrated V4 experiment."""

import copy
import hashlib
import http.cookiejar
import importlib.util
import json
import os
import subprocess
import sys
import time
import urllib.error
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("dc2_release", ROOT / "scripts/dev/release.py")
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)
OLD = "sha256:" + "a" * 64
GOOD = "sha256:" + "b" * 64
BAD = "sha256:" + "c" * 64
SOURCE = {"revision": "1" * 40, "source_fingerprint": "2" * 64}
MEDIA = {
    "media": [{"container_id": "media-cid", "image_id": OLD, "revision": "old"}],
    "media-recovery": [{"container_id": "media-recovery-cid", "image_id": OLD}],
    "migration_revisions": ["media_01"],
}


def report(image=GOOD, vulnerabilities=None):
    return {
        "Metadata": {"ImageID": image},
        "Results": [{"Class": "os-pkgs", "Vulnerabilities": vulnerabilities or []}],
    }


def prior_proof(image=OLD):
    return {
        "image_id": image,
        **SOURCE,
        "fast_tests": {**SOURCE, "passed_at": release.utcnow()},
        "artifact_test": {"image_id": image},
        "scan": {"image_id": image, "fixable_high_critical": 0},
        "smoke": {"passed_at": release.utcnow()},
    }


@pytest.fixture
def runner(tmp_path, monkeypatch):
    def configure(run_id, root):
        directory = root / ".local/runs" / run_id
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / "runtime.env"
        path.write_text("PRIVATE_TOKEN=never-record-this\n")
        return {"PRIVATE_TOKEN": "never-record-this"}, {
            "env_file": str(path),
            "compose_project": "dc2-release-isolated",
            "public_url": "https://localhost:43123",
            "ca_file": str(directory / "ca.crt"),
        }

    monkeypatch.setattr(release.runtime, "configure", configure)
    monkeypatch.setattr(
        release.runtime, "subprocess_env", lambda: {"DOCKER_HOST": "unix:///offline/docker.sock"}
    )
    return release.Runner("offline", root=tmp_path)


def arrange(runner, monkeypatch, *, failed_image=None, failed_smoke=False):
    """Mock external boundaries; run the real journal/promotion/rollback state machine."""
    state = {"live": OLD, "applied": [], "scanned": [], "tests": 0, "smokes": 0}
    state["recovery_starts"] = []
    monkeypatch.setattr(
        runner, "compose", lambda *a, **kw: state["recovery_starts"].append((a, kw)) or ""
    )
    monkeypatch.setattr(runner, "source", lambda: dict(SOURCE))
    monkeypatch.setattr(runner, "local_preflight", lambda: {"cpus": 8})
    monkeypatch.setattr(runner, "media_snapshot", lambda: copy.deepcopy(MEDIA))
    monkeypatch.setattr(runner, "revisions", lambda service: [service + "_01"])

    def containers(service):
        count = 3 if service == "worker" else 1
        return [{"image_id": state["live"], "container_id": service + str(i)} for i in range(count)]

    monkeypatch.setattr(runner, "containers", containers)
    monkeypatch.setattr(
        runner, "image_info", lambda image: {"image_id": image, **SOURCE, "injection": None}
    )

    def tests(source):
        state["tests"] += 1
        runner.operation["fast_tests"] = {**source, "passed_at": release.utcnow()}

    monkeypatch.setattr(runner, "tests", tests)

    def build(source, bad_from=None):
        image = BAD if bad_from else GOOD
        runner.operation["build"] = {"image_id": image, **source, "derived_from": bad_from}
        return image

    monkeypatch.setattr(runner, "build", build)
    monkeypatch.setattr(runner, "artifact_test", lambda image: {"image_id": image})

    def scan(image):
        state["scanned"].append(image)
        return release.clean_scan(report(image), image)

    monkeypatch.setattr(runner, "scan", scan)
    monkeypatch.setattr(runner, "migration_check", lambda *args: None)
    monkeypatch.setattr(runner, "drain", lambda: None)

    def apply(image, workers, *, migrate):
        # Observe recovery intent on disk at the actual mutation boundary.
        disk = json.loads(runner.journal_path.read_text())
        assert disk["pending"]["previous"] in disk["tested_images"]
        assert workers == 3
        state["applied"].append((image, migrate))
        state["live"] = image
        if image == failed_image:
            raise release.ReleaseError("candidate health failed")

    monkeypatch.setattr(runner, "apply", apply)

    def smoke():
        state["smokes"] += 1
        if failed_smoke and state["live"] == GOOD:
            raise release.ReleaseError("public smoke HTTP 503")
        return {"passed_at": release.utcnow(), "fixture_sha256": "fixture"}

    monkeypatch.setattr(runner, "smoke", smoke)
    return state


@pytest.mark.parametrize("image", ["latest", "processing:tag", "sha256:short", GOOD.upper(), None])
def test_mutable_or_invalid_image_rejected(image):
    with pytest.raises(release.ReleaseError, match="immutable"):
        release.override(image)


@pytest.mark.parametrize("severity", ["HIGH", "CRITICAL"])
def test_fixable_scan_findings_block_exact_candidate(severity):
    with pytest.raises(release.ReleaseError, match="fixable"):
        release.clean_scan(
            report(vulnerabilities=[{"Severity": severity, "FixedVersion": "1.2"}]), GOOD
        )


def test_unfixable_high_is_permitted_and_scan_is_exact_artifact():
    proof = release.clean_scan(
        report(vulnerabilities=[{"Severity": "HIGH", "FixedVersion": ""}]), GOOD
    )
    assert proof["fixable_high_critical"] == 0
    assert proof["image_id"] == GOOD
    with pytest.raises(release.ReleaseError, match="exact image"):
        release.clean_scan(report(OLD), GOOD)
    with pytest.raises(release.ReleaseError, match="no package"):
        release.clean_scan({"Metadata": {"ImageID": GOOD}, "Results": []}, GOOD)
    with pytest.raises(release.ReleaseError, match="operating system"):
        release.clean_scan(
            {"Metadata": {"ImageID": GOOD}, "Results": [{"Class": "lang-pkgs"}]}, GOOD
        )


def test_success_promotes_exact_image_and_persists_only_processing(runner, monkeypatch):
    state = arrange(runner, monkeypatch)
    assert runner.release() == 0
    assert runner.journal["current"] == GOOD
    assert runner.journal["previous"] == OLD
    assert runner.journal["pending"] is None
    assert state["applied"] == [(GOOD, True)]
    assert state["scanned"] == [OLD, GOOD]
    assert runner.operation["status"] == "promoted"
    assert runner.operation["elapsed_seconds"] < 600
    overrides = json.loads(runner.persisted.read_text())["services"]
    assert set(overrides) == set(release.IMAGE_SERVICES)
    assert all(value == {"image": GOOD, "pull_policy": "never"} for value in overrides.values())
    assert runner.persisted.stat().st_mode & 0o777 == 0o600
    assert "never-record-this" not in runner.journal_path.read_text()
    release.require_tested(runner.journal["tested_images"][GOOD], GOOD)


@pytest.mark.parametrize("at_apply", [True, False])
def test_failed_candidate_rolls_back_prior_immutable_and_returns_nonzero(
    runner, monkeypatch, at_apply
):
    state = arrange(
        runner, monkeypatch, failed_image=GOOD if at_apply else None, failed_smoke=not at_apply
    )
    assert runner.release() == 2
    assert state["applied"] == [(GOOD, True), (OLD, False)]
    assert state["live"] == OLD
    assert runner.journal["current"] == OLD
    assert runner.operation["status"] == "failed_rolled_back"
    assert runner.operation["rollback"]["smoke"]
    assert GOOD not in runner.journal["tested_images"]
    assert runner.journal["pending"] is None
    assert json.loads(runner.persisted.read_text())["services"]["worker"]["image"] == OLD


def test_failed_security_gate_cannot_stop_workers_or_change_persisted_override(runner, monkeypatch):
    state = arrange(runner, monkeypatch)
    runner.persisted.write_text(json.dumps(release.override(OLD)))
    original = runner.persisted.read_bytes()

    def scan(image):
        if image == GOOD:
            raise release.ReleaseError("Trivy found fixable HIGH/CRITICAL vulnerabilities")
        return release.clean_scan(report(image), image)

    monkeypatch.setattr(runner, "scan", scan)
    monkeypatch.setattr(runner, "drain", lambda: pytest.fail("drain before scan gate"))
    assert runner.release() == 1
    assert state["applied"] == []
    assert runner.persisted.read_bytes() == original
    assert runner.operation["status"] == "rejected"
    assert runner.operation["finished_at"]


def test_build_failure_retains_baseline_and_reports_failed_step(runner, monkeypatch):
    state = arrange(runner, monkeypatch)
    monkeypatch.setattr(
        runner,
        "build",
        lambda *a, **kw: (_ for _ in ()).throw(
            subprocess.TimeoutExpired(["docker", "build", "secret-output"], 1, output="private")
        ),
    )
    assert runner.release() == 1
    assert state["applied"] == []
    assert runner.operation["failure"] == "TimeoutExpired"
    step = next(step for step in runner.operation["steps"] if step["name"] == "build")
    assert step["status"] == "failed" and step["finished_at"]
    assert "secret-output" not in runner.journal_path.read_text()
    assert "private" not in runner.journal_path.read_text()


def test_rollback_failure_keeps_durable_recovery_intent(runner, monkeypatch):
    state = arrange(runner, monkeypatch, failed_image=GOOD)
    actual_apply = runner.apply

    def fail_restore(image, workers, *, migrate):
        if image == OLD:
            raise release.ReleaseError("retained image unavailable")
        return actual_apply(image, workers, migrate=migrate)

    monkeypatch.setattr(runner, "apply", fail_restore)
    assert runner.release() == 3
    assert runner.operation["status"] == "recovery_required"
    assert runner.journal["pending"]["previous"] == OLD
    assert not runner.persisted.exists()
    before = list(state["applied"])
    assert runner.release() == 1
    assert state["applied"] == before


def test_manual_rollback_uses_journal_after_restart_and_never_migrates(runner, monkeypatch):
    arrange(runner, monkeypatch)
    assert runner.release() == 0
    restarted = release.Runner("offline", root=runner.root)
    state = arrange(restarted, monkeypatch)
    state["live"] = GOOD
    assert restarted.rollback() == 0
    assert state["applied"] == [(OLD, False)]
    assert restarted.journal["previous"] == GOOD
    assert restarted.operation["limit_seconds"] == 600


def test_interrupted_transition_is_recoverable_without_running_workers(runner, monkeypatch):
    arrange(runner, monkeypatch)
    runner.journal["tested_images"][OLD] = prior_proof()
    runner.journal["pending"] = {
        "previous": OLD,
        "candidate": BAD,
        "workers": 3,
        "media": MEDIA,
        "operation_id": "crashed",
    }
    runner.save()
    restarted = release.Runner("offline", root=runner.root)
    state = arrange(restarted, monkeypatch)
    monkeypatch.setattr(restarted, "containers", lambda *a: pytest.fail("workers may be stopped"))
    assert restarted.rollback() == 0
    assert state["applied"] == [(OLD, False)]
    assert restarted.journal["pending"] is None


def test_expired_promotion_budget_still_allocates_bounded_restore(runner, monkeypatch):
    state = arrange(runner, monkeypatch)
    original = runner.apply

    def expire(image, workers, *, migrate):
        if image == GOOD:
            runner.deadline = time.monotonic() - 1
            raise release.ReleaseError("overall operation deadline exceeded")
        assert 0 < runner.remaining() <= release.ROLLBACK_SECONDS
        return original(image, workers, migrate=migrate)

    monkeypatch.setattr(runner, "apply", expire)
    assert runner.release() == 2
    assert state["live"] == OLD


def test_media_change_cannot_be_reported_as_successful_rollback(runner, monkeypatch):
    arrange(runner, monkeypatch)
    snapshots = iter(
        [
            copy.deepcopy(MEDIA),
            {**MEDIA, "migration_revisions": ["changed"]},
            {**MEDIA, "migration_revisions": ["changed"]},
        ]
    )
    monkeypatch.setattr(runner, "media_snapshot", lambda: next(snapshots))
    assert runner.release() == 3
    assert runner.journal["pending"] is not None
    assert runner.operation["status"] == "recovery_required"


def test_evidence_distinguishes_expected_failure_from_release_success(runner, monkeypatch):
    arrange(runner, monkeypatch, failed_image=BAD)
    assert runner.evidence() == 0
    evidence = json.loads(next(runner.directory.glob("experiment-*.json")).read_text())
    assert evidence["bad_release_exit"] == 2
    assert evidence["restored_image"] == GOOD
    assert evidence["status"] == "passed"
    assert runner.journal["operations"][-1]["status"] == "failed_rolled_back"


def test_evidence_rejects_an_injected_candidate_that_never_reaches_deployment(runner, monkeypatch):
    arrange(runner, monkeypatch)
    scan = runner.scan
    monkeypatch.setattr(
        runner,
        "scan",
        lambda image: (
            (_ for _ in ()).throw(release.ReleaseError("scan unavailable"))
            if image == BAD
            else scan(image)
        ),
    )
    assert runner.evidence() == 1
    evidence = json.loads(next(runner.directory.glob("experiment-*.json")).read_text())
    assert evidence["status"] == "failed"
    assert evidence["bad_release_exit"] == 1


@pytest.mark.parametrize(
    "change,allowed",
    [
        ("A\tprocessing/migrations/versions/02.py\n", True),
        ("M\tprocessing/migrations/versions/01.py\n", False),
        ("D\tprocessing/migrations/versions/01.py\n", False),
    ],
)
def test_only_new_reviewed_migrations_are_permitted(runner, monkeypatch, change, allowed):
    runner.begin("test", 30)
    monkeypatch.setattr(runner, "command", lambda *args: change)
    with pytest.raises(release.ReleaseError, match="additive"):
        runner.migration_check(SOURCE, SOURCE, False)
    if allowed:
        runner.migration_check(SOURCE, SOURCE, True)
    else:
        with pytest.raises(release.ReleaseError, match="additive"):
            runner.migration_check(SOURCE, SOURCE, True)


def test_dirty_source_or_source_changed_during_tests_is_rejected(runner, monkeypatch):
    runner.begin("test", 30)

    def command(args, **kwargs):
        if args[1] == "rev-parse":
            return SOURCE["revision"]
        return " M processing/worker.py\n"

    monkeypatch.setattr(runner, "command", command)
    with pytest.raises(release.ReleaseError, match="commit"):
        runner.source()
    monkeypatch.setattr(runner, "command", lambda *a, **kw: "")
    monkeypatch.setattr(runner, "source", lambda: {**SOURCE, "revision": "changed"})
    with pytest.raises(release.ReleaseError, match="source changed"):
        runner.tests(SOURCE)


def test_drain_observes_last_claim_and_visible_failure_with_grace60(runner, monkeypatch):
    runner.begin("test", 600)
    initial = {
        "id": "one",
        "state": "processing",
        "finished": False,
        "job_status": "processing",
        "has_error": False,
        "deleted": False,
    }
    last = {**initial, "id": "two"}
    active = iter([[initial], [last]])
    monkeypatch.setattr(runner, "active_attempts", lambda: next(active))
    seen = []
    calls = []
    monkeypatch.setattr(runner, "compose", lambda *a, **kw: calls.append((a, kw)))
    terminal = [
        {**row, "state": "failed", "finished": True, "job_status": "failed", "has_error": True}
        for row in (initial, last)
    ]

    def states(ids):
        seen.extend(ids)
        return terminal

    monkeypatch.setattr(runner, "attempt_states", states)
    runner.drain()
    assert seen == ["one", "two"]
    assert calls[0][0] == ("stop", "--timeout", "60", "worker")
    assert runner.operation["drain"]["attempts_after"] == terminal


def test_drain_cannot_hide_interruption_as_requeued(runner, monkeypatch):
    runner.begin("test", 600)
    clock = [1000.0]
    monkeypatch.setattr(release.time, "monotonic", lambda: clock[0])
    runner.deadline = 1600
    row = {
        "id": "one",
        "state": "abandoned",
        "finished": True,
        "job_status": "queued",
        "has_error": True,
        "deleted": False,
    }
    monkeypatch.setattr(runner, "active_attempts", lambda: [row])
    monkeypatch.setattr(runner, "attempt_states", lambda ids: [row])
    monkeypatch.setattr(runner, "compose", lambda *a, **kw: None)
    monkeypatch.setattr(
        release.time, "sleep", lambda seconds: clock.__setitem__(0, clock[0] + seconds)
    )
    with pytest.raises(release.ReleaseError, match="five minutes"):
        runner.drain()
    assert clock[0] == 1300


def test_compose_apply_is_processing_only_without_build_pull_or_dependencies(runner, monkeypatch):
    runner.begin("test", 600)
    calls = []
    monkeypatch.setattr(runner, "compose", lambda *a, **kw: calls.append((a, kw)))
    monkeypatch.setattr(
        runner,
        "containers",
        lambda service: [{"image_id": GOOD} for _ in range(3 if service == "worker" else 1)],
    )
    runner.apply(GOOD, 3, migrate=True)
    assert calls[0][0] == ("run", "--rm", "--no-deps", "--pull", "never", "processing-migrate")
    assert calls[1][0][-3:] == release.SERVICES
    assert "--no-build" in calls[1][0] and "--no-deps" in calls[1][0]
    assert "worker=3" in calls[1][0]
    assert all(call[1]["image"] == GOOD for call in calls)


def test_compose_override_order_and_timeout_use_runtime_helper(runner, monkeypatch):
    runner.begin("test", 600)
    release.atomic_json(runner.persisted, release.override(OLD))
    calls = []

    def compose(state, *args, **kwargs):
        calls.append((state, args, kwargs))
        return SimpleNamespace(stdout="ok")

    monkeypatch.setattr(release.runtime, "compose", compose)
    assert runner.compose("up", image=GOOD, cap=12) == "ok"
    _, args, kwargs = calls[0]
    assert args[0:2] == ("-f", str(runner.persisted))
    assert json.loads(Path(args[3]).read_text())["services"]["worker"]["image"] == GOOD
    assert args[-1] == "up" and kwargs["timeout"] <= 12


def test_owned_db_diagnostics_never_send_secret_values_or_use_postgres_admin(runner, monkeypatch):
    runner.begin("test", 30)
    calls = []
    monkeypatch.setattr(runner, "compose", lambda *a, **kw: calls.append((a, kw)) or "[]")
    runner.revisions = lambda service: None
    runner.diagnostic("processing", "SELECT version_num FROM alembic_version")
    runner.diagnostic("media", "SELECT version_num FROM alembic_version")
    assert calls[0][0] == ("exec", "-T", "processing-recovery", "python", "-")
    assert "PROCESSING_POSTGRES_DSN" in calls[0][1]["input"]
    assert "MEDIA_POSTGRES_DSN" not in calls[0][1]["input"]
    assert "MEDIA_POSTGRES_DSN" in calls[1][1]["input"]
    assert "never-record-this" not in repr(calls)


def test_shared_trivy_binary_cache_are_offline_and_wrong_version_is_rejected(runner, monkeypatch):
    runner.begin("test", 30)
    shared = runner.root / "common"
    binary = shared / ".local/trivy/trivy"
    binary.parent.mkdir(parents=True)
    binary.touch()
    monkeypatch.setattr(release.runtime, "common_root", lambda root: shared)
    calls = []

    def command(args, **kwargs):
        calls.append(args)
        return json.dumps({"Version": "0.75.0"}) if "--version" in args else json.dumps(report())

    monkeypatch.setattr(runner, "command", command)
    assert runner.scan(GOOD)["image_id"] == GOOD
    assert calls[1][0] == str(binary)
    assert str(shared / ".cache/trivy") in calls[1]
    assert "--skip-db-update" in calls[1] and "--offline-scan" in calls[1]
    assert calls[1][-1] == GOOD
    monkeypatch.setattr(runner, "command", lambda *a, **kw: '{"Version":"wrong"}')
    with pytest.raises(release.ReleaseError, match="0.75.0"):
        runner.scan(GOOD)


def test_lock_prevents_concurrent_release_and_atomic_journal_is_private(runner):
    with runner.locked():
        other = release.Runner("offline", root=runner.root)
        with pytest.raises(release.ReleaseError, match="another release"):
            with other.locked():
                pytest.fail("lock acquired twice")
        runner.begin("test", 30)
    assert runner.journal_path.stat().st_mode & 0o777 == 0o600
    assert not list(runner.directory.glob("tmp*"))


def test_process_group_timeout_is_bounded_and_redacts_child_output(runner, monkeypatch):
    runner.begin("test", 30)
    monkeypatch.setattr(release.runtime, "subprocess_env", lambda: os.environ.copy())
    started = time.monotonic()
    code = (
        "import subprocess,sys,time; "
        "subprocess.Popen([sys.executable,'-c','import time; time.sleep(30)']); "
        "time.sleep(30)"
    )
    with pytest.raises(release.ReleaseError, match="command deadline"):
        runner.command([sys.executable, "-c", code], cap=0.05)
    assert time.monotonic() - started < 2


def test_safe_command_evidence_records_hashes_without_child_env_output(runner, monkeypatch):
    runner.begin("test", 30)
    monkeypatch.setattr(release.runtime, "subprocess_env", lambda: os.environ.copy())
    assert runner.command([sys.executable, "-c", "print('secret from env')"]) == "secret from env\n"
    event = runner.operation["command_evidence"][0]
    assert event["stdout_sha256"] == hashlib.sha256(b"secret from env\n").hexdigest()
    # The test command is intentionally not secret-bearing; runtime commands never
    # put credentials in argv. Output itself must not be retained.
    assert "stdout" not in event and "stderr" not in event


def test_bad_artifact_uses_retained_id_and_preserves_python_future_imports(runner, monkeypatch):
    runner.begin("test", 600)
    calls = []
    monkeypatch.setattr(runner, "command", lambda *a, **kw: calls.append((a, kw)) or "")
    monkeypatch.setattr(runner, "image_info", lambda image: {"image_id": BAD, **SOURCE})
    assert runner.build(SOURCE, bad_from=GOOD) == BAD
    dockerfile = calls[0][1]["input"]
    assert dockerfile.startswith("FROM " + GOOD + "\n")
    instruction = next(line for line in dockerfile.splitlines() if line.startswith("RUN "))
    argv = json.loads(instruction[4:])
    assert argv[0:2] == ["python", "-c"]
    assert "p.read_text()+" in argv[2]
    assert "p.write_text('import" not in argv[2]
    assert "dc2.release.build-id=" + runner.operation["id"] in calls[0][0][0]


def test_cli_help_exposes_only_local_actions():
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts/dev/release.py"), "--help"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert "{release,rollback,evidence}" in result.stdout
    assert "--run-id" in result.stdout
    assert "--additive-migrations" in result.stdout


def arrange_http(runner, monkeypatch, *, job_statuses=None, output_url=None, http_failure=None):
    """Exercise the real HTTP smoke body with controlled responses, never network."""
    runner.begin("http-test", 600)
    calls = []
    handlers_seen = []
    asset = "12345678-1234-1234-1234-123456789abc"
    capability = (
        output_url or runner.state["public_url"] + "/output.mp4?X-Amz-Signature=private-url"
    )
    statuses = iter(job_statuses or ["queued", "processing", "done"])
    monkeypatch.setattr(
        release.ssl,
        "create_default_context",
        lambda **kw: calls.append(("tls", kw)) or SimpleNamespace(verify_mode="required"),
    )

    class Reply:
        def __init__(self, status, body):
            self.status = status
            self.body = body

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def read(self, limit):
            return self.body

    class Opener:
        def open(self, request, timeout):
            path = release.urlsplit(request.full_url).path
            calls.append((request.method, path, request.headers, request.data, timeout))
            if http_failure == path:
                raise urllib.error.HTTPError(request.full_url, 503, "private-message", {}, None)
            if path == "/api/auth/login":
                jar = handlers_seen[0].cookiejar
                jar.set_cookie(
                    http.cookiejar.Cookie(
                        0,
                        "access_token",
                        "private-cookie",
                        None,
                        False,
                        "localhost",
                        False,
                        False,
                        "/",
                        True,
                        True,
                        None,
                        True,
                        None,
                        None,
                        {},
                    )
                )
            if path == "/api/jobs/" + asset and request.method == "GET":
                return Reply(
                    200, json.dumps({"status": next(statuses), "output_url": capability}).encode()
                )
            if path == "/api/jobs/" + asset and request.method == "DELETE":
                return Reply(204, b"")
            if path == "/output.mp4":
                return Reply(200, b"video-output")
            if path == "/api/upload":
                return Reply(202, json.dumps({"job_id": asset}).encode())
            if path == "/api/auth/register":
                return Reply(201, b'{"id":"user"}')
            return Reply(200, b'{"status":"ok"}')

    def build_opener(*handlers):
        handlers_seen.extend(handlers)
        return Opener()

    monkeypatch.setattr(release.urllib.request, "build_opener", build_opener)
    monkeypatch.setattr(release.time, "sleep", lambda seconds: None)

    def command(args, **kwargs):
        if args[0] == "ffmpeg":
            Path(args[-1]).write_bytes(b"video-fixture")
            return ""
        assert args[0] == "ffprobe"
        return '{"streams":[{"codec_type":"video"}]}'

    monkeypatch.setattr(runner, "command", command)
    return calls, handlers_seen


def test_public_smoke_contract_tls_uuid_email_upload_process_playable_delete(runner, monkeypatch):
    from pydantic import EmailStr, TypeAdapter

    calls, _ = arrange_http(runner, monkeypatch)
    proof = release.public_smoke(runner)
    assert proof["output_sha256"] == hashlib.sha256(b"video-output").hexdigest()
    assert calls[0] == ("tls", {"cafile": runner.state["ca_file"]})
    registration = next(call for call in calls if call[1] == "/api/auth/register")
    credentials = json.loads(registration[3])
    assert credentials["email"].endswith("@example.com")
    assert TypeAdapter(EmailStr).validate_python(credentials["email"])
    upload = next(call for call in calls if call[1] == "/api/upload")
    assert b'name="file"' in upload[3] and b"video-fixture" in upload[3]
    assert "Idempotency-key" in upload[2]
    assert any(call[0] == "DELETE" for call in calls)
    assert all(call[4] <= 10 for call in calls if call[0] != "tls")
    serialized = json.dumps(proof)
    for private in (credentials["password"], "private-cookie", "X-Amz-Signature", "private-url"):
        assert private not in serialized


@pytest.mark.parametrize("failure,statuses", [("/api/upload", None), (None, ["failed"])])
def test_public_workflow_failures_are_visible_and_redact_capabilities(
    runner, monkeypatch, failure, statuses
):
    arrange_http(runner, monkeypatch, job_statuses=statuses, http_failure=failure)
    with pytest.raises(release.ReleaseError) as caught:
        release.public_smoke(runner)
    assert "private-" not in str(caught.value)
    assert "https://" not in str(caught.value)


def test_smoke_playback_and_redirects_cannot_leave_local_https(runner, monkeypatch):
    _, handlers = arrange_http(
        runner, monkeypatch, output_url="https://other-host.example.com/object?secret=1"
    )
    with pytest.raises(release.ReleaseError, match="outside"):
        release.public_smoke(runner)
    redirect = next(
        handler
        for handler in handlers
        if isinstance(handler, release.urllib.request.HTTPRedirectHandler)
    )
    with pytest.raises(release.ReleaseError, match="outside"):
        redirect.redirect_request(None, None, 307, "", {}, "https://example.com/private")


@pytest.mark.parametrize(
    "field", ["fast_tests", "scan", "artifact_test", "smoke", "source_fingerprint"]
)
def test_retained_image_without_every_exact_gate_cannot_be_used(field):
    proof = prior_proof()
    proof.pop(field)
    with pytest.raises(release.ReleaseError, match="rollback image"):
        release.require_tested(proof, OLD)


@pytest.mark.parametrize(
    "host,accepted",
    [
        ("unix:///local/docker.sock", True),
        ("ssh://remote-host", False),
        ("tcp://remote-host:2375", False),
    ],
)
def test_daemon_preflight_rejects_remote_targets(runner, monkeypatch, host, accepted):
    runner.begin("test", 30)
    monkeypatch.setattr(release.runtime, "subprocess_env", lambda: {"DOCKER_HOST": host})
    monkeypatch.setattr(
        runner,
        "command",
        lambda *a, **kw: json.dumps(
            {"NCPU": 8, "MemTotal": 8 * 1024**3, "Architecture": "aarch64"}
        ),
    )
    if accepted:
        assert runner.local_preflight()["cpus"] == 8
    else:
        with pytest.raises(release.ReleaseError, match="local Unix-socket"):
            runner.local_preflight()


def test_generated_bad_image_code_imports_but_fails_uvicorn_startup(runner, monkeypatch, tmp_path):
    runner.begin("test", 600)
    calls = []
    monkeypatch.setattr(runner, "command", lambda *a, **kw: calls.append((a, kw)) or "")
    monkeypatch.setattr(runner, "image_info", lambda image: {"image_id": BAD, **SOURCE})
    runner.build(SOURCE, bad_from=GOOD)
    instruction = next(
        line for line in calls[0][1]["input"].splitlines() if line.startswith("RUN ")
    )
    generated = json.loads(instruction[4:])[2]
    main = tmp_path / "main.py"
    main.write_text("from __future__ import annotations\napp = 'original-app'\n")
    exec(generated.replace("/app/processing/main.py", str(main)), {})
    content = compile(main.read_text(), str(main), "exec")
    monkeypatch.setattr(sys, "argv", ["python"])
    globals_ = {}
    exec(content, globals_)
    assert globals_["app"] == "original-app"
    monkeypatch.setattr(sys, "argv", ["/usr/local/bin/uvicorn"])
    with pytest.raises(SystemExit) as caught:
        exec(content, {})
    assert caught.value.code == 42


def test_manual_rollback_rejects_untested_target_before_stopping_workers(runner, monkeypatch):
    arrange(runner, monkeypatch)
    runner.journal["previous"] = OLD
    monkeypatch.setattr(runner, "drain", lambda: pytest.fail("must not stop workers"))
    assert runner.rollback() == 1
    assert runner.journal["pending"] is None
    assert runner.operation["status"] == "rejected"


def test_rollback_restores_retained_reaper_before_candidate_drain(runner, monkeypatch):
    state = arrange(runner, monkeypatch, failed_image=GOOD)

    def drain():
        if state["live"] == GOOD:
            args, kwargs = state["recovery_starts"][-1]
            assert args[-1] == "processing-recovery"
            assert "--no-deps" in args and "--no-build" in args
            assert kwargs["image"] == OLD
            assert runner.remaining() <= 300

    monkeypatch.setattr(runner, "drain", drain)
    assert runner.release() == 2
    names = [step["name"] for step in runner.operation["steps"]]
    assert names.index("rollback-recovery-start") < names.index("rollback-worker-drain")
    assert names.index("rollback-worker-drain") < names.index("rollback-apply")


def test_late_terminal_db_reply_cannot_pass_five_minute_drain(runner, monkeypatch):
    runner.begin("test", 600)
    clock = [1000.0]
    monkeypatch.setattr(release.time, "monotonic", lambda: clock[0])
    runner.deadline = 1600
    row = {
        "id": "one",
        "state": "processing",
        "finished": False,
        "job_status": "processing",
        "has_error": False,
        "deleted": False,
    }
    monkeypatch.setattr(runner, "active_attempts", lambda: [row])
    monkeypatch.setattr(runner, "compose", lambda *a, **kw: None)

    def states(ids):
        clock[0] = 1301
        return [
            {**row, "state": "failed", "finished": True, "job_status": "failed", "has_error": True}
        ]

    monkeypatch.setattr(runner, "attempt_states", states)
    with pytest.raises(release.ReleaseError, match="five minutes"):
        runner.drain()
