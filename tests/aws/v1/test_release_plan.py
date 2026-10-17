"""release-plan (#150): plan.json and its bundles from the deploy journal, build evidence and the
registry, against the simulated account. Nothing here reaches AWS."""

import argparse
import io
import json
import stat

import pytest

from scripts.aws.v1 import evidence
from scripts.aws.v1.artifacts import validate_bundle
from scripts.aws.v1.proof import release, release_plan, sim
from scripts.aws.v1.proof.core import ProofError

pytestmark = pytest.mark.unmeasured
GOOD_IDS = {"media": "sha256:" + "4" * 64, "processing": "sha256:" + "5" * 64,
            "worker": "sha256:" + "6" * 64}
BAD_IDS = {"media": "sha256:" + "7" * 64, "processing": "sha256:" + "8" * 64,
           "worker": "sha256:" + "9" * 64}


def stack(tmp_path, *faults):
    world = sim.SimWorld(faults=faults)
    ctx = sim.build(argparse.Namespace(run_id="t", dry_run=True), session="closed", sql=False,
                    tmp=tmp_path / "state", world=world)
    builds = {
        "baseline": sim.build_evidence(tmp_path / "baseline.json", source_sha="a" * 40),
        "good": sim.build_evidence(tmp_path / "good.json", source_sha="b" * 40,
                                   config_ids=GOOD_IDS),
        "bad": sim.build_evidence(tmp_path / "bad.json", source_sha="c" * 40, config_ids=BAD_IDS),
    }
    return world, ctx, builds


def make(ctx, builds, tmp_path, owner="media", *, bad=False, **changes):
    options = {
        "owner": owner, "baseline_evidence": builds["baseline"],
        "good": {"run_id": "g1", "evidence": builds["good"]},
        "bad": bad if isinstance(bad, dict) else (
            {"run_id": "b1", "evidence": builds["bad"]} if bad else None),
        "tests_passed": 12, "target_revision": "m0007", "attest_schema_unchanged": True,
        "out": tmp_path / "plan"}
    options.update(changes)
    return release_plan.run(ctx, **options)


def plan_of(tmp_path):
    return json.loads((tmp_path / "plan" / "plan.json").read_text())


def test_a_media_plan_names_the_deployed_baseline_and_a_new_good_image_with_its_own_definition(
        tmp_path):
    world, ctx, builds = stack(tmp_path)
    summary = make(ctx, builds, tmp_path)
    plan = plan_of(tmp_path)
    assert summary["registered_definitions"] == 1 and summary["owner"] == "media"
    assert release.load_plan(tmp_path / "plan" / "plan.json")["owner"] == "media"
    deployed = f"{world.repository('media')}@{sim.BASELINE_DIGEST['media']}"
    assert plan["baseline"]["image_uri"] == deployed
    assert plan["baseline"]["migration_definition"] == ctx.outputs[
        "MediaMigrationTaskDefinitionArn"]
    assert plan["good"]["migration_definition"] != plan["baseline"]["migration_definition"]
    assert plan["registered_definitions"] == [plan["good"]["migration_definition"]]
    assert "bad" not in plan and "worker_definition" not in plan["good"]


def test_the_registered_definition_is_the_deployed_one_with_only_its_image_swapped(tmp_path):
    world, ctx, builds = stack(tmp_path)
    make(ctx, builds, tmp_path)
    good = plan_of(tmp_path)["good"]
    registered = world.definitions[good["migration_definition"]]
    deployed = world.ecs_describe_task_definition(
        {"taskDefinition": ctx.outputs["MediaMigrationTaskDefinitionArn"]})["taskDefinition"]
    assert registered["family"] == deployed["family"]
    assert registered["taskRoleArn"] == deployed["taskRoleArn"]
    assert registered["executionRoleArn"] == deployed["executionRoleArn"]
    assert registered["containerDefinitions"][0]["image"] == good["image_uri"]
    assert registered["containerDefinitions"][0]["logConfiguration"] == deployed[
        "containerDefinitions"][0]["logConfiguration"]


def test_every_bundle_passes_the_release_gate_and_every_file_is_private(tmp_path):
    _, ctx, builds = stack(tmp_path)
    make(ctx, builds, tmp_path, bad=True)
    plan = plan_of(tmp_path)
    for role in ("baseline", "good", "bad"):
        bundle = json.loads((tmp_path / "plan" / f"bundle-{role}.json").read_text())
        assert validate_bundle(bundle, owner="media")["api"]["manifest_digest"] == plan[role][
            "image_uri"].split("@")[1]
        compat = json.loads((tmp_path / "plan" / f"compat-{role}.json").read_text())
        assert compat["source_sha"] == bundle["api"]["source_sha"]
        assert compat["target_revision"] == "m0007" and compat["additive_only"] is True
    for path in (tmp_path / "plan").iterdir():
        assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_a_processing_plan_carries_worker_images_and_worker_definitions(tmp_path):
    world, ctx, builds = stack(tmp_path)
    summary = make(ctx, builds, tmp_path, "processing", bad=True, target_revision="p0005")
    plan = plan_of(tmp_path)
    assert summary["registered_definitions"] == 4 and len(plan["registered_definitions"]) == 4
    assert plan["baseline"]["worker_definition"] == ctx.outputs["WorkerTaskDefinitionArn"]
    for role in ("good", "bad"):
        worker = world.definitions[plan[role]["worker_definition"]]
        bundle = json.loads((tmp_path / "plan" / f"bundle-{role}.json").read_text())
        assert worker["containerDefinitions"][0]["image"].endswith(
            bundle["worker"]["manifest_digest"])
        assert set(bundle) == {"api", "worker"}
    assert release.load_plan(tmp_path / "plan" / "plan.json")["bad"]["image_uri"]


@pytest.mark.parametrize(("changes", "message"), [
    ({"attest_schema_unchanged": False}, "attest-schema-unchanged"),
    ({"tests_passed": 0}, "tests-passed"),
    ({"tests_passed": True}, "tests-passed"),
])
def test_unattested_inputs_are_refused_before_anything_is_read(tmp_path, changes, message):
    world, ctx, builds = stack(tmp_path)
    with pytest.raises(ProofError, match=message):
        make(ctx, builds, tmp_path, **changes)
    assert not world.calls


def test_build_evidence_of_a_different_build_than_the_deployed_one_is_refused(tmp_path):
    _, ctx, builds = stack(tmp_path)
    with pytest.raises(ProofError, match="not the build of the deployed"):
        make(ctx, builds, tmp_path, baseline_evidence=builds["good"])


def test_failed_build_evidence_is_refused(tmp_path):
    _, ctx, builds = stack(tmp_path)
    failed = sim.build_evidence(tmp_path / "failed.json", source_sha="d" * 40,
                                config_ids=GOOD_IDS, failures=["media: image builds"])
    with pytest.raises(ProofError, match="LOCAL_ARTIFACT_PASS"):
        make(ctx, builds, tmp_path, good={"run_id": "g1", "evidence": failed})


def test_a_good_image_that_is_the_deployed_one_would_move_nothing_and_is_refused(tmp_path):
    world, ctx, builds = stack(tmp_path)
    with pytest.raises(ProofError, match="shares an image with the baseline"):
        make(ctx, builds, tmp_path, good={"run_id": world.env, "evidence": builds["good"]})


def test_a_scan_with_a_high_finding_blocks_the_plan(tmp_path):
    _, ctx, builds = stack(tmp_path, "scan-high")
    with pytest.raises(ProofError, match="HIGH/CRITICAL"):
        make(ctx, builds, tmp_path)
    assert not (tmp_path / "plan" / "plan.json").exists()


def test_a_scan_that_is_not_complete_blocks_the_plan(tmp_path):
    _, ctx, builds = stack(tmp_path, "scan-pending")
    with pytest.raises(ProofError, match="not COMPLETE"):
        make(ctx, builds, tmp_path)


def test_a_stack_whose_definition_was_updated_since_the_deploy_is_refused(tmp_path):
    world, ctx, builds = stack(tmp_path)
    arn = ctx.outputs["MediaMigrationTaskDefinitionArn"]
    spec = world.ecs_describe_task_definition({"taskDefinition": arn})["taskDefinition"]
    spec["containerDefinitions"][0]["image"] = f"{world.repository('media')}@sha256:" + "e" * 64
    world.definitions[arn] = spec
    with pytest.raises(ProofError, match="no longer holds the baseline image"):
        make(ctx, builds, tmp_path)


def test_a_failure_after_registering_retires_the_revisions_it_created(tmp_path):
    world, ctx, builds = stack(tmp_path)
    failed = sim.build_evidence(tmp_path / "failed.json", source_sha="d" * 40,
                                config_ids=BAD_IDS, failures=["media: image builds"])
    with pytest.raises(ProofError, match="LOCAL_ARTIFACT_PASS"):
        make(ctx, builds, tmp_path, bad={"run_id": "b1", "evidence": failed})
    registered = [d for d in world.definitions.values() if d["family"].endswith("migration")]
    assert len(registered) == 1 and registered[0]["status"] == "INACTIVE"  # the good one
    assert not (tmp_path / "plan" / "plan.json").exists()


def test_deregister_retires_exactly_the_revisions_the_plan_lists(tmp_path):
    world, ctx, builds = stack(tmp_path)
    make(ctx, builds, tmp_path, "processing", bad=True, target_revision="p0005")
    listed = plan_of(tmp_path)["registered_definitions"]
    result = release_plan.deregister(ctx, tmp_path / "plan" / "plan.json")
    assert len(result["deregistered"]) == 4
    assert {a for a, d in world.definitions.items() if d["status"] == "INACTIVE"} == set(listed)


# ---- command line ----------------------------------------------------------------------------
def cli(ctx, *argv):
    out = io.StringIO()
    code = evidence.main(["release-plan", "--profile", "dc2-agent", "--region", "ap-southeast-1",
                          "--account", "123456789012", "--run-id", "r",
                          "--state-dir", str(ctx.state_dir), *argv],
                         stdout=out, factory=lambda args: ctx)
    return code, json.loads(out.getvalue())


def test_the_command_writes_the_plan_next_to_the_state_directory_by_default(tmp_path):
    _, ctx, builds = stack(tmp_path)
    code, out = cli(ctx, "--owner", "media", "--baseline-evidence", str(builds["baseline"]),
                    "--good-run-id", "g1", "--good-evidence", str(builds["good"]),
                    "--tests-passed", "12", "--target-revision", "m0007",
                    "--attest-schema-unchanged")
    assert code == 0 and out["plan"] == str(ctx.state_dir / "release" / "plan.json")
    assert set(out["images"]) == {"baseline", "good"}


def test_the_command_lists_what_is_missing_instead_of_guessing(tmp_path):
    _, ctx, _ = stack(tmp_path)
    code, out = cli(ctx, "--owner", "media")
    assert code == 1 and "--baseline-evidence" in out["error"]


def test_the_command_has_no_simulation_of_its_own(tmp_path):
    out = io.StringIO()
    code = evidence.main(["release-plan", "--profile", "dc2-agent", "--region", "ap-southeast-1",
                          "--account", "123456789012", "--run-id", "r", "--dry-run"], stdout=out)
    assert code == 1 and "rehearse" in json.loads(out.getvalue())["error"]
