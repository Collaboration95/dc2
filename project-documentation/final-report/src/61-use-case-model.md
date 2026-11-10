## Use Case Model

Figure {@fig:ucm-scope} defines the FlickPond platform and its two supported clients. Owners submit videos and consume their own results; operators manage capacity and releases. UC-2 runs asynchronously on the owner's behalf. Workers, queues and the pipeline are internal participants. Maya, Arun, Jules and Sam are fictional planning personas, not interviewed customers or application roles (`project-roadmap/business-scope.json` and `business-scope.html`). Jules represents the API integrator; Maya and Arun represent end users.

![Figure {#fig:ucm-scope}. Use-case model: seven scoped goals and grouped exclusions. Grey cases sit outside the delivered system boundary.](figures/ucm-scope.png){width=15cm}

The grey package groups the exclusions in section 1, “Functionality out of scope”, and `docs/architecture/decisions.md` §4. The editor exclusion concerns a crop/clip **UI**; API edit operations and deletion remain supporting capabilities. UC-6 uses bounded finite task launching; general autoscaling remains excluded. UC-3 authorises owners; student, LMS and public access are excluded.

No include/extend relation is asserted. Upload, processing and status reads have temporal dependencies but remain independently observable goals. Retry is requested separately after failure. Publisher repeats the public upload protocol for each file; its detailed model shows that loop without implying that every file requires registration.

The catalogue assigns responsibility for **analysis and design**. All seven cases have **Must** priority as retained proposal scope (business decision BS-06); this is a scope classification, not a claim about GitHub priority fields. Section 6.4 contains each owner's detailed descriptions, normal and exception flows, and analysis/design class and sequence models.

| ID | Name | Primary actor | Planning persona | Analysis/design owner | Priority | Models |
|---|---|---|---|---|---|---|
| UC-1 | Register, log in and upload an owned video | Content owner | Maya, Arun; Jules integrates | Ibrahim Mammadov | Must | §6.4, Ibrahim: UC-1 |
| UC-2 | Process the video into playable outputs | Content owner, through asynchronous execution | Maya, Arun | Ibrahim Mammadov | Must | §6.4, Ibrahim: UC-2 |
| UC-3 | Track status and play the result | Content owner as viewer | Maya, Arun | Nguyễn Kim Long | Must | §6.4, Long: UC-3 |
| UC-4 | Retry from the stored source | Content owner | Maya, Arun | Ibrahim Mammadov | Must | §6.4, Ibrahim: UC-4 |
| UC-5 | Bulk-publish a folder and report results | Content owner using Publisher | Maya; Jules integrates | Nguyễn Kim Long | Must | §6.4, Long: UC-5 |
| UC-6 | Scale processing capacity independently | Platform operator | Sam | Guruprasath Gopal | Must | §6.4, Guruprasath: UC-6 |
| UC-7 | Release Processing on its own and demonstrate rollback | Platform operator | Sam | Guruprasath Gopal | Must | §6.4, Guruprasath: UC-7 |

The backlog map (`docs/execution/issue-map.md` and `github-map.json`) connects UC-1/3/4 to Media epic [E3](https://github.com/Collaboration95/dc2/issues/4), including [M1 #15](https://github.com/Collaboration95/dc2/issues/15); UC-2/6 to Processing epic [E2](https://github.com/Collaboration95/dc2/issues/3), including [P3 #14](https://github.com/Collaboration95/dc2/issues/14); and UC-5 to Clients epic [E4](https://github.com/Collaboration95/dc2/issues/5), including [C2 #19](https://github.com/Collaboration95/dc2/issues/19). These historical implementation groups converge on acceptance epic [E5](https://github.com/Collaboration95/dc2/issues/6), including release/evidence work [V4 #23](https://github.com/Collaboration95/dc2/issues/23), while the UC identifiers preserve the link from business goal to section 6.4 models and tests.

## Analysis-to-Design Transition Strategies

These six strategies connect analysis objects to implemented classes and modules. Read their static and interaction changes alongside section 6.4's analysis/design pairs. Conceptual associations express responsibilities; design associations identify persistence ownership, immutable references and execution authority. Function collections remain modules.

### TR-1 Asset submission and status

| Aspect | Transition |
|---|---|
| Analysis objects | Owner, UploadRequest, OwnedAsset, ProcessingJob, ProcessingAttempt, PlayableOutput. |
| Use cases | UC-1, UC-2, UC-3; UC-5 reuses intake and status. |
| Class-diagram changes | Map Owner to `User`, OwnedAsset to `Asset`, and UploadRequest to `UploadReservation`. Add Media's `ProcessingProjection`; keep `Job` and `Attempt` in Processing. One Job has multiple Attempts and a current-attempt reference. UUID references replace cross-context database associations. |
| Sequence-diagram changes | Replace conceptual submit → process → play with reserve → S3 upload → finalize, command/result delivery, then an owner-filtered local status read and signed playback access. Show queued status before a result arrives. |
| Reason | Separate ownership from execution so that Media can accept submissions and answer status without a synchronous Processing business call. |

The class split is implemented in `media/models.py`, `media/upload_models.py`, `media/projection_models.py` and `processing/models.py`. `media/projections.py:public_job` builds the public response from local state. The projection records Processing's reported state; it does not become the authority that grants an encoder permission to finish.

### TR-2 Identity and authorisation

| Aspect | Transition |
|---|---|
| Analysis objects | Owner, OwnedAsset, UploadRequest, IntegrationBatch. |
| Use cases | UC-1, UC-3, UC-4, UC-5. |
| Class-diagram changes | Separate persistent `User` from the `Actor` contract value. Add `GatewayAdapter` and the authorizer module; retain owner checks in Media and command handling in Processing. |
| Sequence-diagram changes | Add Gateway → authorizer → Gateway → API. Show current-user lookup, trusted context adaptation, Media revalidation, and refusal when identity or ownership is invalid. |
| Reason | A caller cannot choose an owner through a forwarded header; Processing needs neither Media's JWT secret nor a peer authentication call. |

`media/authorizer.py:authorize` reads the current User and emits `Actor` context. `contracts/gateway.py:GatewayAdapter.invoke` adapts the event, while `media/api/deps.py:current_user` rechecks the session against that context. This authentication dependency on Media is distinct from the asynchronous business handoff. The authorizer issues `publisher`; accepting `viewer` in `contracts/v1.py` does not implement viewer sharing.

### TR-3 Upload and immutable source identity

| Aspect | Transition |
|---|---|
| Analysis objects | UploadRequest, OwnedAsset, IntegrationBatch. |
| Use cases | UC-1, UC-5; derived-source edit variant. |
| Class-diagram changes | Add reservation request identity, expiry, checksum, size and S3 VersionId; use the `Source` contract descriptor. An adopted upload retains its pin in `UploadReservation`; `SourceVersion` records a derived edit source. |
| Sequence-diagram changes | Replace API byte transfer with reserve → scoped S3 POST → verification outside SQL locks → locked adoption transaction. Include replay, expiry and verification-failure alternatives. |
| Reason | Avoid Lambda payload limits and bind processing to the exact verified bytes despite later writes to the same object key. |

`media/services/direct_intake.py:reserve` and `finalize` implement this split. Finalize commits the Asset, version pin and staged command together. The edit path in `media/services/v1_lifecycle.py:edit` copies output into a new source and pins it before submission. `publisher/client.py:PublicClient.upload` follows the same public reservation/finalize protocol.

### TR-4 Durable asynchronous handoff

| Aspect | Transition |
|---|---|
| Analysis objects | OwnedAsset, ProcessingJob, ProcessingAttempt. |
| Use cases | UC-1, UC-2, UC-4; UC-5 through intake. |
| Class-diagram changes | Introduce `Envelope`, `MediaOutbox`, `MediaInbox`, `ProcessingOutbox` and `ProcessingInbox`, plus the Media projection. Keep message records local to each database. |
| Sequence-diagram changes | Separate domain mutation/staging/commit, relay reservation/commit/send, consumer inbox/domain commit, and queue acknowledgement. Add duplicate-delivery and lost-send-response alternatives plus scheduled repair. |
| Reason | SQL and SQS cannot commit atomically; durable intent and deduplication absorb at-least-once transport. |

`delivery/sql.py:stage`, `publish_due` and `accept` provide the shared protocol, used by `media/messaging.py` and `processing/messaging.py`. Relay network I/O occurs after its reservation transaction. The diagram must therefore distinguish a committed command from a successfully acknowledged send; a transport timeout does not cancel accepted domain work.

### TR-5 Retry, failure and output authority

| Aspect | Transition |
|---|---|
| Analysis objects | ProcessingJob, ProcessingAttempt, PlayableOutput. |
| Use cases | UC-2, UC-4. |
| Class-diagram changes | Add `SubmissionGuard`, `RetryRequest`, `Claim`, `AttemptTask`, lease/deadline fields and `Output` descriptors under an attempt-specific object prefix. |
| Sequence-diagram changes | Separate owner retry/new Attempt from queued-work repair. Add claim → heartbeat → fenced finish, expired-lease failure, stale-worker/result rejection and short-lane redirect alternatives. |
| Reason | Only the current live attempt may publish a terminal outcome; duplicate messages and late workers must not overwrite a retry. |

`processing/lifecycle.py:claim`, `heartbeat` and `finish` enforce database-clock authority; `processing/recovery.py:recover_expired` ends abandoned execution without automatically retrying it. `processing/short_encoder.py:encode_record` reuses `processing/worker/sqs.py:execute_message` and redirects unsuitable sources through `processing/messaging.py:redirect_to_long_lane`. Both lanes retain the same fences. Output validation in `processing/schemas.py` and `finish` requires one primary MP4; HLS remains optional.

### TR-6 Bounded capacity and independent release

| Aspect | Transition |
|---|---|
| Analysis objects | Operator, ProcessingCapacity, ReleaseCandidate. |
| Use cases | UC-6, UC-7. |
| Class-diagram changes | Map capacity to `LauncherControl` and `LaunchReservation`; add `Planner`, `Journal` and `CLITransport` for release evidence, durable intent and cloud operations. |
| Sequence-diagram changes | Add SQL-serialised slot reservation before RunTask, concurrent-wake and lost-reply branches. For release, show validation → pending intent → migration → owner alias/task-definition change → smoke → adoption or restore; retain unresolved intent for resumption. |
| Reason | Bound outstanding standard encoder slots to three and preserve uncertain cloud outcomes while changing Processing independently of Media. |

`processing/launcher.py:tick` and `_send` preserve the RunTask token and reservation across ambiguous responses. This cap concerns standard finite Fargate capacity; the short Lambda lane has separate admission controls. `scripts/aws/v1/proof/release_plan.py:Planner` checks image evidence, `scripts/aws/journal.py:Journal` persists intent, and `scripts/aws/transport.py:CLITransport.call` executes operations. `scripts/aws/v1/release.py:promote` and `restore` implement per-owner change and recovery. Restore returns images and aliases to their previous state; it does not reverse schema migrations.
