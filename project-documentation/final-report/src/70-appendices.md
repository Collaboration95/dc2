# Appendices

## Use-Case Specifications and Traceability

Each specification is condensed from the use-case catalogue (`docs/architecture/use-case-design.md`),
which links every test named here to its exact assertion. The personas are fictional planning
personas (section 1.3).

**UC-1 Register, log in and upload an owned video** (Maya or Arun; web app or Publisher CLI)

- *Pre:* the account exists or is created; the caller owns a supported video of at most 100 MiB.
- *Normal:* authenticate; Media reserves an owner-scoped S3 grant; the client uploads directly to
  versioned S3; finalize verifies the bytes and pins the VersionId, then atomically adopts the
  Asset and stages `submit`; the API returns `202` with the asset and job ID.
- *Exceptions:* refused when the caller is anonymous, the type is unsupported, the declared size is
  too large, the owner is wrong, the request changed or the reservation expired. Missing, truncated,
  changed or unversioned bytes are not adopted and enqueue no work; a missing object returns a
  recoverable `409`.
- *Post:* one owned Asset, an immutable verified source and one durable command. A replay returns
  the same Asset without a second command.

**UC-2 Process the video into playable outputs** (platform worker, asynchronous)

- *Pre:* UC-1 committed a valid source and command.
- *Normal:* consume the command; create Job and Attempt; launch an encoder within the cap; claim
  under a DB-clock lease and task binding; verify the pinned source; encode the MP4 and the optional
  HLS ladder; commit the terminal state and result before acknowledging the work; update Media's
  projection.
- *Exceptions:* duplicates and reordering are fenced. A dependency, FFmpeg or deadline failure
  becomes a visible `failed`. An expired lease does not re-queue automatically. An HLS failure keeps
  the MP4. Poison messages follow the DLQ policy.
- *Post:* on success, exactly one primary output and optional HLS, scoped to the job and attempt.
  A failure is visible.

**UC-3 Track status and play the result** (owner; browser or CLI)

- *Pre:* the caller is authenticated and owns the Asset.
- *Normal:* Media reads the owner-filtered Asset and its local projection, and returns the status.
  When the job is done, it also returns a short-lived signed MP4 capability. The HLS playlist is
  served through Media, and segments redirect to signed S3 URLs.
- *Exceptions:* foreign and unknown IDs return not found. Stale results cannot replace a newer
  projection. An expired URL needs a fresh authorized read.
- *Post:* owner-only status and expiring playback access; no domain mutation.

**UC-4 Retry from the stored source** (owner; web or CLI)

- *Pre:* the caller owns a failed job whose accepted source remains available.
- *Normal:* a bodyless retry with an idempotency key. Media checks the owner, the failed projection
  and the pinned source. Processing serializes on the SubmissionGuard and creates a new Attempt. A
  replay returns that attempt. No bytes are uploaded again.
- *Exceptions:* a foreign or deleted job returns not found. A non-failed state or a changed request
  conflicts. A stale old-attempt worker or result cannot overwrite the current attempt.
- *Post:* the source identity is unchanged and one new Attempt is queued.

**UC-5 Bulk-publish a folder and report results** (Maya through Publisher; Jules as integrator)

- *Pre:* credentials and a folder of owner-held videos.
- *Normal:* authenticate; submit each eligible file through the published API; continue through
  the batch; report one outcome and job reference per file. `status`, `output` and `retry` share
  the public contract.
- *Exceptions:* one refused file does not hide later successes. Transport uncertainty preserves
  accepted IDs and request keys. Sensitive server error text is withheld.
- *Post:* per-file outcomes survive. Any failure makes the batch exit non-zero without losing
  successful references.

**UC-6 Scale processing capacity independently** (Sam, operator)

- *Pre:* a durable Processing backlog; Media is deployed independently.
- *Normal:* in V2-live, work sends wake the launcher, with a one-minute schedule as fallback. The
  launcher checks SQL and visible SQS demand, reserves slots and starts finite Fargate tasks, up to
  three. In V1, the operator started batches of 1 to 3.
- *Exceptions:* no visible work means no launch. An ambiguous RunTask reply keeps its reservation
  until resolved. An uncertain inventory fails closed. Excess work stays queued.
- *Post:* Processing capacity varied without any change to Media; concurrent triggers stayed within
  three slots.

**UC-7 Release Processing on its own and demonstrate rollback** (Sam through CD)

- *Pre:* the candidate has green required CI, an immutable and scanned image, migration evidence
  and a retained previous image.
- *Normal:* green Main CI updates the stack, and only changed owners release. The release validates
  the candidate, moves that owner's aliases and task definition, runs the smoke test and adopts the
  release. Media is unchanged.
- *Exceptions:* a failed gate stops promotion. A failed smoke restores the previous image. A failed
  restore leaves a durable recovery intent. Migrations are never reversed automatically.
- *Post:* success records the owner image and the smoke result; failure records the restore.

**Traceability matrix.** Analysis objects come from the shared analysis class model (Figure
{@fig:analysisclass}). Design classes come from the implemented design class model (Figure
{@fig:designclass}).

| UC | Analysis objects | Design classes and modules | Sequence views | Key tests | Responsible |
|:----|:--------------|:------------------------------|:----------------|:------------------------------|:---------|
| UC-1 | Owner, UploadRequest, OwnedAsset | `User`, `UploadReservation`, `Asset`, `SourceVersion`, `Envelope`; `media/services/direct_intake.py`, `storage.py`, `media/messaging.py` | Figs {@fig:seqintake}, {@fig:analysisseq1} | `test_publisher_direct_post_encode_projection_and_ownership`, `test_finalize_pins_the_exact_version_it_verified`, `test_wrong_owner_cannot_finalize_or_observe_a_reservation`, `test_missing_object_is_retryable_not_adopted` | Ibrahim |
| UC-2 | ProcessingJob, ProcessingAttempt, PlayableOutput | `Job`, `Attempt`, `SubmissionGuard`, `AttemptTask`, `Output`, `Source`; `processing/messaging.py`, `lifecycle.py`, `worker/tasks.py`, `media_engine/` | Figs {@fig:seqencode}, {@fig:analysisseq1} | `test_success_output_namespace_validation_and_atomic_terminal_result`, `test_a_failing_ladder_leaves_the_mp4_and_reports_no_ladder` | Ibrahim |
| UC-3 | Owner, OwnedAsset, PlayableOutput | `ProcessingProjection`, `Actor`; `media/projections.py`, `media/api/v1_hls.py`, `storage.sign_output` | Figs {@fig:seqplay}, {@fig:analysisseq1} | `test_local_status_hls_and_signed_range_capability`, `test_wrong_owner_source_job_and_output_rejected`, `test_exported_handler_reads_owned_projection_without_peer` | Long |
| UC-4 | ProcessingJob, ProcessingAttempt | `RetryRequest`, `Attempt`, `SubmissionGuard`, `RequestKey`; `media/services/v1_lifecycle.py:retry`, `processing/messaging.py:_retry_locked` | Fig {@fig:analysisseq2}; section 3.2.4 case 2 | `test_publisher_retry_reuses_the_stored_source_after_a_transient_encode_failure`, `test_retry_idempotency_and_cancel_fence_old_and_current_attempts`, `test_retry_and_cancel_are_commands` | Ibrahim |
| UC-5 | IntegrationBatch, UploadRequest | Publisher `cli.py`, `client.py`, `state.py`; OpenAPI documents in `docs/api/` | Fig {@fig:analysisseq2} | `test_cli_mixed_batch_keeps_every_file_outcome`, `test_module_entry_and_import_boundary`, `test_public_schema_conformance_and_explicit_ca` | Long |
| UC-6 | Operator, ProcessingCapacity | `LauncherControl`, `LaunchReservation`, `AttemptTask`; `processing/launcher.py`, `launcher_trigger.py` | Figs {@fig:seqencode}, {@fig:analysisseq3} | `test_always_on_concurrent_wakes_never_exceed_the_cap_without_a_session_end`, `test_a_backlog_of_ten_launches_at_most_three_and_later_ticks_add_none`, `test_a_lost_runtask_response_is_resolved_by_token_without_a_second_launch` | Guruprasath |
| UC-7 | Operator, ReleaseCandidate | `Planner`, `Journal`, `CLITransport`; `scripts/aws/v1/release.py`, `deploy.py`, `scripts/ci/cd.sh` | Fig {@fig:analysisseq3}; section 3.2.4 case 3 | `test_owner_release_applies_a_real_migration_and_failed_candidate_restores_aliases`, `test_pending_intent_before_mutation_and_real_bad_candidate_restore`, `test_owners_are_released_only_when_their_images_build_inputs_changed` | Guruprasath |

## Analysis and Design Models

**Transition from analysis to design.** Each analysis responsibility became a design structure
(static change) and an interaction protocol (dynamic change). The table records the affected use
cases and the rationale.

| Analysis responsibility | Affected UCs | Static design (classes, data) | Dynamic design (interactions) | Rationale |
|:----------------|:------|:----------------------------|:----------------------------|:----------------------------|
| Owner submits an asset and follows its job | UC-1, UC-3 | Media owns `User`, `Asset`, `UploadReservation`, `SourceVersion` and a local `ProcessingProjection`; Processing owns `Job` and `Attempt`; UUIDs, not foreign keys, cross the boundary | Reserve → direct upload → finalize; result snapshots update the projection | Two logical databases with their own roles; no runtime dependency between the services |
| Owner identity and authorization | UC-1, UC-3, UC-4, UC-5 | `Actor` value type; Media authorizer; Gateway adapter | The authorizer reads the current user row per request; the adapter strips caller headers | No shared JWT secret and no caller-controlled owner header at Processing |
| Upload bytes and source identity | UC-1, UC-5 | `UploadReservation` with a pin check constraint; `Source` descriptor | Presigned POST to S3; verify outside SQL locks; adopt in one transaction | Bytes never pass through Lambda; the verified source cannot be replaced |
| Cross-context asynchronous work | UC-1, UC-2, UC-4 | `message_outbox`, `message_inbox` in each database; `Envelope` v1 | Stage in the domain transaction; publish after commit; consumer commits inbox and state before ACK | SQL and SQS are not one atomic resource; at-least-once delivery is absorbed |
| Retry, worker failure and output | UC-2, UC-4 | `RetryRequest`, `AttemptTask`, lease columns, `Output` | A new attempt per retry; DB-clock leases fence old workers | No duplicate terminal writes; no hidden automatic requeue |
| Operator capacity and release | UC-6, UC-7 | `LauncherControl`, `LaunchReservation`; release journal and pending intent | SQL-reserved RunTask with a stable token; per-owner alias move, smoke and restore | Capacity and code change independently; bounded cost |

![Figure {#fig:designclass}. Common implemented design class model for UC-1 to UC-7 (domain, contract and operator-tool types).](figures/use-case-design-02-common-implemented-design-class-model.png){width=13cm}

```{=openxml}
<w:p><w:r><w:t>LANDSCAPE-START</w:t></w:r></w:p>
```

![Figure {#fig:analysisclass}. Shared analysis class model (conceptual objects only).](figures/use-case-design-01-shared-analysis-class-model.png){width=23cm}

![Figure {#fig:analysisseq1}. Analysis sequence, UC-1 to UC-3: the core workflow.](figures/use-case-design-03-analysis-sequence-uc-1-uc-3-core-workflow.png){width=22cm}

![Figure {#fig:analysisseq2}. Analysis sequence, UC-4 and UC-5: stored-source retry and Publisher integration.](figures/use-case-design-04-analysis-sequence-uc-4-and-uc-5-retry-integration.png){height=13.5cm}

![Figure {#fig:analysisseq3}. Analysis sequence, UC-6 and UC-7: capacity and release.](figures/use-case-design-05-analysis-sequence-uc-6-and-uc-7-operations.png){height=13.5cm}

```{=openxml}
<w:p><w:r><w:t>LANDSCAPE-END</w:t></w:r></w:p>
```

The implemented (design-level) sequences for the same three groups name every Lambda, queue and
table. They are too wide to print legibly. They are kept as source in the catalogue and rendered
in `docs/architecture/use-case-design.md`. The compact design sequences in Figures
{@fig:seqintake}–{@fig:seqplay} cover the core workflow.

## Design Problems

The three significant design problems are listed below. Each one covers the problem, the
alternatives, the decision, a before-and-after view, the resulting behaviour and the evidence. The
"before" is the submitted proposal design or the V1 operating mode. These are as-built design
decisions, not claims that a named GoF pattern was chosen. They do use well-known architectural
patterns: transactional outbox and inbox, anti-corruption layer, and lease-based fencing.

### DP-1 Bounded cloud capacity and safe per-owner release (Guruprasath Gopal)

- **Problem.** The environment must be usable at any time while idle cost and the blast radius of a
  release stay small. Processing must change without releasing Media. An ambiguous cloud response
  must never create extra workers, or falsely report a successful rollback.
- **Alternatives.**
  - Keep per-run stacks and booked sessions: slow, at about 25 minutes to deploy and 25–40 minutes
    to tear down.
  - Keep one long-open session: a booking under another name.
  - Release all code with a full stack update: couples the domains.
  - Use mutable image tags: loses the tested identity.
  - Add a separate staging environment: out of scope for the time available.
- **Decision.** AD-27 with AD-16. One persistent stack is updated after green Main CI. Only owners
  whose image inputs changed are released, by immutable digest, with a smoke test and automatic
  restore. A SQL-backed launcher reserves at most three encoder slots, and a stable RunTask token
  survives lost replies.
- **Behaviour.** A failed preflight or smoke is never counted as a promotion. A journal lock and a
  `pending_release` intent precede any mutation. The previous image is retained for restore and,
  under AD-28, is scanned before promotion.
- **Evidence.** The tests named under UC-6 and UC-7 (section 7.1). **[AWS]**: 0 → 3 → 0 scaling,
  the 9-clip backlog, and the bad-candidate restore in run 39271754470.

![Figure {#fig:dp1}. DP-1 before and after: booked per-run sessions (left) and the persistent, automatically updated environment with SQL-reserved finite encoders (right).](figures/report-dp1-capacity-release.png){width=13cm}

### DP-2 Durable asynchronous Processing handoff (Ibrahim Mammadov)

- **Problem.** An upload must stay accepted if Processing or SQS is temporarily unavailable. No Job
  may exist without a durable command, and no work may be published before its state commits.
- **Alternatives.**
  - Keep peer HTTP with Redis/RQ: couples availability, and needs an always-on broker.
  - Perform an unprotected SQL-plus-SQS dual write from the API: can lose or orphan messages.
  - Add another broker or a workflow service: more operations.
- **Decision.** AD-11 with AD-21: a transactional outbox and inbox in each database, SQS between
  them, and a version-fenced projection in Media.
- **Behaviour.**
  - The Media API role cannot send to SQS; a repair publisher claims rows and releases SQL locks
    before network I/O.
  - Duplicates are possible. Consumers commit inbox, state and follow-on outbox rows before ACK.
  - Reordering is handled by `state_version`, attempt, guard and lease fences.
  - `repair_work` rebuilds missing queue entries from SQL.
- **Evidence.** `test_messaging_sql.py`: lost-send replay, an SQS-emulator end-to-end run, and
  stale-attempt fencing **[Local]**. **[AWS]**: the Processing-down isolation run, and the DLQ
  poison message.

![Figure {#fig:dp2}. DP-2 before and after: synchronous SubmitJob with Redis/RQ (left) and the outbox → SQS → inbox chain with Media's projection (right).](figures/report-dp2-handoff.png){height=17cm}

### DP-3 Trusted owner identity and reusable public contract (Nguyễn Kim Long)

- **Problem.** An independent client (Jules) and Processing need the same owner decision. Neither
  may trust a caller-supplied owner header, and Processing must not get Media's JWT secret or user
  table.
- **Alternatives.**
  - Trust `X-Owner-Id`/`X-Role` headers.
  - Give the JWT secret and user lookup to both services.
  - Create a separate identity provider or service.
- **Decision.** AD-09 with AD-20 and AD-24. A Media-owned authorizer passes a validated `Actor`.
  The Gateway adapter strips the public identity headers, and Processing filters by the trusted
  owner. IAM and queue policies, not the envelope schema, establish producer and consumer
  authority. The OpenAPI and `contracts/` documents are versioned, so a client like Publisher needs
  no service imports or credentials.
- **Behaviour.** Forged headers change nothing; a foreign job returns 404; direct queue sends are
  refused.
- **Evidence.** `test_local_gateway.py` (forged-header and anonymous-denial tests),
  `test_contract_fixtures.py` (trusted owner propagation) and the Publisher import-boundary test
  **[Local]**. **[AWS]**: `forged-identity`, `anonymous-denied`, `sqs-direct-send`, and the #229
  cross-owner negatives.

![Figure {#fig:dp3}. DP-3 before and after: service token with a forwarded owner header (left) and the Gateway-trusted actor from the Media authorizer (right).](figures/report-dp3-identity.png){width=13cm}

## Glossary

| Term | Meaning |
|:----------------|:-----------------------------------------------------------------------|
| ACU | Aurora capacity unit; Serverless v2 scales between 0 and 2 ACU here |
| ADR / AD-nn | Architecture decision record and its identifier in `docs/architecture/decisions.md` |
| AISS-nn | Outstanding architectural issue (section 3.4) |
| Attempt | One numbered try at a job; never reused |
| CD / CI | Continuous delivery / continuous integration (GitHub Actions) |
| `dc2-live` | The persistent V2-live AWS environment (stack name) |
| DLQ | Dead-letter queue: receives a message after five failed receives |
| Inbox / outbox | Per-database tables that deduplicate received messages / stage outgoing messages in the same transaction as the state change |
| Lease | A worker's time-limited right to finish an attempt, judged on the database clock |
| OIDC | OpenID Connect: lets GitHub Actions assume an AWS role without stored keys |
| Projection | Media's own read model of Processing state, fenced by `state_version` |
| Release (per owner) | Moving one service's Lambda aliases and task definition to a new image digest, with smoke and restore |
| Seed / producer / consumer | The platform's core asset (an owned video and its job) / who submits it / who uses the result |
| V1 / V2-live | Per-run booked-session stacks (to 18 Oct) / one persistent environment (from 18 Oct, AD-27) |
| VersionId | The S3 object version that pins an accepted source |
