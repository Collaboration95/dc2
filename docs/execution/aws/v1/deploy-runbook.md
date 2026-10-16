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
| MFA-capable credentials in profile `dc2-project2` | On 2026-10-15 an explicit `FlickPondRequireMFA` deny stopped `s3:CreateBucket` and the user had no MFA device. Preflight blocks an IAM user with no device. The pipeline will not bypass or edit that policy. |
| `--run-id` (2-16 lowercase letters/digits) | Namespace `dc2-v1-<run id>` must fit CloudFormation's 24-character `EnvironmentId`. A new id per attempt; a failed stack leaves `ROLLBACK_COMPLETE` that blocks its name. |
| `--state-dir` (private, outside the repo) | Journal, stack outputs, smoke credentials, receipt. Mode 0700, files 0600. Back it up: it is the only record of what this run owns. |
| `--images` | The `--out` evidence file of `deploy/v1/build_and_verify.py` (accepted only if `LOCAL_ARTIFACT_PASS`; each image must still have the verified config id), or a hand-written `images.json`. See below. |
| `--seed-email` | Address for the smoke account. Must pass the Media API's email validation (not `.invalid`). |
| How `session close` proves a drain | One of `--sql-config` (needs a station inside the VPC), `--counts-file`, or `--assume-empty-counts` (the operator attests no worker ever ran, true for a first deploy). Without one the pipeline refuses to open the window. |
| Forecast | Cost Explorer may have no history for a young account; then pass `--forecast-usd` (the operator's own figure). Unavailable and unsupplied fails closed. |
| `--budget-usd` | Default 30, matching `flickpond-monthly`. Preflight blocks if the budget does not exist, is not USD, or is below this flag. |
| Frontend upload | Not done by this pipeline (see gaps). |
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
| 6 | `db-bootstrap` | Reads the RDS-managed master secret, generates four distinct 32-character role passwords (memory only), writes temporary `/dc2/<env>/bootstrap-input`, runs the finite bootstrap task, **always** deletes the input, writes the four DSN parameters and a stable `jwt_secret` as tagged SecureStrings | 3-6 min (Fargate start, Aurora resume) | task ~$0.02/h + DB |
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
an adopted stack and bucket are never deleted, only this run's own template objects are.

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
a failed bootstrap task is forgotten so a rerun starts a new one, a failed migration is forgotten
the same way while an ambiguous launch keeps its retained intent, and finished owners are not
repeated. `status` prints the journal. A second process on the same run is refused by a lock.

## Teardown

Ownership needs **both** the id recorded in this run's journal when its stack created it **and**
the live `deploy-project`/`owner-run` tags. Anything failing either is skipped and listed under
`skipped_not_owned`; pre-existing resources are never candidates. Order, each step journaled:

1. `td-inventory`: tags and presence of everything recorded; writes the ownership map.
2. `td-quiesce`: stop any running task in the project cluster.
3. `td-buckets-emptied`: every version and delete marker (the buckets are versioned) and any
   incomplete multipart upload.
4. `td-images-deleted`: every image in the owned repositories.
5. `td-database`: remove deletion protection, delete the instance, then the cluster. A final
   snapshot `<env>-final` (tagged) is taken unless `--skip-final-snapshot`. This precedes the stack
   because the retained database holds the VPC's subnets.
6. `td-parameters`: owned SecureStrings under `/dc2/<env>/`.
7. `td-stack`: delete the main stack and wait (CloudFront is the long pole).
8. `td-bootstrap-stack`: delete the staging stack (or, if adopted, only this run's templates).
9. `td-retained`: delete the `Retain` buckets, repositories and any owned log groups.
10. `td-receipt`: observe what is left from the services, plus the tagging API.

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

## Known gaps

- Never executed against AWS. Request fields were checked offline against the installed AWS CLI's
  `--generate-cli-skeleton` output (a test does this when `aws` is on the path), not against live
  service behaviour. Expect a first-run surprise or two, and read `status` before rerunning.
- The SPA is not uploaded to the frontend bucket; `SourceCorsOrigin` is set to its URL.
- `schema_revision` and the drain proof need a station that can reach the private database. Without
  one, migrations are verified by exit code only and the close-proof is operator-attested.
- ECS tasks and ECR images carry no tags (the shared task contract has no `tags` field, and images
  are not taggable); the cluster and repositories are tagged and owned.
- A failed run leaves the stack in `ROLLBACK_COMPLETE`; use a new run id and run `teardown` for the
  old one (it deletes the failed stack by ownership).
- One run at a time: the 6-vCPU Fargate quota and the Lambda limit of 10 do not allow overlap.
