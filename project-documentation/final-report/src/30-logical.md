# Solution Overview

This section describes the solution **as built** at the delivered engineering source. The proposal's
Figures 2–3 (synchronous `SubmitJob`, Redis/RQ, a service token) are the "before" design. Where the
build changed a proposal decision, the change and its reason are recorded in the decision register
(`docs/architecture/decisions.md`) and summarised here. Decision identifiers AD-01 to AD-29 are
the register's own. They are kept unchanged across sections 3.1.1, 3.2.1 and 3.3, rather than
renumbered, so every reference in the repository still resolves.

Evidence labels used in this report:

- **[AWS]**: recorded in a live cloud receipt.
- **[Local]**: tests on real PostgreSQL 16 and FFmpeg, with Moto standing in for S3 and SQS.
- **[Code]**: read from source or the rendered CloudFormation template.
- **[NOT_RUN]**: implemented, never run against AWS.

## Logical Architecture & Design

The architecturally significant elements, their types and their providers are listed below.
"Team 17" marks custom code written in this project. "Inherited" marks code reshaped from the
FlickPond baseline.

The logical view (Figure {@fig:logical}) groups these elements into tiers. The two domain services each
have their own API, domain and persistence layers. They share only the published contracts and the
delivery helpers, which are copied into each image at build time.

| Element | Type | Provider | Responsibility |
|:--------------------|:-----------|:------------|:-------------------------------------------------|
| FlickPond web app (`frontend/`) | Custom browser SPA (plain JavaScript, vendored hls.js and Plyr) | Team 17, adapted from inherited UI | Register, log in, direct upload, status polling, MP4/HLS playback, retry, edit, delete |
| Publisher CLI (`publisher/`) | Custom Python client (stdlib plus `httpx`) | Team 17 (new) | Bulk publish, status, output and retry through the public HTTPS API only |
| Media Management (`media/`) | Custom FastAPI service and Lambda handlers | Team 17 | Accounts, ownership, upload grants and verification, the public job view, playback signing, deletion |
| Media authorizer (`media/authorizer.py`) | Custom Lambda REQUEST authorizer | Team 17 (part of Media) | Verifies the session cookie against the current user row; returns the trusted actor |
| Processing (`processing/`) | Custom FastAPI service and Lambda handlers | Team 17 | Jobs, attempts, leases, retry and cancel, output descriptors, recovery, encoder launch |
| Finite encoder (`processing/worker/`, `media_engine/`) | Custom container task | Team 17; FFmpeg command builders inherited and reshaped | Claims one attempt, verifies the pinned source, encodes MP4 and the HLS ladder, writes outputs |
| Shared kernel (`contracts/`, `delivery/`, `runtime_support/`) | Custom libraries copied into both images | Team 17 | Versioned envelope and actor contracts, outbox/inbox and SQS adapters, Lambda DB sessions and settings |
| Operator and delivery tooling (`scripts/aws/v1/`, `scripts/ci/`) | Custom Python CLIs and shell | Team 17 | Template rendering, deploy, session, release and restore, evidence harnesses, CD admission |
| FFmpeg and ffprobe | COTS open source | FFmpeg project (Debian package) | Probing and transcoding |
| FastAPI, Pydantic, SQLAlchemy, Alembic, asyncpg, boto3, PyJWT, bcrypt | Open-source libraries | Python community | Web framework, validation, ORM, migrations, PostgreSQL driver, AWS SDK, JWT, password hashing |
| Relational database (PostgreSQL 16) | Managed service | AWS (Aurora Serverless v2) | `media_db` and `processing_db`, one cluster each (AD-29) |
| Object storage | Managed service | AWS (S3) | Source, output and frontend buckets |
| Messaging | Managed service | AWS (SQS) | Three queues and three dead-letter queues |
| Edge, compute and operations | Managed services | AWS (CloudFront, API Gateway, Lambda, ECS Fargate, EventBridge, SSM, Secrets Manager, ECR, CloudWatch, Budgets, IAM) | Section 3.2 |
| Source control, CI/CD and scanners | SaaS and open-source tools | GitHub (Actions, OIDC); Aqua Trivy, gitleaks, OWASP ZAP, Ruff | Section 5 |

![Figure {#fig:logical}. Logical view: client and edge tiers, the two domain services with their API, domain and persistence layers, the shared kernel, and the data tier.](figures/report-logical.png){width=10.5cm}

The relationships that matter most are the ones that **do not** exist:

- Media never calls Processing, and Processing never calls Media. Every interaction is a message
  on SQS, or a read of the context's own database.
- Neither service holds the other's database credentials. Each Lambda role can read only its own
  domain's connection string.
- The worker cannot send any message. It reports progress only through the Processing database,
  and the Processing outbox publishes the results.

Figures {@fig:seqintake}, {@fig:seqencode} and {@fig:seqplay} show the dynamic relationships for
the core workflow (UC-1 to UC-3), split into its three phases. Section 3.2.4 explains each step.

![Figure {#fig:seqintake}. Dynamic view, phase 1, intake: reserve, direct upload to S3, verify and adopt.](figures/report-seq-intake.png){width=13cm}

![Figure {#fig:seqencode}. Dynamic view, phase 2, handoff and encoding: outbox → SQS → Processing inbox, launch, lease, encode, finish.](figures/report-seq-encode.png){width=15.5cm}

![Figure {#fig:seqplay}. Dynamic view, phase 3, results and playback: Processing outbox → Media projection; owner-checked, signed playback.](figures/report-seq-play.png){width=15.5cm}

### Key Architectural Decisions

The significant decisions reflected in the logical view are summarised below. Each has a full
record in the register (context, decision, alternatives, trade-off, evidence).

| Identifier | Decision | Rationale and trade-off | Status |
|:------|:-----------------------|:-------------------------------------------------------|:---------|
| AD-01 | Extract **Processing** as the only new business service; Identity and Delivery stay inside Media | Processing has its own rules (claim, lease, attempt), lifecycle and CPU-bound scaling profile. Every playback or retry decision needs owner and asset together, so splitting Identity or Delivery out would turn single-database joins into cross-service calls. Four services were rejected as more contracts and operations than the need justifies. | Kept, confirmed by detailed DDD (F-01) |
| AD-02 | **Database per service**: `media_db` and `processing_db`, separate migration histories and roles (`*_runtime` DML only, `*_migrator` DDL, `*_owner` no login) | A real ownership boundary at low cost. Trade-off: V1 put both databases on one Aurora cluster, so logical ownership was real but failure isolation was not; since 21 October each service has its own cluster (AD-29). | Kept (hosting refined by AD-12 and AD-29) |
| AD-09 | **API Gateway HTTP API with a Media-owned Lambda authorizer**; the Gateway adapter builds the actor only from the authorizer context | Processing trusts the owner identity without holding Media's JWT secret or user table. Result cache TTL is 0, so a deleted user or changed role takes effect at once. The cost is a database read per request. | New (supersedes AD-06 service token) |
| AD-11 | **SQS with an SQL outbox and inbox** in both databases, replacing Redis/RQ and synchronous `SubmitJob` | No always-on broker, and failure isolation: Media accepts uploads while Processing is down. The SQL-to-SQS handoff is not atomic, so repair is part of the design. Delivery is at least once, so duplicates are normal and consumers deduplicate. | New (supersedes AD-03; changes AD-04) |
| AD-14 | **Direct-to-S3 intake**: a presigned, owner-scoped reservation, then a finalize step that verifies size, SHA-256 and file signature at a pinned S3 VersionId | No 100 MiB body passes through Gateway or Lambda, and the bytes that were verified are exactly the bytes encoded. Trade-off: a two-step protocol; the client hashes the file first, and versioned buckets need cleanup. | New (changes AD-05) |
| AD-21 | **Media-owned projection** of Processing state, fenced by `state_version` and attempt | Media answers status and signs playback without querying Processing. The view is eventually consistent; stale or reordered results are ignored. | New |
| AD-24 | **`contracts/` as published language and shared kernel**, versioned N / N-1 | Additive changes ship in either release order; consumers accept the current and previous versions and ignore unknown fields. Still a shared kernel: a breaking change needs two releases. | New |
| AD-26 | Retired peer-HTTP and Redis/RQ code **quarantined in `legacy/`** and excluded from images by a build-time check | The submission shows no dead dependency between the services. Trade-off: the legacy package and its CI lane remain to maintain. | New |

### Tiers and Layers

| Tier | Elements | Layers and modules |
|:----------|:---------------------|:--------------------------------------------------------|
| Client | Browser SPA, Publisher CLI | Presentation only. Both call the same public API. The browser uploads bytes straight to S3 with a presigned POST. |
| Edge | CloudFront, API Gateway, Media authorizer | TLS termination, routing (`/api/media/*`, `/api/processing/*`), identity, stage throttle |
| Application | Media Management, Processing | **API layer**: `media/api/*`, `processing/v1_api.py`; transport is FastAPI behind `contracts/gateway.py`. **Domain and service layer**: `media/services/direct_intake.py`, `v1_lifecycle.py`, `media/projections.py`; `processing/messaging.py`, `lifecycle.py`, `launcher.py`. **Messaging layer**: `media/messaging.py`, `processing/messaging.py` over `delivery/`. **Persistence layer**: models, repositories and Alembic migrations per service. **Shared kernel**: `contracts/`, `delivery/`, `runtime_support/`. |
| Execution | Lambda handlers, Fargate encoder | Queue consumers, one-minute repair ticks, ECS and S3 event handlers, the launcher, the encoder and the short-encode Lambda (`processing/worker/` with `media_engine/`) |
| Data | Aurora, S3, SQS | `media_db`, `processing_db`; source, output and frontend buckets; commands, work and results queues |

The dependency rules are enforced, not just documented:

- Processing's API module imports no Media package.
- `deploy/v1/check_runtime.py` fails an image build if the opposite domain package, or any
  `legacy/` module, can be imported.
- The engine package is pure command construction with no I/O.

### Nodes and Subsystems

| Subsystem | Responsibility | Nodes | Owner |
|:----------------|:-----------------------------------------|:------------------------|:--------|
| Identity and intake | Accounts, JWT cookie, upload reservations, verified adoption of uploads | `MediaApi`, `MediaAuthorizer` Lambdas | Media |
| Playback | Owner-checked presigned MP4 URLs, HLS playlist and segment redirects | `MediaApi` | Media |
| Projection | Apply Processing results to Media's read model | `MediaResults` Lambda | Media |
| Media repair | Publish the outbox, expire grants, clean up deleted sources | `MediaRepair` Lambda (one-minute rule) | Media |
| Job orchestration | Job and attempt lifecycle, retry, cancel, leases, state versions | `ProcessingApi`, `ProcessingCommands` Lambdas | Processing |
| Recovery | Rebuild lost work, expire leases, react to stopped tasks and late outputs | `ProcessingRepair`, `ProcessingEcsEvents`, `ProcessingS3Events` Lambdas | Processing |
| Capacity | Start finite encoders from the SQL backlog, at most three; clips of 60 s or less go to the short-encode Lambda instead | `ProcessingLauncher` Lambda (V2-live) | Processing |
| Encoding | Probe, MP4 or edited output, HLS ladder, upload outputs with SHA-256 | Fargate encoder task (2 vCPU, 4 GiB), 0 to 3 | Processing |
| Messaging | Envelope validation, outbox, inbox, SQS lanes, DLQ tooling | Library in both images | Shared kernel |
| Operations | Template, deploy, release and restore, evidence | CD runner or operator station | Platform |

Media and Processing are the only business subsystems. The Lambdas, the encoder and the repair
handlers are **execution roles** of one context. Each runs that context's code under that context's
image, database role and IAM role. They are not extra services, because none has its own data,
rules or release unit.

### Platform Design

The platform design comes from domain-driven design (`docs/architecture/ddd.md`). The proposal
drew the boundary from the language of the workflow (*upload, submit, claim, encode, complete,
play*). The detailed analysis requested in lecturer feedback F-01 then checked that boundary
against the code's real invariants and transaction boundaries.

![Figure {#fig:contextmap}. Context map: the Media Management and Processing contexts, their aggregates, the translation layer and the published language.](figures/report-context-map.png){width=9.3cm}

**Bounded contexts.**

| Context | Owns | Does not own |
|:-------------|:-----------------------------------------------|:----------------------------------|
| Media Management | Accounts and login, ownership, upload intake, source versions, playback signing, the public job view, deletion and source cleanup (`media_db`) | Job state, attempts, leases and outputs. It holds only a projection. |
| Processing | Jobs, attempts, leases, retry and cancel, output descriptors, late-output cleanup, encoder claims and launch reservations (`processing_db`) | Users, assets, source bytes (read-only S3 grant) and playback links |

**Ubiquitous language (selected).**

- **Owner**: the only principal that may read, retry, edit, delete or play an asset. Processing
  holds the owner as a plain UUID, never a foreign key.
- **Asset**: an owned video. Its UUID is also the public `job_id`.
- **Upload reservation**: a 15-minute, owner-scoped grant to write one S3 object.
- **Source revision**: the immutable bytes Processing may read, identified by the pinned S3
  VersionId plus SHA-256 and size.
- **ProcessingJob**: exactly one per asset.
- **Attempt**: one numbered try, never reused.
- **Lease**: one worker's time-limited right to finish an attempt, judged on the database clock.
- **Output descriptor**: the kind, key, size and SHA-256 of an output.
- **Command, work and result**: the three message families (below).
- **Projection**: Media's own copy of Processing state.

**Aggregates and their invariants.** The **Asset** aggregate (root `Asset`, with
`UploadReservation`, `SourceVersion`, `RequestKey` and `CleanupIntent`) enforces these rules:

- Only the owner can read or change an asset; anyone else gets 404.
- A reservation is idempotent per owner and request ID.
- The stored bytes must match the declared size, SHA-256 and signature.
- An adopted source cannot change.
- Adopting a source and staging its `submit` command happen in one commit.
- Retry is allowed only from `failed`.
- Delete is a tombstone plus a `cancel` command in one transaction.

The **ProcessingJob** aggregate (root `Job`, with `Attempt`, `RetryRequest`, `AttemptTask` and
`SubmissionGuard`) enforces these rules:

- There is one job per asset; an identical repeat submit is a no-op.
- Commands must match the stored owner, asset, job and source.
- Transitions are one-way per attempt. A job returns to `queued` only through a **new** attempt.
- A worker needs a valid lease to start and to finish, and one task claims at most one attempt.
- Cancel before submit is permanent.
- `state_version` only increases, and every state change commits together with its outgoing
  messages.

Both aggregates are consistency boundaries. No transaction spans the two databases.

**Commands, results and domain events.** All five message kinds share one versioned envelope
(`contracts/v1.py`): `schema_version`, `message_id`, `kind`, owner, asset, job and attempt IDs,
`state_version`, an immutable `source` descriptor, and a payload. Payload values that look like
secrets or URLs are rejected, so queues never carry bytes, credentials or signed URLs.

| Message | Queue | Producer | Consumer | Purpose |
|:--------|:-------------------|:-----------------------|:-----------------------|:-----------------------------------|
| `submit` | `processing-commands` | Media outbox (sent by `MediaRepair`) | `ProcessingCommands` | Process a newly adopted asset |
| `retry` | `processing-commands` | Media | `ProcessingCommands` | New attempt over the stored source |
| `cancel` | `processing-commands` | Media | `ProcessingCommands` | Tombstone; may precede `submit` |
| `work` | `processing-work` | Processing outbox | Fargate encoder | Wake an encoder for one attempt |
| `result` | `media-results` | Processing outbox | `MediaResults` | Full job state snapshot at a `state_version` |

The system has no separately named domain events such as `JobStarted`, and it is **not** event
sourced. Each claim, completion, failure, retry or cancel emits one `result` snapshot with a
monotonically increasing `state_version` (event-carried state transfer). Producer authority is not
part of the schema. Queue resource policies and per-handler IAM roles enforce it: a direct
`SendMessage` from any other principal was refused on all three queues **[AWS]**.

**Context-map relationships.**

- **Customer/supplier.** Media is the customer: it states what to process. Processing is the
  supplier and owns the answer.
- **Translation on both sides.** Media builds a `submit` envelope from its asset and pinned source,
  and turns each result into its own projection and public status. Processing turns each command
  into `Job`, `Attempt` and `SubmissionGuard` rows.
- **Published language.** `contracts/v1.py`, `contracts/gateway.py`, the two OpenAPI 1.0.0
  documents, and frozen fixtures that a contract change must update in the same pull request.

**Interaction with producers and consumers.** The platform roles from the briefing map onto the
design as follows.

| Platform role | As built | How it interacts |
|:-------------|:---------------------------------|:------------------------------------------------------|
| Seed | An owned video asset and its processing job (`Asset` plus `Job`, linked by `asset_id`) | Created by finalize; the single shared identifier across contexts |
| Producers | The web app (one file at a time) and the Publisher CLI (batches) | Public API only: reserve → direct S3 POST → finalize; status, retry, edit, delete |
| Consumers | Owners playing their own output | Presigned MP4 with range requests; HLS playlist through Media; segments by 307 redirect to presigned S3 URLs |
| Integrators | Developers building new clients | Two OpenAPI documents, `contracts/`, and the Publisher as reference client. The Publisher has 0 imports from service code and 0 database credentials, enforced by a test. |
| Operators | The team | CD workflow, release and restore CLI, evidence harnesses; V2-live launches encoders automatically |
