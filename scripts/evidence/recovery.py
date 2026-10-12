"""Real local failure experiments. Each fault is restored even when assertions fail."""

import json
import time
from uuid import uuid4

from scripts.dev.runtime import compose
from scripts.dev.scenario import Scenario, fixture


def command(scenario, *args, timeout=75):
    return compose(scenario.state, *args, timeout=timeout, capture_output=True, text=True)


def retry(scenario, client, user, asset, old_attempt):
    key = str(uuid4())
    headers = {"Idempotency-Key": key}
    first = scenario.request(
        client, "POST", f"jobs/{asset}/retry", 202, route="/jobs/{job_id}/retry", headers=headers
    )
    again = scenario.request(
        client, "POST", f"jobs/{asset}/retry", 202, route="/jobs/{job_id}/retry", headers=headers
    )
    assert first["job_id"] == again["job_id"] == asset
    scenario.wait(client, asset, timeout=240)
    job = scenario.processing_job(user["id"], asset)
    assert job["current_attempt"]["attempt_id"] != old_attempt
    assert job["current_attempt"]["number"] == 2
    assert sum(output["kind"] == "primary" for output in job["outputs"]) == 1
    scenario.passed("CT-06", "Replayed retry produced one new attempt and one primary output")
    return job


def worker_kill(scenario, source):
    client, user, _ = scenario.account("kill")
    asset = scenario.upload(client, source)["job_id"]
    scenario.wait(client, asset, states=("processing",), timeout=45)
    before = scenario.processing_job(user["id"], asset)
    started = time.monotonic()
    command(scenario, "kill", "-s", "SIGKILL", "worker", timeout=15)
    try:
        scenario.wait(client, asset, states=("failed",), timeout=300)
        elapsed = time.monotonic() - started
        assert elapsed <= 300
    finally:
        command(scenario, "up", "-d", "--no-deps", "worker")
    after = retry(scenario, client, user, asset, before["current_attempt"]["attempt_id"])
    scenario.record(
        "worker-kill",
        asset_id=asset,
        job_id=after["job_id"],
        failed_attempt_id=before["current_attempt"]["attempt_id"],
        retry_attempt_id=after["current_attempt"]["attempt_id"],
        visible_failure_seconds=round(elapsed, 3),
        bound_seconds=300,
    )
    scenario.request(client, "DELETE", f"jobs/{asset}", 204, route="/jobs/{job_id}")


def queue_loss(scenario, source):
    client, user, _ = scenario.account("queue-loss")
    command(scenario, "stop", "worker", "processing-recovery")
    try:
        asset = scenario.upload(client, source)["job_id"]
        before = scenario.processing_job(user["id"], asset)
        attempt = before["current_attempt"]["attempt_id"]
        # Diagnostic fault injection uses Processing's own queue configuration.
        # Preserve the RQ hash deliberately: existence must not mean runnable.
        code = (
            "import json; from processing.queue import get_queue; q=get_queue(); "
            f"a={json.dumps(attempt)}; "
            "removed=q.connection.lrem(q.key,0,a); "
            "assert removed==1, 'expected queued payload'; "
            "assert q.connection.exists('rq:job:'+a), 'job hash must survive'; "
            "print(json.dumps({'removed':removed,'hash_survives':True}))"
        )
        injected = command(scenario, "exec", "-T", "processing", "python", "-c", code)
        assert json.loads(injected.stdout)["hash_survives"] is True
        started = time.monotonic()
        command(scenario, "up", "-d", "--no-deps", "processing-recovery")
        deadline = started + 120
        probe = (
            "from processing.queue import get_queue; q=get_queue(); "
            f"print(int(q.connection.lpos(q.key,{json.dumps(attempt)}) is not None))"
        )
        while time.monotonic() < deadline:
            available = command(
                scenario, "exec", "-T", "processing", "python", "-c", probe, timeout=10
            ).stdout.strip()
            if available == "1":
                break
            time.sleep(0.5)
        else:
            raise TimeoutError("Lost queue item was not repaired within 120s")
        elapsed = time.monotonic() - started
        assert elapsed <= 120
        after = scenario.processing_job(user["id"], asset)
        assert after["current_attempt"]["attempt_id"] == attempt
        scenario.record(
            "queue-loss-repair",
            asset_id=asset,
            job_id=before["job_id"],
            attempt_id=attempt,
            hash_survives=True,
            reenqueue_seconds=round(elapsed, 3),
            bound_seconds=120,
        )
    finally:
        command(scenario, "up", "-d", "--no-deps", "worker", "processing-recovery")
    scenario.wait(client, asset)
    scenario.passed(
        "CT-12", "Real Redis list entry lost with surviving hash, repaired with same Attempt"
    )
    scenario.request(client, "DELETE", f"jobs/{asset}", 204, route="/jobs/{job_id}")


def processing_outage(scenario, source):
    client, _, _ = scenario.account("pending")
    completed = scenario.upload(client, source)["job_id"]
    scenario.wait(client, completed)
    command(scenario, "stop", "processing", "media-recovery")
    key = str(uuid4())
    try:
        accepted = scenario.upload(client, source, key)
        asset = accepted["job_id"]
        pending = scenario.request(client, "GET", f"jobs/{asset}", 200, route="/jobs/{job_id}")
        assert pending["status"] == "queued" and pending["submission_status"] == "pending"
        scenario.request(client, "GET", f"jobs/{completed}", 503, route="/jobs/{job_id}")
        command(scenario, "restart", "media")
        # Readiness polling is distinct from retrying a failing acceptance assertion.
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            reply = client.get("health")
            if reply.status_code == 200:
                break
            time.sleep(0.5)
        else:
            raise TimeoutError("Media did not restart")
        restored = scenario.request(client, "GET", f"jobs/{asset}", 200, route="/jobs/{job_id}")
        assert restored["submission_status"] == "pending"
        assert scenario.upload(client, source, key)["job_id"] == asset
        scenario.record("pending-survives-restart", asset_id=asset)
    finally:
        command(scenario, "up", "-d", "--no-deps", "processing", "media-recovery")
    scenario.wait(client, asset)
    scenario.passed(
        "CT-13",
        "Processing outage accepts durable pending source/Asset, survives restart, converges",
    )
    scenario.passed("CT-14", "Submitted Asset returns 503 while Processing is down")
    for item in (asset, completed):
        scenario.request(client, "DELETE", f"jobs/{item}", 204, route="/jobs/{job_id}")


def run(run_id):
    scenario = Scenario(run_id, "recovery")
    source = scenario.artifacts / "fault.mp4"
    try:
        scenario.report["fixture"] = fixture(source, seconds=20, width=1280, height=720)
        worker_kill(scenario, source)
        queue_loss(scenario, source)
        processing_outage(scenario, source)
        scenario.finish()
    except BaseException as error:
        scenario.finish(error)
        raise
    print(f"PASS: {scenario.artifacts / 'result.json'}")
