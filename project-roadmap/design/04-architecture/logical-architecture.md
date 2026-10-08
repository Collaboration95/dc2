# Step 04 — logical architecture

Designed on 9 October 2026; reconciled with owner step 05; not implemented or measured.

## Step 04: logical architecture designed

Draft architecture prepared for team review on 9 October 2026. All proposed components, decisions and checks are designed, not implemented or measured. This task changes documentation only. The local baseline is Media_player 885453726d629c524bf511d665311863d9bc70a5, selected in D-01; no upstream comparison or Git operation is required.

Team17-Proposal.docx remains the authoritative proposal. F-01 records lecturer acceptance and asks for a detailed DDD suitability argument; acceptance is not runtime proof. Earlier D-03 restricted its own step 02 turn; the current user explicitly authorises steps 03–05. This directory provides the step 04 part only.

P-01 Maya and P-02 Arun own and review their own content. P-03 Jules integrates the same public API; P-04 Sam operates releases and worker capacity. These are fictional planning personas, not application role additions. No shared team ownership, learner access, LMS, public discovery or new dashboard is introduced. [P2 §1.2–1.4; F01; BS]

## Inherited architecture observed in the current code

The browser calls the existing FastAPI entrypoint through the frontend/proxy. API routes handle account sessions, owner checks, upload, job reads/retry/edit/delete, operator compatibility and HLS delivery. Upload stores a source, commits Job, then publishes its ID to Redis/RQ. Job IDs are public today. [C03; C04; C11; C12]

Separate worker and reaper containers already exist and worker count is configurable. They share the app package, settings, job repository/model, one PostgreSQL DSN and the same storage credentials. jobs.owner_id has a foreign key to users.id. Worker/reaper startup depends on API/migrations. Process separation and worker replication are inherited, not new Project 2 contributions. [C01; C02; C05; C06; C10]

Existing worker logic claims queued jobs, runs FFmpeg, uploads MP4 and best-effort HLS, then records keys and readable outcomes. The reaper has local stale job and orphan source checks. Its default 30-minute lease and 60-minute orphan grace do not establish the proposal’s 5-minute/2-minute recovery targets. The frontend retry button still reuploads lastFile while the backend supports stored-source retry. [C06–C09; C12 lines 410–412]

## Why two services fit the domain

Asset acceptance, immutable source revision, account ownership and playback authorisation form the user-facing consistency boundary. Identity, Media and Delivery use the same owner and asset rules and change with the product. Keeping them together in MM avoids a distributed permission lookup for every playback request. [P2 §2.3; BS; AD-01]

Processing has a different lifecycle and consistency boundary: a Job is queued, processing, done or failed; an Attempt needs a valid live claim; only its winning completion can publish Output references. Its FFmpeg/queue/reaper changes do not define an Account or playback policy. The asset and owner IDs are plain references across services. An explicit contract translates Asset into SubmitJob rather than sharing ORM/domain models. [P2 §2.3; C02; C05–C07; U04]

A modular monolith would reduce communication and operational work and remains a credible simpler alternative if API reuse alone were the objective. The accepted contribution also requires owned migrations and a P-only release; the shared database/code boundary does not demonstrate those. Four services would add identity/media/delivery contracts without distinct enough rules or project evidence to justify their cost. The selected two-service boundary must still be checked against the detailed step 03 model and actual release/security results. Worker scaling is supporting evidence, not the whole DDD argument. [F01 F-01; P2 §1.4, AD-01, UC-7]

## Logical responsibility and dependency map

Each service exposes an application boundary and owns its domain and infrastructure adapters. API, worker, reconciliation and reaper are process roles; PostgreSQL, Redis and object storage are infrastructure; Account/Asset and Job/Attempt/Output are logical models. These categories must not be counted as separate microservices.

MM calls the private P API for submit/status/retry and compatibility operations. P calls MM’s scoped internal source-access API only to refresh source capability. This reverse dependency does not create a circular authorisation lookup: MM checks its own Asset, and P checks live attempts locally. No database transaction is held while waiting for another service. [P2 §2.2–2.3; U04]

| Component | Responsibilities | Dependencies / release ownership |
| --- | --- | --- |
| MM public API | Accounts/cookie sessions; upload validation; Asset acceptance; owner-filtered public projection composed from live Processing reads; authorised output/HLS delivery; compatibility facade. | Own media_db/source adapters and private P client. MM release. |
| MM pending-submission reconciler | Recover durable pending Asset submissions and correlate internal Job UUID. Submitted status is composed through live owner-filtered Processing reads. | MM-owned pending state and P HTTP contract; no Redis/processing_db access. MM process/release. |
| P private API | Authenticate scoped caller; idempotent submit; reserve queued Attempts at Submit/Retry commit; owner-scoped Job queries and compatibility commands. CancelAssetJob uses stable asset_id and owner-bound submission guard. | processing_db and P-owned Redis producer. P release. |
| P workers | Claim an already-reserved queued Attempt; validate live attempt; source URL refresh; standard MP4/best-effort HLS; inherited edit-only MKV/MP3; conditional output completion. | processing_db, RQ, MM source-access, presigned source GET, output-write storage. P process/release; count can change. |
| P reaper/reconciler | P-owned missing queue and stale attempt reconciliation; cleanup of unpublished attempt outputs under scoped permission. | processing_db, Redis, separate output cleanup role. Source orphan cleanup moves to MM. P process/release. |
| Infrastructure | One PostgreSQL server/two databases; Redis/RQ; private source/output buckets; HTTPS edge. | Shared runtime resources, not independent business services. Exact hosting products deferred. |

## Tiers and internal layers that can adapt to the code

Presentation tier: web UI and Publisher CLI. Both use the same HTTPS entrypoint, accounts and workflow, with cookie authentication; neither imports services, accesses databases/queue, or calls P directly. The CLI maintains the existing session with a cookie jar. [P2 §1.3, §3.3; C11; U04]

Service tier: MM and P expose contract adapters; application operations coordinate repositories and ports; domain objects enforce local ownership, submission and attempt rules. Infrastructure adapters implement PostgreSQL persistence, P HTTP, Redis/RQ, storage signing and FFmpeg. Dependencies point from adapters into application/domain rules; exact module names need not match inherited folders. FFmpeg is a P adapter, not the domain model.

Data tier: durable metadata remains in each service’s owned database; source/output bytes remain in private object storage; Redis is a work transport, not the authoritative Job ledger. These tiers are conceptual and may share one host. Introducing layers does not imply another process, container or microservice. [P2 §2.2–2.5; AD-02–AD-03]

## Data, identifier and credential ownership

The accepted public reference is asset_id. Existing /jobs paths and response compatibility fields may keep their legacy names, but their identifier value represents an MM Asset. P assigns a separate internal Job UUID and correlates it with asset_id. No client may use or depend on that internal UUID. Fresh demonstration data avoids reinterpretation of historic public job links. The owner step 05 OpenAPI specifies exact fields/errors. [U04; AD-08]

MM owns durable Asset/submission/correlation state and composes the public read projection from live owner-filtered Processing reads for submitted assets. No stored encode-state/output-ref cache or observation/freshness fields are mandatory. P remains authoritative for Job state and winning durable output refs. Pending Assets return status=queued and submission_status=pending with no output links; submitted dependency failure or a missing Job returns 503 rather than cached success. owner_id and source revision are immutable submission references; no cross-service foreign keys or database reads. [P2 §2.3; AD-02; K05 status-projection, persistence; K05P GET /jobs]

| State / permission | Owner | Boundary rule |
| --- | --- | --- |
| Account; password/session identity | MM / media_db | P holds owner ID reference, no account copy or user FK. |
| Asset; immutable source revision; pending intent; Job correlation | MM / media_db | Intake and submission/correlation records are durable. Compose submitted status and playback refs from live P reads; no mandatory stored encode-state cache or freshness fields. |
| Job; Attempts; published Output refs | P / processing_db | asset_id unique submit key; locally enforced claims; only winning attempt publishes. |
| Owner-bound submission guard / tombstone | P / processing_db | Submit and stable asset-ID Cancel lock the same guard; deleted guard rejects delayed submission; retained throughout demo. |
| Source objects | MM source role | MM writes/reads/signs; P workers have no source credentials and use short-lived GET capability. |
| Output objects | P output-write role; separate cleanup role | Attempt-specific keys; worker writes only; cleanup belongs to P, not source bucket. |
| Playback signing and HLS playlist read | MM output-read/sign role | Separate from source role and output-write credentials; owner authorisation before issuance. |
| Queue/task payload | P only | Redis/RQ credentials never in MM or clients; Job ledger in processing_db. |
| Migrations | Respective service | Separate histories and scoped roles; no runtime superuser or cross-database access. |

## Success path, durable submit and idempotent transport retry

1. Owner logs in through /api/auth; browser and CLI keep the existing HTTPS cookie session. MM validates declared/sniffed video type and measured ≤100 MiB size, writes the private source, then commits Asset(pending), immutable source descriptor and the owner/operation-scoped request key together. New clients retain Idempotency-Key across an uncertain upload response; legacy callers may omit it without a replay guarantee. Storage and SQL are not atomic, so MM owns staged-object and source-orphan cleanup. [C03; AD-03; K05 idempotency, transactions]

2. MM calls POST /internal/v1/jobs with service token, verified X-Owner-Id, asset_id, matching owner_id/source.asset_id, immutable source descriptor, optional ordered operations and fresh source_url/expiry. P commits Job plus first queued Attempt under unique asset_id before enqueueing (job_id, attempt_id) to RQ. The request fingerprint excludes URL and expiry. MM records only internal correlation/submission acceptance after acknowledgement. The client receives 202 {job_id: asset_id}. [AD-03–AD-04; K05P SubmitJob]

3. A lost acknowledgement leaves durable MM intent pending. Replay with the same immutable request and a refreshed URL returns the existing Job/current Attempt; it never creates a second Attempt or implies RetryJob. Missing delivery of a committed queued Attempt is P reconciliation work. During a P outage, valid durable upload is still 202; polling that unconfirmed Asset returns 200 status=queued, submission_status=pending and no output links. This is an MM compatibility state, not proof P has queued a Job. Permanent submission rejection becomes failed/error with a safe reason. [AD-03–AD-04; K05 status-projection]

4. An RQ worker conditionally claims the already-reserved current queued Attempt of a live Job; claim does not mint a new Attempt. It checks live attempt authority locally. The initial source URL is transient; before download or after expiry it can obtain ReadSource through POST /internal/v1/assets/{asset_id}/source-access using the separate reverse token, X-Owner-Id and revision. MM checks its own owner, revision and nondeleted Asset without querying P. The designed source GET grant expires after 15 minutes. Standard intake produces MP4 plus best-effort HLS; MKV/MP3 exist only for inherited edit conversion compatibility. Attempt-specific output writes precede conditional winning completion and durable reference publication. [AD-05; K05 storage, transactions; K05M source-access]

5. Owner GET /api/jobs/{asset_id} resolves the internal Job correlation and composes a public response from a live owner-filtered P read. List pages MM Assets, then batches submitted Asset IDs by owner. A submitted P outage or missing durable Job returns 503; MM neither serves cached done nor fabricates a new Job. Completed responses translate durable primary output refs into newly signed 15-minute output URLs and an MM HLS route when available. No mandatory encode-state cache, freshness fields or stored expiring URLs. [K05 status-projection, public-routes; K05U GET /jobs]

## Owner-only MP4 and HLS playback

An owner check governs status and each MM HLS request. MM obtains winning durable refs through live P reads for a submitted Asset; unavailable/missing P state returns 503. A fresh primary-output GET URL is a temporary bearer capability, with a 15-minute design default, and never durable state. Standard upload output is MP4; MKV/MP3 primary outputs are inherited edit conversion compatibility only. Cross-owner API rejection and signed URL expiry/tamper are separate checks. Output buckets have no public-read/list policy. [AD-05; K05 storage, status-projection; C09–C10]

MM /jobs/{asset_id}/hls/{path} validates the path within the winning output prefix returned by a live owner-filtered P read for that asset. It reads/serves master and rendition playlist bodies with private, no-store semantics, keeping relative URIs anchored at the authorised MM route. It signs and redirects segments individually. Redirecting a playlist itself would change its relative base to object storage and break HLS; preserve the inherited working pattern. Cookie sessions let the browser revisit MM routes; real browser playback, HTTPS signing endpoint and applicable object endpoint/CORS behaviour require implementation checks. [C09 lines 14–28, 80–121; AD-05]

## Existing client routes and designed compatibility additions

The web and CLI use the existing /api/auth, /api/upload and /api/jobs routes. Public /jobs identifiers mean asset_id. New clients retain an owner/operation-scoped Idempotency-Key for upload, retry and edit. Retry uses the stored source through /jobs/{asset_id}/retry, replacing the current browser reupload. P first looks up retry_request_id: replay returns the existing current result without another transition. A new retry is allowed only from failed and atomically reserves the next queued Attempt/current pointer before enqueueing. An uncertain downstream retry returns 503 and the client retains its key. [C04; C12; K05 idempotency, transactions; K05P RetryJob]

Preserve inherited edit/delete/admin route compatibility in step 05 rather than silently dropping routes already used by the selected baseline. Edit creates a derived MM Asset whose immutable source is copied from the authorised published output, so deleting the original cannot destroy a borrowed source. It submits with a new asset_id; processing-request details are immutable in its fingerprint. This source-copy design and new Asset relationship are designed additions; current code instead borrows the original output key. [C04 edit_job_by_id, _delete_job_and_storage; U04] Preserve only existing edit operation variants, including convert to MKV/MP3; these are not added standard UC-2 outputs or new crop/clip widgets. [K05 public-routes; K05U EditOperation] MM persists the derived Asset’s immutable operations JSON alongside its independent source descriptor and pending intent, so an outage/replay cannot silently submit a plain transcode. Schema/type/size admission failures are rejected before 202; source-dependent edit geometry checks may fail asynchronously as a visible failed Attempt. [K05 persistence, transactions; K05U edit]

MM atomically records its Asset tombstone and cleanup intent before 204, then always cancels by stable asset_id through DELETE /internal/v1/assets/{asset_id}/job with the target owner. A lost Submit acknowledgement therefore does not require a known internal Job UUID. P submission_guards serialises Submit and Cancel using the same owner-bound row: Cancel-first records a tombstone that rejects delayed same-owner Submit with 410; Submit-first cancels/tombstones the Job and schedules owned-output cleanup. Retain guards throughout the demonstration environment. Repeated same-owner cancellation is 204; another owner is 404. MM denies new source/playback grants and cleans its own sources after cancellation prerequisites; P cleans only its outputs. Existing signed capabilities last until expiry/object removal. MM operator routes forward each target owner through scoped APIs, without unscoped Processing operations. Detailed cancellation/cleanup mechanics and tests remain step 06 work. [K05 internal-contracts, persistence, transactions; K05P CancelAssetJob]

## Shared runtime limits and designed quality checks

The logical reference deployment uses one small shared host and one PostgreSQL server with two databases. It has shared host, DB server, queue and storage failure boundaries; no multi-zone/multi-region failover is promised. Separate containers and two databases establish ownership and release boundaries, not physical fault isolation. MM’s P-outage intake scenario assumes MM/media_db/source storage are still functioning. [AD-02; AD-07; P2 §3.5]

Video encoding still competes for finite CPU/memory/I/O. The 1/2/3-worker experiment (30 identical 60-second 720p clips; 2 vCPU each) must record resources and sufficient aggregate capacity. Proposal targets (2 workers ≥1.6×; 3 workers ≥2.1× jobs/minute; decreasing median queue wait; zero failures) are future checks. API polling target p90 ≤700 ms/<1% errors at 50 concurrent callers for 3 minutes and login p90 <2s at 20 concurrent logins also remain unmeasured. [P2 §3.4; BS UC-6]

Step 06 owns durable recovery implementation details: polling cadence, timeouts/backoff, claim/attempt fencing, cleanup races and measured recovery windows. Step 07 owns exact AWS product/SKU, network deployment and cost choices. This step documents logical constraints and validation intent; it neither implements those later steps nor declares their targets met.

## Representative use-case and decision traceability

Business IDs and personas are retained from business-scope.json. The table links the logical design to representative observable checks, not completed evidence. Jules follows the same owner workflow through the published API; Sam remains an operator stakeholder. [BS; P2 §3.2–3.4]

| Use case / persona | Logical route / ownership | Decisions | Implementation evidence to collect |
| --- | --- | --- | --- |
| UC-1 / P-01 Maya, P-02 Arun, P-03 Jules | MM auth+intake → pending Asset → P SubmitJob | AD-01–AD-06, AD-08 | Valid source ≤100 MiB; invalid/anonymous rejection; source+asset durable during P outage; public Asset ID. |
| UC-2 / platform for owners | P claim → source capability → FFmpeg → winning refs | AD-01, AD-03–AD-05 | MP4 playback, best-effort HLS/fallback, attempt fencing, readable failure. |
| UC-3 / owner-viewers | MM owner lookup + live P reads → fresh output URL / MM HLS routes | AD-01–AD-02, AD-05–AD-06 | Pending queued/pending; submitted status from live P; dependency/missing-job 503; cross-owner rejection; expiry/tamper; real browser HLS. |
| UC-4 / Maya, Arun | MM retry → owner-scoped failed-state RetryJob | AD-03–AD-06 | Same source/revision, no browser reupload; retry_request_id replay deduplicates a reserved queued attempt; wrong owner/state rejected. |
| UC-5 / Maya; Jules integrates | CLI cookie jar → same HTTPS MM workflow per file | AD-01, AD-03–AD-06, AD-08 | Every file outcome; no service imports/DB credentials; actual effort/size. |
| UC-6 / Sam | P worker count 1 → 2 → 3; MM unchanged | AD-01, AD-07–AD-08 | Fixed backlog, 2-vCPU caps, measured throughput/wait/failures/resources; existing replication not claimed as new. |
| UC-7 / Sam | Versioned P-only container release/rollback | AD-01–AD-02, AD-06–AD-08 | MM image/media_db unchanged; smoke pass and timed ≤10-minute target; step 07 deployment. |

## AD-01 · Extract Processing as the only new service

Status: designed; not implemented. Owner: Long (architecture documentation); Ibrahim (implementation review); team review pending.

Context: The baseline has separate worker processes, but API, workers and reaper share Job code, credentials and one user-linked database. F-01 asks the team to justify suitable microservices in detailed DDD. Candidate contexts are Identity, Media, Processing and Delivery.

Decision: Combine Identity, Media and Delivery in Media Management (MM); extract Processing (P) as one separately owned/deployed service. MM owns Account, Asset and owner access. P owns Job, Attempt, Output, asynchronous queue/FFmpeg and job reconciliation. Worker/reaper containers are processes within P, not further business services. Separate lifecycle, consistency rules and change ownership justify the boundary; CPU profile supports it but is not its sole justification.

Sources: P2 §1.4, §2.3, AD-01; F01 F-01; C01; C02; C06; BS. Use cases: UC-1, UC-2, UC-3, UC-5, UC-6, UC-7.

Planned implementation checks; no runtime or measurement evidence produced by this documentation task.

| Record field | Details |
| --- | --- |
| Alternatives considered | Keep a modular monolith: simpler calls and transactions, but retain common release/data ownership unless the product only needs internal reuse.<br>Split Identity, Media, Processing and Delivery: small responsibility sets, but adds three boundaries, identity/playback coordination and releases for this team. |
| Positive consequences | Asset acceptance and owner access remain coherent without distributing account rules.<br>P can change FFmpeg, attempt rules and migrations without importing MM models or altering media_db.<br>Both web and CLI reuse the same public workflow. |
| Negative consequences | Extra network contract, authentication and eventually consistent status add work.<br>Same host CPU, storage and database server remain shared failure/resource boundaries.<br>Small team still coordinates two deployable services; service separation alone does not ensure faster processing. |
| Validation to perform | Review aggregates and invariants against detailed step 03 DDD and F-01.<br>Verify MM cannot import P ORM/domain modules or query processing_db; P cannot read media_db.<br>Release P with unchanged MM image/media_db migrations; run web/CLI upload-to-playback contract smoke checks.<br>Compare 1/2/3 worker throughput under CPU caps; record results rather than claim an unmeasured improvement. |

## AD-02 · Two service databases on one PostgreSQL server

Status: designed; not implemented. Owner: Long (architecture documentation); Ibrahim (implementation review); team review pending.

Context: Current jobs.owner_id references users.id within the shared database; API and workers use the same DSN. The proposed services need enforceable data and migration ownership with low operational cost.

Decision: Use one PostgreSQL server with media_db and processing_db. MM runtime role can connect/use only media_db; P API, workers and reaper roles can access only processing_db with permissions appropriate to their process. Each service has its own migration history and migration role limited to its database. Revoke default cross-database CONNECT and broad privileges; runtime roles are not superusers and cannot create roles/databases. owner_id/asset_id in P are opaque identifiers, not foreign keys into MM. No federated query, FDW or shared ORM table.

Sources: P2 AD-02, §2.3; C01 lines 39, 76, 128; C02 lines 50–53. Use cases: UC-1, UC-2, UC-3, UC-7.

Planned implementation checks; no runtime or measurement evidence produced by this documentation task.

| Record field | Details |
| --- | --- |
| Alternatives considered | One database and shared tables: cheap, but permits cross-service joins and couples migrations.<br>Two schemas with broad roles: less setup, but weaker separation if grants remain shared.<br>Separate PostgreSQL servers: independent capacity/failure isolation at greater demonstration cost. |
| Positive consequences | Database permissions make service ownership testable.<br>One server lowers operating cost and setup effort.<br>Independent schema changes are possible within published contract compatibility. |
| Negative consequences | One server outage affects both databases; connections, CPU and I/O compete.<br>Cross-service consistency requires API checks and reconciliation instead of SQL joins.<br>Separate database names alone are insufficient without grants and role checks. |
| Validation to perform | For each runtime/migration credential, prove own allowed operations and denied other-database connection/table access.<br>Inspect role grants for superuser, default CONNECT, public schemas and cross-database extensions.<br>Apply each service migration independently without the other service credentials or migration execution. |

## AD-03 · Synchronous durable submission; asynchronous Redis/RQ processing

Status: designed; not implemented. Owner: Long (architecture documentation); Ibrahim (implementation review); team review pending.

Context: Clients need an immediate accepted-item reference while FFmpeg is long-running. Redis/RQ already queues and executes processing. Upload acceptance must remain durable during a P outage.

Decision: MM writes the immutable source then commits Asset(pending) plus intake request-key intent before attempting synchronous authenticated SubmitJob. P commits a durable queued Job plus first queued Attempt in processing_db; enqueue (job_id, attempt_id) to Redis/RQ only after commit. Queue publication failure leaves accepted recoverable work. MM returns 202 {job_id: asset_id} after durable intake. Pending owner reads return 200 status=queued, submission_status=pending, with no playback links; this is the public intake projection, not confirmation of a P Job. Submitted owner/list reads use live P queries; P dependency outage or a missing submitted Job returns 503. No mandatory stored encode-state cache/freshness fields. Bounded timeouts preserve MM responsiveness. MM never accesses Redis; no event broker.

Sources: P2 AD-03, §3.3–3.4; C03; C06; C08; U04; K05 owner content and OpenAPI, reconciled 9 October 2026. Use cases: UC-1, UC-2, UC-3, UC-5.

Planned implementation checks; no runtime or measurement evidence produced by this documentation task.

| Record field | Details |
| --- | --- |
| Alternatives considered | Synchronous FFmpeg in upload request: simpler chain, but long requests and no independent worker workflow.<br>New event broker between services: decouples delivery but adds new infrastructure/contract operation.<br>Publish directly from MM into P queue: avoids HTTP but exposes worker import paths and couples clients to P internals. |
| Positive consequences | Immediate owner-visible asset reference and durable intake across P outage.<br>Reuse existing RQ/FFmpeg without a new transport.<br>Only P owns task payloads and queue permissions. |
| Negative consequences | DB commit and enqueue are separate actions; reconciliation is necessary.<br>Status polling and submit calls add network latency.<br>Pending admission can build backlog while P is unavailable; durability does not guarantee a finish time. |
| Validation to perform | Stop P, upload valid content, restart MM and verify asset/source/pending survive; restore P and observe submission.<br>Lose queue entry after committed Job and verify eventual enqueue without a second Job.<br>Verify upload returns before FFmpeg completes and MM has no Redis credentials.<br>Measure proposed polling/login targets after implementation; do not infer them from diagram.<br>Verify pending reads are queued/pending without outputs, while submitted dependency failure/missing Job is 503.<br>Verify SubmitJob commits Job and first queued Attempt before enqueue, and claim starts that same Attempt. |

## AD-04 · Idempotency by asset_id with durable reconciliation

Status: designed; not implemented. Owner: Long (architecture documentation); Ibrahim (implementation review); team review pending.

Context: A submit response may be lost after P commits. MM must retry an accepted asset without creating an extra job, and database/queue writes cannot form one distributed transaction. The existing reaper handles some local gaps, not the new MM-to-P pending gap.

Decision: P enforces unique asset_id and an immutable canonical fingerprint of owner, source revision/digest/type/size and ordered operations. source_url and its expiry are excluded. Same-request SubmitJob replay returns the existing Job/current Attempt; changed owner/payload is rejected. MM durably retains pending intent/correlation and resubmits by asset_id. New web/CLI uploads and edits use owner/operation-scoped Idempotency-Key to avoid creating duplicate Assets before SubmitJob. P reserves first queued Attempt in Submit commit. For RetryJob, look up retained retry_request_id before state checks; a replay returns the current result without a new Attempt, while a new failed-state retry atomically reserves next queued Attempt and updates the current pointer before enqueue. Workers claim only the already-reserved current queued Attempt; they do not mint it. P owns missing-delivery/stale-attempt reconciliation and winning-completion fencing, publishing durable refs under attempt-specific keys. MM composes submitted public projections from live P reads, not a required stored status cache. No distributed transaction or event broker. P submission_guards stores an owner-bound row per asset_id and serialises Submit/Cancel on that row; stable asset-ID cancellation can precede Job creation and tombstones reject delayed Submit. Guards remain throughout the demo. MM persists immutable derived-edit operations with the pending Asset for faithful Submit replay.

Sources: P2 AD-04, §3.3–3.4; C05; C06; C08; U04; K05 owner content and OpenAPI, reconciled 9 October 2026. Use cases: UC-1, UC-2, UC-3, UC-4, UC-5.

Planned implementation checks; no runtime or measurement evidence produced by this documentation task.

| Record field | Details |
| --- | --- |
| Alternatives considered | Distributed transaction across both DBs and Redis: complex and incompatible with a small HTTP/RQ boundary.<br>Transactional outbox/event relay: strong delivery bookkeeping, but adds implementation and operations not selected in the proposal.<br>Blind retry without durable intent/uniqueness: may lose submissions or create duplicate work. |
| Positive consequences | Safe submit replay after timeout without a second Job.<br>Durable pending record covers P outage independently of P reaper.<br>No cross-service transaction or event broker; one asset-to-job correlation.<br>Attempt isolation prevents a late attempt from replacing the current published output. |
| Negative consequences | Submission and queue delivery are eventually reconciled; no exactly-once execution is promised. Submitted reads need live P availability and return 503 on dependency failure.<br>Reconciliation scheduling, stale-attempt fencing and cleanup require step 06 implementation.<br>A pending row is not proof of delivery; logging and meaningful outcome visibility remain necessary. |
| Validation to perform | Concurrently replay same asset_id with fresh source URLs: one Job and unchanged identity.<br>Change owner/revision/request under same asset_id: reject without modifying existing job.<br>Drop SubmitJob response after commit: pending MM replay obtains existing Job.<br>Kill MM between intake/submit/ack steps and verify pending work remains recoverable.<br>Race late and winning attempts: only winning refs published; orphan attempt outputs not served.<br>Specify and exercise recovery timings separately in step 06; inherited reaper defaults do not satisfy proposal targets by assertion.<br>Check stable upload/edit request keys select one Asset; changed fingerprint conflicts.<br>Replay retry_request_id after the Job finishes: no new Attempt; changed new retry from nonfailed is 409.<br>Verify claim/enqueue use the current durable attempt_id created at Submit/Retry commit.<br>Race Submit/Cancel in both orders, including lost Submit acknowledgement: cancel by asset_id succeeds, no delayed resurrection, guard remains throughout demo.<br>Restart pending derived edit after source copy: replay retains identical ordered operations; source-dependent geometry failure becomes visible asynchronous failure. |

## AD-05 · Presigned source reads and private output delivery with separate credentials

Status: designed; not implemented. Owner: Long (architecture documentation); Ibrahim (implementation review); team review pending.

Context: Today API and worker MinIO clients use the same bucket credentials. A source URL minted at submit can expire while queued; storing expiring playback URLs would also make successful results brittle.

Decision: Keep private source and output stores with separate permissions. MM source role writes/reads/signs sources; workers receive no source credentials. SubmitJob includes transient source_url and expiry per proposal, both excluded from the immutable fingerprint and not durable source truth. ReadSource grants a single-object GET URL with a 15-minute design default via MM POST /internal/v1/assets/{asset_id}/source-access: reverse scoped service token, X-Owner-Id and revision. MM checks its own owner, revision and nondeleted Asset, accepting no arbitrary URL/bucket/key. P checks its live Attempt locally; no MM callback/cross-DB lookup. Workers validate configured storage origins/prefixes and avoid arbitrary redirects. Workers write only attempt-specific outputs; P cleanup has separate scoped permissions. MM has output-read/sign only, including playlist reads. P persists winning durable Output refs; MM composes submitted responses from live P reads and signs fresh 15-minute primary-output/segment URLs without storing them. Standard intake produces MP4 plus best-effort HLS; MKV/MP3 primary outputs are inherited edit compatibility only. HLS playlists remain on MM owner routes; segment redirects are freshly signed.

Sources: P2 AD-05, §3.3; C07; C09; C10; U04; K05 owner content and OpenAPI, reconciled 9 October 2026. Use cases: UC-1, UC-2, UC-3, UC-4.

Planned implementation checks; no runtime or measurement evidence produced by this documentation task.

| Record field | Details |
| --- | --- |
| Alternatives considered | Shared bucket-wide credentials: easy reuse but worker can access MM-owned source objects.<br>Public source/output buckets: avoids signing but breaks owner access and private storage.<br>Store one submit-time URL permanently: simple payload but queue delay invalidates work. |
| Positive consequences | Workers cannot list/read the source bucket through long-lived credentials.<br>Queue delay and retry can obtain a fresh URL for the same source revision.<br>MP4 data/segments can flow directly from object storage, while HLS playlists retain correct API-relative paths.<br>Output references survive playback URL expiry. |
| Negative consequences | A presigned URL is bearer access until expiry; owner checking governs issuance, not every subsequent object GET.<br>Workers need MM source-access availability to refresh; reciprocal call direction introduces a runtime dependency, but no circular authorisation lookup.<br>Per-bucket roles, correct signing endpoints and HLS session continuity require implementation checks.<br>Attempt output isolation creates orphan cleanup work; worker write-only permissions limit direct output inspection. |
| Validation to perform | Queue until submit URL expires, then fetch through source-access and process successfully.<br>Reject wrong owner/revision, deleted asset, missing/wrong reverse token and arbitrary object-key requests.<br>Prove workers cannot access sources by storage credential and MM cannot write output objects.<br>Expire/tamper playback URL, reject cross-owner API/HLS access, reject playlist path traversal.<br>Play real HLS in browser; master/rendition playlists remain on MM routes and segments use private signed redirects.<br>Verify no URL tokens in durable output records or ordinary logs; signer uses consumer-reachable HTTPS host.<br>Verify source/output grant expiry defaults to 15 minutes and ReadSource response carries expires_at plus immutable descriptor.<br>Reject unconfigured source origins/prefixes and arbitrary redirects; confirm source URLs/expiries are not durable identifiers.<br>Verify standard intake remains MP4/best-effort HLS; MKV/MP3 are only explicit inherited edit conversions. |

## AD-06 · Private internal API with scoped service token and forwarded owner

Status: designed; not implemented. Owner: Long (architecture documentation); Ibrahim (implementation review); team review pending.

Context: Public callers authenticate to MM; P still needs an enforceable caller/owner boundary without sharing users tables. A private network alone does not establish authority.

Decision: MM authenticates browser and CLI through the existing HTTPS cookie session; CLI uses a cookie jar. No new public bearer-token flow. Only MM is publicly routed for /auth, /upload and /jobs. MM-to-P calls carry a scoped service token and owner_id derived from the verified session, never an untrusted public owner header. P authorises service token and filters all GetJob/ListJobs/RetryJob operations by stored owner_id. Submit binds immutable owner+asset. Reverse source-access token is distinct/scoped to that operation; MM checks owner/revision/not-deleted and P owns attempt validation. Internal APIs, queue and DB ports are private; object contents remain private although capability-authorised HTTPS object retrieval is possible. MM authorises existing operator sessions for /admin/jobs, then forwards each target owner and batches reads by owner through the same owner-filtered P API. There is no unscoped P admin operation. Step 05 defines X-Owner-Id and direction-specific scoped service tokens.

Sources: P2 AD-06, §3.3; C04; C11; U04; K05 owner content and OpenAPI, reconciled 9 October 2026. Use cases: UC-1, UC-3, UC-4, UC-5, UC-7.

Planned implementation checks; no runtime or measurement evidence produced by this documentation task.

| Record field | Details |
| --- | --- |
| Alternatives considered | Private network without service authentication: reachable internal caller can issue work.<br>Reuse end-user cookie directly in P: makes P depend on MM session/account implementation.<br>Mutual TLS: stronger peer identity, but adds certificate operations beyond the selected demonstration. |
| Positive consequences | Small boundary that can be exercised with negative tests.<br>P cannot be bypassed by guessing a Job UUID or omitting owner filters.<br>No copied accounts or public authentication protocol addition required for CLI. |
| Negative consequences | Forwarded owner is trusted as asserted by authorised MM; compromised MM credentials remain a trust risk.<br>Static service tokens require secret handling and eventual rotation; full key rotation is out of scope.<br>Private network does not isolate failures or remove need for TLS/public object endpoint design. |
| Validation to perform | Reject missing/forged/wrong-scope token; reject cross-owner read/list/retry.<br>Attempt public access to P, Redis and PostgreSQL: unavailable.<br>CLI completes login/upload/poll/retry with cookie jar; logout/expiry remain explicit.<br>Exercise operator compatibility separately with ordinary user rejection and per-target owner forwarding with no unscoped P API.<br>Verify secrets absent from source/image/logs; deployment injects them. |

## AD-07 · AWS containers in one small environment; product selection deferred

Status: designed; not implemented. Owner: Long (architecture documentation); Ibrahim (implementation review); team review pending.

Context: The accepted proposal commits to AWS and independently deployable containers with private durable storage. Existing containers provide a starting point; a three-member team cannot justify Kubernetes or multiple environments solely for the demonstration.

Decision: Plan one small AWS environment running separate MM and P container release units; P includes API, worker and reaper processes. Preserve developer-local container execution. One PostgreSQL server hosts the two owned databases; media is in private object storage, Redis/RQ stays internal. Logical reference deployment shares one compute host: host outage and CPU/memory/I/O contention affect both services. Only HTTPS application and authorised object-access endpoints are public; internal P API, DB and queue have no public routes. Exact AWS products, host capacity, storage/network topology, secret delivery and SKU/cost decisions are deferred to step 07; this ADR does not select ECS, EC2, Lightsail, RDS, S3 or another product. Per-service versioned release, health checks and upload-to-playback smoke test are planned capabilities.

Sources: P2 AD-07, §2.5, §3.3–3.5; C01; U04. Use cases: UC-6, UC-7.

Planned implementation checks; no runtime or measurement evidence produced by this documentation task.

| Record field | Details |
| --- | --- |
| Alternatives considered | Kubernetes: powerful orchestration but excess operating work for this scope.<br>Multiple environments or multi-zone infrastructure: better isolation at extra cost, excluded from current proposal.<br>One inseparable application image/release: easy operation but cannot demonstrate P-only release. |
| Positive consequences | Builds on existing packaging and limits demonstration operating effort.<br>Independent container releases provide a concrete way to test UC-7.<br>Same logical stack can be rehearsed locally. |
| Negative consequences | Single-host reference deployment is a shared SPOF and resource ceiling; two services are not high availability.<br>1/2/3 workers at 2 vCPU each require enough aggregate host capacity; caps alone do not reserve CPU.<br>P outage intake assumes MM, source storage and media_db remain reachable; host/database/storage outage is broader.<br>No AWS infrastructure, deployment or quality target is proved by this logical design. |
| Validation to perform | In step 07 resolve products/cost/security topology and demonstrate private internal ports plus HTTPS object capability access.<br>Record CPU, memory, queue and storage contention under fixed backlog; verify MM release unchanged.<br>Deploy P version and rollback prior image without MM/media_db change, against proposal ≤10-minute target.<br>Preserve raw smoke/performance/security results; report shared-host limits. |

## AD-08 · Use fresh owned demonstration data

Status: designed; not implemented. Owner: Long (architecture documentation); Ibrahim (implementation review); team review pending.

Context: The team needs repeatable evidence on the selected local baseline, not migration of historic accounts and videos. Existing Job UUIDs and borrowed edit sources would complicate the new Asset model.

Decision: Start the new service databases with new test accounts and team-owned video sources. No historical data migration or reinterpretation of existing Job IDs is required. Public compatibility /jobs/{id} names now carry MM asset_id; P has a separate internal Job UUID. Document this semantic change and keep original materials unchanged. Use identified test fixtures and planned fixed clips; record actual preparation and results later.

Sources: P2 AD-08, §3.5, §4.4; F01 D-01; C03; U04. Use cases: UC-1, UC-5, UC-6, UC-7.

Planned implementation checks; no runtime or measurement evidence produced by this documentation task.

| Record field | Details |
| --- | --- |
| Alternatives considered | Migrate historic users/jobs/storage keys: preserves history but adds mappings, migration testing and ownership risk.<br>Reuse arbitrary third-party data: convenient but unsuitable as owned, repeatable demonstration content. |
| Positive consequences | Keeps project effort on service ownership, contracts and evidence.<br>No historical cross-service foreign-key or job-to-asset migration obligation.<br>Stable demonstration inputs support comparable experiments. |
| Negative consequences | Historical accounts/links are not preserved.<br>New public-ID semantics need compatibility documentation even though data is fresh.<br>Fresh fixtures do not demonstrate production migration or general real-world performance. |
| Validation to perform | Initialise empty databases independently; create/register owners via MM.<br>Show /upload reference equals public Asset ID and differs from internal P Job UUID.<br>Verify demo content provenance and hash/count of fixed experiment inputs.<br>Check original proposal/source files remain unmodified and no migration claim is made. |

## Editable architecture and success-sequence diagrams

The assigned board https://www.tldraw.com/f/0GOUcscLFXmGeNDXAJTx5 contains two rendered editable native-shape pages: inherited versus proposed logical architecture, and upload-to-playback success sequence with optional idempotent replay and private ReadSource refresh. diagram-manifest.json records exact page/root/shape IDs, SVG exports and visual inspection. Native layouts keep the architecture about 1470 px wide; diagram-layouts.json and render-tldraw.js reproduce them. The two Mermaid files retain the fuller semantic sources.

The inherited pane is observed from C01–C12. The proposed pane and sequence are designed, not implemented. Solid HTTP calls denote synchronous request/response; RQ delivery drives asynchronous work; status uses polling rather than events. Shared deployment and PostgreSQL boundaries remain explicit. SVG exports, when available, are renderings of the editable tldraw shapes.

## Design issues and subsequent implementation checks

The chosen architecture decisions are recorded, but the design has no runtime proof. Team review should cross-check step 03 aggregates and step 05 schemas against the IDs, revision and permission rules here.

- Owner step 05 fixes public ID/cookie session, queued/pending representation, live submitted reads/503, source-access, operator target-owner forwarding and inherited edit/delete compatibility. Verify implementation against those OpenAPI schemas; mandatory stored cache/freshness fields are not part of the design.
- Step 06 implements reserved queued Attempt claims, retry_request_id deduplication, fencing/lease, reconciliation/backoff, owner-bound Submit/Cancel guards, stable asset-ID cancellation and orphan cleanup; retain guards throughout the demo and test both race orders. No exactly-once guarantee.
- Source and output grants use the step 05 15-minute design default. Validate refresh/expiry and safe logging during implementation; never log the signed query string. P enforces live attempts locally and MM source-access does not call back to P.
- Validate worker output-write-only permission supports the implemented upload mechanism and separate cleanup role; MM output-read/sign must never acquire output-write.
- Step 07 must resolve exact AWS products, available aggregate CPU for capped workers, TLS/HTTPS object access, private networking, secrets and cost. A single shared host remains a SPOF.
- Evidence pending: independent P release, denied cross-database access, boundary auth/storage tests, real MP4/HLS playback, durable outage/queue-loss recovery and measured proposal targets.

## Source register

Proposal and repository evidence above is local. No GitHub or external reference lookup was needed. Code citations refer to the selected current local baseline; no implementation or Git operation was performed. User contract refinements are marked U04 rather than attributed to the original proposal.

| ID | Local source | Locator / basis |
| --- | --- | --- |
| P2 | project-documentation/Team17-Proposal.docx | §1.1–1.4; §2.2–2.5; AD-01–AD-08; §3.2–3.5 — Authoritative submitted proposal. Read using /tmp/team17-review/Team17-Proposal.txt. Original unchanged. |
| F01 | project-roadmap/records/project-decisions.txt | F-01, D-01 — Lecturer accepts proposal and requests detailed DDD justification. Current local 8854537 supersedes proposal historical baseline 890c5ec. |
| BS | project-roadmap/business-scope.json | P-01–P-04, UC-1–UC-7, exclusions — Fictional planning personas; account-owner playback; no shared team or LMS scope. |
| C01 | Media_player/docker-compose.yml | lines 2–146, 148–228 — API, replicated workers and reaper already run separately; shared DSN, bucket and credentials; worker/reaper startup depends on API. |
| C02 | Media_player/app/models/job.py | lines 13–73 — Job lifecycle, users foreign key, source/output/HLS keys and edit operations share one model. |
| C03 | Media_player/app/api/uploads.py | upload_video; POST /upload — Authenticated type/sniff/size checks, source store, committed Job, then enqueue; returns processing job_id today. |
| C04 | Media_player/app/api/jobs.py | _to_response; get_job_by_id; retry_job_by_id; edit_job_by_id; _delete_job_and_storage; admin routes — Owner-filtered queries, fresh playback URLs, stored-source retry, borrowed output for edit, deletion and operator compatibility. |
| C05 | Media_player/app/repositories/jobs.py | lines 126–233; delete_job; list_stale; mark_stale_failed — Conditional state transitions and existing retry locking. No durable Attempt model in current Job schema. |
| C06 | Media_player/app/worker/tasks.py | lines 88–145 — Claim, encode without DB connection held, then commit output references or readable failure. |
| C07 | Media_player/app/worker/storage.py | lines 183–185, 207–274, 303–335 — Current worker downloads using shared storage client and produces MP4 plus best-effort HLS. |
| C08 | Media_player/app/worker/reaper.py | lines 20–49; Media_player/app/config.py lines 73–75 — Existing stale processing, missing RQ record, and orphan source checks. Defaults: interval 60s, lease 1800s, orphan grace 3600s; these do not prove proposal recovery targets. |
| C09 | Media_player/app/api/hls.py | lines 14–28, 80–121 — Owner route serves playlist bodies; segments use freshly signed redirects. Relative references stay on API origin. |
| C10 | Media_player/app/services/minio_client.py | lines 32–57; Media_player/app/services/output_urls.py lines 18–75 — Internal/public endpoint clients use same credentials today; signature endpoint must be reachable by its consumer. |
| C11 | Media_player/app/api/deps.py | lines 22–41; Media_player/app/api/auth.py register/login/logout — Existing session is an HTTP cookie, not a public bearer flow. |
| C12 | Media_player/frontend/app.js | lines 5–12, 410–412, 473, 1005, 1249, 1390 — Existing routes and edit/delete/admin use; retry button currently reuploads lastFile despite backend stored-source retry. |
| U04 | Current user task/clarification | User instructions for this design task and owner contract clarification, 9 October 2026 — Public asset IDs; cookie jar CLI; pending assets; source_url excluded from fingerprint; reverse scoped source-access token; local attempt validation; isolated storage permissions; edit source copy. |
| K05 | project-roadmap/design/05-contracts/content.json | status-projection, idempotency, storage, transactions, persistence, public-routes — Owner design: live submitted reads/503, pending queued/pending, queued Attempts reserved at commit, 15-minute grants and inherited compatibility. |
| K05U | project-roadmap/design/05-contracts/public.openapi.json | /api public routes; PublicJob; Accepted; EditOperation — Owner public compatibility schema; no mandatory cache/freshness fields. |
| K05P | project-roadmap/design/05-contracts/processing.openapi.json | Submit/Get/List/Retry; stable asset-ID CancelAssetJob; reserved Attempt and durable Output; owner-bound submission guards retained through demo. |
| K05M | project-roadmap/design/05-contracts/media-internal.openapi.json | POST /internal/v1/assets/{asset_id}/source-access; SourceAccess — Private ReadSource capability refresh with reverse token, owner header and revision. |

