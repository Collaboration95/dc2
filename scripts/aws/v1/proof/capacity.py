"""#64: fixed 1/2/3-encoder runs, interrupted-encoder recovery, dead-letter behaviour, drain.

Encoders are 2-vCPU finite Fargate tasks started only through `Session.batch`, which enforces
the global cap of three (the account's Fargate quota is 6 vCPU). Nothing here starts a task the
session logic would refuse, and nothing leaves one running: every step ends by waiting for its
tasks to be STOPPED and then counting what is still live.

Peak concurrency is computed from each task's own pull-start and stop stamps, not from polling,
and the polled maximum is recorded beside it as a cross-check. Polling resolution (five
seconds) is stated in every receipt that depends on it; the recovery gate is 300 seconds.

`run_backlog` (#185) is the proposal's scalability scenario: a fixed backlog drained at encoder
cap 1, then 2, then 3. See the section at the end of this module.
"""

import math
import uuid

from scripts.aws.transport import OperationError
from scripts.aws.v1.proof import tasks, workflow
from scripts.aws.v1.proof.core import FAIL, PASS, ProofError, percentile, seconds_between

REQUIRED = ("run-1", "run-2", "run-3", "recovery", "dlq", "drain")
CAP = 3
POLL_SECONDS = 5
REQUEUE_GATE_SECONDS = 300
QUEUES = ("ProcessingCommands", "ProcessingWork", "MediaResults")


def verdict(ok, public, private=None):
    return {"status": PASS if ok else FAIL, "public": public, "private": private or {}}


def running_count(ctx):
    reply = ctx.aws.call(
        "ecs",
        "list-tasks",
        {"cluster": ctx.config["cluster"], "desiredStatus": "RUNNING"},
        deadline=ctx.deadline(60),
    )
    return len(reply.get("taskArns", []))


def observe(ctx, api, job_ids, *, timeout, checkpoint):
    """Poll every job to a terminal status, sampling how many encoders run meanwhile."""
    start, seen, samples = ctx.clock(), {j: [] for j in job_ids}, []
    last, polls = {}, 0
    while True:
        for job_id in job_ids:
            if last.get(job_id, {}).get("status") in workflow.TERMINAL:
                continue
            reply = api.request("GET", f"/api/media/jobs/{job_id}")
            job = reply.json() if reply.status == 200 else None
            if job:
                last[job_id] = job
                if not seen[job_id] or seen[job_id][-1][1] != job["status"]:
                    seen[job_id].append((round(ctx.clock() - start, 1), job["status"]))
        samples.append(running_count(ctx))
        if all(last.get(j, {}).get("status") in workflow.TERMINAL for j in job_ids):
            return seen, last, samples
        if ctx.clock() - start >= timeout:
            raise ProofError(f"Jobs did not all finish within {timeout} seconds")
        polls += 1
        if polls % 6 == 0:
            checkpoint("open")
        ctx.sleep(POLL_SECONDS)


def encoder_run(ctx, proof, count, fixture, *, timeout, minutes):
    name = f"run-{count}"
    intent = proof.intent(name)
    if not intent.get("tasks") and workflow.live_tasks(ctx):
        raise ProofError("Encoder tasks are already running; wait for the drain first")
    api, _, _ = workflow.login(ctx)
    jobs = intent.setdefault("jobs", [])
    while len(jobs) < count:
        jobs.append({})
    for entry in jobs:
        if not entry.get("job_id") or not entry.get("finalized"):
            entry.update(workflow.submit(ctx, api, fixture, entry, proof.save))
            entry["finalized"] = True
            proof.save()
    if not intent.get("tasks"):
        intent["tasks"] = workflow.start_workers(ctx, count, minutes)
        proof.save()
    ids = [e["job_id"] for e in jobs]
    seen, last, samples = observe(ctx, api, ids, timeout=timeout, checkpoint=proof.checkpoint)
    final = workflow.wait_stopped(ctx, intent["tasks"], timeout=600, checkpoint=proof.checkpoint)
    left = len(workflow.live_tasks(ctx))
    described = [tasks.summary(t) for t in final.values()]
    peak = tasks.peak_overlap(final.values())
    to_done = [seen[j][-1][0] for j in ids]
    public = {
        "encoders": count,
        "jobs_submitted": count,
        "outcomes": {
            s: sum(1 for j in ids if last[j]["status"] == s)
            for s in sorted({last[j]["status"] for j in ids})
        },
        "seconds_to_terminal": to_done,
        "slowest_seconds": max(to_done),
        "median_seconds": percentile(to_done, 0.5),
        "peak_concurrent_from_task_stamps": peak,
        "peak_concurrent_polled": max(samples),
        "cap": CAP,
        "poll_interval_seconds": POLL_SECONDS,
        "encoder_cpu": sorted({d["cpu"] for d in described}),
        "encoder_memory": sorted({d["memory"] for d in described}),
        "encoder_billed_seconds": [d["billed_seconds"] for d in described],
        "encoder_exit_codes": [d["exit_codes"] for d in described],
        "encoders_left_running": left,
        "fixture_bytes": jobs[0].get("bytes"),
    }
    ok = (
        all(last[j]["status"] == "done" for j in ids)
        and peak <= min(count, CAP)
        and max(samples) <= CAP
        and len(intent["tasks"]) == count
        and left == 0
    )
    return verdict(ok, public, {"jobs": ids, "tasks": described, "transitions": seen})


def recovery(ctx, proof, fixture, *, timeout, minutes):
    """Stop an encoder mid-encode; time how long until the platform reacts, then completes."""
    intent = proof.intent("recovery")
    api, _, _ = workflow.login(ctx)
    if not intent.get("finalized"):
        intent.update(workflow.submit(ctx, api, fixture, intent, proof.save))
        intent["finalized"] = True
        proof.save()
    first = intent.get("tasks") or workflow.start_workers(ctx, 1, minutes)
    intent["tasks"] = first
    proof.save()
    _, job = workflow.poll_job(
        ctx,
        api,
        intent["job_id"],
        timeout=timeout,
        interval=2,
        until={"processing", *workflow.TERMINAL},
        checkpoint=proof.checkpoint,
    )
    if job["status"] != "processing":
        raise ProofError("The job finished before it could be interrupted; use a longer fixture")
    stopped = ctx.clock()
    ctx.aws.call(
        "ecs",
        "stop-task",
        {
            "cluster": ctx.config["cluster"],
            "task": first[0],
            "reason": "dc2 evidence: interrupt mid-encode",
        },
        deadline=ctx.deadline(60),
    )
    after, job = workflow.poll_job(
        ctx,
        api,
        intent["job_id"],
        timeout=timeout,
        interval=POLL_SECONDS,
        until={"queued", "done", "failed", "cancelled"},
        checkpoint=proof.checkpoint,
    )
    reacted = round(ctx.clock() - stopped, 1)
    outcome, delay, to_done = job["status"], None, None
    if outcome == "queued":
        # V1 has no unattended worker controller: a requeued job waits for an operator start,
        # and that wait is reported apart from the platform's own reaction time.
        noticed = ctx.clock()
        second = workflow.start_workers(ctx, 1, minutes)
        intent["replacement"] = second
        delay = round(ctx.clock() - noticed, 1)
        _, job = workflow.poll_job(
            ctx,
            api,
            intent["job_id"],
            timeout=timeout,
            interval=POLL_SECONDS,
            checkpoint=proof.checkpoint,
        )
        to_done = round(ctx.clock() - stopped, 1)
    arns = [first[0], *intent.get("replacement", [])]
    final = workflow.wait_stopped(ctx, arns, timeout=600, checkpoint=proof.checkpoint)
    left = len(workflow.live_tasks(ctx))
    public = {
        "status_after_stop": outcome,
        "stop_to_reaction_seconds": reacted,
        "reaction_gate_seconds": REQUEUE_GATE_SECONDS,
        "within_gate": reacted <= REQUEUE_GATE_SECONDS,
        "operator_start_delay_seconds": delay,
        "stop_to_done_seconds": to_done,
        "final_status": job["status"],
        "poll_interval_seconds": POLL_SECONDS,
        "interrupted_attempts": 1,
        "encoders_left_running": left,
    }
    ok = (
        reacted <= REQUEUE_GATE_SECONDS
        and left == 0
        and (outcome == "failed" or job["status"] == "done")
    )
    return verdict(
        ok,
        public,
        {
            "transitions": after,
            "tasks": [tasks.summary(t) for t in final.values()],
            "job_id": intent["job_id"],
        },
    )


def dead_letters(ctx, proof, *, poison, wait):
    """Dead-letter queue contents after the runs; optionally one provoked poison message."""
    from delivery import dlq

    client = ctx.sqs()
    attrs = ["ApproximateNumberOfMessages", "ApproximateNumberOfMessagesNotVisible"]

    def counts():
        found = {}
        for name in QUEUES:
            url = ctx.urls["dlq"][name]["url"]
            got = client.get_queue_attributes(QueueUrl=url, AttributeNames=attrs)["Attributes"]
            found[name] = (
                int(got["ApproximateNumberOfMessages"]),
                int(got["ApproximateNumberOfMessagesNotVisible"]),
            )
        return found

    before = counts()
    per_queue = {n: {"visible": v, "in_flight": f} for n, (v, f) in before.items()}
    identities = {}
    for name, (visible, _) in before.items():
        if visible:
            identities[name] = dlq.inspect(client, ctx.urls["dlq"][name]["url"], limit=10)
            per_queue[name]["invalid_envelopes"] = sum(
                1 for m in identities[name] if not m.get("valid")
            )
    public = {"per_queue": per_queue, "poison_provoked": bool(poison)}
    if not poison:
        return verdict(
            all(v == 0 and f == 0 for v, f in before.values()), public, {"identities": identities}
        )
    intent = proof.intent("dlq")
    marker = intent.setdefault("marker", f"dc2-evidence-poison-{uuid.uuid4().hex[:12]}")
    proof.save()
    if not intent.get("sent"):
        client.send_message(QueueUrl=ctx.outputs["ProcessingCommandsQueueUrl"], MessageBody=marker)
        intent["sent"], intent["sent_at"] = True, ctx.clock()
        proof.save()
    url = ctx.urls["dlq"]["ProcessingCommands"]["url"]

    def arrived():
        got = client.receive_message(
            QueueUrl=url, MaxNumberOfMessages=10, VisibilityTimeout=30, WaitTimeSeconds=0
        ).get("Messages", [])
        for message in got:
            if message["Body"] == marker:
                client.delete_message(QueueUrl=url, ReceiptHandle=message["ReceiptHandle"])
                return True, int(message.get("Attributes", {}).get("ApproximateReceiveCount", 0))
        return False, None

    receive_count = tasks.wait_until(
        ctx, arrived, timeout=wait, interval=30, checkpoint=proof.checkpoint, session="open"
    )
    public.update(
        seconds_to_dead_letter=round(ctx.clock() - intent["sent_at"]),
        receive_count_at_dead_letter=receive_count,
        poison_removed=True,
    )
    return verdict(True, public, {"identities": identities})


def drain(ctx):
    live = workflow.live_tasks(ctx)
    return verdict(not live, {"encoders_running": len(live)})


def run(
    ctx,
    *,
    fixture,
    workers=None,
    short_fixture=None,
    poison=False,
    job_timeout=1500,
    minutes=60,
    only=None,
    poison_wait=2400,
):
    proof = ctx.proof(64, REQUIRED)
    steps = {
        f"run-{n}": (
            "open",
            lambda i, n=n: encoder_run(
                ctx, proof, n, fixture, timeout=job_timeout, minutes=minutes
            ),
        )
        for n in (1, 2, 3)
        if workers is None or n in workers
    }
    if short_fixture:
        steps["recovery"] = (
            "open",
            lambda i: recovery(ctx, proof, short_fixture, timeout=job_timeout, minutes=minutes),
        )
    steps["dlq"] = ("active", lambda i: dead_letters(ctx, proof, poison=poison, wait=poison_wait))
    steps["drain"] = ("active", lambda i: drain(ctx))
    for name, (kind, action) in steps.items():
        if only and name not in only:
            continue
        proof.step(name, action, session=kind)
    return proof


# ---- #185 backlog throughput ---------------------------------------------------------------
# The proposal's headline scenario (section 3.4) is a fixed backlog drained by 1, 2 and 3
# workers, judged on jobs per minute and queue wait. The 1/2/3 runs above prove parallel
# independence (one job per encoder) but never leave work waiting, so they cannot show it.
#
# Why this needs a driver and not one `Session.batch`: a V1 encoder is a finite task that claims
# at most ONE attempt, encodes it and exits (processing/worker/sqs.py). "Cap" therefore cannot
# mean "N encoders that each work through the backlog". It means the operator keeps up to `cap`
# encoders alive and starts another the moment one stops while work is still queued, which is
# what an operator running batches by hand would do and what the V2 launcher automates. The
# decision rule is the launcher's own: start min(queued - encoders that have not claimed yet,
# cap - encoders alive). Every start goes through `Session.batch`, whose cap of three (the
# account's 6 vCPU Fargate quota over 2-vCPU tasks) and reservation accounting still apply.
BACKLOG_ISSUE = 185
BACKLOG_REQUIRED = ("backlog-1", "backlog-2", "backlog-3", "backlog-compare")
DEFAULT_BACKLOG = 6  # divisible by 1, 2 and 3: 6, 3 and 2 full rounds, no ragged last round
BACKLOG_BOUNDS = (3, 12)  # below 3 the cap-3 step could not even use three encoders
DRAIN_TIMEOUT = 2400  # per cap step; cap 1 is the slow one (six clips one after another)
TARGETS = {2: 1.6, 3: 2.1}  # the proposal's speedup targets over cap 1
REFILL_GAP_GATE = 60  # a longer silence between control polls means encoders were not refilled
LAUNCH_FACTOR = 2  # at most this many starts per queued job, so a dying image cannot loop forever
QUEUED_STATES = {"accepted", "queued"}
CAP_NOTE = (
    "Cap 3 is the ceiling because the account's Fargate on-demand quota is 6 vCPU and each "
    "encoder is a 2-vCPU task; a cap above 3 was not and could not be measured."
)
BASIS_NOTE = (
    "jobs_per_minute = jobs done / (first upload started to last job seen terminal, polled every "
    "5 s); drain_* starts instead at the first encoder launch. Queue wait and processing time are "
    "the Processing API's own attempt stamps (queued_at, started_at, finished_at), so they carry "
    "no client clock skew. p90 is nearest-rank."
)


def attempt_times(doc):
    """(queue wait, processing seconds, attempt number) from a Processing job document.

    Both spans are differences of server-side stamps of the current attempt. A missing stamp or a
    negative span is reported as None: it is never replaced by a client-side guess.
    """
    attempt = (doc or {}).get("current_attempt") or {}
    wait = seconds_between(attempt.get("queued_at"), attempt.get("started_at"))
    run = seconds_between(attempt.get("started_at"), attempt.get("finished_at"))
    return (
        wait if wait is not None and wait >= 0 else None,
        run if run is not None and run >= 0 else None,
        attempt.get("number"),
    )


def queue_stats(docs):
    """Queue-wait and processing-time samples from the jobs' Processing documents."""
    waits, runs, retried, no_wait, no_run = [], [], 0, 0, 0
    for doc in docs:
        wait, run, number = attempt_times(doc)
        retried += 1 if number and number > 1 else 0
        if wait is None:
            no_wait += 1
        else:
            waits.append(wait)
        if run is None:
            no_run += 1
        else:
            runs.append(run)
    return {
        "waits": waits,
        "runs": runs,
        "retried_jobs": retried,
        "missing_queue_wait": no_wait,
        "missing_processing_time": no_run,
    }


def rate(done, seconds):
    """Jobs per minute, or None when it cannot be computed (nothing done, no elapsed time)."""
    return done * 60.0 / seconds if done and seconds and seconds > 0 else None


def rounded(value, digits=4):
    return round(value, digits) if value is not None else None


def speedups(rates):
    """Each cap's rate over cap 1's. None where either side is missing; never defaulted."""
    base = rates.get(1)
    return {
        cap: (value / base if value is not None and base else None)
        for cap, value in rates.items()
        if cap != 1
    }


def meets_targets(ratios):
    return {
        cap: ratios.get(cap) is not None and ratios[cap] >= target
        for cap, target in TARGETS.items()
    }


def ideal_speedup(size, cap):
    """The speedup identical jobs could reach with zero overhead: whole rounds of `cap` jobs."""
    return size / math.ceil(size / cap)


def check_backlog(size):
    low, high = BACKLOG_BOUNDS
    if not low <= size <= high:
        raise ProofError(f"--backlog takes {low} to {high} clips per cap")
    short = [
        f"cap {cap} ({ideal_speedup(size, cap):.2f}x)"
        for cap, target in TARGETS.items()
        if ideal_speedup(size, cap) < target
    ]
    if short:
        raise ProofError(
            f"{size} clips cannot reach the speedup targets even with zero "
            f"overhead at {', '.join(short)}; use a multiple of 6 such as 6 or 12"
        )


def stop_ours(ctx, arns, reason):
    """Best-effort stop of this step's encoders that are still alive (never raises)."""
    try:
        alive = set(workflow.live_tasks(ctx))
    except Exception:  # the caller is already unwinding; stop everything we launched
        alive = set(arns)
    for arn in arns:
        if arn in alive:
            tasks.stop(ctx, arn, reason)


def poll_backlog(ctx, api, rows, started):
    for row in rows:
        if row.get("status") in workflow.TERMINAL:
            continue
        reply = api.request("GET", f"/api/media/jobs/{row['job_id']}")
        job = reply.json() if reply.status == 200 else None
        if not job:
            continue
        if job.get("processing_job_id"):
            row["processing_job_id"] = job["processing_job_id"]
        if job["status"] != row.get("status"):
            row["status"] = job["status"]
            row.setdefault("transitions", []).append(
                [round(ctx.wall() - started, 1), job["status"]]
            )
            if job["status"] in workflow.TERMINAL:
                row["terminal_wall"] = ctx.wall()


def refill(ctx, intent, rows, live, *, cap, minutes):
    """Start the encoders the backlog needs now; returns how many were started.

    Queued jobs not yet claimed need an encoder each, and an encoder that is alive but has not
    claimed anything yet (starting up, or long-polling) already stands for one of them. A job
    shown as `processing` has its encoder. The rest is bounded by the free slots under the cap.
    """
    pending = [r for r in rows if r.get("status", "queued") not in workflow.TERMINAL]
    queued = sum(1 for r in pending if r.get("status", "queued") in QUEUED_STATES)
    busy = sum(1 for r in pending if r.get("status") == "processing")
    want = min(queued - max(0, live - busy), cap - live)
    if want <= 0:
        return 0
    if len(intent["tasks"]) + want > LAUNCH_FACTOR * len(rows):
        raise ProofError(
            "The encoder start budget is spent with jobs still queued; "
            "encoders are exiting without claiming work"
        )
    try:
        started = workflow.start_workers(ctx, want, minutes)
    except OperationError as error:
        if "cap reached" not in str(error):
            raise
        return 0  # a stopping task or an ambiguous reservation still holds a slot; retry
    intent.setdefault("first_launch_wall", ctx.wall())
    intent["tasks"].extend(started)
    return len(started)


def drain_backlog(ctx, proof, api, intent, *, cap, timeout, minutes):
    """Poll the jobs and keep up to `cap` encoders busy until all are terminal. True = timed out."""
    rows, begun = intent["jobs"], ctx.clock()
    intent.setdefault("tasks", [])
    polls = 0
    try:
        while True:
            now = ctx.wall()
            if intent.get("last_poll_wall") is not None:
                intent["max_poll_gap"] = max(
                    intent.get("max_poll_gap", 0), round(now - intent["last_poll_wall"], 1)
                )
            intent["last_poll_wall"] = now
            poll_backlog(ctx, api, rows, intent["submit_started"])
            live = len(workflow.live_tasks(ctx))
            intent["peak_polled"] = max(intent.get("peak_polled", 0), live)
            if all(r.get("status") in workflow.TERMINAL for r in rows):
                proof.save()
                return False
            if refill(ctx, intent, rows, live, cap=cap, minutes=minutes):
                intent["launch_waves"] = intent.get("launch_waves", 0) + 1
            proof.save()
            if ctx.clock() - begun >= timeout:
                return True
            polls += 1
            if polls % 6 == 0:
                proof.checkpoint("open")
            ctx.sleep(POLL_SECONDS)
    except BaseException:
        # An error, a closed session window or an interrupt must not leave encoders billing.
        stop_ours(ctx, intent["tasks"], "dc2 evidence: backlog step aborted")
        raise


def backlog_step(ctx, proof, cap, fixture, size, *, timeout, minutes):
    name = f"backlog-{cap}"
    intent = proof.intent(name)
    leftover = [
        n
        for n, s in proof.doc["steps"].items()
        if n.startswith("backlog-") and n != name and s["public"].get("jobs_not_terminal")
    ]
    if leftover:
        raise ProofError(
            "An earlier backlog step left jobs unfinished; they would join this "
            "backlog and spoil the measurement"
        )
    if not intent.get("tasks") and workflow.live_tasks(ctx):
        raise ProofError("Encoder tasks are already running; wait for the drain first")
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
    # Encoders start only now, with the whole backlog queued, so every cap drains a fixed backlog.
    timed_out = drain_backlog(ctx, proof, api, intent, cap=cap, timeout=timeout, minutes=minutes)
    if timed_out:
        stop_ours(ctx, intent["tasks"], "dc2 evidence: backlog step timed out")
    final = workflow.wait_stopped(ctx, intent["tasks"], timeout=600, checkpoint=proof.checkpoint)
    left = len(workflow.live_tasks(ctx))
    docs = []
    for row in jobs:
        reply = (
            api.request("GET", f"/api/processing/jobs/{row['processing_job_id']}")
            if row.get("processing_job_id") and row.get("status") in workflow.TERMINAL
            else None
        )
        docs.append(reply.json() if reply is not None and reply.status == 200 else None)
    stats = queue_stats(docs)
    described = [tasks.summary(t) for t in final.values()]
    statuses = [r.get("status") for r in jobs]
    done = statuses.count("done")
    stamps = [r["terminal_wall"] for r in jobs if r.get("terminal_wall")]
    ended = max(stamps) if len(stamps) == len(jobs) else ctx.wall()
    elapsed = ended - intent["submit_started"]
    drain = ended - intent["first_launch_wall"] if intent.get("first_launch_wall") else None
    billed = [d["billed_seconds"] for d in described]
    peak = tasks.peak_overlap(final.values())
    gap = intent.get("max_poll_gap", 0)
    complete = not stats["missing_queue_wait"] and not stats["missing_processing_time"]
    public = {
        "cap": cap,
        "backlog": size,
        "fixture_bytes": jobs[0].get("bytes"),
        "outcomes": {s: statuses.count(s) for s in sorted(set(map(str, statuses)))},
        "jobs_done": done,
        "jobs_failed": statuses.count("failed"),
        "jobs_not_terminal": sum(1 for s in statuses if s not in workflow.TERMINAL),
        "timed_out": timed_out,
        "retried_jobs": stats["retried_jobs"],
        "elapsed_seconds": round(elapsed, 1),
        "jobs_per_minute": rounded(rate(done, elapsed)),
        "drain_seconds": round(drain, 1) if drain is not None else None,
        "drain_jobs_per_minute": rounded(rate(done, drain)),
        "queue_wait_median_seconds": percentile(stats["waits"], 0.5),
        "queue_wait_p90_seconds": percentile(stats["waits"], 0.9),
        "queue_wait_samples": len(stats["waits"]),
        "processing_median_seconds": percentile(stats["runs"], 0.5),
        "processing_p90_seconds": percentile(stats["runs"], 0.9),
        "missing_queue_wait": stats["missing_queue_wait"],
        "missing_processing_time": stats["missing_processing_time"],
        "encoders_started": len(intent["tasks"]),
        "launch_waves": intent.get("launch_waves", 0),
        "encoder_billed_seconds": billed,
        "encoder_billed_seconds_total": round(sum(b for b in billed if b), 1),
        "encoder_nonzero_exits": sum(1 for d in described for c in d["exit_codes"] if c != 0),
        "peak_concurrent_from_task_stamps": peak,
        "peak_concurrent_polled": intent.get("peak_polled", 0),
        "cap_limit": CAP,
        "max_poll_gap_seconds": gap,
        "refill_gap_gate_seconds": REFILL_GAP_GATE,
        "poll_interval_seconds": POLL_SECONDS,
        "encoders_left_running": left,
        "encoder_cpu": sorted({d["cpu"] for d in described}),
        "encoder_memory": sorted({d["memory"] for d in described}),
        "cap_note": CAP_NOTE,
    }
    ok = (
        done == size
        and not timed_out
        and left == 0
        and complete
        and gap <= REFILL_GAP_GATE
        and peak <= cap
        and public["peak_concurrent_polled"] <= cap
    )
    return verdict(ok, public, {"jobs": jobs, "tasks": described})


def backlog_compare(proof):
    """Speedup of cap 2 and 3 over cap 1, against the proposal targets. Reads receipts only."""
    steps = {cap: proof.doc["steps"][f"backlog-{cap}"] for cap in (1, 2, 3)}
    pub = {cap: step["public"] for cap, step in steps.items()}
    by = {
        "": lambda p: rate(p.get("jobs_done"), p.get("elapsed_seconds")),
        "drain_": lambda p: rate(p.get("jobs_done"), p.get("drain_seconds")),
    }
    rates = {key: {cap: fn(p) for cap, p in pub.items()} for key, fn in by.items()}
    ratios = {key: speedups(value) for key, value in rates.items()}
    meets = {key: meets_targets(value) for key, value in ratios.items()}
    waits = [pub[cap].get("queue_wait_median_seconds") for cap in (1, 2, 3)]
    sizes = {p.get("backlog") for p in pub.values()}
    comparable = len(sizes) == 1 and len({p.get("fixture_bytes") for p in pub.values()}) == 1
    clean = all(step["status"] == PASS for step in steps.values())

    def table(values, digits=4):
        return {str(cap): rounded(v, digits) for cap, v in values.items()}

    size = next(iter(sizes)) if len(sizes) == 1 else None
    public = {
        "backlog": size,
        "targets": table(TARGETS, 2),
        "basis": BASIS_NOTE,
        "jobs_per_minute": table(rates[""]),
        "speedup": table(ratios[""]),
        "meets_target": {str(c): v for c, v in meets[""].items()},
        "drain_jobs_per_minute": table(rates["drain_"]),
        "drain_speedup": table(ratios["drain_"]),
        "drain_meets_target": {str(c): v for c, v in meets["drain_"].items()},
        "ideal_speedup": table({c: ideal_speedup(size, c) for c in (2, 3)}, 2) if size else None,
        "median_queue_wait_seconds": table(dict(zip((1, 2, 3), waits, strict=True)), 1),
        "p90_queue_wait_seconds": table(
            {c: pub[c].get("queue_wait_p90_seconds") for c in (1, 2, 3)}, 1
        ),
        "median_queue_wait_decreasing": (
            all(w is not None for w in waits) and waits[0] > waits[1] > waits[2]
        ),
        "jobs_failed": {str(c): pub[c].get("jobs_failed") for c in (1, 2, 3)},
        "encoder_billed_seconds_total": table(
            {c: pub[c].get("encoder_billed_seconds_total") for c in (1, 2, 3)}, 1
        ),
        "encoders_left_running": {str(c): pub[c].get("encoders_left_running") for c in (1, 2, 3)},
        "all_cap_steps_passed": clean,
        "comparable": comparable,
        "cap_note": CAP_NOTE,
        "verdict_rule": "PASS needs every cap step PASS, one backlog size and fixture, and "
        "speedup >= 1.6 at cap 2 and >= 2.1 at cap 3 on the jobs_per_minute basis",
    }
    ok = clean and comparable and all(meets[""].values())
    return verdict(ok, public)


def run_backlog(
    ctx,
    *,
    fixture,
    backlog=DEFAULT_BACKLOG,
    workers=None,
    minutes=60,
    drain_timeout=DRAIN_TIMEOUT,
    only=None,
):
    """#185: drain a fresh backlog of `backlog` identical clips at cap 1, 2 and 3, then compare."""
    check_backlog(backlog)
    proof = ctx.proof(BACKLOG_ISSUE, BACKLOG_REQUIRED)
    for cap in (1, 2, 3):
        name = f"backlog-{cap}"
        if (workers is not None and cap not in workers) or (only and name not in only):
            continue
        proof.step(
            name,
            lambda i, cap=cap: backlog_step(
                ctx, proof, cap, fixture, backlog, timeout=drain_timeout, minutes=minutes
            ),
            session="open",
        )
    # The comparison reads only receipts, so it runs once all three caps have been recorded.
    if all(f"backlog-{cap}" in proof.doc["steps"] for cap in (1, 2, 3)) and (
        not only or "backlog-compare" in only
    ):
        proof.step("backlog-compare", lambda i: backlog_compare(proof), session=None)
    return proof
