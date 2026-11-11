## Use Case Model

Figure {@fig:ucm-scope} defines the FlickPond platform and its two supported clients. Owners submit videos and consume their own results; operators manage capacity and releases. UC-2 runs asynchronously on the owner's behalf, and workers, queues and the pipeline are internal participants. The personas Maya, Arun, Jules and Sam are described in the Introduction; they are planning personas, not application roles.

![Figure {#fig:ucm-scope}. Use-case model: seven scoped goals and grouped exclusions. Grey cases sit outside the delivered system boundary.](figures/ucm-scope.png){width=15cm}

The grey package groups the exclusions listed in the Introduction under "Functionality out of scope". The editor exclusion concerns a crop/clip **UI**; API edit operations and deletion remain supporting capabilities. UC-6 uses bounded finite task launching, and general autoscaling is excluded. UC-3 authorises owners; student, LMS and public access are excluded.

No include/extend relation is asserted. Upload, processing and status reads depend on each other in time but remain independently observable goals. Retry is requested separately after failure. Publisher repeats the public upload protocol for each file.

The catalogue assigns responsibility for **analysis and design**. All seven proposal use cases have Must priority (BS-06); the backlog separately records implementation priority. Section 6.4 contains each owner's descriptions, normal and exception flows, and analysis and design class and sequence models; the appendix traceability matrix links each case to its code modules and tests.

| ID | Name | Primary actor | Planning persona | Analysis/design owner | Priority | Models |
|---|---|---|---|---|---|---|
| UC-1 | Register, log in and upload an owned video | Content owner | Maya, Arun; Jules integrates | Ibrahim Mammadov | Must | §6.4, Ibrahim: UC-1 |
| UC-2 | Process the video into playable outputs | Content owner, through asynchronous execution | Maya, Arun | Ibrahim Mammadov | Must | §6.4, Ibrahim: UC-2 |
| UC-3 | Track status and play the result | Content owner as viewer | Maya, Arun | Nguyễn Kim Long | Must | §6.4, Long: UC-3 |
| UC-4 | Retry from the stored source | Content owner | Maya, Arun | Ibrahim Mammadov | Must | §6.4, Ibrahim: UC-4 |
| UC-5 | Bulk-publish a folder and report results | Content owner using Publisher | Maya; Jules integrates | Nguyễn Kim Long | Must | §6.4, Long: UC-5 |
| UC-6 | Scale processing capacity independently | Platform operator | Sam | Guruprasath Gopal | Must | §6.4, Guruprasath: UC-6 |
| UC-7 | Release Processing on its own and demonstrate rollback | Platform operator | Sam | Guruprasath Gopal | Must | §6.4, Guruprasath: UC-7 |

## Analysis-to-Design Transition Strategies

These six strategies connect analysis objects to implemented classes and modules. Read their class and sequence changes alongside the analysis and design pairs in section 6.4. Conceptual associations express responsibilities; design associations identify persistence ownership, immutable references and execution authority. Function collections remain modules.

### TR-1 Asset submission and status

| Aspect | Transition |
|---|---|
| Analysis objects | Owner, UploadRequest, OwnedAsset, ProcessingJob, ProcessingAttempt, PlayableOutput. |
| Use cases | UC-1, UC-2, UC-3; UC-5 reuses intake and status. |
| Class-diagram changes | Map Owner to `User`, OwnedAsset to `Asset`, and UploadRequest to `UploadReservation`. Add Media's `ProcessingProjection`; keep `Job` and `Attempt` in Processing. One Job has multiple Attempts and a current-attempt reference. UUID references replace cross-context database associations. |
| Sequence-diagram changes | Replace conceptual submit → process → play with reserve → S3 upload → finalize, command/result delivery, then an owner-filtered local status read and signed playback access. Show queued status before a result arrives. |
| Reason | Separate ownership from execution so that Media accepts submissions and answers status without a synchronous Processing call. The projection records reported state and never authorises an encoder to finish. |
| Implemented in | `media/models.py`, `media/upload_models.py`, `media/projection_models.py`, `processing/models.py`, `media/projections.py:public_job`. |

### TR-2 Identity and authorisation

| Aspect | Transition |
|---|---|
| Analysis objects | Owner, OwnedAsset, UploadRequest, IntegrationBatch. |
| Use cases | UC-1, UC-3, UC-4, UC-5. |
| Class-diagram changes | Separate persistent `User` from the `Actor` contract value. Add `GatewayAdapter` and the authorizer module; retain owner checks in Media and command handling in Processing. |
| Sequence-diagram changes | Add Gateway → authorizer → Gateway → API. Show current-user lookup, trusted context adaptation, Media revalidation, and refusal when identity or ownership is invalid. |
| Reason | A caller cannot choose an owner through a forwarded header, and Processing needs neither Media's JWT secret nor a peer authentication call. |
| Implemented in | `media/authorizer.py:authorize`, `contracts/gateway.py:GatewayAdapter.invoke`, `media/api/deps.py:current_user`. The authorizer issues only the `publisher` role. |

### TR-3 Upload and immutable source identity

| Aspect | Transition |
|---|---|
| Analysis objects | UploadRequest, OwnedAsset, IntegrationBatch. |
| Use cases | UC-1, UC-5; derived-source edit variant. |
| Class-diagram changes | Add reservation request identity, expiry, checksum, size and S3 VersionId; use the `Source` contract descriptor. An adopted upload retains its pin in `UploadReservation`; `SourceVersion` records a derived edit source. |
| Sequence-diagram changes | Replace API byte transfer with reserve → scoped S3 POST → verification outside SQL locks → locked adoption transaction. Include replay, expiry and verification-failure alternatives. A finalized replay receives no new upload grant. |
| Reason | Avoid Lambda payload limits and bind processing to the exact verified bytes despite later writes to the same object key. |
| Implemented in | `media/services/direct_intake.py:reserve` and `finalize`; `media/services/v1_lifecycle.py:edit` (copy, then pin and stage the command in one adoption transaction); `publisher/client.py:PublicClient.upload`. |

### TR-4 Durable asynchronous handoff

| Aspect | Transition |
|---|---|
| Analysis objects | OwnedAsset, ProcessingJob, ProcessingAttempt. |
| Use cases | UC-1, UC-2, UC-4; UC-5 through intake. |
| Class-diagram changes | Introduce `Envelope`, `MediaOutbox`, `MediaInbox`, `ProcessingOutbox` and `ProcessingInbox`, plus the Media projection. Keep message records local to each database. |
| Sequence-diagram changes | The sequence separates adoption commit, relay send and send acknowledgement; response loss leaves accepted work available for replay. It also shows consumer inbox/domain commit, duplicate delivery and scheduled repair. |
| Reason | SQL and SQS cannot commit atomically; durable intent and deduplication absorb at-least-once transport. |
| Implemented in | `delivery/sql.py:stage`, `publish_due` and `accept`, used by `media/messaging.py` and `processing/messaging.py`; relay I/O follows its reservation transaction. |

### TR-5 Retry, failure and output authority

| Aspect | Transition |
|---|---|
| Analysis objects | ProcessingJob, ProcessingAttempt, PlayableOutput. |
| Use cases | UC-2, UC-4. |
| Class-diagram changes | Add `SubmissionGuard`, `RetryRequest`, `Claim`, `AttemptTask`, lease/deadline fields and `Output` descriptors under an attempt-specific object prefix. |
| Sequence-diagram changes | Separate owner retry/new Attempt from queued-work repair. Add claim → heartbeat → fenced finish, expired-lease failure, stale-worker/result rejection and short-lane redirect alternatives. |
| Reason | Only the current live attempt may publish a terminal outcome; duplicate messages and late workers must not overwrite a retry. Output validation in `processing/schemas.py` and `processing/lifecycle.py:finish` requires exactly one verified primary output in the current attempt namespace. Unedited uploads produce MP4; conversion edits can produce MKV or MP3. HLS remains optional. |
| Implemented in | `processing/lifecycle.py:claim`, `heartbeat` and `finish` (database-clock authority); `processing/recovery.py:recover_expired`; `processing/short_encoder.py:encode_record` and `processing/messaging.py:redirect_to_long_lane`. Both lanes keep the same fences. |

### TR-6 Bounded capacity and independent release

| Aspect | Transition |
|---|---|
| Analysis objects | Operator, ProcessingCapacity, ReleaseCandidate. |
| Use cases | UC-6, UC-7 (Figures {@fig:uc6-design-class}, {@fig:uc7-design-class}). |
| Class-diagram changes | Map capacity to `LauncherControl` and `LaunchReservation`. Map release coordination to `release.promote` and `release.restore`, durable intent to `Journal` and `DeployJournal`, deployment adoption to `deploy.adopt_release`, and AWS operations to `OperatorTransport`. |
| Sequence-diagram changes | Add SQL-serialised slot reservation before RunTask, concurrent-wake and lost-reply branches (Figure {@fig:uc6-design-recovery}). For release, show validation → pending intent → migration → publication marker → version → revision-checked alias change → owner smoke → adoption or restore, with unresolved intent kept for resumption (Figures {@fig:uc7-design-normal}, {@fig:uc7-design-recovery}). |
| Reason | Bound outstanding standard encoder slots to three and preserve uncertain cloud outcomes while changing Processing independently of Media. The cap concerns standard finite Fargate capacity; the short Lambda lane has separate admission controls. |
| Implemented in | `processing/launcher.py:tick` and `_send` keep the RunTask token and reservation across ambiguous responses. `scripts/aws/v1/release.py:promote` and `restore` execute per-owner changes through `scripts/aws/v1/transport.py:OperatorTransport.call`; `scripts/aws/journal.py:Journal` retains intent and `scripts/aws/v1/deploy.py:adopt_release` records the new baseline. `CLITransport` is limited to planning and emulator execution. Restore does not reverse schema migrations. |
