"""#66: warm API latency from an independent Fargate generator, and the cold wake apart.

Warm: a temporary Fargate task definition (registered from the deployed worker image, with no
task role, no secrets and no database access) runs `generator.py` against the Gateway URL, and is
deregistered afterwards even when the run fails. The task registers its own throwaway account,
so no credential is placed in the task overrides (CloudTrail records those). The 50-user status
cycle and the 20-login cycle are judged by `scripts.aws.latency.summarize`, the same arithmetic
the original local gates used; every failure stays in the denominator and nothing is retried.

Cold: only measurable when Aurora has actually paused. The harness checks CloudWatch first and
records NOT_RUN if the database is awake, then opens the session window (whose readiness probes
wake Aurora) and times that plus the first public requests. It is measured from the operator's
station, so it includes the network path to the Gateway; the receipt says so.
"""

import base64
import io
import re
import zlib
from pathlib import Path

from scripts.aws.latency import summarize
from scripts.aws.v1 import session_cli
from scripts.aws.v1.proof import spend, tasks
from scripts.aws.v1.proof.core import (
    FAIL,
    NOT_RUN,
    PASS,
    ProofError,
    private_write,
    sha256_text,
)

REQUIRED = ("cold-wake", "generator")
GENERATOR = Path(__file__).with_name("generator.py")
ROOT = Path(__file__).resolve().parents[4]
CPU, MEMORY = "512", "1024"
MARKER, SAMPLES = "DC2-RESULT", "DC2-SAMPLES"


def verdict(ok, public, private=None):
    return {"status": PASS if ok else FAIL, "public": public, "private": private or {}}


def configured_hash_cost():
    """The bcrypt cost the Media service hashes with, read from its source (a configured value,
    not read back from a stored hash: the database is private)."""
    text = (ROOT / "media/services/security.py").read_text()
    found = re.search(r"^BCRYPT_ROUNDS\s*=\s*(\d+)", text, re.M)
    if not found:
        raise ProofError("Cannot find the configured bcrypt cost")
    return int(found.group(1))


def definition_body(ctx, base, packed, command):
    container = base["containerDefinitions"][0]
    logs = {"logDriver": container["logConfiguration"]["logDriver"],
            "options": {**container["logConfiguration"]["options"],
                        "awslogs-stream-prefix": "generator"}}
    return {
        "family": f"{ctx.data['environment_id']}-latency-generator", "cpu": CPU, "memory": MEMORY,
        "networkMode": "awsvpc", "requiresCompatibilities": ["FARGATE"],
        # Pull and log only: no task role, so the generator can reach nothing but the Gateway.
        "executionRoleArn": base["executionRoleArn"],
        "runtimePlatform": base.get("runtimePlatform", {
            "cpuArchitecture": "X86_64", "operatingSystemFamily": "LINUX"}),
        "containerDefinitions": [{
            "name": "generator", "image": container["image"], "essential": True,
            "entryPoint": ["/usr/bin/env"], "command": command,
            "environment": [{"name": "DC2_SCRIPT", "value": packed},
                            {"name": "DC2_BASE_URL", "value": ctx.gateway_url}],
            "logConfiguration": logs}],
        "tags": [{"key": "deploy-project", "value": "dc2-v1"},
                 {"key": "owner-run", "value": ctx.run_id}],
    }


def collect_samples(lines):
    """Reassemble the chunked compressed CSV the generator printed."""
    chunks = {}
    for line in lines:
        if line.startswith(SAMPLES + " "):
            _, index, total, data = line.split(" ", 3)
            chunks[int(index)] = (int(total), data)
    if not chunks or sorted(chunks) != list(range(next(iter(chunks.values()))[0])):
        raise ProofError("The generator's sample chunks are incomplete")
    return zlib.decompress(base64.b64decode("".join(chunks[i][1] for i in sorted(chunks)))
                           ).decode()


def parse_samples(text):
    rows = []
    for line in text.splitlines():
        route, phase, user, started, ended, elapsed, code, error = line.split(",")
        rows.append({"route": route, "phase": phase, "user": int(user),
                     "started_at": float(started), "ended_at": float(ended),
                     "elapsed_ms": float(elapsed), "status_code": int(code) or None,
                     "error": error or None})
    return rows


def judge(result, rows):
    """The issue's gates: status p90 <= 700 ms and login p90 < 2 s, errors < 1%, eligible."""
    users = result["users"]
    windows = result["windows"]
    status = [r for r in rows if r["route"] == "status" and r["phase"] == "timed"]
    login = [r for r in rows if r["route"] == "login"]
    return (
        summarize(status, users=users, duration_seconds=180, measurement="status",
                  window=windows["status"]),
        summarize(login, users=20, duration_seconds=0, measurement="login",
                  actual_hash_cost=configured_hash_cost(), window=windows["login"]),
    )


def generator(ctx, proof, intent):
    worker = ctx.outputs["WorkerTaskDefinitionArn"]
    base = ctx.aws.call("ecs", "describe-task-definition", {"taskDefinition": worker},
                        deadline=ctx.deadline(60))["taskDefinition"]
    packed, command = tasks.ship(GENERATOR)
    arn = intent.get("definition")
    try:
        if not arn:
            registered = ctx.aws.call("ecs", "register-task-definition",
                                      definition_body(ctx, base, packed, command),
                                      deadline=ctx.deadline(60))
            arn = intent["definition"] = registered["taskDefinition"]["taskDefinitionArn"]
            proof.save()
        task = tasks.run(ctx, intent, proof.save, label="latency", definition=arn, overrides={},
                         timeout=900, checkpoint=proof.checkpoint)
        reply = ctx.aws.call("ecs", "describe-task-definition", {"taskDefinition": arn},
                             deadline=ctx.deadline(60))
        group, stream = tasks.log_stream(reply, "generator", task["taskArn"])
        ctx.sleep(10)  # log delivery trails the stop
        lines = tasks.read_lines(ctx, group, stream)
    finally:
        if arn:
            try:
                ctx.aws.call("ecs", "deregister-task-definition", {"taskDefinition": arn},
                             deadline=ctx.deadline(60))
                intent["deregistered"] = True
                proof.save()
            except Exception:
                intent["deregistered"] = False
    found = tasks.tagged(lines, MARKER)
    if not found or not found[-1].get("ok"):
        raise ProofError("The generator did not complete: " + str(
            (found[-1] if found else {}).get("stage", "no result line")))
    result = found[-1]
    text = collect_samples(lines)
    if sha256_text(text) != result["samples_sha256"] or len(text) != result["samples_length"]:
        raise ProofError("The sample stream does not match its recorded hash and length")
    private_write(ctx.evidence_dir / f"latency-samples-{ctx.run_id}.csv", text)
    status, login = judge(result, parse_samples(text))
    summary = tasks.summary(task)
    public = {
        "status_cycle": {k: status[k] for k in (
            "users", "duration_seconds", "sample_count", "p90_ms", "error_rate", "eligible",
            "status")} | {"p90_gate_ms": 700},
        "login_cycle": {k: login[k] for k in (
            "users", "sample_count", "p90_ms", "error_rate", "eligible", "hash_cost", "status")}
        | {"p90_gate_ms": 2000, "hash_cost_source": "configured in source, not read back"},
        "routes": result["routes"],
        "generator": {"cpu": summary["cpu"], "memory": summary["memory"],
                      "billed_seconds": summary["billed_seconds"], "separate_task_definition":
                      True, "task_role": "none", "image_digests": summary["image_digests"]},
        "samples_sha256": result["samples_sha256"], "samples_length": result["samples_length"],
        "retries": 0, "target": "gateway",
        "task_definition_deregistered": intent.get("deregistered", False),
    }
    return verdict(status["status"] == "PASS" and login["status"] == "PASS"
                   and intent.get("deregistered"), public, {"task": summary})


def cold_wake(ctx, proof, override=None):
    cluster = spend.cluster_id(ctx, override)
    asleep = spend.paused_now(ctx, cluster)
    if not asleep:
        why = ("no ServerlessDatabaseCapacity datapoints" if asleep is None
               else "the database was awake (capacity above 0)")
        return {"status": NOT_RUN, "public": {
            "reason": f"A cold wake cannot be observed: {why}"}}
    out = io.StringIO()
    started = ctx.clock()
    scope = ctx.scope
    code = session_cli.main(
        ["window", "--config", str(ctx.state_dir / "operator-config.json"),
         "--profile", scope["profile"], "--region", scope["region"], "--account",
         scope["account"], "--deadline-seconds", "600"],
        environ={}, transport_factory=ctx.sdk, stdout=out)
    window_seconds = round(ctx.clock() - started, 1)
    if code:
        raise ProofError("The session window did not open")
    api = ctx.api("gateway")
    reply, _ = api.login(ctx.credentials())
    first = api.request("GET", "/api/media/jobs", timeout=70)
    second = api.request("GET", "/api/media/jobs", timeout=70)
    public = {
        "database_paused_before": True, "window_open_seconds": window_seconds,
        "login_ms": reply.ms, "first_read_ms": first.ms, "second_read_ms": second.ms,
        "statuses": [reply.status, first.status, second.status], "retries": 0,
        "measured_from": "operator station (includes the network path to the Gateway)",
        "wake_observed_through": "readiness probes during session window",
    }
    return verdict(reply.status == 200 and first.status == 200 and second.status == 200, public)


def run(ctx, *, only=None, cluster=None):
    proof = ctx.proof(66, REQUIRED)
    steps = (("cold-wake", "closed", lambda i: cold_wake(ctx, proof, cluster)),
             ("generator", "active", lambda i: generator(ctx, proof, i)))
    for name, kind, action in steps:
        if only and name not in only:
            continue
        proof.step(name, action, session=kind)
    return proof

