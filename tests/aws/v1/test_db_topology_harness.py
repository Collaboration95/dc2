"""The #94 measurement harness: what it measures, what it refuses, and the rule it applies.

Every run here is against the simulated account, so no receipt is evidence about AWS (each is
marked SIMULATED and the summary writer refuses it). What is proved is that the harness measures
what it claims, never reports a cold resume it did not observe, refuses the wrong stack for each
arm and a session that would keep Aurora awake, and applies a fixed rule without making the
merge decision itself.
"""

import argparse
import copy
import io
import json
import stat
import threading
import time
from types import SimpleNamespace

import pytest

from scripts.aws.transport import OperationError
from scripts.aws.v1 import deploy, evidence
from scripts.aws.v1.proof import db_topology, sim
from scripts.aws.v1.proof.core import FAIL, NOT_RUN, PASS, ProofError, SessionRefused
from scripts.aws.v1.transport import validate_arguments

pytestmark = pytest.mark.unmeasured


def build(tmp_path, name, database="shared", session="window", **world):
    args = argparse.Namespace(run_id="t", dry_run=True)
    return sim.build(
        args, session=session, tmp=tmp_path / name, world=sim.SimWorld(database=database, **world)
    )


def run_arm(ctx, arm, **kwargs):
    kwargs.setdefault("samples", 10)
    kwargs.setdefault("tail_minutes", 0)
    return db_topology.run(ctx, arm_name=arm, **kwargs)


def public(proof, step):
    return proof.doc["steps"][step]["public"]


@pytest.fixture
def both(tmp_path):
    """Both arms and their comparison, in two simulated worlds sharing one receipt."""
    import shutil

    first = build(tmp_path, "shared", "shared")
    run_arm(first, "shared")
    second = build(tmp_path, "separate", "separate")
    second.evidence_dir.mkdir(mode=0o700, exist_ok=True)
    shutil.copy(first.evidence_dir / "evidence-94-t.json", second.evidence_dir)
    run_arm(second, "separate")
    return second, db_topology.run(second, arm_name="compare")


# ---- the arms ---------------------------------------------------------------------------------
def test_the_shared_arm_measures_one_cluster_serving_both_domains(tmp_path):
    proof = run_arm(build(tmp_path, "a", "shared"), "shared")
    step = proof.doc["steps"]["shared"]
    data = step["public"]
    assert step["status"] == PASS and data["clusters"] == 1
    assert list(data["cold_resume"]) == ["cluster"]
    cold = data["cold_resume"]["cluster"]
    assert cold["measured"] and cold["succeeded"]
    assert cold["probe_domain"] == "processing"  # the Processing API's ready probe
    assert 25 <= cold["resume_seconds"] <= 45  # the simulated resume is 30 s
    assert cold["paused_confirmed_by"] == "ServerlessDatabaseCapacity == 0"
    assert set(data["warm"]) == {"media", "processing"}
    assert data["configured"]["cluster"] == {
        "min_acu": 0.0,
        "max_acu": 2.0,
        "seconds_until_auto_pause": 300,
    }


def test_the_shared_cluster_is_woken_and_slowed_by_the_peers_load(tmp_path):
    data = public(run_arm(build(tmp_path, "a", "shared"), "shared"), "shared")
    wake = data["isolation"]["peer_wake"]
    assert wake["same_cluster"] is True and wake["peer_woken"] is True
    assert wake["peer_max_acu"] > 0
    assert data["isolation"]["peer_slowdown"]["slowdown_p95"] > db_topology.MAX_PEER_SLOWDOWN


def test_the_separate_arm_measures_each_cluster_and_the_peer_stays_paused(tmp_path):
    proof = run_arm(build(tmp_path, "a", "separate"), "separate")
    data = public(proof, "separate")
    assert proof.doc["steps"]["separate"]["status"] == PASS and data["clusters"] == 2
    assert set(data["cold_resume"]) == {"media", "processing"}
    assert {v["probe_domain"] for v in data["cold_resume"].values()} == {"media", "processing"}
    wake = data["isolation"]["peer_wake"]
    assert wake["same_cluster"] is False and wake["peer_woken"] is False
    assert wake["peer_max_acu"] == 0
    assert data["isolation"]["peer_slowdown"]["slowdown_p95"] <= db_topology.MAX_PEER_SLOWDOWN


def test_every_part_of_the_isolation_test_is_taken_while_the_clusters_are_paused(tmp_path):
    ctx = build(tmp_path, "a", "separate")
    seen = []
    original = db_topology.wait_paused

    def spy(ctx_, clusters, **kwargs):
        left = original(ctx_, clusters, **kwargs)
        seen.append((sorted(clusters), left))
        return left

    import unittest.mock as mock

    with mock.patch.object(db_topology, "wait_paused", spy):
        run_arm(ctx, "separate")
    # a pause is confirmed before each cold resume and again before the wake test
    assert [s[0] for s in seen] == [["media"], ["processing"], ["media", "processing"]]
    assert all(left == [] for _, left in seen)


def test_the_stack_must_be_the_layout_the_arm_names(tmp_path):
    for world, arm in (("shared", "separate"), ("separate", "shared")):
        proof = run_arm(build(tmp_path, f"{world}-{arm}", world), arm)
        step = proof.doc["steps"][arm]
        assert step["status"] == FAIL
        assert f"--database-topology {arm}" in step["public"]["error"]


def test_a_session_that_would_keep_aurora_awake_is_refused(tmp_path):
    # `session open` enables the repair schedules, which touch the database every minute.
    with pytest.raises(SessionRefused, match="needs window"):
        run_arm(build(tmp_path, "a", "shared", session="open"), "shared")
    with pytest.raises(SessionRefused):
        run_arm(build(tmp_path, "b", "shared", session="closed"), "shared")


def test_a_cluster_that_never_pauses_is_not_measured_cold_and_the_arm_is_not_run(tmp_path):
    proof = run_arm(
        build(tmp_path, "a", "shared", faults=("never-pauses",)), "shared", pause_minutes=2
    )
    step = proof.doc["steps"]["shared"]
    cold = step["public"]["cold_resume"]["cluster"]
    assert step["status"] == NOT_RUN
    assert cold["measured"] is False and "never showed 0 ACU" in cold["reason"]
    assert "resume_seconds" not in cold
    assert step["public"]["isolation"]["peer_wake"]["measured"] is False
    assert proof.overall() == "SIMULATED"


def test_a_probe_that_fails_counts_against_the_arm_and_leaves_no_latency(tmp_path):
    ctx = build(tmp_path, "a", "shared")
    real = ctx.world.lambda_invoke

    def failing(payload):
        reply = real(payload)
        if "Processing" in payload["FunctionName"] and reply["Payload"].get("ready"):
            reply["Payload"]["ready"] = False
        return reply

    ctx.world.lambda_invoke = failing
    step = run_arm(ctx, "shared").doc["steps"]["shared"]
    # the cold resume itself cannot succeed either, and says so
    assert step["status"] == FAIL
    assert step["public"]["warm"]["processing"]["failures"] == 10
    assert step["public"]["warm"]["processing"]["p95_ms"] is None
    assert step["public"]["cold_resume"]["cluster"]["succeeded"] is False


def test_an_interrupted_arm_resumes_without_repeating_a_finished_measurement(tmp_path):
    import unittest.mock as mock

    ctx = build(tmp_path, "a", "separate")
    calls = []
    real = db_topology.cold_resume

    def counting(*args, **kwargs):
        calls.append(args[2])
        return real(*args, **kwargs)

    with (
        mock.patch.object(db_topology, "cold_resume", counting),
        mock.patch.object(db_topology, "measure_warm", side_effect=ProofError("interrupted")),
    ):
        first = run_arm(ctx, "separate")
    assert first.doc["steps"]["separate"]["status"] == FAIL
    assert calls == ["media", "processing"]
    with mock.patch.object(db_topology, "cold_resume", counting):
        second = run_arm(ctx, "separate")
    assert second.doc["steps"]["separate"]["status"] == PASS
    assert calls == ["media", "processing"], "a finished cold resume must not be taken twice"


def test_a_passed_arm_is_not_run_again(tmp_path):
    ctx = build(tmp_path, "a", "shared")
    run_arm(ctx, "shared")
    before = len(ctx.world.calls)
    again = run_arm(ctx, "shared")
    assert again.ran == [] and len(ctx.world.calls) == before


def test_the_receipt_is_private_and_its_public_view_names_no_resource(tmp_path):
    ctx = build(tmp_path, "a", "separate")
    proof = run_arm(ctx, "separate")
    assert stat.S_IMODE(proof.path.stat().st_mode) == 0o600
    shown = json.dumps(public(proof, "separate"))
    assert "sim-media-cluster" not in shown and "arn:aws" not in shown and "http" not in shown
    assert proof.doc["steps"]["separate"]["private"]["clusters"] == {
        "media": "sim-media-cluster",
        "processing": "sim-processing-cluster",
    }


def test_a_longer_auto_pause_lengthens_the_wait_for_the_pause(tmp_path):
    ctx = build(tmp_path, "a", "shared", auto_pause_seconds=3600)
    started = ctx.clock()
    proof = run_arm(ctx, "shared", pause_minutes=5)
    assert proof.doc["steps"]["shared"]["status"] == PASS
    assert public(proof, "shared")["configured"]["cluster"]["seconds_until_auto_pause"] == 3600
    assert ctx.clock() - started > 3600  # it waited out the pause rather than giving up at 5 min


def test_the_arm_options_are_bounded(tmp_path):
    ctx = build(tmp_path, "a", "shared")
    for kwargs in ({"samples": 4}, {"samples": 201}, {"concurrency": 0}, {"concurrency": 9}):
        with pytest.raises(ProofError):
            run_arm(ctx, "shared", **kwargs)
    with pytest.raises(ProofError, match="shared, separate or compare"):
        db_topology.run(ctx, arm_name="third")


# ---- cluster selection ------------------------------------------------------------------------
def journal_with(ctx, **resources):
    path = ctx.state_dir / "deploy-journal.json"
    journal = deploy.DeployJournal(path, station="sim-station", environment=ctx.world.env)
    journal.mutate(lambda d: d["resources"].clear() or d["resources"].update(resources))


def test_a_shared_stack_with_two_clusters_in_the_journal_needs_an_explicit_one(tmp_path):
    ctx = build(tmp_path, "a", "shared")
    journal_with(ctx, db_clusters=["one", "two"])
    with pytest.raises(ProofError, match="--cluster"):
        db_topology.cluster_ids(ctx)
    assert db_topology.cluster_ids(ctx, shared="two") == {"cluster": "two"}


def test_a_separate_stack_is_told_apart_by_the_journals_logical_names_or_by_override(tmp_path):
    ctx = build(tmp_path, "a", "separate")
    journal_with(ctx, db_clusters=["x", "y"])  # a journal written before logical names
    with pytest.raises(ProofError, match="--media-cluster"):
        db_topology.cluster_ids(ctx)
    assert db_topology.cluster_ids(ctx, media="x", processing="y") == {
        "media": "x",
        "processing": "y",
    }
    journal_with(
        ctx,
        db_clusters=["x", "y"],
        db_logical={"x": "ProcessingDatabaseCluster", "y": "DatabaseCluster"},
    )
    assert db_topology.cluster_ids(ctx) == {"media": "y", "processing": "x"}
    with pytest.raises(ProofError, match="--media-cluster"):
        db_topology.cluster_ids(ctx, media="x", processing="x")


def test_the_topology_is_read_from_the_stack_outputs():
    assert db_topology.topology_of(SimpleNamespace(outputs={"DatabaseEndpoint": "h"})) == "shared"
    assert db_topology.topology_of(SimpleNamespace(outputs={})) == "shared"
    assert (
        db_topology.topology_of(SimpleNamespace(outputs={"DatabaseTopology": "separate"}))
        == "separate"
    )
    assert (
        db_topology.topology_of(SimpleNamespace(outputs={"ProcessingDatabaseEndpoint": "h"}))
        == "separate"
    )


def test_a_stack_deployed_by_the_pipeline_exposes_what_the_harness_reads():
    from scripts.aws.v1.definitions import SEPARATE, DatabaseOptions, template

    separate = template(DatabaseOptions(SEPARATE))["Outputs"]
    assert "DatabaseTopology" in separate and "ProcessingDatabaseEndpoint" in separate
    assert "DatabaseTopology" not in template()["Outputs"]


# ---- the primitives ---------------------------------------------------------------------------
class FakeTransport:
    def __init__(self, reply=None, error=None):
        self.reply, self.error, self.calls = reply, error, []

    def call(self, service, operation, payload, *, deadline):
        self.calls.append((service, operation, payload))
        validate_arguments(service, operation, payload)  # the operator contract, as live
        if self.error:
            raise self.error
        return self.reply


def fake_ctx(**overrides):
    values = dict(
        clock=time.monotonic,
        sleep=lambda _s: None,
        simulated=False,
        hooks={"media_api": "fn-MediaApi", "processing_api": "fn-ProcessingApi"},
        config={"alias": "live"},
        deadline=lambda seconds: time.monotonic() + seconds,
    )
    values.update(overrides)
    return SimpleNamespace(**values)


def ready(service="processing", **extra):
    return {
        "StatusCode": 200,
        "FunctionError": False,
        "Payload": {"service": service, "ready": True, **extra},
    }


def test_the_probe_is_the_owners_alias_ready_event_within_the_operator_contract():
    transport = FakeTransport(ready("media"))
    ok, ms = db_topology.probe(fake_ctx(), transport, "media")
    assert ok and ms >= 0
    ((service, operation, payload),) = transport.calls
    assert (service, operation) == ("lambda", "invoke")
    assert payload == {
        "FunctionName": "fn-MediaApi",
        "Qualifier": "live",
        "InvocationType": "RequestResponse",
        "Payload": {"dc2_operation": "ready"},
    }


@pytest.mark.parametrize(
    "reply,error",
    [
        ({"StatusCode": 200, "FunctionError": "Unhandled", "Payload": {}}, None),
        (
            {
                "StatusCode": 500,
                "FunctionError": False,
                "Payload": {"service": "media", "ready": True},
            },
            None,
        ),
        (ready("processing"), None),  # the wrong owner answered
        (
            {
                "StatusCode": 200,
                "FunctionError": False,
                "Payload": {"service": "media", "ready": False},
            },
            None,
        ),
        ({"StatusCode": 200, "FunctionError": False, "Payload": "not an object"}, None),
        (None, OperationError("V1 operator request failed")),
    ],
)
def test_anything_but_a_clean_ready_reply_is_a_failed_probe(reply, error):
    ok, _ = db_topology.probe(fake_ctx(), FakeTransport(reply, error), "media")
    assert ok is False


def test_latency_percentiles_use_successes_and_count_failures():
    samples = [(True, float(ms)) for ms in range(10, 110, 10)] + [(False, 9999.0)]
    stats = db_topology.latency_stats(samples)
    assert stats == {"count": 11, "failures": 1, "p50_ms": 50.0, "p95_ms": 100.0, "max_ms": 100.0}
    nothing = db_topology.latency_stats([(False, 1.0)])
    assert nothing["p50_ms"] is None and nothing["failures"] == 1


def test_settle_gives_up_instead_of_timing_a_cluster_that_never_answers():
    clock = sim.VirtualClock()
    ctx = fake_ctx(clock=clock.monotonic, sleep=clock.sleep)
    transport = FakeTransport(
        reply={
            "StatusCode": 200,
            "FunctionError": False,
            "Payload": {"service": "media", "ready": False},
        }
    )
    assert db_topology.settle(ctx, transport, "media", timeout=60) is False
    assert clock.t - clock.t0 >= 60


def test_live_load_runs_probes_on_threads_and_stops_them():
    seen = threading.Event()
    count = []

    class Transport(FakeTransport):
        def call(self, *args, **kwargs):
            count.append(threading.current_thread().name)
            if len(count) >= 6:
                seen.set()
            time.sleep(0.001)
            return super().call(*args, **kwargs)

    transport = Transport(ready("media"))
    with db_topology.load(fake_ctx(), transport, "media", 3) as stats:
        assert seen.wait(5)
    settled = len(count)
    time.sleep(0.05)
    assert len(count) == settled, "no worker may outlive the load"
    assert stats["requests"] >= 6 and stats["ok"] == stats["requests"]
    assert len(set(count)) > 1, "concurrency must use more than one thread"


def test_acu_hours_are_summed_from_per_minute_averages_and_cost_adds_the_fixed_share():
    window = 3600.0

    class Aws:
        def call(self, service, operation, payload, *, deadline):
            assert (service, operation) == ("cloudwatch", "get-metric-statistics")
            assert payload["Period"] == 60 and payload["Statistics"] == ["Average", "Maximum"]
            assert payload["Dimensions"] == [{"Name": "DBClusterIdentifier", "Value": "c1"}]
            return {
                "Datapoints": [{"Average": 0.5, "Maximum": 1.0}] * 30
                + [{"Average": 0.0, "Maximum": 0.0}] * 30
            }

    ctx = fake_ctx(aws=Aws())
    row = db_topology.acu_hours(ctx, "c1", since=1_000_000.0, until=1_000_000.0 + window)
    assert row == {"acu_hours": 0.25, "datapoints": 60, "window_minutes": 60.0, "max_acu": 1.0}
    cost = db_topology.cost_section(
        ctx, {"a": "c1", "b": "c1"}, since=1_000_000.0, until=1_000_000.0 + window
    )
    compute = 0.25 * deploy.ACU_HOUR
    fixed = deploy.EXTRA_CLUSTER_MONTH_USD / db_topology.MONTH_HOURS
    assert cost["clusters"]["a"]["compute_usd"] == pytest.approx(compute, abs=1e-4)
    assert cost["clusters"]["a"]["fixed_usd"] == pytest.approx(fixed, abs=1e-4)
    assert cost["total_usd"] == pytest.approx(2 * (compute + fixed), abs=1e-3)
    assert "Cost Explorer" in cost["basis"]


def test_a_cluster_still_awake_after_the_wait_is_named_and_the_wake_test_is_not_run(tmp_path):
    ctx = build(tmp_path, "a", "separate", faults=("never-pauses",))
    transport = ctx.sdk(ctx.scope)
    clusters = {"media": "sim-media-cluster", "processing": "sim-processing-cluster"}
    result = db_topology.peer_wake(
        ctx,
        transport,
        clusters,
        load_seconds=10,
        concurrency=2,
        pause_minutes=1,
        checkpoint=lambda kind: None,
    )
    assert result["measured"] is False
    assert "media, processing" in result["reason"]


# ---- the comparison ---------------------------------------------------------------------------
def test_the_comparison_applies_the_fixed_rule_and_never_decides_the_merge(both):
    _, proof = both
    data = public(proof, "compare")
    assert proof.doc["steps"]["compare"]["status"] == PASS
    assert data["decision_rule"] == {
        "both_arms_fully_measured": True,
        "coupling_observed_when_shared": True,
        "separate_does_not_wake_the_peer": True,
        "separate_peer_slowdown_within_limit": True,
        "separate_cold_resume_not_slower": True,
        "separate_warm_p95_not_slower": True,
        "separate_extra_cost_within_limit": True,
    }
    assert data["warrants_change"] is True  # in the simulation; the receipt is SIMULATED
    assert data["merge_decision"] == "pending"
    assert data["default"].startswith("shared (V1)")
    assert proof.overall() == "SIMULATED"
    assert data["limits"]["extra_usd_per_month"] == 2.0


def mutate(both_result, change):
    ctx, proof = both_result
    proof.doc["steps"]["shared"] = copy.deepcopy(proof.doc["steps"]["shared"])
    proof.doc["steps"]["separate"] = copy.deepcopy(proof.doc["steps"]["separate"])
    change(proof.doc["steps"]["shared"]["public"], proof.doc["steps"]["separate"]["public"])
    return db_topology.compare(proof)["public"]["decision_rule"], proof


@pytest.mark.parametrize(
    "name,change",
    [
        (
            "separate_does_not_wake_the_peer",
            lambda one, two: two["isolation"]["peer_wake"].update(peer_woken=True),
        ),
        (
            "separate_does_not_wake_the_peer",
            lambda one, two: two["isolation"]["peer_wake"].update(same_cluster=True),
        ),
        (
            "separate_peer_slowdown_within_limit",
            lambda one, two: two["isolation"]["peer_slowdown"].update(slowdown_p95=1.26),
        ),
        (
            "separate_peer_slowdown_within_limit",
            lambda one, two: two["isolation"]["peer_slowdown"].update(slowdown_p95=None),
        ),
        (
            "separate_cold_resume_not_slower",
            lambda one, two: two["cold_resume"]["media"].update(
                resume_seconds=one["cold_resume"]["cluster"]["resume_seconds"] + 15.1
            ),
        ),
        (
            "separate_cold_resume_not_slower",
            lambda one, two: two["cold_resume"]["media"].update(resume_seconds=None),
        ),
        (
            "separate_warm_p95_not_slower",
            lambda one, two: two["warm"]["processing"].update(
                p95_ms=one["warm"]["processing"]["p95_ms"] * 1.21
            ),
        ),
        (
            "separate_extra_cost_within_limit",
            lambda one, two: two["cost"]["clusters"]["media"].update(compute_usd=5.0),
        ),
        (
            "both_arms_fully_measured",
            lambda one, two: one["cold_resume"]["cluster"].update(measured=False),
        ),
        (
            "coupling_observed_when_shared",
            lambda one, two: (
                one["isolation"]["peer_wake"].update(peer_woken=False),
                one["isolation"]["peer_slowdown"].update(slowdown_p95=1.0),
            ),
        ),
    ],
)
def test_each_part_of_the_rule_can_fail_the_comparison_on_its_own(both, name, change):
    rule, proof = mutate(both, change)
    assert rule[name] is False
    assert [k for k, v in rule.items() if not v] == [name] or name == "both_arms_fully_measured"
    assert db_topology.compare(proof)["public"]["warrants_change"] is False


def test_the_comparison_needs_both_arms(tmp_path):
    ctx = build(tmp_path, "a", "shared")
    run_arm(ctx, "shared")
    proof = db_topology.run(ctx, arm_name="compare")
    assert proof.doc["steps"]["compare"]["status"] == FAIL
    assert "separate arm has not been run" in proof.doc["steps"]["compare"]["public"]["error"]


def test_the_projected_extra_cost_is_a_second_clusters_fixed_cost_plus_measured_compute(both):
    data = public(both[1], "compare")
    assert data["projected_extra_usd_per_month"] >= deploy.EXTRA_CLUSTER_MONTH_USD
    assert "one such window" in data["projection_basis"]


# ---- the command line -------------------------------------------------------------------------
SCOPE = [
    "--profile",
    "dc2-agent",
    "--region",
    "ap-southeast-1",
    "--account",
    "123456789012",
    "--run-id",
    "t",
    "--dry-run",
]


def test_the_evidence_cli_has_the_db_topology_subcommand_with_documented_defaults():
    args = evidence.build_parser().parse_args(["db-topology", "--arm", "separate", *SCOPE])
    assert (
        args.arm,
        args.samples,
        args.pause_wait_minutes,
        args.resume_timeout,
        args.load_seconds,
        args.load_concurrency,
        args.tail_minutes,
    ) == ("separate", 30, 30, 300, 60, 4, 10)
    assert evidence.SESSION["db-topology"] == "window"


@pytest.mark.parametrize("arm", ["shared", "separate"])
def test_a_dry_run_of_each_arm_completes_against_the_matching_simulation(arm):
    out = io.StringIO()
    code = evidence.main(
        ["db-topology", "--arm", arm, "--samples", "6", "--tail-minutes", "0", *SCOPE], stdout=out
    )
    report = json.loads(out.getvalue())
    assert code == 0 and report["overall"] == "SIMULATED"
    assert report["steps"][arm]["status"] == PASS and report["steps"][arm]["arm"] == arm


def test_compare_alone_in_a_dry_run_reports_the_missing_arms():
    out = io.StringIO()
    code = evidence.main(["db-topology", "--arm", "compare", *SCOPE], stdout=out)
    assert code == 1
    assert "has not been run" in json.loads(out.getvalue())["steps"]["compare"]["error"]


def test_rehearsal_includes_the_database_comparison():
    out = io.StringIO()
    assert evidence.rehearse(argparse.Namespace(run_id="rehearsal", release_plan=None), out) == 0
    steps = json.loads(out.getvalue())["harnesses"]["db-topology"]["steps"]
    assert steps == {"shared": PASS, "separate": PASS, "compare": PASS}


def test_the_existing_pause_harness_says_what_to_do_on_a_two_cluster_stack(tmp_path):
    from scripts.aws.v1.proof import spend

    ctx = build(tmp_path, "a", "separate")
    with pytest.raises(ProofError, match="pass --cluster"):
        spend.cluster_id(ctx)
    assert spend.cluster_id(ctx, "sim-media-cluster") == "sim-media-cluster"
