"""Each cloud-proof harness against the simulated account, pass paths and one fault apiece.

The simulation is a rehearsal: every receipt it makes is marked SIMULATED. These tests prove the
harnesses detect the failures they exist to detect and never claim anything about AWS.
"""

import argparse
import json

import pytest

from scripts.aws.v1.proof import capacity, gateway, latency, sim, spend, tasks, workflow
from scripts.aws.v1.proof.core import FAIL, NOT_RUN, PASS, ProofError, sha256_text

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


# ---- #223 the smoke's encoder waits for the command ------------------------------------
E2E = {"direct-upload-e2e"}


def test_the_smoke_starts_its_encoder_only_after_the_command_reached_processing(
        tmp_path, fixture):
    # Media publishes the command 75 s after finalize (a cold consumer after a release). An
    # encoder started at finalize would long-poll 40 s, exit without claiming and strand the job.
    ctx = build(tmp_path, "open", outbox_seconds=75.0)
    proof = gateway.run(ctx, fixture=fixture, minutes=30, only=E2E)
    assert statuses(proof)["direct-upload-e2e"] == PASS
    public = proof.doc["steps"]["direct-upload-e2e"]["public"]
    assert public["encoders_started"] == 1
    (task,) = [t for t in ctx.world.tasks.values() if t["kind"] == "worker"]
    assert task["created_at"] >= 75.0


def test_the_smoke_starts_another_encoder_when_one_exits_without_claiming(tmp_path, fixture):
    ctx = build(tmp_path, "open", dud_encoders=1)
    proof = gateway.run(ctx, fixture=fixture, minutes=30, only=E2E)
    assert statuses(proof)["direct-upload-e2e"] == PASS
    assert proof.doc["steps"]["direct-upload-e2e"]["public"]["encoders_started"] == 2


def test_the_smoke_stops_starting_encoders_that_keep_exiting_without_claiming(
        tmp_path, fixture):
    ctx = build(tmp_path, "open", dud_encoders=9)
    proof = gateway.run(ctx, fixture=fixture, minutes=30, only=E2E)
    assert statuses(proof)["direct-upload-e2e"] == FAIL
    assert "start budget is spent" in proof.doc["steps"]["direct-upload-e2e"]["public"]["error"]
    assert len([t for t in ctx.world.tasks.values() if t["kind"] == "worker"]) == 2


def test_on_the_always_on_environment_the_smoke_lets_the_launcher_start_the_encoder(
        tmp_path, fixture):
    # V2-live (#236, #237): no operator batch, which the unattended session would refuse.
    args = argparse.Namespace(run_id="t", dry_run=True)
    ctx = sim.build(args, session="open", unattended=True, tmp=tmp_path / "state",
                    world=sim.SimWorld(encode_seconds=45.0, launcher=True))
    proof = gateway.run(ctx, fixture=fixture, minutes=30, only=E2E)
    assert statuses(proof)["direct-upload-e2e"] == PASS
    public = proof.doc["steps"]["direct-upload-e2e"]["public"]
    assert public["encoders_started"] >= 1 and public["encoders_left_running"] == 0


def test_the_smoke_refuses_to_start_on_stale_work_from_an_earlier_run(tmp_path, fixture):
    ctx = build(tmp_path, "open", stale_work=17)
    proof = gateway.run(ctx, fixture=fixture, minutes=30, only=E2E)
    assert statuses(proof)["direct-upload-e2e"] == FAIL
    assert "17 message(s)" in proof.doc["steps"]["direct-upload-e2e"]["public"]["error"]
    assert ctx.world.jobs == {} and not [t for t in ctx.world.tasks.values()
                                         if t["kind"] == "worker"]


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
    proof = latency.run(ctx, only={"cold-wake"})
    assert journal_session(ctx) == "closed"  # cold-wake closed its own window
    sim.reopen(ctx, "open")  # the operator's `session open` between the two steps
    proof = latency.run(ctx, only={"generator"})
    assert statuses(proof) == {"cold-wake": PASS, "generator": PASS}
    assert inactive(ctx)  # the temporary task definition was deregistered


def journal_session(ctx):
    with ctx.journal.locked() as state:
        return state.get("session")


def wake(ctx, **kwargs):
    step = latency.run(ctx, only={"cold-wake"}, **kwargs).doc["steps"]["cold-wake"]
    return step["status"], step["public"]


def limited(ctx, answers):
    """Make the Gateway answer the health probe with `answers` (then 200) and count the probes."""
    seen, real = [], ctx.http

    def http(method, url, headers, body, timeout):
        if url.endswith(latency.GATE_PROBE_PATH):
            seen.append(url)
            if len(seen) <= answers:
                return 429, {}, b""
        return real(method, url, headers, body, timeout)

    ctx.http = http
    return seen


def test_cold_wake_waits_for_the_database_to_pause_instead_of_giving_up_at_once(tmp_path):
    ctx = build(tmp_path, "closed", awake=True)  # capacity stays above 0 for about 5.5 minutes
    before = ctx.clock()
    status, public = wake(ctx)
    assert status == PASS and public["database_paused_before"] is True
    assert 300 <= public["pause_wait_seconds"] <= latency.PAUSE_WAIT_SECONDS
    assert ctx.clock() - before >= public["pause_wait_seconds"]  # on the injected clock


def test_cold_wake_is_not_run_only_after_the_whole_pause_wait_shows_no_pause(tmp_path):
    ctx = build(tmp_path, "closed", "never-pauses")
    status, public = wake(ctx)
    assert status == NOT_RUN and "awake" in public["reason"]
    assert latency.PAUSE_WAIT_SECONDS - 60 <= public["pause_wait_seconds"] <= (
        latency.PAUSE_WAIT_SECONDS)
    assert journal_session(ctx) == "closed"  # never opened a window it had no reason to open


def test_the_pause_wait_can_be_shortened(tmp_path):
    status, public = wake(build(tmp_path, "closed", "never-pauses"), pause_wait=120)
    assert status == NOT_RUN and public["pause_wait_seconds"] == 120


def test_cold_wake_waits_for_the_gateway_to_stop_throttling_before_it_measures(tmp_path):
    ctx = build(tmp_path, "closed")
    seen = limited(ctx, answers=3)
    status, public = wake(ctx)
    assert status == PASS and public["statuses"] == [200, 200, 200]
    assert public["gate_probes"] == len(seen) == 4
    assert public["gate_settle_seconds"] == 3 * latency.GATE_POLL_SECONDS
    assert "window_open_seconds" in public  # the wake time stays its own number


def test_cold_wake_fails_with_a_reason_when_the_gateway_never_settles_and_still_closes(tmp_path):
    ctx = build(tmp_path, "closed")
    seen = limited(ctx, answers=10_000)
    status, public = wake(ctx)
    assert status == FAIL and "429" in public["reason"]
    assert public["gate_settle_seconds"] <= latency.GATE_SETTLE_SECONDS
    assert len(seen) == public["gate_probes"] > 1 and "login_ms" not in public
    assert public["window_closed"] is True and journal_session(ctx) == "closed"


def test_cold_wake_closes_the_window_it_opened_even_when_a_measurement_raises(
        tmp_path, monkeypatch):
    ctx = build(tmp_path, "closed")
    monkeypatch.setattr(latency, "wait_for_gate", lambda *a: 1 / 0)
    status, public = wake(ctx)
    assert status == FAIL and "ZeroDivisionError" in public["reason"]
    assert public["window_closed"] is True and journal_session(ctx) == "closed"


def test_a_raising_probe_and_a_failed_close_keep_the_timings_and_say_how_to_recover(
        tmp_path, monkeypatch):
    ctx = build(tmp_path, "closed")
    answered = limited(ctx, answers=2)
    real_http = ctx.http

    def http(method, url, headers, body, timeout):
        if url.endswith(latency.GATE_PROBE_PATH) and len(answered) >= 2:
            raise TimeoutError("probe timed out at https://example.invalid")
        return real_http(method, url, headers, body, timeout)

    ctx.http = http
    real = latency.session_cli.main
    monkeypatch.setattr(latency.session_cli, "main", lambda argv, **kw: (
        1 if argv[0] == "close" else real(argv, **kw)))
    status, public = wake(ctx)
    assert status == FAIL and "TimeoutError" in public["reason"]
    assert "example.invalid" not in json.dumps(public)  # the class, never the text
    assert public["gate_probes"] == 3 and public["gate_settle_seconds"] >= 2 * (
        latency.GATE_POLL_SECONDS)
    assert "window_open_seconds" in public and "login_ms" not in public
    assert public["window_closed"] is False and "session close" in public["recovery"]


def test_cold_wake_does_not_pass_when_its_window_could_not_be_closed(tmp_path, monkeypatch):
    ctx = build(tmp_path, "closed")
    real = latency.session_cli.main
    monkeypatch.setattr(latency.session_cli, "main", lambda argv, **kw: (
        1 if argv[0] == "close" else real(argv, **kw)))
    status, public = wake(ctx)
    assert status == FAIL and public["window_closed"] is False
    assert "session close" in public["recovery"] and public["statuses"] == [200, 200, 200]


@pytest.mark.parametrize("fault", ["slow-tail", "errors"])
def test_a_slow_tail_or_any_failed_request_fails_the_generator_judgement(tmp_path, fault):
    proof = latency.run(build(tmp_path, "open", fault), only={"generator"})
    assert statuses(proof)["generator"] == FAIL


def test_the_generator_definition_is_deregistered_even_when_the_judgement_fails(tmp_path):
    ctx = build(tmp_path, "open", "errors")
    latency.run(ctx, only={"generator"})
    assert inactive(ctx)


@pytest.mark.parametrize(("rate", "burst"), [(5, 10), (49, 200), (100, 99)])
def test_the_generator_refuses_an_undersized_gate_before_any_side_effect(tmp_path, rate, burst):
    ctx = build(tmp_path, "open")
    ctx.world.plan.stage = {"ThrottlingBurstLimit": burst, "ThrottlingRateLimit": rate}
    proof = latency.run(ctx, only={"generator"})
    step = proof.doc["steps"]["generator"]
    assert step["status"] == FAIL and "edge_open" in step["public"]["error"]
    assert "session open" in step["public"]["error"]
    assert not ctx.world.definitions and not ctx.world.tasks and ctx.world.registered == 0
    assert proof.doc["intents"]["generator"] == {}  # nothing was minted either


def test_the_smallest_adequate_gate_is_accepted(tmp_path):
    ctx = build(tmp_path, "open")
    ctx.world.plan.stage = {"ThrottlingBurstLimit": latency.LOAD_EDGE_MIN_BURST,
                            "ThrottlingRateLimit": latency.LOAD_EDGE_MIN_RATE}
    assert statuses(latency.run(ctx, only={"generator"}))["generator"] == PASS


def test_throttled_requests_are_reported_apart_but_stay_errors_in_the_denominator(tmp_path):
    proof = latency.run(build(tmp_path, "open", "throttled"), only={"generator"})
    step = proof.doc["steps"]["generator"]
    public = step["public"]
    assert step["status"] == FAIL  # gates unchanged: a 429 is still an error
    assert public["status_cycle"]["throttled"] > 0 and public["login_cycle"]["throttled"] > 0
    assert public["status_cycle"]["error_rate"] >= (
        public["status_cycle"]["throttled"] / public["status_cycle"]["sample_count"])
    assert all("throttled" in route for route in public["routes"].values())
    assert public["routes"]["status"]["throttled"] == public["status_cycle"]["throttled"]


def test_a_healthy_run_reports_zero_throttled_requests(tmp_path):
    public = latency.run(build(tmp_path, "open"), only={"generator"}).doc[
        "steps"]["generator"]["public"]
    assert public["status_cycle"]["throttled"] == public["login_cycle"]["throttled"] == 0


def test_a_fresh_generator_rerun_mints_a_new_task_and_archives_the_old_attempt(tmp_path):
    ctx = build(tmp_path, "open", "errors")
    first = latency.run(ctx, only={"generator"})
    old_step, old_intent = first.doc["steps"]["generator"], dict(first.doc["intents"]["generator"])
    assert old_step["status"] == FAIL and old_intent["definition"]
    registered = ctx.world.registered

    ctx.fresh = {"generator"}
    second = latency.run(ctx, only={"generator"})
    assert ctx.world.registered == registered + 1  # a new definition and a new task
    archived = second.doc["attempts"]["generator"]
    assert [a["attempt"] for a in archived] == [1]
    assert archived[0]["step"] == old_step and archived[0]["intent"] == old_intent
    assert second.doc["intents"]["generator"]["definition"] != old_intent["definition"]
    assert second.doc["intents"]["generator"]["task"] != old_intent["task"]
    assert second.ran == ["generator"]

    third = latency.run(ctx, only={"generator"})  # same process settings: archived once per Proof
    assert [a["attempt"] for a in third.doc["attempts"]["generator"]] == [1, 2]


def test_each_attempt_keeps_its_own_raw_samples_and_the_archive_names_the_file(tmp_path):
    ctx = build(tmp_path, "open")
    first = latency.run(ctx, only={"generator"})
    one = ctx.evidence_dir / "latency-samples-t.csv"  # the first attempt keeps the old name
    kept = one.read_text()
    assert first.doc["steps"]["generator"]["private"]["samples_file"] == one.name

    ctx.fresh = {"generator"}
    ctx.world.generated = None
    ctx.world.faults.add("slow-tail")  # a different sample stream
    second = latency.run(ctx, only={"generator"})
    two = ctx.evidence_dir / "latency-samples-t-a2.csv"
    assert two.exists() and two.read_text() != kept and one.read_text() == kept
    (archived,) = second.doc["attempts"]["generator"]
    assert archived["step"]["private"]["samples_file"] == one.name
    assert archived["step"]["public"]["samples_sha256"] == sha256_text(kept)
    assert second.doc["steps"]["generator"]["private"]["samples_file"] == two.name

    ctx.world.generated = None
    ctx.world.faults.discard("slow-tail")
    third = latency.run(ctx, only={"generator"})  # same process settings: attempt 3 is fresh too
    assert third.doc["steps"]["generator"]["private"]["samples_file"] == (
        "latency-samples-t-a3.csv")


def test_a_samples_file_that_holds_other_samples_is_never_overwritten(tmp_path):
    ctx = build(tmp_path, "open")
    ctx.evidence_dir.mkdir(parents=True, exist_ok=True)
    taken = ctx.evidence_dir / "latency-samples-t.csv"
    taken.write_text("someone else's evidence\n")
    step = latency.run(ctx, only={"generator"}).doc["steps"]["generator"]
    assert step["status"] == FAIL and "never overwritten" in step["public"]["error"]
    assert taken.read_text() == "someone else's evidence\n"


def test_without_fresh_a_failed_generator_rerun_resumes_the_same_task(tmp_path):
    ctx = build(tmp_path, "open", "errors")
    first = latency.run(ctx, only={"generator"})
    task = first.doc["intents"]["generator"]["task"]
    again = latency.run(ctx, only={"generator"})
    assert "attempts" not in again.doc and again.doc["intents"]["generator"]["task"] == task


def test_fresh_reruns_a_passed_cold_wake_that_is_otherwise_final(tmp_path):
    ctx = build(tmp_path, "closed")
    assert wake(ctx)[0] == PASS
    assert latency.run(ctx, only={"cold-wake"}).ran == []  # final without --fresh
    ctx.fresh = True
    proof = latency.run(ctx, only={"cold-wake"})
    assert proof.ran == ["cold-wake"] and len(proof.doc["attempts"]["cold-wake"]) == 1


def test_a_not_run_cold_wake_can_be_retried_with_fresh(tmp_path):
    ctx = build(tmp_path, "closed", "never-pauses")
    assert wake(ctx, pause_wait=0)[0] == NOT_RUN
    ctx.world.faults.discard("never-pauses")
    ctx.fresh = {"cold-wake"}
    status, public = wake(ctx, pause_wait=0)
    assert status == PASS and public["window_closed"] is True


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


def test_slow_status_rounds_do_not_push_the_last_round_out_of_the_judged_window():
    # Live r1017b: drift-based pacing ran 176 of 180 rounds and no client covered end - 1.
    from concurrent.futures import ThreadPoolExecutor

    from scripts.aws.latency import timing_eligible
    from scripts.aws.v1.proof import generator

    now = [100.0]
    rounds = []

    def request(user, method, path, cookie):
        if user == 0:
            rounds.append(now[0])
        slow = len(rounds) in {20, 90, 150}  # three rounds take 2.4 s, as observed live
        elapsed = 2400.0 if slow else 70.0
        if user == 49:
            now[0] += elapsed / 1000
        return 200, elapsed, [], b""

    def sleep(seconds):
        now[0] += seconds + 0.0001  # a real sleep overshoots; live r1017b lost the last round

    rows = []
    with ThreadPoolExecutor(max_workers=1) as pool:  # serial: the fake clock is not shared-safe
        start, end = generator.window_rounds(
            request, lambda: now[0], sleep, pool, users=50, seconds=180, route="/s",
            cookie=None, phase="timed", rows=rows, label="status")
    assert len(rounds) == 180
    window = {"started_at": start, "ended_at": end, "warmup_started_at": start,
              "warmup_ended_at": start, "booked_deadline": end + 600}
    assert timing_eligible(rows, users=50, duration_seconds=180, measurement="status",
                           window=window)
