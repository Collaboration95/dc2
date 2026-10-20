"""Offline policy behavior, source resolution, and strict aggregate regressions."""

import ast
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.ci.policy import (
    IMAGE_RECIPES,
    LANES,
    SERVICE_INPUTS,
    changed_paths,
    classify,
    event_selection,
    expected_jobs,
    image_inputs,
    validate_gate,
)
from scripts.dev.common import coverage_omit_patterns

ROOT = Path(__file__).resolve().parents[2]
SHA = "a" * 40


def results(plan, scope="dev"):
    return {
        "classify": {"result": "success"},
        **{
            name: {"result": "success" if selected else "skipped"}
            for name, selected in expected_jobs(plan, scope).items()
        },
    }


class SelectionTests(unittest.TestCase):
    def test_path_table(self):
        cases = [
            ("docs/project2-worklog.txt", {"policy-checks"}, set()),
            ("docs/execution/evidence/run.txt", {"policy-checks"}, set()),
            ("docs/ci/policy.md", {"policy-checks"}, set()),
            ("docs/execution/aws/v1/backlog.json", {"planning"}, {"v1_live", "images"}),
            ("frontend/app.js", {"frontend", "v1_offline", "v1_live", "browser-trust"}, {"images"}),
            (
                "publisher/client.py",
                {"lint-and-unit", "publisher-https", "browser-trust"},
                {"images"},
            ),
            (
                "media/api/auth.py",
                {"media-integration", "v1_offline", "v1_live", "images", "browser-trust"},
                set(),
            ),
            (
                "processing/worker.py",
                {"processing-intake", "v1_live", "images", "browser-trust"},
                set(),
            ),
            (
                "runtime_support/config.py",
                {"media-integration", "processing-intake", "v1_live", "images"},
                set(),
            ),
            ("media_engine/hls.py", {"legacy-integration", "processing-intake", "images"}, set()),
            ("contracts/source.json", {"media-integration", "processing-intake", "images"}, set()),
            ("migrations/versions/new.py", {"legacy-integration", "browser-trust"}, {"images"}),
            ("media/migrations/new.py", {"media-integration", "images"}, set()),
            ("tests/media/test_auth.py", {"media-integration", "v1_live"}, {"images", "security"}),
            (
                "tests/integration/test_media_persistence.py",
                {"media-integration"},
                {"legacy-integration"},
            ),
            (
                "tests/integration/test_processing_worker.py",
                {"processing-intake"},
                {"media-integration"},
            ),
            (
                "tests/integration/conftest.py",
                {"legacy-integration", "processing-intake", "media-integration"},
                set(),
            ),
            (
                "tests/contracts/example.json",
                {"v1_offline", "v1_live", "browser-trust"},
                {"images"},
            ),
            (
                "tests/v1/fixtures/contracts/envelopes_valid.json",
                {"v1_offline", "v1_live"},
                {"images"},
            ),
            ("tests/aws/v1/test_deploy.py", {"v1_offline", "lint-and-unit"}, {"v1_live", "images"}),
            ("scripts/aws/v1/deploy.py", {"v1_offline", "lint-and-unit"}, {"v1_live", "images"}),
            ("scripts/aws/v1/bootstrap.py", {"v1_offline", "images"}, set()),
            ("scripts/dev/runtime.py", {"browser-trust", "v1_live", "publisher-https"}, set()),
            ("scripts/dev/v1_gateway.py", {"v1_live", "v1_offline"}, {"browser-trust"}),
            ("compose/local/docker-compose.yml", {"browser-trust", "media-integration"}, set()),
            ("deploy/v1/check_runtime.py", {"v1_offline", "images", "v1_live"}, set()),
            ("deploy/v1/global-bundle.pem", {"images"}, set()),
        ]
        for path, required, absent in cases:
            with self.subTest(path=path):
                plan = classify([path])
                selected = {k for k, v in plan["selected"].items() if v}
                self.assertEqual(plan["mode"], "dev")
                self.assertTrue(required <= selected, required - selected)
                self.assertFalse(absent & selected, absent & selected)
                if required == {"policy-checks"}:
                    self.assertEqual(selected, required)

    def test_retired_and_ci_only_compose_paths_do_not_select_the_dast_scan(self):
        retired = classify(["docker-compose.yml"])
        self.assertEqual(retired["mode"], "full")

        fixture = classify(["docker-compose.processing.yml"])
        self.assertFalse(fixture["selected"]["dast"])
        self.assertTrue(fixture["selected"]["processing-intake"])

    def test_conservative_inputs(self):
        for paths in [
            None,
            ["unknown/new.py"],
            ["docs/fixture.json"],
            ["docs/example.sh"],
            ["uv.lock"],
            [".github/workflows/ci.yml"],
            ["scripts/ci/policy.py"],
            ["tests/ci/test_policy.py"],
            ["frontend/package-lock.json"],
            ["../outside"],
            [".dockerignore"],
            ["tests/future_component/test_behavior.py"],
            ["deploy/future_surface/config.json"],
            ["compose/future_surface.yml"],
        ]:
            with self.subTest(paths=paths):
                plan = classify(paths)
                self.assertEqual(plan["mode"], "full")
                self.assertTrue(all(plan["selected"].values()))
                self.assertEqual(len(plan["security_matrix"]["include"]), 3)
        self.assertEqual(sum(classify([])["selected"].values()), 1)

    def test_full_bypasses_diff(self):
        for paths in [[], ["docs/project2-worklog.txt"], None]:
            plan = classify(paths, full=True)
            self.assertEqual(set(plan["selected"]), set(LANES))
            self.assertTrue(all(plan["selected"].values()))

    def test_actual_copy_inputs_and_legacy_matrix(self):
        for name, (recipe, _) in IMAGE_RECIPES.items():
            inputs = []
            for line in (ROOT / recipe).read_text().splitlines():
                if line.startswith("COPY "):
                    inputs.extend(line.split()[1:-1])
            for path in inputs:
                # Audit directory COPY sources as changed child files.
                changed = path + "/changed.py" if (ROOT / path).is_dir() else path
                with self.subTest(recipe=recipe, changed=changed):
                    self.assertIn(name, image_inputs(changed)[1])
        for recipe in (ROOT / "deploy/v1").glob("*.Dockerfile"):
            for line in recipe.read_text().splitlines():
                if line.startswith("COPY "):
                    for path in line.split()[1:-1]:
                        changed = path + "/changed.py" if (ROOT / path).is_dir() else path
                        with self.subTest(recipe=recipe.name, changed=changed):
                            self.assertTrue(image_inputs(changed)[0])
        self.assertEqual(image_inputs("media/config.py")[1], {"media"})
        self.assertEqual(image_inputs("processing/config.py")[1], {"processing"})
        self.assertEqual(image_inputs("runtime_support/config.py")[1], {"media", "processing"})
        self.assertFalse(image_inputs("tests/v1/test_config.py")[0])

    def test_event_table_and_exact_manual_source(self):
        event = {"pull_request": {"base": {"ref": "dev/closeout", "sha": "base"}}}
        self.assertEqual(event_selection("pull_request", event, SHA)[::2], (False, "base"))
        for base in ["Main", "dev/v1-integration", "other", None]:
            event["pull_request"]["base"]["ref"] = base
            self.assertTrue(event_selection("pull_request", event, SHA)[0])
        self.assertTrue(event_selection("pull_request", {}, SHA)[0])
        for event_name in ["push", "schedule", "unknown_event"]:
            self.assertTrue(event_selection(event_name, {}, SHA)[0])
        self.assertTrue(event_selection("workflow_dispatch", {}, SHA, SHA)[0])
        for candidate in ["", "Main", "b" * 40, SHA[:7]]:
            with self.subTest(candidate=candidate), self.assertRaises(ValueError):
                event_selection("workflow_dispatch", {}, SHA, candidate)


class GateTests(unittest.TestCase):
    def test_selected_success_and_expected_skips(self):
        for paths in [[], ["docs/project2-worklog.txt"], ["media/config.py"], ["frontend/app.js"]]:
            plan = classify(paths)
            self.assertEqual(validate_gate(plan, results(plan), "dev"), [])

    def test_selected_failure_cancellation_skip_missing_and_unknown(self):
        plan = classify(["media/config.py"])
        for status in ["failure", "cancelled", "skipped", "missing", "unknown"]:
            needs = results(plan)
            needs["media-integration"] = {"result": status}
            self.assertTrue(validate_gate(plan, needs, "dev"))
        needs = results(plan)
        del needs["v1-local"]
        self.assertTrue(validate_gate(plan, needs, "dev"))

    def test_unselected_job_cannot_cancel_fail_or_run_unexpectedly(self):
        plan = classify(["docs/project2-worklog.txt"])
        for status in ["failure", "cancelled", "success"]:
            needs = results(plan)
            needs["browser-trust"] = {"result": status}
            self.assertTrue(validate_gate(plan, needs, "dev"))

    def test_docs_selected_failure_is_not_hidden_by_skips(self):
        plan = classify(["docs/execution/aws/v1/backlog.json"])
        needs = results(plan)
        needs["planning"]["result"] = "failure"
        self.assertTrue(validate_gate(plan, needs, "dev"))
        needs = results(plan)
        needs["classify"]["result"] = "cancelled"
        self.assertTrue(validate_gate(plan, needs, "dev"))

    def test_full_every_requested_job_is_required(self):
        plan = classify([], full=True)
        self.assertEqual(validate_gate(plan, results(plan, "full"), "full"), [])
        for job in expected_jobs(plan, "full"):
            for status in ["failure", "cancelled", "skipped"]:
                with self.subTest(job=job, status=status):
                    needs = results(plan, "full")
                    needs[job]["result"] = status
                    self.assertTrue(validate_gate(plan, needs, "full"))
        self.assertIn("frontend", expected_jobs(plan, "full"))
        self.assertIn("security", expected_jobs(plan, "full"))
        self.assertIn("dast", expected_jobs(plan, "full"))
        self.assertNotIn("security", expected_jobs(plan, "dev"))

    def test_invalid_full_plan_fails_closed(self):
        plan = classify([], full=True)
        plan["selected"]["images"] = False
        with self.assertRaises(ValueError):
            expected_jobs(plan, "full")
        plan = classify([])
        plan["selected"]["v1_live"] = "false"
        with self.assertRaises(ValueError):
            expected_jobs(plan, "dev")


class ServiceLaneTests(unittest.TestCase):
    """#199: owner paths select only that owner's service job; shared inputs select both."""

    def lanes(self, path):
        plan = classify([path])
        return {lane for lane in ("media-service", "processing-service") if plan["selected"][lane]}

    def test_owner_paths_select_only_their_service(self):
        for path, expected in [
            ("media/api/auth.py", {"media-service"}),
            ("tests/media/test_auth.py", {"media-service"}),
            ("deploy/v1/media.Dockerfile", {"media-service"}),
            ("processing/service.py", {"processing-service"}),
            ("processing/worker/ffmpeg.py", {"processing-service"}),
            ("processing/v1_worker.py", {"processing-service"}),
            ("tests/processing/test_contracts.py", {"processing-service"}),
            ("media_engine/hls.py", {"processing-service"}),
            ("deploy/v1/worker.Dockerfile", {"processing-service"}),
            ("deploy/v1/processing.Dockerfile", {"processing-service"}),
            ("scripts/aws/v1/bootstrap.py", {"processing-service"}),
        ]:
            with self.subTest(path=path):
                self.assertEqual(self.lanes(path), expected)

    def test_shared_inputs_select_both_services(self):
        both = {"media-service", "processing-service"}
        for path in [
            "contracts/v1.py",
            "delivery/dlq.py",
            "runtime_support/lambda_db.py",
            "tests/contracts/test_prepared_contracts.py",
            "deploy/v1/check_runtime.py",
            "deploy/v1/build_and_verify.py",
            "deploy/v1/global-bundle.pem",
            "deploy/v1/README.md",
            "deploy/aws/v1/template.json",
        ]:
            with self.subTest(path=path):
                self.assertEqual(self.lanes(path), both)

    def test_unrelated_paths_select_no_service(self):
        for path in ["frontend/app.js", "publisher/client.py", "docs/ci/policy.md", "app/main.py"]:
            with self.subTest(path=path):
                self.assertEqual(self.lanes(path), set())

    def test_full_mode_selects_both(self):
        plan = classify([], full=True)
        self.assertTrue(plan["selected"]["media-service"])
        self.assertTrue(plan["selected"]["processing-service"])

    def test_every_dockerfile_copy_source_selects_its_owner(self):
        owners = {
            "media": {"media-service"},
            "processing": {"processing-service"},
            "worker": {"processing-service"},
        }
        shared = {"media-service", "processing-service"}
        for recipe in (ROOT / "deploy/v1").glob("*.Dockerfile"):
            owner = recipe.name.split(".")[0]
            for line in recipe.read_text().splitlines():
                if not line.startswith("COPY "):
                    continue
                for path in line.split()[1:-1]:
                    if path in {"pyproject.toml", "uv.lock"}:
                        continue  # dependency manifests select full verification
                    changed = path + "/changed.py" if (ROOT / path).is_dir() else path
                    with self.subTest(recipe=recipe.name, changed=changed):
                        got = self.lanes(changed)
                        self.assertTrue(owners[owner] <= got, (owners[owner], got))
                        # A source that only this owner copies must not wake the peer.
                        if changed.startswith((f"{owner}/", "media/", "processing/")):
                            self.assertNotEqual(got, shared)

    def test_every_dockerfile_copy_source_is_a_build_input_of_its_image(self):
        from scripts.ci.policy import IMAGE_BUILD_INPUTS, changed_images

        for recipe in (ROOT / "deploy/v1").glob("*.Dockerfile"):
            image = recipe.name.split(".")[0]
            self.assertIn(f"deploy/v1/{recipe.name}", IMAGE_BUILD_INPUTS[image])
            for line in recipe.read_text().splitlines():
                if not line.startswith("COPY "):
                    continue
                for path in line.split()[1:-1]:
                    changed = path + "/changed.py" if (ROOT / path).is_dir() else path
                    with self.subTest(recipe=recipe.name, changed=changed):
                        self.assertIn(image, changed_images([changed]))
        # Only what an image copies selects it: tests, docs and the template select none,
        # and Media's own code never selects Processing's images.
        self.assertEqual(
            changed_images(["tests/media/x.py", "docs/a.md", "deploy/aws/v1/template.json"]), set()
        )
        self.assertEqual(changed_images(["media/api/uploads.py"]), {"media"})
        self.assertEqual(changed_images(["media_engine/x.py"]), {"worker"})

    def test_service_inputs_name_real_files(self):
        for lane, inputs in SERVICE_INPUTS.items():
            for path in inputs:
                with self.subTest(lane=lane, path=path):
                    self.assertTrue((ROOT / path).exists(), path)

    def test_secret_scan_is_required_by_both_aggregates_and_cannot_be_skipped(self):
        for scope, mode_plan in [("dev", classify([])), ("full", classify([], full=True))]:
            with self.subTest(scope=scope):
                self.assertTrue(expected_jobs(mode_plan, scope)["secret-scan"])
                self.assertEqual(validate_gate(mode_plan, results(mode_plan, scope), scope), [])
                for status in ["failure", "cancelled", "skipped", "missing"]:
                    needs = results(mode_plan, scope)
                    needs["secret-scan"] = {"result": status}
                    self.assertTrue(validate_gate(mode_plan, needs, scope), status)


class SourceTests(unittest.TestCase):
    def test_rename_delete_and_tested_merge_diff(self):
        with tempfile.TemporaryDirectory() as directory:

            def command(*args):
                return subprocess.check_output(["git", "-C", directory, *args], text=True).strip()

            command("init", "-q", "-b", "base")
            command("config", "user.email", "ci@example.invalid")
            command("config", "user.name", "CI test")
            command("config", "merge.directoryRenames", "false")
            root = Path(directory)
            (root / "docs").mkdir()
            (root / "media").mkdir()
            (root / "docs/note.txt").write_text("rename me")
            (root / "media/delete.py").write_text("deleted")
            command("add", ".")
            command("commit", "-qm", "base")
            command("checkout", "-qb", "candidate")
            (root / "processing").mkdir()
            command("mv", "docs/note.txt", "processing/new.py")
            command("rm", "media/delete.py")
            command("commit", "-qm", "candidate")
            command("checkout", "base")
            (root / "docs/base-only.txt").write_text("unrelated base change")
            command("add", ".")
            command("commit", "-qm", "base moved")
            base = command("rev-parse", "HEAD")
            command("merge", "--no-ff", "candidate", "-m", "tested merge")
            candidate = command("rev-parse", "HEAD")
            previous = Path.cwd()
            try:
                os.chdir(directory)
                paths = changed_paths(base, candidate)
            finally:
                os.chdir(previous)
            self.assertEqual(set(paths), {"docs/note.txt", "processing/new.py", "media/delete.py"})
            selected = classify(paths)["selected"]
            self.assertTrue(selected["processing-intake"])
            self.assertTrue(selected["media-integration"])

    def test_cli_missing_diff_is_full_and_checkout_mismatch_fails(self):
        from scripts.ci.policy import main

        with tempfile.TemporaryDirectory() as directory:
            event = Path(directory) / "event.json"
            event.write_text(
                json.dumps(
                    {"pull_request": {"base": {"ref": "dev/closeout", "sha": "unreadable-base"}}}
                )
            )
            output = Path(directory) / "output"
            env = {
                "GITHUB_EVENT_NAME": "pull_request",
                "GITHUB_EVENT_PATH": str(event),
                "GITHUB_SHA": SHA,
                "GITHUB_OUTPUT": str(output),
            }
            with patch.dict(os.environ, env), patch.object(sys, "argv", ["policy", "classify"]):
                with patch("scripts.ci.policy.git", return_value=(SHA + "\n").encode()):
                    with patch(
                        "scripts.ci.policy.changed_paths",
                        side_effect=subprocess.CalledProcessError(1, "git"),
                    ):
                        with patch("builtins.print"):
                            main()
                self.assertIn("mode=full", output.read_text())
                with patch("scripts.ci.policy.git", return_value=b"wrong-source\n"):
                    with self.assertRaisesRegex(SystemExit, "mixed-source"):
                        main()


class FullCoverageTests(unittest.TestCase):
    def test_every_mandatory_fragment_and_metadata_remain_required(self):
        # Execute the real gate's evidence validation without importing app dependencies.
        source = ast.parse((ROOT / "scripts/dev/coverage.py").read_text())
        function = next(
            node
            for node in source.body
            if isinstance(node, ast.FunctionDef) and node.name == "main"
        )
        import argparse

        namespace = {
            "argparse": argparse,
            "Path": Path,
            "json": json,
            "ROOT": ROOT,
            "fingerprint": lambda: "same",
            "packages": lambda: ["media"],
            "coverage_omit_patterns": coverage_omit_patterns,
        }
        exec(
            compile(ast.Module(body=[function], type_ignores=[]), "coverage-evidence-gate", "exec"),
            namespace,
        )
        tiers = [
            "fast",
            "legacy-integration",
            "processing-integration",
            "media-integration",
            "v1-integration",
        ]
        workflow = (ROOT / ".github/workflows/ci.yml").read_text()
        for tier in tiers:
            self.assertIn(f"artifacts/coverage/.coverage.{tier}", workflow)
        with tempfile.TemporaryDirectory() as directory:
            paths = [Path(directory) / (".coverage." + tier) for tier in tiers]
            args = ["coverage"] + [value for path in paths for value in ("--data", str(path))]
            for missing in paths:
                for metadata_missing in (False, True):
                    for path, tier in zip(paths, tiers, strict=True):
                        path.write_text("placeholder")
                        Path(str(path) + ".json").write_text(
                            json.dumps(
                                {
                                    "tier": tier,
                                    "fingerprint": "same",
                                    "omit": coverage_omit_patterns(ROOT),
                                }
                            )
                        )
                    Path(str(missing) + ".json" if metadata_missing else missing).unlink()
                    with self.subTest(missing=missing.name, metadata=metadata_missing):
                        with (
                            patch.object(sys, "argv", args),
                            self.assertRaisesRegex(SystemExit, "Missing coverage evidence"),
                        ):
                            namespace["main"]()


if __name__ == "__main__":
    unittest.main()
