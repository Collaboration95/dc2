"""Controlled fault and supervisor regressions; no Docker, network or browser."""

import json
import subprocess
import sys
from types import SimpleNamespace

import pytest

from scripts.dev import e2e_clients, runtime, verify
from scripts.dev.scenario import ServiceGuard, ServiceRestoreError
from scripts.evidence import recovery


class ControlledStack:
    def __init__(self):
        self.counts = {
            "worker": 3,
            "processing-recovery": 1,
            "processing": 1,
            "media-recovery": 1,
            "media": 1,
        }
        self.active = self.counts.copy()
        self.calls = []
        self.events = []
        self.injection_error = None
        self.restore_failures = set()

    def compose(self, state, *args, **kwargs):
        assert state["compose_project"] == "controlled-only"
        assert 0 < kwargs["timeout"] <= 75
        self.calls.append(args)
        service = args[-1]
        if args[0] == "ps":
            rows = [
                {"Service": service, "State": "running" if i < self.active[service] else "exited"}
                for i in range(self.counts[service])
            ]
            return SimpleNamespace(stdout=json.dumps(rows))
        if args[0] in ("stop", "kill"):
            # Mutate only the first named service, then fail before finishing.
            selected = args[3] if args[0] == "kill" else args[1]
            self.active[selected] = 0
            if self.injection_error is not None:
                raise self.injection_error
            return SimpleNamespace(stdout="")
        assert args[:7] == ("up", "-d", "--no-deps", "--no-build", "--pull", "never", "--scale")
        assert args[7] == f"{service}={self.counts[service]}"
        if service in self.restore_failures:
            raise subprocess.TimeoutExpired("controlled-restore", kwargs["timeout"])
        self.active[service] = self.counts[service]
        return SimpleNamespace(stdout="")

    def record(self, event, **values):
        self.events.append({"event": event, **values})

    def guard(self, *services):
        return ServiceGuard({"compose_project": "controlled-only"}, services, self.record)


@pytest.fixture
def stack(monkeypatch):
    stack = ControlledStack()
    monkeypatch.setattr(runtime, "compose", stack.compose)
    monkeypatch.setattr(recovery, "compose", stack.compose)
    monkeypatch.setattr(e2e_clients, "compose", stack.compose)
    return stack


@pytest.mark.parametrize(
    "error", [RuntimeError("partial mutation"), subprocess.TimeoutExpired("controlled-stop", 1)]
)
def test_mutation_then_injection_failure_restores_every_service(stack, error):
    stack.injection_error = error
    with pytest.raises(type(error)) as caught, stack.guard("worker", "processing-recovery"):
        stack.compose(
            {"compose_project": "controlled-only"},
            "stop",
            "worker",
            "processing-recovery",
            timeout=1,
        )
    assert caught.value is error
    assert stack.active == stack.counts
    outcome = stack.events[-1]
    assert outcome["original_failure_type"] == type(error).__name__
    assert all(row["status"] == "PASS" for row in outcome["outcomes"])
    assert outcome["outcomes"][0]["expected_replicas"] == 3


def test_failed_restore_preserves_original_failure_and_attempts_other_services(stack):
    original = AssertionError("original acceptance failure")
    stack.restore_failures.add("worker")
    with pytest.raises(AssertionError) as caught, stack.guard("worker", "processing-recovery"):
        stack.active["worker"] = stack.active["processing-recovery"] = 0
        raise original
    assert caught.value is original
    assert stack.active["processing-recovery"] == 1
    assert "restoration failed" in original.__notes__[0]
    assert [row["status"] for row in stack.events[-1]["outcomes"]] == ["FAIL", "PASS"]
    assert stack.events[-1]["outcomes"][0]["failure_type"] == "TimeoutExpired"


def test_failed_restore_without_original_failure_fails_the_run(stack):
    stack.restore_failures.add("worker")
    with pytest.raises(ServiceRestoreError), stack.guard("worker"):
        stack.active["worker"] = 0
    assert stack.events[-1]["outcomes"][0]["status"] == "FAIL"


def test_guard_refuses_stopped_baseline_before_any_mutation(stack):
    stack.active["worker"] = 2
    with pytest.raises(ServiceRestoreError), stack.guard("worker"):
        pytest.fail("Guard admitted mixed baseline")
    assert all(args[0] == "ps" for args in stack.calls)


@pytest.mark.parametrize(
    "workflow,services",
    [
        (recovery.worker_kill, ("worker",)),
        (recovery.queue_loss, ("worker", "processing-recovery")),
        (recovery.processing_outage, ("processing", "media-recovery", "media")),
        (e2e_clients.browser_workflow, ("worker",)),
    ],
)
def test_callable_workflow_arms_guard_before_fault(
    stack, tmp_path, monkeypatch, workflow, services
):
    error = subprocess.TimeoutExpired("controlled-injection", 1)
    stack.injection_error = error
    scenario = SimpleNamespace(
        state={"compose_project": "controlled-only", "public_url": "https://controlled.invalid"},
        artifacts=tmp_path,
        run_id="controlled-only",
        restore_services=stack.guard,
        account=lambda _: (object(), {"id": "owner"}, {}),
        upload=lambda *a: {"job_id": "asset"},
        wait=lambda *a, **kw: None,
        processing_job=lambda *a: {"current_attempt": {"attempt_id": "attempt"}},
        client=lambda: object(),
        request=lambda *a, **kw: None,
    )
    if workflow is e2e_clients.browser_workflow:
        from contextlib import nullcontext

        page_events = []
        page = SimpleNamespace(
            set_default_timeout=lambda _: None,
            on=lambda event, callback: page_events.append(event),
            goto=lambda *a, **kw: None,
            evaluate=lambda _: True,
        )
        monkeypatch.setattr(e2e_clients, "fixture", lambda *a, **kw: None)
        monkeypatch.setattr(e2e_clients, "browser_login", lambda *a: None)
        monkeypatch.setattr(
            e2e_clients,
            "trusted_browser",
            lambda _: nullcontext(SimpleNamespace(new_page=lambda: page)),
        )
    with pytest.raises(subprocess.TimeoutExpired) as caught:
        if workflow is e2e_clients.browser_workflow:
            workflow(scenario)
        else:
            workflow(scenario, tmp_path / "controlled.mp4")
    assert caught.value is error
    if workflow is e2e_clients.browser_workflow:
        assert "requestfinished" in page_events and "response" not in page_events
    assert stack.active == stack.counts
    assert tuple(row["service"] for row in stack.events[-1]["outcomes"]) == services
    fault_index = next(i for i, args in enumerate(stack.calls) if args[0] in ("stop", "kill"))
    assert all(args[0] == "ps" for args in stack.calls[:fault_index])


@pytest.mark.parametrize("ignore_term", [False, True])
def test_outer_timeout_restores_original_worker_replicas_when_child_cannot_finalize(
    stack,
    tmp_path,
    monkeypatch,
    ignore_term,
):
    mutation = tmp_path / "worker-count"
    mutation.write_text("3")
    cleanup = tmp_path / "child-finally"
    monkeypatch.setattr(verify, "ROOT", tmp_path)
    monkeypatch.setattr(verify, "configure", lambda _: ({}, {"compose_project": "controlled-only"}))
    compose = stack.compose

    def controlled_compose(state, *args, **kwargs):
        stack.active["worker"] = int(mutation.read_text())
        result = compose(state, *args, **kwargs)
        mutation.write_text(str(stack.active["worker"]))
        return result

    monkeypatch.setattr(runtime, "compose", controlled_compose)
    code = (
        "import signal,time; from pathlib import Path\n"
        + ("signal.signal(signal.SIGTERM,signal.SIG_IGN)\n" if ignore_term else "")
        + f"Path({str(mutation)!r}).write_text('0')\n"
        + "try:\n    time.sleep(60)\nfinally:\n"
        + f"    Path({str(cleanup)!r}).write_text('ran')\n"
    )
    with pytest.raises(subprocess.TimeoutExpired):
        verify.supervised_e2e(
            "controlled", timeout=0.5, command=[sys.executable, "-c", code], grace=0.1
        )
    assert not cleanup.exists(), "Child finally must be bypassed in this regression"
    assert mutation.read_text() == "3"
    report = json.loads(next((tmp_path / "artifacts/controlled").glob("*.json")).read_text())
    assert report["status"] == "FAIL" and report["failure_type"] == "TimeoutExpired"
    restore = report["events"][-1]
    assert restore["original_failure_type"] == "TimeoutExpired"
    assert restore["outcomes"] == [
        {"service": "worker", "expected_replicas": 3, "running_replicas": 3, "status": "PASS"}
    ]
    assert {args[-1] for args in stack.calls} == {"worker"}


def test_supervisor_preserves_child_failure_and_records_restoration(stack, tmp_path, monkeypatch):
    monkeypatch.setattr(verify, "ROOT", tmp_path)
    monkeypatch.setattr(verify, "configure", lambda _: ({}, {"compose_project": "controlled-only"}))
    with pytest.raises(SystemExit) as caught:
        verify.supervised_e2e("controlled", command=[sys.executable, "-c", "raise SystemExit(7)"])
    assert caught.value.code == 7
    report = json.loads(next((tmp_path / "artifacts/controlled").glob("*.json")).read_text())
    assert report["status"] == "FAIL"
    assert report["events"][-1]["outcomes"][0]["status"] == "PASS"


@pytest.mark.parametrize("unavailable", [False, True])
def test_restart_readiness_tolerates_transport_failure_and_restores_on_deadline(
    stack, monkeypatch, tmp_path, unavailable
):
    import httpx

    now = [0.0]
    health = []
    cases = []
    requests = []

    def sleep(seconds):
        now[0] += seconds

    monkeypatch.setattr(recovery, "time", SimpleNamespace(monotonic=lambda: now[0], sleep=sleep))
    original = recovery.command

    def command(scenario, *args, **kwargs):
        if args == ("restart", "media"):
            return SimpleNamespace(stdout="")
        return original(scenario, *args, **kwargs)

    monkeypatch.setattr(recovery, "command", command)

    def get(path, *, timeout):
        assert path == "health"
        assert 0 < timeout <= min(1.0, 30 - now[0])
        health.append(timeout)
        if unavailable or len(health) == 1:
            raise httpx.ConnectError("controlled readiness refusal")
        return SimpleNamespace(status_code=200)

    def request(*args, **kwargs):
        requests.append(args)
        return {"status": "queued", "submission_status": "pending"}

    assets = iter(("completed", "pending", "pending"))
    scenario = SimpleNamespace(
        state={"compose_project": "controlled-only"},
        account=lambda _: (SimpleNamespace(get=get), {}, {}),
        upload=lambda *args: {"job_id": next(assets)},
        wait=lambda *args, **kwargs: None,
        restore_services=stack.guard,
        request=request,
        record=lambda *args, **kwargs: None,
        passed=lambda case, detail: cases.append(case),
    )
    if unavailable:
        with pytest.raises(TimeoutError, match="Media did not restart"):
            recovery.processing_outage(scenario, tmp_path / "controlled.mp4")
        assert now[0] == 30
        assert cases == []
        # Pending/replay/convergence assertions were not retried or reached.
        assert len(requests) == 2
    else:
        recovery.processing_outage(scenario, tmp_path / "controlled.mp4")
        assert len(health) == 2
        assert cases == ["CT-13", "CT-14"]
    assert stack.active == stack.counts
    assert all(row["status"] == "PASS" for row in stack.events[-1]["outcomes"])
    assert stack.events[-1]["original_failure_type"] == ("TimeoutError" if unavailable else None)
