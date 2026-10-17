"""The local VM helper: small by default, explicit for benchmarks, and never left unattended.

Nothing here boots, resizes or talks to a VM: Lima, Docker and the clock are replaced.
"""

import subprocess
from types import SimpleNamespace

import pytest

from scripts.dev import capacity

HOST = {"cpus": 10, "memory_gib": 32}
ME = {"user": "me", "host": "h", "worktree": "/work/a", "pid": 1}
OTHER = {"user": "you", "host": "h", "worktree": "/work/b", "pid": 2}


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setattr(capacity, "LIMA_HOME", tmp_path / "lima")
    monkeypatch.setattr(capacity, "LEASE", tmp_path / "lima/d-lease.json")
    monkeypatch.setattr(capacity, "CACHE", tmp_path / "cache")
    monkeypatch.setattr(capacity, "current_owner", lambda: ME)
    return tmp_path


def request(**kwargs):
    values = {"cpus": None, "memory_gib": None, "benchmark": False, "host": HOST}
    return capacity.resolve_request(**{**values, **kwargs})


def write_yaml(home, cpus, memory):
    folder = home / "lima/d"
    folder.mkdir(parents=True)
    (folder / "lima.yaml").write_text(f'cpus: {cpus}\nmemory: "{memory}"\ndisk: 64GiB\n')


def test_default_request_is_two_cpus_and_two_gib_never_the_benchmark_size():
    chosen = request()
    assert (chosen["profile"], chosen["cpus"], chosen["memory_gib"]) == ("default", 2, 2)


def test_large_profile_is_only_chosen_by_the_explicit_benchmark_flag():
    chosen = request(benchmark=True)
    assert (chosen["profile"], chosen["cpus"], chosen["memory_gib"]) == ("benchmark", 8, 8)


@pytest.mark.parametrize("name", ["cpus", "memory_gib"])
def test_sizes_above_the_default_budget_are_refused_with_the_flag_to_use(name):
    with pytest.raises(SystemExit, match="--benchmark"):
        request(**{name: 3})


@pytest.mark.parametrize("value", [0, -1])
def test_non_positive_sizes_are_rejected(value):
    with pytest.raises(SystemExit, match="at least 1"):
        request(cpus=value)


def test_a_benchmark_that_would_starve_the_host_is_refused():
    with pytest.raises(SystemExit, match="headroom"):
        request(benchmark=True, host={"cpus": 4, "memory_gib": 32})
    with pytest.raises(SystemExit, match="headroom"):
        request(benchmark=True, host={"cpus": 16, "memory_gib": 12})


def test_existing_smaller_instance_keeps_its_size_when_a_default_start_is_requested(home):
    write_yaml(home, 1, "1GiB")
    persisted = capacity.persisted_resources()
    kept = capacity.effective_resources(request(), persisted)
    assert (kept["cpus"], kept["memory_gib"]) == (1, 1)
    assert "kept" in kept["source"]


def test_existing_instance_is_not_grown_by_an_explicit_larger_request(home):
    write_yaml(home, 2, "2GiB")
    with pytest.raises(SystemExit, match="not resized implicitly"):
        grown = request(benchmark=True, cpus=4)
        capacity.effective_resources(grown, capacity.persisted_resources())


def test_persisted_memory_in_mib_is_converted_and_missing_instance_is_none(home):
    assert capacity.persisted_resources() is None
    write_yaml(home, 2, "1536MiB")
    assert capacity.persisted_resources()["memory_gib"] == 1.5


def test_provenance_records_the_size_actually_used_not_a_constant(home):
    capacity.CACHE.mkdir(parents=True)
    (capacity.CACHE / "provenance.json").write_text('{"cpus": 8, "memory_gib": 8}')
    capacity.write_instance_record({"profile": "default", "cpus": 2, "memory_gib": 2})
    recorded = capacity.json.loads((capacity.CACHE / "provenance.json").read_text())
    assert recorded["instance"]["cpus"] == 2 and "cpus" not in recorded


def test_default_lease_expires_and_is_flagged_after_its_time(home):
    lease = capacity.make_lease(120, keep_alive=False, resources={}, now=1000, owner=ME)
    assert lease["expires_at"] == 1000 + 7200
    assert capacity.lease_state(lease, 1001) == "ACTIVE"
    assert capacity.lease_state(lease, 1000 + 7200) == "EXPIRED"
    assert capacity.lease_state(None, 1) == "NONE"


def test_long_leases_need_keep_alive_and_are_still_bounded(home):
    with pytest.raises(SystemExit, match="--keep-alive"):
        capacity.make_lease(600, keep_alive=False, resources={}, now=0, owner=ME)
    assert capacity.make_lease(600, keep_alive=True, resources={}, now=0, owner=ME)["keep_alive"]
    with pytest.raises(SystemExit):
        capacity.make_lease(24 * 60 + 1, keep_alive=True, resources={}, now=0, owner=ME)


def test_a_second_worktree_joins_an_active_lease_without_shortening_it(home):
    first = capacity.make_lease(120, keep_alive=False, resources={}, now=0, owner=ME)
    joined = capacity.make_lease(
        10, keep_alive=False, resources={}, now=60, owner=OTHER, existing=first
    )
    assert joined["expires_at"] == first["expires_at"]
    assert {o["worktree"] for o in joined["owners"]} == {"/work/a", "/work/b"}


def test_another_tasks_unexpired_lease_protects_its_vm_from_stop_but_expiry_does_not(home):
    theirs = capacity.make_lease(30, keep_alive=False, resources={}, now=0, owner=OTHER)
    assert not capacity.may_stop(theirs, ME, 10, force=False)
    assert capacity.may_stop(theirs, ME, 10, force=True)
    assert capacity.may_stop(theirs, ME, 31 * 60, force=False)
    mine = capacity.make_lease(30, keep_alive=False, resources={}, now=0, owner=ME)
    assert capacity.may_stop(mine, ME, 10, force=False)
    shared = capacity.make_lease(30, keep_alive=False, resources={}, now=0, owner=ME, existing=mine)
    shared = capacity.make_lease(
        30, keep_alive=False, resources={}, now=0, owner=OTHER, existing=shared
    )
    assert not capacity.may_stop(shared, ME, 10, force=False)


def test_status_reports_without_starting_or_calling_docker_when_the_vm_is_stopped(
    home, monkeypatch, capsys
):
    calls = []
    monkeypatch.setattr(capacity, "run", lambda *a, **k: calls.append(a))
    monkeypatch.setattr(capacity, "instance_state", lambda *a: "Stopped")
    outcome = capacity.status({}, home / "limactl")
    assert calls == [] and outcome["state"] == "Stopped"
    assert "not running" in capsys.readouterr().out


def test_status_flags_a_running_vm_with_an_expired_lease_without_stopping_it(
    home, monkeypatch, capsys
):
    stopped = []
    capacity.write_lease(
        capacity.make_lease(1, keep_alive=False, resources={}, now=0, owner=OTHER)
    )
    monkeypatch.setattr(capacity, "instance_state", lambda *a: "Running")
    monkeypatch.setattr(capacity, "run", lambda *a, **k: None)
    monkeypatch.setattr(capacity, "stop_instance", lambda *a: stopped.append(a))
    outcome = capacity.status({}, home / "limactl")
    assert outcome["expired_but_running"] and stopped == []
    assert "capacity-reap" in capsys.readouterr().out


def test_reap_stops_only_a_running_vm_whose_lease_has_expired(home, monkeypatch):
    stopped = []
    monkeypatch.setattr(capacity, "stop_instance", lambda *a: stopped.append(a))
    monkeypatch.setattr(capacity.time, "time", lambda: 5000)
    states = iter(["Running", "Running", "Running", "Stopped"])
    monkeypatch.setattr(capacity, "instance_state", lambda *a: next(states))
    live = capacity.make_lease(120, keep_alive=False, resources={}, now=4000, owner=OTHER)
    capacity.write_lease(live)
    capacity.reap({}, home / "limactl")
    assert stopped == []  # unexpired
    capacity.LEASE.unlink()
    capacity.reap({}, home / "limactl")
    assert stopped == []  # untracked: flagged by status, not ours to stop
    capacity.write_lease(capacity.make_lease(1, keep_alive=False, resources={}, now=0, owner=OTHER))
    capacity.reap({}, home / "limactl")
    assert len(stopped) == 1  # expired
    capacity.reap({}, home / "limactl")
    assert len(stopped) == 1  # already stopped: nothing to do


class Job:
    """Drives run_job with a fake start/stop and a scripted command outcome."""

    def __init__(self, monkeypatch, *, started, outcome):
        self.stops = []
        monkeypatch.setattr(capacity, "start", lambda *a: started)
        monkeypatch.setattr(capacity, "stop_instance", lambda *a: self.stops.append(a))

        def command(*a, **k):
            if isinstance(outcome, BaseException):
                raise outcome
            return SimpleNamespace(returncode=outcome)

        monkeypatch.setattr(capacity.subprocess, "run", command)

    def run(self, keep_alive=False):
        args = SimpleNamespace(command=["true"], lease_minutes=5, keep_alive=keep_alive)
        return capacity.run_job(args, {}, "limactl", "image")


@pytest.mark.parametrize(
    "outcome",
    [0, 3, subprocess.TimeoutExpired("x", 1), KeyboardInterrupt()],
    ids=["success", "failure", "timeout", "cancellation"],
)
def test_a_job_that_started_the_vm_stops_it_however_the_job_ends(monkeypatch, outcome):
    job = Job(monkeypatch, started=True, outcome=outcome)
    if isinstance(outcome, BaseException):
        with pytest.raises(type(outcome)):
            job.run()
    else:
        assert job.run() == outcome
    assert len(job.stops) == 1


def test_a_job_never_stops_a_vm_it_did_not_start_or_one_with_a_keep_alive_lease(monkeypatch):
    shared = Job(monkeypatch, started=False, outcome=0)
    shared.run()
    assert shared.stops == []
    demo = Job(monkeypatch, started=True, outcome=0)
    demo.run(keep_alive=True)
    assert demo.stops == []


def test_run_without_a_command_is_refused_before_anything_starts(monkeypatch):
    job = Job(monkeypatch, started=True, outcome=0)
    with pytest.raises(SystemExit, match="command"):
        capacity.run_job(SimpleNamespace(command=[], lease_minutes=5, keep_alive=False), {}, 1, 2)
    assert job.stops == []
