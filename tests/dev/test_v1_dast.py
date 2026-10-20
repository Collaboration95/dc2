"""DAST scope, scanner invocation, ownership evidence and report hygiene contracts."""

import json
import subprocess
from collections import Counter
from pathlib import Path

import pytest

from scripts.dev import v1_dast

ROOT = Path(__file__).resolve().parents[2]


def schemas():
    return {
        service: json.loads((ROOT / f"docs/api/{service}.openapi.json").read_text())
        for service in v1_dast.SERVICES
    }


def operations(document):
    return [
        (path, method.upper(), operation)
        for path, item in document["paths"].items()
        for method, operation in item.items()
        if method.lower() in v1_dast.METHODS
    ]


def zap_report(port, alerts=None, host="127.0.0.1"):
    return {
        "@version": "2.16.0",
        "@generated": "2026-10-20T00:00:00Z",
        "site": [
            {
                "@name": f"https://{host}:{port}",
                "@host": host,
                "@port": str(port),
                "@ssl": "true",
                "alerts": alerts or [],
            }
        ],
    }


def test_all_generated_operations_have_a_reviewed_scan_or_exclusion_decision():
    rows = v1_dast.operation_rows(schemas())
    counts = Counter(row["service"] for row in rows)
    assert counts == {"media": 15, "processing": 5}
    assert all(row["operation_id"] for row in rows)
    assert all(row["reason"] for row in rows if row["scan"] == "excluded")
    assert {row["service"] for row in rows if row["scan"] == "imported"} == {"media", "processing"}


def test_active_scan_contract_contains_only_local_reads_and_owned_examples():
    docs = schemas()
    fixtures = {
        "media_job": "11111111-1111-4111-8111-111111111111",
        "processing_job": "22222222-2222-4222-8222-222222222222",
    }
    rows = v1_dast.operation_rows(docs)
    scans = {
        service: v1_dast.scan_document(
            service, docs[service], "https://127.0.0.1:4443", fixtures, rows
        )
        for service in v1_dast.SERVICES
    }
    for document in scans.values():
        ops = operations(document)
        assert ops
        assert all(method in v1_dast.SCAN_METHODS for _, method, _ in ops)
        assert document["servers"] == [{"url": "https://127.0.0.1:4443"}]
        assert all(not path.startswith("/api/media/admin") for path, _, _ in ops)
    assert sum(len(operations(document)) for document in scans.values()) == 7
    media_parameters = [
        param
        for path, method, op in operations(scans["media"])
        if path == "/api/media/jobs/{job_id}" and method == "GET"
        for param in op.get("parameters", [])
    ]
    processing_parameters = [
        param
        for path, method, op in operations(scans["processing"])
        if path in {"/api/processing/jobs", "/api/processing/jobs/{job_id}"} and method == "GET"
        for param in op.get("parameters", [])
    ]
    assert any(item.get("example") == fixtures["media_job"] for item in media_parameters)
    assert any(item.get("example") == fixtures["media_job"] for item in processing_parameters)
    assert any(item.get("example") == fixtures["processing_job"] for item in processing_parameters)


@pytest.mark.parametrize(
    "target",
    [
        "http://127.0.0.1:4443",
        "https://127.0.0.1",
        "https://localhost:4443",
        "https://example.invalid:4443",
        "https://127.0.0.1:4443/path",
        "https://127.0.0.1:4443?next=https://example.invalid",
    ],
)
def test_scan_target_refuses_non_exact_loopback_origins(target):
    with pytest.raises(ValueError, match="HTTPS loopback"):
        v1_dast.local_origin(target)


def test_docker_desktop_uses_the_certificate_san_alias_through_bridge_network(monkeypatch):
    origin = "https://127.0.0.1:4443"
    monkeypatch.setattr(v1_dast.sys, "platform", "darwin")
    assert v1_dast.scanner_base(origin) == "https://postgres:4443"
    assert v1_dast.local_origin("https://postgres:4443") == "https://postgres:4443"
    desktop_context = v1_dast.context_xml(4443, "postgres")
    assert "^https://postgres:4443(?:/.*)?$" in desktop_context
    assert r"^https://postgres:4443/api/" in v1_dast.zap_options(
        4443, "access_token=private-session-value", "postgres"
    )

    monkeypatch.setattr(v1_dast.sys, "platform", "linux")
    assert v1_dast.scanner_base(origin) == origin
    with pytest.raises(ValueError, match="Docker Desktop host alias"):
        v1_dast.local_origin("https://postgres:4443")


def test_cookie_replacement_is_api_only_and_context_stays_on_local_origin():
    options = v1_dast.zap_options(4443, "access_token=private-session-value")
    context = v1_dast.context_xml(4443)
    assert "private-session-value" in options
    assert r"^https://127\.0\.0\.1:4443/api/(?:media|processing)" in options
    assert "^https://" in context and "127" in context
    for bad_cookie in (
        "access_token=",
        "access_token=bad\nreplacer.full_list(1).enabled=true",
        "access_token=one; other=two",
    ):
        with pytest.raises(ValueError):
            v1_dast.zap_options(4443, bad_cookie)


def test_route_coverage_matches_templates_without_saving_request_values():
    rows = v1_dast.operation_rows(schemas())
    match = v1_dast.match_operation(
        rows, "GET", "/api/processing/jobs/22222222-2222-4222-8222-222222222222"
    )
    assert match["route"] == "/api/processing/jobs/{job_id}"
    assert match["operation_id"]
    assert v1_dast.match_operation(rows, "GET", "/api/processing/jobs/not/a/job") is None


def test_dast_run_names_are_unique_safe_runtime_namespaces():
    v1_dast.validate_run_id("dast-12345-2")
    for run_id in ("../shared", "dast-Upper-1", "dast-1-local", "dast-" + "1" * 50):
        with pytest.raises(ValueError, match="unique DAST run ID"):
            v1_dast.validate_run_id(run_id)


def test_report_shape_requires_a_nonempty_local_zap_site():
    port = 4443
    v1_dast.validate_report(zap_report(port), port)
    v1_dast.validate_report(zap_report(port, host="postgres"), port, "postgres")
    for invalid in ({}, {"site": []}, zap_report(port + 1), {**zap_report(port), "site": [{}]}):
        with pytest.raises(RuntimeError):
            v1_dast.validate_report(invalid, port)


def test_sanitized_findings_are_report_only_and_drop_raw_evidence():
    report = zap_report(
        4443,
        [
            {
                "pluginid": "40018",
                "riskcode": "3",
                "confidence": "High",
                "count": "2",
                "url": "https://127.0.0.1/path?secret=raw",
                "evidence": "private response data",
            }
        ],
    )
    clean = json.dumps(v1_dast.sanitized_findings("media", report))
    assert json.loads(clean) == [
        {
            "service": "media",
            "plugin_id": "40018",
            "risk_code": "3",
            "confidence": "high",
            "count": 2,
        }
    ]
    assert "private-id" not in clean and "secret=raw" not in clean
    assert "private response data" not in clean and "blocking" not in clean


def test_zap_invocation_uses_host_cidfile_and_a_clean_java_trust_option(tmp_path, monkeypatch):
    private = tmp_path / "private"
    private.mkdir()
    schema = private / "media.openapi.json"
    schema.write_text(json.dumps({"servers": [{"url": "https://127.0.0.1:4443"}]}))
    ca = private / "ca.crt"
    ca.write_text("test ca")
    calls = []

    def run(command, **kwargs):
        calls.append((command, kwargs))
        cid_file = Path(command[command.index("--cidfile") + 1])
        cid_file.write_text("a" * 64)
        report_path = private / "media-openapi-raw.json"
        report_path.write_text(json.dumps(zap_report(4443)))
        return subprocess.CompletedProcess(command, 0, "scanner output", "")

    monkeypatch.setattr(v1_dast.subprocess, "run", run)
    code, report = v1_dast._run_zap(private, ca, schema)
    command = calls[0][0]
    cid_file = Path(command[command.index("--cidfile") + 1])
    script = command[-1]
    assert code == 0 and report["site"]
    assert cid_file == (private / "media.openapi.cid").resolve()
    assert "/zap/wrk/" not in str(cid_file)
    assert v1_dast.ZAP_IMAGE in command
    assert "/home/zap/.ZAP/policies/API-Minimal.policy" in script
    assert "/tmp/.ZAP/policies/API-Minimal.policy" in script
    assert "javax.net.ssl.trustStore=/tmp/dast-trust" in script
    assert command[command.index("--network") + 1] == (
        "bridge" if v1_dast.sys.platform == "darwin" else "host"
    )
    if v1_dast.sys.platform == "darwin":
        assert command[command.index("--add-host") + 1] == "postgres:host-gateway"
    java_options = [line for line in script.splitlines() if "_JAVA_OPTIONS=" in line]
    assert len(java_options) == 2 and all("\\" not in line for line in java_options)


def test_zap_timeout_removes_only_container_captured_in_host_cidfile(tmp_path, monkeypatch):
    private = tmp_path / "private"
    private.mkdir()
    schema = private / "media.openapi.json"
    schema.write_text(json.dumps({"servers": [{"url": "https://127.0.0.1:4443"}]}))
    ca = private / "ca.crt"
    ca.write_text("test ca")
    container_id = "b" * 64
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        if command[:2] == ["docker", "run"]:
            Path(command[command.index("--cidfile") + 1]).write_text(container_id)
            raise subprocess.TimeoutExpired(command, kwargs["timeout"])
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(v1_dast.subprocess, "run", run)
    with pytest.raises(RuntimeError, match="timed out"):
        v1_dast._run_zap(private, ca, schema, timeout=1)
    assert calls[1] == ["docker", "rm", "--force", container_id]


def test_zap_execution_errors_report_only_exit_code(tmp_path, monkeypatch):
    private = tmp_path / "private"
    private.mkdir()
    schema = private / "media.openapi.json"
    schema.write_text(json.dumps({"servers": [{"url": "https://127.0.0.1:4443"}]}))
    ca = private / "ca.crt"
    ca.write_text("test ca")

    def run(command, **_kwargs):
        return subprocess.CompletedProcess(command, 3, "private scanner output", "private stderr")

    monkeypatch.setattr(v1_dast.subprocess, "run", run)
    with pytest.raises(RuntimeError, match="ZAP scanner exit 3"):
        v1_dast._run_zap(private, ca, schema)


def test_gateway_coverage_counts_only_forwarded_scanner_requests_and_allows_refusals():
    rows = v1_dast.operation_rows(schemas())
    health = next(
        row for row in rows if row["service"] == "media" and row["route"] == "/api/media/health"
    )
    calls = []

    def handler(event, _context):
        calls.append(event)
        return {"statusCode": 200, "body": "{}"}

    v1_dast.DastGateway.routes = (health,)
    gateway = v1_dast.DastGateway(handler, handler, lambda *_: {"isAuthorized": True})
    gateway.begin_scan(request_cap=2)
    okay = gateway.invoke("GET", "/api/media/health", {"host": "127.0.0.1"})
    refused = gateway.invoke("DELETE", "/api/media/health", {"host": "127.0.0.1"})
    gateway.end_scan()
    evidence = v1_dast._validate_coverage(gateway, (health,))
    assert okay["statusCode"] == 200 and refused["statusCode"] == 405
    assert len(calls) == evidence["requests_forwarded"] == 1
    assert evidence["blocked_out_of_scope_requests"] == 1
    assert evidence["unmatched_requests"] == 1


def test_gateway_request_cap_stops_forwarding_before_real_handlers():
    calls = []

    def handler(event, _context):
        calls.append(event)
        return {"statusCode": 200, "body": "{}"}

    health = next(
        row
        for row in v1_dast.operation_rows(schemas())
        if row["service"] == "media" and row["route"] == "/api/media/health"
    )
    v1_dast.DastGateway.routes = (health,)
    gateway = v1_dast.DastGateway(handler, handler, lambda *_: {"isAuthorized": True})
    gateway.begin_scan(request_cap=1)
    first = gateway.invoke("GET", "/api/media/health", {"host": "127.0.0.1"})
    capped = gateway.invoke("GET", "/api/media/health", {"host": "127.0.0.1"})
    gateway.end_scan()
    evidence = gateway.scan_evidence()
    assert first["statusCode"] == 200 and capped["statusCode"] == 429
    assert len(calls) == 1
    assert evidence["requests_seen"] == 2
    assert evidence["requests_forwarded"] == 1
    assert evidence["cap_exceeded"] is True


def test_gateway_blocks_excluded_mutations_before_the_real_handler():
    calls = []

    def handler(event, _context):
        calls.append(event)
        return {"statusCode": 204, "body": ""}

    rows = v1_dast.operation_rows(schemas())
    v1_dast.DastGateway.routes = tuple(rows)
    gateway = v1_dast.DastGateway(handler, handler, lambda *_: {"isAuthorized": True})
    gateway.begin_scan(request_cap=10)
    reply = gateway.invoke(
        "DELETE", "/api/media/jobs/11111111-1111-4111-8111-111111111111", {"host": "127.0.0.1"}
    )
    gateway.end_scan()
    evidence = gateway.scan_evidence()
    assert reply["statusCode"] == 405
    assert not calls
    assert evidence["requests_forwarded"] == 0
    assert evidence["blocked_out_of_scope_requests"] == 1
