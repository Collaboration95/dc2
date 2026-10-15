# V1 live operator receipt — 15 October 2026

Status: account preflight observed; deployment and #63–#67 NOT_RUN.
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
| Lambda account quota | 10 concurrent executions; 10 unreserved; zero functions | Positive per-function reservations conflict with AWS's 100-unit unreserved pool; session opening pending correction |
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

## Reproduction and private state

Run from the selected worktree with its own `PYTHONPATH`:

```sh
PYTHONPATH="$PWD" python -m scripts.aws.v1_operator \
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

Actual invoice currency, usable bounded Lambda reservations, valid infrastructure
and image handoffs, deployed TLS/roles/SQL/migrations, workflow, recovery, releases,
latency, pause and final bill reconciliation remain unproven. Keep #45 and
#63–#67 open until their individual acceptance criteria have real receipts.
