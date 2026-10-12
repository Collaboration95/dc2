"""Offline CI regressions for complete acceptance and safe failure evidence."""

import json
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def workflow():
    return yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text())


@pytest.fixture
def complete_report():
    return {
        "status": "PASS",
        "scope": "full",
        "cases": {
            "CT-18-cli": {"status": "PASS"},
            "CT-18-browser": {"status": "PASS"},
        },
        "events": [
            {"event": "browser-hls-decoded"},
            {"event": "browser-mp4-decoded"},
        ],
    }


@pytest.mark.parametrize(
    "incomplete",
    [None, "public-only", "failed", "missing-cli", "missing-browser", "missing-mp4"],
)
def test_ci_acceptance_rejects_partial_results(
    workflow, complete_report, incomplete, tmp_path, monkeypatch
):
    job = workflow["jobs"]["browser-trust"]
    step = next(step for step in job["steps"] if "scripts.dev.e2e" in step.get("run", ""))
    command, validation = step["run"].split("<<'PY'\n", 1)
    assert "--public-only" not in command
    assert "timeout --signal=TERM --kill-after=30s 15m" in command
    assert "continue-on-error" not in step
    if incomplete == "public-only":
        complete_report["scope"] = "public-only"
    elif incomplete == "failed":
        complete_report["status"] = "FAIL"
    elif incomplete == "missing-cli":
        del complete_report["cases"]["CT-18-cli"]
    elif incomplete == "missing-browser":
        del complete_report["cases"]["CT-18-browser"]
    elif incomplete == "missing-mp4":
        complete_report["events"].pop()
    folder = tmp_path / "artifacts/ci-trust"
    folder.mkdir(parents=True)
    result = folder / "result.json"
    result.write_text(json.dumps(complete_report))
    (folder / "e2e-latest.json").write_text(json.dumps({"status": "PASS", "result": str(result)}))
    monkeypatch.chdir(tmp_path)
    code = compile(validation.rsplit("\nPY", 1)[0], "ci-e2e-validation", "exec")
    if incomplete:
        with pytest.raises((AssertionError, KeyError)):
            exec(code, {})
    else:
        exec(code, {})


def test_ci_retains_failure_evidence_without_private_run_files(workflow, tmp_path):
    job = workflow["jobs"]["browser-trust"]
    upload = next(
        step for step in job["steps"] if step.get("uses", "").startswith("actions/upload-artifact@")
    )
    assert upload["if"] == "always()"
    assert upload["with"]["retention-days"] == 7
    safe = {
        "artifacts/ci-trust/runner-capacity.json",
        "artifacts/ci-trust/browser-trust.json",
        "artifacts/ci-trust/browser-trust.png",
        "artifacts/ci-trust/e2e-latest.json",
        "artifacts/ci-trust/e2e-example/result.json",
        "artifacts/ci-trust/e2e-example/browser-failed-attempt.png",
        "artifacts/ci-trust/e2e-example/browser-playing.png",
        "artifacts/ci-trust/e2e-example/browser-playback-failed.png",
    }
    private = {
        ".local/runs/ci-trust/runtime.env",
        ".local/runs/ci-trust/tls/server.key",
        ".local/runs/ci-trust/publisher-e2e/cookies.txt",
        "artifacts/ci-trust/e2e-example/cli-stdout.json",
        "artifacts/ci-trust/e2e-example/trace.zip",
        "artifacts/ci-trust/e2e-example/browser-profile/cookies.sqlite",
        "artifacts/ci-trust/e2e-example/owned.mp4",
    }
    for name in safe | private:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()
    retained = {
        str(path.relative_to(tmp_path))
        for pattern in upload["with"]["path"].splitlines()
        for path in tmp_path.glob(pattern)
        if path.is_file()
    }
    assert retained == safe
    assert not retained & private
    aggregate = workflow["jobs"]["integration"]
    assert "browser-trust" in aggregate["needs"]
    guard = aggregate["steps"][0]
    assert guard["env"]["TRUST_RESULT"] == "${{ needs.browser-trust.result }}"
    assert 'test "$TRUST_RESULT" = success' in guard["run"]
