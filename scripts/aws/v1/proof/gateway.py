"""#63: workflow and boundary evidence through the real Gateway and CloudFront.

What `PublicSmoke` already proves at deploy time (health, anonymous denial, cookie flags, one
never-finalized reservation) is not repeated here as a pass; this adds what the runbook lists as
"not produced by this pipeline": the direct-to-S3 workflow end to end, CORS and the cookie round
trip through CloudFront, forged-identity and anonymous denial, queue sends by the public
principal, and the database boundary from inside the VPC.

Needs a full `session open` (consumers on, edge open): a job only reaches `done` if a repair
tick and an encoder task run. The harness starts the single finite encoder itself.
"""

import uuid
from pathlib import Path
from urllib.parse import urlencode

from scripts.aws.v1.proof import capacity, tasks, workflow
from scripts.aws.v1.proof.core import FAIL, NOT_RUN, PASS, ProofError, SessionRefused, direct

REQUIRED = ("anonymous-denied", "forged-identity", "session-roundtrip", "cors-preflight",
            "sqs-direct-send", "direct-upload-e2e", "cross-database")
DENIED = {401, 403}
QUEUES = ("ProcessingCommands", "ProcessingWork", "MediaResults")
PROBE = Path(__file__).with_name("probe_crossdb.py")
EVIL_ORIGIN = "https://evil.example"


def verdict(ok, public, private=None):
    return {"status": PASS if ok else FAIL, "public": public, "private": private or {}}


def anonymous_denied(ctx):
    seen = {}
    for origin in ("frontend", "gateway"):
        api = ctx.api(origin)
        for name, path in (("media_jobs", "/api/media/jobs"),
                           ("processing_jobs", f"/api/processing/jobs?asset_ids={uuid.uuid4()}"),
                           ("admin_jobs", "/api/media/admin/jobs")):
            seen[f"{origin}_{name}"] = api.request("GET", path).status
    return verdict(all(v in DENIED for v in seen.values()), {"statuses": seen})


def forged_identity(ctx):
    """The adapter drops x-owner-id/x-role; only the authorizer's context may name an actor."""
    forged = {"x-owner-id": str(uuid.uuid4()), "x-role": "operator"}
    anonymous = ctx.api("frontend")
    seen = {
        "anonymous_jobs": anonymous.request("GET", "/api/media/jobs", headers=forged).status,
        "anonymous_admin": anonymous.request(
            "GET", "/api/media/admin/jobs", headers=forged).status,
    }
    api, _, _ = workflow.login(ctx)
    plain = api.request("GET", "/api/media/jobs")
    spoofed = api.request("GET", "/api/media/jobs", headers=forged)
    admin = api.request("GET", "/api/media/admin/jobs", headers=forged)
    seen.update(authenticated_admin=admin.status, jobs_plain=plain.status,
                jobs_with_forged_headers=spoofed.status)
    same = plain.json() == spoofed.json() and isinstance(plain.json(), list)
    ok = (all(seen[k] in DENIED for k in ("anonymous_jobs", "anonymous_admin",
                                           "authenticated_admin"))
          and plain.status == spoofed.status == 200 and same)
    return verdict(ok, {"statuses": seen, "forged_headers_changed_nothing": same})


def session_roundtrip(ctx):
    """Login through CloudFront, then use the cookie there: the browser's real path."""
    api = ctx.api("frontend")
    reply, attributes = api.login(ctx.credentials())
    flags = " ".join(attributes)
    checks = {
        "http_only": "httponly" in flags, "secure": "secure" in flags,
        "same_site_strict": "samesite=strict" in flags, "host_only": "domain=" not in flags,
        "no_wildcard_cors": reply.first("access-control-allow-origin") != "*",
    }
    me = api.request("GET", "/api/media/auth/me")
    anonymous = ctx.api("frontend").request("GET", "/api/media/auth/me")
    public = {"login_status": reply.status, "me_status": me.status,
              "anonymous_me_status": anonymous.status, **checks,
              "through_cloudfront": "cloudfront" in reply.first("x-cache").lower()
              or "cloudfront" in reply.first("via").lower()}
    ok = (reply.status == 200 and me.status == 200 and anonymous.status in DENIED
          and all(checks.values()) and public["through_cloudfront"])
    return verdict(ok, public)


def cors_preflight(ctx):
    """The browser's two cross-origin hops: S3 (direct upload) and the API (same origin)."""
    api, _, _ = workflow.login(ctx)
    _, data = workflow.reserve(api, _tiny(ctx), str(uuid.uuid4()))
    upload = data["upload"]["url"]
    ask = {"access-control-request-method": "POST", "access-control-request-headers":
           "content-type"}
    good = direct(ctx.http, "OPTIONS", upload, {"origin": ctx.frontend_url, **ask}, None,
                  clock=ctx.clock)
    bad = direct(ctx.http, "OPTIONS", upload, {"origin": EVIL_ORIGIN, **ask}, None,
                 clock=ctx.clock)
    edge = api.request("OPTIONS", "/api/media/jobs", headers={
        "origin": ctx.frontend_url, "access-control-request-method": "GET"}, auth=False)
    public = {
        "s3_allowed_status": good.status,
        "s3_allows_frontend_origin": good.first("access-control-allow-origin") == ctx.frontend_url,
        "s3_allows_post": "POST" in good.first("access-control-allow-methods").upper(),
        "s3_foreign_origin_status": bad.status,
        "s3_foreign_origin_allowed": bool(bad.first("access-control-allow-origin")),
        "api_preflight_status": edge.status,
        "api_wildcard": edge.first("access-control-allow-origin") == "*",
    }
    ok = (good.status == 200 and public["s3_allows_frontend_origin"] and public["s3_allows_post"]
          and not public["s3_foreign_origin_allowed"] and not public["api_wildcard"])
    return verdict(ok, public)


def _tiny(ctx):
    """A throwaway 1 KiB file for a reservation that is never finalized (it expires itself)."""
    path = ctx.state_dir / "evidence" / "cors-probe.mp4"
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.write_bytes(b"dc2-evidence-cors" * 60)
    return path


def sqs_direct_send(ctx):
    """An unsigned SendMessage is what the public principal can do: it must be refused."""
    seen = {}
    body = urlencode({"Action": "SendMessage", "MessageBody": "dc2-evidence-anonymous-send",
                      "Version": "2012-11-05"}).encode()
    for name in QUEUES:
        url = ctx.outputs[f"{name}QueueUrl"]
        reply = direct(ctx.http, "POST", url,
                       {"content-type": "application/x-www-form-urlencoded"}, body,
                       timeout=20, clock=ctx.clock)
        seen[name] = reply.status
    accepted = [n for n, s in seen.items() if s == 200]
    return verdict(all(s in DENIED for s in seen.values()), {
        "statuses": seen, "messages_accepted": len(accepted)}, {"accepted": accepted})


def drive_job(ctx, proof, api, intent, job_id, *, timeout, minutes, interval=5):
    """Poll one job and keep one encoder on it; returns (transitions, last job document).

    The encoder is started only once the job is `queued` with a Processing job id, that is once
    Media's command has reached Processing's work queue, and another is started if one exits
    without claiming (the same rule as the backlog and isolation drivers, for a backlog of
    one). Starting at finalize raced the command: after a Processing release the encoder
    long-polled an empty queue, exited 0 and nothing was left to claim the work (r1018b, #223).
    """
    row = intent.setdefault("row", {"job_id": job_id})
    intent.setdefault("tasks", [])
    start, transitions, polls = ctx.clock(), [], 0
    while True:
        reply = api.request("GET", f"/api/media/jobs/{job_id}")
        job = reply.json() if reply.status == 200 else None
        if job:
            if not transitions or transitions[-1][1] != job["status"]:
                transitions.append((round(ctx.clock() - start, 1), job["status"]))
            row["status"], row["processing_job_id"] = job["status"], job.get("processing_job_id")
            if job["status"] in workflow.TERMINAL:
                return transitions, job
        if ctx.clock() - start >= timeout:
            raise ProofError(
                f"Job did not reach {sorted(workflow.TERMINAL)} within {timeout} seconds")
        if row.get("processing_job_id") and row.get("status") in capacity.QUEUED_STATES:
            live = len(workflow.live_tasks(ctx))
            if capacity.refill(ctx, intent, [row], live, cap=1, minutes=minutes):
                intent.setdefault("started_at", ctx.clock())
                proof.save()
        polls += 1
        if polls % 12 == 0:
            proof.checkpoint("open")
        ctx.sleep(interval)


def direct_upload(ctx, proof, fixture, *, timeout, minutes):
    intent = proof.intent("direct-upload-e2e")
    api, _, _ = workflow.login(ctx)
    if not intent.get("request_id"):
        intent["stale_work_polls"] = workflow.require_empty_work_queue(ctx)
        proof.save()
    sent = workflow.submit(ctx, api, fixture, intent, proof.save)
    transitions, job = drive_job(ctx, proof, api, intent, sent["job_id"], timeout=timeout,
                                 minutes=minutes)
    final = workflow.wait_stopped(ctx, intent["tasks"], timeout=300, checkpoint=proof.checkpoint)
    still = workflow.live_tasks(ctx)
    ok, played = workflow.playback(ctx, api, job) if job["status"] == "done" else (False, {})
    task = list(final.values())[-1]
    public = {
        "job_status": job["status"], "bytes": sent["bytes"],
        "reserve_ms": sent["reserve_ms"], "upload_ms": sent.get("upload_ms"),
        "upload_status": sent.get("upload_status"), "finalize_ms": sent["finalize_ms"],
        "storage_host_is_s3": sent.get("storage_host_is_s3"),
        "transitions": [list(t) for t in transitions],
        "seconds_to_terminal": transitions[-1][0], "encoders_started": len(intent["tasks"]),
        "encoder_exit_codes": tasks.summary(task)["exit_codes"],
        "encoders_left_running": len(still), **played,
    }
    good = job["status"] == "done" and ok and not still
    return verdict(good, public, {"job_id": sent["job_id"], "task": tasks.summary(task)})


def cross_database(ctx, proof, skip=None):
    if skip:
        return {"status": NOT_RUN, "public": {"reason": skip}}
    intent = proof.intent("cross-database")
    definition = ctx.outputs.get("WorkerTaskDefinitionArn")
    if not definition:
        return {"status": NOT_RUN, "public": {"reason": "no worker task definition output"}}
    packed, command = tasks.ship(PROBE)
    overrides = {"cpu": "256", "memory": "512", "containerOverrides": [{
        "name": "worker", "command": command,
        "environment": [{"name": "DC2_SCRIPT", "value": packed}]}]}
    try:
        task = tasks.run(ctx, intent, proof.save, label="crossdb", definition=definition,
                         overrides=overrides, timeout=420, checkpoint=proof.checkpoint)
        found = tasks.result(ctx, definition, "worker", task["taskArn"], "DC2-RESULT")
    except SessionRefused:
        raise
    except ProofError as error:
        return {"status": NOT_RUN, "public": {"reason": str(error)}}
    if not found:
        return {"status": NOT_RUN, "public": {"reason": "the probe printed no result"}}
    if found.get("own_database") != "connected":
        return {"status": NOT_RUN, "public": {
            "reason": "the database was not reachable from the task", "own_database":
            found.get("own_database")}}
    ddl_denied = str(found.get("own_ddl")).startswith("denied")
    other_denied = (str(found.get("other_database")).startswith("connect-denied")
                    or str(found.get("other_database_read")).startswith("denied"))
    public = {"own_ddl_denied": ddl_denied, "other_database_denied": other_denied,
              "own_ddl": found.get("own_ddl"), "other_database": found.get("other_database"),
              "other_database_read": found.get("other_database_read")}
    return verdict(ddl_denied and other_denied, public, {"task": tasks.summary(task)})


def run(ctx, *, fixture, skip_cross_database=None, job_timeout=900, minutes=45, only=None):
    proof = ctx.proof(63, REQUIRED)
    plan = {
        "anonymous-denied": ("active", lambda i: anonymous_denied(ctx)),
        "forged-identity": ("active", lambda i: forged_identity(ctx)),
        "session-roundtrip": ("active", lambda i: session_roundtrip(ctx)),
        "cors-preflight": ("active", lambda i: cors_preflight(ctx)),
        "sqs-direct-send": ("active", lambda i: sqs_direct_send(ctx)),
        "cross-database": ("open", lambda i: cross_database(ctx, proof, skip_cross_database)),
        "direct-upload-e2e": ("open", lambda i: direct_upload(
            ctx, proof, fixture, timeout=job_timeout, minutes=minutes)),
    }
    for name, (kind, action) in plan.items():
        if only and name not in only:
            continue
        proof.step(name, action, session=kind)
    return proof

