"""#64: fixed 1/2/3-encoder runs, interrupted-encoder recovery, dead-letter behaviour, drain.

Encoders are 2-vCPU finite Fargate tasks started only through `Session.batch`, which enforces
the global cap of three (the account's Fargate quota is 6 vCPU). Nothing here starts a task the
session logic would refuse, and nothing leaves one running: every step ends by waiting for its
tasks to be STOPPED and then counting what is still live.

Peak concurrency is computed from each task's own pull-start and stop stamps, not from polling,
and the polled maximum is recorded beside it as a cross-check. Polling resolution (five
seconds) is stated in every receipt that depends on it; the recovery gate is 300 seconds.
"""

import uuid

from scripts.aws.v1.proof import tasks, workflow
from scripts.aws.v1.proof.core import FAIL, PASS, ProofError, percentile

REQUIRED = ("run-1", "run-2", "run-3", "recovery", "dlq", "drain")
CAP = 3
POLL_SECONDS = 5
REQUEUE_GATE_SECONDS = 300
QUEUES = ("ProcessingCommands", "ProcessingWork", "MediaResults")


def verdict(ok, public, private=None):
    return {"status": PASS if ok else FAIL, "public": public, "private": private or {}}


def running_count(ctx):
    reply = ctx.aws.call("ecs", "list-tasks", {
        "cluster": ctx.config["cluster"], "desiredStatus": "RUNNING"},
        deadline=ctx.deadline(60))
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
        "encoders": count, "jobs_submitted": count,
        "outcomes": {s: sum(1 for j in ids if last[j]["status"] == s)
                     for s in sorted({last[j]["status"] for j in ids})},
        "seconds_to_terminal": to_done, "slowest_seconds": max(to_done),
        "median_seconds": percentile(to_done, 0.5),
        "peak_concurrent_from_task_stamps": peak,
        "peak_concurrent_polled": max(samples), "cap": CAP,
        "poll_interval_seconds": POLL_SECONDS,
        "encoder_cpu": sorted({d["cpu"] for d in described}),
        "encoder_memory": sorted({d["memory"] for d in described}),
        "encoder_billed_seconds": [d["billed_seconds"] for d in described],
        "encoder_exit_codes": [d["exit_codes"] for d in described],
        "encoders_left_running": left, "fixture_bytes": jobs[0].get("bytes"),
    }
    ok = (all(last[j]["status"] == "done" for j in ids) and peak <= min(count, CAP)
          and max(samples) <= CAP and len(intent["tasks"]) == count and left == 0)
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
    _, job = workflow.poll_job(ctx, api, intent["job_id"], timeout=timeout, interval=2,
                               until={"processing", *workflow.TERMINAL},
                               checkpoint=proof.checkpoint)
    if job["status"] != "processing":
        raise ProofError("The job finished before it could be interrupted; use a longer fixture")
    stopped = ctx.clock()
    ctx.aws.call("ecs", "stop-task", {
        "cluster": ctx.config["cluster"], "task": first[0],
        "reason": "dc2 evidence: interrupt mid-encode"}, deadline=ctx.deadline(60))
    after, job = workflow.poll_job(
        ctx, api, intent["job_id"], timeout=timeout, interval=POLL_SECONDS,
        until={"queued", "done", "failed", "cancelled"}, checkpoint=proof.checkpoint)
    reacted = round(ctx.clock() - stopped, 1)
    outcome, delay, to_done = job["status"], None, None
    if outcome == "queued":
        # V1 has no unattended worker controller: a requeued job waits for an operator start,
        # and that wait is reported apart from the platform's own reaction time.
        noticed = ctx.clock()
        second = workflow.start_workers(ctx, 1, minutes)
        intent["replacement"] = second
        delay = round(ctx.clock() - noticed, 1)
        _, job = workflow.poll_job(ctx, api, intent["job_id"], timeout=timeout,
                                   interval=POLL_SECONDS, checkpoint=proof.checkpoint)
        to_done = round(ctx.clock() - stopped, 1)
    arns = [first[0], *intent.get("replacement", [])]
    final = workflow.wait_stopped(ctx, arns, timeout=600, checkpoint=proof.checkpoint)
    left = len(workflow.live_tasks(ctx))
    public = {
        "status_after_stop": outcome, "stop_to_reaction_seconds": reacted,
        "reaction_gate_seconds": REQUEUE_GATE_SECONDS,
        "within_gate": reacted <= REQUEUE_GATE_SECONDS,
        "operator_start_delay_seconds": delay, "stop_to_done_seconds": to_done,
        "final_status": job["status"], "poll_interval_seconds": POLL_SECONDS,
        "interrupted_attempts": 1, "encoders_left_running": left,
    }
    ok = (reacted <= REQUEUE_GATE_SECONDS and left == 0
          and (outcome == "failed" or job["status"] == "done"))
    return verdict(ok, public, {"transitions": after, "tasks": [
        tasks.summary(t) for t in final.values()], "job_id": intent["job_id"]})


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
            found[name] = (int(got["ApproximateNumberOfMessages"]),
                           int(got["ApproximateNumberOfMessagesNotVisible"]))
        return found

    before = counts()
    per_queue = {n: {"visible": v, "in_flight": f} for n, (v, f) in before.items()}
    identities = {}
    for name, (visible, _) in before.items():
        if visible:
            identities[name] = dlq.inspect(client, ctx.urls["dlq"][name]["url"], limit=10)
            per_queue[name]["invalid_envelopes"] = sum(
                1 for m in identities[name] if not m.get("valid"))
    public = {"per_queue": per_queue, "poison_provoked": bool(poison)}
    if not poison:
        return verdict(all(v == 0 and f == 0 for v, f in before.values()), public,
                       {"identities": identities})
    intent = proof.intent("dlq")
    marker = intent.setdefault("marker", f"dc2-evidence-poison-{uuid.uuid4().hex[:12]}")
    proof.save()
    if not intent.get("sent"):
        client.send_message(QueueUrl=ctx.outputs["ProcessingCommandsQueueUrl"], MessageBody=marker)
        intent["sent"], intent["sent_at"] = True, ctx.clock()
        proof.save()
    url = ctx.urls["dlq"]["ProcessingCommands"]["url"]

    def arrived():
        got = client.receive_message(QueueUrl=url, MaxNumberOfMessages=10, VisibilityTimeout=30,
                                     WaitTimeSeconds=0).get("Messages", [])
        for message in got:
            if message["Body"] == marker:
                client.delete_message(QueueUrl=url, ReceiptHandle=message["ReceiptHandle"])
                return True, int(message.get("Attributes", {}).get("ApproximateReceiveCount", 0))
        return False, None

    receive_count = tasks.wait_until(ctx, arrived, timeout=wait, interval=30,
                                     checkpoint=proof.checkpoint, session="open")
    public.update(seconds_to_dead_letter=round(ctx.clock() - intent["sent_at"]),
                  receive_count_at_dead_letter=receive_count, poison_removed=True)
    return verdict(True, public, {"identities": identities})


def drain(ctx):
    live = workflow.live_tasks(ctx)
    return verdict(not live, {"encoders_running": len(live)})


def run(ctx, *, fixture, workers=None, short_fixture=None, poison=False, job_timeout=1500,
        minutes=60, only=None, poison_wait=2400):
    proof = ctx.proof(64, REQUIRED)
    steps = {f"run-{n}": ("open", lambda i, n=n: encoder_run(
        ctx, proof, n, fixture, timeout=job_timeout, minutes=minutes)) for n in (1, 2, 3)
        if workers is None or n in workers}
    if short_fixture:
        steps["recovery"] = ("open", lambda i: recovery(
            ctx, proof, short_fixture, timeout=job_timeout, minutes=minutes))
    steps["dlq"] = ("active", lambda i: dead_letters(ctx, proof, poison=poison,
                                                     wait=poison_wait))
    steps["drain"] = ("active", lambda i: drain(ctx))
    for name, (kind, action) in steps.items():
        if only and name not in only:
            continue
        proof.step(name, action, session=kind)
    return proof
