### UC-3 Track status and play the result

#### Description

Analysis and design: Nguyễn Kim Long. The primary actor is an authenticated owner (Maya or Arun) using the browser or Publisher CLI. The precondition is an owned Asset accepted through UC-1; encoding need not have finished. The postcondition is an owner-visible status and, after successful processing, expiring playback access. Reading status never mutates domain state.

In the normal flow the owner requests the Asset by its public ID, Media reads the local processing projection and displays the status, and a `done` Asset returns a signed primary MP4 URL whose bytes (including Range requests) come directly from object storage. Where an HLS manifest exists, the player reads playlists through Media and follows segment redirects to storage. In Media's `/jobs/{job_id}` routes, `job_id` identifies the **Asset**, while `processing_job_id` identifies Processing's Job (`media/api/v1_jobs.py`, `media/schemas/public.py`).

Exception flows preserve ownership and ordering. Unknown, foreign and deleted Assets return 404. Pending intake displays `accepted`; a projected job can be `queued`, `processing`, `done`, `failed` or `cancelled`, and only `done` has a playback URL. Missing HLS leaves MP4 available; unsafe HLS paths or unavailable playlists return 404. An expired capability needs another authorized status read. Duplicate or stale results cannot move the projection backwards, and conflicting results are rejected (`media/projections.py`, `media/api/v1_hls.py`).

#### Analysis class diagram

Figure {@fig:uc3-analysis-class} separates the viewing boundary, status control and owned result entities.

![Figure {#fig:uc3-analysis-class}. UC-3 analysis objects and ownership.](figures/uc3-analysis-class.png){width=9.5cm}

#### Analysis sequence diagrams

Figures {@fig:uc3-analysis-read} and {@fig:uc3-analysis-exceptions} show status with optional playback, then denied access and result ordering.

![Figure {#fig:uc3-analysis-read}. UC-3 normal status and playback flow.](figures/uc3-analysis-read.png){width=15cm}

![Figure {#fig:uc3-analysis-exceptions}. UC-3 ownership, replay and conflicting-result flows.](figures/uc3-analysis-exceptions.png){width=15cm}

#### Design class diagram

Figure {@fig:uc3-design-class} refines the status record into `Asset` and `ProcessingProjection`. The `projections` module maps them into `PublicJob` and validates transitions; `Storage` supplies playback capabilities. The projection belongs to Media and has an Asset foreign key; its Processing identifiers are plain values (`media/models.py`, `media/projection_models.py`).

![Figure {#fig:uc3-design-class}. UC-3 implemented projection and playback collaborators, with selected members.](figures/uc3-design-class.png){width=15cm}

#### Design sequence diagrams

Figure {@fig:uc3-design-read} shows the authorized read and HLS branches. `get_asset` applies the owner predicate before mapping; `public_job_from_projection` signs only a completed primary output. `part` repeats ownership and readiness checks on every playlist or segment request. Playlists are bounded to 1 MiB, segments return HTTP 307, and authenticated responses carry `private, no-store` (`media/repositories/assets.py`, `media/services/storage.py`, `contracts/gateway.py`).

![Figure {#fig:uc3-design-read}. UC-3 local read, MP4 capability and optional HLS access.](figures/uc3-design-read.png){width=13cm}

Figure {@fig:uc3-design-results} shows the result transaction. Inbox deduplication precedes `apply_result`, which validates owner, accepted source, Job and output namespace before transition fences. Same-version replay excludes `message_id` from its hash. A new stale result commits its inbox entry without changing the projection; a conflict rolls back both, and the batch handler reports it as a failed record (`media/messaging.py`, `media/handlers.py`, `delivery/sql.py`).

![Figure {#fig:uc3-design-results}. UC-3 atomic inbox/projection update and replay alternatives.](figures/uc3-design-results.png){width=13.5cm}

`tests/media/test_v1_projection.py` covers replay, attempt and terminal fences, owner/source/output rejection, status mapping and optional HLS. `test_local_status_hls_and_signed_range_capability` checks routes with mocked storage; the dated playback receipts in §4 cover S3 Range access.

#### Analysis to design

The owned-video entity becomes `Asset`; its status snapshot becomes `ProcessingProjection`; the view response becomes `PublicJob`. The status control becomes functions in `media/projections.py`, and playback access becomes `Storage.sign_output` and `v1_hls.part`. Separating projection writes from local reads avoids a Processing request during playback and gives result ordering one validation point.

### UC-5 Bulk-publish a folder and report results

#### Description

Analysis and design: Nguyễn Kim Long. Maya is the content owner; Jules integrates the Publisher CLI. Preconditions are a valid session, an HTTPS API base and a folder of owner-held files. Publishing visits immediate regular files in sorted order, skips directories and symlinks, and records each attempted file's outcome. Acceptance means the API returned an Asset ID; `--wait` additionally requires processing to reach `done`.

The normal flow obtains the current owner, reserves an intent key, creates an upload reservation, sends bytes directly to S3, finalizes, and records the accepted ID. Optional bounded polling follows acceptance. A mixed batch continues after individual failures and exits 1 while retaining successful references. Authentication failure or uncertain transport keeps the pending key for replay; definitive rejection completes the intent. Empty batches and exhausted waits also exit unsuccessfully. The postcondition is a per-file report plus durable pending replay keys, not an all-or-nothing batch transaction (`publisher/cli.py`, `publisher/client.py`, `publisher/state.py`).

#### Analysis class diagram

Figure {@fig:uc5-analysis-class} gives the batch one outcome per attempted file and separates publication intent from accepted reference.

![Figure {#fig:uc5-analysis-class}. UC-5 conceptual batch, file intent and outcome objects.](figures/uc5-analysis-class.png){width=12cm}

#### Analysis sequence diagrams

Figures {@fig:uc5-analysis-publish} and {@fig:uc5-analysis-exceptions} show the normal loop and the partial-failure and replay alternatives; uncertain delivery is unresolved, not rejected.

![Figure {#fig:uc5-analysis-publish}. UC-5 per-file publication and optional completion wait.](figures/uc5-analysis-publish.png){width=15cm}

![Figure {#fig:uc5-analysis-exceptions}. UC-5 mixed outcomes and replay after uncertainty.](figures/uc5-analysis-exceptions.png){width=12.5cm}

#### Design class diagram

Figure {@fig:uc5-design-class} maps the batch control to the `cli` module, API access to `PublicClient`, and pending-key persistence to `Intents`. Scope is API base plus owner; file identity is name, size and SHA-256 of every byte. The CLI locks shared session state across processes, and private writes atomically replace files with mode 0600 (`publisher/state.py`, `publisher/client.py`).

![Figure {#fig:uc5-design-class}. UC-5 implemented client, orchestration and private intent state.](figures/uc5-design-class.png){width=15cm}

#### Design sequence diagrams

Figure {@fig:uc5-design-publish} shows `execute`, `mutation`, `upload` and `finish`. Upload uses a separate HTTP client without cookies; reservation and finalize share one request UUID, and no video bytes traverse API Gateway. A finalized replay may omit the upload grant.

![Figure {#fig:uc5-design-publish}. UC-5 direct upload protocol and per-file outcome accumulation.](figures/uc5-design-publish.png){width=12.5cm}

Figure {@fig:uc5-design-exceptions} shows why key reservation precedes network activity. `PublisherError.uncertain` or HTTP 401 preserves the key. Acceptance retains `job_id` in the outcome even if state persistence or polling fails; the report returns accepted IDs and the state file stores pending keys. Diagnostics omit server response bodies (`publisher/cli.py`, `publisher/client.py`).

![Figure {#fig:uc5-design-exceptions}. UC-5 uncertain delivery, definitive rejection and retained acceptance.](figures/uc5-design-exceptions.png){width=14cm}

`tests/publisher/test_publisher.py` checks mixed batches, replay after transport or authentication failure, bounded polling and state-write failure. `test_direct_upload.py` checks cookie isolation and finalize replay; `test_file_identity.py` checks complete-file hashing.

#### Analysis to design

`IntegrationBatch` becomes the `execute` loop and returned `files` list, with no server-side batch entity. `PublicationIntent` becomes `Intents` with durable UUID reservation. The integration boundary becomes `PublicClient` over the published HTTP schemas. Publisher imports no service or database code, so it follows the same public behavior as the web client.
