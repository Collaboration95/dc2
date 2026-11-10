## Physical Architecture & Design

The deployment targets one AWS account in **ap-southeast-1 (Singapore)**, with CloudFront at
the global edge. `scripts/aws/v1/definitions.py` generates CloudFormation; tests check the
checked-in default template's freshness. The figures expand the persistent mode with
applications, unattended launch, short encodes and separate databases enabled. Counts are
**source configuration reviewed on 10 November**, separate from current AWS health/inventory.

- **V1** used per-run October proof stacks (`r1017b`, `r1018b`, `r1019a`, tag `project2-v1`),
  closed outside booked sessions and deleted afterwards.
- **V2-live**, introduced 18 October, uses persistent `dc2-live`, updated by qualifying Main
  CI/CD and configured for idle compute to scale to zero. The 21 October receipts record short
  execution and the database split; historical resource counts keep their original scope.

The views separate runtime placement (Figure {@fig:arch-deployment-main}), image
artifacts, queue triggers, stores and network. Together they identify nodes, artifacts and paths.

![Figure {#fig:arch-deployment-main}. Configured persistent deployment in Singapore: Gateway authorizer and API integrations, private Lambda aliases, separate Aurora instances and launcher-created finite Fargate tasks. A+B denote subnet choices, not replica placement.](figures/arch-deployment-main.png){width=15cm}

| Component | Deployed as | Placement and configured bound |
|:---------------|:----------------------------------|:----------------------------------------------------|
| Web app | Static files in FrontendBucket behind CloudFront OAC | Global HTTPS edge; `/api/*` forwarded to regional HTTP API |
| Public API | HTTP API, Media/Processing integrations and Media-owned REQUEST authorizer | Direct invocation of `live` aliases; open-stage throttle 20 requests/s, burst 50; 29 s integration timeout |
| Media handlers | MediaImageUri → MediaApi, MediaAuthorizer, MediaResults, MediaRepair (4 functions) | Private A+B; each function has an IAM role, published version and `live` alias |
| Processing control | ProcessingImageUri → ProcessingApi, ProcessingCommands, ProcessingRepair, ProcessingEcsEvents, ProcessingS3Events, ProcessingLauncher (6 functions) | Private A+B; independent roles/versions/aliases |
| Short encoder | WorkerImageUri → ProcessingShortEncoder (1 Lambda); entrypoint `python -m awslambdaric` | Private A+B; 3008 MB, 900 s timeout, 2048 MB scratch; SQS mapping batch 1, max concurrency 2 |
| Standard encoder | WorkerImageUri → WorkerTaskDefinition; finite ECS Fargate task, no ECS service | Public A+B choices; 2 vCPU, 4096 MiB; launcher cap 3, zero when idle; no inbound listener |
| Operations | Media/Processing migration tasks from their domain images; bootstrap from Worker image | One-off Fargate tasks, 256 CPU units / 512 MiB, public task placement |
| Databases | Aurora PostgreSQL 16 Serverless v2, `media_db` and `processing_db`, separate clusters | Private subnet group A+B; one instance per cluster, default 0–2 ACU with 300 s auto-pause; encrypted, forced TLS |
| Object storage | FrontendBucket, SourceBucket, OutputBucket | Regional; versioned, SSE-S3, public access blocked, TLS-only, retained data |
| Messaging | Commands, standard work, short work and results: 4 Standard SQS queues plus 4 DLQs | Regional managed service outside VPC; encryption, TLS-only and role-scoped policies |
| Scheduling/hints | Three one-minute rules; ECS STOPPED rule; output S3 Object Created rule | Five EventBridge rules; hints lead back to SQL-authoritative recovery |
| Configuration/images | Five SecureString DSN/JWT parameters, four String activity markers, RDS-managed master secrets; three ECR repositories | Roles read only relevant parameters; immutable image tags/digests identify releases |
| Operations visibility | CloudWatch groups, ServicesDashboard, alarms and monthly budget | Seven-day logs; 15 configured alarms (11 function Errors + 4 DLQs), no paging action; USD 20 budget alerts |

**Artifacts, entry points and authority.** The artifact view maps digest images to
runtimes. Handler commands select exports; every Lambda has a role, version and `live` alias.
Both Processing encoders share the Worker artifact and FFmpeg pipeline. The source map is in
`scripts/aws/v1/definitions.py`.

[Image artifacts, OIDC and runtime placement](figures/arch-artifacts.png). Three image artifacts deployed to Lambda execution environments and one-off Fargate task sets. WorkerImageUri supplies both short Lambda and finite standard encoding.

| Source export / executable | Image → runtime | Alias integration / trigger | Owned data and authority |
|:-------------------------------|:-------------------------------------|:--------------------------------|:-----------------------------------|
| `media.lambda_handler.handler` | Media → MediaApi | Gateway Media integration → `live` | Media SQL, owned S3 verification/copy/signing; no SQS send |
| `media.lambda_handler.authorizer` | Media → MediaAuthorizer | Gateway REQUEST authorizer → `live` | JWT secret and current Media User lookup |
| `media.handlers.result_handler` | Media → MediaResults | Results mapping → `live` | Media inbox/projection/cleanup authority |
| `media.handlers.repair_handler` | Media → MediaRepair | One-minute rule → `live` | Media outbox sends and source recovery |
| `processing.lambda_handler.handler` | Processing → ProcessingApi | Gateway Processing integration → `live` | Trusted Actor; Processing SQL; no S3/SQS grant |
| `processing.handlers.command_handler` | Processing → ProcessingCommands | Commands mapping → `live` | Inbox/guard/Job/Attempt and work/result outboxes |
| `processing.handlers.repair_handler`, `ecs_handler`, `s3_handler` | Processing → ProcessingRepair, ProcessingEcsEvents, ProcessingS3Events | Minute / ECS STOPPED / output-created rules → `live` | Processing recovery, cleanup and outbox publication |
| `processing.handlers.launcher_handler` | Processing → ProcessingLauncher | Minute rule or post-standard-send async invocation → `live` | Processing reservation rows, standard queue visibility, ECS RunTask |
| `processing.handlers.short_encoder_handler` | Worker → ProcessingShortEncoder | Short-work mapping → `live` | Processing claim/lease/finish; pinned S3 GET and output PUT |
| `processing.v1_worker` → `worker.sqs.main` | Worker → finite Fargate encoder | Launcher RunTask; worker polls standard work | Same claim/finish authority; receive/delete work; no queue send |
| Alembic / `scripts.aws.v1.bootstrap` | Domain migration / Worker bootstrap tasks | Deployment tooling, one-off RunTask | Separate migrator roles; privileged bootstrap only during provisioning |

**Queue and store placement.** Commands/results use mapped batches of 10, one-second windows,
partial failures and maximum concurrency 2 each. Short work uses batch 1/cap 2. Standard work
is polled by finite workers (the linked queue view). Each queue redrives after five receives.
Base visibility is 420 s; short visibility is 960 s. Standard workers normally override receive
visibility to 60 s and renew it. Visibility is separate from retention.

Three minute rules target MediaRepair, ProcessingRepair and ProcessingLauncher. ECS STOPPED
and output-created hints target ProcessingEcsEvents/ProcessingS3Events. A successful standard
send also wakes the launcher (`processing/launcher_trigger.py`). SQL remains authoritative:
an uploaded object requires Media finalize/adoption before it becomes a job.

[Queue and consumer deployment](figures/arch-triggers.png). Four physical queue/DLQ pairs and consumer triggers. Standard work is returned to polling Fargate tasks; SQS does not launch them.

CloudFront reads FrontendBucket through OAC; clients upload under a Media grant and play signed
outputs (the linked storage view). Media verifies sources, copies validated outputs for edits
and reads playlists. Encoders GET the accepted VersionId and PUT attempt-scoped outputs.
Each context owns its SQL authority. A two-AZ subnet group supplies placement choices; each
cluster has **one instance**, with no reader failover target.

[S3 storage deployment and byte paths](figures/arch-stores.png). Three S3 buckets and direct byte paths. Media owns source acceptance/playback access; Processing owns attempt output descriptors. Aurora placement is in the main deployment view.

**Network and identity.** One dual-stack VPC (`10.62.0.0/16`) spans two AZ choices. Private A/B
are `10.62.0.0/24` and `10.62.1.0/24`; Public A/B are `10.62.2.0/24` and `10.62.3.0/24`, each
also with an IPv6 /64. All eleven Lambdas attach to Private A+B. Private IPv6 default routes
use an egress-only internet gateway for dual-stack AWS APIs; private subnets have no IPv4
default route or NAT gateway. These are public AWS API endpoints reached over IPv6, not
private interface endpoints.

Finite workers and operations tasks use public subnet choices and temporary public IPv4.
Worker HTTPS egress uses IPv4 through the internet gateway; the worker security group has no
general IPv6 HTTPS rule. S3 IPv4 traffic uses the gateway endpoint on all four route tables.
Its policy permits SourceBucket/OutputBucket and GetObject from the regional ECR starport
layer bucket. No compute group admits inbound traffic. Media DB accepts Lambda/migration
groups; Processing DB additionally accepts worker SQL traffic on 5432. Shared Lambda SGs reach
both database groups; domain isolation is refined by IAM parameter access, PostgreSQL roles
and image contents, rather than a separate SG per function.

[Subnet placement and egress](figures/arch-network.png). Network placement and allowed egress. Private Lambda IPv6 egress and public-task IPv4 HTTPS use different routes; all four route tables share the S3 gateway endpoint.

GitHub Actions uses temporary OIDC credentials through the `aws` environment's
`dc2-github-deploy` role (`deploy/aws/v1/github-oidc.yaml`, AD-17). Runtime IAM roles,
SSM parameter scopes and SQL DML/migrator roles are distinct authorities. Encoder source-read
access is broader than one owner; accepted source and owner/job/attempt checks bind execution
before S3 access (AD-20).

### Key Architectural Decisions

These decisions are reflected in the physical view. Section 3.1.1 holds the logical ones.

| Identifier | Decision | Rationale and trade-off | Status |
|:------|:-----------------------|:-------------------------------------------------------|:---------|
| AD-10 | **Lambda images for domain handlers; Worker artifact for both encoders**; handler command and `live` alias per function | Scale-to-zero and per-domain releases. Cold starts, invocation-scoped NullPool connections and 29 s Gateway timeout. Alternative: warm container API fleet (AD-30). | New, refines AD-07 |
| AD-12 | **Aurora Serverless v2**, one instance per cluster, default 0–2 ACU | Low idle compute and role separation; no reader failover. Historical paused-resume read: 4.7 s **[AWS]**. V1 shared a cluster; AD-29 split it. | New, refines AD-02 |
| AD-29 | **One cluster per service**, split in place | Separates failure/capacity boundaries. Processing received a copy-on-write clone; cleanup removed peer databases. Rehearsal and pre-split snapshot preceded recorded CD on 21 October (`docs/results/engineering-20261021/database-split-rehearsal.json`). Additional storage/wake cost; Processing must be idle during split. | New, refines AD-02/12 |
| AD-13 | **Finite standard encoders**, cap 3/zero idle; optional short Lambda cap 2 | One claimed Attempt per finite task. Reject always-on ECS workers/Batch for idle cost/additional operations. Accept startup latency and explicit launcher recovery; dispatch/admission below. | New |
| AD-15 | **CloudFront as normal frontend/API entry** | Managed HTTPS and one cookie origin. Generated hostname; execute-api is also reachable (AISS-02). | New |
| AD-16 | **Owner image-digest/alias release and restore** | Processing can release independently. Failed owner-readiness smoke restores aliases; later playback smoke is a separate boundary (section 5.3). Image-only restore requires additive schema changes. | New |
| AD-17 | **GitHub Actions OIDC**, no stored cloud key | Repeatable delivery via `aws` environment. Broad AdministratorAccess with region lock; branch restrictions, no reviewer rule in dated audit (AISS-04). | New |
| AD-18 | **Private Lambda IPv6 egress, S3 gateway, no NAT** | Avoids NAT/interface-endpoint idle charges. Dependencies require IPv6/gateway reachability; finite tasks use public IPv4 for image pulls. | New |
| AD-20 | **Per-handler IAM/SSM and queue policies** | Native credentials establish authority. MediaApi/ProcessingApi have no SQS grant; finite workers receive/delete but cannot send. Broad source read requires code-level owner binding. | New, supersedes AD-06 |
| AD-23 | **One stack, infrastructure then digest-pinned applications** | Small operational surface; infrastructure changes together while code releases remain independent. | New |
| AD-25 | **Per-service alarms/dashboard** | Owner-tagged function-error and DLQ alarms locate failures. No paging target is wired. | New |
| AD-27 | **Persistent environment, update in place and zero idle compute** | Avoids per-check deploy/teardown. SQL plus standard-queue visibility, tasks and reservations drive the launcher. Public entry persists; versions overlap during release; throttle/cap/USD 20 budget bound operation. | New, supersedes AD-19 |

**AD-30 — distribute HTTP through Gateway/Lambda and encoding through queues plus finite
capacity; retain no ALB.** HTTP requests select the Media or Processing Lambda integration;
Lambda supplies concurrent invocations. SQS buffers asynchronous commands, results and work.
Mapped consumers have explicit concurrency bounds, while standard encoders are competing
receivers under a launcher cap. The generated stack has no ALB, HTTP target group or ECS
service; the encoder exposes no HTTP listener. This arrangement reduces idle compute but
accepts cold starts, finite-task startup latency and custom capacity/recovery logic.

The alternative, an **ALB plus ECS HTTP service**, offers health-checked warm HTTP targets,
with standing infrastructure/service operations and a separate queue-capacity policy. Reassess
when sustained warm HTTP containers are needed. AD-30 records this report's analysis, without
a historical ALB trial or comparative benchmark.

**Load distribution and execution admission.**

| Mechanism | Configured distribution / bound | Trade-off |
|:----------------------|:----------------------------------------------|:----------------------------------------|
| HTTP | Gateway route integration, throttle 20/s and burst 50; Lambda concurrent invocations | Shared account quota; no reserved/provisioned concurrency; cold starts and 29 s integration |
| Commands/results | Separate SQS mappings, maximum 2 invocations each | At-least-once/unordered delivery requires inbox and version fences |
| Short execution | Short-work mapping, batch 1 and maximum 2 | 900 s invocation, 720 s pipeline budget with 180 s headroom; bounded scratch/CPU |
| Standard execution | Finite Fargate tasks, launcher cap 3 | Queue/start delay; one Attempt per task, then exit |
| SQL | Separate clusters, one 0–2 ACU instance each | Cold resume, connections and lock/CPU contention; no reader failover |

The configured standard-plus-short encoder ceiling is **3 + 2 = 5**, rather than a single
three-worker cap. It is not evidence of measured five-way throughput. Lane choice and standard
capacity are distinct decisions:

1. **Dispatch in the state transaction.** `processing/messaging.py:emit_state()` calls
   `processing/short_lane.py:work_lane()` before staging work. It chooses short only when
   `PROCESSING_SHORT_LANE=true`, source size is strictly an integer in `(0,64 MiB]`, and no
   earlier Attempt of that Job has a `lambda-` task binding. Otherwise it stages standard
   work. At dispatch, duration and height have not been probed (Figure {@fig:arch-dispatch}).
2. **Short executor admission.** `processing/short_encoder.py:encode_record()` supplies
   `short_lane.check_probe` to `worker.sqs.execute_message`. After claim and source download,
   `processing/worker/tasks.py` probes the source and applies admission: finite positive
   duration ≤60 seconds and height ≤1080 pixels. A size-admitted source can therefore still
   be rejected at execution.
3. **Fenced redirect.** On `NotAdmitted`, `processing/messaging.py:redirect_to_long_lane()`
   locks Job, reads the current Attempt and verifies the live DB-clock lease. It abandons the
   short Attempt, records cleanup intent, creates a new numbered queued Attempt and stages
   standard work plus result. The existing Lambda binding makes dispatch sticky to standard.
   A stale token changes nothing. Ordinary failure/expiry ends the attempt and awaits owner
   retry; that retry also stays standard (Figure {@fig:arch-probe-redirect}).
4. **Standard capacity.** `processing/launcher.py:tick()` observes tasks and queue visibility;
   `_reserve()` serializes LauncherControl/reservations and computes demand from SQL queued
   current Attempts and visible **standard** work. Existing idle/pending workers offset
   demand and occupied slots reduce the cap. Reservations commit before RunTask; stable
   tokens reconcile uncertain replies. A reservation does not claim an Attempt: the finite
   worker claims after its own queue receive. Short Lambda capacity is controlled separately
   by its event mapping.

![Figure {#fig:arch-dispatch}. Dispatch selects a work lane inside the Processing transaction, then publication activates the short mapping or wakes the standard-capacity launcher.](figures/arch-dispatch.png){width=15cm}

![Figure {#fig:arch-probe-redirect}. Probe admission follows download. A live-lease redirect creates a successor Attempt and standard work; stale execution cannot mutate current state.](figures/arch-probe-redirect.png){width=15cm}

Verification covers bounds/sticky fallback (`tests/processing/test_short_lane.py`), redirect/lease
loss (`test_short_encoder.py`) and real-SQL handoff/capacity concurrency
(`tests/v1/test_short_encoder_sql.py`, `test_launcher_sql.py`).

### Technology and Services

| Technology or service | Used for | Rationale | Trade-off accepted |
|:----------------|:---------------------|:-----------------------------------------|:-----------------------------------------|
| Python 3.12, FastAPI, Pydantic, SQLAlchemy 2 (async), Alembic | Services, worker and tooling | Continuity with the inherited code; typed validation at every boundary; one migration history per database | One lockfile; owner extras scope image dependencies |
| FFmpeg and ffprobe | Probing, MP4 encoding, HLS ladder (360/480/720, capped at the source height) | Industry standard and already proven in Project 1 | CPU-bound; HLS is best effort; a large unfixed-CVE surface in the worker image (section 4.3) |
| Plain JavaScript SPA, hls.js, Plyr | Web client | No build step; browsers load `app.js` directly; Vitest tests it | No production bundling or minification |
| Python stdlib plus `httpx` | Publisher CLI | Proves reuse with the smallest dependency set: 491 lines in 6 files | Polling-based status; one cookie jar per process |
| AWS Lambda (container images) | APIs, consumers, repair, launcher | Pay per request, scale to zero, per-domain image release; also the short-encode lane | Cold starts; account concurrency limit of 10 observed |
| Amazon API Gateway HTTP API | Routing, authorizer hook, throttle | Cheapest managed HTTP front for Lambda; REQUEST authorizer | No WAF; one stage-level limit |
| Amazon CloudFront | HTTPS entry, static site, `/api/*` pass-through | Managed TLS, HTTP/2 and HTTP/3, no custom domain needed | Playback bytes come from S3 directly, not through CloudFront |
| Amazon SQS (Standard) with DLQs | Commands, work and results | Serverless, durable, cheap; redrive policy (5 receives) | Unordered and at least once, hence inbox dedupe and version fences |
| Amazon Aurora PostgreSQL Serverless v2 | Two owned relational databases, one cluster each | Transactions, constraints and `SKIP LOCKED` for outbox claims; scales to 0 ACU | One instance per cluster; cold resume of several seconds |
| Amazon S3 (versioned) | Sources, outputs, frontend | Presigned POST/GET keep bytes off the API; versioning makes the pinned source immutable | Cleanup must delete every version |
| Amazon ECS on Fargate | Finite encoders, migrations, bootstrap task | No hosts to manage; per-task CPU caps make capacity predictable | Task start median 25.6 s **[AWS]**, which dominates queue wait |
| Amazon EventBridge | Repair ticks, ECS and S3 event hints | Rebuild lost work and react to stopped tasks without polling clients | One-minute granularity |
| AWS IAM, SSM Parameter Store, Secrets Manager | Per-handler roles, DSNs and JWT secret, Aurora master secret | Secrets stay out of code, images and the template | SSM read at cold start |
| Amazon ECR | Three image repositories | Immutable tags and digests are the release identity | Scan on push complements the CI and CD Trivy scans |
| Amazon CloudWatch, AWS Budgets | Logs, alarms, dashboard, cost alerts | Per-service observability at near-zero cost | 7-day log retention; no paging |
| GitHub Actions, OIDC, Pages | CI, CD, study-guide publication | Integrated with pull requests; no long-lived cloud keys | Hosted runner limits shape the CI lanes |

**AD-31 — retain PostgreSQL authority with JSONB; consider NoSQL when access patterns justify
it.** Asset/source/output data include document-shaped values. The schemas already store
variable operations and descriptors in JSONB while S3 stores video bytes. PostgreSQL keeps
owner-filtered reads, relational identities, unique request/message/task constraints, local
state/inbox/outbox transactions and DB-clock lease fences in one authority. `delivery/sql.py`
uses indexed due work and `FOR UPDATE SKIP LOCKED`; `processing/lifecycle.py` checks current
Attempt/token/deadline against database time. These requirements apply alongside JSONB (`media/models.py`, `processing/models.py`; Persistence Design).

| Requirement | PostgreSQL retained | MongoDB alternative design | DynamoDB alternative design |
|:----------------|:----------------------------------|:--------------------------------|:--------------------------------|
| Owned Asset and status | Owner-filtered local queries, projection and JSONB | Owner/Asset documents with appropriate indexes | Owner partition, Asset key and listing index |
| Domain + inbox + intent | One local SQL transaction | Bounded embedding or explicit multi-document transaction boundary | Conditional identity items and transaction/publication design |
| Replay/task uniqueness | Primary, unique and composite constraints | Unique indexes and transaction policy | Conditional identity reservations and transaction policy |
| Lease, due work, capacity | DB-time fences, row locks and due indexes | Compare-and-set/transaction plus clock and due-index policy | Conditional updates plus partition/due-query and clock policy |

A NoSQL replacement needs explicit publication, concurrency and recovery policies; an external
SQS send still falls outside its transaction. No comparative benchmark establishes a benefit
for this workload. Retaining SQL preserves flexible payloads and the current authority. A future owner-facing read store would need backfill, tombstones,
version/attempt fences and reconciliation: result snapshots are not a complete retained event
log. AD-31 continues the report numbering; the repository register remains read-only.

**Runtime and development tools are separate.**

- Runtime images contain only the owning service's code and its runtime extras. `deploy/v1/check_runtime.py`
  verifies this.
- Development tools run only in CI and on developer machines: pytest, Ruff, Vitest, Playwright,
  Moto, cfn-lint, actionlint, CodeQL, Trivy, gitleaks and ZAP.
