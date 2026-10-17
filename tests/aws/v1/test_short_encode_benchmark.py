"""The #93 benchmark harness: cost arithmetic, log parsing, both arms and the keep rule.

Every run here is against the simulated account, so no receipt is evidence of anything about
AWS (each is marked SIMULATED). What is proved is that the harness measures what it claims to,
refuses the wrong stack for each arm, and never makes the merge decision itself.
"""

import argparse
import io
import json

import pytest

from processing import short_lane
from scripts.aws.v1 import deploy, evidence
from scripts.aws.v1.proof import short_encode, sim
from scripts.aws.v1.proof.core import FAIL, PASS, ProofError

pytestmark = pytest.mark.unmeasured


@pytest.fixture
def fixture(tmp_path):
    path = tmp_path / "fixture.mp4"
    path.write_bytes(b"\0" * 4096)
    return path


def build(tmp_path, name, **world):
    args = argparse.Namespace(run_id="t", dry_run=True)
    return sim.build(args, session="open", world=sim.SimWorld(**world), tmp=tmp_path / name)


def statuses(proof):
    return {name: step["status"] for name, step in proof.doc["steps"].items()}


# --- Prices and cost per success -----------------------------------------------------------------


def test_prices_come_from_the_captured_price_files():
    prices = short_encode.load_prices()
    assert prices["lambda_gb_second"] == pytest.approx(0.0000166667)
    assert prices["lambda_request"] == pytest.approx(2e-7)
    assert prices["lambda_storage_gb_second"] == pytest.approx(3.7e-8)
    assert prices["fargate_vcpu_hour"] > 0 and prices["fargate_gb_hour"] > 0


def test_lambda_cost_is_gb_seconds_plus_ephemeral_above_the_free_tier_plus_a_request():
    prices = short_encode.load_prices()
    cost = short_encode.lambda_cost(
        10_000, memory_mb=3584, ephemeral_mb=2048, prices=prices
    )
    expected = (
        10 * 3584 / 1024 * prices["lambda_gb_second"]
        + 10 * (2048 - 512) / 1024 * prices["lambda_storage_gb_second"]
        + prices["lambda_request"]
    )
    assert cost == pytest.approx(expected)
    # 512 MB of ephemeral storage is included in the price of the function.
    free = short_encode.lambda_cost(1000, memory_mb=1024, ephemeral_mb=512, prices=prices)
    assert free == pytest.approx(prices["lambda_gb_second"] + prices["lambda_request"])


def test_fargate_cost_has_a_sixty_second_minimum_and_includes_the_ipv4_allowance():
    prices = short_encode.load_prices()
    rate = 2 * prices["fargate_vcpu_hour"] + 4 * prices["fargate_gb_hour"] + prices["ipv4_hour"]
    assert short_encode.fargate_cost(5, vcpu=2, memory_gib=4, prices=prices) == pytest.approx(
        60 / 3600 * rate
    )
    assert short_encode.fargate_cost(90.2, vcpu=2, memory_gib=4, prices=prices) == pytest.approx(
        91 / 3600 * rate
    )
    # A two-vCPU, four-GiB task is about $0.128 an hour in the V1 worksheet.
    assert rate == pytest.approx(0.12824, rel=0.01)


# --- Log lines -----------------------------------------------------------------------------------

COLD = (
    "REPORT RequestId: aaaa1111\tDuration: 8123.45 ms\tBilled Duration: 8124 ms\t"
    "Memory Size: 3584 MB\tMax Memory Used: 912 MB\tInit Duration: 1650.20 ms"
)
WARM = (
    "REPORT RequestId: bbbb2222\tDuration: 3500.00 ms\tBilled Duration: 3500 ms\t"
    "Memory Size: 3584 MB\tMax Memory Used: 905 MB"
)


def encode_line(job, request, outcome="finished", cold=False):
    payload = {"event": "short_encode", "job_id": job, "request_id": request,
               "outcome": outcome, "cold": cold, "seconds": 1.0}
    return "[INFO]\t2026-10-17T10:00:00Z\tabc\tdc2.short_encode " + json.dumps(payload)


def test_report_lines_yield_billed_init_and_memory_and_other_lines_yield_nothing():
    cold = short_encode.parse_report(COLD)
    assert cold == {"request_id": "aaaa1111", "duration_ms": 8123.45, "billed_ms": 8124,
                    "memory_mb": 3584, "max_memory_mb": 912, "init_ms": 1650.2}
    assert short_encode.parse_report(WARM)["init_ms"] is None
    assert short_encode.parse_report("START RequestId: x Version: $LATEST") is None


def test_encode_lines_are_parsed_and_malformed_or_foreign_ones_are_ignored():
    assert short_encode.parse_encode(encode_line("j1", "r1"))["job_id"] == "j1"
    assert short_encode.parse_encode("dc2.short_encode {not json") is None
    assert short_encode.parse_encode('dc2.short_encode {"event": "other"}') is None
    assert short_encode.parse_encode("nothing here") is None


def test_invocations_are_grouped_by_job_and_joined_to_their_report_by_request_id():
    found = short_encode.invocations_by_job(
        [encode_line("j1", "aaaa1111", cold=True), encode_line("j2", "bbbb2222")], [COLD, WARM]
    )
    assert found["j1"][0]["report"]["billed_ms"] == 8124 and found["j1"][0]["cold"]
    assert found["j2"][0]["report"]["init_ms"] is None
    lone = short_encode.invocations_by_job([encode_line("j3", "unknown")], [COLD])
    assert lone["j3"][0]["report"] == {}  # the REPORT line has not been delivered yet


# --- Statistics ----------------------------------------------------------------------------------


def row(phase, seconds, *, success=True, status="done", retries=0):
    return {"phase": phase, "seconds": seconds, "success": success, "status": status,
            "retries": retries, "regressions": 0}


def test_summaries_keep_failures_in_the_denominator_and_split_cold_from_warm():
    rows = [row("cold", 40.0), row("warm", 20.0), row("warm", 30.0),
            row("warm", 99.0, success=False, status="failed")]
    summary = short_encode.summarize(rows, arm="x", costs=[0.01, 0.01, 0.01, 0.01])
    assert (summary["jobs"], summary["successes"], summary["failures"]) == (4, 3, 1)
    assert summary["cold"]["median_seconds"] == 40.0
    assert summary["warm"]["count"] == 2  # a failed job has no completed latency
    assert summary["warm"]["median_seconds"] == 20.0
    assert summary["cost_usd_total"] == pytest.approx(0.04)
    # Cost per success charges the failed job's cost to the successes.
    assert summary["cost_usd_per_success"] == pytest.approx(0.04 / 3, abs=1e-6)
    assert "Shared services are excluded" in summary["cost_basis"]


def test_status_regressions_count_only_backwards_moves():
    forward = [(0, "queued"), (5, "processing"), (30, "done")]
    assert short_encode.regressions(forward) == 0
    assert short_encode.regressions([(0, "queued"), (5, "processing"), (9, "queued"),
                                     (20, "processing"), (30, "done")]) == 1


# --- The arms against the simulation ---------------------------------------------------------


def run_both(tmp_path, fixture, *, lambda_world=None, fargate_world=None):
    first = build(tmp_path, "fargate", **(fargate_world or {"encode_seconds": 40}))
    short_encode.run(first, arm="fargate", fixture=fixture, fixture_seconds=24.0, jobs=3)
    second = build(tmp_path, "lambda", lambda_lane=True, **(lambda_world or {}))
    second.evidence_dir.mkdir(mode=0o700, exist_ok=True)
    (second.evidence_dir / "evidence-93-t.json").write_bytes(
        (first.evidence_dir / "evidence-93-t.json").read_bytes()
    )
    short_encode.run(second, arm="lambda", fixture=fixture, fixture_seconds=24.0, jobs=3,
                     idle_minutes=0)
    return short_encode.run(second, arm="compare"), first, second


def test_both_arms_and_the_comparison_run_and_the_decision_stays_pending(tmp_path, fixture):
    proof, first, second = run_both(tmp_path, fixture)
    assert statuses(proof) == {"fargate": PASS, "lambda": PASS, "compare": PASS}
    assert proof.overall() == "SIMULATED"
    verdict = proof.doc["steps"]["compare"]["public"]
    assert verdict["merge_decision"] == "pending"
    assert verdict["meets_keep_rule"] is True  # a simulation fast enough to satisfy the rule
    lam = proof.doc["steps"]["lambda"]["public"]
    assert lam["cold"]["count"] == 1 and lam["warm"]["count"] == 2
    assert lam["cold_start_observed"] is True and lam["invocations"] == 3
    assert lam["queue_leftover"] == 0 and lam["dead_letters"] == 0
    assert lam["memory_mb"] == short_lane.MEMORY_MB
    far = proof.doc["steps"]["fargate"]["public"]
    assert far["cold"]["median_seconds"] > far["warm"]["median_seconds"]  # the task start
    assert far["encoders_left_running"] == 0
    assert not second.world.tasks, "the Lambda arm never starts a Fargate task"


def test_the_keep_rule_fails_when_lambda_is_slower_even_though_everything_succeeded(
    tmp_path, fixture
):
    proof, *_ = run_both(
        tmp_path, fixture, lambda_world={"lambda_cold_seconds": 300.0, "lambda_warm_seconds": 200.0}
    )
    verdict = proof.doc["steps"]["compare"]["public"]
    assert verdict["keep_rule"]["no_failures_on_either_arm"] is True
    assert verdict["keep_rule"]["lambda_cold_median_lower"] is False
    assert verdict["keep_rule"]["lambda_warm_median_lower"] is False
    assert verdict["meets_keep_rule"] is False
    assert verdict["merge_decision"] == "pending"
    assert statuses(proof)["compare"] == PASS  # the measurement succeeded; the rule did not


def test_the_fargate_arm_refuses_a_stack_that_has_the_lane(tmp_path, fixture):
    ctx = build(tmp_path, "lane", lambda_lane=True)
    proof = short_encode.run(ctx, arm="fargate", fixture=fixture, fixture_seconds=24.0, jobs=2)
    assert statuses(proof)["fargate"] == FAIL
    assert "would run on Lambda" in proof.doc["steps"]["fargate"]["public"]["error"]
    assert not ctx.world.tasks and not ctx.world.reservations


def test_the_lambda_arm_refuses_a_stack_without_the_lane(tmp_path, fixture):
    ctx = build(tmp_path, "plain")
    proof = short_encode.run(ctx, arm="lambda", fixture=fixture, fixture_seconds=24.0, jobs=2,
                             idle_minutes=0)
    assert statuses(proof)["lambda"] == FAIL
    assert "no Lambda lane" in proof.doc["steps"]["lambda"]["public"]["error"]


def test_the_lambda_arm_refuses_while_its_mapping_is_closed(tmp_path, fixture):
    ctx = build(tmp_path, "closed", lambda_lane=True)
    ctx.world.plan.mappings.clear()  # no session open has enabled it
    proof = short_encode.run(ctx, arm="lambda", fixture=fixture, fixture_seconds=24.0, jobs=2,
                             idle_minutes=0)
    assert statuses(proof)["lambda"] == FAIL
    assert "not enabled" in proof.doc["steps"]["lambda"]["public"]["error"]


def test_compare_needs_both_arms(tmp_path, fixture):
    ctx = build(tmp_path, "one", encode_seconds=40)
    short_encode.run(ctx, arm="fargate", fixture=fixture, fixture_seconds=24.0, jobs=2)
    proof = short_encode.run(ctx, arm="compare")
    assert statuses(proof)["compare"] == FAIL
    assert "lambda arm has not been run" in proof.doc["steps"]["compare"]["public"]["error"]


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"fixture_seconds": 61.0}, "within the bound"),
        ({"fixture_seconds": 0}, "within the bound"),
        ({"jobs": 1}, "2..20"),
        ({"jobs": 21}, "2..20"),
    ],
)
def test_a_fixture_or_job_count_outside_the_design_is_refused_before_any_call(
    tmp_path, fixture, kwargs, message
):
    ctx = build(tmp_path, "bad", lambda_lane=True)
    arguments = {"fixture": fixture, "fixture_seconds": 24.0, "jobs": 3, "idle_minutes": 0}
    arguments.update(kwargs)
    with pytest.raises(ProofError, match=message):
        short_encode.run(ctx, arm="lambda", **arguments)
    assert ctx.world.calls == []


def test_a_fixture_over_the_size_bound_is_refused(tmp_path):
    big = tmp_path / "big.mp4"
    with big.open("wb") as handle:
        handle.truncate(short_lane.MAX_SOURCE_BYTES + 1)
    with pytest.raises(ProofError, match="size bound"):
        short_encode.check_fixture(big, 24.0)


def test_a_rerun_of_a_finished_arm_repeats_nothing(tmp_path, fixture):
    ctx = build(tmp_path, "again", lambda_lane=True)
    short_encode.run(ctx, arm="lambda", fixture=fixture, fixture_seconds=24.0, jobs=2,
                     idle_minutes=0)
    invocations = len(ctx.world.invocations)
    again = short_encode.run(ctx, arm="lambda", fixture=fixture, fixture_seconds=24.0, jobs=2,
                             idle_minutes=0)
    assert again.ran == [] and len(ctx.world.invocations) == invocations


def test_a_lambda_job_that_was_redirected_or_retried_is_not_a_success(tmp_path, fixture):
    ctx = build(tmp_path, "retry", lambda_lane=True)
    real = ctx.world.logs_filter_log_events

    def twice(payload):
        reply = real(payload)
        # Every invocation is reported twice: the message was redelivered and ran again.
        return {"events": reply["events"] * 2}

    ctx.world.logs_filter_log_events = twice
    proof = short_encode.run(ctx, arm="lambda", fixture=fixture, fixture_seconds=24.0, jobs=2,
                             idle_minutes=0)
    public = proof.doc["steps"]["lambda"]["public"]
    assert statuses(proof)["lambda"] == FAIL and public["retries"] == 2
    assert public["successes"] == 0


# --- Wiring ----------------------------------------------------------------------------------


def test_the_evidence_cli_has_a_short_encode_subcommand_and_requires_a_fixture_for_an_arm(tmp_path):
    parser = evidence.build_parser()
    args = parser.parse_args(["short-encode", "--arm", "lambda", "--profile", "p", "--region",
                              "r", "--account", "1", "--run-id", "x", "--dry-run"])
    assert (args.arm, args.jobs, args.idle_minutes) == ("lambda", 5, 20)
    out = io.StringIO()
    code = evidence.main(["short-encode", "--arm", "fargate", "--profile", "dc2-agent",
                          "--region", "ap-southeast-1", "--account", "123456789012",
                          "--run-id", "t", "--dry-run"], stdout=out)
    assert code == 1 and "--fixture" in out.getvalue()


def test_a_dry_run_of_the_fargate_arm_completes_against_the_simulation(tmp_path, fixture):
    out = io.StringIO()
    code = evidence.main(["short-encode", "--arm", "fargate", "--fixture", str(fixture),
                          "--fixture-seconds", "24", "--jobs", "2", "--profile", "dc2-agent",
                          "--region", "ap-southeast-1", "--account", "123456789012",
                          "--run-id", "t", "--dry-run"], stdout=out)
    report = json.loads(out.getvalue())
    assert code == 0 and report["overall"] == "SIMULATED"
    assert report["steps"]["fargate"]["status"] == PASS


def test_rehearsal_includes_the_short_encode_comparison():
    out = io.StringIO()
    assert evidence.rehearse(argparse.Namespace(run_id="rehearsal", release_plan=None), out) == 0
    steps = json.loads(out.getvalue())["harnesses"]["short-encode"]["steps"]
    assert steps == {"fargate": PASS, "lambda": PASS, "compare": PASS}


def test_log_filtering_is_a_read_only_allowlisted_operation():
    deploy.check_operation("logs", "filter-log-events", {"logGroupName": "/g"})
    assert not deploy.is_mutating("filter-log-events")
    with pytest.raises(deploy.DeployError):
        deploy.check_operation("logs", "put-log-events", {})
