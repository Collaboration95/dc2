"""#68 (V2): the unattended encoder launcher against the operator-batch result, same backlog.

    python -m scripts.aws.v1.evidence unattended ...  after `capacity --backlog` and a session
        opened with `session open --unattended` on a stack deployed with `--unattended-launch`

This is the observe-only twin of the backlog driver in `capacity.py`. It uploads N identical
clips with no encoder running and then starts none itself: the launcher Lambda (one tick a
minute) is the only thing that may start a worker, and `Session.batch` refuses while it owns
starts. The harness only watches: jobs, and every worker-family task ECS reports.

Recorded: queue wait and processing time (the Processing API's own attempt stamps), jobs/min on
the same basis as the operator-batch result, peak concurrency (from task stamps and from
polling; the launcher's cap is three), encoders started and starts per job, encoders that
started without ever claiming a job (idle or unclaimed), and any start after the backlog was
empty (an idle respawn). The last job's terminal status opens a settle window in which a correct
launcher starts nothing.

The comparison reads the operator-batch cap-3 step from the #185 receipt of the same run. Both
used the same stack and the same N, so queue wait differs by the launcher's tick and the
encoders' boot, not by the stack. There is no numeric target here: the ratios are reported as
measured and the verdict covers correctness (cap, no idle respawn, nothing left running,
every job done), not speed.
"""

import json
from pathlib import Path

from scripts.aws import workers
from scripts.aws.v1.proof import capacity, tasks, workflow
from scripts.aws.v1.proof.core import FAIL, PASS, ProofError, parse_time, percentile
from scripts.aws.workers import inventory

ISSUE = 68
STEPS = ("launcher-preflight", "launcher-backlog", "launcher-compare")
REQUIRED = STEPS
SETTLE_SECONDS = 180  # the launcher's idle-respawn pause is 120 s: wait past it
UNCLAIMED_LIMIT = 3  # the launcher's own idle breaker stops after three in a row
POLL_SECONDS = capacity.POLL_SECONDS
CAP = capacity.CAP


def verdict(ok, public, private=None):
    return {"status": PASS if ok else FAIL, "public": public, "private": private or {}}


def baseline(ctx):
    """The operator-batch cap-3 step of this run's #185 receipt, or a refusal naming the fix."""
    path = Path(ctx.evidence_dir) / f"evidence-{capacity.BACKLOG_ISSUE}-{ctx.run_id}.json"
    if not path.exists():
        raise ProofError("No #185 receipt for this run id; run `evidence capacity --backlog` "
                         "first, on this stack, so the launcher has a baseline")
    doc = json.loads(path.read_text())
    step = doc.get("steps", {}).get("backlog-3")
    if (doc.get("mode") == "live") == ctx.simulated or not step or step["status"] != PASS:
        raise ProofError("The #185 receipt has no passing backlog-3 step in this mode to "
                         "compare against")
    return step["public"]


def worker_tasks(ctx):
    family = workers.family(ctx.config["task_definitions"]["worker"])
    found = inventory(ctx.config, ctx.aws, deadline=ctx.deadline(120))
    return {a: t for a, t in found.items() if workers.family(t["taskDefinitionArn"]) == family}


def preflight(ctx, *, iam_simulated):
    """What can be verified before a job is uploaded; the IAM simulation is the operator's."""
    if not iam_simulated:
        raise ProofError("Run `aws iam simulate-principal-policy` for the launcher role first "
                         "(deploy-runbook, 'Unattended launcher') and pass --iam-simulated")
    launcher = ctx.config.get("launcher")
    if not launcher:
        raise ProofError("This stack has no launcher; deploy it with `--unattended-launch`")
    with ctx.journal.locked() as state:
        unattended, session = bool(state.get("unattended")), state.get("session")
    rule = ctx.sdk(ctx.scope).call("events", "describe-rule", {"Name": launcher["rule"]},
                                   deadline=ctx.deadline(60)).get("State")
    live = len(worker_tasks_alive(ctx))
    base = baseline(ctx)
    public = {"launcher_in_stack": True, "session": session, "session_unattended": unattended,
              "launcher_rule_state": rule, "encoders_running_at_start": live,
              "baseline_backlog": base.get("backlog"),
              "baseline_fixture_bytes": base.get("fixture_bytes"),
              "iam_simulation": "attested by the operator, not verified by this harness"}
    return verdict(unattended and rule == "ENABLED" and live == 0, public)


def worker_tasks_alive(ctx):
    return {a: t for a, t in worker_tasks(ctx).items() if t["lastStatus"] != "STOPPED"}


def watch(ctx, proof, api, intent, *, timeout, settle):
    """Poll until every job is terminal, then through the settle window. True = timed out."""
    rows, before = intent["jobs"], set(intent["before"])
    begun = ctx.clock()
    polls = 0
    try:
        while True:
            capacity.poll_backlog(ctx, api, rows, intent["submit_started"])
            found = worker_tasks(ctx)
            new = sorted(a for a in found if a not in before)
            alive = sum(1 for t in found.values() if t["lastStatus"] != "STOPPED")
            intent["peak_polled"] = max(intent.get("peak_polled", 0), alive)
            intent["new_tasks"] = new
            done = all(r.get("status") in workflow.TERMINAL for r in rows)
            if done and "empty_wall" not in intent:
                intent["empty_wall"], intent["known_when_empty"] = ctx.wall(), new
            proof.save()
            if done and ctx.wall() - intent["empty_wall"] >= settle:
                return False
            if not done and ctx.clock() - begun >= timeout:
                return True
            polls += 1
            if polls % 6 == 0:
                proof.checkpoint("open")
            ctx.sleep(POLL_SECONDS)
    except BaseException:
        # The launcher keeps running until `session close`; what it started must not outlive
        # this command if the command is what failed.
        capacity.stop_ours(ctx, intent.get("new_tasks", []), "dc2 evidence: unattended aborted")
        raise


def launcher_backlog(ctx, proof, fixture, size, *, timeout, settle):
    intent = proof.intent("launcher-backlog")
    if not intent.get("before"):
        intent["before"] = sorted(worker_tasks(ctx))
    api, _, _ = workflow.login(ctx)
    jobs = intent.setdefault("jobs", [])
    while len(jobs) < size:
        jobs.append({})
    intent.setdefault("submit_started", ctx.wall())
    proof.save()
    for entry in jobs:
        if not entry.get("job_id") or not entry.get("finalized"):
            entry.update(workflow.submit(ctx, api, fixture, entry, proof.save))
            entry["finalized"] = True
            proof.save()
    timed_out = watch(ctx, proof, api, intent, timeout=timeout, settle=settle)
    new = intent.get("new_tasks", [])
    final = workflow.wait_stopped(ctx, new, timeout=600, checkpoint=proof.checkpoint) if new else {}
    left = len(workflow.live_tasks(ctx))
    docs = []
    for row in jobs:
        reply = (api.request("GET", f"/api/processing/jobs/{row['processing_job_id']}")
                 if row.get("processing_job_id") and row.get("status") in workflow.TERMINAL
                 else None)
        docs.append(reply.json() if reply is not None and reply.status == 200 else None)
    stats = capacity.queue_stats(docs)
    described = [tasks.summary(t) for t in final.values()]
    statuses = [r.get("status") for r in jobs]
    done = statuses.count("done")
    stamps = [r["terminal_wall"] for r in jobs if r.get("terminal_wall")]
    ended = max(stamps) if len(stamps) == len(jobs) else ctx.wall()
    elapsed = ended - intent["submit_started"]
    # Claims are attempts that started: a retried job claims more than once.
    claims = sum((d["current_attempt"].get("number") or 1) for d in docs
                 if d and d["current_attempt"].get("started_at"))
    queued = [parse_time(d["current_attempt"]["queued_at"]).timestamp() for d in docs
              if d and d["current_attempt"].get("queued_at")]
    created = sorted(parse_time(t["createdAt"]).timestamp() for t in final.values()
                     if t.get("createdAt"))
    first_queued = min(queued) if queued else None
    after_empty = sorted(set(new) - set(intent.get("known_when_empty", [])))
    unclaimed = max(0, len(new) - claims)
    peak = tasks.peak_overlap(final.values())
    billed = [d["billed_seconds"] for d in described]
    complete = not stats["missing_queue_wait"] and not stats["missing_processing_time"]
    public = {
        "backlog": size, "fixture_bytes": jobs[0].get("bytes"),
        "outcomes": {s: statuses.count(s) for s in sorted(set(map(str, statuses)))},
        "jobs_done": done, "jobs_failed": statuses.count("failed"),
        "jobs_not_terminal": sum(1 for s in statuses if s not in workflow.TERMINAL),
        "timed_out": timed_out, "retried_jobs": stats["retried_jobs"],
        "elapsed_seconds": round(elapsed, 1),
        "jobs_per_minute": capacity.rounded(capacity.rate(done, elapsed)),
        "queue_wait_median_seconds": percentile(stats["waits"], 0.5),
        "queue_wait_p90_seconds": percentile(stats["waits"], 0.9),
        "queue_wait_samples": len(stats["waits"]),
        "processing_median_seconds": percentile(stats["runs"], 0.5),
        "processing_p90_seconds": percentile(stats["runs"], 0.9),
        "missing_queue_wait": stats["missing_queue_wait"],
        "missing_processing_time": stats["missing_processing_time"],
        "encoders_started": len(new), "starts_per_job": round(len(new) / size, 2),
        "jobs_claimed": claims, "unclaimed_encoders": unclaimed,
        "unclaimed_limit": UNCLAIMED_LIMIT,
        "first_start_after_first_queued_seconds": (
            round(created[0] - first_queued, 1) if created and first_queued else None),
        "start_offsets_seconds": [round(c - first_queued, 1) for c in created]
        if first_queued else [],
        "starts_after_backlog_empty": len(after_empty), "settle_seconds": settle,
        "encoder_billed_seconds": billed,
        "encoder_billed_seconds_total": round(sum(b for b in billed if b), 1),
        "peak_concurrent_from_task_stamps": peak,
        "peak_concurrent_polled": intent.get("peak_polled", 0), "cap_limit": CAP,
        "encoders_left_running": left, "poll_interval_seconds": POLL_SECONDS,
        "encoder_nonzero_exits": sum(1 for d in described for c in d["exit_codes"] if c != 0),
        "cap_note": capacity.CAP_NOTE,
    }
    ok = (done == size and not timed_out and complete and left == 0 and peak <= CAP
          and public["peak_concurrent_polled"] <= CAP and not after_empty
          and unclaimed <= UNCLAIMED_LIMIT)
    return verdict(ok, public, {"jobs": jobs, "tasks": described})


def compare(ctx, proof):
    """Unattended against the operator-batch cap-3 step, as measured."""
    step = proof.doc["steps"]["launcher-backlog"]
    unattended, operator = step["public"], baseline(ctx)
    keys = ("backlog", "fixture_bytes")
    comparable = all(unattended.get(k) == operator.get(k) for k in keys)
    rates = (capacity.rate(unattended["jobs_done"], unattended["elapsed_seconds"]),
             capacity.rate(operator["jobs_done"], operator["elapsed_seconds"]))

    def pair(key, digits=1):
        return {"operator_cap3": operator.get(key), "unattended": unattended.get(key),
                "delta": capacity.rounded(unattended[key] - operator[key], digits)
                if unattended.get(key) is not None and operator.get(key) is not None else None}

    public = {
        "backlog": unattended.get("backlog"), "comparable": comparable,
        "jobs_per_minute": {"operator_cap3": capacity.rounded(rates[1]),
                            "unattended": capacity.rounded(rates[0])},
        "throughput_ratio": (
            capacity.rounded(rates[0] / rates[1]) if rates[0] and rates[1] else None),
        "queue_wait_median_seconds": pair("queue_wait_median_seconds"),
        "queue_wait_p90_seconds": pair("queue_wait_p90_seconds"),
        "encoder_billed_seconds_total": pair("encoder_billed_seconds_total"),
        "encoders_started": pair("encoders_started", 0),
        "peak_concurrent_from_task_stamps": pair("peak_concurrent_from_task_stamps", 0),
        "unattended_step_passed": step["status"] == PASS,
        "verdict_rule": "PASS needs the unattended step PASS (every job done, peak concurrency "
                        "at most 3, no start after the backlog emptied, at most 3 unclaimed "
                        "encoders, nothing left running) and the same backlog and fixture as the "
                        "operator-batch step. No speed target: the ratios are as measured.",
        "cap_note": capacity.CAP_NOTE,
    }
    return verdict(step["status"] == PASS and comparable, public)


def run(ctx, *, fixture, backlog=None, drain_timeout=capacity.DRAIN_TIMEOUT,
        settle=SETTLE_SECONDS, iam_simulated=False, only=None):
    proof = ctx.proof(ISSUE, REQUIRED)
    base = baseline(ctx)
    size = backlog or base.get("backlog")
    capacity.check_backlog(size)
    plan = {
        "launcher-preflight": lambda i: preflight(ctx, iam_simulated=iam_simulated),
        "launcher-backlog": lambda i: launcher_backlog(
            ctx, proof, fixture, size, timeout=drain_timeout, settle=settle),
        "launcher-compare": lambda i: compare(ctx, proof),
    }
    for name, action in plan.items():
        if only and name not in only:
            continue
        if name == "launcher-compare" and "launcher-backlog" not in proof.doc["steps"]:
            continue
        # A failed preflight stops the command: nothing is uploaded to a stack that cannot run.
        proof.step(name, action, session=None if name == "launcher-compare" else "open")
        if name == "launcher-preflight" and proof.doc["steps"][name]["status"] != PASS:
            break
    return proof
