"""Cross-bundle regression checks for reviewed preparation boundaries."""

import hashlib
import json
import ssl
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from scripts.aws.context import Client, Context, ContextError
from scripts.aws.definitions import environment_template, generator_template
from scripts.aws.edge import gate_digest, prepare_activation, validate_activation
from scripts.aws.latency import summarize
from scripts.aws.reports import retained_reports
from scripts.aws.transport import OperationError
from scripts.dev import tls


def test_edge_activation_is_private_matched_and_required_before_wake():
    config = {
        "environment_id": "demo",
        "cloudfront_distribution_id": "edge",
        "origin_transport_accepted": True,
    }
    current = {
        "ETag": "v1",
        "DistributionConfig": {
            "Enabled": False,
            "Origins": {
                "Items": [
                    {"Id": "state", "CustomOriginConfig": {"OriginProtocolPolicy": "http-only"}}
                ]
            },
        },
    }
    secret = "a" * 64
    private, receipt = prepare_activation(
        config,
        current,
        private_gate=secret,
        nginx_gate_sha256=gate_digest(secret),
        public_dns="fresh.example",
    )
    assert not current["DistributionConfig"]["Enabled"]
    assert receipt["applied"] is False and secret not in json.dumps(receipt)
    with pytest.raises(OperationError):
        validate_activation(
            config, {"ETag": "v2", "DistributionConfig": private["DistributionConfig"]}
        )
    config["edge_activation"] = {**receipt, "status": "VERIFIED", "nginx_gate_observed": True}
    observed = {"ETag": "v2", "DistributionConfig": private["DistributionConfig"]}
    assert validate_activation(config, observed)["Id"] == "state"
    observed["DistributionConfig"]["Origins"]["Items"][0]["CustomHeaders"]["Items"][0][
        "HeaderValue"
    ] = "b" * 64
    with pytest.raises(OperationError):
        validate_activation(config, observed)


def test_rendered_resource_tags_and_emitted_operator_actions_agree():
    resources = environment_template()["Resources"]
    tags = resources["StateInstance"]["Properties"]["Tags"]
    assert {t["Key"]: t["Value"] for t in tags}["Environment"] == {"Ref": "EnvironmentId"}
    generator = generator_template()["Resources"]["Generator"]["Properties"]
    assert generator["PropagateTagsToVolumeOnCreation"] is True
    assert {t["Key"]: t["Value"] for t in generator["Tags"]}["Role"] == "generator"
    statements = [
        s
        for p in resources["OperatorRole"]["Properties"]["Policies"]
        for s in p["PolicyDocument"]["Statement"]
    ]
    actions = {a for s in statements for a in s["Action"]}
    assert {"ecs:DescribeTaskDefinition", "ec2:TerminateInstances", "ec2:DeleteVolume"} <= actions
    for action in ("ec2:TerminateInstances", "ec2:DeleteVolume"):
        stmt = next(s for s in statements if action in s["Action"])
        assert stmt["Condition"]["StringEquals"]["ec2:ResourceTag/Role"] == "generator"
    stmt = next(s for s in statements if "ecs:DescribeTaskDefinition" in s["Action"])
    assert all(r["Fn::Sub"].endswith(":*") for r in stmt["Resource"])


@pytest.mark.integration
def test_physical_loopback_https_object_fixture_trust_query_and_isolation(tmp_path, monkeypatch):
    monkeypatch.setattr(tls, "ROOT", tmp_path)
    folder = tls.ensure_tls("fixture")
    seen = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            seen.append((self.path, dict(self.headers)))
            self.send_response(206)
            self.send_header("Content-Range", "bytes 0-3/8")
            self.end_headers()
            self.wfile.write(b"data")

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(folder / "server.crt", folder / "server.key")
    server.socket = context.wrap_socket(server.socket, server_side=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    origin = f"https://127.0.0.1:{server.server_port}"
    fixture = Context(
        origin,
        "ap-southeast-1",
        ("source-bucket",),
        mode="local-fixture",
        fixture_object_origin=origin,
    )
    capability = origin + "/source-bucket/key?X-Amz-Signature=dead%2Bbeef&x=1"
    try:
        with Client(fixture, ca_file=str(folder / "ca.crt")) as client:
            client.api.cookies.set("session", "private")
            assert client.download(capability, byte_range=(0, 3))[:2] == (206, b"data")
        assert seen[0][0].endswith("?X-Amz-Signature=dead%2Bbeef&x=1")
        assert "Cookie" not in seen[0][1] and "Authorization" not in seen[0][1]
        with Client(fixture) as client, pytest.raises(ContextError):
            client.download(capability)
        assert not fixture.capability_allowed(origin + "/wrong-bucket/key")
        assert not fixture.capability_allowed(origin + "/source-bucket/%2e%2e/key")
        with pytest.raises(ContextError):
            Context(
                "https://demo.cloudfront.net",
                "ap-southeast-1",
                ("source-bucket",),
                fixture_object_origin=origin,
            )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(2)


@pytest.mark.parametrize(
    "damage", ["instant", "truncated", "missing", "reversed", "nan", "outside", "elapsed"]
)
def test_latency_replay_rejects_incomplete_or_inconsistent_timing(damage):
    samples = [
        {
            "user": u,
            "phase": "timed",
            "status_code": 200,
            "elapsed_ms": 100,
            "started_at": t,
            "ended_at": t + 0.1,
        }
        for t in range(180)
        for u in range(50)
    ]
    window = {
        "started_at": 0,
        "ended_at": 180,
        "warmup_started_at": 0,
        "warmup_ended_at": 0,
        "booked_deadline": 210,
    }
    if damage == "instant":
        samples = samples[:50]
    elif damage == "truncated":
        samples = samples[:4500]
    elif damage == "missing":
        window = None
    elif damage == "reversed":
        samples[0]["ended_at"] = -1
    elif damage == "nan":
        samples[0]["started_at"] = float("nan")
    elif damage == "outside":
        samples[0].update(started_at=181, ended_at=181.1)
    else:
        samples[0]["elapsed_ms"] = 999
    assert not summarize(
        samples, users=50, duration_seconds=180, measurement="status", window=window
    )["eligible"]


def test_retained_reports_keep_inspectable_packages_cases_and_bind_exact_bytes():
    config = "sha256:" + "a" * 64
    raw = json.dumps(
        {
            "Metadata": {"ImageID": config, "Env": "private-sentinel"},
            "Results": [
                {
                    "Class": "os-pkgs",
                    "Type": "debian",
                    "Packages": [{"Name": "libc", "Version": "1", "Log": "private-sentinel"}],
                    "Vulnerabilities": [],
                }
            ],
        }
    ).encode()
    xml = (
        b'<testsuite><testcase name="case[private-sentinel]" '
        b'classname="tests.case" time="1"><system-out>private-sentinel</system-out>'
        b"</testcase></testsuite>"
    )
    scan, tests = retained_reports(raw, xml, source="b" * 40, config_id=config)
    assert b"private-sentinel" not in scan + tests
    assert json.loads(scan)["Results"][0]["Packages"] == [{"Name": "libc", "Version": "1"}]
    assert json.loads(tests)["passed"] == 1
    assert json.loads(scan)["RawReportSHA256"] == hashlib.sha256(raw).hexdigest()
    assert json.loads(tests)["raw_report_sha256"] == hashlib.sha256(xml).hexdigest()
    with pytest.raises(OperationError):
        retained_reports(
            raw,
            b"<testsuite><testcase><failure/></testcase></testsuite>",
            source="b" * 40,
            config_id=config,
        )


def test_local_worker_freshness_bounds_small_clock_skew_and_rejects_stale_receipts():
    from types import SimpleNamespace

    from scripts.aws.local_adapters import LocalData

    observer = LocalData.__new__(LocalData)
    observer.redis = SimpleNamespace(time=lambda: (1000, 0))
    assert observer._fresh({b"dc2_warm_ack": b"1000.001"})
    assert observer._fresh({b"dc2_warm_ack": b"999"})
    assert not observer._fresh({b"dc2_warm_ack": b"1003"})
    assert not observer._fresh({b"dc2_warm_ack": b"879"})


def test_operation_deadline_rejects_a_late_terminal_http_response():
    import httpx

    from scripts.aws.smoke import Ledger, Workflow

    now = [0.0]

    def response(request):
        now[0] = 20
        return httpx.Response(
            200,
            json={
                "id": "00000000-0000-0000-0000-000000000001",
                "filename": "short.mp4",
                "status": "done",
                "submission_status": "submitted",
                "output_url": None,
                "hls_url": None,
                "error": None,
            },
        )

    context = Context("https://demo.cloudfront.net", "ap-southeast-1", ("sources", "outputs"))
    with Client(
        context, api_transport=httpx.MockTransport(response), clock=lambda: now[0]
    ) as client:
        workflow = Workflow(client, Ledger())
        with pytest.raises(ValueError, match="deadline"):
            workflow.poll("00000000-0000-0000-0000-000000000001", deadline=10, clock=lambda: now[0])


@pytest.mark.parametrize("failure", ["redis", "peer", "role"])
def test_concrete_readiness_rejects_dependency_failure(failure):
    from types import SimpleNamespace

    from scripts.aws.exports import REVISIONS
    from scripts.aws.local_bindings import LocalBindings

    binding = LocalBindings.__new__(LocalBindings)
    binding.running = lambda *a, **kw: True
    binding.data = SimpleNamespace(
        schema_revision=lambda *a, **kw: REVISIONS["media"],
        redis=SimpleNamespace(ping=lambda: failure != "redis"),
    )
    binding._owned_roles = lambda *a: failure != "role"
    binding._private_peer = lambda *a: failure != "peer"
    binding.client = SimpleNamespace(request=lambda *a, **kw: (200, b"", {}))
    assert binding.readiness("media", 10) is False


def test_multipart_upload_stops_reading_when_operation_budget_expires():
    import httpx

    ticks = [0]

    def clock():
        ticks[0] += 1
        return ticks[0]

    reached = []
    context = Context("https://demo.cloudfront.net", "ap-southeast-1", ("sources", "outputs"))
    with Client(
        context, api_transport=httpx.MockTransport(lambda r: reached.append(r)), clock=clock
    ) as c:
        with pytest.raises(ContextError, match="upload deadline"):
            c.request(
                "POST", "/api/upload", files={"file": ("short.bin", b"x" * 200000)}, deadline=4
            )
    assert not reached
