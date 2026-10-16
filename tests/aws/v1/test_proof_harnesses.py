"""Each cloud-proof harness against the simulated account, pass paths and one fault apiece.

The simulation is a rehearsal: every receipt it makes is marked SIMULATED. These tests prove the
harnesses detect the failures they exist to detect and never claim anything about AWS.
"""

import argparse

import pytest

from scripts.aws.v1.proof import capacity, gateway, latency, sim, spend, tasks, workflow
from scripts.aws.v1.proof.core import FAIL, NOT_RUN, PASS, ProofError

pytestmark = pytest.mark.unmeasured


@pytest.fixture
def fixture(tmp_path):
    path = tmp_path / "fixture.mp4"
    path.write_bytes(b"\0" * 4096)
    return path


def build(tmp_path, session, *faults, **world):
    world.setdefault("encode_seconds", 45.0)
    args = argparse.Namespace(run_id="t", dry_run=True)
    return sim.build(args, session=session, world=sim.SimWorld(faults=faults, **world),
                     tmp=tmp_path / "state")


def inactive(ctx):
    """Every task definition the harness registered is deregistered, and at least one existed."""
    return bool(ctx.world.definitions) and all(
        d["status"] == "INACTIVE" for d in ctx.world.definitions.values())


def statuses(proof):
    return {name: step["status"] for name, step in proof.doc["steps"].items()}


# ---- #63 gateway -----------------------------------------------------------------------
def test_a_healthy_simulated_gateway_passes_every_step_but_is_still_only_simulated(
        tmp_path, fixture):
    proof = gateway.run(build(tmp_path, "open"), fixture=fixture, minutes=30)
    assert set(statuses(proof).values()) == {PASS}
    assert proof.overall() == "SIMULATED"


@pytest.mark.parametrize(("fault", "step"), [
    ("cors-open", "cors-preflight"),
    ("sqs-open", "sqs-direct-send"),
    ("crossdb-open", "cross-database"),
    ("weak-cookie", "session-roundtrip"),
    ("no-hls", "direct-upload-e2e"),
])
def test_each_gateway_boundary_that_is_left_open_fails_exactly_its_own_step(
        tmp_path, fixture, fault, step):
    proof = gateway.run(build(tmp_path, "open", fault), fixture=fixture, minutes=30)
    assert statuses(proof)[step] == FAIL
    assert [n for n, s in statuses(proof).items() if s == FAIL] == [step]
    assert proof.failed_now() == [step]


def test_an_unreachable_database_is_not_run_rather_than_passed(tmp_path, fixture):
    proof = gateway.run(build(tmp_path, "open", "db-unreachable"), fixture=fixture, minutes=30)
    assert statuses(proof)["cross-database"] == NOT_RUN


def test_a_gateway_harness_refuses_while_the_session_is_closed(tmp_path, fixture):
    from scripts.aws.v1.proof.core import SessionRefused

    with pytest.raises(SessionRefused):
        gateway.run(build(tmp_path, "closed"), fixture=fixture, minutes=30)


def test_a_rerun_of_the_gateway_harness_repeats_nothing_that_already_passed(tmp_path, fixture):
    ctx = build(tmp_path, "open")
    gateway.run(ctx, fixture=fixture, minutes=30)
    registered = ctx.world.registered
    again = gateway.run(ctx, fixture=fixture, minutes=30)
    assert again.ran == [] and ctx.world.registered == registered


# ---- #64 capacity ----------------------------------------------------------------------
def test_simulated_capacity_runs_one_two_and_three_encoders_then_recovers_and_drains(
        tmp_path, fixture):
    ctx = build(tmp_path, "open", encode_seconds=240.0)
    proof = capacity.run(ctx, fixture=fixture, short_fixture=fixture, minutes=30)
    assert set(statuses(proof).values()) == {PASS}
    assert proof.doc["steps"]["run-3"]["public"]["peak_concurrent_from_task_stamps"] == 3


def test_recovery_fails_when_nothing_reacts_to_the_stopped_encoder_within_the_gate(
        tmp_path, fixture):
    ctx = build(tmp_path, "open", encode_seconds=240.0, repair_seconds=2000.0)
    proof = capacity.run(ctx, fixture=fixture, short_fixture=fixture, minutes=30,
                         only={"recovery"})
    assert statuses(proof)["recovery"] == FAIL


def test_recovery_also_accepts_a_job_the_system_fails_cleanly_inside_the_gate(tmp_path, fixture):
    ctx = build(tmp_path, "open", encode_seconds=240.0, requeue=False)
    proof = capacity.run(ctx, fixture=fixture, short_fixture=fixture, minutes=30,
                         only={"recovery"})
    assert statuses(proof)["recovery"] == PASS
    assert proof.doc["steps"]["recovery"]["public"]["final_status"] == "failed"


# ---- #66 latency -----------------------------------------------------------------------
def test_the_generator_and_cold_wake_pass_on_a_healthy_simulation_and_clean_up(tmp_path):
    ctx = build(tmp_path, "closed")
    proof = latency.run(ctx)
    assert statuses(proof) == {"cold-wake": PASS, "generator": PASS}
    assert inactive(ctx)  # the temporary task definition was deregistered


@pytest.mark.parametrize("fault", ["slow-tail", "errors"])
def test_a_slow_tail_or_any_failed_request_fails_the_generator_judgement(tmp_path, fault):
    proof = latency.run(build(tmp_path, "open", fault), only={"generator"})
    assert statuses(proof)["generator"] == FAIL


def test_the_generator_definition_is_deregistered_even_when_the_judgement_fails(tmp_path):
    ctx = build(tmp_path, "open", "errors")
    latency.run(ctx, only={"generator"})
    assert inactive(ctx)


def test_the_shipped_generator_fits_a_container_override_and_names_no_credential():
    packed, command = tasks.ship(latency.GENERATOR)
    assert len(packed) < tasks.MAX_SCRIPT and command[:2] == ["python", "-c"]
    assert "DC2_PASSWORD" not in latency.GENERATOR.read_text()  # it registers its own account


def test_generator_samples_round_trip_through_the_log_chunks(tmp_path):
    ctx = build(tmp_path, "closed")
    lines = ctx.world.generator_lines()
    rows = latency.parse_samples(latency.collect_samples(lines))
    result = tasks.tagged(lines, "DC2-RESULT")[-1]
    timed = [r for r in rows if r["phase"] == "timed"]
    assert result["ok"] and len(timed) == sum(r["count"] for r in result["routes"].values())


# ---- #67 spend -------------------------------------------------------------------------
def test_close_state_pause_and_cost_pass_in_the_simulation_but_teardown_stays_not_run(tmp_path):
    proof = spend.run(build(tmp_path, "closed"), wait_minutes=10)
    assert statuses(proof) == {"close-state": PASS, "pause": PASS, "cost-explorer": PASS,
                               "teardown-receipt": NOT_RUN}


def test_a_database_that_never_scales_to_zero_fails_the_pause_step(tmp_path):
    proof = spend.run(build(tmp_path, "closed", "never-pauses"), wait_minutes=10)
    assert statuses(proof)["pause"] == FAIL


def test_spend_refuses_to_judge_the_closed_state_while_the_session_is_open(tmp_path):
    from scripts.aws.v1.proof.core import SessionRefused

    with pytest.raises(SessionRefused):
        spend.run(build(tmp_path, "open"), only={"close-state"})


def test_cost_categories_do_not_name_an_account_or_resource(tmp_path):
    proof = spend.run(build(tmp_path, "closed"), only={"cost-explorer"})
    public = str(proof.doc["steps"]["cost-explorer"]["public"])
    assert "arn:" not in public and "sim-cluster" not in public


# ---- helpers ---------------------------------------------------------------------------
def test_peak_overlap_counts_tasks_alive_together_and_frees_before_it_starts():
    def task(start, stop):
        return {"pullStartedAt": f"2026-10-17T10:{start:02d}:00+00:00",
                "stoppedAt": f"2026-10-17T10:{stop:02d}:00+00:00"}

    assert tasks.peak_overlap([task(0, 5), task(1, 6), task(2, 7)]) == 3
    assert tasks.peak_overlap([task(0, 5), task(5, 9)]) == 1
    assert tasks.peak_overlap([{"pullStartedAt": "2026-10-17T10:00:00+00:00"}]) == 0


# ---- resuming an upload that was already finalized ---------------------------------------
@pytest.fixture
def uploads(monkeypatch):
    """Counts the direct-to-storage POSTs the workflow makes."""
    posted, real = [], workflow.direct

    def counting(http, method, *args, **kwargs):
        if method == "POST":
            posted.append(method)
        return real(http, method, *args, **kwargs)

    monkeypatch.setattr(workflow, "direct", counting)
    return posted


def test_a_resume_after_finalize_replays_the_reservation_and_reuses_the_same_job(
        tmp_path, fixture, uploads):
    ctx = build(tmp_path, "open")
    api, _, _ = workflow.login(ctx)
    intent = {}
    first = workflow.submit(ctx, api, fixture, intent, lambda: None)
    assert len(uploads) == 1
    again = workflow.submit(ctx, api, fixture, intent, lambda: None)  # a later step had failed
    assert again["job_id"] == first["job_id"]
    assert len(uploads) == 1 and len(ctx.world.jobs) == 1 and len(ctx.world.reservations) == 1
    assert again["reserve_ms"] == first["reserve_ms"]  # the original measurement is kept


def test_a_resume_that_lost_its_upload_and_job_records_still_finds_the_finalized_job(
        tmp_path, fixture, uploads):
    ctx = build(tmp_path, "open")
    api, _, _ = workflow.login(ctx)
    intent = {}
    first = workflow.submit(ctx, api, fixture, intent, lambda: None)
    survivor = {"request_id": intent["request_id"]}  # crashed before anything else was saved
    again = workflow.submit(ctx, api, fixture, survivor, lambda: None)
    assert again["job_id"] == first["job_id"] and survivor["uploaded"] is True
    assert len(uploads) == 1


def test_a_caller_that_needs_an_upload_grant_still_rejects_a_replayed_reservation(
        tmp_path, fixture):
    ctx = build(tmp_path, "open")
    api, _, _ = workflow.login(ctx)
    intent = {}
    workflow.submit(ctx, api, fixture, intent, lambda: None)
    with pytest.raises(ProofError, match="no upload grant"):
        workflow.reserve(api, fixture, intent["request_id"])
