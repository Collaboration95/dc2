"""Splitting an established shared stack into one Aurora cluster per service, in place (#94).

Offline, against the simulation from test_deploy.py: what is proved is the order of the
steps, what each is given, that nothing is attempted while Processing has work, that a failed
run resumes after the last state it reached, and that nothing is dropped before a verified
smoke. That CloudFormation clones the cluster, how long it takes and what survives is the
rehearsal's evidence (docs/results), not this module's.
"""

import io
import json
import stat
import time

import pytest
from test_deploy import ARGS, Rig, no_disk_sync  # noqa: F401  (an autouse fixture)

from scripts.aws.v1 import deploy
from scripts.aws.v1.definitions import SEPARATE, SHARED, DatabaseOptions
from scripts.aws.v1.deploy import AwaitingExecute, DeployError, DeployJournal

pytestmark = pytest.mark.unmeasured
PREFIX = "/dc2/dc2-live/"
TOUCHED = PREFIX + "activity/processing/touched"
DSNS = ("processing_runtime_dsn", "processing_migration_dsn")


@pytest.fixture
def live(tmp_path):
    """An established environment on V1's shared layout that has opted in to being split."""
    rig = Rig(tmp_path, run_id="live", persistent=True, split_from_shared=True)
    rig.deploy()
    return rig


def split(rig):
    pipeline = rig.pipeline()
    pipeline.split_database()
    return pipeline


def ops(rig, name, since=0):
    return [(i, c[2]) for i, c in enumerate(rig.sim.calls) if i >= since and c[1] == name]


def dsn_host(rig, key):
    return rig.sim.param_values[PREFIX + key].split("@")[1].split(":")[0]


# ---- the order, and what each step is given ------------------------------------------------
def test_the_split_runs_every_step_in_order_and_ends_verified(live):
    split(live)
    meta = live.journal.view()
    names = [n for n in deploy.ordered_steps(meta) if n.startswith("split-")]
    assert names == [
        "split-precheck",
        "split-snapshot",
        "split-clone",
        "split-login",
        "split-freeze",
        "split-switch",
        "split-verify",
    ]
    assert all(meta["steps"][n]["status"] == "done" for n in names)
    assert meta["database_split"]["state"] == "verified"
    assert meta["database"] == {
        "topology": "separate",
        "auto_pause_seconds": 300,
        "max_capacity": 2,
        "clone_processing": True,
    }
    assert len(live.sim.clusters) == 2 and len(live.sim.instances) == 2


def test_processing_is_checked_idle_before_anything_changes_and_the_check_is_recorded(live):
    start = len(live.sim.calls)
    split(live)
    calls = live.sim.calls[start:]
    first_change = next(i for i, c in enumerate(calls) if deploy.is_mutating(c[1]))
    checks = {c[1] for c in calls[:first_change]}
    assert {"get-parameter", "get-queue-attributes", "list-tasks"} <= checks
    evidence = live.journal.view()["database_split"]["idle_before"]
    assert evidence["quiet"] is True
    assert (evidence["queued_messages"], evidence["running_tasks"]) == (0, 0)


def test_the_stack_is_updated_only_after_the_snapshot_is_available(live):
    start = len(live.sim.calls)
    split(live)
    snapshot = ops(live, "create-db-cluster-snapshot", start)
    assert len(snapshot) == 1
    name = snapshot[0][1]["DBClusterSnapshotIdentifier"]
    assert name == "dc2-live-pre-split-20261016"  # the day the test's clock says
    assert snapshot[0][1]["Tags"]  # tagged like every other resource of the run
    first_poll = ops(live, "describe-db-cluster-snapshots", start)[0][0]
    clone_update = ops(live, "execute-change-set", start)
    assert snapshot[0][0] < first_poll < clone_update[0][0]
    assert live.journal.view()["database_split"]["snapshot"] == name


def test_the_clone_update_adds_processings_cluster_and_removes_only_the_encoders_old_rule(live):
    split(live)
    changes = live.journal.view()["steps"]["split-clone"]["detail"]["changes"]
    added = {c["LogicalResourceId"] for c in changes if c["Action"] == "Add"}
    assert {"ProcessingDatabaseCluster", "ProcessingDatabaseInstance"} <= added
    assert [c["LogicalResourceId"] for c in changes if c["Action"] == "Remove"] == [
        "DatabaseFromWorker"
    ]
    # Media's cluster, instance and group are not in the change set: nothing about them moves.
    touched = {c["LogicalResourceId"] for c in changes}
    assert not touched & {"DatabaseCluster", "DatabaseInstance", "DatabaseSecurityGroup"}
    assert all(c["Replacement"] != "True" for c in changes)


def test_any_other_removal_still_fails_the_update(live):
    with pytest.raises(DeployError, match="removes Distribution"):
        deploy.review_changes(
            [
                {
                    "ResourceChange": {
                        "Action": "Remove",
                        "LogicalResourceId": "Distribution",
                        "ResourceType": "AWS::CloudFront::Distribution",
                    }
                }
            ],
            "UPDATE",
            removable=("DatabaseFromWorker",),
        )


def test_each_bootstrap_task_is_given_only_one_domains_logins(live):
    split(live)
    before = len(live.sim.bootstrap_inputs) - 2  # the first deploy ran none (it is established)
    login, freeze = live.sim.bootstrap_inputs[before:]
    outputs = json.loads((live.s.state_dir / "outputs.json").read_text())
    assert set(login["databases"]) == set(freeze["databases"]) == {"processing"}
    # The clone's own master credential, then the old cluster's: never each other's.
    assert login["databases"]["processing"]["host"] == outputs["ProcessingDatabaseEndpoint"]
    assert freeze["databases"]["processing"]["host"] == outputs["MediaDatabaseEndpoint"]
    assert (
        login["databases"]["processing"]["password"]
        != freeze["databases"]["processing"]["password"]
    )
    for sent in (login, freeze):
        assert set(sent["role_passwords"]) == {"processing_migrator", "processing_runtime"}
        assert not any("media" in role for role in sent["role_passwords"])
    # The old cluster's passwords are throwaways: nothing published or kept names them.
    assert not set(freeze["role_passwords"].values()) & set(login["role_passwords"].values())
    published = " ".join(live.sim.param_values.values())
    assert not any(v in published for v in freeze["role_passwords"].values())


def test_the_old_copy_is_frozen_before_the_dsn_moves_and_the_clone_is_ready_before_both(live):
    start = len(live.sim.calls)
    media_dsn = live.sim.param_values[PREFIX + "media_runtime_dsn"]
    split(live)
    runs = ops(live, "run-task", start)
    puts = [
        i
        for i, p in ops(live, "put-parameter", start)
        if p["Name"].endswith(DSNS)  # the two Processing DSNs
    ]
    assert len(runs) == 2 and len(puts) == 2
    assert runs[0][0] < runs[1][0] < puts[0] < puts[1]
    # Processing's DSNs now name the clone (with the new passwords); Media's is untouched.
    outputs = json.loads((live.s.state_dir / "outputs.json").read_text())
    for key in DSNS:
        assert dsn_host(live, key) == outputs["ProcessingDatabaseEndpoint"]
        assert live.sim.param_values[PREFIX + key].endswith("/processing_db")
    assert live.sim.param_values[PREFIX + "media_runtime_dsn"] == media_dsn
    password = live.sim.bootstrap_inputs[-2]["role_passwords"]["processing_runtime"]
    assert password in live.sim.param_values[PREFIX + "processing_runtime_dsn"]
    assert not live.s.state_dir.joinpath("split-passwords.json").exists()  # nothing kept


def test_the_smoke_runs_last_and_marks_the_split_verified(live):
    start = len(live.gateway.requests)
    split(live)
    assert ("GET", "/api/processing/health") in live.gateway.requests[start:]
    assert live.journal.view()["steps"]["split-verify"]["detail"]["checks"]


def test_a_smoke_that_fails_at_first_is_retried_while_warm_lambdas_pick_up_the_new_dsn(live):
    # A warm environment is refused once by the old cluster before it re-reads its DSN.
    live.gateway.login = [503, 503, 200]
    pipeline = split(live)
    assert live.journal.view()["database_split"]["state"] == "verified"
    assert pipeline.s.database.clone_processing is True


# ---- Processing must be idle ---------------------------------------------------------------
def queue_url(live, name="ProcessingWorkQueueUrl"):
    return json.loads((live.s.state_dir / "outputs.json").read_text())[name]


@pytest.mark.parametrize("why", ["queued", "running", "not_quiet"])
def test_nothing_is_attempted_while_processing_has_work(live, why):
    start = len(live.sim.calls)
    if why == "queued":
        live.sim.queue_depth[queue_url(live)] = 1
    elif why == "running":
        live.sim.tasks["arn:aws:ecs:x:1:task/sim/encoder"] = {
            "definition": "worker",
            "polls": 0,
            "stopped": False,
        }
    else:  # a Processing writer touched the marker a moment ago
        live.sim.param_values[TOUCHED] = str(time.time())
    with pytest.raises(DeployError, match="Processing to be idle"):
        split(live)
    assert not [
        c for c in live.sim.calls[start:] if deploy.is_mutating(c[1]) and c[1] != "run-task"
    ]
    assert live.journal.view().get("database_split") is None
    assert live.journal.view().get("database", {"topology": "shared"})["topology"] == "shared"


def test_the_short_lane_queue_counts_as_work_too(live):
    live.sim.queue_depth[queue_url(live, "ProcessingShortWorkQueueUrl")] = 2
    with pytest.raises(DeployError, match="Processing to be idle"):
        split(live)


def test_without_execute_the_split_only_checks_and_reports(live):
    live.s.execute = False
    start = len(live.sim.calls)
    with pytest.raises(AwaitingExecute, match="Processing is idle"):
        split(live)
    assert not [c for c in live.sim.calls[start:] if deploy.is_mutating(c[1])]
    assert live.journal.view()["database_split"]["state"] == "started"


# ---- what the window cost -------------------------------------------------------------------
def run_until_switch(rig):
    pipeline = rig.pipeline()
    for name, action in (
        ("split-precheck", pipeline.step_split_precheck),
        ("split-snapshot", pipeline.step_split_snapshot),
        ("split-clone", pipeline.step_split_clone),
        ("split-login", pipeline.step_split_login),
        ("split-freeze", pipeline.step_split_freeze),
    ):
        pipeline.run_step(name, action)
    return pipeline


def test_no_processing_write_after_the_clone_is_reported_as_none(live):
    split(live)
    record = live.journal.view()["database_split"]
    assert record["writes_after_clone"] == "none"
    assert record["clone_to_switch_seconds"] >= 0


@pytest.mark.parametrize(
    "marker,expected", [(lambda now: str(now + 5), "possible"), (lambda now: "garbled", "unknown")]
)
def test_a_touch_after_the_clone_or_an_unreadable_marker_is_not_called_none(live, marker, expected):
    pipeline = run_until_switch(live)
    live.sim.param_values[TOUCHED] = marker(time.time())
    pipeline.run_step("split-switch", pipeline.step_split_switch)
    assert live.journal.view()["database_split"]["writes_after_clone"] == expected


def test_lost_passwords_stop_the_switch_instead_of_publishing_new_ones(live):
    pipeline = run_until_switch(live)
    live.s.state_dir.joinpath("split-passwords.json").unlink()
    with pytest.raises(DeployError, match="passwords are gone"):
        pipeline.step_split_switch()
    assert (
        dsn_host(live, "processing_runtime_dsn")
        != live.sim.bootstrap_inputs[-2]["databases"]["processing"]["host"]
    )


# ---- resuming -------------------------------------------------------------------------------
def test_a_failed_step_resumes_after_the_last_state_it_reached(live):
    live.sim.task_exit["bootstrap"] = 1  # the clone's reconcile fails
    with pytest.raises(DeployError, match="bootstrap task failed"):
        split(live)
    record = live.journal.view()["database_split"]
    assert record["state"] == "cloned"
    live.sim.task_exit.clear()
    before = len(live.sim.calls)
    split(live)
    assert live.journal.view()["database_split"]["state"] == "verified"
    # No second snapshot, no second change set, no second precheck's reads of the markers.
    assert not ops(live, "create-db-cluster-snapshot", before)
    assert not ops(live, "execute-change-set", before)
    assert not ops(live, "get-queue-attributes", before)


def test_a_deploy_between_two_attempts_does_not_start_the_split_over(live):
    live.sim.task_exit["bootstrap"] = 1
    with pytest.raises(DeployError):
        split(live)
    live.sim.task_exit.clear()
    live.deploy()  # archives the step log; renders the layout the journal now records
    before = len(live.sim.calls)
    assert not [c for c in live.sim.calls[before - 1 :] if c[1] == "create-db-cluster-snapshot"]
    split(live)
    assert not ops(live, "create-db-cluster-snapshot", before)
    assert live.journal.view()["database_split"]["state"] == "verified"


def test_a_deploy_after_the_split_renders_the_clone_layout_and_changes_nothing(live):
    split(live)
    start = len(live.sim.calls)
    live.deploy()
    # The same bytes as the split's own update: no change set is created, let alone executed.
    assert not ops(live, "create-change-set", start)
    assert not ops(live, "execute-change-set", start)
    assert live.journal.view()["database"]["clone_processing"] is True


def test_a_finished_split_is_not_repeated(live):
    split(live)
    start = len(live.sim.calls)
    split(live)
    assert not [c for c in live.sim.calls[start:] if deploy.is_mutating(c[1])]


# ---- who may split, and what `deploy` does meanwhile ------------------------------------------
def test_a_stack_that_did_not_opt_in_cannot_be_split(tmp_path):
    rig = Rig(tmp_path, run_id="live", persistent=True)
    rig.deploy()
    with pytest.raises(DeployError, match="--database-split-from-shared"):
        split(rig)


def test_only_an_established_environment_can_be_split(tmp_path):
    rig = Rig(tmp_path, run_id="live", persistent=True, split_from_shared=True)
    with pytest.raises(DeployError, match="established"):
        split(rig)


def test_an_environment_created_with_one_cluster_per_service_has_nothing_to_split(tmp_path):
    rig = Rig(tmp_path, run_id="live", persistent=True, database=DatabaseOptions(SEPARATE))
    rig.deploy()
    start = len(rig.sim.calls)
    assert split(rig) is not None
    assert not [c for c in rig.sim.calls[start:] if deploy.is_mutating(c[1])]
    assert "database_split" not in rig.journal.view()
    assert rig.s.database.clone_processing is False


def journal_with(tmp_path, options):
    journal = DeployJournal(tmp_path / "j.json", station="s", environment="e")
    journal.create({"account": "1", "database": options.as_dict()})
    return journal


def test_deploy_keeps_rendering_shared_until_the_split_has_run(tmp_path):
    journal = journal_with(tmp_path, DatabaseOptions())
    chosen = deploy.check_database_layout(journal, DatabaseOptions(SEPARATE), split_ok=True)
    assert chosen.topology == SHARED and chosen.clone_processing is False
    assert journal.view()["database"]["topology"] == "shared"


def test_without_the_opt_in_a_shared_journal_still_refuses_separate(tmp_path):
    journal = journal_with(tmp_path, DatabaseOptions())
    with pytest.raises(DeployError, match="topology shared"):
        deploy.check_database_layout(journal, DatabaseOptions(SEPARATE))


def test_a_split_stack_can_never_go_back_to_shared(tmp_path):
    journal = journal_with(tmp_path, DatabaseOptions(SEPARATE, clone_processing=True))
    with pytest.raises(DeployError, match="topology separate"):
        deploy.check_database_layout(journal, DatabaseOptions(), split_ok=True)


def test_a_split_stack_keeps_the_clone_option_whatever_a_later_run_asks_for(tmp_path):
    journal = journal_with(tmp_path, DatabaseOptions(SEPARATE, clone_processing=True))
    chosen = deploy.check_database_layout(journal, DatabaseOptions(SEPARATE, 900, 4))
    assert chosen == DatabaseOptions(SEPARATE, 900, 4, True)  # pause and ceiling still follow
    assert journal.view()["database"]["clone_processing"] is True


# ---- the cleanup, after a verified smoke ----------------------------------------------------
def test_nothing_is_dropped_before_the_split_is_verified(live):
    with pytest.raises(DeployError, match="not been verified"):
        live.pipeline().finish_database_split("smoke-1")
    pipeline = run_until_switch(live)
    pipeline.run_step("split-switch", pipeline.step_split_switch)  # switched, not yet verified
    with pytest.raises(DeployError, match="not been verified"):
        live.pipeline().finish_database_split("smoke-1")


def test_the_cleanup_names_the_smoke_that_allowed_it(live):
    split(live)
    with pytest.raises(DeployError, match="--verified-by"):
        live.pipeline().finish_database_split(None)
    with pytest.raises(DeployError, match="--verified-by"):
        live.pipeline().finish_database_split("not a label; rm -rf")
    assert live.journal.view()["database_split"]["state"] == "verified"
    assert live.sim.bootstrap_inputs[-1].get("action") is None  # nothing was dropped


def test_the_cleanup_drops_the_peers_database_on_each_cluster_and_writes_a_receipt(live):
    split(live)
    live.pipeline().finish_database_split("smoke-123-1")
    sent = live.sim.bootstrap_inputs[-1]
    assert sent["action"] == "drop-peers" and set(sent) == {"databases", "action"}
    assert sent["databases"]["media"]["host"] != sent["databases"]["processing"]["host"]
    record = live.journal.view()["database_split"]
    assert record["state"] == "cleaned" and record["verified_by"] == "smoke-123-1"
    path = live.s.state_dir / "database-split-receipt.json"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    receipt = json.loads(path.read_text())
    assert receipt["snapshot"] == "dc2-live-pre-split-20261016"
    assert receipt["writes_after_clone"] == "none" and receipt["idle_before"]["quiet"] is True
    assert "cluster" not in path.read_text().lower() or "clone_" in path.read_text()
    # A second call is a no-op, not a second drop.
    before = len(live.sim.calls)
    live.pipeline().finish_database_split("smoke-123-1")
    assert not [c for c in live.sim.calls[before:] if deploy.is_mutating(c[1])]


def test_a_failed_cleanup_leaves_the_split_verified_and_can_be_repeated(live):
    split(live)
    live.sim.task_exit["bootstrap"] = 1
    with pytest.raises(DeployError, match="bootstrap task failed"):
        live.pipeline().finish_database_split("smoke-1")
    assert live.journal.view()["database_split"]["state"] == "verified"
    live.sim.task_exit.clear()
    live.pipeline().finish_database_split("smoke-1")
    assert live.journal.view()["database_split"]["state"] == "cleaned"


# ---- teardown after a split -----------------------------------------------------------------
def test_teardown_takes_a_final_snapshot_per_cluster_and_reports_the_pre_split_one(tmp_path):
    rig = Rig(
        tmp_path, run_id="live", persistent=True, split_from_shared=True, confirm_run_id="live"
    )
    rig.deploy()
    split(rig)
    receipt = rig.teardown().receipt
    names = {c[2]["FinalDBSnapshotIdentifier"] for c in rig.ops("delete-db-cluster")}
    assert names == {"dc2-live-media-final", "dc2-live-processing-final"}
    kept = {r["id"] for r in receipt["resources_remaining"] if r["kind"] == "aurora-snapshot"}
    assert kept == names | {"dc2-live-pre-split-20261016"}


def test_a_throwaway_teardown_deletes_the_pre_split_snapshot_with_the_rest(tmp_path):
    rig = Rig(
        tmp_path,
        run_id="live",
        persistent=True,
        split_from_shared=True,
        skip_final_snapshot=True,
        confirm_run_id="live",
    )
    rig.deploy()
    split(rig)
    receipt = rig.teardown().receipt
    assert rig.sim.snapshots == {} and receipt["status"] == "CLEAN"
    assert [c[2]["DBClusterSnapshotIdentifier"] for c in rig.ops("delete-db-cluster-snapshot")] == [
        "dc2-live-pre-split-20261016"
    ]


# ---- the command line -----------------------------------------------------------------------
def run_cli(*argv):
    out = io.StringIO()
    code = deploy.main([*argv], stdout=out, stderr=io.StringIO())
    return code, json.loads(out.getvalue())


def test_the_split_actions_have_no_dry_run_and_need_an_existing_journal(tmp_path):
    for action in ("split-database", "finish-database-split"):
        code, body = run_cli(action, *ARGS, "--environment", "live", "--dry-run")
        assert code == 1 and "no dry run" in body["error"]
        code, body = run_cli(
            action, *ARGS, "--environment", "live", "--state-dir", str(tmp_path / "s"), "--execute"
        )
        assert code == 1 and "No journal" in body["error"]


def test_the_opt_in_flag_and_the_verified_by_label_are_parsed():
    args = deploy.build_parser().parse_args(
        [
            "finish-database-split",
            *ARGS,
            "--environment",
            "live",
            "--database-topology",
            "separate",
            "--database-split-from-shared",
            "--verified-by",
            "smoke-1-1",
        ]
    )
    assert args.database_split_from_shared is True and args.verified_by == "smoke-1-1"
    assert deploy.build_parser().parse_args(["deploy", *ARGS, "--run-id", "x"]).verified_by is None


def test_a_failed_stack_update_leaves_the_journal_on_the_layout_the_stack_still_has(live):
    live.sim.fail[("stack-complete", "dc2-live")] = "clone refused"
    with pytest.raises(DeployError, match="clone refused"):
        split(live)
    assert live.journal.view().get("database", {}).get("topology", SHARED) == SHARED
    assert live.s.database.topology == SHARED and live.s.database.clone_processing is False
    assert live.journal.view()["database_split"]["state"] == "snapshotted"
