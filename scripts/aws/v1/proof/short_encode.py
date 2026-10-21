"""#93 (V2): short encodes on Lambda against Fargate, on the same fixed short fixture.

    python -m scripts.aws.v1.evidence short-encode --arm fargate ...   stack WITHOUT the lane
    python -m scripts.aws.v1.evidence short-encode --arm lambda  ...   stack WITH the lane
    python -m scripts.aws.v1.evidence short-encode --arm compare ...   no AWS call; reads both

The two arms cannot run in one stack state: with `LambdaShortEncodes=true` every admitted job
goes to the Lambda lane, so a Fargate arm measured there would measure Lambda. Run the Fargate
arm first on the V1 stack, update the stack with the flag, run the Lambda arm with the same
`--state-dir` and `--run-id`, then compare. The receipt (`evidence-93-<run>.json`) accumulates.

Per arm, N jobs of the one fixture. Job 1 is the cold case and jobs 2..N the warm case:

* Fargate cold: the job is submitted and then the operator starts a task, so the task start
  (image pull included) is inside the complete-job latency. Warm: a task is already RUNNING and
  polling when the job is submitted. A finite task encodes once, so each job still needs a task.
* Lambda cold: the first job after `--idle-minutes` of idleness (the encoder's own log line says
  whether it really was a fresh environment; Lambda offers no way to force one). Warm: the jobs
  that follow immediately.

Latency is finalize accepted -> job `done` seen by a 2-second poll, so it is accurate to the poll.
Correctness is the public playback check plus exactly one attempt prefix of outputs in S3.
Cost per success is billed compute only (see `lambda_cost` / `fargate_cost`); anything both arms
share (database, SQS, API, S3, logs) is out of it. A rehearsal against the simulation proves the
harness logic and nothing about AWS.
"""

import json
import math
import re
from pathlib import Path

from processing import short_lane
from scripts.aws.v1.proof import capacity, tasks, unattended, workflow
from scripts.aws.v1.proof.context import LAMBDA_CALL_SECONDS
from scripts.aws.v1.proof.core import FAIL, PASS, ProofError, percentile
from scripts.aws.workers import describe_tasks

ROOT = Path(__file__).resolve().parents[4]
FUNCTION = "ProcessingShortEncoder"
REQUIRED = ("fargate", "lambda", "compare")
ARMS = ("fargate", "lambda")
POLL_SECONDS = 2
SETTLE_SECONDS = 180  # CloudWatch Logs delivery trails an invocation by a few seconds
FREE_EPHEMERAL_MB = 512  # Lambda bills ephemeral storage only above this
# The design's acceptance rule and the V2-live queue-wait target (LV-8): queued_at to started_at.
QUEUE_WAIT_TARGET_SECONDS = 20
COST_BASIS = (
    "billed compute only: Lambda GB-seconds + ephemeral GB-seconds + request, with the REPORT "
    "Init Duration added to Billed Duration (conservative); Fargate pull-to-stop seconds "
    "(60 s minimum) at vCPU + GB + IPv4 rates. Shared services are excluded."
)
REPORT = re.compile(
    r"REPORT RequestId: (?P<id>\S+)\s+Duration: (?P<duration>[\d.]+) ms\s+"
    r"Billed Duration: (?P<billed>\d+) ms\s+Memory Size: (?P<memory>\d+) MB\s+"
    r"Max Memory Used: (?P<used>\d+) MB(?:\s+Init Duration: (?P<init>[\d.]+) ms)?"
)
ENCODE = re.compile(r"dc2\.short_encode (\{.*\})")


# ---- prices and cost --------------------------------------------------------------------------
def load_prices(root=ROOT):
    """Rates from the captured price files; the Lambda rows are the AWS price-list rows."""
    rows = json.loads((root / "docs/execution/aws/v1/prices/AWSLambda-prices.json").read_text())
    lambda_usd = {r["attributes"]["usagetype"]: float(r["usd"]) for r in rows["rows"]}
    worksheet = json.loads((root / "docs/execution/aws/cost-worksheet.json").read_text())
    rates = worksheet["rates_usd"]
    return {
        "lambda_gb_second": lambda_usd["APS1-Lambda-GB-Second"],
        "lambda_request": lambda_usd["APS1-Request"],
        "lambda_storage_gb_second": lambda_usd["APS1-Lambda-Storage-GB-Second"],
        "fargate_vcpu_hour": rates["fargate_vcpu_hour"],
        "fargate_gb_hour": rates["fargate_gb_hour"],
        "ipv4_hour": rates["ipv4_hour"],
    }


def lambda_cost(billed_ms, *, memory_mb, ephemeral_mb, prices):
    seconds = billed_ms / 1000
    compute = seconds * memory_mb / 1024 * prices["lambda_gb_second"]
    storage = (
        seconds
        * max(0, ephemeral_mb - FREE_EPHEMERAL_MB)
        / 1024
        * prices["lambda_storage_gb_second"]
    )
    return compute + storage + prices["lambda_request"]


def fargate_cost(billed_seconds, *, vcpu, memory_gib, prices):
    seconds = max(60, math.ceil(billed_seconds))
    rate = vcpu * prices["fargate_vcpu_hour"] + memory_gib * prices["fargate_gb_hour"]
    return seconds / 3600 * (rate + prices["ipv4_hour"])


# ---- log lines --------------------------------------------------------------------------------
def parse_report(message):
    """billed/init/memory from a Lambda REPORT line, or None for any other line."""
    found = REPORT.search(message)
    if not found:
        return None
    return {
        "request_id": found["id"],
        "duration_ms": float(found["duration"]),
        "billed_ms": int(found["billed"]),
        "memory_mb": int(found["memory"]),
        "max_memory_mb": int(found["used"]),
        "init_ms": float(found["init"]) if found["init"] else None,
    }


def parse_encode(message):
    found = ENCODE.search(message)
    if not found:
        return None
    try:
        payload = json.loads(found[1])
    except ValueError:
        return None
    return payload if isinstance(payload, dict) and payload.get("event") == "short_encode" else None


def read_events(ctx, group, pattern, since_ms):
    """Every message matching a CloudWatch filter pattern since a time, bounded in pages."""
    messages, token = [], None
    for _ in range(40):
        request = {"logGroupName": group, "filterPattern": pattern, "startTime": since_ms}
        if token:
            request["nextToken"] = token
        reply = ctx.aws.call("logs", "filter-log-events", request, deadline=ctx.deadline(60))
        messages += [e["message"] for e in reply.get("events", [])]
        token = reply.get("nextToken")
        if not token:
            break
    return messages


def invocations_by_job(encode_lines, report_lines):
    """{processing job id: [invocation, ...]}, each joined with its REPORT line by request id."""
    reports = {r["request_id"]: r for r in map(parse_report, report_lines) if r}
    found = {}
    for payload in filter(None, map(parse_encode, encode_lines)):
        report = reports.get(payload.get("request_id"), {})
        found.setdefault(payload.get("job_id"), []).append({**payload, "report": report})
    return found


# ---- statistics -------------------------------------------------------------------------------
def spread(values):
    if not values:
        return {"count": 0, "median_seconds": None, "p90_seconds": None, "seconds": []}
    return {
        "count": len(values),
        "median_seconds": percentile(values, 0.5),
        "p90_seconds": percentile(values, 0.9),
        "min_seconds": min(values),
        "max_seconds": max(values),
        "seconds": [round(v, 1) for v in values],
    }


def summarize(rows, *, arm, costs, extra=None):
    """The public view of one arm from per-job rows. Failures stay in the denominators."""
    good = [r for r in rows if r["success"]]
    cold = [r["seconds"] for r in rows if r["phase"] == "cold" and r["status"] == "done"]
    warm = [r["seconds"] for r in rows if r["phase"] == "warm" and r["status"] == "done"]

    def stamped(key, phase=None):
        return [
            r[key]
            for r in rows
            if r.get(key) is not None and (phase is None or r["phase"] == phase)
        ]

    total = sum(costs)
    return {
        "arm": arm,
        "jobs": len(rows),
        "successes": len(good),
        "failures": len(rows) - len(good),
        "cold": spread(cold),
        "warm": spread(warm),
        # The Processing API's own attempt stamps (queued_at -> started_at -> finished_at), so
        # they carry no client clock skew and no polling error.
        "queue_wait": {
            "all": spread(stamped("queue_wait_seconds")),
            "cold": spread(stamped("queue_wait_seconds", "cold")),
            "warm": spread(stamped("queue_wait_seconds", "warm")),
        },
        "processing": spread(stamped("processing_seconds")),
        "retries": sum(r.get("retries", 0) for r in rows),
        "status_regressions": sum(r.get("regressions", 0) for r in rows),
        "poll_interval_seconds": POLL_SECONDS,
        "cost_usd_total": round(total, 6),
        "cost_usd_per_success": round(total / len(good), 6) if good else None,
        "cost_basis": COST_BASIS,
        **(extra or {}),
    }


def regressions(transitions):
    """Count of observed status changes that went backwards (processing -> queued)."""
    order = {"accepted": 0, "queued": 1, "processing": 2, "done": 3, "failed": 3, "cancelled": 3}
    seq = [order.get(s, 0) for _, s in transitions]
    return sum(1 for a, b in zip(seq, seq[1:], strict=False) if b < a)


# ---- S3 correctness ---------------------------------------------------------------------------
def attempt_ids(ctx, processing_job_id):
    """Attempt ids that still have any object version or delete marker under the job."""
    found, markers = set(), {}
    for _ in range(10):
        request = {
            "Bucket": ctx.outputs["OutputBucketName"],
            "Prefix": f"jobs/{processing_job_id}/attempts/",
            **markers,
        }
        reply = ctx.aws.call("s3api", "list-object-versions", request, deadline=ctx.deadline(60))
        for item in reply.get("Versions", []) + reply.get("DeleteMarkers", []):
            found.add(item["Key"].split("/")[3])
        if not reply.get("IsTruncated"):
            break
        markers = {
            "KeyMarker": reply["NextKeyMarker"],
            "VersionIdMarker": reply["NextVersionIdMarker"],
        }
    return found


# ---- the arms ---------------------------------------------------------------------------------
def check_fixture(fixture, seconds, *, allow_over_size=False):
    """``allow_over_size`` is the Fargate arm on a stack that has the lane: a source over the
    size bound is routed to the standard lane at dispatch, whatever the flag says."""
    fixture = Path(fixture)
    if not fixture.is_file():
        raise ProofError("The fixture file does not exist")
    size = fixture.stat().st_size
    if size <= 0 or (size > short_lane.MAX_SOURCE_BYTES and not allow_over_size):
        raise ProofError("The fixture is outside the Lambda lane's size bound")
    if not 0 < seconds <= short_lane.MAX_DURATION_SECONDS:
        raise ProofError("--fixture-seconds must be the fixture's real duration, within the bound")
    return size


def submit_and_wait(ctx, proof, api, fixture, row, timeout):
    """One job to a terminal status. Latency starts when finalize has been accepted."""
    if not row.get("job_id") or not row.get("finalized"):
        row.update(workflow.submit(ctx, api, fixture, row, proof.save))
        row["finalized"] = True
        proof.save()
    started = ctx.clock()
    transitions, job = workflow.poll_job(
        ctx, api, row["job_id"], timeout=timeout, interval=POLL_SECONDS, checkpoint=proof.checkpoint
    )
    row.update(
        status=job["status"],
        seconds=round(ctx.clock() - started, 3),
        regressions=regressions(transitions),
        processing_job_id=job.get("processing_job_id"),
    )
    ok, detail = workflow.playback(ctx, api, job) if job["status"] == "done" else (False, {})
    row["playback_ok"] = ok
    attempt_stamps(api, row)
    return job


def attempt_stamps(api, row):
    """Queue wait and processing time from the job's Processing document (server-side stamps)."""
    pid = row.get("processing_job_id")
    if not pid or row.get("status") != "done":
        return
    reply = api.request("GET", f"/api/processing/jobs/{pid}")
    wait, run, number = capacity.attempt_times(reply.json() if reply.status == 200 else None)
    row.update(queue_wait_seconds=wait, processing_seconds=run, attempt_number=number)


def finish_row(ctx, row, *, expected_invocations=None):
    """Success = done + playable + exactly one attempt of outputs (+ one invocation on Lambda)."""
    attempts = (
        attempt_ids(ctx, row["processing_job_id"])
        if row.get("processing_job_id") and row["status"] == "done"
        else set()
    )
    row["attempt_prefixes"] = len(attempts)
    row["success"] = bool(
        row["status"] == "done"
        and row["playback_ok"]
        and len(attempts) == 1
        and (expected_invocations is None or row.get("invocations") == expected_invocations)
    )
    return row


def fargate_launcher_arm(ctx, proof, intent, *, fixture, jobs, timeout):
    """V2-live: the launcher starts every encoder, so this arm submits and watches.

    Jobs run one at a time, so every task that appears between a submit and the job's end is
    that job's, and each job is a cold start (the launcher starts its encoder after the submit,
    which is what a user of the always-on environment gets). Cost is every worker task that
    ran, claimed or not, so an idle respawn would count against the arm.
    """
    prices, api = load_prices(), workflow.login(ctx)[0]
    rows = intent.setdefault("rows", [{} for _ in range(jobs)])
    for row in rows:
        row["phase"] = "cold"
        if row.get("done"):
            continue
        if "before" not in row:
            row["before"] = sorted(unattended.worker_tasks(ctx))
            proof.save()
        submit_and_wait(ctx, proof, api, fixture, row, timeout)
        new = sorted(a for a in unattended.worker_tasks(ctx) if a not in row["before"])
        final = (
            workflow.wait_stopped(ctx, new, timeout=600, checkpoint=proof.checkpoint) if new else {}
        )
        described = [tasks.summary(t) for t in final.values()]
        row["encoders_started"] = len(new)
        row["billed_seconds"] = sum(d["billed_seconds"] or 0 for d in described)
        row["task_exit_codes"] = [c for d in described for c in d["exit_codes"]]
        row["cost"] = sum(
            fargate_cost(
                d["billed_seconds"] or 0,
                vcpu=int(d["cpu"]) / 1024,
                memory_gib=int(d["memory"]) / 1024,
                prices=prices,
            )
            for d in described
        )
        finish_row(ctx, row)
        row["success"] = row["success"] and len(new) == 1
        row["done"] = True
        proof.save()
    left = len(workflow.live_tasks(ctx))
    public = summarize(
        rows,
        arm="fargate",
        costs=[r["cost"] for r in rows],
        extra={
            "executor_start": "launcher",
            "encoder_billed_seconds": [r["billed_seconds"] for r in rows],
            "encoders_started": sum(r["encoders_started"] for r in rows),
            "encoders_left_running": left,
            "retries": 0,
            "fixture_bytes": rows[0].get("bytes"),
        },
    )
    ok = public["failures"] == 0 and left == 0
    return {
        "status": PASS if ok else FAIL,
        "public": public,
        "private": {"jobs": [r.get("job_id") for r in rows]},
    }


def fargate_arm(ctx, proof, intent, *, fixture, jobs, minutes, timeout):
    # A source over the size bound goes to the standard lane at dispatch, so on a stack that
    # has the lane a fixture over the bound still measures Fargate.
    if f"{FUNCTION}FunctionName" in ctx.outputs and (
        Path(fixture).stat().st_size <= short_lane.MAX_SOURCE_BYTES
    ):
        raise ProofError(
            "This stack has the Lambda lane, so these jobs would run on Lambda. Measure the "
            "Fargate arm on a stack deployed with LambdaShortEncodes=false, or with a fixture "
            "over the size bound"
        )
    if workflow.live_tasks(ctx):
        raise ProofError("Encoder tasks are already running; wait for the drain first")
    if workflow.launcher_owns_workers(ctx):
        return fargate_launcher_arm(ctx, proof, intent, fixture=fixture, jobs=jobs, timeout=timeout)
    prices, api = load_prices(), workflow.login(ctx)[0]
    rows = intent.setdefault("rows", [{} for _ in range(jobs)])
    costs, billed = [], []
    for index, row in enumerate(rows):
        row["phase"] = "cold" if index == 0 else "warm"
        if row.get("done"):
            continue
        if row["phase"] == "warm" and not row.get("tasks"):
            row["tasks"] = workflow.start_workers(ctx, 1, minutes)
            proof.save()
            tasks.wait_until(
                ctx,
                lambda arns=row["tasks"]: _running(ctx, arns),
                timeout=300,
                interval=5,
                checkpoint=proof.checkpoint,
                session="open",
            )
        if not row.get("finalized"):
            row.update(workflow.submit(ctx, api, fixture, row, proof.save))
            row["finalized"] = True
            proof.save()
        if row["phase"] == "cold" and not row.get("tasks"):
            row["tasks"] = workflow.start_workers(ctx, 1, minutes)  # after the job exists
            proof.save()
        submit_and_wait(ctx, proof, api, fixture, row, timeout)
        final = workflow.wait_stopped(ctx, row["tasks"], timeout=600, checkpoint=proof.checkpoint)
        described = [tasks.summary(t) for t in final.values()]
        row["billed_seconds"] = sum(d["billed_seconds"] or 0 for d in described)
        row["task_exit_codes"] = [c for d in described for c in d["exit_codes"]]
        row["cost"] = fargate_cost(
            row["billed_seconds"],
            vcpu=int(described[0]["cpu"]) / 1024,
            memory_gib=int(described[0]["memory"]) / 1024,
            prices=prices,
        )
        finish_row(ctx, row)
        row["done"] = True
        proof.save()
    left = len(workflow.live_tasks(ctx))
    costs = [r["cost"] for r in rows]
    billed = [r["billed_seconds"] for r in rows]
    public = summarize(
        rows,
        arm="fargate",
        costs=costs,
        extra={
            "encoder_billed_seconds": billed,
            "encoders_left_running": left,
            "retries": 0,
            "fixture_bytes": rows[0].get("bytes"),
        },
    )
    ok = public["failures"] == 0 and left == 0
    return {
        "status": PASS if ok else FAIL,
        "public": public,
        "private": {"jobs": [r.get("job_id") for r in rows]},
    }


def _running(ctx, arns):
    found = describe_tasks(ctx.config, ctx.aws, arns, deadline=ctx.deadline(60))
    return all(t["lastStatus"] == "RUNNING" for t in found.values()), found


def lambda_arm(ctx, proof, intent, *, fixture, jobs, timeout, idle_minutes):
    name = ctx.outputs.get(f"{FUNCTION}FunctionName")
    mapping = ctx.outputs.get(f"{FUNCTION}MappingId")
    if not name or not mapping:
        raise ProofError("This stack has no Lambda lane; deploy with LambdaShortEncodes=true")
    state = ctx.aws.call(
        "lambda",
        "get-event-source-mapping",
        {"UUID": mapping},
        deadline=ctx.deadline(LAMBDA_CALL_SECONDS),
    ).get("State")
    if state != "Enabled":
        raise ProofError("The short-encoder mapping is not enabled; open a session first")
    if workflow.live_tasks(ctx):
        raise ProofError("Fargate encoders are running; this arm must be Lambda only")
    prices, api = load_prices(), workflow.login(ctx)[0]
    memory, ephemeral = short_lane.MEMORY_MB, short_lane.EPHEMERAL_STORAGE_MB
    if idle_minutes and not intent.get("idled"):
        # The only lever on a cold start is time: idle the function so its environment expires.
        end = ctx.clock() + 60 * idle_minutes
        while ctx.clock() < end:
            proof.checkpoint("open")
            ctx.sleep(min(30, max(0.0, end - ctx.clock())))
        intent["idled"] = True
    intent.setdefault("since_ms", int(ctx.wall() * 1000))
    proof.save()
    rows = intent.setdefault("rows", [{} for _ in range(jobs)])
    for index, row in enumerate(rows):
        row["phase"] = "cold" if index == 0 else "warm"
        if not row.get("done"):
            submit_and_wait(ctx, proof, api, fixture, row, timeout)
            row["done"] = True
            proof.save()
    group = f"/dc2/{ctx.config['environment_id']}/{FUNCTION}"
    pids = {r["processing_job_id"] for r in rows if r.get("processing_job_id")}
    found = {}
    end = ctx.clock() + SETTLE_SECONDS
    while True:
        encodes = read_events(ctx, group, '"dc2.short_encode"', intent["since_ms"])
        reports = read_events(ctx, group, '"REPORT RequestId"', intent["since_ms"])
        found = invocations_by_job(encodes, reports)
        complete = all(
            any(i["report"] for i in found.get(p, [])) for p in pids if found.get(p)
        ) and pids <= set(found)
        if complete or ctx.clock() >= end:
            break
        ctx.sleep(10)
    costs, observed_cold, redirected = [], None, 0
    for index, row in enumerate(rows):
        calls = found.get(row.get("processing_job_id"), [])
        row["invocations"] = len(calls)
        row["retries"] = max(0, len(calls) - 1)
        row["outcomes"] = [c.get("outcome") for c in calls]
        row["cold_observed"] = bool(calls and calls[0].get("cold"))
        redirected += sum(1 for c in calls if c.get("outcome") == "redirected")
        reports = [c["report"] for c in calls if c["report"]]
        row["billed_ms"] = sum(r["billed_ms"] + (r["init_ms"] or 0) for r in reports)
        row["max_memory_mb"] = max((r["max_memory_mb"] for r in reports), default=None)
        row["cost"] = sum(
            lambda_cost(
                r["billed_ms"] + (r["init_ms"] or 0),
                memory_mb=memory,
                ephemeral_mb=ephemeral,
                prices=prices,
            )
            for r in reports
        )
        costs.append(row["cost"])
        if index == 0:
            observed_cold = row["cold_observed"]
        finish_row(ctx, row, expected_invocations=1)
        row["success"] = row["success"] and bool(reports) and row["outcomes"] == ["finished"]
    depth = _short_queue_depth(ctx)
    public = summarize(
        rows,
        arm="lambda",
        costs=costs,
        extra={
            "cold_start_observed": bool(observed_cold),
            "redirected_to_fargate": redirected,
            "invocations": sum(r["invocations"] for r in rows),
            "billed_ms": [r["billed_ms"] for r in rows],
            "max_memory_mb": max((r["max_memory_mb"] or 0 for r in rows), default=0),
            "memory_mb": memory,
            "ephemeral_mb": ephemeral,
            "timeout_seconds": short_lane.LAMBDA_TIMEOUT_SECONDS,
            "queue_leftover": depth["queued"] + depth["in_flight"],
            "dead_letters": depth["dead"],
            "idle_minutes_before_cold": idle_minutes,
            "fixture_bytes": rows[0].get("bytes"),
        },
    )
    ok = public["failures"] == 0 and public["queue_leftover"] == 0 and public["dead_letters"] == 0
    return {
        "status": PASS if ok else FAIL,
        "public": public,
        "private": {"jobs": [r.get("job_id") for r in rows]},
    }


def _short_queue_depth(ctx):
    client = ctx.sqs()
    names = ("ApproximateNumberOfMessages", "ApproximateNumberOfMessagesNotVisible")

    def count(url):
        got = client.get_queue_attributes(QueueUrl=url, AttributeNames=list(names))["Attributes"]
        return int(got[names[0]]), int(got[names[1]])

    queued, in_flight = count(ctx.outputs["ProcessingShortWorkQueueUrl"])
    dead = sum(count(ctx.outputs["ProcessingShortWorkDlqUrl"]))
    return {"queued": queued, "in_flight": in_flight, "dead": dead}


# ---- the verdict ------------------------------------------------------------------------------
def compare(proof):
    """Pre-registered keep rule applied to both arms. The merge decision is never made here."""
    steps = proof.doc["steps"]
    for arm in ARMS:
        if arm not in steps:
            raise ProofError(f"The {arm} arm has not been run for this run id")
    f, lam = steps["fargate"]["public"], steps["lambda"]["public"]

    def lower(a, b):
        return a is not None and b is not None and a < b

    def median_pair(phase):
        return lam[phase]["median_seconds"], f[phase]["median_seconds"]

    def lambda_queue_wait():
        return ((lam.get("queue_wait") or {}).get("all") or {}).get("median_seconds")

    # With launcher-started encoders (V2-live) Fargate has no warm job: every encoder starts after
    # the submit. The Lambda warm median is then compared with that cold Fargate median, which is
    # the Fargate a user of the always-on environment gets.
    launcher = f.get("executor_start") == "launcher"
    rule = {
        "no_failures_on_either_arm": f["failures"] == 0 and lam["failures"] == 0,
        "lambda_cold_start_observed": bool(lam.get("cold_start_observed")),
        "lambda_no_retries_or_redirects": lam["retries"] == 0
        and lam.get("redirected_to_fargate", 0) == 0,
        "lambda_cold_median_lower": lower(*median_pair("cold")),
        "lambda_warm_median_lower": (
            lower(lam["warm"]["median_seconds"], f["cold"]["median_seconds"])
            if launcher
            else lower(*median_pair("warm"))
        ),
        "lambda_queue_wait_median_within_target": (
            lambda_queue_wait() is not None and lambda_queue_wait() <= QUEUE_WAIT_TARGET_SECONDS
        ),
        "lambda_cost_per_success_not_higher": (
            lam["cost_usd_per_success"] is not None
            and f["cost_usd_per_success"] is not None
            and lam["cost_usd_per_success"] <= f["cost_usd_per_success"]
        ),
    }
    ratio = (
        round(lam["cost_usd_per_success"] / f["cost_usd_per_success"], 3)
        if lam["cost_usd_per_success"] and f["cost_usd_per_success"]
        else None
    )
    return {
        "public": {
            "fargate": {k: f[k] for k in ("successes", "failures", "cold", "warm")}
            | {
                "cost_usd_per_success": f["cost_usd_per_success"],
                "queue_wait": f.get("queue_wait"),
                "executor_start": f.get("executor_start", "operator"),
            },
            "lambda": {k: lam[k] for k in ("successes", "failures", "cold", "warm", "retries")}
            | {
                "cost_usd_per_success": lam["cost_usd_per_success"],
                "queue_wait": lam.get("queue_wait"),
            },
            "queue_wait_target_seconds": QUEUE_WAIT_TARGET_SECONDS,
            "cost_ratio_lambda_over_fargate": ratio,
            "keep_rule": rule,
            "meets_keep_rule": all(rule.values()),
            "merge_decision": "pending",
            "decision_note": (
                "Keep only if every rule holds in a live run; otherwise redeploy without the "
                "flag. This harness records the measurement and never decides the merge."
            ),
        }
    }


def run(
    ctx,
    *,
    arm,
    fixture=None,
    fixture_seconds=None,
    jobs=5,
    minutes=60,
    job_timeout=900,
    idle_minutes=20,
):
    proof = ctx.proof(93, REQUIRED)
    if arm == "compare":
        proof.step("compare", lambda _intent: compare(proof), session=None)
        return proof
    if arm not in ARMS:
        raise ProofError("--arm is fargate, lambda or compare")
    if not 2 <= jobs <= 20:
        raise ProofError("--jobs is 2..20: one cold job and at least one warm job")
    check_fixture(fixture, fixture_seconds, allow_over_size=arm == "fargate")
    if arm == "fargate":
        proof.step(
            "fargate",
            lambda intent: fargate_arm(
                ctx, proof, intent, fixture=fixture, jobs=jobs, minutes=minutes, timeout=job_timeout
            ),
            session="open",
        )
    else:
        proof.step(
            "lambda",
            lambda intent: lambda_arm(
                ctx,
                proof,
                intent,
                fixture=fixture,
                jobs=jobs,
                timeout=job_timeout,
                idle_minutes=idle_minutes,
            ),
            session="open",
        )
    return proof
