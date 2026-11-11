### Persistence Design

**Owned relational schemas.** Media and Processing each own a PostgreSQL 16 database on a separate
Aurora Serverless v2 cluster (AD-29). Ordered migrations give eleven application tables per
database at heads `media_0008` and `processing_0007`, excluding `alembic_version`. The schemas
follow this checkout's SQLAlchemy records and migrations (`media/models.py`,
`media/upload_models.py`, `media/projection_models.py`, both `messaging_models.py` files,
`processing/models.py`, `processing/launcher_models.py` and both `migrations/versions/` folders).

Figures {@fig:data-media-main}–{@fig:data-delivery-schema} select typed columns and declared
relationships. The dictionaries retain all 172 columns, 61 PK/FK/unique/CHECK constraints and
twelve explicit indexes, including both physical copies of the delivery tables.

![Figure {#fig:data-media-main}. Media database: selected typed intake, source-pin and projection fields; only declared local foreign keys are connected.](figures/data-media-main.png){width=15cm}

![Figure {#fig:data-media-support}. Media database: request, cleanup and orphan-write records; grey boxes repeat referenced keys.](figures/data-media-support.png){width=15cm}

![Figure {#fig:data-processing-main}. Processing database: selected typed Job/Attempt, retry and cancellation-guard fields. The current-attempt FK is deferred and non-unique.](figures/data-processing-main.png){width=15cm}

![Figure {#fig:data-processing-support}. Processing database: cleanup, state-version and task-binding records.](figures/data-processing-support.png){width=15cm}

![Figure {#fig:data-processing-launcher}. Processing database: optional launcher singleton and durable RunTask request, with unique token and startedBy identities.](figures/data-processing-launcher.png){width=15cm}

![Figure {#fig:data-delivery-schema}. Identical inbox/outbox schemas exist independently in each database; no shared table or cross-database transaction is implied.](figures/data-delivery-schema.png){width=15cm}

Cross-context owner/asset/job UUIDs carry identity without foreign keys. In Media,
`upload_reservations.asset_id` is unique but has no Asset FK; a reservation precedes its Asset.
`assets.source_asset_id` is also a plain UUID. Processing's nullable `submission_guards.job_id`
is non-unique. `jobs.current_attempt_id` is non-unique and DEFERRABLE INITIALLY DEFERRED: SQL
allows the Job/first Attempt insert cycle, while `processing/lifecycle.py:lock_pair` checks that
the current Attempt belongs to that Job.

Database bootstrap creates `*_owner` (no login), `*_migrator` (inherits owner) and `*_runtime`
(DML plus sequence use). `PUBLIC` has no access; login roles cannot connect to the other database;
connections require verified TLS (`scripts/aws/v1/bootstrap.py`). Recorded AWS checks refused
cross-database runtime login and runtime DDL **[AWS]**.

**Compact physical data dictionaries.** Each row names one table; comma-grouped column names
share the following type. `?` marks nullable; all other columns are NOT NULL. `=value` is a SQL
server default; omitted defaults are supplied by callers or Python, not SQL. `PK`, `UK`, `FK`
and `IX` denote primary, unique, foreign and explicit index definitions. All FKs use ON UPDATE
NO ACTION and ON DELETE NO ACTION unless CASCADE is shown. PK/UK backing indexes are implicit.
`timestamptz` means timestamp with time zone; unbounded `varchar` remains distinct from `text`.

Media (`media_db.public`, head `media_0008`):

| Table / purpose | Columns: name(s): SQL type | Keys, checks and explicit indexes |
|:--|:--|:--|
| `staged_objects` — Crash-safe orphan ledger for uncertain source writes. | `key: text`; `created_at: timestamptz`; `write_uncertain: boolean=true` | `PK (key)` |
| `users` — Account identity, credentials and role. | `id: uuid`; `email: varchar(320)`; `password_hash: text`; `role: varchar(20)`; `created_at: timestamptz` | `CHECK role IN ('user', 'operator')`; `PK (id)`; `UK (email)` |
| `assets` — Owned immutable asset intake and submission state. | `id, owner_id, source_asset_id?, processing_job_id?: uuid`; `filename, source_media_type: varchar(100)`; `source_key, last_submit_error?: text`; `source_revision, source_size_bytes, submit_attempts: integer`; `source_sha256: varchar(64)`; `operations: jsonb`; `submission_state: varchar(20)`; `submitted_at?, next_submit_at, created_at, deleted_at?: timestamptz` | `CHECK source_revision >= 1 AND source_size_bytes > 0`; `CHECK submission_state IN ('pending', 'submitted', 'error')`; `FK (owner_id) → users.id`; `PK (id)`; `UK (source_key)`; IX `assets_pending_due(submission_state,next_submit_at)`; IX `ix_assets_owner_id(owner_id)` |
| `cleanup_intents` — Deletion progress and retained rescan authority. | `asset_id: uuid`; `processing_deleted_at?, source_deleted_at?, next_try_at: timestamptz`; `attempts: integer`; `last_error?: text` | `FK (asset_id) → assets.id`; `PK (asset_id)` |
| `request_keys` — Owner/operation/request identity and immutable request hash. | `owner_id, request_key, asset_id: uuid`; `operation: varchar(20)`; `request_hash: varchar(64)`; `created_at: timestamptz` | `FK (asset_id) → assets.id`; `FK (owner_id) → users.id`; `PK (owner_id, operation, request_key)` |
| `retry_intents` — Retained legacy peer retry bookkeeping. | `id, asset_id: uuid`; `confirmed_at?, rejected_at?, created_at, next_try_at: timestamptz`; `attempts: integer`; `last_error?: text` | `FK (asset_id) → assets.id`; `PK (id)`; IX `ix_retry_intents_asset_id(asset_id)` |
| `asset_source_versions` — Version pins for edit-derived copied sources. | `asset_id: uuid`; `bucket, key, version_id: text`; `sha256: varchar(64)`; `size_bytes: integer`; `content_type: varchar(100)` | `FK (asset_id) → assets.id`; `PK (asset_id)` |
| `upload_reservations` — Direct-upload idempotency, immutable version pin and orphan rescan authority. | `id, owner_id, request_id, asset_id: uuid`; `request_hash, sha256: varchar(64)`; `filename, content_type: varchar(100)`; `bucket, key, version_id?: text`; `size_bytes: integer`; `expires_at, finalized_at?, created_at, cleanup_checked_at, cleanup_retired_at?: timestamptz`; `cleanup_next_at: timestamptz=now()`; `cleanup_attempts: integer=0` | `CHECK finalized_at IS NULL OR (version_id IS NOT NULL AND version_id NOT IN ('', 'null')) [ck_upload_reservations_finalized_has_pin]`; `FK (owner_id) → users.id`; `PK (id)`; `UK (asset_id)`; `UK (key)`; `UK (owner_id, request_id)`; IX `ix_upload_reservations_cleanup_due(cleanup_next_at) WHERE cleanup_retired_at IS NULL`; IX `ix_upload_reservations_expires_at(expires_at)`; IX `ix_upload_reservations_owner_id(owner_id)` |
| `processing_projections` — Media-owned result snapshot. | `asset_id, job_id, attempt_id?: uuid`; `attempt_number, state_version: integer`; `status: varchar(20)`; `source, outputs: jsonb`; `error?: text`; `result_hash: varchar(64)` | `CHECK state_version >= 0 AND attempt_number >= 0`; `CHECK status IN ('queued', 'processing', 'done', 'failed', 'cancelled')`; `FK (asset_id) → assets.id`; `PK (asset_id)`; `UK (job_id)` |

Processing (`processing_db.public`, head `processing_0007`):

| Table / purpose | Columns: name(s): SQL type | Keys, checks and explicit indexes |
|:--|:--|:--|
| `jobs` — Processing authority for one asset, source, operations, current attempt and output descriptors. | `id, asset_id, owner_id, current_attempt_id: uuid`; `source, operations: jsonb`; `request_hash: varchar(64)`; `source_url, error?: varchar`; `source_url_expires_at, created_at, updated_at, deleted_at?: timestamptz`; `status: varchar(16)`; `outputs: jsonb='[]'::jsonb` | `CHECK status IN ('queued', 'processing', 'done', 'failed') [ck_jobs_status]`; `FK (current_attempt_id) → attempts.id; DEFERRABLE INITIALLY DEFERRED [fk_jobs_current_attempt]`; `PK (id)`; `UK (asset_id)`; IX `ix_jobs_owner_id(owner_id)` |
| `attempts` — Numbered execution attempt, token lease, deadline and recovery schedule. | `id, job_id, lease_token?: uuid`; `attempt_number: integer`; `state: varchar(16)`; `queued_at, started_at?, finished_at?, heartbeat_at?, lease_expires_at?, deadline_at?, next_dispatch_at?: timestamptz`; `error?, dispatch_error?: varchar`; `dispatch_count: integer=0` | `CHECK attempt_number >= 1 [ck_attempts_number]`; `CHECK state IN ('queued', 'processing', 'succeeded', 'failed', 'abandoned', 'cancelled') [ck_attempts_state]`; `FK (job_id) → jobs.id`; `PK (id)`; `UK (job_id, attempt_number) [uq_attempts_job_number]`; IX `ix_attempts_recovery(state,next_dispatch_at)` |
| `submission_guards` — Durable owner/asset submission/cancellation boundary, including cancel-before-submit. | `asset_id, owner_id, job_id?: uuid`; `deleted_at?: timestamptz` | `FK (job_id) → jobs.id`; `PK (asset_id)` |
| `retry_requests` — Stable retry identity maps to the already-created attempt. | `id, job_id, request_id, attempt_id: uuid` | `FK (attempt_id) → attempts.id; ON DELETE CASCADE`; `FK (job_id) → jobs.id; ON DELETE CASCADE`; `PK (id)`; `UK (job_id, request_id)` |
| `cleanup_intents` — Deletion progress and retained rescan authority. | `attempt_id, job_id: uuid`; `next_try_at, retired_at?: timestamptz`; `tries: integer=0`; `last_error?: varchar`; `created_at: timestamptz=now()` | `FK (attempt_id) → attempts.id; ON DELETE CASCADE`; `FK (job_id) → jobs.id; ON DELETE CASCADE`; `PK (attempt_id)`; IX `ix_cleanup_intents_due(next_try_at,attempt_id) WHERE retired_at IS NULL` |
| `job_messaging` — Monotonic result/work state version per Job. | `job_id: uuid`; `state_version: integer=0` | `FK (job_id) → jobs.id`; `PK (job_id)` |
| `attempt_tasks` — One finite task-name binding per Attempt and unique task name. | `attempt_id: uuid`; `task_name: varchar(256)` | `FK (attempt_id) → attempts.id`; `PK (attempt_id)`; `UK (task_name)` |
| `launcher_control` — Optional unattended launcher singleton enable/session gate. | `id: integer=nextval('launcher_control_id_seq'::regclass)`; `enabled: boolean=false`; `enabled_at?, session_end_at?: timestamptz`; `updated_at: timestamptz=now()` | `CHECK id = 1 [ck_launcher_control_singleton]`; `PK (id)` |
| `launch_reservations` — Optional unattended launcher durable ECS request replay and capacity reservations. | `token: varchar(64)`; `started_by: varchar(36)`; `status: varchar(16)=reserved`; `payload: jsonb`; `deadline_at, sent_at?, launched_at?, settled_at?: timestamptz`; `reserved_at: timestamptz=now()`; `task_arn?: varchar(512)`; `claimed?: boolean`; `last_error?: varchar(120)` | `CHECK status IN ('reserved', 'launched', 'stopped', 'released') [ck_launch_reservations_status]`; `PK (token)`; `UK (started_by)`; IX `ix_launch_reservations_open(reserved_at) WHERE status IN ('reserved', 'launched')` |

The common delivery definition contributes two tables to **each** database:

| Table / purpose | Columns: name(s): SQL type | Keys, checks and explicit indexes |
|:--|:--|:--|
| `message_inbox` — Received message identity plus canonical body hash. | `message_id: uuid`; `body_hash: varchar(64)`; `received_at: timestamptz=now()` | `PK (message_id)` |
| `message_outbox` — Canonical envelope and durable relay claim/replay schedule. | `message_id, claim_token?: uuid`; `body_hash: varchar(64)`; `queue: varchar(40)`; `body: jsonb`; `next_try_at, sent_at?: timestamptz`; `tries: integer=0`; `last_error?: varchar` | `PK (message_id)`; IX `ix_message_outbox_due(next_try_at)` |

The ORM omits the `ix_attempts_recovery` and `ix_cleanup_intents_due` declarations and uses a
Python default of 1 for the `launcher_control.id` singleton; the dictionary follows the migration
DDL for those indexes and the SERIAL default. `retry_intents` and
`jobs.source_url/source_url_expires_at` are retained legacy structures; native intake writes an
empty URL and database time, using the pinned JSONB source. The launcher tables are used only by the optional unattended launcher.

**Transactions and concurrency.** Every transaction is local to one database. SQL commits
locally; durable outbox intent, inbox deduplication and repair bridge the SQS boundary. DP-2
(section 6.5) gives the full relay protocol.

| Boundary | Locks and checks | Commits together | Failure or replay |
|:--|:--|:--|:--|
| Media adopt (`direct_intake.finalize`) | Verifies the explicit S3 VersionId outside row locks, then locks and rechecks `UploadReservation` | Pin, new `Asset`, submit `MediaOutbox` (`delivery/sql.py:stage` never commits for its caller) | Reservation `(owner_id,request_id)` plus request hash returns the adopted Asset |
| Media edit adoption (`v1_lifecycle.edit`) | Locks the staged row; verifies and pins the copied source inside the transaction | Derived `Asset`, `SourceVersion`, optional `RequestKey`, submit outbox; staged row removed | `RequestKey(owner_id,operation,request_key)` replays the winner; a loser discards its copy |
| Relay (`delivery.sql.publish_due`) | One due row `FOR UPDATE SKIP LOCKED`; UUID claim token and DB-time reservation | Claim; a second transaction records success or backoff only if the token still matches | SQS I/O runs outside SQL locks; an uncertain send repeats with the same message ID |
| Processing accept (`messaging.handle_command`) | Locks `SubmissionGuard` before an existing `Job`; `delivery.sql.accept` compares canonical body hashes | Inbox row, domain changes, work/result outbox | Same ID and body is a no-op; same ID with a different body raises `MessageConflict`; retry-before-submit rolls back for later redelivery; `RetryRequest(job_id,request_id)` fixes the successor |
| Claim, heartbeat, finish (`processing/lifecycle.py`) | `lock_pair` locks the Job and checks its current Attempt; token, lease and deadline use `clock_timestamp()` | Lease state; terminal result and result outbox | A stale token, expired lease or passed deadline cannot heartbeat or finish; `AttemptTask` allows one task binding per Attempt |
| Media result (`media/messaging.py:consume_result`) | Checks owner, source, Job and Attempt; accepts only a newer valid `state_version` | `MediaInbox` row and projection | Identical equal-version content is ignored; conflicting content is rejected and rolled back with the inbox (`media/projections.py:validate_transition`) |

Encoding and downloads run between these transactions. Consumers acknowledge only after commit:
command ACK follows committed acceptance, standard workers delete work after a durable outcome or
SQL-proved staleness, the short Lambda returns partial batch failures, and result ACK follows
Media's inbox/projection commit
(`processing/handlers.py`, `processing/worker/sqs.py`, `processing/short_encoder.py`,
`media/handlers.py`).

**JSONB value schemas.** These are application contracts, not SQL JSONB CHECK constraints.

| Value / columns | Shape and validation boundary |
|:--|:--|
| Source — `jobs.source`, `processing_projections.source` | `{bucket:str,key:str,version_id:str,sha256:str,size_bytes:int,content_type:str}`. All six required; nonempty/non-`null` pin, lowercase 64-hex digest, strict size 1..100 MiB. `contracts/v1.py:Source` differs from legacy `processing.schemas.Source`. Workers check owner prefix and downloaded bytes. |
| Operations — `assets.operations`, `jobs.operations` | `[{operation,params}]`: clip `{start:number,end:number}` with `0≤start<end`; crop `{x:int≥0,y:int≥0,w:int>0,h:int>0}`; upscale/downscale `{height:int>0}`; convert `{format:"mkv" or "mp3"}`. No duplicate kinds or simultaneous upscale/downscale; probe-dependent bounds checked at execution (`media/schemas/edit.py`, `processing/schemas.py`, `processing/worker/tasks.py`). |
| Outputs — `jobs.outputs`, `processing_projections.outputs` | `[{kind:"primary" or "hls_manifest",object_key:str,media_type:str,size_bytes:int or null,sha256:str or null}]`. DTO permits null size/hash; successful `lifecycle.finish` requires positive size, digest, unique kinds, exactly one primary and current Attempt namespace. |
| Projection row | Job/Attempt IDs, attempt number, state version, status, Source, outputs/error and semantic result hash. Source/outputs are JSONB; other fields are typed columns. Media's local read model is independent of Processing's Job. |
| `message_outbox.body` | Canonical Envelope below; `delivery/envelope.py` normalises known fields before hashing. Inbox retains only identity/hash/time. |
| `launch_reservations.payload` | RunTask request: `{cluster,taskDefinition,launchType:"FARGATE",count:1,clientToken,startedBy,networkConfiguration:{awsvpcConfiguration:{subnets,securityGroups,assignPublicIp}},overrides:{containerOverrides:[{name,command}]}}`; replayed from SQL (`processing/launcher.py:run_payload`). |

**SQS wire model.** `contracts/v1.py:Envelope` requires all ten keys below, even when values
are nullable; UUIDs are JSON strings, version fields are strict integers, and schema version 1 is
emitted and accepted.

```text
Envelope = {schema_version:1, message_id:UUID, kind:submit|retry|cancel|work|result,
            owner_id:UUID, asset_id:UUID, job_id:UUID|null, attempt_id:UUID|null,
            state_version:int>=0, source:Source|null, payload:object}
```

| Kind | Producer shape / required binding |
|:--|:--|
| `submit` | Media: `{operations:[Operation]}`; Source required. Normal finalize emits null Job/Attempt and version 0; Processing assigns Job identity. |
| `retry` | Media: `{}`, stored Source; durable Job retains operations. Consumer uses optional `payload.request_id`, otherwise `message_id`, as retry identity. Envelope permits null Source; consumer compares it when supplied. |
| `cancel` | Media: `{}`, null Source; Job/Attempt may be null. `SubmissionGuard` persists cancel-before-submit. |
| `work` | Processing: `{operations:[Operation]}`; Job/Attempt/Source required. Stable UUID derives from Attempt and state version; worker compares stored acceptance before S3 GET. Both work lanes use this schema. |
| `result` | Processing: `{status,outputs:[Output],error:str or null,attempt_number:int≥0}` with Job/Attempt/Source. Status is queued/processing/done/failed/cancelled; cancellation derives from `Job.deleted_at`, not `jobs.status`. |

Cancel-before-submit instead produces version 0 with null Job/Attempt/Source and exactly
`{status:"cancelled",cancellation_confirmed:true,command_message_id:UUID}`, confirming a durable
guard; Media matches the retained cancel command before authorising source cleanup
(`processing/messaging.py:_cancel_locked`, `media/projections.py:confirm_cancellation`). DLQs
retain the same body.

**Object storage.** Source version pins and output Attempt namespaces serve different purposes:

| Object | Exact key layout and authoritative identity |
|:--|:--|
| Direct source | `staging/{owner_id}/{reservation_id}/source`; adopted in place, with VersionId on finalized `UploadReservation`. |
| Edit source | `sources/{owner_id}/{asset_id}/source`; verified copy of parent's primary, with VersionId on `SourceVersion`. |
| Primary output | `jobs/{job_uuid}/attempts/{attempt_uuid}/primary.{mp4,mkv,mp3}`; extension follows operations, default MP4. Attempt UUID is not attempt number. |
| Optional HLS | Same Attempt prefix plus `hls/master.m3u8`, `hls/v{n}/index.m3u8`, `hls/v{n}/seg%05d.ts`; unedited inputs only, master uploaded last. |
| Frontend | `index.html`, `<stem>.<SHA256-prefix10>.<js/css>`, `vendor/...`; manifest records type, cache control, size, SHA-256 and MD5 (`scripts/aws/v1/frontend.py`). |

Output descriptors have no output VersionId. Fenced SQL finish determines which Attempt's
objects can be published. HLS names are validated before playback. Cleanup enumerates versions
and delete markers and retains rescan authority for late writes (`processing/worker/tasks.py`,
`media_engine/hls.py`, `processing/recovery_v1.py`, `media/recovery_v1.py`).

**What persists, and for how long.** These are the values configured in the template and code. The
lifecycle of this deployment as a whole is set by AD-08 (fresh demonstration data only) and AD-27
(the persistent environment is torn down once, after 16 November 2026).

| Data | Persists beyond | Period configured |
|:--------------------|:----------------|:------------------------------------------------------------|
| Session (JWT cookie) | One request | 1 hour (`jwt_ttl_seconds` 3600); not stored server-side |
| Upload grant | One request | 15 minutes; an expired reservation is rescanned for late writes and retired after a clean scan beyond a one-day horizon |
| Signed playback URL | One request | At most 900 seconds (`signed_url_ttl_seconds`), shortened to remain within the signing credentials' lifetime |
| Accounts | Session | Until environment teardown. No account deletion feature or purge schedule exists |
| Assets, sources and outputs | Session | Until the owner deletes the asset. Deletion is a tombstone; every source and output version is then deleted asynchronously. No age-based expiry and no S3 lifecycle rule are configured |
| Jobs, attempts and tombstone rows | Session | Until environment teardown; no hard-purge job |
| Outbox and inbox rows | Transaction | Until environment teardown; sent rows are kept for replay; no pruning job |
| SQS messages | Transaction | 7 days (DLQs 14 days); visibility: base 420 s, short queue 960 s, Fargate receive override normally 60 s; redrive after 5 receives |
| Lambda and task logs | Request | 7 days |
| Aurora backups | n/a | 1-day automated backup retention on each cluster; the pre-split snapshot of the original cluster is kept, and one final snapshot is kept at teardown |
| CI and CD artifacts | Workflow run | 7, 14 or 60 days, depending on the artifact |

**Information architecture: data inventory and classification.** The team uses four levels:
**Restricted** (credentials, keys and secrets), **Confidential** (personal data and owners'
content), **Internal** (operational and processing metadata) and **Public** (published static
assets). Shared controls (session cookie, encryption, IAM and network) are in section 4.3; the
table keeps the controls specific to each group.

| Data group (classification) | Format and store | Group-specific controls | Rationale and trade-off |
|:--|:--|:--|:--|
| Accounts and authentication (Confidential; hashes and secrets Restricted) | `users` rows (UUID, email, bcrypt hash at cost 10, role `user` or `operator`) in `media_db`, for unique constraints and joins with asset ownership; stateless HS256 JWT in the session cookie; signing secret as an SSM SecureString | Only Media roles read the JWT secret and Media DSN. With authorizer cache TTL 0, each protected request reads the current user row, and role checks use that identity (`media/authorizer.py`). Password bytes are length-limited before hashing. | Cognito would add MFA and recovery flows but a new dependency and token format; the inherited account model was kept, with verification at the edge (AD-09). |
| Owner media content (Confidential) | Accepted video sources of at most 100 MiB in the allowed types. Encoded outputs have no configured 100 MiB cap: the primary is MP4 by default, or MKV/MP3 for conversion; unedited inputs can also produce HLS playlists and segments. Versioned S3 buckets. | Public access blocked, TLS-only bucket policies, SSE-S3. Presigned POST fixes key, content type and length range. Downloads use owner-checked presigned GET links valid for at most 900 s, shortened when the signing credentials expire sooner; HLS segments use a 307 redirect to a fresh signature. CORS admits only the frontend origin. The worker reads only the source bucket, after checking the owner and source binding. | S3 stores video bytes; PostgreSQL stores transactional metadata and descriptors. Versioning gives each source an immutable VersionId. Proxying bytes through the API would exceed Gateway/Lambda payload limits; presigned URLs are bearer capabilities, so their lifetime is short. |
| Asset and upload metadata (Internal; original filenames Confidential) | `assets`, `upload_reservations`, `asset_source_versions`, `request_keys`, `cleanup_intents`, `staged_objects` and `processing_projections` in `media_db`; JSONB operations and outputs | Owner filter on every query, foreign IDs return 404. CHECK constraints enforce the pinned-source rule (`ck_upload_reservations_finalized_has_pin`) and status sets. Idempotency keys make finalize, edit and retry safe to repeat. | Media keeps a projection instead of querying Processing (AD-21): no runtime dependency, at the cost of eventual consistency. |
| Processing job data (Internal) | `jobs`, `attempts`, `submission_guards`, `retry_requests`, `attempt_tasks`, `job_messaging`, `cleanup_intents`, `launcher_control` and `launch_reservations` in `processing_db`; JSONB source and outputs | Only Processing roles hold its runtime DSN. Commands for an existing Job must match its owner and asset; supplied Job IDs and source descriptors must also match. A cancel can instead tombstone an owner-bound `SubmissionGuard` before a Job exists. Native workers require the durable source and current-attempt binding before claiming execution. | Leases, row locks and `SKIP LOCKED` need a transactional store with a trustworthy clock; the store comparison is AD-31 (section 3.2.2). |
| Messages in transit (Internal) | Envelope v1 (above) in SQS Standard queues and DLQs, plus `message_outbox` and `message_inbox` | Validation rejects credential/token/media-byte-like keys and HTTP(S) URL strings. Resource policies deny `SendMessage` to all but the listed producer roles, and receive/delete to all but the listed consumer roles. | FIFO queues would add ordering and deduplication at lower throughput and with message-group design; inbox and version fences already tolerate duplicates and reordering. |
| Secrets and configuration (Restricted) | Four role DSNs and the JWT secret as SSM SecureStrings; the Aurora master password is RDS-managed in Secrets Manager. Four non-secret SSM epochs (`activity/{media,processing}/{touched,quiet}`) let repair skip idle passes (`runtime_support/activity.py`). | Each handler role reads only its own domain's parameters; only the bootstrap operator reaches the master secret. No AWS key is stored in GitHub. | SSM Parameter Store has no per-secret monthly fee but no automatic rotation; rotation is out of scope. Cold starts read the parameters once. |
| Telemetry and delivery evidence (Internal) | CloudWatch logs (bounded, redacted failure events), metrics and alarm state; Actions artifacts (7–60 days); sanitized receipts under `docs/results/` and `docs/execution/aws/v1/evidence/`; private versioned S3 bucket for CD state | Signed URLs, cookies, secrets and account IDs are stripped before commit. The state bucket is private because it holds the smoke account's credentials. | Seven-day logs keep cost and exposure low; committed receipts cover later reconstruction. |
| Static frontend (Public) | HTML, CSS and JavaScript with content-hashed names in a private S3 bucket behind CloudFront origin access control | Integrity comes from the deploy pipeline; the bucket is not directly public. | No material trade-off. |

### Detailed Design

Three representative collaborations are summarised here at class/object level. Section 6.4
contains the complete per-use-case analysis and design models; section 6.5 explains the design
patterns.

**Upload, process and play (UC-1–UC-3).** Figure {@fig:arch-intake-handoff} locates the handoff.
Bytes go straight to versioned S3 under an `UploadReservation`, and `direct_intake.finalize`
adopts them as above. Processing accepts the command into a queued `Job` and `Attempt`,
`short_lane.work_lane` chooses the lane, a worker claims under a DB-clock lease, and
`lifecycle.finish` commits the terminal result; public status stays `accepted` until Media
projects it. Figures {@fig:uc1-design-class},
{@fig:uc1-design-upload}, {@fig:uc2-design-class}, {@fig:uc2-design-intake},
{@fig:uc2-design-execution} and {@fig:uc3-design-results} in section 6.4 give the typed records,
operations and exceptions. `test_finalize_pins_the_exact_version_it_verified`,
`test_finalize_intent_rolls_back_with_adoption_and_commits_once` and
`test_success_output_namespace_validation_and_atomic_terminal_result` verify the pin, the atomic
adoption and the terminal commit (`tests/v1/test_direct_intake_s3.py`,
`test_media_messaging_sql.py`, `test_messaging_sql.py`).

**Edit-derived intake.** `media/api/v1_jobs.py:edit` calls `v1_lifecycle.edit`, which resolves
request replay and checks an owned, nondeleted completed parent with a primary output.
`intake.stage` commits a `StagedObject` before copying. A copy transaction locks the parent and
staged row, copies the primary through `Storage.copy_output_source` and records writer
completion. The adoption transaction then locks the staged row, creates and flushes the derived
`Asset`, verifies and pins the copied source through `direct_intake.pin_copied_source`, writes
`SourceVersion` and the optional `RequestKey`, stages submit and removes the staged row in one
commit (Figure {@fig:data-edit-sequence}).

![Figure {#fig:data-edit-sequence}. Edit copies the parent's primary, then verifies and pins it inside the adoption transaction that commits Asset, SourceVersion and submit intent.](figures/data-edit-sequence.png){width=14cm}

Unlike direct finalize, pin verification happens **inside** edit adoption. The `MediaRepair`
handler relays the submit command only after the adoption commit, possibly before HTTP 202 reaches
the caller; Figure {@fig:dp2-solution-sequence} shows the relay and Processing inbox. A failed copy
or adoption keeps its cleanup authority, and a losing keyed edit discards its copy and replays the
winner (`test_edit_local_projection_adoption_and_submit` and
`test_uncertain_copy_keeps_cleanup_and_never_submits` in `tests/media/test_v1_projection.py`).

**Stored-source retry (UC-4).** When execution authority expires,
`processing/recovery.py:recover_expired` abandons the Attempt and fails the Job under the Job
lock. `v1_lifecycle.retry` checks the owner, failed projection, stored pin and optional
`RequestKey`, then commits the retry command. Processing's `_retry_locked` creates the next queued
Attempt for a new `(job_id,request_id)`, keeping source and operations; a replay returns the
current Attempt. Figures {@fig:uc4-design-class}, {@fig:uc4-design-successor} and
{@fig:uc4-design-fences} in section 6.4 show the records, the successor transaction and the fences
that stop a superseded `Claim` from finishing
(`tests/v1/test_messaging_sql.py:test_retry_idempotency_and_cancel_fence_old_and_current_attempts`).

Independent release (UC-7) is described in Continuous Delivery (section 5) and its class/object
models in section 6.4; DP-1 in section 6.5 explains reservation and recovery-journal choices.
