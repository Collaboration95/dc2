"""#185: the backlog throughput mode of the capacity proof, against the simulated account.

The simulation is a rehearsal; none of this says anything about AWS. These tests pin the parts
that decide a verdict: the ratio arithmetic, where queue wait comes from, what counts as a
failure, and that no step ever leaves an encoder running.
"""

import argparse
import io
import json

import pytest

from scripts.aws.transport import OperationError
from scripts.aws.v1 import evidence
from scripts.aws.v1.proof import capacity, sim, summary, workflow
from scripts.aws.v1.proof.core import FAIL, PASS, ProofError, SessionRefused

pytestmark = pytest.mark.unmeasured


@pytest.fixture
def fixture(tmp_path):
    path = tmp_path / "fixture.mp4"
    path.write_bytes(b"\0" * 4096)
    return path


def build(tmp_path, *faults, **world):
    world.setdefault("encode_seconds", 150.0)
    args = argparse.Namespace(run_id="t", dry_run=True)
    return sim.build(
        args, session="open", world=sim.SimWorld(faults=faults, **world), tmp=tmp_path / "state"
    )


def statuses(proof):
    return {name: step["status"] for name, step in proof.doc["steps"].items()}


def public(proof, name):
    return proof.doc["steps"][name]["public"]


class Stub:
    """Just enough context for `refill`, which only stamps the first launch."""

    @staticmethod
    def wall():
        return 1_000.0


STUB = Stub()


def stopped(ctx):
    """Every task the harness started is STOPPED in the simulated account."""
    return bool(ctx.world.tasks) and all(
        ctx.world.task_view(t)["lastStatus"] == "STOPPED" for t in ctx.world.tasks.values()
    )


# ---- the arithmetic ---------------------------------------------------------------------
def test_jobs_per_minute_and_speedups_are_ratios_of_the_measured_rates():
    rates = {1: capacity.rate(6, 900.0), 2: capacity.rate(6, 500.0), 3: capacity.rate(6, 300.0)}
    assert rates[1] == pytest.approx(0.4)
    ratios = capacity.speedups(rates)
    assert ratios == {2: pytest.approx(1.8), 3: pytest.approx(3.0)}


def test_a_missing_rate_gives_no_ratio_rather_than_a_default():
    assert capacity.rate(0, 100.0) is None and capacity.rate(6, 0) is None
    assert capacity.speedups({1: None, 2: 0.5, 3: 0.7}) == {2: None, 3: None}
    assert capacity.speedups({1: 0.4, 2: None, 3: 0.9})[2] is None
    assert capacity.meets_targets({2: None, 3: None}) == {2: False, 3: False}


@pytest.mark.parametrize(
    ("ratio_2", "ratio_3", "expected"),
    [
        (1.6, 2.1, (True, True)),  # exactly on the target passes
        (1.5999, 2.1, (False, True)),  # just under fails, whatever it rounds to for display
        (1.9, 2.0999, (True, False)),
        (1.0, 1.0, (False, False)),
    ],
)
def test_the_targets_are_one_point_six_at_cap_two_and_two_point_one_at_cap_three(
    ratio_2, ratio_3, expected
):
    found = capacity.meets_targets({2: ratio_2, 3: ratio_3})
    assert (found[2], found[3]) == expected


def test_the_ideal_speedup_is_whole_rounds_of_the_cap():
    assert capacity.ideal_speedup(6, 2) == 2.0 and capacity.ideal_speedup(6, 3) == 3.0
    assert capacity.ideal_speedup(5, 3) == 2.5  # a ragged last round caps what is reachable


@pytest.mark.parametrize("size", [2, 13, 4])
def test_a_backlog_that_cannot_reach_the_targets_even_with_no_overhead_is_refused(size):
    with pytest.raises(ProofError):
        capacity.check_backlog(size)


@pytest.mark.parametrize("size", [5, 6, 12])
def test_reasonable_backlog_sizes_are_accepted(size):
    capacity.check_backlog(size)


# ---- queue wait comes from the attempt's own stamps ----------------------------------------
def job_doc(queued, started, finished, number=1):
    return {
        "current_attempt": {
            "number": number,
            "queued_at": queued,
            "started_at": started,
            "finished_at": finished,
        }
    }


def test_queue_wait_and_processing_time_are_differences_of_the_attempt_stamps():
    doc = job_doc(
        "2026-10-21T10:00:00.250000+00:00",
        "2026-10-21T10:01:30.750000+00:00",
        "2026-10-21T10:03:50.750000Z",
    )
    assert capacity.attempt_times(doc) == (90.5, 140.0, 1)


@pytest.mark.parametrize(
    "doc",
    [
        None,
        {},
        job_doc("2026-10-21T10:00:00Z", None, None),
        job_doc("2026-10-21T10:05:00Z", "2026-10-21T10:00:00Z", "2026-10-21T10:06:00Z"),  # negative
    ],
)
def test_a_missing_or_impossible_stamp_is_reported_as_missing_not_guessed(doc):
    wait, _, _ = capacity.attempt_times(doc)
    assert wait is None
    assert capacity.queue_stats([doc])["missing_queue_wait"] == 1


def test_queue_stats_counts_retried_jobs_and_keeps_only_real_samples():
    docs = [
        job_doc("2026-10-21T10:00:00Z", "2026-10-21T10:00:10Z", "2026-10-21T10:02:00Z"),
        job_doc("2026-10-21T10:00:00Z", "2026-10-21T10:00:50Z", None, number=2),
        None,
    ]
    stats = capacity.queue_stats(docs)
    assert stats["waits"] == [10.0, 50.0] and stats["runs"] == [110.0]
    assert (
        stats["retried_jobs"],
        stats["missing_queue_wait"],
        stats["missing_processing_time"],
    ) == (1, 1, 2)


def test_the_receipt_reports_server_side_processing_time_and_falling_queue_wait(tmp_path, fixture):
    proof = capacity.run_backlog(build(tmp_path), fixture=fixture)
    assert set(statuses(proof).values()) == {PASS}
    for cap in (1, 2, 3):
        assert public(proof, f"backlog-{cap}")["processing_median_seconds"] == 150.0
        assert public(proof, f"backlog-{cap}")["queue_wait_samples"] == 6
    compare = public(proof, "backlog-compare")
    waits = compare["median_queue_wait_seconds"]
    assert waits["1"] > waits["2"] > waits["3"] and compare["median_queue_wait_decreasing"]
    assert public(proof, "backlog-3")["queue_wait_p90_seconds"] >= waits["3"]


# ---- the comparison and its verdict ------------------------------------------------------
def test_a_clean_simulated_sweep_reports_measured_speedups_against_the_targets(tmp_path, fixture):
    proof = capacity.run_backlog(build(tmp_path), fixture=fixture)
    compare = public(proof, "backlog-compare")
    assert compare["meets_target"] == {"2": True, "3": True}
    assert compare["speedup"]["2"] > 1.6 and compare["speedup"]["3"] > 2.1
    assert compare["targets"] == {"2": 1.6, "3": 2.1}
    assert compare["ideal_speedup"] == {"2": 2.0, "3": 3.0}
    assert proof.overall() == "SIMULATED"  # a rehearsal can never be a PASS
    for cap in (1, 2, 3):
        assert "6 vCPU" in public(proof, f"backlog-{cap}")["cap_note"]
    assert "6 vCPU" in compare["cap_note"]


def test_a_sweep_that_misses_a_target_fails_the_comparison_with_the_numbers_kept(tmp_path, fixture):
    ctx = build(tmp_path)
    proof = capacity.run_backlog(ctx, fixture=fixture, only={"backlog-1", "backlog-2", "backlog-3"})
    steps = proof.doc["steps"]
    # Rewrite the recorded elapsed times as if extra encoders had bought almost nothing.
    for cap, elapsed in ((2, 900.0), (3, 800.0)):
        steps[f"backlog-{cap}"]["public"]["elapsed_seconds"] = elapsed
    step = proof.step("backlog-compare", lambda i: capacity.backlog_compare(proof), session=None)
    assert step["status"] == FAIL
    assert step["public"]["meets_target"] == {"2": False, "3": False}
    assert step["public"]["speedup"]["2"] < 1.6  # reported as measured, not rounded up


def test_the_comparison_fails_when_the_steps_used_different_backlogs(tmp_path, fixture):
    proof = capacity.run_backlog(build(tmp_path), fixture=fixture)
    proof.doc["steps"]["backlog-2"]["public"]["backlog"] = 12
    step = proof.step(
        "backlog-compare", lambda i: capacity.backlog_compare(proof), session=None, rerun=True
    )
    assert step["status"] == FAIL and step["public"]["comparable"] is False


def test_the_comparison_waits_until_all_three_caps_are_recorded(tmp_path, fixture):
    proof = capacity.run_backlog(build(tmp_path), fixture=fixture, workers={1, 2})
    assert "backlog-compare" not in proof.doc["steps"] and proof.overall() == "SIMULATED"
    assert set(proof.doc["steps"]) == {"backlog-1", "backlog-2"}


# ---- finite encoders: the operator batch keeps up to `cap` busy -----------------------------
def test_each_cap_drains_a_fresh_backlog_with_one_encoder_per_job_and_never_more_than_cap(
    tmp_path, fixture
):
    ctx = build(tmp_path)
    proof = capacity.run_backlog(ctx, fixture=fixture)
    for cap in (1, 2, 3):
        step = public(proof, f"backlog-{cap}")
        assert step["encoders_started"] == step["jobs_done"] == 6  # a finite encoder takes one
        assert step["peak_concurrent_from_task_stamps"] == cap
        assert step["peak_concurrent_polled"] <= cap
        assert step["launch_waves"] == 6 // cap  # refilled as each wave stopped
    assert len(ctx.world.jobs) == 18  # a new backlog per cap, not the same jobs again


def test_a_job_that_is_queued_when_an_encoder_stops_is_picked_up_by_a_replacement(
    tmp_path, fixture
):
    ctx = build(tmp_path)
    proof = capacity.run_backlog(ctx, fixture=fixture, workers={1}, backlog=6, only={"backlog-1"})
    assert public(proof, "backlog-1")["jobs_done"] == 6
    assert len({t["started_at"] for t in ctx.world.tasks.values()}) == 6


def test_refill_starts_only_what_the_backlog_needs_under_the_cap(monkeypatch):
    started = []
    monkeypatch.setattr(
        workflow,
        "start_workers",
        lambda ctx, count, minutes: started.append(count) or ["t"] * count,
    )
    rows = [{"status": "queued"}] * 4 + [{"status": "processing"}, {"status": "done"}]
    intent = {"tasks": []}
    # Three alive, one of them busy: two have not claimed yet and stand for two queued jobs.
    assert capacity.refill(STUB, intent, rows, 3, cap=3, minutes=60) == 0
    assert capacity.refill(STUB, intent, rows, 1, cap=3, minutes=60) == 2
    assert started == [2]


def test_refill_treats_a_busy_slot_as_taken_and_never_exceeds_the_cap(monkeypatch):
    monkeypatch.setattr(workflow, "start_workers", lambda ctx, count, minutes: ["t"] * count)
    rows = [{"status": "queued"}] * 5
    assert capacity.refill(STUB, {"tasks": []}, rows, 0, cap=2, minutes=60) == 2
    assert capacity.refill(STUB, {"tasks": []}, rows, 2, cap=2, minutes=60) == 0


def test_a_slot_the_session_still_holds_is_retried_but_other_launch_errors_stop_the_step(
    monkeypatch,
):
    def full(ctx, count, minutes):
        raise OperationError("Worker/reservation cap reached")

    def uncertain(ctx, count, minutes):
        raise OperationError("Launch uncertain; reserved slot retained")

    rows = [{"status": "queued"}] * 3
    monkeypatch.setattr(workflow, "start_workers", full)
    assert capacity.refill(STUB, {"tasks": []}, rows, 0, cap=3, minutes=60) == 0
    monkeypatch.setattr(workflow, "start_workers", uncertain)
    with pytest.raises(OperationError):
        capacity.refill(STUB, {"tasks": []}, rows, 0, cap=3, minutes=60)


def test_encoders_that_exit_without_claiming_work_exhaust_a_start_budget(monkeypatch):
    monkeypatch.setattr(workflow, "start_workers", lambda ctx, count, minutes: ["t"] * count)
    rows = [{"status": "queued"}] * 3
    spent = {"tasks": ["t"] * (capacity.LAUNCH_FACTOR * 3 - 1)}
    with pytest.raises(ProofError, match="start budget"):
        capacity.refill(STUB, spent, rows, 0, cap=3, minutes=60)


# ---- failures -------------------------------------------------------------------------------
def test_a_failed_encode_fails_its_step_and_the_comparison_and_is_counted(tmp_path, fixture):
    ctx = build(tmp_path, fail_claims={2})
    proof = capacity.run_backlog(ctx, fixture=fixture)
    first = public(proof, "backlog-1")
    assert statuses(proof)["backlog-1"] == FAIL
    assert first["jobs_failed"] == 1 and first["jobs_done"] == 5
    assert first["outcomes"] == {"done": 5, "failed": 1}
    assert statuses(proof)["backlog-2"] == statuses(proof)["backlog-3"] == PASS
    compare = proof.doc["steps"]["backlog-compare"]
    assert compare["status"] == FAIL and compare["public"]["all_cap_steps_passed"] is False
    assert compare["public"]["jobs_failed"] == {"1": 1, "2": 0, "3": 0}
    assert proof.failed_now() == ["backlog-1", "backlog-compare"]


def test_throughput_counts_only_jobs_that_finished_successfully(tmp_path, fixture):
    proof = capacity.run_backlog(
        build(tmp_path, fail_claims={1, 2}), fixture=fixture, only={"backlog-1"}
    )
    step = public(proof, "backlog-1")
    assert step["jobs_done"] == 4
    assert step["jobs_per_minute"] == pytest.approx(4 * 60.0 / step["elapsed_seconds"], rel=1e-3)


def test_counts_for_the_close_proof_include_the_backlog_outcomes(tmp_path, fixture):
    ctx = build(tmp_path, fail_claims={2})
    capacity.run_backlog(ctx, fixture=fixture)
    docs = summary.load(ctx.evidence_dir, "t")
    docs["185"]["mode"] = "live"
    found = summary.counts(docs)
    assert found["succeeded"] == 17 and found["failed"] == 1 and found["queued"] == 0


# ---- encoders are never left running ----------------------------------------------------------
def test_a_clean_sweep_leaves_no_encoder_running(tmp_path, fixture):
    ctx = build(tmp_path)
    proof = capacity.run_backlog(ctx, fixture=fixture)
    assert stopped(ctx)
    assert all(public(proof, f"backlog-{c}")["encoders_left_running"] == 0 for c in (1, 2, 3))


def test_an_encoder_still_alive_after_the_drain_fails_the_step(tmp_path, fixture, monkeypatch):
    ctx = build(tmp_path)
    real = workflow.live_tasks
    state = {"done": False}

    def live(inner):
        found = real(inner)
        # Only the final inventory, after every job is terminal, shows a straggler.
        if state["done"]:
            found = {**found, "arn:straggler": {"lastStatus": "RUNNING"}}
        return found

    monkeypatch.setattr(workflow, "live_tasks", live)
    real_wait = workflow.wait_stopped
    monkeypatch.setattr(
        workflow, "wait_stopped", lambda *a, **k: state.update(done=True) or real_wait(*a, **k)
    )
    proof = capacity.run_backlog(ctx, fixture=fixture, workers={1}, only={"backlog-1"})
    assert statuses(proof)["backlog-1"] == FAIL
    assert public(proof, "backlog-1")["encoders_left_running"] == 1


def test_an_encoder_already_running_blocks_the_step_before_any_upload(tmp_path, fixture):
    ctx = build(tmp_path)
    workflow.start_workers(ctx, 1, 60)
    proof = capacity.run_backlog(ctx, fixture=fixture, workers={1}, only={"backlog-1"})
    assert statuses(proof)["backlog-1"] == FAIL
    assert "already running" in public(proof, "backlog-1")["error"] and not ctx.world.jobs


# ---- stop and timeout -------------------------------------------------------------------------
def test_a_step_that_times_out_stops_its_encoders_and_fails_with_the_numbers_it_had(
    tmp_path, fixture
):
    ctx = build(tmp_path, encode_seconds=5000.0)
    proof = capacity.run_backlog(
        ctx, fixture=fixture, drain_timeout=120, workers={2}, only={"backlog-2"}
    )
    step = public(proof, "backlog-2")
    assert statuses(proof)["backlog-2"] == FAIL
    assert step["timed_out"] is True and step["jobs_not_terminal"] == 6
    assert step["encoders_left_running"] == 0 and stopped(ctx)


def test_a_backlog_left_unfinished_blocks_the_next_cap_so_it_cannot_join_the_measurement(
    tmp_path, fixture
):
    ctx = build(tmp_path, encode_seconds=5000.0)
    proof = capacity.run_backlog(ctx, fixture=fixture, drain_timeout=120)
    found = statuses(proof)
    assert found["backlog-1"] == found["backlog-2"] == found["backlog-3"] == FAIL
    assert "left jobs unfinished" in public(proof, "backlog-2")["error"]
    assert len(ctx.world.jobs) == 6  # the blocked caps uploaded nothing
    assert statuses(proof)["backlog-compare"] == FAIL


def test_an_interrupt_mid_drain_stops_the_encoders_and_propagates(tmp_path, fixture):
    ctx = build(tmp_path)
    real_sleep, calls = ctx.sleep, []

    def sleep(seconds):
        calls.append(seconds)
        if len(calls) == 8:
            raise KeyboardInterrupt
        real_sleep(seconds)

    ctx.sleep = sleep
    with pytest.raises(KeyboardInterrupt):
        capacity.run_backlog(ctx, fixture=fixture, workers={3}, only={"backlog-3"})
    assert ctx.world.tasks and stopped(ctx)


def test_a_session_closed_mid_drain_stops_the_encoders_and_ends_the_command(tmp_path, fixture):
    ctx = build(tmp_path)
    real_sleep, calls = ctx.sleep, []

    def sleep(seconds):
        calls.append(seconds)
        if len(calls) == 3:
            with ctx.journal.locked() as state:
                state.update(session="closed")
                ctx.journal.save(state)
        real_sleep(seconds)

    ctx.sleep = sleep
    with pytest.raises(SessionRefused):
        capacity.run_backlog(ctx, fixture=fixture, workers={3}, only={"backlog-3"})
    assert ctx.world.tasks and stopped(ctx)


def test_a_driver_that_went_quiet_too_long_cannot_pass_because_it_was_not_refilling(
    tmp_path, fixture
):
    ctx = build(tmp_path)
    real_sleep, calls = ctx.sleep, []

    def sleep(seconds):
        calls.append(seconds)
        real_sleep(seconds + (200 if len(calls) == 4 else 0))  # a suspended laptop

    ctx.sleep = sleep
    proof = capacity.run_backlog(ctx, fixture=fixture, workers={3}, only={"backlog-3"})
    step = public(proof, "backlog-3")
    assert statuses(proof)["backlog-3"] == FAIL and step["max_poll_gap_seconds"] > 60


def test_a_rerun_after_a_pass_repeats_nothing(tmp_path, fixture):
    ctx = build(tmp_path)
    capacity.run_backlog(ctx, fixture=fixture)
    jobs, again = len(ctx.world.jobs), capacity.run_backlog(ctx, fixture=fixture)
    assert again.ran == [] and len(ctx.world.jobs) == jobs


def test_a_harness_refuses_while_the_session_is_closed(tmp_path, fixture):
    ctx = build(tmp_path)
    sim.reopen(ctx, "closed")
    with pytest.raises(SessionRefused):
        capacity.run_backlog(ctx, fixture=fixture)


# ---- the evidence CLI -----------------------------------------------------------------------
SCOPE = (
    "--profile",
    "dc2-project2-mfa",
    "--region",
    "ap-southeast-1",
    "--account",
    "123456789012",
    "--run-id",
    "cli",
)


def cli(*argv, **kwargs):
    out = io.StringIO()
    code = evidence.main(list(argv), stdout=out, **kwargs)
    return code, json.loads(out.getvalue())


def test_capacity_backlog_runs_through_the_cli_and_writes_its_own_receipt(tmp_path, fixture):
    world = sim.SimWorld(encode_seconds=150.0)
    code, report = cli(
        "capacity", *SCOPE, "--dry-run", "--fixture", str(fixture), "--backlog", "6", world=world
    )
    assert code == 0 and report["issue"] == "#185" and report["overall"] == "SIMULATED"
    assert set(report["steps"]) == {"backlog-1", "backlog-2", "backlog-3", "backlog-compare"}
    assert report["steps"]["backlog-compare"]["meets_target"] == {"2": True, "3": True}


def test_a_bare_backlog_flag_uses_the_default_size():
    args = evidence.build_parser().parse_args(
        ["capacity", *SCOPE, "--fixture", "f.mp4", "--backlog"]
    )
    assert args.backlog == capacity.DEFAULT_BACKLOG == 6
    plain = evidence.build_parser().parse_args(["capacity", *SCOPE, "--fixture", "f.mp4"])
    assert plain.backlog is None


def test_without_backlog_the_capacity_command_still_runs_the_one_two_three_proof(tmp_path, fixture):
    world = sim.SimWorld(encode_seconds=240.0)
    code, report = cli(
        "capacity",
        *SCOPE,
        "--dry-run",
        "--fixture",
        str(fixture),
        "--short-fixture",
        str(fixture),
        world=world,
    )
    assert code == 0 and report["issue"] == "#64"
    assert {"run-1", "run-2", "run-3", "recovery", "dlq", "drain"} == set(report["steps"])


@pytest.mark.parametrize("extra", [["--poison"], ["--short-fixture", "s.mp4"]])
def test_backlog_does_not_mix_with_the_recovery_or_poison_steps(tmp_path, fixture, extra):
    code, body = cli(
        "capacity", *SCOPE, "--dry-run", "--fixture", str(fixture), "--backlog", "6", *extra
    )
    assert code == 1 and "does not combine" in body["error"]


def test_an_unreachable_backlog_size_is_refused_through_the_cli(tmp_path, fixture):
    code, body = cli("capacity", *SCOPE, "--dry-run", "--fixture", str(fixture), "--backlog", "4")
    assert code == 1 and "cannot reach" in body["error"]


def test_the_backlog_receipt_is_summarized_without_identifiers(tmp_path, fixture):
    ctx = build(tmp_path)
    capacity.run_backlog(ctx, fixture=fixture)
    docs = summary.load(ctx.evidence_dir, "t")
    docs["185"]["mode"] = "live"
    built = summary.build(docs, evidence.REQUIRED, "t", wall=lambda: 0)
    text = json.dumps(built)
    assert built["issues"]["#185"]["steps"]["backlog-compare"]["status"] == PASS
    assert "arn:aws" not in text and "http" not in text and "job_id" not in text
    assert built["issues"]["#64"]["overall"] == "NOT_RUN"
