# Solution Overview

This section describes the solution **as built** at the delivered engineering source. The proposal used synchronous `SubmitJob`, Redis/RQ and a service token. Major changes and
their rationale are recorded in `docs/architecture/decisions.md` and summarised here. Decision identifiers AD-01 to AD-29 retain the register's numbering. AD-30 and AD-31 continue
that sequence for the report's load-distribution and database alternative analyses; these two
report decisions are recorded in section 3.2.1. Historical receipts remain dated evidence,
separate from the enabled source configuration described here.

Evidence labels used in this report:

- **[AWS]**: recorded in a live cloud receipt.
- **[Local]**: tests on real PostgreSQL 16 and FFmpeg, with Moto standing in for S3 and SQS.
- **[Code]**: read from source or the rendered CloudFormation template.
- **[NOT_RUN]**: implemented, never run against AWS.

## Logical Architecture & Design

**Architecture views.** Each view answers a different question while keeping the same names,
identities and ownership boundaries.

| View | Question answered | Report home / course connection |
|:---------|:------------------------------------------|:----------------------------------------------|
| Context and scenarios | Who uses the platform, for what? | Introduction and use-case models; ARCHSS / SAD |
| Logical and source structure | Which responsibilities and interfaces collaborate? | This section, tiers and components; ARCHSS / 4+1 logical and development concerns |
| Domain and consistency | Why these contexts and aggregate boundaries? | Platform Design; Platform Engineering |
| Runtime and trust | Who authorizes, commits and publishes? | Identity and intake flows here; Detailed Design; SAD / SDP |
| Deployment and capacity | Where do artifacts execute, and how is load bounded? | Physical Architecture; Cloud Native Solution Design |
| Information | What persists, with which keys and rules? | Persistence Design; Platform Engineering / SAD |
| Delivery and verification | How are changes admitted, released and checked? | DevOps; DevSecOps |

These are view correspondences, not full conformance claims for C4, 4+1 or arc42. Static source
organization and delivery activities answer separate concerns.

The architecturally significant elements, their types and their providers are listed below.
"Team 17" marks custom code written in this project. "Inherited" marks code reshaped from the
FlickPond baseline.

The logical view (Figure {@fig:arch-logical}) groups these elements into tiers. The two domain services each
have their own API, domain and persistence layers. Their reusable contract and technical libraries are copied into each image at build time;
the domain models and databases remain separate.

| Element | Type | Provider | Responsibility |
|:--------------------|:-----------|:------------|:-------------------------------------------------|
| FlickPond web app (`frontend/`) | Custom browser SPA (plain JavaScript, vendored hls.js and Plyr) | Team 17, adapted from inherited UI | Register, log in, direct upload, status polling, MP4/HLS playback, retry, edit, delete |
| Publisher CLI (`publisher/`) | Custom Python client (stdlib plus `httpx`) | Team 17 (new) | Bulk publish, status, output and retry through the public HTTPS API only |
| Media Management (`media/`) | Custom FastAPI service and Lambda handlers | Team 17 | Accounts, ownership, upload grants and verification, the public job view, playback signing, deletion |
| Media authorizer (`media/authorizer.py`) | Custom Lambda REQUEST authorizer | Team 17 (part of Media) | Verifies the session cookie against the current user row; returns the trusted actor |
| Processing (`processing/`) | Custom FastAPI service and Lambda handlers | Team 17 | Jobs, attempts, leases, retry and cancel, output descriptors, recovery, encoder launch |
| Finite encoder (`processing/worker/`, `media_engine/`) | Custom container task | Team 17; FFmpeg command builders inherited and reshaped | Claims one attempt, verifies the pinned source, encodes MP4 and the HLS ladder, writes outputs |
| Shared contract and technical libraries (`contracts/`, `delivery/`, `runtime_support/`) | Custom libraries copied into both images | Team 17 | Versioned envelope and actor contracts, outbox/inbox and SQS adapters, Lambda DB sessions and settings |
| Operator and delivery tooling (`scripts/aws/v1/`, `scripts/ci/`) | Custom Python CLIs and shell | Team 17 | Template rendering, deploy, session, release and restore, evidence harnesses, CD admission |
| FFmpeg and ffprobe | COTS open source | FFmpeg project (Debian package) | Probing and transcoding |
| FastAPI, Pydantic, SQLAlchemy, Alembic, asyncpg, boto3, PyJWT, bcrypt | Open-source libraries | Python community | Web framework, validation, ORM, migrations, PostgreSQL driver, AWS SDK, JWT, password hashing |
| Relational database (PostgreSQL 16) | Managed service | AWS (Aurora Serverless v2) | `media_db` and `processing_db`, one cluster each (AD-29) |
| Object storage | Managed service | AWS (S3) | Source, output and frontend buckets |
| Messaging | Managed service | AWS (SQS) | Four queues and four dead-letter queues with short encodes enabled |
| Edge, compute and operations | Managed services | AWS (CloudFront, API Gateway, Lambda, ECS Fargate, EventBridge, SSM, Secrets Manager, ECR, CloudWatch, Budgets, IAM) | Section 3.2 |
| Source control, CI/CD and scanners | SaaS and open-source tools | GitHub (Actions, OIDC); Aqua Trivy, gitleaks, OWASP ZAP, Ruff | Section 5 |

![Figure {#fig:arch-logical}. Logical responsibilities, provided HTTP interfaces, asynchronous business messages and owned data. The Media authorizer is a synchronous Gateway dependency for both protected APIs.](figures/arch-logical.png){width=15cm}

Media and Processing exchange business commands and state snapshots through SQS. Neither
business handler calls the other's API or database. A protected Processing HTTP request still
depends on Media's authorizer and current User lookup. Media also reads S3 objects for upload
verification, derived edits and playback. Encoders commit state and result intent in Processing
SQL; a Processing relay publishes the results. No encoder sends queue messages directly.

**Public request and identity boundary.** The normal path is CloudFront `/api/*` → API Gateway
HTTP API → the selected API's `live` alias. For protected routes, Gateway first invokes
`MediaAuthorizer`, a **Media-owned Lambda REQUEST authorizer** attached through
`GatewayAuthorizer` (`scripts/aws/v1/definitions.py`). Cookie is the identity source, payload
format is 2.0, responses are simple authorization responses and the result-cache TTL is zero.
The Lambda verifies the JWT and looks up the current Media `User`; missing identity, an
unsupported current role or lookup failure denies access (`media/authorizer.py`).

Gateway invokes the selected API separately. `contracts/gateway.py` strips supplied owner/role
headers, rebuilds Cookie from Gateway's cookie list and injects the authorizer's `Actor`.
Media additionally revalidates the cookie/current User and checks agreement with Actor
(`media/api/deps.py`); Processing trusts only the adapter-injected Actor (`processing/auth.py`).
Gateway-scoped Lambda invocation policies support this boundary. TTL zero avoids cached
permission decisions; it does not revoke a request already executing. Health and Media
register/login/logout bypass the hook. CloudFront is the normal entry; the regional
`execute-api` endpoint remains reachable directly.

![Figure {#fig:arch-authorizer}. Gateway invokes the Media-owned REQUEST authorizer before its API integration. Media revalidates current identity; Processing uses the trusted Actor.](figures/arch-authorizer.png){width=15cm}

**Durable upload and edit acceptance.** Both paths adopt a source before publishing a command
(Figure {@fig:arch-intake-handoff}). Direct upload uses reserve → client POST to S3 → finalize.
Finalize verifies bytes outside the adoption transaction, then locks and rechecks the reservation,
stores its VersionId, creates Asset and stages `submit` in the **same SQL commit**
(`media/services/direct_intake.py`). Edit checks an owned completed parent, copies its validated
primary output to a new source and pins it. Adoption commits the new Asset, SourceVersion,
optional RequestKey and submit outbox together; the original Asset stays intact
(`media/services/v1_lifecycle.py`). The staged-object ledger supports cleanup if copying or
adoption is interrupted.

`MediaRepair` later relays the command. `delivery/sql.py` commits an outbox claim, sends to SQS
outside that transaction, then fences its send acknowledgement. Processing commits its inbox,
guard, Job/Attempt and result/work outboxes before acknowledging the command. Its handler can
publish after that commit in the same invocation; repair continues after an outage
(`media/handlers.py`, `processing/handlers.py`). HTTP response and relay scheduling have no
fixed relative order. Uncertain sends may repeat, so inbox identity checks and lifecycle fences
are required. Detailed Design expands the operation-level collaborations.

![Figure {#fig:arch-intake-handoff}. Upload and edit converge on SQL adoption plus outbox intent, followed by relay, SQS and the Processing inbox. SQS publication is outside the adoption transaction.](figures/arch-intake-handoff.png){width=15cm}

### Key Architectural Decisions

The significant decisions reflected in the logical view are summarised below. AD-01–29 retain their register identities; the descriptions
clarify the implemented mechanisms and the alternatives relevant to this report.

| Identifier | Decision | Rationale and trade-off | Status |
|:------|:-----------------------|:-------------------------------------------------------|:---------|
| AD-01 | Extract **Processing** as the only new business service; Identity and Delivery stay inside Media | Processing has its own rules (claim, lease, attempt), lifecycle and CPU-bound scaling profile. Every playback or retry decision needs owner and asset together, so splitting Identity or Delivery out would turn single-database joins into cross-service calls. Four services were rejected as more contracts and operations than the need justifies. | Kept; boundary rationale below |
| AD-02 | **Database per service**: `media_db` and `processing_db`, separate migration histories and roles (`*_runtime` DML only, `*_migrator` DDL, `*_owner` no login) | A real ownership boundary at low cost. Trade-off: V1 put both databases on one Aurora cluster, so logical ownership was real but failure isolation was not; since 21 October each service has its own cluster (AD-29). | Kept (hosting refined by AD-12 and AD-29) |
| AD-09 | **API Gateway HTTP API with a Media-owned Lambda authorizer**; the Gateway adapter builds the actor only from the authorizer context | Processing trusts the owner identity without holding Media's JWT secret or user table. TTL 0 requires a fresh authorization lookup for each protected request; Media also revalidates. In-flight requests retain their earlier authorization. The cost is a synchronous Media lookup even for Processing HTTP requests. | New (supersedes AD-06 service token) |
| AD-11 | **SQS with an SQL outbox and inbox** in both databases, replacing Redis/RQ and synchronous `SubmitJob` | No always-on broker, and failure isolation: Media accepts uploads while Processing is down. The SQL-to-SQS handoff is not atomic, so repair is part of the design. Delivery is at least once, so duplicates are normal and consumers deduplicate. | New (supersedes AD-03; changes AD-04) |
| AD-14 | **Direct-to-S3 intake**: a presigned, owner-scoped reservation, then a finalize step that verifies size, SHA-256 and file signature at a pinned S3 VersionId | No 100 MiB body passes through Gateway or Lambda, and the bytes that were verified are exactly the bytes encoded. Trade-off: a two-step protocol; the client hashes the file first, and versioned buckets need cleanup. | New (changes AD-05) |
| AD-21 | **Media-owned projection** of Processing state, fenced by `state_version` and attempt | Media answers status and signs playback without querying Processing. The view is eventually consistent. Older or identical snapshots are no-ops; conflicting equal-version content is rejected. Higher versions still pass source, identity, attempt and transition checks (`media/projections.py`). | New |
| AD-24 | **`contracts/` as published language and reused contract values** | At this source, producers emit version 1 and `accepted_versions()` returns only `{1}`. Additive N/N-1 evolution is the release policy; its two-version behavior applies when version 2 exists. Shared code alone does not establish formal Shared Kernel governance. | New |
| AD-26 | Retired peer-HTTP and Redis/RQ code **quarantined in `legacy/`** and excluded from images by a build-time check | The submission shows no dead dependency between the services. Trade-off: the legacy package and its CI lane remain to maintain. | New |

### Tiers and Layers

| Tier | Elements | Layers and modules |
|:----------|:---------------------|:--------------------------------------------------------|
| Client | Browser SPA, Publisher CLI | Presentation only. Both call the same public API. The browser uploads bytes straight to S3 with a presigned POST. |
| Edge | CloudFront, API Gateway, Media authorizer | TLS termination, routing (`/api/media/*`, `/api/processing/*`), identity, stage throttle |
| Application | Media Management, Processing | **API layer**: `media/api/*`, `processing/v1_api.py`; transport is FastAPI behind `contracts/gateway.py`. **Domain and service layer**: `media/services/direct_intake.py`, `v1_lifecycle.py`, `media/projections.py`; `processing/messaging.py`, `lifecycle.py`, `launcher.py`. **Messaging layer**: `media/messaging.py`, `processing/messaging.py` over `delivery/`. **Persistence layer**: models, repositories and Alembic migrations per service. **Shared libraries**: `contracts/`, `delivery/`, `runtime_support/`. |
| Execution | Lambda handlers, Fargate encoder | Queue consumers, one-minute repair ticks, ECS and S3 event handlers, the launcher, the encoder and the short-encode Lambda (`processing/worker/` with `media_engine/`) |
| Data | Aurora, S3, SQS | `media_db`, `processing_db`; source, output and frontend buckets; commands, standard/short work and results queues |

Figures {@fig:arch-media-components} and {@fig:arch-processing-components} expand the layers
into actual modules and exports. Media reuses repository helpers for owned lookup and replay;
both services also query SQLAlchemy records directly. Storage/subprocess adapters perform I/O;
`media_engine` builds commands and parses probe data without I/O. Interface symbols name
provided exports, rather than additional Python Protocol classes. These are component views,
with the use-case sequences developed separately in Detailed Design.

```{=openxml}
<w:p><w:r><w:t>LANDSCAPE-START</w:t></w:r></w:p>
```

![Figure {#fig:arch-media-components}. Media components: API entry points, adoption/projection policy, repository helpers, owned SQL and storage/messaging adapters.](figures/arch-media-components.png){width=23cm}

![Figure {#fig:arch-processing-components}. Processing components: command and lifecycle policy, shared encoder pipeline, storage/subprocess adapters and launcher capacity control.](figures/arch-processing-components.png){width=23cm}

```{=openxml}
<w:p><w:r><w:t>LANDSCAPE-END</w:t></w:r></w:p>
```

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
| Dispatch | Stage standard/short work using source size, feature flag and prior Lambda execution history | `messaging.emit_state` → `short_lane.work_lane` inside the state transaction | Processing |
| Standard capacity | Reconcile SQL backlog, visible standard work, tasks and reservations; reserve at most three slots | `ProcessingLauncher` Lambda | Processing |
| Short execution | Claim, download, probe admission, encode or fenced standard-lane redirect | `ProcessingShortEncoder`, Worker image, mapping cap 2 | Processing |
| Standard execution | Long-poll, claim at most one Attempt, probe/encode/upload and fenced finish | Finite Fargate task, Worker image, 2 vCPU / 4 GiB, cap 3 | Processing |
| Messaging | Envelope validation, outbox, inbox, SQS lanes, DLQ tooling | Library in both images | Shared libraries |
| Operations | Template, deploy, release and restore, evidence | CD runner or operator station | Platform |

Media and Processing are the two business subsystems. API, repair, consumer and encoder
processes are execution roles of their owning context. Four Media functions use MediaImageUri;
six Processing functions use ProcessingImageUri. Processing's short Lambda and finite Fargate
encoder both use WorkerImageUri. Separate images and triggers do not introduce additional
business contexts. Section 3.2 maps these artifacts to nodes, aliases and authorities.

### Platform Design

Domain-driven design explains the boundary requested in F-01 and developed after the
26 October feedback. Capabilities were grouped by vocabulary, invariants and required local
consistency, then checked against code (`docs/architecture/ddd.md`; reviewed
`report-notes/W2.md`). Lambdas and tables implement these responsibilities within the contexts.

**Deriving the bounded contexts.**

| Capability | Vocabulary and rule | Required consistency | Context and boundary rationale |
|:-----------------|:--------------------------------|:--------------------------------|:--------------------------------------------|
| Account and ownership | User, current role, owner | Current User and owner-filtered Asset lookup | **Media Management** keeps account/access decisions near owned assets. Separate Identity would add a boundary without a separate implemented identity model. |
| Source adoption and edit | UploadReservation, verified pin, derived Asset | Reservation/new Asset/submit intent, or derived Asset/pin/request key/intent, commit locally | **Media Management** owns which bytes are accepted. Separate Upload would split the adoption transaction and require another durable handoff. |
| Status and playback | Public job, projection, playback link | Validate Processing state into an owned read model; authorize against Asset plus projection | **Media Management** keeps delivery as an access/view capability. A separate Delivery context would add remote coordination to every owned playback decision. |
| Execution and recovery | Job, Attempt, lease, heartbeat, outputs | Current Attempt/token/deadline and result/work intent agree at commit | **Processing** owns execution vocabulary and CPU-bound capacity independently of intake. A single service could implement both models, but would couple their execution and change responsibilities. |
| Pre-Job cancellation | SubmissionGuard, tombstone | Cancellation must survive a later or reordered submit | **Processing** owns durable execution refusal even before a Job exists. The guard is local policy support, not a third service. |

Media owns users, assets, accepted sources and public projections in `media_db`. Processing
owns jobs, attempts, leases, outputs and execution recovery in `processing_db`. Neither holds the
other's database credentials. Processing stores owner/asset UUIDs without Media foreign keys;
Media holds Processing identities in its projection. The split costs asynchronous integration
and operational coordination, while allowing independent business state and execution recovery.

![Figure {#fig:arch-context-map}. Context map: commands cross to Processing, results return through Media validation/mapping, and work remains inside Processing. PL denotes the published message language; U/D is scoped to the result model.](figures/arch-context-map.png){width=15cm}

**Context-map relationships.** `contracts/v1.py` publishes Envelope and Source. Processing
translates commands in `messaging.handle_command`; Media's `projections.apply_result` validates
source, identity, attempt and output namespace, then maps the snapshot to its public model.
This incoming validation/mapping acts as an anti-corruption layer. Processing is upstream and
Media downstream for the **result vocabulary**; command direction does not imply a universal
upstream relation. Shared libraries establish code reuse, while Customer/Supplier and Shared
Kernel would additionally require governance agreements. Those formal patterns are not assumed.
Actor is a separate trusted API-context value, not part of the queue envelope.

**Ubiquitous language.** Asset is an owned uploaded or edit-derived video; its UUID is Media's
public `job_id`. Processing's actual ORM root is `Job`, with a distinct UUID and at most one Job
per `asset_id`; `ProcessingJob` names a response DTO. An Attempt has its own UUID plus a positive
per-Job number. `source_revision` is an integer, whereas S3 `version_id` identifies the exact
object version. A source pin also includes bucket, key, SHA-256, byte size and media type.
A lease is the token/expiry/deadline stored on Attempt and judged on the database clock.
The projection is a validated Media snapshot, never a shared Job object.

**Media domain model and invariants.** Asset is the principal business aggregate root. It owns
accepted source identity and operations; an edit-derived pin is a `SourceVersion` persisted value
record keyed by Asset. `contracts.v1.Source` is the frozen value object carrying the six pin
fields. Direct uploads retain their pin on UploadReservation. User and pre-adoption
UploadReservation have independent lifecycles, so neither is nested as an Asset child
(Figures {@fig:arch-media-asset} and {@fig:arch-media-intake}).

![Figure {#fig:arch-media-asset}. Media Asset root, typed source attributes and owned pin value; UUID references connect independent roots without sharing domain objects.](figures/arch-media-asset.png){width=15cm}

![Figure {#fig:arch-media-intake}. Independent Media identity and intake roots. A reservation exists before its eventual Asset; finalize spans both records in one local transaction.](figures/arch-media-intake.png){width=15cm}

The Media rules are enforced by `media/services/direct_intake.py`, `v1_lifecycle.py` and
`media/repositories/assets.py`:

- Owner-filtered access returns 404 to another owner. User has unique email and a checked stored
  role (`user` or `operator`); the authorizer maps either to the API Actor role `publisher`.
- Reservation identity is unique per `(owner_id, request_id)`; replay must match its request
  hash. The 15-minute grant can be adopted only after byte verification and an expiry recheck.
  A finalized reservation must hold a non-null S3 version pin.
- Adoption commits Asset/source authority and submit intent together. Source revision and size
  are positive; service paths preserve the accepted pin. Editing creates a new Asset referring
  to its parent by UUID, with a copied/pinned source and normalized operations.
- Retry requires Media's failed projection and stages intent; Processing owns the actual new
  Attempt. Delete commits an Asset tombstone, cleanup intent and cancel outbox together.

**Processing domain model and invariants.** Job is the aggregate root for its numbered Attempt
history and current execution authority. Attempt is a member entity with its own identity and
lifecycle. Source data and output descriptors are embedded values; Output is a local Pydantic
DTO serialized to JSON, not another table (Figure {@fig:arch-processing-job}).

![Figure {#fig:arch-processing-job}. Processing Job root and Attempt entities, with typed lease attributes and output values. Current-attempt membership and lifecycle ordering are checked by service functions.](figures/arch-processing-job.png){width=15cm}

`processing/messaging.py` and `processing/lifecycle.py` enforce the following rules:

- Unique `Job.asset_id` permits at most one Job per Asset. A repeated submit must match the
  canonical source/operations identity. Owner and source are checked before execution.
- Attempt numbers are positive and unique per Job. `lock_pair()` locks Job, reads Attempt and
  verifies current membership. A new claim **acquires** a token and DB-clock lease; heartbeat
  and finish require the token to remain live and within the fixed deadline.
- A finite task binds to at most one Attempt. Retry creates a new numbered Attempt; replay
  returns the current Attempt. Probe rejection can create a successor through the fenced
  redirect described in section 3.2, without reusing the claimed Attempt.
- Successful finish requires one primary output and optionally one HLS manifest, with positive
  sizes, digests and current-attempt object namespaces. Old tokens cannot finish a successor.
- State version increases with emitted state. Transitions commit state and outgoing intent
  together. A pre-Job cancel persists a SubmissionGuard tombstone, so late submit cannot
  resurrect execution. A tombstoned Media Asset likewise ignores late non-cancel results.

[Execution authority and cancellation model](figures/arch-processing-authority.png). Local Claim value, lease-fencing module, output cleanup ledger and independent pre-Job cancellation root. Lease authority is local execution state, not a queue credential.

**Supporting consistency boundaries.** The ORM records declare fields and constraints; service
functions enforce the business rules. Root marks express lifecycle and consistency ownership.
Local finalize spans reservation/new Asset, and command handling can span guard/Job. These
transactions remain inside one context; none spans both databases.

| Boundary / record | Identity and invariant | Enforcement |
|:--------------------|:---------------------------------------|:------------------------------------------|
| Media request/projection | RequestKey PK `(owner_id, operation, request_key)` maps a request hash to Asset; ProcessingProjection is keyed by Asset, with unique internal Job UUID | Replay helpers and `apply_result`: older/identical results are no-ops; conflicting equal versions fail; higher versions pass transition/source checks |
| Media source cleanup | CleanupIntent is keyed by Asset; StagedObject by source key and can exist before Asset | Tombstone/cancel confirmation and repeated cleanup preserve authority over uncertain or late writes |
| Processing cancellation/binding | SubmissionGuard is keyed by asset with nullable local Job FK; AttemptTask is keyed by Attempt with unique task name | Guard owner check and tombstone; atomic claim binding prevents two executor identities sharing an Attempt |
| Processing retry/state | RetryRequest has unique `(job_id, request_id)`; JobMessaging is keyed by Job with `state_version: int` | Retry and `emit_state` commit Attempt/version/outbox changes together |
| Owned delivery ledgers | Each context has separate inbox/outbox rows, `message_id: UUID` PK and body hash | `delivery.sql.accept/stage/publish_due`; same ID/body is a replay, changed body is a conflict |
| Launcher technical control | Singleton `LauncherControl.id = 1`; reservation token PK and unique `started_by` | `_reserve` serializes capacity before RunTask; ambiguous replies retain slots; reservations are separate from Attempt claims |

[Typed delivery ledgers](figures/arch-delivery-ledgers.png). Typed local inbox/outbox records. Reused delivery code operates on separate owned rows; SQL state and intent commit before the external send.

[Launcher control and reservations](figures/arch-launcher-control.png). Processing capacity-control records and invariants. The technical transaction boundary supports finite execution without creating another business context.

**Domain changes and messages.** The platform records current state, rather than an event-sourced
history. There are no separately persisted `AssetUploaded` or `JobStarted` event classes.
Accepted Processing changes emit a full `result` snapshot: submit, claim, success/failure,
retry, cancel, interruption and redirect. Heartbeat emits no result; repair can republish work
without a new domain change. Five message kinds occupy four transport lanes when short execution
is enabled:

| Kind / intent | Logical queue | Producer → consumer | Contents / cause |
|:----------------|:--------------------------|:-----------------------------------------|:---------------------------------------|
| `submit` | `processing-commands` | Media adoption outbox, relayed by MediaRepair → ProcessingCommands | Source pin and operations for a newly accepted Asset |
| `retry` | `processing-commands` | Media retry outbox, relayed by MediaRepair → ProcessingCommands | Failed projection authorizes intent over the accepted source |
| `cancel` | `processing-commands` | Media tombstone outbox, relayed by MediaRepair → ProcessingCommands | Empty payload; source absent in the current producer; Job ID if known |
| `work` | `processing-work` | Processing outbox/relay → finite Fargate encoder | Queued current Attempt, source and operations; internal to Processing |
| `work` | `processing-work-short` | Processing outbox/relay → ProcessingShortEncoder | Same work contract, selected by dispatch; internal to Processing |
| `result` | `media-results` | Processing state outbox/relay → MediaResults | Status, outputs, error and attempt number at a state version |

Envelope declares `schema_version: int`, `message_id: str`, `kind: str`, `owner_id: str`,
`asset_id: str`, `job_id: str | None`, `attempt_id: str | None`, `state_version: int`,
`source: Source | None` and `payload: dict`. UUIDs serialize as strings. Source contains
`bucket/key/version_id/sha256/content_type: str` and `size_bytes: int`. Queue bodies carry
identities and descriptors, never media bytes, credentials or signed playback URLs. The special
cancel-before-submit result has no Job/Attempt/source, version zero and payload
`status="cancelled"`, `cancellation_confirmed=true`, `command_message_id=<UUID>`; it confirms
an existing guard tombstone rather than inventing a Job.

Queue policies and per-handler IAM roles establish producer authority; schema checks alone do
not authenticate senders. The earlier AWS SendMessage denial receipt covered the three original
queues. Four-queue authority here describes the enabled source configuration, not a new AWS test.

**Platform producers and consumers.**

| Platform role | As built | Interaction |
|:-----------------|:--------------------------------------|:------------------------------------------------|
| Seed | Owned Asset plus its Processing Job, linked by `asset_id` | Upload/finalize or edit adoption creates the source of processing value; Job has a distinct internal UUID |
| Producers | Web app, one file at a time; Publisher CLI, batches | Public HTTPS API for reserve/finalize/status/retry/edit/delete; bytes use the granted direct S3 POST |
| Consumers | Owners playing their own processed output | Signed MP4 with Range; HLS playlist through Media and segment redirects to signed S3 URLs |
| Integrators | Developers building additional clients | Two OpenAPI documents, published contracts and Publisher reference client; tests enforce no service imports or DB credentials in Publisher |
| Operators | Team 17 | Delivery/session/release/restore tooling and evidence harnesses; unattended launch is a Processing execution role |
