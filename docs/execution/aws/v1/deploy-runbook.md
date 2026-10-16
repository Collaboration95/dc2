# V1 deploy and teardown runbook

Status: **written and verified offline only.** The pipeline in
[`scripts/aws/v1/deploy.py`](../../../../scripts/aws/v1/deploy.py) has never been run against
AWS. Nothing here authorizes AWS operations, spend or deletion; the operator named in
[`cloud-operator-20261015.md`](cloud-operator-20261015.md) decides when to run it. Cloud issues
#63-#67 stay open and Blocked until a real run produces real receipts.

One ordered, resumable, journaled path takes the account from nothing to a smoke-tested,
closed V1 and back to nothing. Every step journals itself, supports `--dry-run`, and tags what
it creates `deploy-project=dc2-v1` and `owner-run=<run id>` (the keys avoid `Project`, which the
template already uses: IAM compares tag keys case-insensitively and would reject the duplicate).

## Before the first real run

The operator must decide or supply all of these. None has a default.

| Item | Why it blocks |
|---|---|
| An MFA session in profile `dc2-project2-mfa` | `FlickPondRequireMFA` denies when `aws:MultiFactorAuthPresent` is `false`. Direct calls with the long-term key pass, but calls CloudFormation makes on the caller's behalf carry no MFA and are denied. So every deploy, session and evidence command uses the session profile that `make aws-mfa-session CODE=<6 digits>` writes (the helper asks `sts get-session-token` for 129600 s, the 36 h maximum, and prints the expiry). Preflight blocks a long-term key and says to run the helper. The pipeline will not bypass or edit the policy. |
| `--run-id` (2-16 lowercase letters/digits) | Namespace `dc2-v1-<run id>` must fit CloudFormation's 24-character `EnvironmentId`. A new id per attempt; a failed stack leaves `ROLLBACK_COMPLETE` that blocks its name. |
| `--state-dir` (private, outside the repo) | Journal, stack outputs, smoke credentials, the transient database role passwords, receipt. Mode 0700, files 0600. Back it up: it is the only record of what this run owns. |
| `--images` | The `--out` evidence file of `deploy/v1/build_and_verify.py` (accepted only if `LOCAL_ARTIFACT_PASS`; each image must still have the verified config id), or a hand-written `images.json`. See below. |
| `--seed-email` | Address for the smoke account. Must pass the Media API's email validation (not `.invalid`). |
| How `session close` proves a drain | One of `--sql-config` (needs a station inside the VPC), `--counts-file`, or `--assume-empty-counts` (the operator attests no worker ever ran, true for a first deploy). Without one the pipeline refuses to open the window. |
| Forecast | Cost Explorer may have no history for a young account; then pass `--forecast-usd` (the operator's own figure). Unavailable and unsupplied fails closed. |
| `--budget-usd` | Default 30, matching `flickpond-monthly`. Preflight blocks if the budget does not exist, is not USD, or is below this flag. |
| Frontend upload | Done by the `frontend` step after `applications`: `frontend/` is content-hashed, uploaded to the frontend bucket and CloudFront is invalidated. Unrun against AWS. |
| Operator role | The public register endpoint creates role `user` only (see Seed). |

Tools: AWS CLI v2, Docker (the `docker` CLI must reach the daemon that holds the images;
`DOCKER_HOST`/`DOCKER_CONTEXT` pass through, but the registry login itself uses a throwaway
`DOCKER_CONFIG`), Python from the repo `.venv`. Ambient `AWS_*` credential, profile and endpoint
variables are refused; the profile `default` is refused; the region must be `ap-southeast-1`.

Hand-written `images.json` (the build script's evidence file is accepted as-is instead; it says
`promotion_eligible: false` and `scan: NOT_RUN`, which a first deploy does not need but a promotion
would):

```json
{"media": "dc2-v1-media:sha-abc", "processing": "dc2-v1-processing:sha-abc",
 "worker": {"source": "dc2-v1-worker:sha-abc", "expected_digest": "sha256:<64 hex>"}}
```

`expected_digest` is optional and, when given, must equal the registry's digest after push. The
local image id is journaled before the push; a resume with a rebuilt image is refused, because
ECR tags are immutable and would otherwise silently deploy the older push.

## Commands

All take `--profile dc2-project2 --region ap-southeast-1 --account 866865534361` explicitly.

```sh
# 1. Rehearse everything offline (simulated account, throwaway journal, prints the exact commands)
python -m scripts.aws.v1.deploy rehearse <scope> --run-id r1016a
python -m scripts.aws.v1.deploy deploy   <scope> --run-id r1016a --dry-run [--plan-detail all]

# 2. Real deploy: review-then-execute ladder (exit 3 = change set described, awaiting --execute)
python -m scripts.aws.v1.deploy deploy <scope> --run-id r1016a --state-dir D --images images.json \
    --seed-email ops@example.com --assume-empty-counts --forecast-usd 0 --stop-after bootstrap-stack
python -m scripts.aws.v1.deploy deploy <scope> ... --execute --stop-after bootstrap-stack
python -m scripts.aws.v1.deploy deploy <scope> ... --stop-after foundation        # shows the change set
python -m scripts.aws.v1.deploy deploy <scope> ... --execute                       # the rest

# 3. Inspect
python -m scripts.aws.v1.deploy status <scope> --run-id r1016a --state-dir D

# 4. Teardown (plan first; --execute needs the run id repeated)
python -m scripts.aws.v1.deploy teardown <scope> --run-id r1016a --state-dir D
python -m scripts.aws.v1.deploy teardown <scope> --run-id r1016a --state-dir D --dry-run
python -m scripts.aws.v1.deploy teardown <scope> --run-id r1016a --state-dir D \
    --execute --confirm-run-id r1016a [--skip-final-snapshot]
```

`--dry-run` never reads or writes a real state directory (it uses a temporary one) and never
starts a process; `teardown --dry-run --state-dir D` only *reads* D's journal to rehearse what
that run recorded. A dry run proves ordering and request shape; its identity, quota and budget
answers are simulated, labelled `simulated`, and prove nothing about the account.
Exit codes: 0 done, 1 failed (message names the step, never a payload), 3 awaiting `--execute`.

## Ordered steps

Times are estimates from AWS behaviour, not measurements; replace them with the first real run's
journal timestamps. Costs use the receipt's Singapore rates: Aurora $0.20/ACU-hour, Fargate
$0.05056/vCPU-hour + $0.00553/GiB-hour + $0.005/hour public IPv4. The database is the only
meaningful meter: about $0.10/hour typical (0.5 ACU) and $0.40/hour at its 2 ACU ceiling while
awake; a 0.25-vCPU/0.5-GiB finite task is about $0.02/hour.

| # | Step | What it does (AWS calls) | Time | Cost while running |
|---|---|---|---|---|
| 1 | `preflight` (always re-run) | STS identity equals `--account`; MFA device; Lambda limit 10 and nothing to reserve; Fargate vCPU quota (blocks < 2, warns < 6); Aurora 16.8 orderable with minimum 0 ACU; budget exists (USD, not below the flag); cost guard; a close-proof is configured; name collisions (stacks, `/dc2/<env>/` parameters and log groups, artifacts bucket incl. a 403); images file shape; records the old `dc2-v1-20261015t1146-bootstrap` as not reused, not touched | 1 min | 0 |
| 2 | `bootstrap-stack` | Creates `<env>-bootstrap` from `deploy/aws/v1-operator-bootstrap.json` (private versioned staging bucket) with the namespace allow-list rewritten to this run. Change set: create, describe, execute only with `--execute` | 1-2 min | 0 |
| 3 | `foundation` | Stages the 82 KB main template in that bucket (inline limit is 51,200 bytes); change set with `DeployApplications=false`: VPC, queues, Aurora cluster+instance, three buckets, CloudFront, **the three ECR repositories**, cluster. Records every physical id | 15-25 min (Aurora instance, CloudFront) | DB starts to bill |
| 4 | `images` | Per owner: confirms linux/amd64, pushes tag `<run>-<owner>` once, reads the registry digest, optional `expected_digest`, reads scan findings, journals `repo@sha256:...` | 5-15 min (upload) | ECR storage ~$0.15/month |
| 5 | `applications` | UPDATE change set: `DeployApplications=true`, three digest-pinned image URIs, `SourceCorsOrigin` = generated frontend URL. Lambda functions, aliases, mappings and rules are created closed; gateway throttle 0/0. Writes `outputs.json` | 5-10 min | + pennies |
| 5b | `frontend` | Builds `frontend/` into `<state-dir>/frontend-dist` (hashed asset names, `index.html` `no-cache`, assets `immutable`), lists the bucket, uploads only changed objects with SSE and tags (`index.html` last), `cloudfront create-invalidation` `/*`, polls until `Completed`, fetches the page through CloudFront | 2-6 min (invalidation) | pennies |
| 6 | `db-bootstrap` | Reads the RDS-managed master secret, generates four distinct 32-character role passwords and keeps them in `<state-dir>/db-bootstrap-passwords.json` (0600, never journaled or printed) until the DSNs are published, writes temporary `/dc2/<env>/bootstrap-input`, runs the finite bootstrap task, **always** deletes the input, writes the four DSN parameters and a stable `jwt_secret` as tagged SecureStrings, then removes the local password file | 3-6 min (Fargate start, Aurora resume) | task ~$0.02/h + DB |
| 7 | `migrations` | `scripts.aws.v1.migration.migrate` for Media then Processing: run-task, poll, exit code 0, schema revision. Target revision is the Alembic head from the repo | 6-10 min | as above |
| 8 | `session-init` | `session init` for a pipeline-owned session journal; refuses unless a close-proof is configured | < 1 min | 0 |
| 9 | `session-window` | `session window`: readiness probes (wakes Aurora), public API only, consumers/rules/workers stay off | 1-3 min | DB awake |
| 10 | `seed` | `POST /api/media/auth/register` through the Gateway; password generated, stored 0600 | < 1 min | 0 |
| 11 | `public-smoke` | `PublicSmoke`: media/processing health, anonymous denial, login cookie flags, jobs, processing batch, one never-finalized reservation | < 1 min | 0 |
| 12 | `session-close` | `session close`: stage throttle to 0/0, drain and outcomes from the close-proof, mappings and rules off. Also runs automatically (and the window is reopened on rerun) when any earlier step fails after the window opened | 1-3 min | then DB pauses after 5 idle minutes |

End to end: roughly 50-80 minutes, about $0.40-$2.00 including the retained month, worst-case
`planned_cost(3 h)` of $1.97 (this is what the cost guard adds to month-to-date and forecast).
Standing cost once closed: about $0.76/month (RDS-managed secret $0.40, ECR $0.15, Aurora storage,
logs) plus anything that wakes the database (maintenance, requests).

### Change sets

`create-change-set` is named for the template+parameter hash, so a rerun reuses it. The review
refuses: any non-`Add` change on an initial stack; any `Remove`; replacement of a stateful type
(RDS, S3, ECR, VPC, subnets, queues, ECS cluster) without `--allow-replacement`. A change set that
was executed before a crash is detected (`EXECUTE_COMPLETE`) and not executed twice. Cost is
re-checked immediately before each execute.

### Bootstrap stack: reuse or not

`dc2-v1-20261015t1146-bootstrap` is `ROLLBACK_COMPLETE` with no resources. It is **not
reusable**: CloudFormation cannot update a rolled-back stack, its template pins the old namespace,
and its `Retain` bucket never existed. The pipeline leaves it alone (teardown receipts list it as
untouched; deleting it is a free, manual, optional cleanup). It creates `<env>-bootstrap` instead.
`--adopt-bootstrap-stack NAME` reuses a *healthy* staging stack with an `ArtifactsBucket` output;
an adopted stack and bucket are never deleted, only the template object versions this run uploaded are (see Teardown).

### Seed: the operator account

The existing approach is the public `POST /api/media/auth/register`. It always creates role
`user` (the authorizer lets `user` and `operator` publish; operator privilege is checked
elsewhere), so the smoke account is a `user`. Promotion to `operator` needs an `UPDATE` by the
Media migrator role inside the private network and is not automated. A `409` is accepted as
"exists" only because the credentials file is this run's own.

## Cost guard

`--budget-usd` (default 30) is compared with
`month-to-date UnblendedCost + forecast + planned_cost(--planned-hours, default 3)`.
Forecast is Cost Explorer's remainder-of-month figure, or `--forecast-usd`; unavailable and
unsupplied refuses. It runs in preflight and again before every change-set execute, and the
numbers are journaled. It is an alert-grade guard on a lagging, estimated source, not a cap.

## Resuming

Each step is `started` / `done` / `failed` / `awaiting-execute` in the journal. A rerun skips done
steps and repeats `preflight`. Launch intent (the ECS client token) is journaled before `run-task`,
a failed bootstrap task is forgotten so a rerun starts a new one (with the same saved passwords), a failed migration is forgotten
the same way while an ambiguous launch keeps its retained intent, and finished owners are not
repeated. A rerun after the bootstrap task finished but before every DSN reached SSM reuses that
task and publishes the saved passwords, so SSM and PostgreSQL agree; if the password file is lost
the recorded task is retired and a fresh bootstrap applies newly generated ones. Retiring means
stopping any unfinished earlier bootstrap task (the recorded one, and any launched under the same
`startedBy` whose ARN was never journaled) and waiting up to 5 minutes for STOPPED; if that cannot
be confirmed the step fails and nothing is relaunched, so a stale task cannot reset the roles after
the new DSNs are published. The task's successful exit code is journaled before any DSN is written,
so a resume never describes the task again (ECS shows stopped tasks for only about an hour). A task
ECS no longer reports and that never gave a verdict is re-checked a few times, retired and
relaunched once with the same saved passwords; a second disappearance fails the step. `status` prints the journal. A second process on the same run is refused by a lock.

## Teardown

Ownership needs **both** the id recorded in this run's journal when its stack created it **and**
the live `deploy-project`/`owner-run` tags. Anything failing either is skipped and listed under
`skipped_not_owned`; pre-existing resources are never candidates. Order, each step journaled:

1. `td-inventory`: tags and presence of everything recorded; writes the ownership map.
2. `td-session-close`: close the front doors before anything is stopped or deleted, through the
   same `session close` code the deploy ends with (stage throttle 0/0, event-source mappings and
   rules disabled, functions quiesced). It uses attested zero attempt counts because the data is
   about to be deleted, so a drain proof gates nothing. A close that failed only its `drain`,
   `outcomes` or `inventory` checks (they cannot pass while an encoder runs) continues to the next
   step; any other failure stops the teardown. Skipped, and journaled as such, when the
   applications were never deployed or the session was never initialised.
3. `td-quiesce`: stop every running task in the project cluster, then wait (up to 15 minutes) until
   `describe-tasks` reports all of them STOPPED and a fresh listing finds none. A task that does
   not stop fails the step and nothing has been emptied.
4. `td-buckets-emptied`: every version and delete marker (the buckets are versioned) and any
   incomplete multipart upload. Only reached once no writer is left. This sweep is not trusted to
   be the last: upload grants issued before the session closed stay valid for 15 minutes.
5. `td-images-deleted`: every image in the owned repositories.
6. `td-database`: remove deletion protection, delete the instance, then the cluster. A final
   snapshot `<env>-final` (tagged) is taken unless `--skip-final-snapshot`. This precedes the stack
   because the retained database holds the VPC's subnets.
7. `td-parameters`: owned SecureStrings under `/dc2/<env>/` (and any leftover local password file).
8. `td-stack`: delete the main stack and wait (CloudFront is the long pole).
9. `td-bootstrap-stack`: delete the staging stack. If it was adopted, delete only the object
   versions this run uploaded: template keys are `templates/<run id>/<sha256>.json`, each put's
   `VersionId` is journaled, and exactly those `(key, version)` pairs are removed, so a second
   run sharing the bucket keeps its identical templates. Objects journaled without a version id
   are kept and listed as `staged_without_version_id_kept`.
10. `td-retained`: delete the `Retain` buckets, repositories and any owned log groups. Each
    bucket is emptied again immediately before its delete, and a `BucketNotEmpty` answer triggers
    another sweep (up to 5 attempts, 10 s apart) before the step fails; a resume repeats the sweep
    instead of skipping it. Chosen over waiting out the 15-minute grant lifetime after the close,
    which would add that wait to every teardown; the re-sweep costs a few list calls and covers
    late Lambda writes as well. A bucket still written to after 5 sweeps is reported, never
    force-deleted.
11. `td-receipt`: observe what is left from the services, plus the tagging API.

Expected 25-45 minutes (CloudFront 10-20, Aurora 5-10, snapshot 2-5), then the meter stops.
`teardown-receipt-<run>.json` (0600) is the "resources remaining" receipt for #67: status
`CLEAN` or `ITEMS_REMAIN`, each remaining item with a reason (by default the final snapshot,
which keeps billing storage until deleted), skipped items, and the untouched legacy stack. It does
not reconcile billing: do that from Cost Explorer after the usage lags in (about a day).

## Evidence each issue gets from each step

`journal` = `deploy-journal.json`; `receipt` = the teardown receipt. None of this is an AWS PASS
until produced by a real run; local fakes are not evidence.

| Step | #63 deploy and boundaries | #64 capacity and recovery | #65 release and rollback | #66 latency | #67 spend and close |
|---|---|---|---|---|---|
| preflight | STS identity, MFA state | Fargate vCPU quota (6), Lambda limit 10 | - | - | budget record, month-to-date, forecast, planned cost |
| bootstrap-stack, foundation | change-set ids, template sha256, change list, resource ids, closed defaults | cluster, network, queues | - | - | per-step journal timestamps |
| images | per-owner digest and scan severity counts (or `PENDING`) | worker image digest for task evidence | the baseline `repo@sha256` set that `release promote --bundle` compares against | - | ECR retained storage |
| applications | Gateway URL, function/alias/mapping/rule names, closed throttle 0/0 | finite worker task definition ARN | first-install `live` aliases (the release adapter deliberately invents no rollback version) | Gateway origin to measure | - |
| db-bootstrap | task exit codes, four roles and databases created, temporary input removed | - | - | - | task start/stop timestamps |
| migrations | Alembic revisions and task exit codes; schema check labelled `task-exit-code-only` or `alembic_version-over-verified-tls` | - | pre-release schema revision | - | task timestamps |
| session-window, seed, public-smoke | Gateway routes, anonymous denial, cookie flags, readiness | - | the same smoke a release repeats | warm path exists; cold wake time is **not** recorded here | window start time |
| session-close | close result, mappings and rules disabled, throttle 0/0 | zero tasks (inventory) | - | - | `database_pause: NOT_OBSERVED` until measured separately |
| teardown | - | - | - | - | `resources_remaining` receipt, final snapshot, untouched legacy stack |

Not produced by this pipeline, still needed: IPv6 and S3-gateway connectivity, verified database
TLS from Lambda, cross-database and DDL denial, queue and spoof denials, direct upload, CORS and
CloudFront cookie round trip (#63); encoder runs and recovery timing (#64); a real promotion
and rollback (#65); the Fargate generator and cold/warm numbers (#66); actual ACU pause and the
invoice reconciliation (#67).

## Cloud proof in order

Status: **every harness here is written and exercised only against a simulated account.** None has
touched AWS; no receipt below exists yet, so #63-#67 stay open. `S` stands for
`--profile dc2-project2-mfa --region ap-southeast-1 --account 866865534361`, `D` for the private
`--state-dir` the deploy used, `R` for its run id. Every harness keeps its receipt at
`D/evidence/evidence-<issue>-R.json` (0600), skips a step that already passed (rerun is safe;
`--only a,b` picks steps), exits 1 only when a step run just now failed, and **refuses to start**
while the session journal says closed (and between polls, also when the Gateway throttle is 0).
A step that cannot be observed is `NOT_RUN`, never `PASS`.

```sh
# 0. MFA session (the only interactive step), then rehearse everything offline
make aws-mfa-session CODE=123456                      # writes profile dc2-project2-mfa, prints expiry
make aws-proof-rehearse                               # every harness vs the simulation; proves nothing
python -m scripts.aws.v1.deploy deploy $S --run-id R --dry-run

# 1. Deploy (the ladder above, `--execute` last); it ends with the session closed
python -m scripts.aws.v1.deploy deploy $S --run-id R --state-dir D --images images.json \
    --seed-email ops@example.com --assume-empty-counts --forecast-usd 0 --execute

# 2. Open for real work, then #63 and #64
python -m scripts.aws.v1.session open --config D/operator-config.json $S
python -m scripts.aws.v1.evidence gateway  $S --state-dir D --run-id R --fixture short.mp4
python -m scripts.aws.v1.evidence capacity $S --state-dir D --run-id R --fixture long.mp4 \
    --short-fixture short.mp4 [--poison]

# 3. Derive the drain proof from the receipts and close; note the printed close time
python -m scripts.aws.v1.evidence counts --state-dir D --run-id R
python -m scripts.aws.v1.session close --config D/operator-config.json $S

# 4. #67 closed state and the ACU pause (waits up to 30 min for capacity to reach 0)
python -m scripts.aws.v1.evidence spend $S --state-dir D --run-id R --closed-at <close time> \
    --only close-state,pause

# 5. #66 needs the paused database: cold wake first, then the Fargate generator (it opens its own window)
python -m scripts.aws.v1.evidence latency $S --state-dir D --run-id R
python -m scripts.aws.v1.session close --config D/operator-config.json $S

# 6. #65 release (window, not open; needs a `sql` station and a plan, see below)
python -m scripts.aws.v1.session window --config D/operator-config.json $S
python -m scripts.aws.v1.evidence release $S --state-dir D --run-id R --plan plan.json
python -m scripts.aws.v1.session close --config D/operator-config.json $S

# 7. Tear down, then the spend steps that need the receipt and the invoice to lag in (~1 day)
python -m scripts.aws.v1.deploy teardown $S --run-id R --state-dir D \
    --execute --confirm-run-id R
python -m scripts.aws.v1.evidence spend $S --state-dir D --run-id R --only cost-explorer,teardown-receipt

# 8. Redacted summary for the repository (refuses simulated receipts)
python -m scripts.aws.v1.evidence summary --state-dir D --run-id R
```

| Step | Time | Cost | Closes (as evidence, not by itself) |
|---|---|---|---|
| 0 | 1 min | 0 | - |
| 1 | 50-80 min | see Ordered steps | deploy part of #63 |
| 2 gateway | 10-15 min | encoder task, cents | #63 anonymous and forged denial, session round trip, CORS, queue and cross-database denial, direct upload to HLS playback |
| 2 capacity | 60-90 min (the DLQ poison adds about 35 min: visibility 420 s x 5 receives) | three encoder tasks for minutes: low dollars at the Fargate rates above | #64 1/2/3 concurrent encoders, mid-encode stop recovery inside 300 s, DLQ empty, drain |
| 3-4 | 5 + up to 30 min | DB awake for the wait | #67 closed state, ACU pause |
| 5 | 15-20 min | generator task cents plus DB awake | #66 cold wake kept apart from 50-user warm status p90 and 20-login p90 |
| 6 | 20-40 min | pennies plus DB awake | #65 promote, rollback, peer owner untouched, optional failing candidate |
| 7 | 25-45 min, plus about a day | stops the meter | #67 resources remaining and spend, the invoice itself is not proven |

Release plan (`plan.json`, nonsecret): `owner` (`media` or `processing`), `migration_definition`,
`target_revision`, `good` and `baseline` images each `{bundle, image_uri, compat_evidence}` (a
Processing release adds `worker_definition`), and an optional `bad` image that must fail its smoke
test. Without a `sql` block in the operator config the release steps record `NOT_RUN`.

Caveats that matter when reading receipts:

- `--assume-empty-counts` in step 1 is true only for the first deploy. After step 2 the close in
  step 3 uses the counts file `evidence counts` wrote into the operator config (an attestation that
  nothing else ran on this stack, stated in its output), or a `sql` station.
- Cross-database denial needs a station that reaches the private database; from outside the VPC the
  step records `NOT_RUN`. `--skip-cross-database "reason"` records a deliberate skip.
- The generator measures from a Fargate task in the same region, with a task definition it registers
  and deregisters itself, using an account it registers itself: no credential is put in the task
  overrides. It reports no retries and keeps every failure in the denominator.
- The summary holds statuses, durations and numbers only (no account, URL, ARN, address or token);
  a value that looks like one fails the step instead of being stored.

## Known gaps

- Never executed against AWS. Request fields were checked offline against the installed AWS CLI's
  `--generate-cli-skeleton` output (a test does this when `aws` is on the path), not against live
  service behaviour. Expect a first-run surprise or two, and read `status` before rerunning.
- The SPA upload (`frontend` step) has only run against the simulated account and a fake CloudFront; the first real run may show an S3 or invalidation surprise.
- `schema_revision` and the drain proof need a station that can reach the private database. Without
  one, migrations are verified by exit code only and the close-proof is operator-attested.
- ECS tasks and ECR images carry no tags (the shared task contract has no `tags` field, and images
  are not taggable); the cluster and repositories are tagged and owned.
- A failed run leaves the stack in `ROLLBACK_COMPLETE`; use a new run id and run `teardown` for the
  old one (it deletes the failed stack by ownership).
- A harness rerun after `finalize` succeeded replays the reservation (Media answers `upload: null`
  for a finalized one) and finalize, keeps the first run's timings and reuses the same job.
- One run at a time: the 6-vCPU Fargate quota and the Lambda limit of 10 do not allow overlap.
