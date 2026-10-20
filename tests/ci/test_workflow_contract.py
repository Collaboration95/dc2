"""Check policy wiring without an application environment or YAML dependency."""

import re
import unittest
from pathlib import Path

from scripts.ci.policy import LANES, V1_LANES, classify, expected_jobs

ROOT = Path(__file__).resolve().parents[2]


def jobs(text):
    # The workflow's job IDs are two-space YAML keys. Refuse duplicates instead
    # of allowing a YAML parser's last-value-wins behavior to hide lost checks.
    bodies = re.split(r"^  ([a-z][a-z0-9_-]*):\n", text.split("\njobs:\n", 1)[1], flags=re.M)
    names = bodies[1::2]
    if len(names) != len(set(names)):
        raise AssertionError("Duplicate workflow job IDs")
    return dict(zip(names, bodies[2::2], strict=True))


class WorkflowContractTests(unittest.TestCase):
    def setUp(self):
        self.ci = (ROOT / ".github/workflows/ci.yml").read_text()
        self.jobs = jobs(self.ci)

    def test_external_actions_use_immutable_commits_including_local_composites(self):
        workflows = list((ROOT / ".github/workflows").glob("*.yml"))
        composites = list((ROOT / ".github/actions").glob("*/action.yml"))
        for path in workflows + composites:
            for reference in re.findall(r"\buses:\s*(\S+)", path.read_text()):
                if reference.startswith("./"):
                    self.assertTrue((ROOT / reference).exists(), (path, reference))
                else:
                    self.assertRegex(reference, r"^[\w./-]+@[0-9a-f]{40}$", str(path))

    def test_aggregates_wait_for_their_whole_scope(self):
        for job, scope in [("fast", "dev"), ("integration", "full")]:
            body = self.jobs[job]
            needs = re.search(r"^    needs: \[([^\n]+)\]", body, flags=re.M).group(1)
            required = set(expected_jobs(classify([], full=True), scope)) | {"classify"}
            self.assertEqual(set(needs.split(", ")), required)
            self.assertIn("if: always()", body)
            self.assertIn(f"policy.py gate --scope {scope}", body)
            self.assertIn("CI_PLAN: ${{ needs.classify.outputs.plan }}", body)
            self.assertIn("CI_NEEDS: ${{ toJSON(needs) }}", body)
        self.assertIn("needs.classify.result != 'success'", self.jobs["integration"])
        self.assertIn("name: Dev gate", self.jobs["fast"])
        self.assertIn("name: Full verification", self.jobs["integration"])
        self.assertNotIn("security", self.jobs["fast"])
        self.assertNotIn("sast", self.jobs["integration"])

    def test_classifier_outputs_and_job_conditions_match(self):
        for lane in LANES:
            output = lane.replace("-", "_")
            self.assertIn(
                f"{output}: ${{{{ steps.policy.outputs.{output} }}}}", self.jobs["classify"]
            )
            if lane not in V1_LANES:
                self.assertIn(f"if: needs.classify.outputs.{output} == 'true'", self.jobs[lane])
        reusable = self.jobs["v1-local"]
        self.assertIn("uses: ./.github/workflows/v1.yml", reusable)
        for name, output in [
            ("run_offline", "v1_offline"),
            ("run_live", "v1_live"),
            ("images", "images"),
        ]:
            self.assertIn(f"{name}: ${{{{ needs.classify.outputs.{output} == 'true' }}}}", reusable)
        self.assertIn("auto_images: false", reusable)
        self.assertIn("flow: all", reusable)
        self.assertIn("v1-local", self.jobs["coverage-gate"])

    def test_full_scan_and_advisory_sonar_policy(self):
        dast = (ROOT / ".github/workflows/dast.yml").read_text()
        jobs(dast)
        self.assertIn("workflow_call:", dast)
        self.assertIn("required_candidate: true", self.jobs["dast"])
        self.assertIn("uses: ./.github/workflows/dast.yml", self.jobs["dast"])
        self.assertIn("schedule:", dast)
        self.assertIn("workflow_dispatch:", dast)
        self.assertNotIn("  pull_request:", dast)  # CI owns the single candidate scan.
        self.assertIn("group: dast-${{ github.workflow }}-${{ github.ref }}", dast)
        self.assertIn("-m scripts.dev.v1_dast scan --run-id", dast)
        self.assertIn("source == os.environ['GITHUB_SHA']", dast)
        self.assertIn("if: always()\n        run: .venv/bin/python -m scripts.dev.v1_dast cleanup", dast)
        self.assertNotIn("continue-on-error", jobs(dast)["dast"])
        self.assertNotIn("needs:", self.jobs["sonar-config"])
        self.assertIn("NOT_RUN / not configured", self.jobs["sonar-config"])
        self.assertNotIn("download-artifact", self.jobs["sast"])
        self.assertIn("sonar.qualitygate.wait=false", self.jobs["sast"])
        self.assertIn("sonar.qualitygate.wait=true", self.jobs["sast-full"])
        self.assertIn("name: python-coverage", self.jobs["sast-full"])
        self.assertIn("name: frontend-coverage", self.jobs["sast-full"])
        for job in ["sast", "sast-full"]:
            self.assertIn("continue-on-error: true", self.jobs[job])
            self.assertIn("needs.sonar-config.outputs.configured == 'true'", self.jobs[job])
        security = self.jobs["security"]
        self.assertIn("matrix: ${{ fromJSON(needs.classify.outputs.security_matrix) }}", security)
        self.assertIn("exit-code: '1'", security)
        self.assertIn("severity: CRITICAL,HIGH", security)
        self.assertIn("ignore-unfixed: true", security)
        self.assertIn("image-source.json", security)
        self.assertIn("trivy-findings.json", security)
        self.assertNotIn("matrix.image.", security)

    def test_docs_job_never_installs_runtime_or_starts_services(self):
        body = self.jobs["policy-checks"] + self.jobs["planning"]
        for expensive in ["uv sync", "docker", "moto", "playwright", "postgres"]:
            self.assertNotIn(expensive, body)
        self.assertIn("python3 -m unittest discover -s tests/ci -v", body)
        self.assertIn("python3 scripts/planning/validate_v1_plan.py", body)
        self.assertIn("fetch-depth: 0", self.jobs["classify"])
        self.assertIn("cancel-in-progress: true", self.ci)
        self.assertIn("contents: read", self.ci)
        self.assertNotIn("pull_request_target:", self.ci)


if __name__ == "__main__":
    unittest.main()
