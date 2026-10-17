"""#196: Media keeps accepting uploads while Processing is down, and Processing catches up.

The two services meet only at queues: Media's finalize writes a command to its own outbox and
never calls Processing. This step proves it on the deployed stack. It switches off Processing's
command consumer (the `ProcessingCommands` event source mapping), then reserves and finalizes
an upload through the public API exactly as a browser does, and checks that:

* finalize answers 2xx and the asset is visible and still waiting (`accepted` or `queued`);
* Processing has not seen it (no Processing job id is projected back to Media);
* the command is held, in Media's outbox (`submission_status` pending) or in the commands queue
  (its depth, read from SQS).

Then it switches the consumer back on, starts one finite encoder once Processing has picked the
command up (and another if that one exits without claiming, the same rule as the backlog driver),
and requires the job to reach `done` within the gate.

"Down" means the consumer is off: it is the only path from Media's write side to Processing. The
Processing API stays up. Under this stack's `zero_reservation: off` policy a Lambda cannot be
quiesced without writing reserved concurrency the session does not use, and `session status`
would then report drift; a mapping is the one switch the session itself already owns.

The mapping is restored on every exit path: normal end, an error, an interrupt, a closed session.
A closed session is the exception that proves the rule: `session close` has already disabled
every mapping and re-enabling one would reopen a consumer inside a closed window, so the step
leaves it disabled and says so. The intent is journaled before the mapping is touched, so a
killed process resumes from the receipt and a rerun finishes the job.
"""

from scripts.aws.v1.proof import capacity, tasks, workflow
from scripts.aws.v1.proof.context import LAMBDA_CALL_SECONDS
from scripts.aws.v1.proof.core import FAIL, PASS, ProofError

ISSUE = 196
REQUIRED = ("processing-down",)
STEP = "processing-down"
HOLD_MIN_SECONDS = 30  # keep the consumer off at least this long once the command is visible
HOLD_SECONDS = 150  # and at most this long waiting for it to reach the queue (repair is 1/min)
CATCH_UP_SECONDS = 120  # wait for Processing to take the command before starting the encoder
POLL_SECONDS = 5
WAITING = {"accepted", "queued"}  # what Media may show before Processing has acknowledged
QUEUE_ATTRIBUTES = ["ApproximateNumberOfMessages", "ApproximateNumberOfMessagesNotVisible",
                    "ApproximateNumberOfMessagesDelayed"]


def mapping_id(ctx):
    try:
        return ctx.outputs["ProcessingCommandsMappingId"]
    except KeyError:
        raise ProofError("The stack outputs name no ProcessingCommands mapping") from None


def mapping_state(ctx, transport, identity):
    reply = transport.call("lambda", "get-event-source-mapping", {"UUID": identity},
                           deadline=ctx.deadline(LAMBDA_CALL_SECONDS))
    return reply.get("State")


def set_mapping(ctx, transport, identity, enabled):
    """Enable or disable the mapping and wait until Lambda reports that state."""
    transport.call("lambda", "update-event-source-mapping",
                   {"UUID": identity, "Enabled": enabled},
                   deadline=ctx.deadline(LAMBDA_CALL_SECONDS))
    want = "Enabled" if enabled else "Disabled"

    def reached():
        state = mapping_state(ctx, transport, identity)
        return state == want, state

    return tasks.wait_until(ctx, reached, timeout=180, interval=3)


def commands_queue_depth(ctx):
    """Messages the ProcessingCommands queue holds: visible, in flight or delayed."""
    got = ctx.sqs().get_queue_attributes(
        QueueUrl=ctx.outputs["ProcessingCommandsQueueUrl"], AttributeNames=QUEUE_ATTRIBUTES)
    return sum(int(got["Attributes"].get(name, 0)) for name in QUEUE_ATTRIBUTES)


def session_allows_consumers(ctx):
    with ctx.journal.locked() as state:
        return state.get("session") == "open" and not state.get("paused")


def restore(ctx, transport, intent, save, *, quiet):
    """Put the consumer back as the session wants it. Safe to call again.

    Open session: re-enable and wait for it. Anything else: leave it, the session owns it.
    `quiet` is for unwinding after another failure: it records and swallows its own error.
    """
    if not intent.get("mapping_disabled"):
        return
    try:
        if session_allows_consumers(ctx):
            set_mapping(ctx, transport, mapping_id(ctx), True)
            intent["restore"] = "re-enabled"
            intent.setdefault("reenabled_wall", ctx.wall())
        else:
            intent["restore"] = "left disabled: the session is not open"
        intent["mapping_disabled"] = False
    except Exception as error:
        if not quiet:
            raise
        intent["restore_error"] = type(error).__name__
    finally:
        save()


def job_view(api, job_id):
    reply = api.request("GET", f"/api/media/jobs/{job_id}")
    return reply.status, (reply.json() if reply.status == 200 else None)


def listed(api, job_id):
    reply = api.request("GET", "/api/media/jobs")
    body = reply.json()
    return reply.status == 200 and isinstance(body, list) and any(
        isinstance(j, dict) and j.get("id") == job_id for j in body)


def observe_outage(ctx, proof, api, intent, *, hold):
    """Watch the waiting upload while the consumer is off; returns what was held and seen."""
    seen = intent.setdefault("outage", {
        "depth_max": 0, "outbox_pending_seen": False, "progressed": False, "status": None,
        "submission_status": None, "visible_by_id": False, "polls": 0})
    job_id, begun = intent["job_id"], ctx.clock()
    while True:
        status, job = job_view(api, job_id)
        seen["polls"] += 1
        seen["visible_by_id"] = status == 200
        if job:
            seen["status"], seen["submission_status"] = job["status"], job.get("submission_status")
            seen["outbox_pending_seen"] |= job.get("submission_status") == "pending"
            if job.get("processing_job_id") or job["status"] not in WAITING:
                seen["progressed"] = True
        seen["depth_max"] = max(seen["depth_max"], commands_queue_depth(ctx))
        proof.save()
        waited = ctx.clock() - begun
        if seen["progressed"] or waited >= hold or (
                seen["depth_max"] >= 1 and waited >= HOLD_MIN_SECONDS):
            break
        proof.checkpoint("open")
        ctx.sleep(POLL_SECONDS)
    seen["in_list"] = listed(api, job_id)
    seen["held_seconds"] = round(ctx.clock() - begun, 1)
    intent["outage_checked"] = True
    proof.save()
    return seen


def wait_catch_up(ctx, proof, api, intent):
    """Seconds from re-enabling until Processing's job id reaches Media, or None if not seen."""
    begun = ctx.clock()
    while ctx.clock() - begun < CATCH_UP_SECONDS:
        _, job = job_view(api, intent["job_id"])
        if job and (job.get("processing_job_id") or job["status"] not in WAITING):
            return round(ctx.clock() - begun, 1)
        proof.checkpoint("open")
        ctx.sleep(POLL_SECONDS)
    return None


def finish_job(ctx, proof, api, intent, *, gate, minutes):
    """Keep one encoder alive until the job is terminal or the gate passes (the same rule as
    the backlog driver, for a backlog of one)."""
    row, begun = intent["row"], ctx.clock()
    row["job_id"] = intent["job_id"]
    intent.setdefault("tasks", [])
    while True:
        _, job = job_view(api, intent["job_id"])
        if job:
            row["status"] = job["status"]
            row["processing_job_id"] = job.get("processing_job_id")
        if row.get("status") in workflow.TERMINAL or ctx.clock() - begun >= gate:
            return job
        live = len(workflow.live_tasks(ctx))
        if capacity.refill(ctx, intent, [row], live, cap=1, minutes=minutes):
            proof.save()
        proof.checkpoint("open")
        ctx.sleep(POLL_SECONDS)


def processing_down(ctx, proof, fixture, *, gate, minutes, hold):
    intent = proof.intent(STEP)
    transport = ctx.sdk(ctx.scope)
    identity = mapping_id(ctx)
    if not intent.get("tasks") and workflow.live_tasks(ctx):
        raise ProofError("Encoder tasks are already running; wait for the drain first")
    if not intent.get("disabled_wall") and not intent.get("mapping_disabled"):
        before = mapping_state(ctx, transport, identity)
        if before != "Enabled":
            raise ProofError(f"The ProcessingCommands mapping is {before}, not Enabled; "
                             "open the session first")
        intent["mapping_before"] = before
    api, _, _ = workflow.login(ctx)
    row = intent.setdefault("row", {})
    try:
        if not intent.get("disabled_wall"):
            intent["mapping_disabled"] = True  # recorded first: a crash must find it
            proof.save()
            intent["mapping_during"] = set_mapping(ctx, transport, identity, False)
            intent["disabled_wall"] = ctx.wall()
            proof.save()
        if not row.get("finalized"):
            row.update(workflow.submit(ctx, api, fixture, row, proof.save))
            row["finalized"] = True
            intent["job_id"] = row["job_id"]
            proof.save()
        outage = intent.get("outage") if intent.get("outage_checked") else observe_outage(
            ctx, proof, api, intent, hold=hold)
        restore(ctx, transport, intent, proof.save, quiet=False)
        if intent.get("restore") != "re-enabled":
            raise ProofError("The consumer was not re-enabled: " + intent.get("restore", "?"))
        if "catch_up" not in intent:
            intent["catch_up"] = wait_catch_up(ctx, proof, api, intent)
            proof.save()
        catch_up = intent["catch_up"]
        final = finish_job(ctx, proof, api, intent, gate=gate, minutes=minutes)
        if not final or final["status"] not in workflow.TERMINAL:  # the gate passed: stop, record
            capacity.stop_ours(ctx, intent.get("tasks", []), "dc2 evidence: isolation gate passed")
        stopped = workflow.wait_stopped(ctx, intent["tasks"], timeout=600,
                                        checkpoint=proof.checkpoint) if intent["tasks"] else {}
    except BaseException:
        # An error, an interrupt or a closed session must not leave the consumer off or an
        # encoder billing.
        restore(ctx, transport, intent, proof.save, quiet=True)
        capacity.stop_ours(ctx, intent.get("tasks", []), "dc2 evidence: isolation step aborted")
        raise
    after = mapping_state(ctx, transport, identity)
    left = len(workflow.live_tasks(ctx))
    waiting = outage["status"] in WAITING
    held = outage["depth_max"] >= 1 or outage["outbox_pending_seen"]
    to_done = round(ctx.wall() - intent["reenabled_wall"], 1)
    public = {
        "finalize_status": row.get("finalize_status"),
        "mapping_before": intent.get("mapping_before"), "mapping_during": intent["mapping_during"],
        "mapping_after": after, "mapping_restore": intent["restore"],
        "outage_seconds": round(intent["reenabled_wall"] - intent["disabled_wall"], 1),
        "asset_visible_by_id": outage["visible_by_id"], "asset_in_list": outage["in_list"],
        "status_during_outage": outage["status"],
        "submission_status_during_outage": outage["submission_status"],
        "processing_acknowledged_during_outage": outage["progressed"],
        "commands_queue_depth_max": outage["depth_max"],
        "outbox_pending_seen": outage["outbox_pending_seen"],
        "command_held_in": ("both" if outage["depth_max"] >= 1 and outage["outbox_pending_seen"]
                            else "queue" if outage["depth_max"] >= 1
                            else "outbox" if outage["outbox_pending_seen"] else "nowhere"),
        "held_seconds": outage["held_seconds"], "consumer_catch_up_seconds": catch_up,
        "job_status": final["status"] if final else None, "gate_seconds": gate,
        "reenable_to_done_seconds": to_done, "within_gate": bool(
            final and final["status"] == "done" and to_done <= gate + POLL_SECONDS),
        "encoders_started": len(intent.get("tasks", [])), "encoders_left_running": left,
        "encoder_billed_seconds": [tasks.summary(t)["billed_seconds"] for t in stopped.values()],
        "poll_interval_seconds": POLL_SECONDS,
        "scope_note": "Processing is down means its ProcessingCommands consumer is off; its API "
                      "stays up.",
    }
    ok = (str(public["finalize_status"]).startswith("2") and outage["visible_by_id"]
          and outage["in_list"] and waiting and not outage["progressed"] and held
          and after == "Enabled" and public["within_gate"] and left == 0)
    return {"status": PASS if ok else FAIL, "public": public,
            "private": {"job_id": intent["job_id"], "tasks": intent.get("tasks", [])}}


def run(ctx, *, fixture, job_timeout=900, minutes=60, hold=HOLD_SECONDS):
    proof = ctx.proof(ISSUE, REQUIRED)
    proof.step(STEP, lambda i: processing_down(
        ctx, proof, fixture, gate=job_timeout, minutes=minutes, hold=hold), session="open")
    return proof
