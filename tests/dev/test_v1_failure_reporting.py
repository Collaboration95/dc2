"""What a failed V1 acceptance run leaves in the log, the manifest and the artifact.

Issue #137: a browser-leg failure was visible only as a count. These tests protect that the
failing test is named with its assertion, that nothing credential-shaped goes with it, and
that the browser leg's work pump forgives a blip but not a stuck pipeline.
"""

import base64
import json
import subprocess

import pytest

from scripts.dev import v1_verify
from scripts.dev.v1_redact import first_lines, redact


def segment(value):
    return base64.urlsafe_b64encode(json.dumps(value).encode()).rstrip(b"=").decode()


# Built at import so no token-shaped literal sits in the repository for a secret scanner.
JWT = ".".join([segment({"alg": "HS256"}), segment({"sub": "user"}), "dGVzdC1zaWduYXR1cmU"])
PRESIGNED = (
    "https://127.0.0.1:9000/bucket/outputs/a.mp4"
    "?X-Amz-Algorithm=AWS4-HMAC-SHA256&X-Amz-Credential=testing%2F20261017&X-Amz-Signature=abc123"
)


def test_redaction_removes_cookie_values_from_a_header_dict_and_a_header_line():
    text = f"{{'origin': 'https://x', 'cookie': 'session={JWT}; theme=dark'}}\nCookie: a=b"
    cleaned = redact(text)
    assert "session=" not in cleaned and JWT not in cleaned and "a=b" not in cleaned
    assert "'origin': 'https://x'" in cleaned


def test_redaction_removes_the_query_of_a_presigned_url_but_keeps_its_path():
    cleaned = redact(f"Range read of {PRESIGNED} failed")
    assert "X-Amz-Signature" not in cleaned and "abc123" not in cleaned
    assert "https://127.0.0.1:9000/bucket/outputs/a.mp4?<redacted> failed" in cleaned


def test_redaction_removes_bearer_tokens_and_bare_jwts():
    cleaned = redact(f"Authorization: Bearer abcdefgh12345678 and token {JWT}")
    assert "abcdefgh12345678" not in cleaned and JWT not in cleaned


def test_redaction_leaves_an_ordinary_assertion_message_readable():
    message = (
        "AssertionError: Clock stuck: {'t': 0, 'e': None, 'r': 1}; recent [('GET', '/a', 200)]"
    )
    assert redact(message) == message


def test_excerpt_is_bounded_and_redacted():
    cleaned = first_lines("first\n" + "x" * 5000 + f"\ncookie: {JWT}", lines=3, chars=100)
    assert len(cleaned) <= 100 and JWT not in cleaned


JUNIT = """<?xml version="1.0"?>
<testsuites><testsuite name="pytest" tests="3" failures="1" errors="1" skipped="1">
<testcase classname="tests.v1.test_browser_acceptance" name="test_play[native]">
<failure message="AssertionError: leaked {'cookie': 'session=SECRETVALUE'} at https://h/x?X-Amz-Signature=s">trace</failure>
</testcase>
<testcase classname="tests.v1.test_browser_acceptance" name="test_play[hlsjs]">
<error message="TimeoutError: waited">trace</error>
</testcase>
<testcase classname="tests.v1.test_session" name="test_close">
<skipped message="no runtime"/>
</testcase>
</testsuite></testsuites>"""


def test_junit_failures_are_named_by_test_id_with_a_redacted_message(tmp_path):
    report = tmp_path / "r.xml"
    report.write_text(JUNIT)
    counts, failed, skipped = v1_verify.read_junit(report)
    assert counts == {"tests": 3, "errors": 1, "failures": 1, "skipped": 1}
    assert [(f["id"], f["kind"]) for f in failed] == [
        ("tests/v1/test_browser_acceptance.py::test_play[native]", "failure"),
        ("tests/v1/test_browser_acceptance.py::test_play[hlsjs]", "error"),
    ]
    assert (
        "SECRETVALUE" not in failed[0]["message"] and "X-Amz-Signature" not in failed[0]["message"]
    )
    assert failed[0]["message"].startswith("AssertionError: leaked")
    assert skipped == ["tests/v1/test_session.py::test_close"]


def test_failed_tests_are_collected_from_nested_flow_results_with_their_flow():
    item = {"id": "t.py::x", "kind": "failure", "message": "m"}
    flows = {
        "a": {"status": "PASS"},
        "b": {"status": "FAIL", "browser": {"failed_tests": [item]}, "publisher": {}},
    }
    assert v1_verify.failed_tests(flows) == [{"flow": "b", **item}]


def test_failures_become_github_error_annotations_on_one_line(monkeypatch, capsys):
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    v1_verify.report_failures(
        [{"flow": "b", "id": "t.py::x[native]", "kind": "failure", "message": "line1\n100%"}]
    )
    line = capsys.readouterr().err.strip()
    assert line.startswith("::error title=V1 flow b test failed::t.py::x[native] (failure): ")
    assert line.endswith("line1%0A100%25") and "\n" not in line


def test_failures_print_as_plain_lines_outside_github(monkeypatch, capsys):
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    v1_verify.report_failures([{"flow": "b", "id": "t.py::x", "kind": "run", "message": "killed"}])
    assert capsys.readouterr().err.strip() == "FAILED flow b: t.py::x (run): killed"


def test_a_killed_test_run_is_reported_as_a_failed_run_not_a_silent_one(tmp_path, monkeypatch):
    def expire(*args, **kwargs):
        raise subprocess.TimeoutExpired(args[0], 1, output=b"partial out", stderr=None)

    monkeypatch.setattr(v1_verify, "local_environment", lambda data: {})
    monkeypatch.setattr(v1_verify.subprocess, "run", expire)
    result = v1_verify.selected_tests(
        ["tests/v1/test_browser_acceptance.py"], tmp_path, {}, tag="browser", timeout=1
    )
    assert result["status"] == "FAIL" and "exceeded its 1s budget" in result["reason"]
    assert result["failed_tests"][0]["kind"] == "run"
    assert (tmp_path / "pytest-private-browser.log").read_text() == "partial out"


@pytest.fixture
def pump_module(monkeypatch):
    from scripts.dev import v1_acceptance

    calls = {"pump": [], "encode": 0}
    monkeypatch.setattr(v1_acceptance, "pump", lambda runtime: calls["pump"].pop(0)())
    monkeypatch.setattr(v1_acceptance, "encode_one", lambda runtime: calls.update(encode=1))
    return calls


def failing(message):
    def raise_it():
        raise TimeoutError(message)

    return raise_it


def make_pump(monkeypatch):
    from scripts.dev.v1_browser import WorkPump

    work = WorkPump({}, interval=0)
    monkeypatch.setattr(work, "queued_work", lambda: 1)
    return work


def test_work_pump_forgives_a_single_slow_call_that_the_next_pass_recovers(
    pump_module, monkeypatch
):
    work = make_pump(monkeypatch)
    pump_module["pump"] += [failing("read timed out"), lambda: None, lambda: None]
    for _ in range(3):
        work.iterate()
    assert work.problem() is None
    assert work.errors == ["TimeoutError: read timed out"] and work.encodes == 2


def test_work_pump_reports_a_fault_that_persists(pump_module, monkeypatch):
    work = make_pump(monkeypatch)
    pump_module["pump"] += [failing("moto is down")] * 6
    for _ in range(6):
        work.iterate()
    assert "failed 6 times in a row" in work.problem() and "moto is down" in work.problem()


def test_work_pump_gets_one_last_pass_so_a_failure_just_before_stop_can_recover(
    pump_module, monkeypatch
):
    work = make_pump(monkeypatch)
    pump_module["pump"] += [failing("late blip"), lambda: None]
    work.iterate()
    work.stopped.set()
    work.run()
    assert work.problem() is None


def test_work_pump_that_is_still_failing_at_stop_is_a_problem(pump_module, monkeypatch):
    work = make_pump(monkeypatch)
    pump_module["pump"] += [failing("one"), failing("two")]
    work.iterate()
    work.stopped.set()
    work.run()
    assert "still failing: True" in work.problem()
