### Persistence Design

**Relational data.** Each service owns one PostgreSQL 16 database on its own Aurora Serverless v2 cluster (AD-29), with
its own Alembic migration history (Media `0001_media` … `media_0008`; Processing `processing_0001`
… `processing_0007`). No table has a foreign key into the other database. Owner and asset
identifiers cross the boundary only as plain UUIDs inside messages. Figures {@fig:ermedia} and {@fig:erprocessing} are the logical
data models.

![Figure {#fig:ermedia}. Media Management logical data model (`media_db`).](figures/views-er-media.png){width=12.5cm}

![Figure {#fig:erprocessing}. Processing logical data model (`processing_db`).](figures/views-er-processing.png){width=12.5cm}

Database roles are created by a one-off bootstrap task:

- `*_owner` owns the database and cannot log in.
- `*_migrator` inherits the owner and runs Alembic.
- `*_runtime` has only `SELECT`, `INSERT`, `UPDATE` and `DELETE` plus sequence use.

`PUBLIC` has no access to either database, and neither domain's login roles can connect to the
other database. On AWS, a runtime login to the other database was refused, and DDL as the runtime
role was refused **[AWS]**. Connections require verified TLS.

**Transactions and concurrency.** The design's correctness rests on a few local-transaction rules:

- **State and message commit together (outbox).** Each state change stages its outgoing messages
  in `message_outbox` in the same transaction (`delivery/sql.py:stage`). A publisher claims due
  rows with `FOR UPDATE SKIP LOCKED` and a claim token, commits, sends outside the lock, and
  acknowledges only if the token still owns the row. A lost reply can resend the same
  `message_id`; it can never lose a committed message.
- **Consume once per content (inbox).** Consumers insert `message_id` plus a canonical body hash
  into `message_inbox` inside the domain transaction. The same ID with the same body is a no-op.
  The same ID with a different body is a conflict. Lambda acknowledges only after commit.
- **Serialisation per asset.** `SubmissionGuard` is locked first, then `Job`, then `Attempt`, so
  submit, retry and cancel for one asset never interleave. `jobs.current_attempt_id` is a
  deferrable foreign key, so a job and its first attempt can be inserted in one transaction.
- **Leases on the database clock.** Claim, heartbeat and finish compare `lease_token`,
  `lease_expires_at` and `deadline_at` with `clock_timestamp()`. Worker clocks are never trusted.
- **Monotonic projection.** `processing_projections` applies a result only if its `state_version`
  is newer, for the same job, source and attempt namespace. Older results are ignored, and
  conflicting content at the same version is rejected.

**Object storage.** S3 keys are an implicit contract enforced in code on both sides. Sources sit at
`staging/{owner}/{reservation}/source`, or at `sources/{owner}/{asset}/source` for edit-derived
assets, and are pinned by VersionId. Outputs sit at `jobs/{job}/attempts/{attempt}/primary.*` and
`…/hls/`. Exactly one primary output is required, and HLS names are validated before Media serves
them. Because buckets are versioned, cleanup deletes every object version, not just the latest.

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
| SQS messages | Transaction | 7 days (DLQs 14 days); visibility timeout 420 s; redrive after 5 receives |
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
  - The authorizer re-reads the current user row on every request, so role changes and deletions
    apply at once.
  - Password bytes are length-limited before hashing.
  - Authenticated responses use `Cache-Control: private, no-store`.
- *Trade-off considered:* A managed identity provider (Cognito) would add MFA and recovery flows,
  but brings a new dependency and token format. The team kept the inherited account model and moved
  verification to the edge (AD-09). There is no password reset, and no key rotation.

**Owner media content: source videos and encoded outputs** (Confidential)

- *Data format:* binary video objects up to 100 MiB, in the allowed video types. Outputs are an
  MP4 primary and an HLS ladder (`.m3u8` playlists, `.ts` segments).
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
- *Trade-off considered:* DynamoDB or the RDS Data API would remove VPC attachment and connection
  handling. They were left to the V2 backlog because the lease and outbox logic depends on SQL
  transactions.

**Messages in transit** (Internal)

- *Data format:* JSON envelope v1 (identifiers, `state_version`, source descriptor, payload). No
  bytes, credentials or URLs are allowed in a payload.
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
  RDS-managed master secret.
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

Three architecturally representative use cases are described here. Section 7.1 traces every use
case to its classes, modules, sequence views and tests. Section 7.2 holds the shared analysis and
design class models and the grouped sequence views, and section 7.3 holds the three design problems
with before-and-after views.

**Case 1: upload, process and play (UC-1 to UC-3).** This is the platform's main flow (Figures {@fig:seqintake}–{@fig:seqplay}).

| Step | Class / function | What it does | Invariant protected |
|:-----|:-----------------------------|:-----------------------------------------------------|:-----------------------------|
| Reserve | `media.services.direct_intake.reserve`, `storage.direct_upload_grant` | Creates an `UploadReservation` (owner, request ID, filename, type, size, SHA-256) and a presigned POST that fixes the key, type and length; expires in 15 min | Idempotent per `(owner_id, request_id)`; changed body → 409; type and 100 MiB size checked |
| Upload | Browser or Publisher → S3 | Sends the bytes straight to the versioned source bucket; no cookie and no API involved | Bytes never pass through Gateway or Lambda |
| Finalize | `direct_intake.finalize`, `storage.verify_direct_upload`, `media.messaging.enqueue_submit` | Reads size, SHA-256 and signature at an explicit VersionId, outside SQL locks; then, in one transaction, pins the version, creates the `Asset` and stages `submit` | The verified bytes are the bytes encoded; adoption and command are atomic; a missing object → 409, not adopted |
| Publish | `MediaRepair` → `delivery.sql.publish_due` | Claims due outbox rows (`SKIP LOCKED`), sends to `processing-commands`, acknowledges by claim token | At least once; no committed message is lost |
| Accept | `processing.handlers.command_handler` → `messaging.handle_command` | Records the inbox row; locks `SubmissionGuard`; creates `Job` and attempt 1 as `queued`; `emit_state` stages `work` and `result` v1 | One job per asset; duplicate submit is a no-op; owner and source must match |
| Launch | `processing.launcher` (V2-live) | Reserves a slot in SQL and starts a Fargate task with a stable RunTask token; at most 3. A clip of at most 60 s, 64 MiB and 1080p is instead staged on `ProcessingShortWork` and read by the `ProcessingShortEncoder` Lambda (cap 2); an executor probe that finds a longer clip returns the job to the standard lane | The cap holds under concurrent wakes and lost RunTask replies |
| Claim | `processing.worker.sqs.decode_work` → `messaging.claim` → `lifecycle.claim` | Binds the task to the attempt (`AttemptTask`), takes a lease on the DB clock, sets `processing`, stages `result` v2 | A valid lease is needed; one task, one attempt |
| Encode | `processing.worker.tasks.pipeline`, `media_engine` (same pipeline in the Fargate task and in the short-encode Lambda) | Downloads the source at its pinned VersionId and checks SHA-256; ffprobe; MP4; HLS variants via `variants_for` (never above the source height) | HLS failure keeps the MP4; outputs scoped to `jobs/{job}/attempts/{attempt}/` |
| Finish | `lifecycle.finish` | Under the live lease, records exactly one primary output plus optional HLS, sets `done`, stages `result` v3; the worker then deletes its SQS message | Terminal state commits before the work is acknowledged |
| Project | `media.handlers.result_handler` → `projections.apply_result` | Inbox dedupe; `validate_transition`; upserts the projection | Never moves backwards; checks job, source and attempt namespace |
| Play | `projections.public_job`, `storage.sign_output`, `media/api/v1_hls.py` | Returns owner-filtered status, a presigned MP4 URL and the HLS playlist; segments redirect (307) to presigned S3 URLs | Owner only; no-store caching; short-lived capability |

**Case 2: retry over the stored source (UC-4).**

1. `media.services.v1_lifecycle.retry` checks the owner, the projection state `failed`, the
   pinned source and an idempotency key (`RequestKey`).
2. It then stages a `retry` command in the same transaction.
3. In Processing, `messaging._retry_locked` locks the guard and job, and creates a **new**
   `Attempt` with the next number and a `RetryRequest` keyed by `(job_id, request_id)`. A replayed
   retry returns the same attempt.
4. If a retry arrives before its submit (SQS reordering), it is rolled back, including its inbox
   row, so redelivery can succeed later.
5. A worker still holding the old attempt's lease cannot finish: `lifecycle.finish` requires the
   current attempt and the same live `lease_token`.

No bytes are uploaded again. An expired lease marks the attempt `abandoned` and the job `failed`.
The job is never re-queued automatically. A retry is always an explicit owner command, which keeps
duplicate outputs and hidden loops out of the design. Tests:
`test_retry_idempotency_and_cancel_fence_old_and_current_attempts` and
`test_publisher_retry_reuses_the_stored_source_after_a_transient_encode_failure`.

![Figure {#fig:jobstates}. Job and attempt state machine: one-way transitions per attempt; a retry creates a new attempt.](figures/views-job-states.png){width=12cm}

**Case 3: independent, safe release of one owner (UC-7).**

1. `scripts/ci/cd.sh` calls `release_owner` for each owner whose image build inputs changed. Media
   is untouched by a Processing-only change.
2. `scripts/aws/v1/release.py` takes the journal lock and writes a durable `pending_release`
   intent **before** any mutation.
3. It pins the candidate image digest and the resolved task definitions. It verifies the
   registry manifest bytes against the scanned image config, and checks migration compatibility
   (heads must be unchanged, or attested as additive).
4. It publishes a Lambda version per function, moves each `live` alias, and runs the owner's smoke
   test.
5. On a failed gate or smoke, it restores the previous versions and records `restored`. A failed
   restore leaves the recovery intent in place for an explicit resume.
6. `deploy.py:adopt_release` then writes the promoted images back into the stack, so the template
   still describes what runs.

Schema is never rolled back. This is why migrations must be additive. Tests:
`test_owner_release_applies_a_real_migration_and_failed_candidate_restores_aliases`,
`test_pending_intent_before_mutation_and_real_bad_candidate_restore` and
`test_owners_are_released_only_when_their_images_build_inputs_changed`. **[AWS]**: CD run
39271754470 shipped a deliberately failing Processing candidate, and it restored automatically.
