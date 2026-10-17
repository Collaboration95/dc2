# V2 experiment: opt-in unattended encoder starts (#68)

Status: **implemented locally, cloud evidence NOT_RUN.** Nothing here has touched AWS. The
fakes in the tests stand in for ECS and SQS, so they prove the launcher's decisions and its SQL
reservations, not ECS idempotency, IAM evaluation, dual-stack endpoint reachability or cost.
V1 stays the default and the baseline: a stack built without `UnattendedLaunch=true` contains
none of this, and the operator's serialized finite batches (`session batch`) are unchanged.

The experiment was started in parallel with the V1 cloud proof at the user's direction, which
overrides the epic's "after the `project2-v1` tag" gating (#80). It is still not on the V1
critical path: no V1 issue depends on it and it can be reverted by redeploying without the flag.

## What it does

A Lambda (`processing.handlers.launcher_handler`) runs on an EventBridge `rate(1 minute)` rule
while a session is open **and** the operator opted in. Each tick it starts finite Fargate
encoders (the same task definition, command and container the operator batch uses) only when
there is work for them, and never more than three in total.

```text
tick -> SQL: control row, open reservations, queued attempts   (no ECS/SQS call if idle)
     -> ECS: ListTasks (RUNNING + STOPPED) + DescribeTasks      (every worker, by anyone)
     -> SQS: ApproximateNumberOfMessages on the work queue
     -> SQL txn A (control row FOR UPDATE): reconcile, decide, INSERT reservations, COMMIT
     -> per reservation, SQL txn B (control row FOR SHARE): RunTask, record the result
```

### Decisions

| Question | Rule |
|---|---|
| Is there backlog? | `demand = min(queued attempts in SQL, visible SQS messages)`. SQL is the durable truth; the queue count says a worker could actually receive something. An unreadable queue means no demand. |
| How many to start? | `min(demand - unclaimed workers, 3 - occupied)`. A finite worker takes one attempt, so a worker that already claimed one is not capacity; one that has not (including a slot still starting) is. |
| What is occupied? | Every worker-family task ECS reports that is not STOPPED (started by anyone, STOPPING included) **plus** every reservation no live task explains yet. Ambiguous launches therefore keep their slot. |
| Idle respawn | A worker that stops without ever claiming an attempt pauses launches for 120 s; three in a row stop them until the next explicit enable. The attempt-to-task binding (`attempt_tasks`) is how "claimed" is known. |
| Session end | `enable` requires a future end. Launches stop `min_useful_seconds` (120) before it, and every worker's `--deadline-epoch` is `min(now + lifetime, session end)`. A forgotten session cannot launch forever. |

### Reservations and tokens

`launch_reservations` (migration `processing_0007`, additive) holds one row per slot:
`token` (the ECS `clientToken`, 32 hex), `started_by` (`v1-u` + token, 36 characters, also the
worker's `--name` and so its `attempt_tasks` binding), the full RunTask payload, a status and
timestamps. The row is committed **before** RunTask is called, so the payload a replay sends is
byte-identical to the first.

States: `reserved` (slot taken, RunTask may or may not have landed: the ambiguous state),
`launched`, `stopped`, `released` (proven never started).

* A lost response leaves the row `reserved`. The next tick finds the task through its
  `startedBy`, or, once `replay_after_seconds` (15 s, longer than any RunTask the adapter
  allows) has passed and there is still demand, replays the same token and payload.
* A killed Lambda leaves a `reserved` row with no `sent_at` (the send transaction rolled back).
  The next tick treats it the same way.
* A row ECS never confirms is released after `release_after_seconds` (120 s). If the task turns
  up later it is still counted through the live ECS inventory, so the cap holds either way.
* A definite refusal (HTTP 4xx other than `ConflictException`, or no task plus `failures`) is
  `released` immediately and ends that tick's sends. Timeouts and 5xx stay ambiguous.

### Concurrency and the close interlock

`launcher_control` is a single row. Reserving takes it `FOR UPDATE`, so concurrent ticks
queue and each sees the previous tick's reservations. Every RunTask is made while holding it
`FOR SHARE`. `disable` takes it `FOR UPDATE`, so it **waits for any in-flight send and returns
only when none can start**; a send that begins afterwards re-reads the flag, releases its own
slot and never calls ECS. Hence "no launch after close begins".

`session close` runs, before anything else: disable the rule, confirm it, disable the SQL flag.
Only then does it quiesce intake and run the existing drain and outcome checks, followed by a
`settle` step (reconcile without launching) that must report zero ambiguous reservations
before the worker inventory check. If any launcher step fails, close fails as partial and skips
the drain; every other wake source is still closed.

## Infrastructure

Everything is created only when the stack parameter `UnattendedLaunch` is `true` (default
`false`, together with `DeployApplications`): condition `Unattended`.

* `ProcessingLauncher` Lambda (512 MB, timeout 30 s, unreserved), alias `live`, log group.
* `ProcessingLauncherRule`: `rate(1 minute)`, **`State: DISABLED`**, no retries. The timeout is
  below the period, so a tick never overlaps itself.
* Role, least privilege: `ecs:RunTask` on `task-definition/<env>-worker:*` with
  `ecs:cluster` = this cluster; `iam:PassRole` on the worker's task and execution role only,
  `iam:PassedToService=ecs-tasks.amazonaws.com`; `ecs:ListTasks` and `ecs:DescribeTasks`
  conditioned on this cluster; `sqs:GetQueueAttributes` on the work queue; its own domain's
  runtime DSN parameter, logs and VPC ENI actions like every handler. No S3, no queue
  send/receive, no `StopTask`.
* Outputs `ProcessingLauncher{FunctionName,AliasArn,RuleName}`; the operator config adds the
  function to Processing's releases and its rule to Processing's quiescence set, but never to
  the schedules `session open` enables.

Lambda concurrency: the account limit is 10 and nothing is reservable. Background sources are
two SQS consumers at `MaximumConcurrency` 2, plus scheduled functions that run at most once at a
time. The launcher raises the scheduled set from 2 to 3, so the background footprint goes from 6
to 7 of 10, leaving 3 for the API and event hints (pinned by
`test_concurrency_accounting_includes_the_launcher_and_stays_inside_the_account_limit`).

## Using it during a session

1. Deploy with `"unattended_launch": true` in the nonsecret V1 config (rendered as
   `UnattendedLaunch=true`). Run the Processing migration task first: `processing_0007` only
   adds two tables. Without the flag, none of the below applies.
2. Open a normal session but opt in, with a bounded horizon:

   ```sh
   python -m scripts.aws.v1.session open --config <operator.json> --profile <p> \
       --region ap-southeast-1 --account <id> --unattended --minutes 90
   ```

   Open sets the SQL flag (with the session end) and then enables the rule. A plain `open`
   leaves the launcher off even on a stack that has it.
3. While unattended, `session batch` is refused (two launchers sharing the cap would race
   their inventory reads). `session status` reports the launcher rule and flags drift.
4. `session close` as usual. It disables the launcher first.

Operator steps do not change if the launcher is absent: `session close` only touches it when the
stack outputs name it.

## Cost implications

* **Fargate** dominates and is the only line that can grow: the V1 model prices a worker at
  about 0.128 USD per hour including IPv4 (`cost-inputs.json`). The launcher adds no capacity
  beyond the existing cap of three, and each task is finite (`WorkerLifetimeSeconds`, default
  1800 s). A wasted start (a worker that finds nothing) lasts roughly its two empty polls plus
  start-up, around a minute or two, about 0.002-0.004 USD; the idle breaker stops after three.
  A start that tracks real backlog replaces the operator-batch latency, not its cost.
* **Lambda**: one 512 MB invocation per minute of an open session is negligible (hundreds per
  session, well under a second each when idle).
* **Aurora**: the tick reads SQL every minute, so the database cannot auto-pause while the rule
  is on. The existing repair rule already does exactly that for the whole open session, so the
  awake time is unchanged. An enabled rule after the session ended would keep it awake: the
  launcher self-limits by session end, but only `session close` disables the rule, so close.
* No NAT, endpoint or other always-on resource is added.

## Not solved here (risks to measure, not hidden)

* **IAM conditions are unverified.** `ecs:cluster` on `ListTasks` and `DescribeTasks`, and the
  task ARN shape for `DescribeTasks`, follow the documented condition keys but have not been
  evaluated. Check with `aws iam simulate-principal-policy` before the first live tick.
* **ECS `clientToken` idempotency** is assumed on RunTask (the operator replay relies on it
  too). The design holds without it (live inventory still enforces the cap), but a replay of a
  launch that landed unseen could cost one extra task. The `startedBy` lookup comes first.
* **Dual-stack reachability.** The launcher runs in the private subnets with IPv6 egress only
  and `AWS_USE_DUALSTACK_ENDPOINT=true`. Whether the ECS and SQS API endpoints answer there is
  the same open question as the rest of the network plan (#63).
* `ApproximateNumberOfMessages` can lag by up to a minute: a worker may start one tick late.
* Operator-started tasks count against the cap, but a batch started in the same instant as a
  tick is not serialized with it; that is why `batch` is refused while unattended.
* Close can fail as partial while a launched worker is still idle-polling (existing
  `inventory` behaviour); retry after its two empty polls.

## Verification

Offline (no AWS, no services): `make lint`, `make lint-cfn`, `make test`, `make test-v1`,
`make test-aws`, `python -m scripts.dev.checks coverage-fast`. The template tests pin the
disabled default, the conditions, the role, and the concurrency footprint
(`tests/aws/v1/test_unattended_launch.py`).

Real PostgreSQL with fake ECS/SQS (`tests/v1/test_launcher_sql.py`, run by
`make verify-v1 FLOW=c`, or directly with `V1_TEST_PROCESSING_DSN`): no backlog, no launch (and no
ECS call); a backlog of ten starts three; concurrent ticks (released together by a barrier, and
shown to fail when the control-row lock is removed) never exceed the cap, even when every response
is lost; a lost response resolves by `startedBy` or replays the identical token and payload
without a second task; a killed Lambda resumes its reserved slots; idle workers are not added to
and not respawned; foreign tasks count against the cap; a disable waits for an in-flight send and
nothing launches after it; settle clears ambiguity.

## Cloud measurement plan (NOT_RUN)

Run only inside an authorized, MFA-backed session (#45, #63-#67), after V1 evidence is
captured, and compare each result with the serialized operator-batch baseline from the same
session:

1. **Correctness under real ECS**: with one queued attempt, observe exactly one RunTask, the
   `startedBy` correlation, the `attempt_tasks` binding and a clean `STOPPED` settle; then force
   a lost response (short client timeout) and confirm the token replay yields one task.
   Record the `simulate-principal-policy` result and whether ECS/SQS answer over the dual-stack
   path.
2. **Latency and cap**: submit 1, 3 and 10 uploads; record queue-to-claim time versus the
   operator-batch path and the peak concurrent worker count (must never exceed 3); repeat with
   two concurrent session opens/ticks if the account allows.
3. **Cost and idle behaviour**: record Fargate task-seconds, tasks that exited without a claim,
   Lambda invocations and Aurora awake minutes for an idle one-hour session with the launcher on
   versus off; confirm that close leaves no task, enabled rule or ambiguous reservation.

Receipts keep source/version/limits/failures and contain no DSNs, cookies or signed URLs. Until
they exist the status of this experiment is `cloud_acceptance: NOT_RUN` and the epic stays open.
