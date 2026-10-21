# V2 experiment: bounded short encodes on Lambda (#93)

Status: **implemented locally, cloud evidence NOT_RUN, merge decision PENDING.** Nothing here
has touched AWS. The tests prove the admission rule, the routing, the fencing and the recovery
paths against fakes and against real PostgreSQL plus Moto and FFmpeg. They do not prove Lambda
cold-start time, the real cost of a short encode, IAM evaluation, or how the event source
mapping behaves under SQS. Those are what the measurement plan below is for.

V1 is the default and the baseline: a stack built without `LambdaShortEncodes=true` contains
none of this, every dispatcher keeps sending to the one `ProcessingWork` queue, and every
encode runs on a finite Fargate task exactly as before. Turning the flag back off (and
redeploying) is the whole revert.

Experiment owner decision (see #80): the epic's "after the `project2-v1` tag" gate is
overridden for this work, as it was for #68. It is off by default and not on the V1 critical
path. **Keep it only if the measured benefit holds** (rule below); otherwise do not merge the
flag into a release.

## Admission rule

A source is *short* when it is at or under **all three** bounds (inclusive). The constants are
in `processing/short_lane.py`; the template, this document and the tests are checked against
them.

| Bound | Value | Why |
|---|---|---|
| Source duration | 60 s | Encode time scales with seconds of video; the primary plus the HLS ladder of 60 s of 1080p was expected well under two minutes on about 2 vCPU, and is about 15 % longer on the 1.7 vCPU the Lambda has (see Memory). The only measured datum when this was written was a local 24 s fixture, so the margin is wide on purpose. |
| Source size | 64 MiB | A cheap pre-filter and the only bound known at dispatch. 8.9 Mbit/s over a full 60 s covers an ordinary 1080p phone clip, and keeps the worst `/tmp` footprint (source plus outputs, bounded at 5x the source, 320 MiB) well inside 2 GiB. |
| Source height | 1080 px | Bounds the ladder and the per-second decode cost. |
| Full-pipeline deadline | 720 s | The pipeline (claim, download, probe, encode, upload, commit) must end inside `900 s - 180 s` of headroom. Headroom covers killing the FFmpeg process group, one fenced failure write, temp removal and a database reconnect. 720 s is also about 6x the expected encode time. |
| Lambda timeout | 900 s | Service maximum. |
| Memory | 3008 MB | About 1.7 vCPU (1769 MB is one vCPU). The design chose 3584 MB (about 2 vCPU, the same compute as the 2 vCPU Fargate task), but this account refuses more than 3008 MB (CloudFormation on `dc2-live`, 21 October: "`MemorySize` ... must have value less than or equal to 3008", CD run 39596145564, rolled back); more needs a support request. The comparison with Fargate is therefore at 85 % of its CPU, so a Lambda encode is expected to run about 15 % longer, and the cost per second falls with the memory (GB-seconds). The 720 s pipeline deadline is still about 6x the expected encode time. |
| Ephemeral storage | 2048 MB | See the size bound. 512 MB is included in the function price; 1.5 GB is billed. |

Everything else runs on Fargate: longer, larger or taller sources, a job whose Lambda attempt
failed, and every job when the flag is off.

### Two stages, because the facts arrive at different times

1. **Dispatch** (`short_lane.work_lane`, called from `messaging.emit_state` and from the repair
   path `recovery_v1.repair_work`): only the accepted source descriptor is known, which is its
   size. A source over the size bound goes to the standard `ProcessingWork` queue. Duration
   and height are not known: Media does not probe, so the first probe is the executor's.
2. **Executor** (`short_lane.check_probe`, passed to the shared pipeline as `admit`): after
   the fenced claim, download and probe, a source over the duration or height bound raises
   `NotAdmitted`. The worker loop hands the attempt back with
   `messaging.redirect_to_long_lane`, which is the same fenced transition a retry uses: the
   old attempt becomes abandoned with a cleanup intent, a successor attempt (number + 1) is
   queued on the standard lane, and the job returns to `queued`. A probe that cannot be parsed
   is not an admission failure; it follows the ordinary failure path.

Routing is a separate queue, `ProcessingShortWork`, not a direct invoke. This was chosen
because a direct invoke would need its own redelivery, retry and dead-letter handling and
would not use the SQS redelivery that the existing repair relies on. With a queue, the
message is the same work message the Fargate worker consumes, so **attempt fencing is
unchanged**: the executor decodes it with the same `decode_work` and claims with the same SQL.
Any dispatcher whose short queue URL is missing falls back to the standard lane
(`delivery.sqs.FALLBACK_LANE`), so a half-configured stack degrades to V1 rather than losing
work.

### Sticky fallback, with no migration

Whether an attempt ran on Lambda is read from `attempt_tasks`: the Lambda executor binds its
attempt under the name `lambda-<request id>`, and the Fargate worker never uses that prefix.
`work_lane` sends a job to the standard lane when any of its attempts has a `lambda-` binding.
So a job that crashed or timed out on Lambda, or was redirected, is retried on Fargate and
cannot ping-pong. A plain, non-Lambda job that the operator retries returns to the short lane
if it is still admitted. No schema change is needed.

## The executor

`processing.short_encoder.invoke` is the Lambda handler (`processing.handlers.short_encoder_handler`).
It reuses `processing.worker.sqs.execute_message` and the pure engine in `media_engine`, so
the claim, heartbeat, lease token, `lock_pair`/`live` fencing and the single fenced commit are
the same code the Fargate worker runs.

* **One record per invocation** (`BatchSize` 1). Any extra records, a malformed body, or a body
  that is not a `work` message are returned in `batchItemFailures` for SQS to redrive.
* **Budget**: `min(remaining time - 180 s, 720 s)`. Under 60 s of budget the executor claims
  nothing and returns the message. The attempt's durable `attempt_timeout_seconds` is bound to
  the same figure, so the stored deadline never outlives the invocation.
* **Outcomes**: `finished`, `stale` and `redirected` are acknowledged. `malformed`, `no_time`,
  `skipped` (SQL cannot prove the attempt dead, so the message stays) and `lost` (the fenced
  commit was refused) are not. `AttemptDeadline` commits nothing: recovery owns timeouts.
* **Log line**: one `dc2.short_encode {...}` JSON line per invocation with ids, outcome, cold
  flag, seconds and source bytes. No URLs, tokens, hashes or keys. The cold flag is a module
  counter, so it marks the first invocation in an execution environment.
* **Credentials** use a `lambda` provider in `processing.storage_credentials`, identical to
  Media's (the function's own role, no assumed role).

### Interruption and no double commit

* **Timeout or crash mid-encode.** The invocation stops writing, its lease stops being renewed,
  and SQS redelivers after the queue visibility timeout (960 s, above the function timeout, as
  SQS requires). The existing `recover_expired`/`interrupt` and repair path ends the dead
  attempt and queues a successor; because the dead attempt had a `lambda-` binding the
  successor goes to **Fargate**. A late invocation that is somehow still running holds a stale
  lease token, so its `finish` is refused by the same fence that protects Fargate. Its
  uploads are under the old attempt id and are removed by the existing cleanup-intent rescans.
* **Redelivery after success** finds the attempt no longer `queued`, claims nothing, and the
  message is deleted as stale.
* **Two invocations racing** on one message: only one wins the claim.
* The tests exercise each of these against real PostgreSQL
  (`tests/v1/test_short_encoder_sql.py`), including "crash mid-encode, recovery, cleanup,
  zombie finish refused, Fargate retry, exactly one commit".

## Concurrency arithmetic (written for an account limit of 10, nothing reservable)

**Update, 21 October 2026:** the account's Lambda concurrency limit is now **1000** (read with
`lambda get-account-settings`; 1000 unreserved), so the squeeze described here no longer applies
and a reservation is possible. The decision was not to change anything for the live enablement:
the mapping still caps the encoder at its minimum of 2 and nothing is reserved. The pinned
arithmetic and `ACCOUNT_CONCURRENCY = 10` in `processing/short_lane.py` are the design's original
worst case, kept as written.

New AWS accounts here have a Lambda concurrency limit of **10**, and at that size no
concurrency can be reserved (AWS keeps 10 unreserved). So the encoder cannot be given a
guaranteed slot. It can only be capped, by the event source mapping's
`ScalingConfig.MaximumConcurrency`, whose minimum is **2**.

Background consumers that can run at once (from the template, pinned by
`test_the_background_concurrency_arithmetic_is_pinned_against_the_account_limit`):

| State | Background slots | Left for API, authorizer, hints |
|---|---|---|
| V1 | 6 = ProcessingCommands mapping 2 + MediaResults mapping 2 + the 2 repair rules (1 each) | 4 |
| V1 + unattended launcher (#68) | 7 | 3 |
| V1 + short encoder | 8 = 6 + 2 | 2 |
| V1 + launcher + short encoder (worst case) | **9** | **1** |

The cost of the experiment is therefore explicit: with both opt-ins on, one Lambda execution
slot remains for the API, the authorizer and the two event hints. That is enough for the API to
always run at least once, and a burst beyond it is throttled and retried, not lost; but it is a
real reduction in headroom. This is why `MaximumConcurrency` is set at the minimum and why no
reserved concurrency is declared.

Combined encoder cap: Fargate keeps its cap of **3** (operator batches and the launcher, both
unchanged) and Lambda adds **2**, so up to **5 encodes** can be in flight when both executors
are busy. This is a deliberate decision: the Fargate cap of three workers is a cost and
Aurora-connection limit, and five encoders hold at most 15 connections (pool_size 2 plus one
overflow each) against a cluster that scales 0 to 2 ACU. The alternative, lowering Fargate
to 1 while Lambda runs, was rejected because it would make the baseline arm depend on the
experiment. The cap of 5 is pinned in code (`COMBINED_ENCODER_CAP`) and by a test; raise it
only with new arithmetic.

## How to enable

1. Build and push the **worker** image. It now also carries the Lambda runtime interface
   client (`awslambdaric`) and precompiled bytecode; its Fargate entrypoint is unchanged and
   the template function overrides the entrypoint, so there is no fourth image or repository.
2. Set `lambda_short_encodes: true` in the deploy config (CloudFormation parameter
   `LambdaShortEncodes`, default `false`, effective only together with the applications
   deploy). This creates the short queue and DLQ, the function and alias, the mapping (created
   **closed**), the producer grants, and sets `PROCESSING_SHORT_LANE=true` plus the queue URL on
   the four dispatching functions.
   * **Persistent environment (`dc2-live`).** CD renders its parameters from `Settings` in
     `scripts/aws/v1/deploy.py`, not from a file in the state bucket, so the switch is the module
     constant `PERSISTENT_LAMBDA_SHORT_ENCODES` (enabled by #296). Every CD path reads it: the
     review, the deploy and the stack update that adopts a release. The mapping is created
     **enabled** (`AlwaysOpen`). Reverting is that constant set to `False`; the next CD deploy
     removes the lane and the dispatchers fall back to Fargate.
   * **Per-run stack.** Pass `--lambda-short-encodes` to `scripts.aws.v1.deploy deploy`
     (refused together with `--environment`).
3. `session open` enables the mapping with the others and `session close` disables it (on the
   always-on environment the mapping is already enabled and `session close` is the kill switch).
   It joins the close-proof quiescence check. It is **not** part of a release promotion
   (`owner_functions` excludes it): it runs the worker image, which a Processing release does not
   promote. On the persistent environment the stack update that adopts a release moves it (see
   the next section).
4. Disable: set the parameter back to `false` (on `dc2-live`, the constant) and redeploy. Let the short queue drain first (its DLQ and queue depth are reported by the harness); the queue and function are deleted with the stack resources, and dispatchers fall back to the standard lane as soon as the URL is gone.

## The always-on environment (AD-27) and the lane

This document was written for per-run stacks and a booked session. The persistent environment
`dc2-live` (AD-27) differs in five ways that matter here. Each was read from the code and, where
a real PostgreSQL case exists, run; the live results are under "Results on dc2-live".

* **Launcher wake.** `launcher_trigger.WakeOnWork` invokes the launcher only after a send to
  `processing-work`. A short-lane send goes to `processing-work-short` and wakes nothing. The
  launcher's demand is `min(queued attempts in SQL, visible messages in the standard queue)`, so a
  short job that sits in the short queue adds to the SQL side and not the queue side: no Fargate
  task is started for it. A redirected job (over the duration or height bound) gets a successor
  attempt whose outbox row is published to the standard queue by the minute repair tick, which is
  a work publisher and does wake the launcher.
* **`repair_work` and the lane.** A work message is one outbox row per `(attempt, state version)`,
  and the row carries its queue. Repair re-arms an existing row, so a re-send goes to the lane the
  attempt was dispatched to; a missing row is staged through `short_lane.work_lane`, which applies
  the size bound and the sticky Fargate fallback (any earlier `lambda-` binding sends the job to
  the standard lane). A message left in the short queue because the executor could not claim is
  re-sent by the same repair pass, about a minute later, not after the 960 s visibility timeout.
* **Activity markers and Aurora.** Idle ticks skip SQL while the SSM `quiet` marker is valid, and
  the markers are written by the writers (the command consumer, the Media and Processing APIs) and
  by the repair pass. The short encoder is not a writer and does not need to be: it only acts on
  an attempt that is already `queued` or `processing`, for which `next_due` is 0 and no quiet value
  is in force. Its heartbeat and its commit keep Aurora awake while it works; when the job is done
  the next repair pass finds nothing due, writes `quiet`, and the cluster can pause.
* **Per-owner release.** The short encoder is not in `owner_functions`, so a Processing release
  does not move it. It follows the worker image through the stack: its code and the description of
  its published version name `WorkerImageUri`, which `adopt-release` rewrites and the following
  `deploy --stop-after applications` renders, so the alias moves exactly when the worker image
  does (pinned by `tests/aws/v1/test_persistent_environment.py`). Its mapping is in the Processing
  owner's consumers, so a release's online invariant requires it enabled and the kill switch
  (`session close`) disables it. Between a release and its adoption the function runs the previous
  worker image, like the launcher's task definition; a release is additive, so that is safe.
* **What the CD smoke now exercises.** The smoke's 3 s clip is short, so on `dc2-live` it takes
  the Lambda lane. The Fargate worker path is exercised by sources over the bounds, which is also
  how the measurement times Fargate on the same stack.

## Measurement plan (not yet run)

The two arms are different stack states, because with the flag on every admitted job goes to
Lambda. Run them in order with one fixture and one run id:

```text
# 1. A stack WITHOUT the lane. The harness refuses a stack that has it.
python -m scripts.aws.v1.evidence short-encode --arm fargate --fixture short.mp4 \
    --fixture-seconds 24 --jobs 5 --profile ... --region ... --account ... --run-id R

# 2. Redeploy with lambda_short_encodes: true, session open (enables the mapping).
python -m scripts.aws.v1.evidence short-encode --arm lambda  --fixture short.mp4 \
    --fixture-seconds 24 --jobs 5 --idle-minutes 20 ... --run-id R

# 3. Apply the keep rule to the two stored receipts.
python -m scripts.aws.v1.evidence short-encode --arm compare ... --run-id R
```

`--dry-run` runs the same harness against the simulated account (receipts are marked
SIMULATED and can never be summarized). `evidence rehearse` includes it.

* **Fixture**: one fixed short mp4 (with an audio track; the HLS ladder maps `a:0`), at most
  60 s and 64 MiB, identical for both arms.
* **Per executor**: `N` jobs (default 5), 2 to 20. Job 1 is *cold*, the rest *warm*. A Fargate
  cold job is one whose task started after the submit; warm is a task already RUNNING. A Lambda
  cold job follows an idle wait (default 20 minutes), and is confirmed by a REPORT line with an
  `Init Duration` and the executor's cold flag; if no cold start is observed the rule fails.
* **Recorded per job**: submit-to-done latency (cold and warm medians kept apart), success,
  retries (a second invocation of the same job counts), status regressions, S3 correctness
  (one attempt id in the outputs), and queue and DLQ leftovers.
* **Cost per success**: failures stay in the cost and out of the denominator, so a flaky arm
  looks worse.
  * Lambda: `billed ms x memory GB x GB-second price`, plus
    `billed seconds x (ephemeral - 0.5 GB) x storage price`, plus the request price, plus the
    init duration, from the REPORT line (container image init is billed). Prices come from
    `docs/execution/aws/v1/prices/AWSLambda-prices.json`.
  * Fargate: the task's running seconds, 60 s minimum, at the vCPU, GB and public IPv4 hourly
    rates from `docs/execution/aws/cost-worksheet.json` (about $0.128/hour for 2 vCPU and
    4 GiB).
  * Shared services (API Gateway, SQS, Aurora, S3, logs) are identical or negligible between
    arms and are excluded; the receipt says so.
* **Keep rule** (all must hold, from a live run, with `merge_decision` left `pending`):
  no failures on either arm; a Lambda cold start observed; no retries or redirects on the
  Lambda arm; Lambda cold median lower than Fargate cold median; Lambda warm median lower
  than Fargate warm median; Lambda cost per success not higher than Fargate's.

The expected result is that Lambda wins on cold latency (no 30 to 60 s task start) and loses
on neither cost nor reliability for a short clip. That is a hypothesis; if a live run shows
otherwise, do not merge the flag into a release.

## Limits and risks

* Only the first record of a batch is encoded (`BatchSize` 1 by design). Extra records are
  returned to the queue.
* A source that is short by size but over the duration or height bound pays one wasted
  download and probe on Lambda before it is redirected. The redirect is cheap, but the wasted
  time is counted in that job's latency.
* The invocation budget has no preemption except the deadline: a hung FFmpeg is killed by the
  supervisor at the deadline, and the Lambda timeout is the backstop.
* The Lambda image runs amd64 only (`x86_64`). Local image builds under emulation are slow.
* `scripts/aws/v1/deploy.py` has one small change for this experiment: `logs filter-log-events`
  is added to the read-only allowlist so the harness can read the encoder's REPORT lines. No
  other deploy, bootstrap or simulation file for the deploy path is touched.
* Cloud evidence is NOT_RUN; every number in the receipts from `--dry-run` or `rehearse` is
  simulated.
