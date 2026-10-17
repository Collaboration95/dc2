# V1 live operator receipt — 15 October 2026

Status: account preflight observed; bootstrap attempted and rolled back.
V1 application deployment and #63–#67 acceptance NOT_RUN. *(Superseded: run `r1017b` on 17 October recorded PASS receipts, see [`evidence/cloud-proof-r1017b.json`](evidence/cloud-proof-r1017b.json).)*
This receipt does not close #45 or any genuine cloud acceptance issue.

The user's current execution instruction authorizes scoped DC2 V1 setup,
deployment, small tests and cleanup. It supersedes the historical planning-only
restriction. One operator owns live mutations. The coordinator publishes through
`gh`; implementation workers do not publish or call AWS. There is no elapsed-work
stop rule. Cost and finite-task bounds still apply.

## Identity and scope

- Account: `866865534361`; region: `ap-southeast-1`.
- Verified operator: `arn:aws:iam::866865534361:user/Guruprasath`.
- Explicit CLI profile: `dc2-project2`.
- Resource namespace: `dc2-v1-20261015t1146`.
- STS verified at 2026-10-15T11:51Z and before subsequent batches.
- Namespace-tagged inventory and namespace CloudFormation stack inventory empty.
- No credentials, DSNs, cookies or signed URLs belong in this receipt.

Only new V1 resources are authorized. No NAT, paid endpoints, ALB, EC2, Redis,
Alibaba, Rewind, unrelated account/resource mutation or account-wide billing/security
change. Source fixtures remain private. Capacity evidence uses six long uploads
in total, plus bounded short/stored-source cases. Maximum three encoder tasks,
including ambiguous reservations; no idle service or unattended launcher.

## Observed prerequisites

| Check | Real observation | Consequence |
|---|---|---|
| Fargate on-demand quota | 6 vCPUs | Three 2-vCPU encoders fit; migration/generator must run separately |
| Lambda account quota | 10 concurrent executions; 10 unreserved; zero functions | Any reservation fails. Resolved in the session design: no reserved concurrency; SQS mapping MaximumConcurrency and Gateway throttling bound work (see 2026-10-16 facts) |
| Aurora PostgreSQL 16.6 | `InvalidParameterCombination`: version unavailable | Do not deploy this version |
| Aurora PostgreSQL 16.8 | Two orderable `db.serverless` options; engine advertises minimum 0 ACUs | Supported candidate; deployed pause/network behavior remains unproven |
| Cost Explorer | 14 October UnblendedCost 0, Unit USD, Estimated true | Actual cost-report unit is USD; this does not confirm invoice/payment currency |

[AWS concurrency rules](https://docs.aws.amazon.com/lambda/latest/dg/lambda-concurrency.html)
retain 100 executions for functions without reservations. A closed deployment may
use reserved concurrency zero, but the operator must not silently bypass the
requested bounded-open policy by switching to unreserved concurrency.
[Aurora auto-pause documentation](https://docs.aws.amazon.com/AmazonRDS/latest/AuroraUserGuide/aurora-serverless-v2-auto-pause.html)
describes zero minimum capacity and the 300-second minimum pause delay. Engine
support is not proof that this deployment reaches zero.

## Cost publication before billable creation

Planning envelope: approximately $200. USD is the observed cost-report unit;
invoice/payment currency remains pending. No free tier or credits are assumed.
Rates checked against AWS's current Singapore offer files:

- [Aurora regional price file](https://pricing.us-east-1.amazonaws.com/offers/v1.0/aws/AmazonRDS/current/ap-southeast-1/index.json): standard PostgreSQL Serverless v2 $0.20/ACU-hour.
- [ECS regional price file](https://pricing.us-east-1.amazonaws.com/offers/v1.0/aws/AmazonECS/current/ap-southeast-1/index.json): Linux x86 $0.05056/vCPU-hour and $0.00553/GiB-hour.
- A 2-vCPU/4-GiB task costs $0.12324/hour plus the worksheet's $0.005/hour IPv4 allowance: $0.12824/hour. Image pulling through stop is charged; three tasks cost $0.38472/hour combined.

Existing `cost-model.json` booked-use forecast with reserves is $12.27 for 20
awake hours at average 0.5 ACU. Its two-week never-pauses sensitivity at 0.5 ACU
is $43.87 with reserves. Replacing that compute line with continuous maximum
2 ACUs for 336 hours gives **$144.67** including the same other allowances and
$7 reserve. That sensitivity is not a worst possible bill: traffic, logs,
storage, retries, taxes and extended operation can exceed it.

Initial small trial allowance is **$5**, with DB maximum 2 ACUs, finite worker
batches and at most three encoders. At maximum DB plus three concurrent encoder
tasks the compute/IP rate is approximately $0.78472/hour, before requests,
storage/logs/egress. The allowance requires operator observation and closeout;
it is not a hard AWS budget cap. No account-wide budget changes are authorized.

## Observed account facts, 2026-10-16 (read-only; re-verify before each run)

- Lambda ConcurrentExecutions is 10 total and 10 unreserved. AWS keeps 10 unreserved, so
  **any** reserved concurrency fails. The session design therefore reserves nothing:
  mappings use `ScalingConfig.MaximumConcurrency` (minimum 2) and the HTTP API stage is
  throttled. Close disables mappings and rules and zeroes the stage throttle; it does not
  call `put-function-concurrency`.
- Fargate On-Demand vCPU quota is 6: three encoders of at most 2 vCPU each; migration and
  generator tasks must not overlap them.
- Stack `dc2-v1-20261015t1146-bootstrap` from the previous sprint is present
  (ROLLBACK_COMPLETE, no resources); a new foundation attempt must not reuse its name.
- Budget `flickpond-monthly` is $30/month USD. It is an alert, not a verified cap, and
  is separate from the approximately $200 planning envelope. The never-pauses forecast
  ($43.87) exceeds it; the booked-use forecasts ($12.27 and $14.27) do not.

## Session and release commands

Explicit `--profile`, `--region ap-southeast-1` and `--account` are mandatory (no default
profile). Add `--dry-run` first to print the planned calls. Inputs are the stack outputs
saved to a private file and a nonsecret operator config naming the journal, outputs file
and optional `sql` paths. See `deploy/aws/v1/README.md`.

```sh
python -m scripts.aws.v1.session init --confirm-empty --confirm-exclusive --config ops.json ...
python -m scripts.aws.v1.session open|status|close --config ops.json ...
python -m scripts.aws.v1.session window --config ops.json ...   # API only, for releases
python -m scripts.aws.v1.release promote|restore|status --config ops.json ...
python -m scripts.aws.v1.session dlq --queue MediaResults --dlq-command inspect|status|redrive ...
```

The `dlq` action calls the shared `delivery.dlq` helper (see `dlq-runbook.md`) under the same
explicit-profile identity checks; redrive needs `--confirm-redrive`.

A failed or partial `close` is journaled (`closing`, `session_failures`), keeps every
wake source disabled, and is resumed by running `close` again. It never records a
database pause; Aurora capacity is observed separately and is evidence for #67.

## Reproduction and private state

Run from the selected worktree with its own `PYTHONPATH`:

```sh
PYTHONPATH="$PWD" python -m scripts.aws.v1_operator \
  --profile <profile> --account <12-digit account> --operator-arn <IAM user ARN> \
  --output-dir /absolute/path/to/ignored/private/cache
```

This read-only entrypoint sanitizes all inherited `AWS_*` variables, disables
metadata/configured endpoint overrides, and passes the profile and region on
every CLI invocation. It refuses another identity. Commands have bounded SDK
retries and process timeouts. Raw receipts are mode 0600 and contain metadata,
not credentials. Keep them in ignored private storage, never in Git.

Before each mutation batch, verify STS again. Retain exact rendered template hash,
parameters, change-set ID, image digests, executed commands and resource IDs.
Create infrastructure only from a validated V1 definition. Do not activate
applications before actual owner migrations, image entrypoints, secret loading
and the durable completion path are confirmed. On close, record zero running
encoder/migration/generator tasks, disabled mappings/schedules, application and
authorizer concurrency zero, and actual Aurora capacity observations. Stored data,
images, secrets, snapshots and logs may continue billing. No backup/restore claim.

## Still required

Actual invoice currency, the unverified Gateway-throttle-zero intake gate, valid infrastructure
and image handoffs, deployed TLS/roles/SQL/migrations, workflow, recovery, releases,
latency, pause and final bill reconciliation remain unproven. Keep #45 and
#63–#67 open until their individual acceptance criteria have real receipts.

## Live attempt and known resource state

The represented bootstrap template is `deploy/aws/v1-operator-bootstrap.json`.
It passed Singapore `cfn-lint`. Its CREATE change set contained only two Add
changes: an S3 bucket and a bucket policy. STS was reverified before execution.

- Stack: `dc2-v1-20261015t1146-bootstrap`.
- Stack ARN: `arn:aws:cloudformation:ap-southeast-1:866865534361:stack/dc2-v1-20261015t1146-bootstrap/503c8ca0-c88f-11f1-ba3f-06ffdc7d1997`.
- Change set: `private-template-staging`, ID `433f40ec-848c-4aa3-8c66-bd287f60be93`.
- Result: **ROLLBACK_COMPLETE**. `s3:CreateBucket` received an explicit identity-policy
  deny from `FlickPondRequireMFA`. The staging bucket was not created.
  Later `HeadBucket` returned 404 and the scoped owned-bucket listing was empty.
  CloudFormation retains a `DELETE_SKIPPED` logical record because of Retain;
  this record is not an existing S3 bucket.
- No encoder, migration, generator, database, Lambda or session was launched.
  There is no recurring compute from this attempt. The empty rolled-back stack is
  retained as a failure receipt. V1 foundation execution did not begin.
- The IAM user's MFA-device metadata returned an empty list. No MFA enrollment,
  IAM-policy edit or other security-setting change was performed.

The newly authorized request for Lambda ConcurrentExecutions=200 was attempted
with service code `lambda`, quota `L-B99A9384`. AWS rejected it with
`IllegalArgumentException`: desired value must exceed the published default
1000. No quota request ID exists, and the applied quota remains 10. A larger
quota was not requested. Do not claim a pending or approved increase.

`python -m scripts.aws.v1_foundation` implements prepare/observe/execute for the
initial foundation only. It verifies identity before mutations, requires a cost
receipt, checks closed application conditions and 0..2 ACU limits, stages oversized
templates only in the exact project artifact bucket, records hashes/change-set
IDs, and permits initial Add changes only. It does not open sessions. The current
C1 foundation snapshot passed its local guard and `cfn-lint`, but the demonstrated
account denial prevents live provisioning. No successful-cloud claim follows
from these local checks.
