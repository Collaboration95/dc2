"""Bounded DAST scope, identity handling and report hygiene regressions."""

import json
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


def test_all_generated_operations_have_a_reviewed_scan_or_exclusion_decision():
    rows = v1_dast.operation_rows(schemas())
    counts = Counter(row["service"] for row in rows)
    assert counts == {"media": 15, "processing": 5}
    assert all(row.get("operation_id") for row in rows)
    assert all(row.get("reason") for row in rows if row["scan"] == "excluded")
    assert {row["service"] for row in rows if row["scan"] == "imported"} == {"media", "processing"}


def test_active_scan_contract_contains_only_local_read_routes_with_owned_examples():
    docs = schemas()
    fixtures = {
        "media_job": "11111111-1111-4111-8111-111111111111",
        "processing_job": "22222222-2222-4222-8222-222222222222",
    }
    scans = {
        service: v1_dast.scan_document(service, docs[service], "https://127.0.0.1:4443", fixtures)
        for service in v1_dast.SERVICES
    }
    for _service, document in scans.items():
        ops = operations(document)
        assert ops
        assert all(method in {"GET", "HEAD", "OPTIONS"} for _, method, _ in ops)
        assert document["servers"] == [{"url": "https://127.0.0.1:4443"}]
        assert all(not path.startswith("/api/media/admin") for path, _, _ in ops)
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
        v1_dast.loopback_base(target)


def test_cookie_replacement_and_native_context_are_limited_to_local_api_paths():
    options = v1_dast.zap_options(4443, "access_token=private-session-value")
    context = v1_dast.context_xml(4443)
    assert "private-session-value" in options
    assert r"^https://127\.0\.0\.1:4443/api/(?:media|processing)" in options
    assert r"https://127\.0\.0\.1:4443/api/(?:media|processing)" in context
    assert "uploads" in context and "hls" in context and "admin" in context
    with pytest.raises(ValueError):
        v1_dast.zap_options(4443, "access_token=bad\nreplacer.full_list(1).enabled=true")


def test_route_coverage_uses_templates_and_never_keeps_ids_or_query_values():
    rows = v1_dast.operation_rows(schemas())
    match = v1_dast.match_operation(
        rows, "GET", "/api/processing/jobs/22222222-2222-4222-8222-222222222222"
    )
    assert match["route"] == "/api/processing/jobs/{job_id}"
    assert match["operation_id"]
    assert v1_dast.match_operation(rows, "GET", "/api/processing/jobs/not/a/job") is None


def test_dast_run_names_are_unique_safe_runtime_namespaces():
    v1_dast.validate_run_id("dast-12345-2")
    for run_id in ("../shared", "dast-Upper-1", "dast-" + "1" * 50):
        with pytest.raises(ValueError, match="unique DAST run ID"):
            v1_dast.validate_run_id(run_id)


def test_finding_gate_blocks_only_selected_high_confidence_high_risk_alerts():
    report = {
        "site": [
            {
                "name": "https://127.0.0.1:4443/api/media/jobs/private-id",
                "alerts": [
                    {
                        "pluginid": "40018",
                        "riskcode": "3",
                        "confidence": "High",
                        "count": "2",
                        "url": "https://127.0.0.1/path?secret=raw",
                        "evidence": "private response data",
                    },
                    {"pluginid": "40018", "riskcode": "3", "confidence": "Low"},
                    {"pluginid": "99999", "riskcode": "3", "confidence": "High"},
                ],
            }
        ]
    }
    clean = json.dumps(v1_dast.sanitized_findings([("media", report)]))
    rows = json.loads(clean)
    assert [row["blocking"] for row in rows] == [True, False, False]
    assert "private-id" not in clean and "secret=raw" not in clean
    assert "private response data" not in clean


def test_gateway_request_ceiling_stops_calls_before_real_handlers():
    calls = []

    def handler(event, _context):
        calls.append(event)
        return {"statusCode": 200, "body": "{}"}

    v1_dast.DastGateway.routes = tuple(v1_dast.operation_rows(schemas()))
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

    v1_dast.DastGateway.routes = tuple(v1_dast.operation_rows(schemas()))
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
