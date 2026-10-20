"""#66: warm API latency from an independent Fargate generator, and the cold wake apart.

Warm: a temporary Fargate task definition (registered from the deployed worker image, with no
task role, no secrets and no database access) runs `generator.py` against the Gateway URL, and is
deregistered afterwards even when the run fails. The task registers its own throwaway account,
so no credential is placed in the task overrides (CloudTrail records those). The 50-user status
cycle and the 20-login cycle are judged by `scripts.aws.latency.summarize`, the same arithmetic
the original local gates used; every failure stays in the denominator and nothing is retried.

Cold: only measurable when Aurora has actually paused. The harness polls CloudWatch for up to
15 minutes (Aurora pauses minutes after the last use) and records NOT_RUN only if no pause
shows, then opens the session window (whose readiness probes wake Aurora) and times that. The
data plane applies the new stage throttle a few seconds after `get-stage` confirms it, so it
polls a cheap unauthenticated route until the gate stops answering 429 (bounded, recorded apart
from the wake) before timing the first public requests. The window it opened is closed again
in a `finally`. It is measured from the operator's station, so it includes the network path to
the Gateway; the receipt says so.

The generator refuses a gate too small for 50 users (the default 5 req/s would make the run
measure the throttle, not the API) before it registers anything.
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
    stage_throttle,
)

REQUIRED = ("cold-wake", "generator")
GENERATOR = Path(__file__).with_name("generator.py")
ROOT = Path(__file__).resolve().parents[4]
CPU, MEMORY = "512", "1024"
MARKER, SAMPLES = "DC2-RESULT", "DC2-SAMPLES"
# 50 users each reading once a second need 50 req/s steady, with headroom for the login burst.
LOAD_EDGE_MIN_RATE, LOAD_EDGE_MIN_BURST = 50, 100
PAUSE_WAIT_SECONDS, PAUSE_POLL_SECONDS = 15 * 60, 60  # Aurora pauses minutes after last use
GATE_SETTLE_SECONDS, GATE_POLL_SECONDS = 60, 2
GATE_PROBE_PATH = "/api/media/health"  # unauthenticated and cheap


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
    logs = {
        "logDriver": container["logConfiguration"]["logDriver"],
        "options": {
            **container["logConfiguration"]["options"],
            "awslogs-stream-prefix": "generator",
        },
    }
    return {
        "family": f"{ctx.data['environment_id']}-latency-generator",
        "cpu": CPU,
        "memory": MEMORY,
        "networkMode": "awsvpc",
        "requiresCompatibilities": ["FARGATE"],
        # Pull and log only: no task role, so the generator can reach nothing but the Gateway.
        "executionRoleArn": base["executionRoleArn"],
        "runtimePlatform": base.get(
            "runtimePlatform", {"cpuArchitecture": "X86_64", "operatingSystemFamily": "LINUX"}
        ),
        "containerDefinitions": [
            {
                "name": "generator",
                "image": container["image"],
                "essential": True,
                "entryPoint": ["/usr/bin/env"],
                "command": command,
                "environment": [
                    {"name": "DC2_SCRIPT", "value": packed},
                    {"name": "DC2_BASE_URL", "value": ctx.gateway_url},
                ],
                "logConfiguration": logs,
            }
        ],
        "tags": [
            {"key": "deploy-project", "value": "dc2-v1"},
            {"key": "owner-run", "value": ctx.run_id},
        ],
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
    return zlib.decompress(base64.b64decode("".join(chunks[i][1] for i in sorted(chunks)))).decode()


def parse_samples(text):
    rows = []
    for line in text.splitlines():
        route, phase, user, started, ended, elapsed, code, error = line.split(",")
        rows.append(
            {
                "route": route,
                "phase": phase,
                "user": int(user),
                "started_at": float(started),
                "ended_at": float(ended),
                "elapsed_ms": float(elapsed),
                "status_code": int(code) or None,
                "error": error or None,
            }
        )
    return rows


def judge(result, rows):
    """The issue's gates: status p90 <= 700 ms and login p90 < 2 s, errors < 1%, eligible."""
    users = result["users"]
    windows = result["windows"]
    status = [r for r in rows if r["route"] == "status" and r["phase"] == "timed"]
    login = [r for r in rows if r["route"] == "login"]
    return (
        summarize(
            status,
            users=users,
            duration_seconds=180,
            measurement="status",
            window=windows["status"],
        ),
        summarize(
            login,
            users=20,
            duration_seconds=0,
            measurement="login",
            actual_hash_cost=configured_hash_cost(),
            window=windows["login"],
        ),
    )


def require_load_edge(ctx):
    """Refuse a gate that would throttle the load, before any side effect."""
    gate = ctx.config.get("gateway")
    if not gate:
        raise ProofError("The operator config has no Gateway stage; cannot read the throttle")
    limits = stage_throttle(ctx.aws, gate)
    rate, burst = limits.get("ThrottlingRateLimit") or 0, limits.get("ThrottlingBurstLimit") or 0
    if rate < LOAD_EDGE_MIN_RATE or burst < LOAD_EDGE_MIN_BURST:
        raise ProofError(
            f"The Gateway throttle is {rate:g}/s (burst {burst:g}); the 50-user load needs at "
            f"least {LOAD_EDGE_MIN_RATE}/s (burst {LOAD_EDGE_MIN_BURST}). Set "
            '"edge_open": {"rate": 100, "burst": 200} in operator-config.json and run '
            "`session open` again, then rerun with --fresh"
        )


def throttled(rows, route=None):
    """Requests the Gateway answered 429: reported apart from application errors, which still
    count them in the denominator."""
    return sum(1 for r in rows if r["status_code"] == 429 and route in (None, r["route"]))


def write_samples(ctx, proof, text):
    """Keep each attempt's raw samples under its own name: the first attempt's is
    `latency-samples-<run>.csv`, attempt N's `...-a<N>.csv`. The archived attempt's private
    entry names its file, so a --fresh rerun can never replace the evidence behind an archived
    hash. A file already there is accepted only when it holds exactly these samples (a resumed,
    not fresh, rerun of the same task); otherwise it is refused, never overwritten."""
    number = len(proof.doc.get("attempts", {}).get("generator", [])) + 1
    name = f"latency-samples-{ctx.run_id}" + (f"-a{number}" if number > 1 else "") + ".csv"
    path = ctx.evidence_dir / name
    if path.exists():
        if sha256_text(path.read_text()) != sha256_text(text):
            raise ProofError(f"{name} already holds different samples; it is never overwritten")
        return name
    private_write(path, text)
    return name


def generator(ctx, proof, intent):
    require_load_edge(ctx)
    worker = ctx.outputs["WorkerTaskDefinitionArn"]
    base = ctx.aws.call(
        "ecs", "describe-task-definition", {"taskDefinition": worker}, deadline=ctx.deadline(60)
    )["taskDefinition"]
    packed, command = tasks.ship(GENERATOR)
    arn = intent.get("definition")
    try:
        if not arn:
            registered = ctx.aws.call(
                "ecs",
                "register-task-definition",
                definition_body(ctx, base, packed, command),
                deadline=ctx.deadline(60),
            )
            arn = intent["definition"] = registered["taskDefinition"]["taskDefinitionArn"]
            proof.save()
        task = tasks.run(
            ctx,
            intent,
            proof.save,
            label="latency",
            definition=arn,
            overrides={},
            timeout=900,
            checkpoint=proof.checkpoint,
        )
        reply = ctx.aws.call(
            "ecs", "describe-task-definition", {"taskDefinition": arn}, deadline=ctx.deadline(60)
        )
        group, stream = tasks.log_stream(reply, "generator", task["taskArn"])
        ctx.sleep(10)  # log delivery trails the stop
        lines = tasks.read_lines(ctx, group, stream)
    finally:
        if arn:
            try:
                ctx.aws.call(
                    "ecs",
                    "deregister-task-definition",
                    {"taskDefinition": arn},
                    deadline=ctx.deadline(60),
                )
                intent["deregistered"] = True
                proof.save()
            except Exception:
                intent["deregistered"] = False
    found = tasks.tagged(lines, MARKER)
    if not found or not found[-1].get("ok"):
        raise ProofError(
            "The generator did not complete: "
            + str((found[-1] if found else {}).get("stage", "no result line"))
        )
    result = found[-1]
    text = collect_samples(lines)
    if sha256_text(text) != result["samples_sha256"] or len(text) != result["samples_length"]:
        raise ProofError("The sample stream does not match its recorded hash and length")
    samples_file = write_samples(ctx, proof, text)
    rows = parse_samples(text)
    status, login = judge(result, rows)
    summary = tasks.summary(task)
    timed_status = [r for r in rows if r["route"] == "status" and r["phase"] == "timed"]
    public = {
        "status_cycle": {
            k: status[k]
            for k in (
                "users",
                "duration_seconds",
                "sample_count",
                "p90_ms",
                "error_rate",
                "eligible",
                "status",
            )
        }
        | {"p90_gate_ms": 700, "throttled": throttled(timed_status)},
        "login_cycle": {
            k: login[k]
            for k in (
                "users",
                "sample_count",
                "p90_ms",
                "error_rate",
                "eligible",
                "hash_cost",
                "status",
            )
        }
        | {
            "p90_gate_ms": 2000,
            "hash_cost_source": "configured in source, not read back",
            "throttled": throttled(rows, "login"),
        },
        "routes": {
            label: {
                **described,
                "throttled": throttled([r for r in rows if r["phase"] == "timed"], label),
            }
            for label, described in result["routes"].items()
        },
        "generator": {
            "cpu": summary["cpu"],
            "memory": summary["memory"],
            "billed_seconds": summary["billed_seconds"],
            "separate_task_definition": True,
            "task_role": "none",
            "image_digests": summary["image_digests"],
        },
        "samples_sha256": result["samples_sha256"],
        "samples_length": result["samples_length"],
        "retries": 0,
        "target": "gateway",
        "task_definition_deregistered": intent.get("deregistered", False),
    }
    return verdict(
        status["status"] == "PASS" and login["status"] == "PASS" and intent.get("deregistered"),
        public,
        {"task": summary, "samples_file": samples_file},
    )


def wait_for_pause(ctx, cluster, limit):
    """Poll CloudWatch until the newest datapoint says capacity 0, for at most `limit` seconds.

    Returns (last observation, seconds waited). The last observation is True (paused), False
    (awake) or None (no datapoints), so the NOT_RUN reason can still tell the two apart.
    """
    began = ctx.clock()
    while True:
        asleep = spend.paused_now(ctx, cluster)
        waited = ctx.clock() - began
        if asleep or waited + PAUSE_POLL_SECONDS > limit:
            return asleep, round(waited, 1)
        ctx.sleep(PAUSE_POLL_SECONDS)


def wait_for_gate(ctx, api, public):
    """Probe a cheap unauthenticated route until it stops answering 429 (bounded).

    `get-stage` confirms the new throttle before the data plane applies it, so the first
    request after a window can still meet the closed 0/0 gate. `public` is updated after every
    probe, so a probe that raises still leaves its count and elapsed time in the receipt.
    Returns whether the gate settled.
    """
    began = ctx.clock()
    public["gate_probes"] = 0
    while True:
        public["gate_probes"] += 1
        try:
            reply = api.request("GET", GATE_PROBE_PATH, auth=False, timeout=20)
        finally:
            public["gate_settle_seconds"] = round(ctx.clock() - began, 1)
        waited = ctx.clock() - began
        if reply.status != 429:
            return True
        if waited + GATE_POLL_SECONDS > GATE_SETTLE_SECONDS:
            return False
        ctx.sleep(GATE_POLL_SECONDS)


def session_command(ctx, action, out, *, extra=()):
    scope = ctx.scope
    return session_cli.main(
        [
            action,
            "--config",
            str(ctx.state_dir / "operator-config.json"),
            "--profile",
            scope["profile"],
            "--region",
            scope["region"],
            "--account",
            scope["account"],
            "--deadline-seconds",
            "600",
            *extra,
        ],
        environ={},
        transport_factory=ctx.sdk,
        stdout=out,
        clock=ctx.clock,
        sleep=ctx.sleep,
    )


def close_window(ctx):
    """Close the window cold-wake opened, so the next `session open` is not refused. The drain
    proof reads its counts with the in-VPC task: Aurora was just woken and nothing ran in it."""
    try:
        return session_command(ctx, "close", io.StringIO(), extra=("--in-vpc-counts",)) == 0
    except Exception:
        return False


def cold_wake(ctx, proof, override=None, pause_wait=PAUSE_WAIT_SECONDS):
    cluster = spend.cluster_id(ctx, override)
    asleep, pause_waited = wait_for_pause(ctx, cluster, pause_wait)
    if not asleep:
        why = (
            "no ServerlessDatabaseCapacity datapoints"
            if asleep is None
            else "the database was awake (capacity above 0)"
        )
        return {
            "status": NOT_RUN,
            "public": {
                "reason": f"A cold wake cannot be observed: {why}",
                "pause_wait_seconds": pause_waited,
            },
        }
    public = {"database_paused_before": True, "pause_wait_seconds": pause_waited}
    try:
        ok = measure_wake(ctx, public)
    except Exception as error:  # keep what was gathered; the class only, never the text
        ok = False
        public["reason"] = f"The measurement raised {type(error).__name__} after the window opened"
    finally:  # even a failed or interrupted measurement must not leave the session in `window`
        public["window_closed"] = close_window(ctx)
    if not public["window_closed"]:
        public["recovery"] = (
            "The window this step opened could not be closed: run "
            "`python -m scripts.aws.v1.session close --config <operator-config> "
            "--in-vpc-counts` (with the deploy's scope) before any other step"
        )
    return verdict(ok and public["window_closed"], public)


def measure_wake(ctx, public):
    """Open the window, wait for the gate, then time login and two reads; fills `public`."""
    started = ctx.clock()
    code = session_command(ctx, "window", io.StringIO())
    public["window_open_seconds"] = round(ctx.clock() - started, 1)
    if code:
        public["reason"] = "The session window did not open"
        return False
    api = ctx.api("gateway")
    if not wait_for_gate(ctx, api, public):
        public["reason"] = (
            f"The gateway still answered 429 {GATE_SETTLE_SECONDS} s after "
            "the window was confirmed open"
        )
        return False
    reply, _ = api.login(ctx.credentials())
    first = api.request("GET", "/api/media/jobs", timeout=70)
    second = api.request("GET", "/api/media/jobs", timeout=70)
    public |= {
        "login_ms": reply.ms,
        "first_read_ms": first.ms,
        "second_read_ms": second.ms,
        "statuses": [reply.status, first.status, second.status],
        "retries": 0,
        "measured_from": "operator station (includes the network path to the Gateway)",
        "wake_observed_through": "readiness probes during session window",
    }
    return reply.status == 200 and first.status == 200 and second.status == 200


def run(ctx, *, only=None, cluster=None, pause_wait=PAUSE_WAIT_SECONDS):
    proof = ctx.proof(66, REQUIRED)
    steps = (
        ("cold-wake", "closed", lambda i: cold_wake(ctx, proof, cluster, pause_wait)),
        ("generator", "active", lambda i: generator(ctx, proof, i)),
    )
    for name, kind, action in steps:
        if only and name not in only:
            continue
        proof.step(name, action, session=kind)
    return proof
