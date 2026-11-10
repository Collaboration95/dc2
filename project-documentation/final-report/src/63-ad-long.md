### UC-3 Track status and play the result

#### Description

Nguyễn Kim Long is responsible for this use case's analysis and design. The primary actor is an authenticated owner, represented by Maya or Arun, using the browser or Publisher CLI. The precondition is an owned Asset accepted through UC-1; encoding need not have finished. The postcondition is an owner-visible status and, after successful processing, expiring playback access. Reading status does not mutate domain state.

The normal flow is: request the Asset by its public ID; read its local processing projection; display the status; obtain a signed primary MP4 URL when `done`; then request bytes directly from object storage, including Range requests. Where an HLS manifest exists, the player reads playlists through Media and follows segment redirects to storage. In Media's `/jobs/{job_id}` routes, `job_id` identifies the **Asset**, while `processing_job_id` identifies Processing's Job (`media/api/v1_jobs.py`, `media/schemas/public.py`).

Exception flows preserve ownership and ordering. Unknown, foreign and deleted Assets return 404. Pending intake displays `accepted`; a projected job can be `queued`, `processing`, `done`, `failed` or `cancelled`. Unfinished jobs have no playback URL. Missing HLS leaves MP4 available; unsafe HLS paths or unavailable playlists return 404. An expired storage capability requires another authorized status read. Duplicate or stale results cannot move the projection backwards, and conflicting results are rejected (`media/projections.py`, `media/api/v1_hls.py`).

#### Analysis class diagram

Figure {@fig:uc3-analysis-class} separates the viewing boundary, status control and owned result entities. These are conceptual responsibilities, independent of a framework.

![Figure {#fig:uc3-analysis-class}. UC-3 analysis objects and ownership.](figures/uc3-analysis-class.png){width=15cm}

#### Analysis sequence diagrams

Figure {@fig:uc3-analysis-read} models status and optional playback. Figure {@fig:uc3-analysis-exceptions} models denied access and result-ordering exceptions; accepting a result is distinct from an owner reading it.

![Figure {#fig:uc3-analysis-read}. UC-3 normal status and playback flow.](figures/uc3-analysis-read.png){width=15cm}

![Figure {#fig:uc3-analysis-exceptions}. UC-3 ownership, replay and conflicting-result flows.](figures/uc3-analysis-exceptions.png){width=15cm}

#### Design class diagram

Figure {@fig:uc3-design-class} refines the conceptual status record into `Asset` and `ProcessingProjection`. The `projections` module maps these into `PublicJob` and validates transitions; `Storage` supplies playback capabilities. The projection belongs to Media and has an Asset foreign key. Its Processing identifiers are values, not cross-service database associations (`media/models.py`, `media/projection_models.py`). Operation parameters without annotations retain their actual Python signatures.

![Figure {#fig:uc3-design-class}. UC-3 implemented projection and playback collaborators, with selected members.](figures/uc3-design-class.png){width=15cm}

#### Design sequence diagrams

Figure {@fig:uc3-design-read} shows the authorized read and HLS branches. `get_asset` applies the owner predicate before mapping; `public_job_from_projection` signs only a completed primary output. `part` repeats ownership/readiness checks on every playlist or segment request. Playlists are bounded to 1 MiB, and segments return HTTP 307. The Gateway adapter adds `private, no-store` to authenticated API responses (`media/repositories/assets.py`, `media/services/storage.py`, `contracts/gateway.py`).

![Figure {#fig:uc3-design-read}. UC-3 local read, MP4 capability and optional HLS access.](figures/uc3-design-read.png){width=15cm}

Figure {@fig:uc3-design-results} shows the separate result transaction. Inbox identity deduplication precedes `apply_result`; that function validates owner, accepted source, Job and output namespace before transition fences. Same-version semantic replay excludes `message_id` from its hash. A new stale result commits its inbox entry without changing the projection; conflict rolls back both. The batch handler reports exceptions as failed records (`media/messaging.py`, `media/handlers.py`, `delivery/sql.py`).

![Figure {#fig:uc3-design-results}. UC-3 atomic inbox/projection update and replay alternatives.](figures/uc3-design-results.png){width=15cm}

`tests/media/test_v1_projection.py` covers replay, attempt/terminal fences, owner/source/output rejection, accepted/queued/cancelled mapping and optional HLS. `test_local_status_hls_and_signed_range_capability` checks route responses using mocked storage; it does not exercise an actual S3 Range transfer.

#### Analysis to design

The owned-video entity becomes `Asset`; its status snapshot becomes `ProcessingProjection`; the view response becomes `PublicJob`. The status control becomes functions in `media/projections.py`, while playback access becomes `Storage.sign_output` and `v1_hls.part`. Separating asynchronous projection writes from local reads avoids a Processing request during playback and gives result ordering one explicit validation point.

### UC-5 Bulk-publish a folder and report results

#### Description

Nguyễn Kim Long is responsible for this use case's analysis and design. Maya is the content owner; Jules integrates the Publisher CLI. Preconditions are a valid account/session, an HTTPS API base and a folder of owner-held files. Login is a separate command. Publishing visits immediate regular files in sorted order, skips directories and symlinks, and records each attempted file's outcome. Acceptance means the API returned an Asset ID; `--wait` additionally requires processing to reach `done`.

The normal flow obtains the current owner, reserves an intent key, creates an upload reservation, sends bytes directly to S3, finalizes, and records the accepted ID. Optional bounded polling follows acceptance. A mixed batch continues after individual failures and exits 1 while retaining successful references. Authentication failure or uncertain transport retains the pending key for replay; definitive rejection completes that intent. Empty batches and exhausted waits also exit unsuccessfully. The postcondition is a per-file report plus durable pending replay keys, not an all-or-nothing batch transaction (`publisher/cli.py`, `publisher/client.py`, `publisher/state.py`).

#### Analysis class diagram

Figure {@fig:uc5-analysis-class} gives the batch one outcome per attempted file and separates session, publication intent and accepted reference.

![Figure {#fig:uc5-analysis-class}. UC-5 conceptual batch, file intent and outcome objects.](figures/uc5-analysis-class.png){width=15cm}

#### Analysis sequence diagrams

Figures {@fig:uc5-analysis-publish} and {@fig:uc5-analysis-exceptions} show the normal loop and partial-failure/replay alternatives. Uncertain delivery is an unresolved outcome rather than proof of rejection.

![Figure {#fig:uc5-analysis-publish}. UC-5 per-file publication and optional completion wait.](figures/uc5-analysis-publish.png){width=15cm}

![Figure {#fig:uc5-analysis-exceptions}. UC-5 mixed outcomes and replay after uncertainty.](figures/uc5-analysis-exceptions.png){width=15cm}

#### Design class diagram

Figure {@fig:uc5-design-class} maps the batch control to the `cli` module, API access to `PublicClient`, and pending-key persistence to `Intents`. The scope includes API base and authenticated owner; file identity includes name, size and SHA-256 of every byte. The CLI locks shared session state across processes. Private writes atomically replace files with mode 0600 (`publisher/state.py`, `publisher/client.py`).

![Figure {#fig:uc5-design-class}. UC-5 implemented client, orchestration and private intent state.](figures/uc5-design-class.png){width=15cm}

#### Design sequence diagrams

Figure {@fig:uc5-design-publish} shows `execute`, `mutation`, `upload` and `finish`. Upload uses a separate HTTP client and removes cookies from storage requests. Reservation/finalize use the same request UUID; no video bytes traverse API Gateway. A finalized replay may omit the upload grant.

![Figure {#fig:uc5-design-publish}. UC-5 direct upload protocol and per-file outcome accumulation.](figures/uc5-design-publish.png){width=15cm}

Figure {@fig:uc5-design-exceptions} shows why key reservation precedes network activity. `PublisherError.uncertain` or HTTP 401 preserves the key. Successful acceptance retains `job_id` in the outcome even if completion-state persistence or subsequent polling fails. Accepted IDs are returned in the report; the durable state file stores pending intent keys. Diagnostics omit server response bodies (`publisher/cli.py`, `publisher/client.py`).

![Figure {#fig:uc5-design-exceptions}. UC-5 uncertain delivery, definitive rejection and retained acceptance.](figures/uc5-design-exceptions.png){width=15cm}

`tests/publisher/test_publisher.py` checks mixed batches, replay after transport/authentication failure, bounded polling and state-write failure without losing accepted IDs. `test_direct_upload.py` checks cookie isolation and finalize replay; `test_file_identity.py` checks complete-file hashing. These are local client/contract tests.

#### Analysis to design

`IntegrationBatch` becomes the `execute` loop and returned `files` list; it requires no server-side batch entity. `PublicationIntent` becomes `Intents` with durable UUID reservation. The integration boundary becomes `PublicClient` using the published HTTP schemas. Publisher imports neither service nor database code, so independent integration follows the same public behavior as the web client.
