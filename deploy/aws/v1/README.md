# DC2 V1 infrastructure

This directory is V1. Historical `deploy/aws/environment.json` and
`scripts/aws/definitions.py` remain unchanged AWS2 preparation.

Render offline from the repository root:

```sh
PYTHONPATH="$PWD" python -m scripts.aws.v1.config \
  --config deploy/aws/v1/config.example.json --output-dir .cache/v1-render
cfn-lint .cache/v1-render/template.json --regions ap-southeast-1
PYTHONPATH="$PWD" python -m pytest tests/aws/v1/test_infrastructure.py -q
```

The example contains dummy account references and creates no resources. Copy it
to an ignored private config, set the explicitly authorized account/environment,
and retain only SSM **ARN references**. Never put credentials or DSN values in
render config, templates, parameters, source control or public evidence. The
renderer rejects secret-bearing fields, shared DB parameters, cross-account
images/references and mutable image tags. It neither imports an SDK nor discovers
credentials. `config.schema.json` documents the public input shape; Python adds
cross-field/account ownership validation.

## Operator deployment sequence

Only the assigned AWS operator applies resources. This helper's checks make zero
AWS calls. Use the dedicated project profile, explicit Singapore region and the
verified account; do not run inherited AWS2 deploy paths.

1. Review current regional engine orderability, service quotas and cost inputs.
   Default PostgreSQL **16.8** comes from the operator's actual Singapore inventory;
   16.6 was unavailable. Verify minimum-zero Serverless v2 support at apply time.
2. Provision foundation with `deploy_applications=false`. There is no `session_open`
   input: the template is always closed-safe (see "Concurrency and session model").
   Set all five future SSM parameter ARNs to distinct project paths; their secret
   values are not needed for this phase. The generated template is larger than
   CloudFormation's inline 51,200-byte limit: use the operator's private encrypted
   template-staging bucket, not a public URL. CloudFormation requires IAM capability
   when applications are enabled. Preserve the full original parameters on updates.
3. Read foundation outputs. Upload the existing built frontend to its private
   bucket. Set `source_cors_origin` to the generated `FrontendUrl` (a provisional
   `https://example.invalid` deliberately grants no useful browser origin before
   this update). Keep the root frontend appearance unchanged.
4. Bootstrap the two logical DBs and role grants with the separate private bootstrap
   procedure below; publish four owner-specific DSNs and JWT key as private SSM
   SecureStrings under exactly the configured paths. Use AWS-managed SSM encryption;
   a custom CMK requires a separately scoped KMS policy change. Only the bootstrap
   operator may obtain Aurora's generated master secret. No runtime role can.
5. Build/scan/push distinct Media, Processing and worker images to the emitted
   immutable ECR repositories using C2's release tooling. Include the verified RDS
   CA at `/opt/rds/global-bundle.pem`. Configure all three digest-pinned image URIs
   and `deploy_applications=true`, keeping the session closed. Images are explicit
   parameters; the stack never deploys an arbitrary dummy/placeholder image.
6. Run each owner's migration task in public task subnets with a temporary public
   IPv4 address and the migration SG. Use its own migration DSN only. Check real
   negative cross-database/DDL tests before intake. Migration tasks must complete
   before encoder batches: the observed Fargate quota was only six vCPUs.
7. Open only through the session API (`python -m scripts.aws.v1.session open ...`)
   after readiness and quotas pass. The template deploys every function with reserved
   concurrency 0, both mappings and all four rules disabled, and Gateway throttle 0.
   See "Concurrency and session model" for how the account limit of 10 is handled.

No ECS service, autoscaler or automatic worker starts exist. `WorkerTaskDefinitionArn`
is one finite 2-vCPU/4-GiB task; Lead C's inventory/journal gate enforces cap three,
including unresolved launches. `DC2_WORKER_CAP=3` is documentary process input,
not an ECS-enforced quota. The worker command must receive an absolute
`--deadline-epoch` and unique `--name` from the launcher before RunTask. Late work
remains queued until another explicitly authorized operator batch.

## Concurrency and session model

Observed account facts, read-only check, **2026-10-16** (re-verify before each run):

- Lambda `ConcurrentExecutions` is **10** total and 10 unreserved. AWS requires the
  account to keep 10 unreserved, so **any** reserved concurrency fails.
- Fargate On-Demand vCPU quota is **6**: three encoders of at most 2 vCPU each.
- Stack `dc2-v1-20261015t1146-bootstrap` from the previous sprint (rolled back) exists.
- Budget `flickpond-monthly` is **$30/month USD**; the planning envelope in
  `docs/execution/aws/v1/cost-model.json` is separate and larger. A budget is an alert,
  not proof of a spend cap.

The model therefore uses **no Lambda reserved concurrency anywhere**, and close does
not depend on `put-function-concurrency`:

| Control | Template (closed-safe default) | Session open | Session close |
|---|---|---|---|
| Function reserved concurrency | none | none (config `zero_reservation: "off"`) | none |
| SQS consumers | mappings `Enabled: false`, `MaximumConcurrency: 2` (the SQS minimum) | enabled | disabled |
| Repair/event rules | `DISABLED` | enabled | disabled |
| Gateway stage throttle | rate 0 / burst 0 | configured open limits | `0` / `0` |

Open work is bounded by the account limit of 10, the two mappings' `MaximumConcurrency`
and the Gateway throttle. There is **one runtime authority**: the session API
(`python -m scripts.aws.v1.session`). The earlier `SessionOpen`/`Open` template condition
is removed so a stack update cannot contradict an operator-opened session. A stack update
that changes a mapping, rule or stage may re-apply the closed defaults; run
`session status` afterward and re-open if it reports drift. Gateway throttle zero as an
intake gate is an unverified live behavior (#63), and it is the only intake gate here:
verify it with a real request while closed before relying on it. Accounts with a larger
quota may opt into explicit reservations (`reservations` in the operator config and
`zero_reservation: "required"`); the session then preflights the unreserved pool first.

Operator CLIs (all need `--profile`, `--region ap-southeast-1` and `--account`; there is
no default profile; `--dry-run` prints the planned calls with no AWS access):

```sh
python -m scripts.aws.v1.session init|open|window|close|batch|status --config <ops.json> ...
python -m scripts.aws.v1.release promote|restore|status --config <ops.json> ...
```

`window` serves only the public API (consumers, rules and workers stay disabled) so a
release can be smoke-tested through the Gateway; end it with `close`.

## Interfaces and permissions

Two explicit HTTP API payload-v2 integrations own `/api/media/*` and
`/api/processing/*`. The Media authorizer has TTL zero and supplies canonical
`dc2-gateway-v1` actor context. Only health and Media POST register/login/logout
bypass auth. Lambda resource policies permit only the specific API/authorizer
integration. All functions have separate scoped roles and log groups. Each domain
artifact includes its own API/control/repair functions and initial `live` aliases;
C2 releases promote the full owning function map independently.

Handler defaults are `media.lambda_handler.handler` / `.authorizer`,
`processing.lambda_handler.handler`, `processing.handlers.command_handler`,
`media.handlers.result_handler` / `.repair_handler`, and
`processing.handlers.repair_handler` / `.ecs_handler` / `.s3_handler`. Override
handler names explicitly through `handlers` only when updating the artifact contract.

`MEDIA_POSTGRES_DSN_PARAMETER_ARN` / `PROCESSING_POSTGRES_DSN_PARAMETER_ARN`
and `MEDIA_JWT_SECRET_PARAMETER_ARN` are runtime-support loader references.
Storage uses existing `*_MINIO_ENDPOINT`, `*_MINIO_USE_SSL`, `*_MINIO_REGION`,
`*_MINIO_OUTPUT_BUCKET`, `MEDIA_MINIO_SOURCE_BUCKET` names; credential mode is
`lambda` for handlers and `ecs` for tasks. No access keys or peer DSNs are injected.
SQL trust is `MEDIA_POSTGRES_SSL_CA` for Media and `PROCESSING_DATABASE_TLS=true` plus
`PROCESSING_DATABASE_CA_FILE` for Processing, both `/opt/rds/global-bundle.pem` (each owner's
Settings class reads a different name and ignores unknown ones, so
`tests/v1/test_rendered_runtime_environment.py` loads every rendered environment into its
Settings); handlers set
`*_RUNTIME_MODE=lambda`. The corresponding runtime loader must dispose invocation
connections so Aurora can pause; infrastructure alone cannot establish that.

Three Standard queues have seven-day retention, 20-second long polls and matching
14-day DLQs. Commands and results have Lambda batch-partial mappings; work is
consumed directly by finite Fargate tasks, so it has **no Lambda mapping**. Only
Media repair publishes commands; only Processing command/repair/ECS handlers
publish work/results after durable owned outboxes commit. Public APIs and workers
cannot SQS-send. Workers may GET source versions and PUT outputs, never mutate
source objects or read Media DB parameters. Explicit queue denies also constrain
producers/consumers. The repair tick runs each minute during open sessions; ECS
terminal and output-created events are bounded recovery hints. Closed sessions
disable all four rules and both mappings; the session API controls concurrency and drain.

Private dual-stack Lambda/DB subnets span two AZs. Lambda SDK traffic uses
`AWS_USE_DUALSTACK_ENDPOINT=true` and IPv6 egress-only routing. Private subnets
have no IPv4 default route; the free S3 gateway provides the only IPv4 HTTPS route.
Public worker/migration tasks use transient IPv4 to pull images/retrieve secrets,
plus narrow SG-to-SG private PostgreSQL access. There is no NAT, paid endpoint,
ALB, Redis, nginx, EC2 application host or Batch dependency. S3 gateway policy allows
the two data buckets and read-only ECR image layers in the regional starport bucket;
frontend uses CloudFront OAC. The endpoint policy includes required principals.
The ECR-layer permission follows [AWS ECR documentation](https://docs.aws.amazon.com/AmazonECR/latest/userguide/vpc-endpoints.html#ecr-setting-up-s3-gateway)
and grants no runtime identity access to unrelated buckets. Buckets are private,
TLS-only, encrypted, versioned and retained. Sources support POST CORS only for
the exact generated frontend HTTPS origin; output GET/HEAD CORS supports playback.
CloudFront forwards `/api/*` to HTTPS Gateway, forwards cookies/query/authorization,
excludes the viewer Host header and disables API caching.

## Required live proof (not passed by local tests)

- Verify two-AZ IPv6 Lambda SSM/SQS/ECS DNS/connectivity and S3 gateway traffic,
  native rotating credentials and verified database TLS; no unexpected IPv4 path.
- Bootstrap/migrate both owners and demonstrate cross-DB, runtime-DDL and
  source-write denials, queue injection/consume denials and authorizer spoof denial.
- Demonstrate direct POST constraints, checksum/version adoption, exact-origin CORS,
  cookie roundtrip through CloudFront HTTPS and independent CLI normal TLS trust.
- Verify real partial batches, duplicate/reordered delivery, bounded repair,
  120s lost-work / 300s interrupted recovery and late-output cleanup.
- Prove finite task/watchdog exit and cap-three unresolved-launch accounting.
- Release one owner independently and exercise failed-candidate rollback.
- Close/drain, observe all function reservations at zero, both mappings/four rules
  disabled, no running tasks, then measure actual Aurora zero ACUs after five
  connection-free minutes. Maintenance can wake Aurora; storage/CDN can still bill.
- Retain actual cost/close receipts. Local render/policy/lint checks are not cloud,
  IAM, pause, latency, recovery or throughput evidence. #45/#63–#67 remain open.

## Private database bootstrap

The separately emitted `BootstrapTaskDefinitionArn` is a finite (180-second
application deadline), 0.25-vCPU/512-MiB operator task using the worker image.
C2 must copy the standalone `scripts/aws/v1/bootstrap.py` to
`/opt/db-bootstrap.py` in that image. It does not import either domain, an AWS SDK,
or runtime credentials. Its task role has no permissions; its execution role
reads only the temporary exact SSM path `/dc2/<EnvironmentId>/bootstrap-input`,
pulls only the worker repository and writes the task log stream. Neither owner
migration task nor any runtime role can read that path or Aurora's master secret.

The operator privately constructs a JSON object with exactly `host`, `port`,
`user`, `password`, and `role_passwords`. `host` is `DatabaseEndpoint`; `port` is
5432; `user` is `dc2bootstrap`; the password comes from the generated managed
`BootstrapSecretArn`. `role_passwords` has exactly four distinct, randomly
generated values of at least 24 characters, keyed by `media_migrator`,
`media_runtime`, `processing_migrator`, `processing_runtime`. No example credential
value is supplied. Store the complete object as a temporary SecureString at the
bootstrap path through the operator's private tooling; never use a command-line
JSON literal, public receipt or task definition environment value. ECS secret
injection provides `DC2_BOOTSTRAP_INPUT_JSON` to the process. The script immediately
removes it from its inherited environment and prints only a safe result.

Run this task in one public task subnet with `MigrationSecurityGroupId`, temporary
public IPv4, the emitted cluster and no concurrent encoders. It requires the
normal verified RDS CA and exits nonzero on failures without printing SQL/DSNs.
It creates `media_db` owned by `media_owner` and `processing_db` owned by
`processing_owner`. Owners cannot log in. Migrators inherit only their own owner;
runtimes receive CONNECT, schema USAGE and DML/sequence grants, without schema
CREATE, database CREATE or peer access. Both existing and future migration-created
tables receive runtime grants. Existing databases with unexpected owners are
rejected before any credential mutation. Re-running reconciles grants and resets
only the four project role passwords to the supplied values; coordinate a closed
session and the matching SSM DSN update when deliberately rotating them.

After success, the operator builds separate percent-encoded asyncpg DSNs for each
role/own DB and writes only its corresponding configured SecureString. Include
verified TLS, and retain the CA image path described above. Remove the temporary
bootstrap input after those four parameters are durable; do not remove the
RDS-managed master secret. Run owner migrations afterward. A workstation already
inside the private network may instead use a mode-0600 private input file:

```sh
DC2_BOOTSTRAP_INPUT_FILE=/private/operator/db-bootstrap.json \
  python -m scripts.aws.v1.bootstrap --ca-file /private/operator/global-bundle.pem
```

Do not set both private input methods. Bootstrap role/schema reconciliation is
covered by fake-connection tests; real RDS ownership, migrations, TLS, IAM and
connection pause still require operator evidence. The current operator reported
an explicit `FlickPondRequireMFA` policy denial on S3 bucket creation and no enrolled
MFA device. The helper does not modify account security or bypass that denial.
Foundation deployment did not complete; the empty staging rollback stack is
operator-owned known state, not a successful V1 deployment.
