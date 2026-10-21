# Architecture decisions, deviations and limitations (V1 as built)

Backs report sections 3.1 to 3.4 and slides 3 and 4. Closes #188 together with
[views.md](views.md). The domain model is in [ddd.md](ddd.md).

Evidence labels used throughout:

| Label | Meaning |
|---|---|
| **[AWS]** | Recorded in a live receipt: [`cloud-proof-r1017b.json`](../execution/aws/v1/evidence/cloud-proof-r1017b.json) (run `r1017b`, 2026-10-17, ap-southeast-1), [`cloud-proof-r1017bmedia.json`](../execution/aws/v1/evidence/cloud-proof-r1017bmedia.json), or, from 18 October, [`cloud-proof-r1018b.json`](../execution/aws/v1/evidence/cloud-proof-r1018b.json) and [`cloud-proof-r1018bmedia.json`](../execution/aws/v1/evidence/cloud-proof-r1018bmedia.json) (run `r1018b`). Both stacks have been torn down. Results against targets: [`docs/evidence-index.md`](../evidence-index.md). |
| **[Local]** | Tests on real PostgreSQL 16 and FFmpeg with Moto for S3/SQS and an in-process Gateway bridge. Not AWS: it does not exercise IAM, Gateway, Lambda, Fargate or Aurora. |
| **[Code]** | Read from source or from the rendered CloudFormation template (`scripts/aws/v1/definitions.py`; the checked-in `deploy/aws/v1/template.json` is identical to its output). No runtime evidence. |
| **[NOT_RUN]** | Implemented, never run against AWS. |

## 1. Register

Status values: **Kept** (as proposed), **Changed** (same intent, different mechanism),
**Superseded by AD-xx**, **New**.

| ID | Decision | Status | One-line reason |
|---|---|---|---|
| AD-01 | Extract Processing as the only new business service | Kept | Two services survive; Identity and Delivery stay inside Media (see [ddd.md](ddd.md) section 3) |
| AD-02 | Database per service on one PostgreSQL server | Kept (hosting changed, see AD-12; one cluster per service since AD-29) | Two databases, separate roles; cross-database access refused on AWS |
| AD-03 | Synchronous submit, asynchronous processing on Redis/RQ | Superseded by AD-11 | Submit became an asynchronous command; Redis/RQ left the V1 runtime |
| AD-04 | Idempotent SubmitJob plus reconciliation, no outbox | Changed (AD-11) | Idempotency and reconciliation kept; a transactional outbox was adopted up front |
| AD-05 | Presigned URLs for source reads and output delivery | Changed (AD-14, AD-20) | Output and uploads stay presigned; workers read the source with an IAM grant on a pinned version |
| AD-06 | Service token plus forwarded owner identity on a private network | Superseded by AD-09 and AD-20 | Gateway-trusted identity and queue policies replaced the token |
| AD-07 | Host on AWS using containers in one small environment | Changed (AD-10, AD-12, AD-13, AD-15, AD-23) | Managed serverless services; only the encoder and migration run as containers on Fargate |
| AD-08 | Fresh demonstration data | Kept | No Project 1 data migration exists; the deploy pipeline seeds one smoke account |
| AD-09 | API Gateway HTTP API with a Media-owned Lambda authorizer | New | One public entry; Processing trusts identity without holding Media's secret or database |
| AD-10 | Domain APIs and control handlers as Lambda container images, one image per domain | New | Scale-to-zero compute and a per-domain release unit |
| AD-11 | SQS queues with SQL outbox and inbox in place of Redis/RQ and synchronous SubmitJob | New | No always-on broker; failure isolation between the two contexts |
| AD-12 | Aurora Serverless v2: one cluster, two logical databases, separate roles | New (refines AD-02) | Pauses to zero when idle; ownership enforced by roles |
| AD-13 | Finite Fargate encoders, cap 3, zero idle, operator-started batches | New | Bounded cost and quota; no autoscaling |
| AD-14 | Direct-to-S3 intake with presigned reservations and pinned versions | New | No video bytes through Gateway or Lambda; the stored bytes are what was verified |
| AD-15 | CloudFront as the single public entry for frontend and API | New | Managed HTTPS with no purchased domain |
| AD-16 | Per-owner release and rollback by image digest and Lambda alias | New | Release Processing without touching Media |
| AD-17 | GitHub Actions CD over OIDC | New | Recorded, repeatable deploy with no stored AWS key |
| AD-18 | Private Lambda subnets, IPv6 egress-only, S3 gateway endpoint, no NAT | New | Avoids NAT and interface-endpoint charges |
| AD-19 | Closed-by-default stack operated as booked sessions | New | Idle spend near zero; intake and consumers gated by the operator |
| AD-20 | Least-privilege IAM per handler, native credentials, queue resource policies | New (supersedes AD-06) | Producer and consumer authority enforced by AWS, not by message schema |
| AD-21 | Media-owned projection of Processing state, fenced by `state_version` | New | Media never reads Processing's database |
| AD-22 | Opt-in V2 experiments live in the same template, off by default | New | Keeps experiments revertible and the V1 template unchanged |
| AD-23 | One CloudFormation stack, applied in two phases | New | Smallest operational surface for a three-person team |
| AD-24 | `contracts/` as published language and shared kernel, with an N / N-1 versioning policy | New | Either service can be released first for additive changes |
| AD-25 | Per-service alarms and one services dashboard | New | Failures are attributable to one service |
| AD-26 | Retired peer-HTTP and Redis/RQ code quarantined in `legacy/`, kept out of V1 images | New | The submission shows no dead dependency between the services |
| AD-27 | One persistent always-on environment, updated in place, scaling to zero | New (supersedes AD-19) | Per-run stacks cost a full deploy and teardown per check; the stack already costs about USD 3-5 a month idle |
| AD-28 | Release admission rescans the replaced rollback image and records, rather than blocks on, fixable findings published after it shipped | New (21 October) | A candidate that remediates a new advisory must be able to replace the vulnerable image it fixes |
| AD-29 | Media and Processing each have their own Aurora Serverless v2 cluster, split in place from the shared one | New (21 October) | One cluster was a shared failure and capacity boundary that role separation did not remove (AISS-01) |

## 2. Decisions carried from the proposal

Each row compares the proposal's text (`Team17-Proposal.docx`, section 2.4) with the code.

| ID | Proposal said | As built | Evidence |
|---|---|---|---|
| AD-01 Kept | Processing is the only new service; keep the modular monolith otherwise; four services would be too many | Two business services, separate images, roles and release units. The Media authorizer is Media code, not a third service. The microservices audit (#195) found it "mostly real". Hardening since merged: the peer-HTTP and RQ code moved to `legacy/` and `deploy/v1/check_runtime.py` fails an image build if any legacy module is importable (AD-26), per-service CI lanes with CODEOWNERS (#204), a contract versioning policy (AD-24), alarms and a dashboard (AD-25), and a failure-isolation proof harness (#196, see AD-11). | [Code] `definitions.py`, `deploy/v1/check_runtime.py` (the opposite domain package must be absent from each image); [AWS] `cross-database`, `promote-good` with `peer_unchanged` |
| AD-02 Kept | Separate databases, roles and migration histories on one server | `media_db` and `processing_db`, one Aurora cluster each since AD-29 (V1 shipped both on one). Roles `*_runtime` (DML only), `*_migrator` (DDL), `*_owner` (no login). Each migration history is separate (`media/migrations`, `processing/migrations`). | [AWS] #63 `cross-database`: other database refused (`InsufficientPrivilegeError`), runtime DDL refused; [Code] `scripts/aws/v1/bootstrap.py` |
| AD-03 Superseded by AD-11 | REST creates the job, RQ drives the work, keep Redis/RQ | No Redis or RQ in the V1 images or template. Submit is a queued command. | [Code] `deploy/v1/*.Dockerfile`, `definitions.py`; [Local] `make verify-v1` |
| AD-04 Changed | Idempotent on `asset_id`, reconciliation task, outbox only if experiments require it | Idempotency kept (`SubmissionGuard`, unique `asset_id`). Reconciliation kept as `repair_work` and lease expiry. The outbox was adopted from the start because the handoff became SQL plus SQS. | [Local] `tests/v1/test_messaging_sql.py`; [Code] `processing/recovery_v1.py` |
| AD-05 Changed | Presigned URLs for source reads and outputs so workers hold no Media storage credentials | Upload: presigned POST. Output: presigned GET signed at read time. Source read by the worker: IAM `GetObject` on the source bucket, bound in code to the pinned VersionId and owner. This is broader than a signed URL; the plan says so. | [Code] `media/services/storage.py`, `definitions.py` (`Worker` role); `architecture-plan.md` ("broadens today's signed-only capability") |
| AD-06 Superseded by AD-09, AD-20 | Service token and forwarded owner on a private network; mutual TLS rejected | No service token on the V1 path. The authorizer's context is the only identity input, and queues are restricted by role. (`processing/auth.py:require_service_token` is still in the Processing package, unused by the V1 API.) | [AWS] `forged-identity`, `sqs-direct-send` |
| AD-07 Changed | Containers on AWS, one small environment, services chosen in week 1 | Lambda, API Gateway, SQS, Aurora Serverless v2, S3, CloudFront; Fargate only for the encoder, migrations and the bootstrap task. One environment per run id. | [Code] `definitions.py`; [AWS] whole receipt |
| AD-08 Kept | Fresh demonstration data | No migration path from Project 1. `deploy.py --seed-email` creates the smoke account. | [Code] `deploy-runbook.md` |

## 3. New decisions

### AD-09 API Gateway HTTP API with a Media-owned Lambda authorizer

- **Context.** The platform needs one public entry with two visible route groups, and Processing
  must trust the caller's identity without holding Media's database or JWT secret.
- **Decision.** One HTTP API. Routes `ANY /api/media/{proxy+}`, `/api/media`, and the same for
  Processing use a REQUEST authorizer (simple response, result cache TTL 0, identity source the
  `Cookie` header). Public routes: both `/health` routes and Media `register`, `login`, `logout`.
  `MediaAuthorizer` verifies the HS256 JWT cookie and reads the **current** user row, then returns
  `{schema_version, integration, owner_id, role}`. The adapter drops `x-owner-id`, `x-role` and
  `cookie` headers and builds the actor only from that context. Both integrations have a Lambda
  resource policy limited to this API.
- **Alternatives.** A managed identity provider or JWT authorizer (the plan rules out OIDC and a
  new provider); each service verifying the cookie itself (Processing would need the JWT secret and
  a Media lookup); the proposal's shared service token (AD-06).
- **Trade-off.** TTL 0 means a database read per request, which also wakes a paused Aurora, but a
  deleted user or changed role takes effect at once. Media's own `current_user` repeats the token
  and row check, so authenticated Media calls read `users` twice. The contract allows a `viewer`
  role that nothing issues.
- **Evidence.** [AWS] `anonymous-denied` (401 on all six frontend and Gateway job routes),
  `forged-identity` (forged headers change nothing; non-operator gets 403 on admin), `session-roundtrip`
  (cookie host-only, HttpOnly, Secure, SameSite=Strict). [Local] `tests/v1/test_gateway.py`,
  `tests/v1/test_contract_fixtures.py`. [Code] `definitions.py` (`GatewayAuthorizer`, routes),
  `media/authorizer.py`, `contracts/gateway.py`.

### AD-10 Lambda container images, one image per domain

- **Context.** Scale-to-zero compute that still lets each domain be released alone.
- **Decision.** Nine functions with `PackageType: Image`. Media image: `MediaApi` (2048 MB, 60 s),
  `MediaAuthorizer` (512 MB, 10 s), `MediaResults`, `MediaRepair`. Processing image: `ProcessingApi`
  (2048 MB), `ProcessingCommands`, `ProcessingRepair`, `ProcessingEcsEvents`, `ProcessingS3Events`.
  `ImageConfig.Command` picks the handler; every function has a `live` alias. FastAPI code runs
  unchanged behind `GatewayAdapter`. Connections are per invocation (`NullPool`, disposed in
  `finally`) so a paused database can stay paused. ECR repositories use immutable tags and scan on push.
- **Alternatives.** Containers behind an ALB (no ALB, NAT, EC2 or nginx is selected in the plan); one
  function per endpoint (the plan forbids "one application per CRUD endpoint").
- **Trade-off.** Cold starts and VPC attachment; no pooled connections; the Gateway integration
  timeout is 29 s; the account's observed Lambda concurrency limit is 10, which shaped AD-19.
- **Evidence.** [AWS] `status` route: 9,000 requests over 180 s from a Fargate generator in the same
  region, p90 58 ms, 0 errors; login 20 users p90 178 ms; first read after a database wake 4.7 s;
  `/api/processing/health` p99 1.49 s (cold-start outlier). [Code] `deploy/v1/media.Dockerfile`,
  `processing.Dockerfile`, `definitions.py`, `media/database.py:invocation_session`.

### AD-11 SQS with SQL outbox and inbox (replaces Redis/RQ and synchronous SubmitJob)

- **Context.** Redis needs an always-on node, and a synchronous Media-to-Processing call couples the
  two services' availability.
- **Decision.** Three Standard queues, each with a DLQ: `processing-commands`, `processing-work`,
  `media-results` (retention 7 days, DLQ 14 days, long poll 20 s, visibility 420 s, redrive after 5
  receives, SQS-managed encryption, TLS-only). SQL stays authoritative. State and message commit
  together (outbox), consumers commit inbox and state before returning, and delivery is
  at-least-once with dedupe on `message_id` plus a body hash. Lost work is rebuilt from SQL by a
  repair tick; ECS `STOPPED` and S3 `Object Created` events are hints that run the same pass.
- **Alternatives recorded.** Keep Redis/RQ with REST (proposal AD-03); a new event broker (the
  proposal judged it extra operations); the plan's rule "SQL/SQS dual writes still require repair"
  rules out sending from the API request. Whether SQS FIFO, SNS or Step Functions were evaluated is
  not recorded in the repository.
- **Trade-off.** The SQL-to-SQS handoff is not atomic, so repair is part of the design. The Media API
  role has no SQS permission: `submit` is published by `MediaRepair` on its one-minute schedule, so
  intake-to-queue latency is up to about a minute and needs an open session. Standard queues are
  unordered, so `state_version` fences stale results. Duplicates are normal.
- **Evidence.** [Local] `tests/v1/test_messaging_sql.py`, `test_delivery.py`, `test_dlq.py`.
  [AWS] `sqs-direct-send` (403 on all three queues), `dlq` (poison message dead-lettered after 2101 s
  and removed), `recovery` (stopped encoder noticed in 5.8 s; gate 300 s). The 120 s lost-queue-entry
  gate is encoded in `processing/messaging.py:REPAIR_INTERVAL_SECONDS`; no AWS receipt exercises a
  lost queue entry. Failure isolation (Media accepts and holds an upload while the
  `ProcessingCommands` consumer is off, then Processing catches up) has a harness,
  `python -m scripts.aws.v1.evidence isolation` (`scripts/aws/v1/proof/isolation.py`, #196), tested
  against the simulated account. [AWS] `r1018b` `processing-down`: command consumer off 48 s, Media
  answered 202, the command was held, and the job reached `done` 58.9 s after re-enable (first attempt
  failed on a harness bug, rerun passed). Consumer only: the Processing API stayed up.

### AD-12 Aurora Serverless v2: one cluster, two logical databases, separate roles

- **Context.** Two owned databases, near-zero idle cost, small team.
- **Decision.** One cluster and one instance (`db.serverless`), PostgreSQL 16.8, min 0 ACU, max 2 ACU,
  auto-pause after 300 s, storage encrypted, `rds.force_ssl=1`, 1-day backups, deletion protection,
  cluster/instance/buckets/ECR retained on stack delete. A one-off bootstrap task creates `media_db`
  and `processing_db`, revokes `PUBLIC`, and creates per-domain `owner`, `migrator`, `runtime`
  roles. Four login DSNs are SSM SecureStrings; each handler role can read only its own domain's.
  The RDS-managed master secret is reachable only by the bootstrap operator.
- **Alternatives.** One cluster per domain: rendered by an option in `definitions.py`, [NOT_RUN]
  in the cloud (#94). RDS Data API, DSQL, DynamoDB: V2 backlog, each needing a compatibility spike.
  Other engines are not recorded as evaluated.
- **Trade-off.** The cluster is a shared capacity and failure boundary (section 6). A request to
  either domain resumes it. Single instance, so no replica failover.
- **Evidence.** [AWS] `cross-database`, `cold-wake` (paused before; first read 4.7 s, later reads
  263 ms), `pause` (max 0.5 ACU after close, zero 6.0 min later, no wake-ups). [Code]
  `definitions.py` (`DatabaseCluster`), `scripts/aws/v1/bootstrap.py`.

### AD-13 Finite Fargate encoders, cap 3, zero idle, operator-started batches

- **Context.** FFmpeg needs minutes of CPU, the account's observed Fargate On-Demand quota is 6 vCPU
  (2026-10-16), and nothing should run while idle.
- **Decision.** An ECS cluster with no service. One task definition: 2 vCPU, 4 GiB, X86_64. The
  operator CLI (`session batch`) starts 1 to 3 tasks with an absolute deadline (at most 3600 s) and a
  unique name. A task claims at most one attempt, exits after two empty 20 s polls (or 25 handled
  messages), renews SQS visibility and its SQL lease together, and has no permission to send
  messages. The cap of 3 counts unresolved launches and is enforced by the operator journal, not by
  ECS (`DC2_WORKER_CAP` is documentary). Work arriving later stays queued until another batch.
- **Alternatives.** An ECS service with autoscaling (always-on cost; the proposal also put
  autoscaling out of scope); AWS Batch (not a V1 dependency); Lambda for short encodes (#93) and a
  launcher Lambda for unattended starts (#68), both opt-in. #68 ran on AWS in `r1018b` (see below); #93 is [NOT_RUN].
- **Trade-off.** No autoscaling; at most three concurrent encodes; submissions are not processed
  until someone starts a batch, so a Publisher job on its own would sit queued.
- **Evidence.** [AWS] `run-1/2/3`: 1, 2, 3 encoders running together (peak concurrency read from task
  stamps), each processing one 36,035,343-byte fixture, all `done`; median time to terminal 153.9,
  180.3, 145.8 s; none left running; billed 138 to 193 s per encoder. This shows concurrency up to the
  cap, not a jobs-per-minute speedup ratio. [Code] `scripts/aws/v1/session.py:batch`,
  `processing/worker/V1.md`, `processing/worker/sqs.py`.

### AD-14 Direct-to-S3 intake with presigned reservations and pinned versions

- **Context.** No 100 MiB video body should pass through Gateway or Lambda, and the bytes that were
  checked must be the bytes that get encoded.
- **Decision.** `POST /uploads/reservations` (request id, filename, type, size, SHA-256) returns a
  15-minute presigned POST whose policy fixes the key, content type and a length range. The client
  uploads straight to the source bucket (no cookie). `finalize` reads the object's size, SHA-256 and
  magic bytes at an explicit VersionId, then in one transaction pins the version, creates the Asset
  and stages the `submit` command. Expired grants are rescanned for late writes with backoff and then
  retired; staged copies from failed edits are collected.
- **Alternatives.** Upload through the API (the plan forbids it); the legacy multipart route is not
  mounted in the V1 app.
- **Trade-off.** Two-step protocol; the client must hash the file before reserving (the browser reads
  it into memory); the source bucket must be versioned, which keeps old versions until cleaned;
  cleanup is a standing background duty.
- **Evidence.** [AWS] `direct-upload-e2e` (828,699-byte clip: reserve 299 ms, upload 272 ms, finalize
  526 ms, `done` 75.6 s after accept, driven against the CloudFront URL), `cors-preflight` (S3
  allows the frontend origin, refuses a foreign origin). [Local] `tests/v1/test_direct_intake_s3.py`
  (Moto does not enforce POST policy signatures, so that part is only proven on AWS). [Code]
  `media/services/direct_intake.py`, migration `media_0007`.

### AD-15 CloudFront as the single public entry

- **Context.** HTTPS without a purchased domain, one origin for cookies, no EC2/nginx.
- **Decision.** One distribution (PriceClass_200, HTTP/2 and 3, IPv6). Default behaviour serves the
  private frontend bucket through origin access control. `/api/*` goes to the API Gateway
  `execute-api` host over HTTPS only (TLS 1.2), with AWS managed cache and origin-request policies referenced by id
  (`4135ea2d...` caching disabled, `b689b0a8...` all viewer values except Host). AWS-generated hostnames and certificates are used.
- **Alternatives.** A CloudFront to public EC2 HTTP origin (the earlier plan; #46 closed it); ALB;
  a custom domain (needs purchase, not selected).
- **Trade-off.** Hostnames are AWS-generated. Playback bytes do not flow through CloudFront: output
  and segments come from S3 by presigned URL. The Gateway endpoint is also publicly reachable
  without CloudFront (section 6).
- **Evidence.** [AWS] `session-roundtrip` (`through_cloudfront`), `direct-upload-e2e`
  (`storage_host_is_s3`, segment 307 to S3, range requests 206, playlist not cached). [Code]
  `definitions.py` (`Distribution`).

### AD-16 Per-owner release and rollback

- **Context.** The proposal's UC-7: release Processing alone, smoke-test it, roll back.
- **Decision.** A release moves one owner's functions together: build and scan that owner's image,
  publish a Lambda version per function, move each `live` alias, smoke, and restore the previous
  versions if smoke or the gate fails. Worker image changes move the Processing worker task
  definition. A journal makes it resumable and blocks a session while a release is pending.
  Schema rollback is never attempted; the operator attests that old and new images both work with the
  additive schema head.
- **Alternatives.** Updating the whole CloudFormation stack per release (would couple the domains;
  AD-23); other deployment strategies are not recorded.
- **Trade-off.** Rollback is image-only. The compatibility check is an attestation, not a test
  (see AD-24 for the tests it should rest on). Additive contract changes can ship in either order;
  a breaking change takes the two-release rollout in `contracts/README.md`.
- **Evidence.** [AWS] Processing: `promote-good` 322.5 s (gate 600 s) with peer unchanged at every
  snapshot, `rollback` 250.7 s, a failing candidate stopped at smoke after 205.7 s and restored in
  54.8 s. Media (`r1018bmedia`): `promote-good` 246.8 s, `rollback` 251.8 s, a failing candidate stopped
  at smoke after 189.5 s and restored in 47.0 s. Through CD, the `Release` step took 10.1 to 10.3 min
  for Processing (the proposal target is 10 min: a marginal FAIL) and 8.0 to 8.2 min for Media, and the
  post-release smoke did not pass in the five runs that reached it. [Code] `scripts/aws/v1/release.py`.

### AD-17 GitHub Actions CD over OIDC

- **Context.** The course asks for a visible, automated pipeline; the proposal wants a deploy step
  and smoke test.
- **Decision.** `.github/workflows/cd.yml` (manual dispatch: preflight, deploy, release, teardown)
  runs the same operator commands. A `gate` job refuses a commit without a green CI run. AWS access
  is the role `dc2-github-deploy` assumed by the `aws` environment through OIDC with an immutable
  repository subject; no AWS key is stored in GitHub. Run state is kept in a private versioned S3
  bucket between jobs. Nothing mutates the account unless `execute=true`.
- **Alternatives.** Long-lived access keys in GitHub secrets (rejected by the design); running the
  CLI only from a laptop (what the live run used).
- **Trade-off.** The role has `AdministratorAccess` plus a region lock (equal to the agent user) and
  is protected only by the environment's branch policy. State bucket contains smoke credentials.
- **Evidence.** [Code] `cd.yml`, `deploy/aws/v1/github-oidc.yaml`, `deploy-runbook.md` "CD workflow".
  **No dispatched run of `cd.yml` exists** (`gh run list --workflow cd.yml --event workflow_dispatch`
  returns nothing at the time of writing; the two recorded runs were push-triggered on
  `closeout/pipeline`). The live receipt `r1017b` came from the operator CLI, not from this workflow.
  Update, 18 October: `r1018a` and `r1018b` ran through `cd.yml` (OIDC). `r1018b` deploy succeeded
  (26.5 min, smoke PASS) and releases promoted, but the post-release smoke failed in all five runs that
  reached it and both teardown dispatches failed at `td-session-close`. Later on 18 October `r1019a`
  went green end to end through `cd.yml`: deploy (run 39085599276), Processing release with a passing
  upload-to-playback smoke (39087966647) and a `CLEAN` teardown (39089615147). The earlier failures
  stand; the deliberate bad-candidate dispatch (39089045496) was cancelled and has no result.

### AD-18 Network: private Lambda subnets, IPv6 egress-only, S3 gateway endpoint, no NAT

- **Context.** NAT gateways and interface endpoints bill per hour; the demo is mostly idle.
- **Decision.** One VPC `10.62.0.0/16` plus an AWS IPv6 block, two AZs, one private and one public
  subnet per AZ. Private subnets (Lambda, Aurora) have an IPv6 route through an egress-only gateway
  and no IPv4 default route. Lambda uses dual-stack endpoints for SQS, SSM and ECS. One S3 gateway
  endpoint is attached to all four route tables with a policy limited to the source and output buckets
  (plus the regional ECR layer bucket). Fargate tasks run in public subnets with a temporary public
  IPv4 address while running. No security group has an inbound rule except the database's, which
  admits Lambda, worker and migration groups on 5432.
- **Alternatives recorded.** NAT, paid interface endpoints, ALB, managed Redis, EC2 and nginx were
  excluded by the plan; AWS Batch and the RDS Data API remain options.
- **Trade-off.** Relies on every AWS dependency of Lambda being reachable over IPv6 or the S3
  gateway; the plan flags actual routing as unverified until a live run. Fargate tasks are on public
  subnets to pull images and reach SQS.
- **Evidence.** [Code] `definitions.py` (`Vpc` through `S3Gateway`, security groups). [AWS] the
  passing steps ran in this layout, but no receipt tests the individual network paths.

### AD-19 Closed-by-default stack, operated as booked sessions

**Superseded by AD-27** for the persistent environment. It still describes the per-run V1 stacks.

- **Context.** The account limits Lambda to 10 concurrent executions, which makes reserved
  concurrency impossible, and cost must stay near zero when idle.
- **Decision.** The template deploys with both SQS event source mappings disabled, all EventBridge
  rules `DISABLED` and the Gateway stage throttle at 0/0. `session open` enables them; `session close`
  quiesces intake, drains workers, disables the rules and mappings and sets the throttle back to 0.
  No Lambda reserved concurrency is used anywhere.
- **Alternatives.** Always-on operation (not a V1 goal); reserved concurrency (blocked by the account
  limit).
- **Trade-off.** The platform is unavailable outside a session. A cold database adds seconds. A stack
  update can re-apply the closed defaults, so `session status` must be checked afterwards.
- **Evidence.** [AWS] `close-state` (mappings disabled, schedules `DISABLED`, 0 tasks, edge rate 0),
  `pause`, `cold-wake` (window open 21.8 s, statuses 200). [Code] `scripts/aws/v1/session.py`,
  `deploy/aws/v1/README.md` "Concurrency and session model".

### AD-20 Least-privilege IAM per handler, native credentials, queue resource policies

- **Context.** The proposal's AD-05 and AD-06 wanted no shared storage credentials and no shared
  trust; the services now share an account and SQS.
- **Decision.** Nineteen roles are defined (17 at the default settings): one per Lambda, per migration
  task, a worker task role, and execution roles. Examples: `ProcessingApi` has no S3 or SQS access;
  `MediaApi` has no SQS access; the worker can read source objects, write outputs and receive from
  the work queue, nothing else; only Media roles can read the JWT secret. Queue resource policies deny
  `SendMessage` and receive/delete to every principal outside the listed producer and consumer roles
  (operators' IAM users excepted for send, to allow redrive). Lambda and ECS use their native role
  credentials; no static keys.
- **Alternatives.** Presigned source URLs for workers (the proposal's AD-05) need a live Media
  callback in the critical path, which the plan removed.
- **Trade-off.** Source `GetObject` for the worker is bucket-wide (S3 cannot scope it to one owner), so
  owner and source binding is enforced in code before any read (`processing/messaging.py:claim`).
  VPC Lambdas hold `ec2:*NetworkInterface` on `*`. Each function's environment now names only the queues its code sends to
  (`definitions.py`, `queue_env`); the IAM role and queue policy were already narrower.
- **Evidence.** [AWS] `sqs-direct-send`, `forged-identity`, `cross-database`. [Local]
  `tests/aws/v1/test_infrastructure.py` (asserts the code-to-permission mapping). [Code]
  `definitions.py` (`privileges`, queue policies).

### AD-21 Media-owned projection of Processing state

- **Context.** Media must show job state and sign outputs without reading Processing's database or
  calling it.
- **Decision.** `processing_projections` holds one row per asset, written only by
  `media/projections.py:apply_result` inside the inbox transaction. The public job view, the HLS
  playlist route and edit pre-checks read only this row. Results with an older `state_version`, an
  older attempt, or a different job or source are ignored or rejected.
- **Alternatives.** Media querying Processing's public API per read (the proposal's `GetJob`):
  couples availability and adds a hop to every poll.
- **Trade-off.** The view is eventually consistent; a lost result leaves a stale status until
  repair or a re-emitted higher version (`recovery_v1.py:reemit_result`).
- **Evidence.** [Local] `tests/v1/test_domain_sql_boundary.py` (reordered results, delete dominates late
  results). [AWS] `direct-upload-e2e` transitions `accepted`, `processing`, `done`.

### AD-22 Opt-in V2 experiments in the same template

- **Context.** Three experiments were developed in parallel with the cloud proof: unattended encoder
  starts (#68), short encodes on Lambda (#93), separate database clusters (#94).
- **Decision.** The first two are CloudFormation conditions (`UnattendedLaunch`, `LambdaShortEncodes`)
  that default to false; the third is a render-time option. With defaults the template is byte-identical
  to the V1 template (a test compares it with `deploy/aws/v1/template.json`).
- **Alternatives.** Separate branches (the original gating, #80).
- **Trade-off.** V1 images and the migration history carry code and tables only the experiments use
  (`launcher_control`, `launch_reservations`). #68 ran in the cloud in `r1018b` (6 clips: 0.787 jobs/min,
  0.69x the operator batch); #93 and #94 are [NOT_RUN].
- **Evidence.** [Code] `docs/execution/aws/v2/*.md`, `definitions.py`, `tests/aws/v1/test_database_topology.py`.

### AD-23 One CloudFormation stack, applied in two phases

- **Context.** Three people, one account, one environment per run.
- **Decision.** One stack renders 60 resources with `DeployApplications=false` (network, database,
  buckets, queues, ECR, ECS cluster, CloudFront, three DLQ alarms) and 159 with `true` at default flags. A template rule
  requires digest-pinned image URIs before applications are enabled. Stateful resources use
  `DeletionPolicy: Retain`.
- **Alternatives.** One stack per domain (not chosen; recorded as an out-of-scope trade-off in #195).
- **Trade-off.** Network, database, queues and IAM for both domains change together, so infrastructure
  edits are not independently releasable; only code is (AD-16).
- **Evidence.** [Code] `definitions.py` (resource counts by condition computed from the rendered
  template). [AWS] teardown receipt: all remaining items explained, one Aurora snapshot kept.

### AD-24 `contracts/` as published language and shared kernel, with a versioning policy

- **Context.** The two services share only `contracts/`, which is copied into both images, so a
  careless change forces a lockstep release.
- **Decision.** Additive changes within a version; consumers accept versions N and N-1 and ignore
  unknown fields; producers emit `EMIT_VERSION`, which trails `SCHEMA_VERSION` until every consumer
  reads the new one. A breaking change takes two releases in either service order. Each consumer owns
  a fixture file of the messages and fields it reads, and the producer's tests check its real messages
  against it.
- **Alternatives.** A schema registry or separately versioned package (not recorded as evaluated); the
  earlier strict equality check `schema_version == 1`.
- **Trade-off.** Still a shared kernel, not independent schemas. Only version 1 exists, so N-1 is
  exercised by tests that raise the version, not by a second real version. The release compatibility
  gate remains an operator attestation that these tests support.
- **Evidence.** [Local] `tests/v1/test_v1_wire_contracts.py`, `tests/v1/fixtures/contracts/`,
  `tests/contracts/consumers/*.json` with `tests/media/test_media_consumer_contract.py` and
  `tests/processing/test_processing_consumer_contract.py`. [Code] `contracts/README.md`,
  `contracts/v1.py` (`accepted_versions`, `EMIT_VERSION`).

### AD-25 Per-service alarms and one services dashboard

- **Context.** The first V1 template had no alarms or dashboard, so a failure could not be attributed
  to a service.
- **Decision.** At default flags, 12 CloudWatch alarms: one DLQ-not-empty alarm per standard queue
  (owned by the service that consumes it) and one `Errors` alarm per function, tagged with the
  owning service. One dashboard, `ServicesDashboard`, has a section per service: invocations, errors,
  duration p90, queue depth, oldest message age, dead-letter depth, and encodes in flight for
  Processing. There is no notification target.
- **Alternatives.** Container Insights for running-task counts (left off for cost, so in-flight work
  messages stand in for running encoders); paging through SNS (out of scope).
- **Trade-off.** Alarms are state to read, not pages. Log retention is 7 days.
- **Evidence.** [Code] `definitions.py` (`*DlqAlarm`, `*ErrorsAlarm`, `ServicesDashboard`);
  [Local] `tests/aws/v1/test_observability.py`. [AWS] `r1018b`: 13 of 13 alarms `OK` after
  the backlog and the unattended run, no transition to `ALARM`; `ServicesDashboard` captured three
  times (images private). No alarm was seen firing.

### AD-26 Retired peer-HTTP and Redis/RQ code quarantined in `legacy/`

- **Context.** The proposal-era synchronous design still lived inside the V1 packages and images,
  where a reader would take it for V1 behaviour.
- **Decision.** Moved, not deleted, to `legacy/media_peer/` and `legacy/processing_rq/`, which only the
  isolated legacy tests and compose stack use. `deploy/v1/check_runtime.py` fails an image build if
  `legacy` or any listed legacy module is importable, if `/app/legacy` exists, or if the executable
  graph imports one.
- **Alternatives.** Deleting it (the issue preferred deletion; the legacy regression jobs still use it).
- **Trade-off.** The package and CI lanes for legacy remain to maintain. The remaining peer-era
  code (`submit_job`, `SubmitJob`, `require_service_token` and the Media peer settings) moved to
  `legacy/` in #210. The unused schema columns stay, by decision (no data migration this close to
  submission): see [views.md](views.md) section 4.5.
- **Evidence.** [Code] `deploy/v1/check_runtime.py`; [Local] `tests/v1/test_image_recipes.py`.

### AD-27 One persistent always-on environment, updated in place, scaling to zero (supersedes AD-19)

- **Context.** V1 created a full stack per run id (VPC, Aurora, CloudFront, ...) and deleted it
  afterwards, and AD-19 kept it closed outside booked sessions. Every infrastructure check cost a
  25 min deploy and a 25-40 min teardown, five times (r1017a-r1019a). The stack already scales to
  zero: Lambda, Aurora at 0 ACU with auto-pause, SQS, CloudFront and Fargate cost nothing idle, and
  there is no NAT and no paid endpoint, so the fixed idle cost is about $3-5 a month (alarms,
  secret, logs, ECR, storage). Nobody runs a product behind booked sessions (#234).
- **Decision.** One named environment (`--environment live`, stack `dc2-live`) is deployed once and
  kept. Its first deploy is a human's dispatch; after that CD updates it after every green CI
  run on Main: a CloudFormation `UPDATE` change set from the checkout, then the per-owner release
  (aliases, migration, smoke, automatic restore) for each owner whose images' build inputs
  changed, online (nothing is closed; see the trade-off). An owner whose migrations changed
  waits for an explicitly attested release. The release's images are then adopted into the
  stack, so the stack stays the description of what runs. A change set that would replace Aurora, an S3
  bucket or the CloudFront distribution fails the deploy unless `--allow-replacement` is given.
  The template deploys open (`AlwaysOn=true`): stage throttle 20 rps / burst 50, consumers and
  schedules enabled, and the launcher (#68) on with no session end. Every work send wakes the
  launcher with an asynchronous invoke; its one-minute schedule stays as the safety net, and the
  SQL reservations keep the cap of three under concurrent wakes. The cost safety net is an AWS
  Budget alerting at 50/80/100 % of $20 a month, plus the per-service alarms (AD-25); the CI-side
  cost guard only reports on routine updates. Idle minute ticks skip SQL (SSM activity markers),
  so Aurora still pauses. `session close` remains as the emergency kill switch, which deploys
  respect (`GatesOpen=false`, releases deferred), and `session status` reports drift.
- **Alternatives.** Keep per-run stacks (the cost in time above); keep the closed template and
  open a long session (an expiring window is a booking under another name); a staging plus a
  production environment (out of scope for the time left).
- **Trade-off.** The environment is public all the time, bounded by the stage throttle, the
  encoder cap (3, a cost choice; the Fargate quota is 30 vCPU) and the budget alerts rather than
  by a closed gate. A release no longer quiesces its owner: old and new code run side by side
  for a moment, which is safe only because an automatic release has unchanged migrations and any
  other is attested additive; for the same reason the launcher may keep starting the previous
  worker until the release is adopted into the stack. The idle markers are best effort: a lost
  touch delays a repair by at most 30 minutes, after which every tick runs a full SQL pass.
  The original 120 s (lost work) and 300 s (worker interruption) targets stay as the comparison
  target for healthy markers only. A failed marker write followed by a healthy read of the old
  quiet snapshot can delay discovery until that snapshot ages out (30 minutes plus tick alignment
  and invocation time); an SSM read failure fails open to SQL instead. This is distinct from a
  missing writer (the public Processing API, #244), which needs no SSM failure and is fixed by
  wiring `ProcessingApi` as a writer; that fix does not close this case. A local test with a
  controlled clock and fake SSM exercises it; no AWS failure injection has been run (NOT_RUN).
  Code reaches an alias only through a release or through a stack update that replaces the
  function's version (its description names the image digest, a digest of the definition, and
  the parameters, conditions and task definitions it resolves).
- **Evidence.** [Code] `scripts/aws/v1/deploy.py` (`deploy_persistent`, `begin_invocation`,
  `adopt_release`), `scripts/aws/v1/definitions.py` (`AlwaysOpen`, `MonthlyBudget`,
  `ProcessingLauncherInvokers`), `processing/launcher_trigger.py`, `scripts/ci/cd.sh`;
  [Local] `tests/aws/v1/test_persistent_environment.py`, `tests/v1/test_launcher_sql.py`.
  [AWS] pending the live verification (#238).

### AD-28 Release admission records fixable findings on a replaced rollback image instead of blocking its release

- **Context.** `scripts/ci/cd.sh:release_owner` scans the new candidate, then rescans the image
  that is running now (the rollback baseline) from its immutable ECR digest. On 21 October CD run
  39532075705 (Main `4ae6a0b`) failed with `media: FAIL: Trivy has 1 fixable HIGH/CRITICAL`. The
  candidate passed. The finding was on the running Media image (`sha256:24bd78a8...`, built from
  `629119c`): GHSA-6q48-6c7w-9gw2 in `certifi 2026.7.22`, published 2026-10-20T19:35Z after that
  image shipped and fixed by the candidate (`certifi 2026.10.19`, commit `94f7463`). The gate
  refused to replace a vulnerable image because it was vulnerable, so the fix could never ship.
- **Decision.** The candidate must still scan to zero fixable HIGH/CRITICAL first. Baseline images
  the release **keeps** are rescanned strictly. Baseline images the release **replaces** are
  rescanned in `--retained` mode: fixable findings become `trivy_scan.status = RETAINED_FIXABLE`
  with their ids, the run is annotated (`::warning::` and job summary) and the release receipt lists
  them as `rollback_target_findings`. Only the release plan's `baseline` role accepts that status;
  promote, the good and bad sets and publication still require `PASS`. Scanner errors and incomplete
  or wrong-image reports fail in both modes.
- **Alternatives.** A per-advisory accept-list entry (a hand-edited exemption for every new advisory,
  and the rule is that a fixable finding is fixed by rebuilding, not accepted); rebuilding the
  baseline (an immutable digest is never rebuilt, and a rebuild is not what actually runs);
  dropping the baseline scan (loses the record).
- **Trade-off.** An emergency restore can put back an image with a recorded fixable finding. That
  adds no exposure beyond what was already running, and the finding is visible in the receipt. A
  release that rebuilds only one of an owner's images still blocks on a fixable finding in the image
  it keeps, by design.
- **Evidence.** [Code] `scripts/ci/cd.sh` (`scan_baseline`), `scripts/ci/v1_scan.py` (`--retained`),
  `scripts/aws/artifacts.py`, `scripts/aws/v1/proof/release_plan.py`. [Local]
  `tests/ci/test_v1_scan.py`, `tests/aws/test_artifacts.py`, `tests/aws/v1/test_release_plan.py`,
  `tests/dev/test_cd_workflow.py`; the real baseline report from run 39532075705 replayed through the
  scanner gives `FAIL` strict and `RETAINED_FIXABLE` retained. PR #285 into `dev/closeout`, #286 into
  `Main`. [AWS] CD run 39545554380 on `c7c489c` promoted both owners with the finding recorded against
  the three replaced images and passed its upload-to-playback smoke; receipt
  `docs/results/engineering-20261021/delivery-c7c489c.json`. That run also carries the companion
  deploy-smoke fix for a paused database (#287, #288), which the first redelivery attempt
  (39542434067, `login:503`) exposed.

### AD-29 Media and Processing each have their own Aurora cluster, split in place from the shared one

- **Context.** V1 kept `media_db` and `processing_db` on one Aurora Serverless v2 cluster:
  separate roles and migrations, but one instance, one ACU ceiling and one failure boundary (AISS-01).
- **Decision.** Media keeps the existing cluster, instance and security group under V1's logical ids,
  so the live cluster is never replaced. Processing gets `ProcessingDatabaseCluster`, a copy-on-write
  clone of it. `split-database` checks Processing is idle, takes a manual snapshot, updates the stack,
  reconciles Processing's logins on the clone, freezes the old copy's Processing logins, points
  Processing's two DSN parameters at the clone and runs the public smoke. After a passing smoke,
  `finish-database-split` drops each cluster's copy of the peer's database. Both clusters keep
  auto-pause (minimum 0 ACU). CD opts an environment in with `CD_DATABASE_SPLIT` (set for `live` only).
  A stack update that rolled back is retried with the same change set name.
- **Alternatives.** Dump and restore (a longer idle window and a second copy of the data to verify);
  recreating the cluster (replaces live data); keeping one cluster and documenting the limit.
- **Trade-off.** A second cluster's fixed storage and wake cost; a Processing write between clone and
  switch would be lost, hence the idle precondition. The old copy of the peer's database stays until the
  smoke passes, which is the way back.
- **Evidence.** [Code] `scripts/aws/v1/deploy.py`, `definitions.py`, `scripts/ci/cd.sh`;
  [Local] `tests/aws/v1/test_database_split.py`, `test_database_topology.py`; [AWS] rehearsal receipt
  `docs/results/engineering-20261021/database-split-rehearsal.json`. Details:
  `docs/execution/aws/v2/database-topology.md`.

## 4. Proposal to as-built deviations

| Commitment (proposal) | What shipped | Why | Evidence |
|---|---|---|---|
| Containers on one small AWS environment (AD-07, section 2.5) | Managed serverless: API Gateway, Lambda, SQS, Aurora Serverless v2, S3, CloudFront. Containers only for the encoder, migrations and bootstrap. | Scale to zero, no host to run, course emphasis on cloud-native services | [Code] `definitions.py`; [AWS] receipt |
| Scale workers 1 to 3 independently (UC-6, section 3.3) | Operator-started finite batches of 1 to 3, not autoscaling. The proposal's own section 3.5 excludes autoscaling. | Cost, Fargate quota (6 vCPU), complexity | [AWS] `run-1/2/3`; [Code] `session.py:batch` |
| Redis/RQ workers kept (AD-03) | SQS plus outbox/inbox; workers poll SQS | Redis is an always-on node; decoupling Media from Processing | [Code] images, template |
| Sync `SubmitJob` and `GetJob` between services | Asynchronous commands and a Media-owned projection | Failure isolation and removal of a runtime dependency | [Local] messaging tests; [AWS] `r1018b` `processing-down` (#196, consumer only) |
| Service token on a private network (AD-06) | Gateway-trusted actor and role-scoped queue policies | No private network exists between Lambdas; IAM is the boundary | [AWS] `forged-identity`, `sqs-direct-send` |
| Workers never hold storage credentials; presigned source URL (AD-05) | Workers read the source bucket with an IAM grant pinned to a VersionId | Removes the Media callback from the encode path | [Code]; plan states the broadening |
| Upload through Media Management, 100 MiB (section 2.3) | Direct-to-S3 reservation and finalize; limit unchanged | Payload limits and cost of proxying bytes | [AWS] `direct-upload-e2e` |
| Transactional outbox only if needed (AD-04) | Outbox and inbox in both databases from the start | The new transport is not atomic with SQL | [Local] `test_messaging_sql.py` |
| Each service deployed on its own (section 2.5) | Code releases are independent per owner (Lambda aliases), with path-filtered per-service CI lanes that build and check only that owner's images (#204, CODEOWNERS). **Infrastructure is one CloudFormation stack** for both. | Effort; recorded as an accepted trade-off in #195 | [AWS] `promote-good` peer unchanged; [Code] AD-23, `.github/workflows/ci.yml`, `.github/CODEOWNERS` |
| One PostgreSQL server (AD-02) | Kept, which makes the **shared Aurora cluster one failure and capacity boundary** | Cost; separate clusters are a [NOT_RUN] experiment (#94) | [Code]; `docs/execution/aws/v2/database-topology.md` |
| Pipeline deploys then the Publisher CLI runs the smoke test (section 2.5) | CD smoke uses the evidence harness (`evidence gateway --only direct-upload-e2e`), not Publisher | Encoders are operator-started, so a Publisher job would stay queued | `deploy-runbook.md` "CD workflow"; Publisher is exercised by CI (`publisher-https`) [Local] |
| Automated pipeline builds, tests, scans, deploys | CI (lint, unit, per-service lanes, Trivy, Sonar, secret scan, ZAP workflow) is automatic. **CD ran by manual dispatch for `r1018a`, `r1018b` (post-release smoke and teardown failed) and `r1019a` (deploy, release with smoke and teardown green); since AD-27 it also runs after every green CI on Main.** | Cost guard and operator-gated sessions | [Code] workflows; [AWS] `r1018b` CD runs, see [`docs/evidence-index.md`](../evidence-index.md) |
| Scalability target: 30 identical 60 s clips, 1, 2, 3 workers, jobs/min ratios (section 3.4) | AWS `r1018b` ran a backlog of **6** clips (36 MB fixture) at cap 1, 2 and 3: 0.483 / 0.700 / 1.134 jobs/min, so 1.449x (**FAIL**, target 1.6x) and 2.347x (PASS, target 2.1x). The proposal's 30-clip backlog ran only locally, on the pre-V1 design, with three rotated repeats (the team's local protocol): 2.03x and 2.89x | Cost and time; the Fargate quota caps the run at 3 encoders | [AWS] `cloud-proof-r1018b.json` `#185`; [Local] `reviews/scaling-validation.md`. Detail and likely cause: [`docs/evidence-index.md`](../evidence-index.md) |
| Status p90 at most 700 ms (50 users, 3 min); login p90 under 2 s | p90 58 ms and 178 ms, measured from a Fargate generator in the same region, not from users | Method fixed by the proof tooling | [AWS] `generator` (#66) |
| Release Processing in 10 min or less | Operator-CLI promote step 322.5 s (`r1017b`, image build excluded); rollback 250.7 s. Through CD the `Release` step took 10.1 to 10.3 min in `r1018b` (**FAIL**, marginal) and 9m39s in `r1019a`, followed by a separate 5m59s upload-to-playback smoke; these are different timing boundaries and none shows an upload-smoked release inside 10 min | | [AWS] `promote-good`, `rollback`; evidence index Q7a, Q7b, Q7i |
| Failed worker re-queued or failed within 5 min | Detected in 5.8 s. Lease expiry marks the attempt `abandoned` and the job `failed`; there is **no automatic requeue**, a retry makes a new attempt. | Design choice in `recovery.py:interrupt` | [AWS] `recovery`; [Code] |
| Presigned, owner-checked playback for authorised viewers | Owners only; no viewer identity or sharing | Out of scope for V1 | [Code] `authorizer.py:gateway_role` |
| Fresh data, no migration (AD-08) | As proposed | | |

## 5. Inconsistencies found while writing

Places where documents and code disagree, or where the code is easy to misread. Listed so the
report does not repeat either side blindly. Re-check before quoting; some will be fixed.

Status on 18 October: rows 1, 2 and 3 were corrected in the source documents, and row 6 is now explained in [views.md](views.md) section 4.2. Rows 4, 5, 7 and 8 were resolved in #210 (below); each keeps the original finding with the resolution appended.

| # | Statement or expectation | What the code or evidence shows |
|---|---|---|
| 1 | `docs/execution/aws/v1/README.md` ("Real AWS acceptance is still pending") and `deploy-runbook.md` ("never run against AWS") | `evidence/cloud-proof-r1017b.json` records a live run with PASS on #63 to #67 |
| 2 | `deploy/aws/v1/README.md` step 7: "every function with reserved concurrency 0" | The same file later, `session.py` and `definitions.py` use **no** reserved concurrency |
| 3 | `architecture-plan.md` "Close ... sets application/authorizer reserved concurrency to zero" | Default policy `zero_reservation: "off"`; `close-state` reports 0 functions with a reservation |
| 4 | Contract and `Actor` accept role `viewer` | `media/authorizer.py:gateway_role` only ever returns `publisher` **Resolved (#210):** documented as intentional at both ends (`contracts/v1.py:Actor.from_context`, `media/authorizer.py:gateway_role`): `viewer` is accepted so a read-only role can be added without a contract bump, and is never issued in V1. |
| 5 | `architecture-plan.md`: Processing creates jobs only from the trusted Media command path | The earlier synchronous path is still in the tree: `processing/service.py:submit_job`, `schemas.SubmitJob` (with `source_url`), `processing/auth.py:require_service_token`, and `media/config.py:source_service_token`. The V1 API does not mount them. The `redis_url` and `media_url` settings and the peer modules moved to `legacy/` (AD-26); `submit_job`, `SubmitJob` and the service-token dependency did not. **Resolved (#210):** `submit_job`, `get_job`/`list_jobs`, `request_fingerprint`, `SubmitJob`, `SourceAccess`, `require_service_token`/`get_owner_id` moved to `legacy/processing_rq/`, and Media's `processing_url`, `processing_service_token`, `source_service_token`, `processing_timeout_seconds` moved to `legacy.media_peer.config.LegacyMediaSettings` (Processing's `service_token` to `LegacySettings`). A static test fails if any name returns to `processing/` or `media/`. The unused schema columns are retained and recorded in [views.md](views.md) section 4.5. |
| 6 | Migration filenames look like a continuous sequence | Media has no `0003`, Processing has no `0004`; Processing `0005` names `0003` as its parent. Revision ids mix `0001_media`, `media_0004` styles. |
| 7 | A `staging/` key holds unadopted data | `direct_intake.py:finalize` keeps the adopted source at `staging/{owner}/{reservation}/source`; edit-derived sources use `sources/{owner}/{asset}/source`. Processing accepts both prefixes. **Resolved (#210):** intentional and now commented at the source (`direct_intake.py:reserve`): the pinned VersionId, not the prefix, makes the source immutable, and a copy to `sources/` would store a second object. Documented in [views.md](views.md) section 4.3. |
| 8 | Submit commands have deterministic ids | Edit-derived assets use a deterministic id (`uuid5`), upload-derived ones a random `uuid4` in `media/messaging.py:enqueue_submit`. Safe because finalize is guarded by the reservation, but inconsistent. **Resolved (#210):** intentional and commented at `media/messaging.py:enqueue_submit`: finalize adopts a reservation once, so a random id cannot duplicate; edits have no reservation, so `v1_lifecycle` derives a `uuid5` from the asset so a replay is idempotent. |

## 6. Architectural limitations

| Limitation | Detail | Evidence or issue |
|---|---|---|
| Shared Aurora cluster is a single failure and capacity boundary | One cluster, one instance, 2 ACU ceiling, 1-day backup retention. An outage, a failed resume or a capacity limit affects both domains. Role separation does not isolate failures. Separate clusters were not measured on AWS. | [Code]; #94 [NOT_RUN] |
| Single region | Everything runs in ap-southeast-1. Subnets span two AZs but the database instance does not. No cross-region copy or failover; the proposal excluded multi-zone and multi-region failover. | [Code] |
| Operator-started encoders | No autoscaling and no unattended starts by default. At most three concurrent encodes (quota and operator cap). Work that arrives after a batch waits for the next one. The opt-in launcher (#68) removes the operator but measured 0.69x the throughput of operator batches on the same 6 clips. | [AWS] `run-1/2/3`; `r1018b` `#68` |
| Booked sessions only | When closed, the Gateway throttle is 0 and consumers are disabled. A cold start after pause took 4.7 s for the first read. | [AWS] `close-state`, `cold-wake` |
| Command publication waits for a repair tick | The Media API cannot send to SQS; the one-minute `MediaRepair` rule publishes `submit`. Intake-to-queue latency is up to about a minute. | [Code] `definitions.py` (`privileges`, rules) |
| One stack, one repository, one lockfile | Infrastructure for both domains changes together. `contracts/`, `delivery/` and `runtime_support/` are copied into both images. Additive changes can ship in either order, but a breaking change needs two releases of both, and compatibility of a released pair is still attested by the operator. | AD-23, AD-16, AD-24 |
| Failure isolation is not yet proven on AWS | Media finalize writes only its outbox and never calls Processing. The proof (`evidence isolation`) disables the `ProcessingCommands` consumer, uploads, checks Media holds the command, re-enables and requires `done`. It passed on AWS in `r1018b` (after one harness-bug failure). The Processing API stays up during it, so it shows consumer isolation, not a full Processing outage. | AD-11; [AWS] `processing-down` |
| Alarms exist but have not been seen firing | 12 alarms at default flags (13 in the `r1018b` stack, all `OK`) and one dashboard. No alarm was observed in the `ALARM` state. There is no notification target, so nobody is paged; log retention is 7 days; Container Insights is off. | AD-25; [AWS] `r1018b`, state only |
| Public API endpoint beyond CloudFront | The `execute-api` URL is reachable directly (the receipt tests both). There is no WAF; throttling is a single stage limit. | [AWS] `anonymous-denied`; [Code] |
| Worker source read is bucket-wide | Owner scoping is application-level binding, not IAM. | AD-20 |
| No viewer sharing | Only the owner can play an asset. | [Code] |
| Rollback is image-only | Schema is never reversed; destructive migrations are not supported by release tooling. | [AWS] `schema_rollback_attempted: false`; `release.py` |
| Delivery is at-least-once | Duplicates, reordering and lost responses are expected and absorbed by fences. Poison messages stop in a DLQ and need an operator redrive (`dlq-runbook.md`). | [Local]; [AWS] `dlq` |
| Evidence limits | Latency is from an in-region generator. Cost Explorer reported an estimate with no usable total (`total` about 0, `final: false`); no invoice. The AWS backlog ratio uses 6 clips, one run per cap. HLS output is best effort. | `cloud-proof-r1017b.json` and `cloud-proof-r1018b.json` "not_proven" |
| CD role is `AdministratorAccess`; the deliberate CD bad-candidate test has no result | `cd.yml` ran for `r1018a` and `r1018b` (the post-release smoke and both teardowns failed there) and went green end to end for `r1019a`. The dispatch with `bad_candidate=true` was cancelled, so rollback inside CD is not shown. | AD-17; evidence index Q7h, Q7i |
| Legacy residue | The peer code moved to `legacy/` and is kept out of the images, but peer-era tables, columns and a few functions remain in V1 packages. | AD-26, section 5 |
