"""release-plan (#150): plan.json and its bundles from the deploy journal, build evidence and the
registry, against the simulated account. Nothing here reaches AWS."""

import argparse
import hashlib
import io
import json
import stat

import pytest

from scripts.aws.v1 import evidence
from scripts.aws.v1.artifacts import validate_bundle
from scripts.aws.v1.proof import release, release_plan, sim
from scripts.aws.v1.proof.core import ProofError

pytestmark = pytest.mark.unmeasured
GOOD_IDS = {
    "media": "sha256:" + "4" * 64,
    "processing": "sha256:" + "5" * 64,
    "worker": "sha256:" + "6" * 64,
}
BAD_IDS = {
    "media": "sha256:" + "7" * 64,
    "processing": "sha256:" + "8" * 64,
    "worker": "sha256:" + "9" * 64,
}


def stack(tmp_path, *faults):
    world = sim.SimWorld(faults=faults)
    ctx = sim.build(
        argparse.Namespace(run_id="t", dry_run=True),
        session="closed",
        sql=False,
        tmp=tmp_path / "state",
        world=world,
    )
    builds = {
        "baseline": sim.build_evidence(tmp_path / "baseline.json", source_sha="a" * 40),
        "good": sim.build_evidence(
            tmp_path / "good.json", source_sha="b" * 40, config_ids=GOOD_IDS
        ),
        "bad": sim.build_evidence(tmp_path / "bad.json", source_sha="c" * 40, config_ids=BAD_IDS),
    }
    world.register_build("g1", builds["good"])
    world.register_build("b1", builds["bad"])
    return world, ctx, builds


def make(ctx, builds, tmp_path, owner="media", *, bad=False, **changes):
    options = {
        "owner": owner,
        "baseline_evidence": builds["baseline"],
        "good": {"run_id": "g1", "evidence": builds["good"]},
        "bad": bad
        if isinstance(bad, dict)
        else ({"run_id": "b1", "evidence": builds["bad"]} if bad else None),
        "tests_passed": 12,
        "target_revision": "m0007",
        "attest_schema_unchanged": True,
        "out": tmp_path / "plan",
    }
    options.update(changes)
    return release_plan.run(ctx, **options)


def plan_of(tmp_path):
    return json.loads((tmp_path / "plan" / "plan.json").read_text())


def test_a_media_plan_names_the_deployed_baseline_and_a_new_good_image_with_its_own_definition(
    tmp_path,
):
    world, ctx, builds = stack(tmp_path)
    summary = make(ctx, builds, tmp_path)
    plan = plan_of(tmp_path)
    assert summary["registered_definitions"] == 1 and summary["owner"] == "media"
    assert release.load_plan(tmp_path / "plan" / "plan.json")["owner"] == "media"
    deployed = f"{world.repository('media')}@{sim.BASELINE_DIGEST['media']}"
    assert plan["baseline"]["image_uri"] == deployed
    assert (
        plan["baseline"]["migration_definition"] == ctx.outputs["MediaMigrationTaskDefinitionArn"]
    )
    assert plan["good"]["migration_definition"] != plan["baseline"]["migration_definition"]
    assert plan["registered_definitions"] == [plan["good"]["migration_definition"]]
    assert "bad" not in plan and "worker_definition" not in plan["good"]


def test_the_registered_definition_is_the_deployed_one_with_only_its_image_swapped(tmp_path):
    world, ctx, builds = stack(tmp_path)
    make(ctx, builds, tmp_path)
    good = plan_of(tmp_path)["good"]
    registered = world.definitions[good["migration_definition"]]
    deployed = world.ecs_describe_task_definition(
        {"taskDefinition": ctx.outputs["MediaMigrationTaskDefinitionArn"]}
    )["taskDefinition"]
    assert registered["family"] == deployed["family"]
    assert registered["taskRoleArn"] == deployed["taskRoleArn"]
    assert registered["executionRoleArn"] == deployed["executionRoleArn"]
    assert registered["containerDefinitions"][0]["image"] == good["image_uri"]
    assert (
        registered["containerDefinitions"][0]["logConfiguration"]
        == deployed["containerDefinitions"][0]["logConfiguration"]
    )


def test_every_bundle_passes_the_release_gate_and_every_file_is_private(tmp_path):
    _, ctx, builds = stack(tmp_path)
    make(ctx, builds, tmp_path, bad=True)
    plan = plan_of(tmp_path)
    for role in ("baseline", "good", "bad"):
        bundle = json.loads((tmp_path / "plan" / f"bundle-{role}.json").read_text())
        assert (
            validate_bundle(bundle, owner="media")["api"]["manifest_digest"]
            == plan[role]["image_uri"].split("@")[1]
        )
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
            bundle["worker"]["manifest_digest"]
        )
        assert set(bundle) == {"api", "worker"}
    assert release.load_plan(tmp_path / "plan" / "plan.json")["bad"]["image_uri"]


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"attest_schema_unchanged": False}, "attest-schema-unchanged"),
        ({"tests_passed": 0}, "tests-passed"),
        ({"tests_passed": True}, "tests-passed"),
    ],
)
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
    failed = sim.build_evidence(
        tmp_path / "failed.json",
        source_sha="d" * 40,
        config_ids=GOOD_IDS,
        failures=["media: image builds"],
    )
    with pytest.raises(ProofError, match="LOCAL_ARTIFACT_PASS"):
        make(ctx, builds, tmp_path, good={"run_id": "g1", "evidence": failed})


def test_a_good_image_that_is_the_deployed_one_would_move_nothing_and_is_refused(tmp_path):
    world, ctx, builds = stack(tmp_path)
    with pytest.raises(ProofError, match="is the baseline's"):
        make(ctx, builds, tmp_path, good={"run_id": world.env, "evidence": builds["baseline"]})


def test_a_scan_with_a_high_finding_blocks_the_plan(tmp_path):
    _, ctx, builds = stack(tmp_path, "scan-high")
    with pytest.raises(ProofError, match="HIGH/CRITICAL"):
        make(ctx, builds, tmp_path)
    assert not (tmp_path / "plan" / "plan.json").exists()


def accept_file(tmp_path, *ids, **changes):
    entry = {
        "package": "glibc",
        "reason": "no fixed version in Debian 13",
        "reviewed_on": "2026-10-17",
    }
    body = {"accepted": [{"id": i, **entry} for i in ids], "verified_by": "apt list --upgradable"}
    body.update(changes)
    path = tmp_path / "accepted.json"
    path.write_text(json.dumps(body))
    return path


def scanned(world, *pairs, page=100):
    world.scan_findings, world.scan_page = list(pairs), page


def test_every_high_finding_accepted_passes_and_is_recorded_per_image(tmp_path):
    world, ctx, builds = stack(tmp_path)
    scanned(world, ("CVE-2026-1", "HIGH"), ("CVE-2026-2", "MEDIUM"))
    accept = accept_file(tmp_path, "CVE-2026-1", "CVE-2026-9")
    summary = make(ctx, builds, tmp_path, accept_unfixed=accept)
    scan = json.loads((tmp_path / "plan" / "bundle-good.json").read_text())["api"]["scan"]
    assert scan["blocking_high_critical"] == scan["fixable_high_critical"] == 0
    assert scan["accepted_high_critical"] == ["CVE-2026-1"]
    assert scan["accept_file_sha256"] == hashlib.sha256(accept.read_bytes()).hexdigest()
    assert scan["report_sha256"].startswith("sha256:")
    assert summary["accepted_unused"] == ["CVE-2026-9"]


def test_a_critical_finding_on_the_accept_list_passes(tmp_path):
    world, ctx, builds = stack(tmp_path)
    scanned(world, ("CVE-2026-7", "CRITICAL"))
    make(ctx, builds, tmp_path, accept_unfixed=accept_file(tmp_path, "CVE-2026-7"))
    scan = json.loads((tmp_path / "plan" / "bundle-baseline.json").read_text())["api"]["scan"]
    assert scan["accepted_high_critical"] == ["CVE-2026-7"]


def test_a_high_finding_missing_from_the_accept_list_still_blocks(tmp_path):
    world, ctx, builds = stack(tmp_path)
    scanned(world, ("CVE-2026-1", "HIGH"), ("CVE-2026-3", "HIGH"))
    with pytest.raises(ProofError, match="not on the accept list: CVE-2026-3"):
        make(ctx, builds, tmp_path, accept_unfixed=accept_file(tmp_path, "CVE-2026-1"))
    assert not (tmp_path / "plan" / "plan.json").exists()


def test_without_an_accept_list_any_high_finding_blocks_and_nothing_is_accepted(tmp_path):
    world, ctx, builds = stack(tmp_path)
    scanned(world, ("CVE-2026-1", "HIGH"))
    with pytest.raises(ProofError, match="1 HIGH/CRITICAL scan findings; the release gate"):
        make(ctx, builds, tmp_path)
    scanned(world, ("CVE-2026-2", "LOW"))
    make(ctx, builds, tmp_path)
    scan = json.loads((tmp_path / "plan" / "bundle-good.json").read_text())["api"]["scan"]
    assert scan["accepted_high_critical"] == [] and scan["accept_file_sha256"] is None


def test_accepted_findings_on_a_later_page_are_still_matched_and_unaccepted_ones_found(tmp_path):
    world, ctx, builds = stack(tmp_path)
    pairs = [(f"CVE-2026-{n}", "LOW") for n in range(5)] + [("CVE-2026-70", "HIGH")]
    scanned(world, *pairs, page=2)
    make(ctx, builds, tmp_path, accept_unfixed=accept_file(tmp_path, "CVE-2026-70"))
    scanned(world, *pairs, ("CVE-2026-71", "HIGH"), page=2)
    with pytest.raises(ProofError, match="CVE-2026-71"):
        make(ctx, builds, tmp_path, accept_unfixed=accept_file(tmp_path, "CVE-2026-70"))


def test_findings_that_cannot_be_matched_to_the_counts_are_refused(tmp_path):
    world, ctx, builds = stack(tmp_path, "scan-high")  # counts say HIGH, no findings listed
    with pytest.raises(ProofError, match="cannot be matched"):
        make(ctx, builds, tmp_path, accept_unfixed=accept_file(tmp_path, "CVE-2026-1"))


def serve_findings(world, findings, counts, *, pages=1):
    """Make the simulated registry answer with these raw findings and counts (None: no counts)."""

    def reply(payload):
        start = int(payload.get("nextToken") or 0)
        size = max(1, -(-len(findings) // pages))
        body = {
            "imageId": payload["imageId"],
            "imageScanStatus": {"status": "COMPLETE"},
            "imageScanFindings": {"findings": findings[start : start + size]},
        }
        if counts is not None:
            body["imageScanFindings"]["findingSeverityCounts"] = counts
        if start + size < len(findings):
            body["nextToken"] = str(start + size)
        return body

    world.ecr_describe_image_scan_findings = reply


HIGH = {"name": "CVE-2026-99", "severity": "HIGH"}


@pytest.mark.parametrize("counts", [{"HIGH": 0}, {}, None])
def test_zero_or_missing_counts_cannot_hide_an_unlisted_high_finding(tmp_path, counts):
    world, ctx, builds = stack(tmp_path)
    serve_findings(world, [HIGH], counts)
    with pytest.raises(ProofError, match="cannot be matched"):
        make(ctx, builds, tmp_path, accept_unfixed=accept_file(tmp_path, "CVE-2026-1"))
    assert not (tmp_path / "plan" / "plan.json").exists()


def test_a_high_finding_on_a_later_page_is_found_although_the_counts_are_zero(tmp_path):
    world, ctx, builds = stack(tmp_path)
    low = [{"name": f"CVE-2026-{n}", "severity": "LOW"} for n in range(3)]
    serve_findings(world, [*low, HIGH], {"LOW": 3}, pages=2)
    with pytest.raises(ProofError, match="cannot be matched"):
        make(ctx, builds, tmp_path, accept_unfixed=accept_file(tmp_path, "CVE-2026-1"))


def test_counts_above_the_listed_findings_are_refused_too(tmp_path):
    world, ctx, builds = stack(tmp_path)
    serve_findings(world, [], {"HIGH": 2})
    with pytest.raises(ProofError, match="counts 2 .* lists 0"):
        make(ctx, builds, tmp_path, accept_unfixed=accept_file(tmp_path, "CVE-2026-1"))


def test_enhanced_findings_are_not_matchable_so_they_are_refused(tmp_path):
    world, ctx, builds = stack(tmp_path)
    serve_findings(world, [], {})
    plain = world.ecr_describe_image_scan_findings

    def enhanced(payload):
        body = plain(payload)
        body["imageScanFindings"]["enhancedFindings"] = [{"severity": "HIGH"}]
        return body

    world.ecr_describe_image_scan_findings = enhanced
    with pytest.raises(ProofError, match="enhanced findings"):
        make(ctx, builds, tmp_path, accept_unfixed=accept_file(tmp_path, "CVE-2026-1"))


def test_the_worker_image_is_reconciled_like_the_api_image(tmp_path):
    world, ctx, builds = stack(tmp_path)
    plain = world.ecr_describe_image_scan_findings
    serve_findings(world, [HIGH], {"HIGH": 0})
    hiding = world.ecr_describe_image_scan_findings

    def per_repository(payload):
        return hiding(payload) if "worker" in payload["repositoryName"] else plain(payload)

    world.ecr_describe_image_scan_findings = per_repository
    with pytest.raises(ProofError, match="cannot be matched"):
        make(
            ctx,
            builds,
            tmp_path,
            "processing",
            target_revision="p0005",
            accept_unfixed=accept_file(tmp_path, "CVE-2026-1"),
        )


@pytest.mark.parametrize("where", ["top", "entry"])
def test_repeated_keys_in_the_accept_file_are_refused_before_the_registry_is_asked(tmp_path, where):
    world, ctx, builds = stack(tmp_path)
    entry = '{"id": "CVE-2026-1", "package": "p", "reason": "r", "reviewed_on": "2026-10-17"'
    text = {
        "top": '{"accepted": ['
        + entry
        + '}], "accepted": ['
        + entry.replace("-1", "-2")
        + '}], "verified_by": "v"}',
        "entry": '{"accepted": [' + entry + ', "reason": "other"}], "verified_by": "v"}',
    }[where]
    path = tmp_path / "accepted.json"
    path.write_text(text)
    calls = len(world.calls)
    with pytest.raises(ProofError, match="accept-unfixed"):
        make(ctx, builds, tmp_path, accept_unfixed=path)
    assert len(world.calls) == calls


@pytest.mark.parametrize(
    "change",
    [
        "not-json",
        "list",
        "no-entries",
        "extra-key",
        "bad-id",
        "duplicate",
        "missing-field",
        "bad-date",
        "unknown-entry-key",
        "no-verified-by",
    ],
)
def test_a_malformed_accept_file_is_refused_before_the_registry_is_asked(tmp_path, change):
    world, ctx, builds = stack(tmp_path)
    path = accept_file(tmp_path, "CVE-2026-1")
    body = json.loads(path.read_text())
    entry = body["accepted"][0]
    if change == "not-json":
        path.write_text("{")
    elif change == "list":
        path.write_text("[]")
    elif change == "no-entries":
        body["accepted"] = []
    elif change == "extra-key":
        body["note"] = "x"
    elif change == "bad-id":
        entry["id"] = "GHSA-1234"
    elif change == "duplicate":
        body["accepted"].append(dict(entry))
    elif change == "missing-field":
        del entry["reason"]
    elif change == "bad-date":
        entry["reviewed_on"] = "17/10/2026"
    elif change == "unknown-entry-key":
        entry["severity"] = "HIGH"
    elif change == "no-verified-by":
        del body["verified_by"]
    if change not in ("not-json", "list"):
        path.write_text(json.dumps(body))
    calls = len(world.calls)
    with pytest.raises(ProofError, match="accept-unfixed"):
        make(ctx, builds, tmp_path, accept_unfixed=path)
    assert len(world.calls) == calls


def test_the_committed_accept_file_is_valid_and_names_each_cve_once():
    ids, _ = release_plan.load_accept("docs/execution/aws/v1/scan-accepted-unfixed-20261017.json")
    assert len(ids) == 15 and {"CVE-2026-52490", "CVE-2025-52290"} <= ids


def test_the_command_passes_the_accept_file_through(tmp_path):
    world, ctx, builds = stack(tmp_path)
    scanned(world, ("CVE-2026-1", "HIGH"))
    code, out = cli(
        ctx,
        "--owner",
        "media",
        "--baseline-evidence",
        str(builds["baseline"]),
        "--good-run-id",
        "g1",
        "--good-evidence",
        str(builds["good"]),
        "--tests-passed",
        "12",
        "--target-revision",
        "m0007",
        "--attest-schema-unchanged",
        "--accept-unfixed",
        str(accept_file(tmp_path, "CVE-2026-1")),
    )
    assert code == 0 and out["accepted_unused"] == []


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
    failed = sim.build_evidence(
        tmp_path / "failed.json",
        source_sha="d" * 40,
        config_ids=BAD_IDS,
        failures=["media: image builds"],
    )
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
    code = evidence.main(
        [
            "release-plan",
            "--profile",
            "dc2-agent",
            "--region",
            "ap-southeast-1",
            "--account",
            "123456789012",
            "--run-id",
            "r",
            "--state-dir",
            str(ctx.state_dir),
            *argv,
        ],
        stdout=out,
        factory=lambda args: ctx,
    )
    return code, json.loads(out.getvalue())


def test_the_command_writes_the_plan_next_to_the_state_directory_by_default(tmp_path):
    _, ctx, builds = stack(tmp_path)
    code, out = cli(
        ctx,
        "--owner",
        "media",
        "--baseline-evidence",
        str(builds["baseline"]),
        "--good-run-id",
        "g1",
        "--good-evidence",
        str(builds["good"]),
        "--tests-passed",
        "12",
        "--target-revision",
        "m0007",
        "--attest-schema-unchanged",
    )
    assert code == 0 and out["plan"] == str(ctx.state_dir / "release" / "plan.json")
    assert set(out["images"]) == {"baseline", "good"}


def test_the_command_lists_what_is_missing_instead_of_guessing(tmp_path):
    _, ctx, _ = stack(tmp_path)
    code, out = cli(ctx, "--owner", "media")
    assert code == 1 and "--baseline-evidence" in out["error"]


def test_the_command_has_no_simulation_of_its_own(tmp_path):
    out = io.StringIO()
    code = evidence.main(
        [
            "release-plan",
            "--profile",
            "dc2-agent",
            "--region",
            "ap-southeast-1",
            "--account",
            "123456789012",
            "--run-id",
            "r",
            "--dry-run",
        ],
        stdout=out,
    )
    assert code == 1 and "rehearse" in json.loads(out.getvalue())["error"]


def test_a_worker_only_then_an_api_only_release_each_plan_against_the_mixed_baseline(tmp_path):
    # V2-live: each release keeps the image whose inputs did not change, so after the first the
    # running API and worker come from different commits, and that baseline must still plan.
    from scripts.aws.v1 import deploy

    world, ctx, builds = stack(tmp_path)
    journal = deploy.DeployJournal(
        ctx.state_dir / "deploy-journal.json",
        station=ctx.data["operator_station"],
        environment=ctx.data["environment_id"],
    )

    def release_keeping(number, kept, rebuilt, baseline_path, source):
        """One release as cd.sh runs it: `kept` retagged as it runs, `rebuilt` from `source`."""
        run_id, deployed = f"g{number}", journal.view()["images"]
        world.retagged[(world.repository(kept), f"{run_id}-{kept}")] = deployed[kept]["digest"]
        evidence = json.loads(baseline_path.read_text())
        evidence["images"][rebuilt] = {
            **evidence["images"][rebuilt],
            "source_sha": source,
            "config_id": "sha256:" + str(number + 6) * 64,
        }
        from scripts.ci.v1_scan import scan_receipt

        config_id = evidence["images"][rebuilt]["config_id"]
        evidence["images"][rebuilt]["trivy_scan"] = scan_receipt(
            json.dumps(
                {
                    "Metadata": {"ImageID": config_id},
                    "Results": [
                        {"Class": "os-pkgs", "Type": "debian"},
                        {"Class": "lang-pkgs", "Type": "python-pkg"},
                    ],
                }
            ).encode(),
            config_id=config_id,
            source_sha=source,
        )
        good = tmp_path / f"good-{number}.json"
        good.write_text(json.dumps(evidence))
        world.register_build(run_id, good, only=[rebuilt])
        make(
            ctx,
            {"baseline": baseline_path, "good": good},
            tmp_path,
            "processing",
            good={"run_id": run_id, "evidence": good},
            target_revision="p0005",
            out=tmp_path / f"plan-{number}",
        )
        bundle = json.loads((tmp_path / f"plan-{number}" / "bundle-good.json").read_text())
        kinds = {"processing": "api", "worker": "worker"}
        assert bundle[kinds[kept]]["retained"] is True
        assert "retained" not in bundle[kinds[rebuilt]]
        # Adopted: the journal and the stack's definitions now name what was released.
        for name in (kept, rebuilt):
            digest = world.image_digest(world.repository(name), f"{run_id}-{name}")
            journal.mutate(
                lambda d, n=name, g=digest: d["images"][n].update(
                    tag=f"{run_id}-{n}", digest=g, local_id=evidence["images"][n]["config_id"]
                )
            )
            world.stack_digests[name] = digest
        return good

    first = release_keeping(1, "processing", "worker", builds["baseline"], "b" * 40)
    second = release_keeping(2, "worker", "processing", first, "c" * 40)
    sources = {n: i["source_sha"] for n, i in json.loads(second.read_text())["images"].items()}
    assert sources["processing"] == "c" * 40 and sources["worker"] == "b" * 40
    baseline = json.loads((tmp_path / "plan-2" / "bundle-baseline.json").read_text())
    assert baseline["api"]["source_sha"] != baseline["worker"]["source_sha"]
    with pytest.raises(Exception, match="share frozen source"):
        validate_bundle(baseline, owner="processing")  # as a candidate it would not pass
    assert validate_bundle(baseline, owner="processing", deployed=True)


@pytest.mark.parametrize(
    "fault",
    ["wrong-config", "raw-hash", "index", "missing", "ambiguous", "wrong-selected", "malformed"],
)
def test_release_requires_the_fetched_single_manifest_to_bind_to_the_tested_config(tmp_path, fault):
    world, ctx, builds = stack(tmp_path)
    base = world.ecr_batch_get_image

    def reply(payload):
        result = base(payload)
        image = result["images"][0]
        if fault == "missing":
            return {"images": [], "failures": [{"failureCode": "ImageNotFound"}]}
        if fault == "ambiguous":
            result["images"] *= 2
        elif fault == "malformed":
            del image["imageManifest"]
        elif fault == "raw-hash":
            image["imageManifest"] += " "
        else:
            manifest = json.loads(image["imageManifest"])
            if fault == "wrong-config":
                manifest["config"]["digest"] = "sha256:" + "f" * 64
            elif fault == "index":
                manifest["manifests"] = []
            else:
                manifest["extra"] = "same config, different selected bytes"
            image["imageManifest"] = json.dumps(manifest)
            image["imageId"]["imageDigest"] = (
                "sha256:" + hashlib.sha256(image["imageManifest"].encode()).hexdigest()
            )
        return result

    world.ecr_batch_get_image = reply
    with pytest.raises(ProofError):
        make(ctx, builds, tmp_path)
    assert not world.definitions
    assert not (tmp_path / "plan" / "plan.json").exists()


@pytest.mark.parametrize(
    "fault", ["missing", "wrong-source", "wrong-config", "fixable", "expired", "wrong-scope"]
)
def test_release_requires_a_fresh_exact_cd_image_os_and_python_scan(tmp_path, fault):
    _, ctx, builds = stack(tmp_path)
    data = json.loads(builds["good"].read_text())
    scan = data["images"]["media"]["trivy_scan"]
    if fault == "missing":
        del data["images"]["media"]["trivy_scan"]
    elif fault == "wrong-source":
        scan["source_sha"] = "c" * 40
    elif fault == "wrong-config":
        scan["config_id"] = "sha256:" + "f" * 64
    elif fault == "fixable":
        scan["fixable_high_critical"] = 1
    elif fault == "expired":
        scan["scanned_at"] = "2020-01-01T00:00:00+00:00"
    else:
        scan["targets"] = [["os-pkgs", "debian"]]
    builds["good"].write_text(json.dumps(data))
    with pytest.raises(ProofError, match="Trivy"):
        make(ctx, builds, tmp_path)
    assert not (tmp_path / "plan" / "plan.json").exists()


GHSA = "GHSA-6q48-6c7w-9gw2 certifi"


def retain(path, *names):
    """Make a build evidence's scans read as cd.sh records a replaced rollback target's."""
    data = json.loads(path.read_text())
    for name in names:
        data["images"][name]["trivy_scan"].update(
            status="RETAINED_FIXABLE", fixable_high_critical=1, fixable_ids=[GHSA]
        )
    path.write_text(json.dumps(data))


def test_a_baseline_that_a_newer_advisory_made_fixable_still_plans_the_release_that_replaces_it(
    tmp_path,
):
    # The deployed image shipped clean; the advisory came out afterwards and the candidate fixes it.
    # Blocking here would keep the vulnerable image in production forever.
    _, ctx, builds = stack(tmp_path)
    retain(builds["baseline"], "media")
    make(ctx, builds, tmp_path)
    baseline = json.loads((tmp_path / "plan" / "bundle-baseline.json").read_text())
    assert baseline["api"]["scan"]["status"] == "RETAINED_FIXABLE"
    assert baseline["api"]["scan"]["fixable_ids"] == [GHSA]
    assert baseline["api"]["scan"]["fixable_high_critical"] == 1  # the finding stays visible
    good = json.loads((tmp_path / "plan" / "bundle-good.json").read_text())
    assert good["api"]["scan"]["status"] == "PASS"
    assert good["api"]["scan"]["fixable_high_critical"] == 0
    # It is a rollback target for the plan and for nothing else.
    assert validate_bundle(baseline, owner="media", deployed=True)
    with pytest.raises(Exception, match="exact-artifact gate"):
        validate_bundle(baseline, owner="media")
    assert validate_bundle(good, owner="media")


@pytest.mark.parametrize("role", ["good", "bad"])
def test_an_image_the_release_would_leave_running_can_never_carry_a_retained_scan(tmp_path, role):
    # Kept images come from the baseline evidence into the good set, so the set that remains in
    # production is held to the strict policy whatever the baseline was allowed to record.
    _, ctx, builds = stack(tmp_path)
    retain(builds[role], "media")
    with pytest.raises(ProofError, match="Trivy"):
        make(ctx, builds, tmp_path, bad=role == "bad")
    assert not (tmp_path / "plan" / "plan.json").exists()


def test_a_retained_baseline_scan_must_still_be_the_exact_fresh_image_scan(tmp_path):
    _, ctx, builds = stack(tmp_path)
    retain(builds["baseline"], "media")
    data = json.loads(builds["baseline"].read_text())
    data["images"]["media"]["trivy_scan"]["scanned_at"] = "2020-01-01T00:00:00+00:00"
    builds["baseline"].write_text(json.dumps(data))
    with pytest.raises(ProofError, match="Trivy scan expired"):
        make(ctx, builds, tmp_path)
