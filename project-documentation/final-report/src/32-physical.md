## Physical Architecture & Design

The deployment targets one AWS account in **ap-southeast-1 (Singapore)**, with CloudFront at
the global edge. `scripts/aws/v1/definitions.py` generates CloudFormation; tests check that the
checked-in default template is current. The figures show the persistent mode with
applications, unattended launch, short encodes and separate databases enabled, as configured in
source on 10 November.

- **V1** used per-run October proof stacks (`r1017b`, `r1018b`, `r1019a`, tag `project2-v1`),
  closed outside booked sessions and deleted afterwards.
- **V2-live**, introduced 18 October, uses persistent `dc2-live`, updated by qualifying Main
  CI/CD and configured for idle compute to scale to zero. The 21 October receipts record short
  execution and the database split.

Figure {@fig:arch-deployment-main} shows runtime placement and Figure {@fig:arch-network} the
network. Supporting views show the [image artifacts](figures/arch-artifacts.png), the
[queue lanes and consumers](figures/arch-triggers.png) and the
[S3 byte paths](figures/arch-stores.png).

![Figure {#fig:arch-deployment-main}. Configured persistent deployment in Singapore: Gateway authorizer and API integrations, private Lambda aliases, separate Aurora instances and launcher-created finite Fargate tasks. A+B denote subnet choices, not replica placement.](figures/arch-deployment-main.png){width=16cm}

The table maps each deployed component to its artifact, trigger, placement and authority. Every
Lambda has its own IAM role, published version and `live` alias; triggers invoke the alias.

| Component | Image → entry point | Trigger | Placement and configured bound | Authority |
|:-------------|:--------------------------|:-------------------|:---------------------------|:---------------------|
| Web app | Static files in FrontendBucket | CloudFront OAC GET | Global HTTPS edge; `/api/*` forwarded to the regional HTTP API | Read-only static assets |
| Public API | HTTP API, two integrations and the Media REQUEST authorizer | Client HTTPS via CloudFront | Stage throttle 20 requests/s, burst 50; 29 s integration timeout | Invokes `live` aliases only |
| MediaApi | Media → `media.lambda_handler.handler` | Gateway Media integration | Private A+B | Media SQL; owned S3 verify, copy and signing; no SQS send |
| MediaAuthorizer | Media → `media.lambda_handler.authorizer` | Gateway REQUEST authorizer | Private A+B | JWT secret; current User lookup |
| MediaResults | Media → `media.handlers.result_handler` | Results mapping, batch 10, cap 2 | Private A+B | Media inbox, projection and cleanup |
| MediaRepair | Media → `media.handlers.repair_handler` | One-minute rule | Private A+B | Media outbox sends; source recovery |
| ProcessingApi | Processing → `processing.lambda_handler.handler` | Gateway Processing integration | Private A+B | Trusted Actor; Processing SQL; no S3 or SQS grant |
| ProcessingCommands | Processing → `processing.handlers.command_handler` | Commands mapping, batch 10, cap 2 | Private A+B | Inbox, guard, Job/Attempt and work/result outboxes |
| ProcessingRepair, ProcessingEcsEvents, ProcessingS3Events | Processing → `repair_handler`, `ecs_handler`, `s3_handler` | One-minute rule; ECS STOPPED; output Object Created | Private A+B | Recovery, cleanup and outbox publication |
| ProcessingLauncher | Processing → `processing.handlers.launcher_handler` | One-minute rule, or async invocation after a standard send | Private A+B | Reservation rows, standard queue visibility, ECS RunTask |
| ProcessingShortEncoder | Worker → `short_encoder_handler` (`python -m awslambdaric`) | Short-work mapping, batch 1, cap 2 | Private A+B; 3008 MB, 900 s, 2048 MB scratch | Claim, lease, finish; pinned S3 GET and output PUT |
| Standard encoder | Worker → `processing.v1_worker` (`worker.sqs.main`); finite Fargate task, no ECS service | Launcher RunTask; the task polls standard work | Public A+B; 2 vCPU / 4096 MiB; cap 3, zero when idle; no inbound listener | Same claim/finish authority; receive and delete work, no send |
| Operations tasks | Alembic from each domain image; `scripts.aws.v1.bootstrap` from Worker | One-off RunTask from deployment tooling | Public A+B; 256 CPU units / 512 MiB | Separate migrator roles; bootstrap only during provisioning |
| Databases | Aurora PostgreSQL 16 Serverless v2: `media_db` and `processing_db`, separate clusters | – | Private subnet group A+B; one instance per cluster, 0–2 ACU, 300 s auto-pause; encrypted, forced TLS | `*_runtime` DML and `*_migrator` DDL roles |
| Object storage | FrontendBucket, SourceBucket, OutputBucket | – | Regional; versioned, SSE-S3, public access blocked, TLS-only | Role-scoped bucket grants |
| Messaging | Commands, standard work, short work and results: 4 Standard SQS queues plus 4 DLQs | – | Regional, outside the VPC; DLQ after 5 receives; visibility 420 s (short 960 s) | Role-scoped queue policies |
| Scheduling and hints | Five EventBridge rules: three one-minute, ECS STOPPED, output Object Created | – | Regional | Hints lead back to SQL-authoritative recovery |
| Configuration and images | Five SecureString and four String SSM parameters; RDS-managed master secrets; three ECR repositories | – | Regional | Roles read only their parameters; image digests identify releases |
| Visibility | CloudWatch logs, ServicesDashboard, 15 alarms (11 function Errors + 4 DLQs), USD 20 budget | – | Seven-day logs; no paging action | – |

Both Processing encoders share the Worker artifact and FFmpeg pipeline. Standard workers
override receive visibility to 60 s and renew it while encoding. SQL remains authoritative: an
uploaded object becomes a job only after Media finalize and adoption.

**Network and identity.** One dual-stack VPC (`10.62.0.0/16`) spans two AZ choices: Private A/B
(`10.62.0.0/24`, `10.62.1.0/24`) and Public A/B (`10.62.2.0/24`, `10.62.3.0/24`), each with an
IPv6 /64. All eleven Lambdas attach to Private A+B and reach dual-stack AWS APIs over IPv6
through an egress-only internet gateway; private subnets have no IPv4 default route or NAT
gateway. Finite workers and operations tasks use public subnets with temporary public IPv4 for
HTTPS egress. All four route tables use the S3 gateway endpoint. No compute security group
admits inbound traffic. Media DB accepts the Lambda and migration groups; Processing DB also
accepts the worker group on 5432. IAM parameter access and PostgreSQL roles separate the
domains within the shared Lambda groups (Figure {@fig:arch-network}).

![Figure {#fig:arch-network}. Network placement and allowed egress. Private Lambda IPv6 egress and public-task IPv4 HTTPS use different routes; all four route tables share the S3 gateway endpoint.](figures/arch-network.png){width=16cm}

GitHub Actions uses temporary OIDC credentials through the `aws` environment's
`dc2-github-deploy` role (`deploy/aws/v1/github-oidc.yaml`, AD-17). Runtime IAM roles, SSM
parameter scopes and SQL DML/migrator roles are distinct authorities. Encoder source-read access
covers the bucket; accepted source and owner/job/attempt checks bind execution before S3 access
(AD-20).

### Key Architectural Decisions

These decisions are reflected in the physical view. Section 3.1.1 holds the logical ones.

| Identifier | Decision | Rationale and trade-off | Status |
|:------|:-----------------------|:-------------------------------------------------------|:---------|
| AD-10 | **Lambda images for domain handlers; Worker artifact for both encoders**; handler command and `live` alias per function | Scale-to-zero and per-domain releases. Cold starts, one pooled SQL connection per warm Lambda environment and the 29 s Gateway timeout. Alternative: warm container API fleet (AD-30). | New, refines AD-07 |
| AD-12 | **Aurora Serverless v2**, one instance per cluster, default 0–2 ACU | Low idle compute and role separation; no reader failover. Paused-resume read: 4.7 s **[AWS]**. V1 shared a cluster; AD-29 split it. | New, refines AD-02 |
| AD-29 | **One cluster per service**, split in place | Separates failure and capacity boundaries. Processing received a copy-on-write clone; cleanup removed peer databases. A rehearsal and pre-split snapshot preceded the CD delivery on 21 October (`docs/results/engineering-20261021/database-split-rehearsal.json`). Additional storage and wake cost; Processing must be idle during the split. | New, refines AD-02/12 |
| AD-13 | **Finite standard encoders**, cap 3, zero when idle; optional short Lambda cap 2 | One claimed Attempt per finite task. Always-on ECS workers and AWS Batch were rejected for idle cost and additional operations. Accepts startup latency and explicit launcher recovery. | New |
| AD-15 | **CloudFront as normal frontend/API entry** | Managed HTTPS and one cookie origin. Generated hostname; execute-api is also reachable (AISS-02). | New |
| AD-16 | **Owner image-digest/alias release and restore** | Processing can release independently. A failed owner-readiness smoke restores aliases; the later playback smoke is a separate boundary (section 5.3). Image-only restore requires additive schema changes. | New |
| AD-17 | **GitHub Actions OIDC**, no stored cloud key | Repeatable delivery through the branch-restricted `aws` environment; promotion is approved at the Main pull request. The deploy role is broad (AdministratorAccess with a region lock; AISS-04). | New |
| AD-18 | **Private Lambda IPv6 egress, S3 gateway, no NAT** | Avoids NAT and interface-endpoint idle charges. Dependencies require IPv6 or gateway reachability; finite tasks use public IPv4 for image pulls. | New |
| AD-20 | **Per-handler IAM/SSM and queue policies** | Native credentials establish authority. MediaApi/ProcessingApi have no SQS grant; finite workers receive and delete but cannot send. Bucket-wide source read relies on code-level owner binding. | New, supersedes AD-06 |
| AD-23 | **One stack, infrastructure then digest-pinned applications** | Small operational surface; infrastructure changes together while code releases remain independent. | New |
| AD-25 | **Per-service alarms/dashboard** | Owner-tagged function-error and DLQ alarms locate failures. No paging target is wired. | New |
| AD-27 | **Persistent environment, update in place and zero idle compute** | Avoids per-check deploy and teardown. SQL plus standard-queue visibility, tasks and reservations drive the launcher. Throttle, cap and the USD 20 budget bound operation. | New, supersedes AD-19 |

**AD-30 — distribute HTTP through Gateway/Lambda and encoding through queues plus finite
capacity; retain no ALB.** HTTP requests select the Media or Processing Lambda integration;
Lambda supplies concurrent invocations. SQS buffers asynchronous commands, results and work.
Mapped consumers have explicit concurrency bounds, while standard encoders are competing
receivers under a launcher cap. The generated stack has no ALB, HTTP target group or ECS
service, and the encoder exposes no HTTP listener. This arrangement keeps idle compute at zero
and accepts cold starts, finite-task startup latency and custom capacity and recovery logic.

The alternative, an **ALB plus ECS HTTP service**, offers health-checked warm HTTP targets, at
the cost of standing infrastructure, service operations and a separate queue-capacity policy.
AD-30 compares the alternatives against the deployed workload and idle-cost goals; it should be
reassessed when sustained warm HTTP containers are needed.

**Load distribution and execution admission.**

| Mechanism | Configured distribution / bound | Trade-off |
|:----------------------|:----------------------------------------------|:----------------------------------------|
| HTTP | Gateway route integration, throttle 20/s and burst 50; Lambda concurrent invocations | Shared account quota; no reserved/provisioned concurrency; cold starts and 29 s integration |
| Commands/results | Separate SQS mappings, maximum 2 invocations each | At-least-once/unordered delivery requires inbox and version fences |
| Short execution | Short-work mapping, batch 1 and maximum 2 | 900 s invocation, 720 s pipeline budget with 180 s headroom; bounded scratch/CPU |
| Standard execution | Finite Fargate tasks, launcher cap 3 | Queue/start delay; one Attempt per task, then exit |
| SQL | Separate clusters, one 0–2 ACU instance each | Cold resume, connections and lock/CPU contention; no reader failover |

The configured encoder ceiling is **3 standard + 2 short = 5**. Lane choice and standard
capacity are separate decisions, each made in one place:

| Decision | Where it is made | Rule |
|:--------------|:------------------------------|:------------------------------------------------|
| Lane dispatch | `processing/short_lane.py:work_lane()`, called by `messaging.emit_state()` inside the state transaction | Short only when `PROCESSING_SHORT_LANE=true`, the source size is in (0, 64 MiB] and no earlier Attempt of the Job ran on a `lambda-` task; otherwise standard. Duration and height are not yet known (Figure {@fig:arch-dispatch}). |
| Short admission | `short_lane.check_probe`, applied by `worker.sqs.execute_message` after claim and download | Finite positive duration ≤ 60 s and height ≤ 1080 px; a size-admitted source can still be rejected here. |
| Fenced redirect | `processing/messaging.py:redirect_to_long_lane()` | With a live DB-clock lease: abandon the short Attempt, record cleanup intent, create a new queued Attempt and stage standard work plus result. A stale token changes nothing; later retries stay standard (Figure {@fig:arch-probe-redirect}). |
| Standard capacity | `processing/launcher.py:tick()` and `_reserve()` | Demand from SQL queued current Attempts and visible standard work, offset by idle or pending workers, bounded by cap 3. Reservations commit before RunTask; the worker claims an Attempt only after its own receive. |
| Short capacity | Short-work event source mapping | Maximum concurrency 2, independent of the launcher. |

![Figure {#fig:arch-dispatch}. Dispatch selects a work lane inside the Processing transaction, then publication activates the short mapping or wakes the standard-capacity launcher.](figures/arch-dispatch.png){width=15cm}

![Figure {#fig:arch-probe-redirect}. Probe admission follows download. A live-lease redirect creates a successor Attempt and standard work; stale execution cannot mutate current state.](figures/arch-probe-redirect.png){width=15cm}

Verification covers bounds and sticky fallback (`tests/processing/test_short_lane.py`), redirect
and lease loss (`test_short_encoder.py`) and real-SQL handoff and capacity concurrency
(`tests/v1/test_short_encoder_sql.py`, `test_launcher_sql.py`). UC-2 and UC-6 give the
operation-level interactions.

### Technology and Services

| Technology or service | Used for | Rationale | Trade-off accepted |
|:----------------|:---------------------|:-----------------------------------------|:-----------------------------------------|
| Python 3.12, FastAPI, Pydantic, SQLAlchemy 2 (async), Alembic | Services, worker and tooling | Continuity with the inherited code; typed validation at every boundary; one migration history per database | One lockfile; owner extras scope image dependencies |
| FFmpeg and ffprobe | Probing, MP4 encoding, HLS ladder (360/480/720, capped at the source height) | Industry standard and already proven in Project 1 | CPU-bound; HLS is best effort; a large unfixed-CVE surface in the worker image (section 4.3) |
| Plain JavaScript SPA, hls.js, Plyr | Web client | No build step; browsers load `app.js` directly; Vitest tests it | No production bundling or minification |
| Python stdlib plus `httpx` | Publisher CLI | Proves reuse with the smallest dependency set: 495 physical Python lines across five files, including blank lines | Polling-based status; one cookie jar per process |
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
it.** Asset, source and output data include document-shaped values, and the schemas already
store variable operations and descriptors in JSONB while S3 stores video bytes. PostgreSQL keeps
owner-filtered reads, relational identities, unique request/message/task constraints, local
state/inbox/outbox transactions and DB-clock lease fences in one authority. `delivery/sql.py`
uses indexed due work and `FOR UPDATE SKIP LOCKED`; `processing/lifecycle.py` checks the current
Attempt, token and deadline against database time (`media/models.py`, `processing/models.py`;
Persistence Design).

| Requirement | PostgreSQL retained | MongoDB alternative design | DynamoDB alternative design |
|:----------------|:----------------------------------|:--------------------------------|:--------------------------------|
| Owned Asset and status | Owner-filtered local queries, projection and JSONB | Owner/Asset documents with appropriate indexes | Owner partition, Asset key and listing index |
| Domain + inbox + intent | One local SQL transaction | Bounded embedding or explicit multi-document transaction boundary | Conditional identity items and transaction/publication design |
| Replay/task uniqueness | Primary, unique and composite constraints | Unique indexes and transaction policy | Conditional identity reservations and transaction policy |
| Lease, due work, capacity | DB-time fences, row locks and due indexes | Compare-and-set/transaction plus clock and due-index policy | Conditional updates plus partition/due-query and clock policy |

A NoSQL replacement needs explicit publication, concurrency and recovery policies, and an
external SQS send still falls outside its transaction. Retaining SQL keeps flexible JSONB
payloads and the current single authority. A future owner-facing read store would need backfill,
tombstones, version/attempt fences and reconciliation, because result snapshots are not a
complete event log.

**Runtime and development tools are separate.**

- Runtime images contain only the owning service's code and its runtime extras;
  `deploy/v1/check_runtime.py` verifies this.
- Development tools run only in CI and on developer machines: pytest, Ruff, Vitest, Playwright,
  Moto, cfn-lint, actionlint, CodeQL, Trivy, gitleaks and ZAP.
