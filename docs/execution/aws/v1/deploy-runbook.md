# V1 deploy and teardown runbook

Status (updated 18 October): **written offline, then run against AWS once by an operator.** Run
`r1017b` (17 October) deployed with the pipeline in
[`scripts/aws/v1/deploy.py`](../../../../scripts/aws/v1/deploy.py) and recorded redacted receipts for
#63-#67 in [`evidence/cloud-proof-r1017b.json`](evidence/cloud-proof-r1017b.json); that run exposed
defects that were fixed afterwards (for example the Aurora wake-up during bootstrap). The CD workflow
described at the end of this file was exercised by runs `r1018a` (partial) and `r1018b` (deploy green;
releases promoted but the post-release smoke did not pass; teardown failed twice and was finished from
the laptop). It is not yet green end to end (pending `r1019a`); see
[`evidence/r1018b-results.md`](evidence/r1018b-results.md). Nothing here authorizes AWS operations, spend or deletion; the
operator named in [`cloud-operator-20261015.md`](cloud-operator-20261015.md) decides when to run it.

One ordered, resumable, journaled path takes the account from nothing to a smoke-tested,
closed V1 and back to nothing. Every step journals itself, supports `--dry-run`, and tags what
it creates `deploy-project=dc2-v1` and `owner-run=<run id>` (the keys avoid `Project`, which the
template already uses: IAM compares tag keys case-insensitively and would reject the duplicate).

## Before the first real run

The operator must decide or supply all of these. None has a default.

| Item | Why it blocks |
|---|---|
| Credentials that satisfy `FlickPondRequireMFA`: an MFA session in profile `dc2-project2-mfa`, **or** the dedicated agent user in profile `dc2-agent` | `FlickPondRequireMFA` denies when `aws:MultiFactorAuthPresent` is `false`. Direct calls with the long-term key pass, but calls CloudFormation makes on the caller's behalf carry no MFA and are denied. So every deploy, session and evidence command uses the session profile that `make aws-mfa-session CODE=<6 digits>` writes (the helper asks `sts get-session-token` for 129600 s, the 36 h maximum, and prints the expiry). Preflight blocks a long-term key and says to run the helper, unless the policy simulator shows that key's principal is not subject to an MFA deny (next paragraph). The pipeline will not bypass or edit the policy.

**Dedicated agent user (authorized 2026-10-17).** The IAM user `flickpond-agent` (AdministratorAccess and `FlickPondRegionLock`; not in the group that carries `FlickPondRequireMFA`, no MFA device) uses long-term keys in profile `dc2-agent`, so no MFA session exists or is needed. The pipeline does not trust the profile name: `mfa_required()` calls `iam simulate-principal-policy` for `s3:CreateBucket` and `cloudformation:CreateStack` with `aws:MultiFactorAuthPresent=false`, `aws:ViaAWSService=false` and `aws:RequestedRegion=ap-southeast-1`. Any `explicitDeny` means MFA is required (blocker, as before); all `allowed` means it is not (preflight `credentials` and `mfa` pass, detail "principal is not subject to an MFA deny (simulated)"); AccessDenied, an error or an inconclusive answer is unknown and fails closed as a blocker. Teardown `--execute` applies the same test. Sessions and assumed roles keep their old behaviour. `Guruprasath` still needs the MFA-session path. Never paste key ids or secrets into a command, file or issue; `--profile` names a profile only. |
| `--run-id` (2-16 lowercase letters/digits) | Namespace `dc2-v1-<run id>` must fit CloudFormation's 24-character `EnvironmentId`. A new id per attempt; a failed stack leaves `ROLLBACK_COMPLETE` that blocks its name. |
| `--state-dir` (private, outside the repo) | Journal, stack outputs, smoke credentials, the transient database role passwords, receipt. Mode 0700, files 0600. Back it up: it is the only record of what this run owns. |
| `--images` | The `--out` evidence file of `deploy/v1/build_and_verify.py` (accepted only if `LOCAL_ARTIFACT_PASS`; each image must still have the verified config id), or a hand-written `images.json`. See below. |
| `--seed-email` | Address for the smoke account. Must pass the Media API's email validation (not `.invalid`). |
| How `session close` proves a drain | One of `--sql-config` (needs a station inside the VPC), `--counts-file`, or `--assume-empty-counts` (the operator attests no worker ever ran, true for a first deploy). Without one the pipeline refuses to open the window. Later closes can instead pass `session close --in-vpc-counts`, which counts the attempts with a finite task inside the VPC (no station, no attestation). |
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

`--dry-run` never reads or writes a real state directory (it uses a temporary one) and starts
at most one kind of process: a read-only `docker image inspect --format ... <ref>`, and only
when `--images` is real build evidence (it carries the verified `config_id`). That is the one
fact a dry run can check for real, so the images step sees the local daemon's id, and the
output's `image_inspect` labels each answer `observed: local Docker daemon` or, when the daemon
is unreachable or lacks the image, `simulated: build evidence config_id`. `login`, `tag` and
`push` stay simulated, and `rehearse` and hand-written `--images` start no process. `teardown --dry-run --state-dir D` only *reads* D's journal to rehearse what
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
`startedBy` whose ARN was never journaled) and waiting up to 5 minutes for STOPPED. ListTasks
filters on the desired status, so a task drops out of it as soon as StopTask is accepted; every
discovered ARN is therefore journaled (`bootstrap_retiring`) before it is stopped and described
directly until ECS reports STOPPED, across resumes too. An ARN ECS reports MISSING (or not at all)
counts as stopped only after 3 consecutive looks, the same reconciliation as a vanished task. If
that cannot
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
   because the retained database holds the VPC's subnets. A stack deployed with the opt-in V2
   `--database-topology separate` (#94, `docs/execution/aws/v2/database-topology.md`) has two
   clusters: every deletion is requested before any is waited on, and the snapshots are
   `<env>-media-final` and `<env>-processing-final`.
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
11. `td-receipt`: observe what is left from the services, plus the tagging API. The tagging API
    is eventually consistent and keeps listing deleted resources for a while (the `r1017a`
    teardown reported ten that were all gone), so each hit it returns that the services have not
    already accounted for is confirmed with its owning service before it is called remaining:
    an EC2 `*.NotFound` (or a VPC endpoint in state `deleted`), an ECS cluster or task
    definition that is `INACTIVE` (free) or being deleted, an RDS not-found (both the `Fault` and
    plain spellings) and an S3 `NoSuchBucket` are gone. Anything else stays, with the state that
    was observed, and a type with no existence check stays as `unchecked` rather than being
    guessed. The run's `INACTIVE` task definitions are then deleted (`ecs delete-task-definitions`,
    ten at a time, errors tolerated and recorded) so they stop being listed. The receipt's
    `tagging_api_observed` lists every hit with the observed state, those confirmed gone included.

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
| migrations | Alembic revisions and task exit codes; schema check labelled `task-exit-code-only` or `alembic_version-over-verified-tls` | - | pre-release schema revision (read later by the release CLI, `schema_revision_source: in-vpc-task` or `sql-station`) | - | task timestamps |
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
`--profile dc2-agent --region ap-southeast-1 --account 866865534361` (or `--profile dc2-project2-mfa` for
the MFA-session path), `D` for the private
`--state-dir` the deploy used, `R` for its run id. Every harness keeps its receipt at
`D/evidence/evidence-<issue>-R.json` (0600), skips a step that already passed (rerun is safe;
`--only a,b` picks steps), exits 1 only when a step run just now failed, and **refuses to start**
while the session journal says closed (and between polls, also when the Gateway throttle is 0).
A step that cannot be observed is `NOT_RUN`, never `PASS`.

```sh
# 0. Credentials. With profile dc2-agent there is nothing to mint; prove it read-only first:
#      python -m scripts.aws.v1.deploy deploy $S --run-id R --state-dir D --assume-empty-counts \
#          --forecast-usd 0 --stop-after preflight      # no --execute: preflight makes only reads
#    With Guruprasath, mint the MFA session (the only interactive step):
make aws-mfa-session CODE=123456                      # writes profile dc2-project2-mfa, prints expiry
# then rehearse everything offline
make aws-proof-rehearse                               # every harness vs the simulation; proves nothing
python -m scripts.aws.v1.deploy deploy $S --run-id R --dry-run

# 1. Deploy (the ladder above, `--execute` last); it ends with the session closed
python -m scripts.aws.v1.deploy deploy $S --run-id R --state-dir D --images images.json \
    --seed-email ops@example.com --assume-empty-counts --forecast-usd 0 --execute
#    (add --unattended-launch to the line above only for the optional #68 measurement)

# 2. Open for real work, then #63 and #64
python -m scripts.aws.v1.session open --config D/operator-config.json $S
python -m scripts.aws.v1.evidence gateway  $S --state-dir D --run-id R --fixture short.mp4
python -m scripts.aws.v1.evidence capacity $S --state-dir D --run-id R --fixture long.mp4 \
    --short-fixture short.mp4 [--poison]
#    #185 backlog throughput (needs a plain `session open`, not `--unattended`): six identical
#    clips per cap, drained at encoder cap 1, then 2, then 3. About 35-40 min and about 0.11 USD of
#    Fargate with the 36 MB fixture (18 encoders of roughly 165 s billed each).
python -m scripts.aws.v1.evidence capacity $S --state-dir D --run-id R --fixture long.mp4 \
    --backlog 6
#    #196 failure isolation (plain `session open`): switch off Processing's command consumer, upload
#    through the public API, check Media accepted it and holds the command, switch the consumer
#    back on, and require `done` within the gate. About 6-8 min, one short encode.
python -m scripts.aws.v1.evidence isolation $S --state-dir D --run-id R --fixture short.mp4

#    #68 (V2, optional): only on a stack deployed with `deploy ... --unattended-launch` (step 1),
#    and only after the #185 sweep above, which is its baseline. Close the plain session, reopen
#    it unattended, run the IAM check ("Unattended launcher" below), then the observe-only harness:
python -m scripts.aws.v1.evidence counts --state-dir D --run-id R
python -m scripts.aws.v1.session close --config D/operator-config.json $S
python -m scripts.aws.v1.session open --config D/operator-config.json $S --unattended --minutes 90
python -m scripts.aws.v1.evidence unattended $S --state-dir D --run-id R --fixture long.mp4 \
    --iam-simulated

# 3. Derive the drain proof from the receipts and close; note the printed close time
python -m scripts.aws.v1.evidence counts --state-dir D --run-id R
python -m scripts.aws.v1.session close --config D/operator-config.json $S
#    or skip the attested file and count the attempts inside the VPC (one finite task per poll,
#    about a minute each; the database is resumed first if it is paused):
#      python -m scripts.aws.v1.session close --config D/operator-config.json $S --in-vpc-counts

# 4. #67 closed state and the ACU pause (waits up to 30 min for capacity to reach 0)
python -m scripts.aws.v1.evidence spend $S --state-dir D --run-id R --closed-at <close time> \
    --only close-state,pause

# 5. #66 needs the paused database. Step 4 above already proved the pause; the cold wake still
#    polls CloudWatch for up to 15 min (--pause-wait-minutes) before it records NOT_RUN.
#    Run long live commands under `nohup ... &` so they survive the terminal or agent session
#    that started them (a killed generator left the session open for 5 h on 2026-10-17). Wait
#    for each to exit (`tail -f` its log; the JSON report is its last output) before the next.
#    5a. Cold wake: opens its own window, waits (<= 60 s, recorded as gate_settle_seconds and
#        gate_probes, apart from window_open_seconds) until the Gateway stops answering 429,
#        times login and two reads, and closes the window it opened (window_closed).
nohup python -m scripts.aws.v1.evidence latency $S --state-dir D --run-id R --only cold-wake \
    > cold-wake.log 2>&1 &
#    5b. The 50-user load needs a bigger gate than the default 5/s. Set in operator-config.json
#        "edge_open": {"rate": 100, "burst": 200}, then open. The generator refuses (before
#        registering anything) a stage below 50/s, burst 100.
python -m scripts.aws.v1.session open --config D/operator-config.json $S
nohup python -m scripts.aws.v1.evidence latency $S --state-dir D --run-id R --only generator \
    > generator.log 2>&1 &
python -m scripts.aws.v1.session close --config D/operator-config.json $S --in-vpc-counts
#    PASS and NOT_RUN are final in a receipt, and a FAILed step resumes its recorded task. To
#    measure again after fixing the cause, add --fresh: the selected steps' old entry and intent
#    are archived under "attempts" in the private receipt (never in the summary) and the step
#    mints a new task, e.g. `... --only generator --fresh`. Without --only it applies to every
#    step of #66. `--fresh` is refused for every other proof (their drain counts and release
#    snapshots are cumulative). Each attempt's raw samples keep their own file
#    (latency-samples-R.csv, then -a2, -a3 ...); none is ever overwritten.

# 6. #65 release (window, not open). No SQL station: the owning schema revision is read by a
#    finite task inside the VPC. Build plan.json first ("Release proof on an existing stack").
python -m scripts.aws.v1.session window --config D/operator-config.json $S
python -m scripts.aws.v1.evidence release $S --state-dir D --run-id R --plan D/release/plan.json
python -m scripts.aws.v1.session close --config D/operator-config.json $S --in-vpc-counts
python -m scripts.aws.v1.evidence release-plan $S --state-dir D --run-id R \
    --deregister D/release/plan.json                  # retire the definition revisions it made

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
| 2 capacity `--backlog 6` | 35-40 min (18 encodes; `--drain-timeout` 2400 s per cap) | about 0.11 USD of Fargate: 18 encoders, roughly 165 s billed each | #185 jobs/min, median and p90 queue wait, failures and billed seconds per cap, speedup at cap 2 and 3 against 1.6x and 2.1x |
| 2 isolation | 6-8 min (consumer off 30-150 s, then one encode) | one short encoder, cents | #196 Media accepts and holds an upload while the ProcessingCommands consumer is off; it reaches `done` after re-enabling |
| 2 unattended | 15-20 min plus the 3 min settle | about 0.11 USD of Fargate plus an awake database | #68 launcher cap, starts per job, idle starts, queue wait against the operator-batch step |
| 3-4 | 5 + up to 30 min | DB awake for the wait | #67 closed state, ACU pause |
| 5 | 15-20 min | generator task cents plus DB awake | #66 cold wake (wake, gate settle and requests kept apart) and the 50-user warm status p90 and 20-login p90, with 429s counted apart from errors |
| 6 | 20-40 min | pennies plus DB awake | #65 promote, rollback, peer owner untouched, optional failing candidate |
| 7 | 25-45 min, plus about a day | stops the meter | #67 resources remaining and spend, the invoice itself is not proven |

### Backlog throughput (`capacity --backlog N`, #185)

The 1/2/3 runs above put one job on each encoder, so they show independence but never leave work
waiting. `--backlog N` is the proposal's scalability scenario (section 3.4): a fixed backlog drained
at a fixed encoder cap, judged on jobs per minute and queue wait. It replaces that invocation's
1/2/3 runs (it cannot be combined with `--short-fixture` or `--poison`) and writes its own receipt,
`D/evidence/evidence-185-R.json`, with the steps `backlog-1`, `backlog-2`, `backlog-3` and
`backlog-compare`. Re-running skips a step that passed; `--only backlog-2` picks one; `--workers 2,3`
picks caps (the comparison needs all three).

How the cap is kept: a V1 encoder is a finite task that claims **one** attempt, encodes it and
exits, so "cap 2" cannot mean two encoders that each work through the backlog. For each cap the
harness uploads N identical clips with no encoder running (a fixed backlog, a fresh one per cap),
then acts as the operator: it starts `min(queued jobs - encoders that have not claimed yet,
cap - encoders alive)` through `Session.batch` and repeats every 5 s, so a replacement starts as soon
as an encoder reaches STOPPED while jobs are still queued. Alive encoders therefore never exceed
the cap, and every refill pays a Fargate start (about 20 s) that cap 1 pays six times in series.
Starts are bounded at 2 per job; a refused start ("cap reached", e.g. a task still STOPPING) is
retried on the next poll. Do not open the session with `--unattended`: the launcher owns starts
then and `Session.batch` refuses.

Per cap the receipt records, all of it redacted (numbers and verdicts only):

| Field | Source |
|---|---|
| `jobs_per_minute` | jobs done / (first upload started to last job seen terminal); `drain_jobs_per_minute` starts at the first encoder launch instead, which leaves out the upload time every cap pays equally |
| `queue_wait_*`, `processing_*` | `queued_at`, `started_at`, `finished_at` of the current attempt from `GET /api/processing/jobs/<id>`: server-side stamps, so no client clock skew. A missing stamp is counted in `missing_queue_wait`, not guessed, and fails the step. p90 is nearest-rank (with 6 jobs it is the slowest) |
| `jobs_failed`, `outcomes`, `retried_jobs` | final job status; an attempt number above 1 counts as retried |
| `encoder_billed_seconds(_total)`, `encoders_started`, `launch_waves` | pull-start to stop of each task |
| `peak_concurrent_from_task_stamps`, `peak_concurrent_polled` | must not exceed the cap |
| `encoders_left_running` | live tasks after the step; must be 0 |
| `max_poll_gap_seconds` | a silence over 60 s between control polls means encoders were not being refilled (a suspended laptop), and fails the step |

`backlog-compare` reads only the three recorded steps and reports speedup over cap 1 as measured,
unrounded for the verdict: PASS needs every cap step PASS, one backlog size and fixture, speedup
at least 1.6 at cap 2 and at least 2.1 at cap 3 on the `jobs_per_minute` basis. The drain-basis
ratios, the zero-overhead `ideal_speedup` for the chosen N, and whether the median queue wait fell
at each step are reported beside it and do not change the verdict. A miss is recorded as FAIL with
the numbers. Re-running a FAILed cap step resumes its recorded jobs and recomputes the same
verdict (and `--fresh` is refused), so a new measurement needs a new run id.
Cap 3 is the ceiling because the account's Fargate quota is 6 vCPU and an encoder is 2 vCPU; the
receipt says so in every step.

A step that times out (`--drain-timeout`, default 2400 s) or is interrupted stops its own
encoders, records what it saw and fails; the jobs it left queued block the next cap, so they
cannot join its backlog. `counts` includes the backlog jobs for the close proof (a job left
unfinished is counted as queued). N must be 3 to 12 and large enough that the targets are
reachable with zero overhead (a multiple of 6 is best: 6 and 12 give ideal 2.0x and 3.0x). The
fixture is whatever `--fixture` names; the measured 36 MB clip fits the budget, and a much shorter
clip lets the fixed task start dominate and flatters nothing.

### Failure isolation (`isolation`, #196)

Media's finalize writes a command to its own outbox and never calls Processing. This step proves
it on the deployed stack. It needs a plain `session open` (the ProcessingCommands mapping must be
Enabled) and writes `D/evidence/evidence-196-R.json`, one step, `processing-down`:

1. record that the mapping is Enabled, disable it and wait for Lambda to report `Disabled`;
2. reserve, upload and finalize one clip through the public API (finalize must answer 2xx);
3. for 30 to 150 s, poll the job: it must stay visible (by id and in the job list), show `accepted`
   or `queued`, carry no Processing job id, and the command must be held in Media's outbox
   (`submission_status` pending) or in the ProcessingCommands queue (depth read from SQS);
4. re-enable the mapping and wait for `Enabled`, wait for Processing's job id to reach Media
   (up to 120 s), start one finite encoder (another if it exits without claiming) and require `done`
   within `--job-timeout` (default 900 s) of the re-enable.

"Processing down" means its command consumer is off. The Processing API stays up: under this
stack's `zero_reservation: off` policy a function cannot be quiesced without writing reserved
concurrency that `session status` would then report as drift, and the mapping is the one switch
the session already owns.

The mapping is restored on every exit path. The intent is journaled before the mapping is touched;
an error or an interrupt re-enables it before the command exits. If the session was closed meanwhile
`session close` has already disabled every mapping, so the step leaves it disabled and says so
(`mapping_restore`); it never reopens a consumer inside a closed window. If the process is killed
outright, rerun the same command: it resumes the same upload, re-enables the mapping and finishes.
Check `session status` afterwards: no drift is expected.

### Unattended launcher (`unattended`, #68, V2 experiment)

Optional, after the V1 evidence, on the same stack and in the same session as the #185 sweep so the
two are comparable. Every step below is outside the V1 critical path.

1. **Deploy with the launcher.** Add `--unattended-launch` to the step 1 `deploy` command. It
   renders `UnattendedLaunch=true`: a `ProcessingLauncher` Lambda and a `rate(1 minute)` rule that
   stays `DISABLED`, with outputs the operator config picks up. Without the flag nothing changes
   from V1. The migrations step applies `processing_0007` (two additive tables).
2. **Operator-batch baseline first.** Run `capacity --backlog` under a plain `session open`: the
   launcher is off, and that cap-3 step is what the launcher is compared with.
3. **Check the launcher role's IAM before its first tick** (its conditions have never been
   evaluated). With `P` standing for the profile and region flags, `O` for `D/outputs.json`:

   ```sh
   ROLE=$(aws $P lambda get-function-configuration --query Role --output text \
       --function-name "$(jq -r .ProcessingLauncherFunctionName $O)")
   CLUSTER=$(jq -r .ClusterArn $O); TD=$(jq -r .WorkerTaskDefinitionArn $O)
   WORKER=$(aws $P ecs describe-task-definition --task-definition "$TD" \
       --query 'taskDefinition.[taskRoleArn,executionRoleArn]' --output text)
   QUEUE=$(jq -r .ProcessingWorkQueueUrl $O | awk -F/ '{print "arn:aws:sqs:ap-southeast-1:"$4":"$5}')
   sim() { aws $P iam simulate-principal-policy --policy-source-arn "$ROLE" "$@" \
       --query 'EvaluationResults[].[EvalActionName,EvalDecision]' --output text; }
   CTX="ContextKeyName=ecs:cluster,ContextKeyValues=$CLUSTER,ContextKeyType=string"
   sim --action-names ecs:RunTask --resource-arns "$TD" --context-entries "$CTX"
   sim --action-names ecs:ListTasks --resource-arns '*' --context-entries "$CTX"
   sim --action-names ecs:DescribeTasks --context-entries "$CTX" \
       --resource-arns "arn:aws:ecs:ap-southeast-1:$(jq -r .ClusterArn $O | cut -d: -f5):task/${CLUSTER##*/}/x"
   for r in $WORKER; do sim --action-names iam:PassRole --resource-arns "$r" --context-entries \
       ContextKeyName=iam:PassedToService,ContextKeyValues=ecs-tasks.amazonaws.com,ContextKeyType=string; done
   sim --action-names sqs:GetQueueAttributes --resource-arns "$QUEUE"
   sim --action-names ecs:StopTask sqs:ReceiveMessage s3:GetObject --resource-arns '*'  # must be denied
   ```

   Every first group must print `allowed` and the last must print `implicitDeny`. If the profile
   may not call `iam:SimulatePrincipalPolicy`, stop: the check is the point, and an unchecked
   launcher is not run. Pass `--iam-simulated` to the harness only after this; the harness records
   the attestation as such and cannot verify it.
4. **Close, then reopen unattended.** `session close` (with `--in-vpc-counts` or after `evidence
   counts`), then `session open ... --unattended --minutes 90`. The minutes bound the launcher: it
   starts nothing after that session end. `session status` should show the launcher rule ENABLED
   and no drift. `session batch` and the backlog driver are refused for the rest of the session.
5. **Measure.** `evidence unattended ... --fixture long.mp4 --iam-simulated` (the clip and N of the
   baseline; `--backlog` defaults to the baseline's N). It writes `D/evidence/evidence-68-R.json`:
   - `launcher-preflight`: launcher in the stack, session opted in, rule ENABLED, nothing running,
     a passing `backlog-3` baseline in the #185 receipt. A failure stops the command before any
     upload.
   - `launcher-backlog`: uploads N clips, starts no encoder, and watches every worker-family task.
     It records queue wait and processing time (server stamps), jobs/min on the baseline's basis,
     peak concurrency from task stamps and from polling (cap 3), `encoders_started` and
     `starts_per_job`, `unclaimed_encoders` (started without claiming a job), the start offsets
     from the first queued job, and `starts_after_backlog_empty` over a 180 s settle window (the
     launcher's idle-respawn pause is 120 s). PASS needs every job done, peak at most 3, no start
     after the backlog emptied, at most 3 unclaimed encoders (the launcher's idle breaker) and
     nothing left running.
   - `launcher-compare`: the same numbers beside the operator-batch `backlog-3` step, with deltas.
     There is no speed target; ratios are as measured. It is FAIL if the backlog size or the
     fixture differs, or if the launcher step failed.
6. **Close.** `session close` disables the launcher rule and its SQL flag first. Afterwards
   confirm no encoder is running, the rule is DISABLED and `session status` shows no drift. The
   Lambda invocation count and the Aurora awake minutes for the cost comparison come from
   `evidence spend` and CloudWatch, not from this harness. The launcher's lost-response replay
   needs a forced client timeout and is not exercised here.

An interrupt stops the encoders the launcher started but cannot stop the launcher: close the
session to do that.

### Release proof on an existing stack

V1 has no bastion and Aurora is private, so the release code reads the owning schema revision
from a finite Fargate task in the VPC: the owner's deployed migration task definition with a
command override that runs `scripts/aws/v1/vpc_probe.py` (it needs no new image and no secret in
the override; the task already holds the owner's migration role and the RDS CA). The probe
connects with a required certificate chain and hostname, asks the server whether the session is
encrypted, prints one tagged line (a revision or counts, never a DSN) and exits; a paused Aurora
is waited out for up to 150 s inside the task. The CLI parses CloudWatch Logs, stops the task on
any error and records `schema_revision_source: in-vpc-task` in every release result and in the
#65 receipt. A `sql` block in the operator config still takes precedence (`sql-station`).

The `baseline` step reads both owners first (it wakes a paused database before any clocked
operation), and `owner-isolation` reads the peer again after the last release. A promotion's own
reads (about 40-60 s each; the opening pair and restore's closing pair run side by side) count
inside its 600 s / 300 s gate, so a slow Fargate start is visible in the receipt as
`schema_read_seconds`.

**`plan.json`** (nonsecret; `evidence release-plan` writes it):

| Field | Meaning |
|---|---|
| `owner` | `media` or `processing` (run each owner under its own `--run-id`: a receipt covers one) |
| `target_revision` | the owner's Alembic head every image migrates to. For this proof it must be the stack's **current** head, so the migration task is a no-op that still proves the task, the pinned definition and the schema read |
| `baseline` | the images the stack runs now, from the deploy journal; the rollback is a second promotion of this set |
| `good` | a new image set to promote |
| `bad` | optional: an image that must migrate and then fail the public smoke, so the real restore path runs (one that fails its migration is cleared by `release abandon` and the step is a FAIL); omitted, that step is `NOT_RUN` |
| each image set | `bundle` (path to `{api[, worker]}` artifact receipts), `image_uri` (`repo@sha256:...` of the API image), `compat_evidence` (path), `migration_definition` (pinned ARN with revision whose container holds exactly that digest), `worker_definition` (Processing only, same rule) |
| `migration_definition` | optional plan-level default for plans whose images share a definition (they rarely can: the release checks the digest) |
| `registered_definitions` | the task definition revisions `release-plan` registered, for `--deregister` |

```sh
# a. What the stack is, read from the VPC (also proves the reader): current heads and their source
python -m scripts.aws.v1.release schema --config D/operator-config.json $S
jq '.deploy.images | map_values({tag, digest, local_id})' D/deploy-journal.json
BASE=$(grep -l "$(jq -r .deploy.images.media.local_id D/deploy-journal.json)" \
       docs/execution/aws/v1/evidence/local-images-*.json)  # build evidence of the deployed images

# b. A different, locally verified image set. Commit first: the image label is the commit, so a
#    new commit is a new config id. Each build must end LOCAL_ARTIFACT_PASS.
git switch -c release-proof-good && git commit --allow-empty -m "release proof: good image"
python deploy/v1/build_and_verify.py --out D/release/build-good.json        # media, processing, worker
T=$(make test-v1 | grep -Eo '[0-9]+ passed' | head -1 | cut -d' ' -f1)       # attested in the bundles

# c. Optional bad image. It must pass every local gate, MIGRATE, and fail only in the Lambda's
#    own database TLS, so login and the job calls fail the smoke and the restore path runs.
#    Do NOT replace deploy/v1/global-bundle.pem: the owner's migration task reads the same image,
#    its TLS fails, the release stops before any alias moves and restore refuses the intent
#    (#65 live run, 2026-10-17). Point only the Lambda handler at a valid non-RDS CA bundle.
#    Never merge or push this branch.
git switch -c release-proof-bad
#   processing: first lines of processing/lambda_handler.py, BEFORE `import processing.config`
#   (the migration task runs alembic via processing/migrations/env.py, not this module):
#       import os, certifi; os.environ["PROCESSING_DATABASE_CA_FILE"] = certifi.where()
#   media: the same at the top of media/lambda_handler.py, before any `media.*` import
#   (media/config.py reads `postgres_ssl_ca` with env prefix MEDIA_):
#       import os, certifi; os.environ["MEDIA_POSTGRES_SSL_CA"] = certifi.where()
#   certifi must be importable in the image; if not, use "/etc/ssl/certs/ca-certificates.crt"
#   (installed by the Dockerfiles) instead of certifi.where().
git commit -am "release proof: Lambda-only non-RDS CA bundle (migrates, must fail the smoke)"
python deploy/v1/build_and_verify.py --out D/release/build-bad.json
#   If a candidate still fails in its migration task, `release abandon` clears the intent once
#   it is proven that nothing moved (see "Release CLI actions"); the proof records that step as
#   FAIL with failed_stage "migration", because the restore path was not exercised.

# d. Push both sets with the deploy's immutable tag convention <id>-<owner> (a private docker
#    config, as the deploy uses); ECR scans on push. Use a new id per attempt.
export DOCKER_CONFIG=$(mktemp -d)
MEDIA=$(jq -r .deploy.outputs.MediaRepositoryUri D/deploy-journal.json)
PROC=$(jq -r .deploy.outputs.ProcessingRepositoryUri D/deploy-journal.json)
WORK=$(jq -r .deploy.outputs.WorkerRepositoryUri D/deploy-journal.json)
aws ecr get-login-password --profile dc2-agent --region ap-southeast-1 \
    | docker login --username AWS --password-stdin "${MEDIA%%/*}"
for pair in "g1:good" "b1:bad"; do                      # <tag id>:<build>, the sha is its commit
  id=${pair%%:*}; sha=$(jq -r .source_sha D/release/build-${pair##*:}.json | cut -c1-12)
  for target in "media:$MEDIA" "processing:$PROC" "worker:$WORK"; do
    docker tag "dc2-v1-${target%%:*}:local-$sha" "${target#*:}:$id-${target%%:*}"
    docker push "${target#*:}:$id-${target%%:*}"
  done
done

# e. plan.json. It asks the registry for each digest and a COMPLETE scan with no HIGH/CRITICAL
#    finding beyond the audited unfixed list (rerun in a minute if the scan is pending),
#    registers one definition revision per good/bad image (the deployed definition with only the
#    image swapped), builds the bundles and runs the release CLI's own offline gates on every
#    image set.
python -m scripts.aws.v1.evidence release-plan $S --state-dir D --run-id R --owner processing \
    --baseline-evidence "$BASE" --good-run-id g1 --good-evidence D/release/build-good.json \
    --bad-run-id b1 --bad-evidence D/release/build-bad.json \
    --tests-passed "$T" --attest-schema-unchanged \
    --accept-unfixed docs/execution/aws/v1/scan-accepted-unfixed-20261017.json \
    --target-revision <processing revision printed by step a>   # default: this checkout's head
```

`--accept-unfixed` is legitimate only for findings with no fixed version available (the pinned
base's Debian packages, confirmed by an empty `apt list --upgradable`); re-check each id before
every release and drop any that now has a fix. A fixable finding must be fixed by rebuilding, not
accepted. Any HIGH/CRITICAL id not on the list still blocks, and the receipt records the accepted
ids and the list's sha256 per image.

What `release-plan` checks and what it only records. Checked: the baseline evidence is the build of
the images the deploy journal recorded; the registry digest of every baseline tag equals the digest
the deploy recorded; the stack's own migration/worker definitions still hold those digests; no good
or bad image equals a baseline image; every scan is COMPLETE with zero HIGH/CRITICAL beyond the
accept list; the release gates (`validate_bundle`, digest pin, Processing worker) pass. Recorded as the operator's word:
`--tests-passed` (the source tests behind the images) and `--attest-schema-unchanged` (no image adds
a migration beyond `--target-revision`, and both directions are compatible with it). The bundle's
`manifest_config_id` is the local config id, because `docker push` of a local image keeps it.
Everything it writes is mode 0600 under `D/release/`.

### Release CLI actions

`python -m scripts.aws.v1.release ACTION --config D/operator-config.json $S`:

| Action | Does |
|---|---|
| `promote` | migrate the owner, publish immutable Lambda versions, move `live`, smoke through the Gateway, keep the intent if it fails |
| `restore` | put the prior aliases back after a failed promote; never downgrades a schema; refuses until the migration completed |
| `abandon` | clear a pending release that provably changed nothing (see below) |
| `status` | read-only: the journal's intent (`migration_complete`, `moved`, `versions`) and each live alias |
| `schema` | read-only: both owners' Alembic revisions and the read's source |

A pending intent blocks `session open` and any other promote. A candidate that fails in its migration
task leaves `{phase: preparing, migration_complete: false, moved: {}}`, which `restore` refuses by
design. `release abandon [--reason TEXT]` clears it only when all of these are read live: there is
a pending release; no alias moved; every function's `live` alias still equals its prior receipt (version and revision id, so an alias moved away and back is refused); the owner's migration task is stopped (any exit code), was never started, or its lost launch is found stopped by `startedBy` (a launch that left no trace is refused until the one-hour RunTask replay window has passed; a task ECS no longer lists is unknown and refused, so abandon within about an hour of the failure); no
published version is aliased (published-but-unaliased versions are immutable, harmless, and listed
in the result as `versions_published_unaliased`); the owner's schema revision (read in the VPC, or
by the SQL station) equals the revision recorded before the release began; the owner is quiescent.
Any failed check is a refusal that keeps the intent. On success the intent moves to
`abandoned_releases` in the journal. After a migration that did apply, abandon refuses (schema
changed) and restore is the path.

Run Media the same way with `--owner media` and its own `--run-id`; each owner is promoted,
rolled back and checked against the other independently, and `evidence summary` takes one run id
at a time.

Caveats that matter when reading receipts:

- `--assume-empty-counts` in step 1 is true only for the first deploy. After step 2 the close in
  step 3 uses the counts file `evidence counts` wrote into the operator config (an attestation that
  nothing else ran on this stack, stated in its output), a `sql` station, or `--in-vpc-counts`,
  which reads the real attempt counts from Aurora with a finite task and needs no attestation.
- Cross-database denial needs a station that reaches the private database; from outside the VPC the
  step records `NOT_RUN`. `--skip-cross-database "reason"` records a deliberate skip.
- The generator measures from a Fargate task in the same region, with a task definition it registers
  and deregisters itself, using an account it registers itself: no credential is put in the task
  overrides. It reports no retries and keeps every failure in the denominator.
- The summary holds statuses, durations and numbers only (no account, URL, ARN, address or token);
  a value that looks like one fails the step instead of being stored.

## CD workflow

[`.github/workflows/cd.yml`](../../../../.github/workflows/cd.yml) runs the commands above from
GitHub Actions through [`scripts/ci/cd.sh`](../../../../scripts/ci/cd.sh); it adds no deploy
logic. It is the recorded, repeatable form of steps 0, 1, 6 and 7 plus an upload-to-playback smoke.

```sh
gh workflow run cd.yml -f operation=preflight -f run_id=r1018a            # reads only
gh workflow run cd.yml -f operation=deploy    -f run_id=r1018a -f execute=true
gh workflow run cd.yml -f operation=deploy    -f run_id=r1018b -f execute=true -f unattended_launch=true   # optional #68 launcher
gh workflow run cd.yml -f operation=release   -f run_id=r1018a -f owner=media -f execute=true -f attest_additive=true
gh workflow run cd.yml -f operation=teardown  -f run_id=r1018a -f execute=true
```

- **Nothing applies unless `execute=true`.** Off, `deploy` runs the real preflight and an offline
  rehearsal, `release` builds and verifies the images only, `teardown` prints its inventory plan.
- **Gate.** The `gate` job refuses a dispatch unless the latest `CI` run for the dispatched commit
  finished green (a commit with no run, a running one or a failed one is refused). Dispatch
  teardown from a green ref too.
- **Deploy** = preflight, native linux/amd64 `build_and_verify.py` on the runner, `deploy --execute`
  (the whole ladder, with the tool's own change-set review), then the smoke. **Release** builds the
  commit's images for one owner, pushes them with a fresh `g<run>x<attempt>` tag, lets
  `evidence release-plan` check digest, scan and bundle, then `session window`, `release promote`,
  `release restore` (or `abandon`) if it fails, `session close --in-vpc-counts`, then the smoke. The
  release commit must differ from the deployed one (the plan refuses an image equal to the baseline).
- **Smoke** = `session open`, `evidence gateway --only direct-upload-e2e` (a generated 3 s clip is
  reserved, uploaded straight to S3, finalized, encoded by the finite Fargate encoder the harness
  starts and played back as HLS through CloudFront), `session close --in-vpc-counts`. The window is
  closed even when the smoke fails. The Publisher CLI is not used: V1 starts the encoder from the
  operator session, so a Publisher job would sit queued.
- **Rollback through CD.** The `release` operation rolls back by itself: `release promote` runs its
  own smoke through the Gateway (health, anonymous denial, login, jobs, and for Media a reservation);
  if it fails, `cd.sh` runs `release restore` (or `release abandon` when the candidate failed in its
  migration task before anything moved), then closes the window, and the job fails with outcome
  `restored`. The upload-to-playback smoke that follows is a verification, not a gate: it runs after
  the promotion, and a failure there does not move any alias. Rolling back a release that passed its
  own smoke is a second promotion of the earlier image set, which the laptop `evidence release`
  harness does (#65, `rollback` step); the CD `release` cannot, because it refuses an image equal to
  the deployed baseline. To prove the automatic path on demand, dispatch `release` with
  `bad_candidate=true` (and `execute=true`): the runner commits a Lambda handler with a non-RDS
  database CA into the candidate (nothing is pushed), the candidate builds, migrates and fails its
  smoke, and the job is green only if the outcome was `restored`.
- **Encoder start in the smoke.** The smoke starts its single encoder only once the job is `queued`
  with a Processing job id, starts another if one exits without claiming (two starts at most), and
  refuses to start while the ProcessingWork queue still holds messages an earlier run left (#223).
- **Teardown close.** `td-session-close` retries each failed close step for up to four minutes in
  total (ten-second pauses; Aurora needs 30 to 60 s to resume and the launcher flag waits on it),
  and a failure names every unresolved step with the error type or curated message (#225). The
  drain checks are not retried.
- **Cost guard** inputs: `budget_usd` (30), `planned_hours` (3), `forecast_usd` (5; Cost Explorer has
  no history here, so the guard needs the operator's figure). Same flags and meaning as above.
- **Credentials.** The `aws` environment assumes `dc2-github-deploy` through GitHub OIDC (no key is
  stored in GitHub). The role and the state bucket come from
  [`deploy/aws/v1/github-oidc.yaml`](../../../../deploy/aws/v1/github-oidc.yaml); the repository
  variables `AWS_DEPLOY_ROLE_ARN` and `AWS_STATE_BUCKET` carry their names. The role's trust is
  `repo:Collaboration95@68595032/dc2@1391679981:environment:aws` (this repository uses immutable OIDC
  subjects, i.e. owner and repository ids, not the plain `Collaboration95/dc2`), and the environment only admits `Main`, `dev/closeout`
  so a branch of someone else cannot reach it. Its
  permissions equal the `flickpond-agent` user's: `AdministratorAccess` plus `FlickPondRegionLock`.
  Session length 4 h. It is written to the named profile `dc2-gha` because the tooling refuses
  ambient `AWS_*` credentials.
- **State.** `D` is `$HOME/dc2-state/<run id>` on the runner. It is restored from, and saved back to,
  `s3://dc2-cd-state-866865534361-ap-southeast-1/runs/<run id>/` (private, encrypted, versioned,
  TLS-only) around every deploy, release and teardown, including after a failure or cancel, so a
  rerun resumes from the journal. It holds the smoke login and, until the DSNs are published, the
  database role passwords, which is why it is never a workflow artifact. A resume after the images
  step reuses the recorded build evidence (`build-baseline.json`); a failure before it rebuilds.
- **Artifacts** hold only reduced files: step statuses, preflight check names, the redacted
  `cloud-proof-*.json` of the smoke, the release outcome. 14 days.

### Operator handoff: CD deploy, then session and evidence from a laptop

The cloud proof steps 2-6 (`session`, `evidence`, `release`) need the run's state directory `D`.
After a CD `deploy` it is in the state bucket, so a laptop with profile `dc2-agent` can take over
and hand back. `unattended_launch=true` on the `deploy` dispatch passes `--unattended-launch`
(the optional #68 launcher; fixed for the run, so repeat it on a resume).

```sh
R=r1018a                                   # the CD run id
D=$HOME/dc2-state/$R                       # any private directory outside the repository
B=dc2-cd-state-866865534361-ap-southeast-1
S="--profile dc2-agent --region ap-southeast-1 --account 866865534361"
mkdir -p -m 700 "$D"

# 1. Take over. Do it only when no CD run for this id is active (the workflow runs one at a time,
#    but nothing stops a laptop writing at the same time).
aws s3 sync "s3://$B/runs/$R/" "$D/" --profile dc2-agent --region ap-southeast-1 --only-show-errors
chmod -R go-rwx "$D"        # S3 keeps no modes; the tooling insists on 0700 / 0600

# 2. Work, exactly as in "Cloud proof in order" (profile dc2-agent, this D, this R)
python -m scripts.aws.v1.session open --config "$D/operator-config.json" $S
python -m scripts.aws.v1.evidence gateway $S --state-dir "$D" --run-id "$R" --fixture short.mp4
python -m scripts.aws.v1.session close --config "$D/operator-config.json" $S --in-vpc-counts

# 3. Hand back, so a later CD teardown or release sees the same journal and receipts. Close the
#    session first: teardown closes it anyway, but a journal that says "open" while the window is
#    closed (or the reverse) is the one inconsistency worth avoiding.
aws s3 sync "$D/" "s3://$B/runs/$R/" --delete --exclude "frontend-dist/*" --exclude "*.run" \
    --exclude "*.lock" --profile dc2-agent --region ap-southeast-1 --only-show-errors
```

What the commands read, all inside `D`:

| File | Used by |
|---|---|
| `operator-config.json` | every `session`, `release` and `evidence` command (`--config`, or `<state-dir>/operator-config.json`) |
| `outputs.json` | named by the config: Gateway and CloudFront URLs, function, queue and task-definition names |
| `session/journal.json` | named by the config: whether the window is open, closed or a release is pending |
| `deploy-journal.json` | `evidence` (images, definitions, repositories), `deploy status` and teardown; the only record of what the run owns |
| `smoke-credentials.json` | the smoke login (`evidence`, `release`); 0600 |
| `build-baseline.json`, `release/` | `evidence release-plan` and the CD `release` (baseline build evidence, plans and bundles) |
| `evidence/` | the receipts; `evidence summary` reads them |

Paths in this state are relative (to `operator-config.json` and to `plan.json`), so the same files
work on the runner and on a laptop; an older absolute path still loads. The commands refuse
ambient `AWS_*` credentials, so run them with the profile only. `db-bootstrap-passwords.json`
exists only between `db-bootstrap` and the DSNs being published; if a deploy failed in that window,
do not delete it. Never run the laptop and a CD dispatch for the same run id at once: the journal
has a lock on one machine, not across two.

## Known gaps

- Run against AWS once by an operator (`r1017b`), not yet through the CD workflow. Request fields were
  also checked offline against the installed AWS CLI's `--generate-cli-skeleton` output (a test does
  this when `aws` is on the path). Expect a surprise or two from a first CD run, and read `status`
  before rerunning.
- The SPA upload (`frontend` step) has only run against the simulated account and a fake CloudFront; the first real run may show an S3 or invalidation surprise.
- The release code and `session close --in-vpc-counts` read the private database with a finite task
  in the VPC; the `deploy` pipeline's own migration step still has no such reader, so without a
  `--sql-config` station it verifies migrations by task exit code only (`task-exit-code-only`), and
  the deploy-time close-proof is operator-attested. None of the in-VPC reads has run against AWS yet.
- ECS tasks and ECR images carry no tags (the shared task contract has no `tags` field, and images
  are not taggable); the cluster and repositories are tagged and owned.
- A failed run leaves the stack in `ROLLBACK_COMPLETE`; use a new run id and run `teardown` for the
  old one (it deletes the failed stack by ownership).
- A harness rerun after `finalize` succeeded replays the reservation (Media answers `upload: null`
  for a finalized one) and finalize, keeps the first run's timings and reuses the same job.
- One run at a time: the 6-vCPU Fargate quota and the Lambda limit of 10 do not allow overlap.
