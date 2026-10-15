import json
from unittest.mock import Mock
from uuid import uuid4

import httpx
import pytest

from scripts.aws.context import Client, Context
from scripts.aws.smoke import Ledger, Workflow


def test_stored_source_retry_uses_existing_api_and_no_second_upload():
    job = str(uuid4())
    requests = []

    def handler(req):
        requests.append(req)
        return httpx.Response(202, json={"job_id": job})

    config = Context("https://demo.cloudfront.net", "ap-southeast-1", ("sources", "outputs"))
    with Client(config, api_transport=httpx.MockTransport(handler)) as client:
        ledger = Ledger()
        workflow = Workflow(client, ledger)
        assert workflow.upload("short", b"offline-fixture", duration_seconds=1)["job_id"] == job
        assert workflow.retry(job, "stable-key")["job_id"] == job
        assert ledger.upload_bytes == len(b"offline-fixture")
        assert requests[-1].headers["idempotency-key"] == "stable-key"
        assert requests[-1].content == b""


def test_ownership_checks_real_hls_facade_path():
    client = Mock()
    client.request.return_value = (404, b"", {})
    Workflow(client, Ledger()).ownership_denied("job")
    assert client.request.call_args.args == ("GET", "/api/jobs/job/hls/master.m3u8")
    client.request.return_value = (200, b"private", {})
    with pytest.raises(ValueError, match="denied"):
        Workflow(client, Ledger()).ownership_denied("job")


def test_range_and_hls_capabilities_follow_only_isolated_downloader():
    client = Mock()
    client.download.return_value = (206, b"x" * 32, {"content-range": "bytes 0-31/100"})
    workflow = Workflow(client, Ledger())
    assert workflow.range("private-capability")["bytes"] == 32
    client.request.return_value = (307, b"", {"location": "private-capability"})
    client.download.return_value = (200, b"segment", {})
    assert workflow.hls_segment("/api/jobs/job/hls/v0/segment.ts") == {
        "status_code": 200,
        "bytes": 7,
    }
    client.download.assert_called_with("private-capability")


def test_poll_deadline_and_http_error_fail_safely():
    now = [0]
    workflow = Workflow(Mock(), Ledger())
    workflow.json = Mock(return_value={"status": "queued"})

    def sleep(seconds):
        now[0] += seconds

    with pytest.raises(ValueError, match="deadline"):
        workflow.poll("job", deadline=2, clock=lambda: now[0], sleep=sleep)
    workflow = Workflow(Mock(), Ledger())
    workflow.client.request.return_value = (500, b"secret-server-response", {})
    with pytest.raises(ValueError, match="^Unexpected public workflow status$"):
        workflow.json("GET", "/api/jobs/job")


def test_durable_reservations_resume_and_failures_consume_allowance(tmp_path):
    from scripts.aws.evidence import Evidence

    evidence = Evidence(tmp_path / "records")
    ledger = Ledger(upload_limit=4, evidence=evidence)
    ledger.reserve("short", b"abc", duration_seconds=1)
    resumed = Ledger.resume(evidence, upload_limit=4)
    assert resumed.upload_bytes == 3
    with pytest.raises(ValueError, match="exhausted"):
        resumed.reserve("another", b"xx", duration_seconds=1)
    assert len((evidence.directory / "ledger.jsonl").read_text().splitlines()) == 1
    with pytest.raises(ValueError, match="differs"):
        Ledger.resume(evidence, mode="emulator", upload_limit=4)


def test_contract_failure_never_exposes_response_capability():
    workflow = Workflow(Mock(), Ledger())
    private = "https://bucket/private?X-Amz-Signature=sentinel"
    workflow.client.request.return_value = (202, json.dumps({"job_id": private}).encode(), {})
    with pytest.raises(ValueError, match="^Public response contract invalid$") as error:
        workflow.json("POST", "/api/upload", expected=202, route="/upload")
    assert private not in str(error.value)
