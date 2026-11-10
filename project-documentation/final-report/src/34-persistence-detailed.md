### Persistence Design

**Owned relational schemas.** Media and Processing each own a PostgreSQL 16 database on a separate
Aurora Serverless v2 cluster (AD-29). Ordered migration reconstruction gives eleven application
tables per database at heads `media_0008` and `processing_0007`, excluding `alembic_version`.
These schemas adapt the reviewed W4 models and were checked against this checkout's SQLAlchemy
records and migrations, rather than a live Aurora catalogue (`media/models.py`,
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

Migration DDL remains authoritative for `ix_attempts_recovery`, `ix_cleanup_intents_due` and the
`launcher_control.id` SERIAL sequence default. The ORM omits those two index declarations and
uses a Python default of 1 for the singleton. These representation differences do not establish
live schema drift. `retry_intents` and `jobs.source_url/source_url_expires_at` are retained legacy
structures; native intake writes an empty URL and database time, using the pinned JSONB source.
Launcher-table presence alone does not establish runtime activation.

**Transactions and concurrency.** The boundaries are local to one database:

- **Adopt and stage.** `direct_intake.finalize` verifies an explicit S3 VersionId outside row
  locks, then locks/rechecks `UploadReservation` and commits its pin, new `Asset` and submit
  `MediaOutbox` together. Edits pin a copied source within their adoption transaction, described
  below. `delivery/sql.py:stage` never commits for its caller.
- **Publish.** `publish_due` takes one due row with `FOR UPDATE SKIP LOCKED`, records a UUID
  claim token and a DB-time reservation, and commits. SQS I/O occurs outside SQL locks. A second
  transaction locks the row and records success/backoff only if its token still matches.
  Uncertain sends can repeat; retained SQL intent and subsequent successful repair permit
  replay. There is no SQL/SQS or cross-database atomic commit, or unconditional loss guarantee.
- **Accept.** `processing/messaging.py:handle_command` commits inbox acceptance, domain changes
  and work/result outbox rows together. `delivery.sql.accept` compares canonical body hashes:
  same message ID/body is a no-op; same ID/different body raises `MessageConflict`. Reordered
  retry-before-submit rolls back its inbox row, allowing later redelivery. Media similarly
  commits `MediaInbox` and `apply_result` together (`media/messaging.py:consume_result`).
- **Lock and lease.** Command handling locks `SubmissionGuard` before an existing `Job`;
  native claim authorization uses the same order. Direct `messaging.retry_job` locks Job
  directly. `lifecycle.lock_pair` locks Job and reads its current Attempt, checking membership;
  it does not take a separate Attempt row lock. Claim sets its token, lease and deadline from
  `clock_timestamp()`. Heartbeat and finish require the current Attempt, matching token,
  live lease and unexpired deadline against that database clock.
  `AttemptTask` additionally makes task names unique and permits one binding per Attempt.
  Encoding and downloads run between these transactions.
- **Idempotency and projection.** Reservation `(owner_id,request_id)` plus request hash protects
  direct intake; `RequestKey(owner_id,operation,request_key)` protects edit/retry; Processing
  `RetryRequest(job_id,request_id)` protects successor creation. Stable edit/retry/work message
  IDs supplement inbox identity. Media checks owner, source, Job and Attempt, then applies newer
  valid `state_version` snapshots. A new message ID with identical equal-version semantics is
  ignored; conflicting equal-version content is rejected. Conflict rolls back inbox and
  projection together (`media/projections.py:validate_transition`).

Processing's batch handler commits command consumption, attempts best-effort publication, then
returns the batch outcome. ACK requires committed acceptance, regardless of publication success;
`handle_command` itself does not publish. Standard workers delete work after a durable outcome
or SQL-proved staleness; unknown/uncertain work remains retryable. The short Lambda returns
partial batch failures to its mapping. Result ACK follows Media inbox/projection commit
(`processing/handlers.py`, `processing/worker/sqs.py`, `processing/short_encoder.py`,
`media/handlers.py`, `delivery/sqs.py`).

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
are nullable; UUIDs are JSON strings and version fields are strict integers. This checkout emits
and accepts schema version 1. Validation and producer authority
are separate controls.

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
`{status:"cancelled",cancellation_confirmed:true,command_message_id:UUID}`. It confirms a durable
guard. Media matches the retained cancel command before authorising source cleanup
(`processing/messaging.py:_cancel_locked`, `media/projections.py:confirm_cancellation`). DLQs
retain the same body; they introduce no additional kind.

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
| Signed playback URL | One request | 900 seconds (`signed_url_ttl_seconds`) |
| Accounts | Session | Until environment teardown. No account deletion feature or purge schedule exists |
| Assets, sources and outputs | Session | Until the owner deletes the asset. Deletion is a tombstone; every source and output version is then deleted asynchronously. No age-based expiry and no S3 lifecycle rule are configured |
| Jobs, attempts and tombstone rows | Session | Until environment teardown; no hard-purge job |
| Outbox and inbox rows | Transaction | Until environment teardown; sent rows are kept for replay; no pruning job |
| SQS messages | Transaction | 7 days (DLQs 14 days); visibility: base 420 s, short queue 960 s, Fargate receive override normally 60 s; redrive after 5 receives |
| Lambda and task logs | Request | 7 days |
| Aurora backups | n/a | 1-day automated backup retention on each cluster; the pre-split snapshot of the original cluster is kept, and one final snapshot is kept at teardown |
| CI and CD artifacts | Workflow run | 7, 14 or 60 days, depending on the artifact |

**Information architecture: data inventory and classification.** The team uses four
classification levels:

- **Restricted**: credentials, keys and secrets.
- **Confidential**: personal data and owners' content.
- **Internal**: operational and processing metadata.
- **Public**: published static assets.

**Account and authentication data** (Confidential; Restricted for hashes and secrets)

- *Data format:* `users` rows (UUID, email, bcrypt hash at cost 10, role `user` or `operator`,
  timestamps). A stateless HS256 JWT in a host-only, `HttpOnly`, `Secure`, `SameSite=Strict`
  cookie. The signing secret is an SSM SecureString.
- *Storage technology:* PostgreSQL in `media_db`, chosen for unique constraints and transactional
  joins with asset ownership.
- *Security requirements and controls:*
  - Only the Media roles can read the JWT secret or the Media DSN.
  - With Gateway authorizer cache TTL 0, authorization reads the current user row for each
    protected request (`media/authorizer.py`); role checks use that current identity.
  - Password bytes are length-limited before hashing.
  - Authenticated responses use `Cache-Control: private, no-store`.
- *Trade-off considered:* A managed identity provider (Cognito) would add MFA and recovery flows,
  but brings a new dependency and token format. The team kept the inherited account model and moved
  verification to the edge (AD-09). There is no password reset, and no key rotation.

**Owner media content: source videos and encoded outputs** (Confidential)

- *Data format:* binary video objects up to 100 MiB, in the allowed video types. Outputs are an
  MP4 primary by default, or MKV/MP3 for conversion; unedited inputs can also produce an
  HLS ladder (`.m3u8` playlists, `.ts` segments).
- *Storage technology:* versioned S3 buckets for sources and outputs. Object storage is the only
  sensible store at this size. Versioning gives each source an immutable identity (VersionId),
  which the pinned-source rule depends on.
- *Security requirements and controls:*
  - Public access is blocked and the bucket policies are TLS-only, with SSE-S3 encryption.
  - Uploads use a presigned POST whose policy fixes the key, the content type and a length range.
  - Downloads use presigned GET links that expire after 900 s, issued only after an owner check.
  - HLS segments are served by a 307 redirect to a fresh signature.
  - CORS allows only the frontend origin.
  - The worker's read is limited to the source bucket, and the owner and source binding is checked
    in code before any read.
  - On AWS: tampered and expired URLs were refused, and an unsigned read returned 403 **[AWS]**.
- *Trade-off considered:* Proxying bytes through the API would centralise control, but it breaks
  Gateway and Lambda payload limits and costs compute. Presigned URLs are bearer capabilities for
  their lifetime, so the lifetime is kept short.

**Asset and upload metadata** (Internal; original filenames are Confidential)

- *Data format:* `assets`, `upload_reservations`, `asset_source_versions`, `request_keys`,
  `cleanup_intents`, `staged_objects` and `processing_projections` rows. JSONB holds operations and
  outputs.
- *Storage technology:* PostgreSQL in `media_db`. Check constraints enforce the pinned-source rule
  (`ck_upload_reservations_finalized_has_pin`) and the status sets.
- *Security requirements and controls:* Every query is filtered by owner, and a foreign ID returns
  HTTP 404. The runtime role cannot run DDL. Idempotency keys make retries of finalize, edit and retry
  safe.
- *Trade-off considered:* Media keeps a projection instead of querying Processing (AD-21). That
  removes a runtime dependency, at the cost of eventual consistency.

**Processing job data** (Internal)

- *Data format:* `jobs`, `attempts`, `submission_guards`, `retry_requests`, `attempt_tasks`,
  `job_messaging`, `cleanup_intents`, `launcher_control` and `launch_reservations` rows. JSONB holds
  the source descriptor and the outputs.
- *Storage technology:* PostgreSQL in `processing_db`. Leases, row locks and `SKIP LOCKED` need a
  transactional store with a trustworthy clock.
- *Security requirements and controls:* Only Processing roles hold the DSN. Owner, asset, job and
  source must match the stored values on every command. The worker can update only its own leased
  attempt.
- *Trade-off considered:* The store-choice comparison is in AD-31 (section 3.2.2); these
  schemas retain local transactional authority.

**Messages in transit** (Internal)

- *Data format:* Envelope v1, as specified above. Validation rejects credential/token/media-byte-like
  keys and HTTP(S) URL strings; IAM and queue policy establish producer authority separately.
- *Storage technology:* SQS Standard queues and DLQs, plus the `message_outbox` and
  `message_inbox` tables.
- *Security requirements and controls:* SQS-managed encryption and TLS-only policies. Resource
  policies deny `SendMessage` to every principal except the listed producer roles, and
  receive/delete to every principal except the listed consumer roles. A direct send was refused
  **[AWS]**.
- *Trade-off considered:* FIFO queues would give ordering and deduplication, but at lower
  throughput and with message-group design work. The inbox and version fences already tolerate
  duplicates and reordering, so Standard queues are enough. The repository does not record a
  formal FIFO evaluation.

**Secrets and configuration** (Restricted)

- *Data format:* four role DSNs and the JWT secret as SSM SecureStrings. The Aurora master password
  is managed by RDS in Secrets Manager.
- *Storage technology:* SSM Parameter Store (no per-secret monthly fee) and Secrets Manager for the
  RDS-managed master secret. Four non-secret SSM String epochs
  (`activity/{media,processing}/{touched,quiet}`) help repair skip idle passes; missing or malformed
  hints trigger a full SQL pass (`runtime_support/activity.py`).
- *Security requirements and controls:* Each handler role can read only its own domain's
  parameters. The master secret is reachable only by the bootstrap operator. No AWS key is stored in
  GitHub; CD uses OIDC. gitleaks runs in CI.
- *Trade-off considered:* SSM has no automatic rotation, and rotation is out of scope. Cold starts
  read the parameters once.

**Operational telemetry and delivery evidence** (Internal)

- *Data format:* CloudWatch logs (bounded, redacted failure events), metrics, alarm state; CI and
  CD artifacts; sanitized JSON receipts committed under `docs/results/` and
  `docs/execution/aws/v1/evidence/`.
- *Storage technology:* CloudWatch Logs (7 days), GitHub Actions artifacts (7–60 days), Git for
  sanitized receipts, and a private, versioned S3 state bucket for CD run state.
- *Security requirements and controls:* Signed URLs, cookies, secrets and account IDs are stripped
  before anything is committed. The state bucket is private because it holds the smoke account's
  credentials.
- *Trade-off considered:* Seven-day logs keep cost and exposure low. Incident reconstruction after
  a week relies on the committed receipts.

**Static frontend** (Public)

- *Data format:* HTML, CSS and JavaScript, with content-hashed asset names.
- *Storage technology:* private S3 bucket behind CloudFront origin access control.
- *Security requirements and controls:* Integrity comes from the deploy pipeline. The bucket is not
  directly public.
- *Trade-off considered:* none material.

### Detailed Design

Three representative collaborations are summarised here at class/object level. Section 6.4
contains the complete per-use-case analysis and design models; section 6.5 explains the design
patterns. Python modules retain their real functions, and ORM records retain their real state.

**Upload, process and play (UC-1–UC-3).** Figure {@fig:arch-intake-handoff} locates the handoff;
Figures {@fig:uc1-design-class} and {@fig:uc2-design-class} in section 6.4 give the typed
records and actual operations. The principal collaborations are:

| Step | Class / function | Transaction or invariant |
|:--|:--|:--|
| Reserve / upload | `direct_intake.reserve`, `Storage.direct_upload_grant`, `UploadReservation` | Persist request identity; client POST goes straight to versioned S3. No video bytes pass through Gateway/Lambda. |
| Finalize | `direct_intake.finalize`, `Storage.verify_direct_upload`, `messaging.enqueue_submit` | Verify outside locks, then atomically adopt pin + Asset + submit outbox. Direct finalize creates no `SourceVersion`. |
| Accept / dispatch | `messaging.handle_command`, `SubmissionGuard`, `Job`, `Attempt`, `emit_state` | Processing inbox + queued state + work/result outbox commit. `short_lane.work_lane` dispatches from source size and prior executor binding; duration/height are checked after download/probe. |
| Execute | `messaging.claim`, `lifecycle.Claim`, `worker.sqs.execute_message`, `worker.tasks.pipeline` | Persist task binding and DB-clock lease; validate source pin/size/hash. Both executors use the same pipeline. Standard launcher cap 3, short mapping cap 2; live admission refusal creates a standard-lane successor (Figures {@fig:arch-dispatch}, {@fig:arch-probe-redirect}). |
| Finish / read | `lifecycle.finish`, `projections.apply_result`, `ProcessingProjection`, `projections.public_job`, `Storage.sign_output` | Live-token terminal commit and result intent; Media inbox/projection commit; owner-filtered signature or HLS redirects (`media/api/v1_hls.py`). HLS failure can preserve the primary. |

Figures {@fig:uc1-design-upload}, {@fig:uc2-design-intake}, {@fig:uc2-design-execution} and
{@fig:uc3-design-results} in section 6.4 expand these phases and their exceptions. Public status
remains `accepted` until Processing's result is projected. Verification is specified by
`test_finalize_pins_the_exact_version_it_verified`,
`test_finalize_intent_rolls_back_with_adoption_and_commits_once` and
`test_success_output_namespace_validation_and_atomic_terminal_result` in
`tests/v1/test_direct_intake_s3.py`, `test_media_messaging_sql.py` and `test_messaging_sql.py`.

**Edit-derived intake.** Figures {@fig:data-edit-sequence} and {@fig:data-edit-relay} adapt W3-14's
copy/adoption/relay views. `media/api/v1_jobs.py:edit` calls `v1_lifecycle.edit`. It first resolves request replay
and checks an owned, nondeleted completed parent with a primary output. `intake.stage` commits
a `StagedObject` before copying. A separate copy transaction locks the parent and staged row,
verifies/copies the primary through `Storage.copy_output_source`, then records writer completion.
The adoption transaction locks the staged row, creates and flushes the derived `Asset`, verifies
and pins the copied source through `direct_intake.pin_copied_source`, writes `SourceVersion`
and optional `RequestKey`, stages submit, and removes the staged row in one commit.

![Figure {#fig:data-edit-sequence}. Edit copies and pins a new source, commits Asset plus submit intent, then independently relays through SQS to the Processing inbox.](figures/data-edit-sequence.png){width=14cm}

![Figure {#fig:data-edit-relay}. Independent relay claim/send/acknowledgement and the Processing inbox transaction; duplicates are transport-safe, conflicts roll back.](figures/data-edit-relay.png){width=15cm}

Unlike direct finalize, pin verification occurs **inside** edit adoption. The independent
`MediaRepair` handler calls `messaging.publish_commands` → `delivery.sql.publish_due` → SQS
only after adoption commit. It may run before HTTP 202 reaches the caller. Copy/adoption failure
retains cleanup authority; a losing keyed edit discards its copy and replays the winner.
`tests/media/test_v1_projection.py` covers local edit adoption and uncertain copy via
`test_edit_local_projection_adoption_and_submit` and
`test_uncertain_copy_keeps_cleanup_and_never_submits`.

**Stored-source retry after execution authority expires (UC-4).** Under the Job lock,
`processing/recovery.py:recover_expired` rechecks DB time, abandons the expired Attempt, fails
the Job and stages cleanup/result intent through its callback. `v1_lifecycle.retry` checks
owner, failed projection, stored pin and optional `RequestKey`, committing the Media retry
command. Processing's `handle_command` acquires guard/Job locks before `_retry_locked`;
a new `(job_id,request_id)` creates the next queued Attempt, keeps source/operations,
clears outputs/error and commits work/result intent. Replay returns the **current** Attempt,
which may be newer than the ledger's original Attempt. Direct Processing
`messaging.retry_job` owns a separate transaction and omits the Media command leg.

Figures {@fig:uc4-design-class}, {@fig:uc4-design-successor} and {@fig:uc4-design-fences}
in section 6.4 show typed records, successor transaction and worker/projection fences.
A superseded or expired `Claim` cannot finish; its token, current Attempt, lease and deadline
must remain valid. Claim freezes field bindings, not nested dict/list contents. Job status is
queued/processing/done/failed; `deleted_at` supplies cancelled snapshots. Lost unclaimed work
is repaired on the same queued Attempt. Execution failure/expiry requires owner retry; live
short-lane refusal alone creates an automatic standard-lane successor.
`tests/v1/test_messaging_sql.py:test_retry_idempotency_and_cancel_fence_old_and_current_attempts`
checks successor uniqueness and stale-finish rejection; `tests/media/test_v1_projection.py`
checks equal-version conflict and Attempt/terminal fencing.

Independent release (UC-7) is described in Continuous Delivery (section 5) and its class/object
models in section 6.4; DP-1 in section 6.5 explains reservation and recovery-journal choices.
