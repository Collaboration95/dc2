## Analysis and Design Models

Ibrahim Mammadov is responsible for the analysis and design of UC-1, UC-2 and UC-4. Each use case below states its actors, conditions and flows, then presents class and sequence models and explains the analysis-to-design transition. Analysis objects use `«boundary»`, `«control»` and `«entity»` stereotypes to describe conceptual responsibilities. Design models use implemented names, mark function collections as `«module»`, and distinguish persistence records, adapters and contract values.

### UC-1 Register, log in and upload an owned video

#### Description

**Actors and conditions.** Maya or Arun uses the web application or Publisher CLI; Media and versioned source storage support the interaction. The owner has a supported video of at most 100 MiB and registers or logs in before requesting an upload. Success leaves one owned `Asset`, a verified immutable source descriptor and durable `submit` intent. The public acceptance response uses `job_id=asset.id`; Processing assigns its internal Job identity asynchronously (`media/api/uploads.py`).

**Normal flow.** Media hashes the registration password or verifies existing credentials, then issues a Secure, HttpOnly, SameSite cookie. Protected requests resolve the current user. Media commits an owner/request reservation before returning its upload grant. The client uploads directly to S3, then finalizes. Media verifies the exact object version without holding a reservation row lock; a second transaction locks and rechecks the reservation, saves its pin, inserts the Asset and stages the command. The API returns HTTP 202 (`media/api/auth.py`, `media/api/deps.py`, `media/services/direct_intake.py`).

**Exception flows.** Duplicate registration returns 409; invalid login returns 401. Anonymous requests are refused. Reservation replay requires the same declaration; changed input conflicts and an expired pending reservation returns 410. A foreign reservation returns 404. Missing bytes return a recoverable 409; truncated, changed, unsupported or unversioned content cannot be adopted. Finalization replay returns the existing Asset without another command. Expiry is checked again after storage verification, covering slow uploads and concurrent finalization (`media/services/storage.py`).

#### Analysis class diagram

Figure {@fig:uc1-analysis-class} separates identity control from intake control. An upload request exists before an owned asset, so a reservation is not treated as an already accepted video.

![Figure {#fig:uc1-analysis-class}. UC-1 conceptual account and intake responsibilities.](figures/uc1-analysis-class.png){width=15cm}

#### Analysis sequence diagrams

Authentication and source adoption have different failure boundaries. Figure {@fig:uc1-analysis-identity} merges registration and login; Figure {@fig:uc1-analysis-upload} includes replay and the main refused-adoption branch.

![Figure {#fig:uc1-analysis-identity}. UC-1 account creation, login and credential refusal.](figures/uc1-analysis-identity.png){width=15cm}

![Figure {#fig:uc1-analysis-upload}. UC-1 direct upload, verification and refused adoption.](figures/uc1-analysis-upload.png){width=15cm}

#### Design class diagram

Figure {@fig:uc1-design-class} uses the actual records and functions. The accepted upload's version pin belongs to `UploadReservation`; `SourceVersion` is used for derived edit sources. The reservation's preallocated `asset_id` is a logical reference without an Asset foreign key (`media/upload_models.py`). Selected ORM annotations are shown without their `Mapped[...]` wrapper; unannotated function parameters remain untyped.

![Figure {#fig:uc1-design-class}. UC-1 implemented adoption records and application functions.](figures/uc1-design-class.png){width=15cm}

#### Design sequence diagrams

The account adapter returns through its real caller in Figure {@fig:uc1-design-identity}. The upload interaction in Figure {@fig:uc1-design-upload} starts after `CurrentUser` resolution. In the Gateway deployment, Media's authorizer validates the cookie and current user, and the adapter constructs trusted context (`media/authorizer.py`, `contracts/gateway.py`). The presigned POST permits 1..declared-size bytes; finalization enforces the exact size and hash. The guaranteed ordering is adoption commit before relay publication.

![Figure {#fig:uc1-design-identity}. UC-1 real account functions and secure-cookie response.](figures/uc1-design-identity.png){width=15cm}

![Figure {#fig:uc1-design-upload}. UC-1 reservation, direct S3 transport and atomic finalization.](figures/uc1-design-upload.png){width=15cm}

The assertions in `tests/media/test_direct_intake.py::test_finalize_atomic_adoption_and_replay` check adoption and replay; `test_finalize_rechecks_expiry_after_slow_storage` checks the second expiry gate. SQL/S3 integration coverage in `tests/v1/test_direct_intake_s3.py` includes `test_finalize_pins_the_exact_version_it_verified`, wrong-owner refusal and `test_missing_object_is_retryable_not_adopted`.

#### Analysis to design

`Owner` becomes `User` plus trusted request identity; `UploadRequest` becomes `UploadReservation`, while `OwnedAsset` becomes `Asset`. Intake control becomes `direct_intake` functions and the `Storage` adapter. The conceptual atomic acceptance becomes pin + Asset + `MediaOutbox` in one SQL transaction, preserving accepted work across a queue outage. `contracts.v1.Source` defines the source descriptor carried to Processing; no media bytes cross the API integration.

### UC-2 Process the video into playable outputs

#### Description

**Actors and conditions.** Processing's command consumer and encoder execute this asynchronous use case; Media receives results. UC-1 has committed a valid source and command intent. Success records one primary MP4 and, when available, an HLS manifest under the current job/attempt namespace. Failure becomes visible through the result projection.

**Normal flow.** Processing commits inbox acceptance, a guarded Job/Attempt and result/work outboxes together. The relay sends work to the selected lane. A finite executor claims the current attempt before fetching the source, binds its task identity and receives a leased `Claim`. It verifies the pinned source, probes and encodes it, uploads acknowledged output descriptors, then commits terminal state and result intent under live authority. Media consumes results into its local projection (`processing/messaging.py`, `processing/lifecycle.py`, `media/projections.py`).

**Exception flows.** Identical messages replay harmlessly; conflicting identity or body rolls back acceptance. A short executor that rejects probe admission creates a fenced standard-lane successor. An ordinary encode error instead records failure when authority remains valid. Lease/deadline loss prevents finish; recovery abandons the expired attempt and fails the Job. Ordinary optional-HLS failure preserves the primary output. Missing queued delivery is repaired for the same Attempt; malformed records remain eligible for redrive and DLQ handling. None of these cases permits a stale worker to replace current outputs.

#### Analysis class diagram

Figure {@fig:uc2-analysis-class} gives the Job a durable identity across attempts. Outputs belong to successful execution, while the processing controller owns scheduling and outcome decisions.

![Figure {#fig:uc2-analysis-class}. UC-2 conceptual job, execution authority and playable outputs.](figures/uc2-analysis-class.png){width=15cm}

#### Analysis sequence diagrams

Figure {@fig:uc2-analysis-sequence} combines the shared processing steps and draws the principal failure and admission alternatives. Durable acceptance, execution and result application remain separate responsibilities.

![Figure {#fig:uc2-analysis-sequence}. UC-2 normal processing, admission redirect and visible failure.](figures/uc2-analysis-sequence.png){width=15cm}

#### Design class diagram

Figure {@fig:uc2-design-class} exposes `Job`, `Attempt`, unique `AttemptTask` binding and the captured `Claim`. A Claim freezes field bindings, while its nested source/operation containers remain ordinary Python values. Lifecycle functions enforce current-attempt, token, processing-state and database-clock expiry checks; ORM records do not provide invented business methods.

![Figure {#fig:uc2-design-class}. UC-2 implemented execution records and lifecycle functions.](figures/uc2-design-class.png){width=15cm}

#### Design sequence diagrams

Figure {@fig:uc2-design-intake} distinguishes `handle_command` from `handlers.invoke`: the callback returns a boolean after its transaction, while batch consumption constructs the partial-failure response. The handler attempts publication afterward. Publication failure leaves committed intent repairable (`processing/handlers.py`, `delivery/sqs.py`).

![Figure {#fig:uc2-design-intake}. UC-2 atomic command acceptance and subsequent publication.](figures/uc2-design-intake.png){width=15cm}

Dispatch uses `short_lane.work_lane`: short routing requires the feature flag, positive integer size at most 64 MiB and no prior Lambda task binding. Duration and height are learned after claim/download: `check_probe` requires finite duration in (0,60] seconds and height at most 1080. `NotAdmitted` invokes `redirect_to_long_lane`; prior Lambda binding sends the new Attempt to standard work. These are code-defined routing rules, independent of the standard launcher's capacity decision (`processing/short_lane.py`, `processing/short_encoder.py`).

![Figure {#fig:uc2-design-execution}. UC-2 claimed execution and optional HLS under live authority.](figures/uc2-design-execution.png){width=15cm}

Figure {@fig:uc2-design-execution} follows `worker.sqs.execute_message` and `worker.tasks.pipeline`. `media_engine.probe`, `operations` and `hls` build/parse commands; `Supervisor.run` executes subprocesses. `SourceStore.download` checks pinned version, size and hash. `OutputStore.put` returns acknowledged descriptors; HLS uploads its master last. The standard worker deletes a receipt after a durable outcome, or drains SQL-proved stale work; uncertain execution retains it. Lambda deletion belongs to the event-source mapping.

Figure {@fig:uc2-design-exceptions} expands the main exception paths. Media's result consumer calls `consume_result(session, envelope, apply)`: inbox acceptance and `apply_result` commit together. Source/output validation and `validate_transition` protect the local projection. A new stale message can commit its inbox row without changing the projection; conflicting content rolls back both. The result handoff uses the same local consistency pattern as Figure {@fig:dp2-solution-sequence}.

![Figure {#fig:uc2-design-exceptions}. UC-2 refused claims, short-lane redirect and interrupted execution.](figures/uc2-design-exceptions.png){width=15cm}

`tests/v1/test_messaging_sql.py` checks duplicate/conflict rollback, source-substitution refusal and atomic terminal results, including output namespace validation. `tests/v1/test_short_encoder_sql.py::test_a_source_the_probe_rejects_becomes_a_new_attempt_on_the_standard_lane` covers redirect. Pipeline tests in `tests/processing/test_worker.py::test_hls_failure_retains_primary` cover preserving MP4 after ladder failure. These are implementation tests, not claims of measured cloud recovery latency.

#### Analysis to design

`ProcessingJob` and `ProcessingAttempt` become `Job` and `Attempt`; execution authority becomes `Claim`, lease columns and `AttemptTask`. `PlayableOutput` becomes validated `Output` descriptors stored in JSON, not an output table. Processing control becomes `messaging`, `lifecycle` and worker modules. Result reception becomes Media's inbox plus `ProcessingProjection`, separating Processing's write authority from Media's owner-facing reads.

### UC-4 Retry from the stored source

#### Description

**Actors and conditions.** The owner retries through the web application or CLI. The owned Asset has a failed projection and a retained accepted source. Success retains Asset, Job, source and operations, while queuing a new numbered Attempt.

**Normal flow.** A bodyless request optionally supplies `Idempotency-Key`. Media locks the owned Asset, resolves replay before checking status, verifies the failed projection and reads the pinned descriptor. It commits request identity and stable retry intent. Processing accepts the command, locks guard then Job, validates durable identity and creates one successor plus work/result intent (`media/services/v1_lifecycle.py`, `processing/messaging.py`).

**Exception flows.** Foreign/deleted Assets return 404; a non-failed projection returns 409. A replay returns the prior public acceptance; Processing's request ledger prevents another successor and returns the current Attempt. Retry-before-submit rolls back the inbox so later redelivery can succeed. Deleted guards cannot resurrect work. Old worker claims and stale result versions cannot overwrite a newer attempt. No source upload is repeated.

#### Analysis class diagram

Figure {@fig:uc4-analysis-class} adds retry identity to the stable Job/Attempt relationship. A retry changes execution authority rather than the source identity.

![Figure {#fig:uc4-analysis-class}. UC-4 conceptual retry identity and successor attempt.](figures/uc4-analysis-class.png){width=15cm}

#### Analysis sequence diagrams

Figure {@fig:uc4-analysis-sequence} combines eligibility, replay and the main late-worker exception around the shared retry flow.

![Figure {#fig:uc4-analysis-sequence}. UC-4 owner retry, replay and refused stale completion.](figures/uc4-analysis-sequence.png){width=15cm}

#### Design class diagram

`RequestKey` deduplicates the public Media operation; `RetryRequest` deduplicates Processing's successor creation. Figure {@fig:uc4-design-class} keeps these separate local records explicit. Without a public key, Media derives message identity from Asset and failed state version.

![Figure {#fig:uc4-design-class}. UC-4 implemented public and Processing retry ledgers.](figures/uc4-design-class.png){width=15cm}

#### Design sequence diagrams

Figures {@fig:uc4-design-retry} and {@fig:uc4-design-successor} show local transactions separated by asynchronous delivery. `_retry_locked` retains source/operations, schedules old-attempt cleanup, increments the attempt number, clears prior error/outputs and calls `emit_state`. Direct Processing retry calls `messaging.retry_job` in its own transaction (`processing/v1_api.py`).

![Figure {#fig:uc4-design-retry}. UC-4 public retry acceptance.](figures/uc4-design-retry.png){width=15cm}

![Figure {#fig:uc4-design-successor}. UC-4 guarded successor creation and retry replay.](figures/uc4-design-successor.png){width=15cm}

![Figure {#fig:uc4-design-fences}. UC-4 independent worker-authority and result-projection fences.](figures/uc4-design-fences.png){width=15cm}

Figure {@fig:uc4-design-fences} separates `lifecycle.live` from `projections.validate_transition`. The former rejects stale execution tokens; the latter ignores old versions/attempts and rejects conflicting same-version content. `tests/v1/test_messaging_sql.py::test_retry_idempotency_and_cancel_fence_old_and_current_attempts` asserts successor uniqueness and rejected old finishes. `tests/media/test_v1_projection.py::test_retry_and_cancel_are_commands` checks Media intent; its transition tests cover version and attempt fencing.

#### Analysis to design

Retry control becomes Media's `v1_lifecycle.retry` and Processing's `_retry_locked`, connected by a versioned `Envelope`. Retry identity becomes `RequestKey`, stable message identity and `RetryRequest`, each addressing a different replay boundary. The conceptual authority check becomes current-attempt and lease validation plus a separate projection fence. An expired Attempt remains abandoned; owner retry creates a new UUID rather than returning that terminal Attempt to queued.
