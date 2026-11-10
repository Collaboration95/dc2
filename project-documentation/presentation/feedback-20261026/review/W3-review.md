# W3 independent review — 26 October 2026

**Result: PASS with corrections applied.** Scope is the two selected detailed-design cases, edit, components and state models at Main `76282d3b5a141f6548056f2506f9d5aff0742692`. This is an independent source/design review, not assessor acceptance or proof of deployed behavior.

Read `FEEDBACK.md` and `WORKPLAN.md` first, then inspected the source under `media/`, `processing/`, `media_engine/`, `delivery/`, `contracts/` and the cited schedule generator. The producer's conclusions and earlier QA receipts were not accepted as evidence. No application/IaC/workflow changes, `site/deck.html` edits or commits were made.

## Findings and repairs

### F01 — High: command callback was shown publishing and returning a Lambda response

**Location:** `W3-07-a2-submit-execute.puml`, old `s30`, corresponding report explanation. `handle_command` was followed by self-calls to `publish_outbox` and transport send, then a partial-batch reply to the queue. That assigns orchestration and a return type to the wrong function.

**Evidence:** [`handle_command` returns bool after its transaction](https://github.com/Collaboration95/dc2/blob/76282d3/processing/messaging.py#L232); [`handlers.invoke` consumes the batch and then attempts publication](https://github.com/Collaboration95/dc2/blob/76282d3/processing/handlers.py#L55); [`consume_batch` builds the partial-batch response](https://github.com/Collaboration95/dc2/blob/76282d3/delivery/sqs.py#L112).

**Fixed:** separate handler/batch interaction W3-07 from one atomic submit callback W3-07a. The publisher is always attempted after normal batch completion; success and caught exception are alternative outcomes. Publication may send either work or result rows. Asynchronous mapping delivery uses an open arrow; awaited publication remains a filled call arrow.

### F02 — High: replies bypassed actual callers and wrappers

**Location:** W3-06, 06a, 08, 13 and 23. Examples included Storage replying with reservation/public API data to the owner, and lifecycle replying directly to the worker despite a messaging wrapper.

**Evidence:** [`reserve` returns the reservation dictionary](https://github.com/Collaboration95/dc2/blob/76282d3/media/services/direct_intake.py#L139), [`finalize_upload` maps Asset to Accepted](https://github.com/Collaboration95/dc2/blob/76282d3/media/api/uploads.py#L36), [`public_job_from_projection` sets the signed URL](https://github.com/Collaboration95/dc2/blob/76282d3/media/projections.py#L258), and [the messaging finish wrapper returns lifecycle's result](https://github.com/Collaboration95/dc2/blob/76282d3/processing/messaging.py#L405).

**Fixed:** replies return through each real caller; module and instance lifelines are explicit, with activation bars and numbered messages. API response conversion is distinguished from a service function's Asset/URL/bool return. A found-call boundary names the omitted API caller where adding a lifeline would obscure the main interaction.

### F03 — Medium: callback ownership and Claim/worker identity were conflated

**Location:** W3-09a, 11, 13 and 23. The probe hook and recovery callback were self-calls on modules that do not define those functions; the stale worker lifeline combined worker execution with the Claim data type.

**Evidence:** [`check_probe`](https://github.com/Collaboration95/dc2/blob/76282d3/processing/short_lane.py#L94), [injection of the hook](https://github.com/Collaboration95/dc2/blob/76282d3/processing/short_encoder.py#L82), [`interrupt` invokes `on_change`](https://github.com/Collaboration95/dc2/blob/76282d3/processing/recovery.py#L24), and [real `authorize`/`changed` callbacks inside messaging.claim](https://github.com/Collaboration95/dc2/blob/76282d3/processing/messaging.py#L337).

**Fixed:** show short_lane, messaging, lifecycle and worker.sqs as the actual modules. `work: Claim` is the worker's argument, not a worker class. Claim/finish callbacks return through their owning modules; nested callback activations are shown.

### F04 — High: edit explanation implied response-before-publication ordering

**Location:** old two-panel edit section and its notes/report prose. The guaranteed causal boundary is the adoption commit. An independent scheduled repair may run before the HTTP 202 response reaches the client.

**Evidence:** [edit stages submit inside adoption and returns afterward](https://github.com/Collaboration95/dc2/blob/76282d3/media/services/v1_lifecycle.py#L145), [the separate Media handler publishes](https://github.com/Collaboration95/dc2/blob/76282d3/media/handlers.py#L70), and [`publish_due` commits its reservation before send](https://github.com/Collaboration95/dc2/blob/76282d3/delivery/sql.py#L77).

**Fixed:** W3-14 is a single main interaction showing preflight, durable staging, the locked copy transaction, adoption and submit intent. W3-14a is an independent relay; W3-14b/c separately expand copy and adoption. Source pin verification stays **inside** edit adoption. The parent link, optional RequestKey, staged-ledger deletion, replay, losing-copy cleanup and transaction scope are retained in notes. Relay numbering restarts at 1. Prose explicitly guarantees commit-before-send rather than 202-before-send.

### F05 — High: recovery's false branch included ineligible and terminal work

**Location:** W3-17 activity diagram. “Not queued” was treated as a dead claimed encoder, omitting the processing/current/deleted/expiry-or-STOPPED prerequisites.

**Evidence:** [queued work selection/recheck](https://github.com/Collaboration95/dc2/blob/76282d3/processing/recovery_v1.py#L84), [expiry selection/recheck](https://github.com/Collaboration95/dc2/blob/76282d3/processing/recovery.py#L40), and [durable STOPPED task matching](https://github.com/Collaboration95/dc2/blob/76282d3/processing/recovery_v1.py#L252).

**Fixed:** add the explicit interruption-eligibility decision and a no-mutation branch. Queued repair keeps the UUID, updates next_dispatch_at and recreates/rearms transport intent; execution interruption abandons the Attempt and fails the Job. Owner retry creates a new Attempt. The 120s constant is a target, not a measurement.

### F06 — Medium: result application and public-read guards needed explicit scope

**Location:** W3-08, 13a and the read continuation. A successful projection write was drawn without distinguishing validate_transition=False or an absent/not-done projection. The original combined interaction was too compressed to show the relevant boundaries.

**Evidence:** [`validate_transition`](https://github.com/Collaboration95/dc2/blob/76282d3/media/projections.py#L36), [return before mutation when stale](https://github.com/Collaboration95/dc2/blob/76282d3/media/projections.py#L116), [`consume_result` ignores the callback's bool](https://github.com/Collaboration95/dc2/blob/76282d3/media/messaging.py#L16), and [the `job and job.status == "done"` signing guard](https://github.com/Collaboration95/dc2/blob/76282d3/media/projections.py#L261).

**Fixed:** separate result transaction W3-08 and public read W3-08a. A new stale message still commits inbox and returns True from consume_result; identical inbox replay returns False before callback. Projection conflict raises and rolls back the inbox too. The signing fragment includes the missing-job check. W3-13a distinguishes older versions, later versions of older attempts, same-version replay, conflicting content and valid progression.

### F07 — Medium: class visibility, scope and associations were incomplete

**Location:** all nine class/module figures, especially W3-03/04/10/20/21. Operations and fields lacked visibility; current-attempt and retry-successor references lacked their end multiplicities. Factory scope was not explained.

**Evidence:** [Job/Attempt foreign keys and typed fields](https://github.com/Collaboration95/dc2/blob/76282d3/processing/models.py#L15), [RetryRequest](https://github.com/Collaboration95/dc2/blob/76282d3/processing/models.py#L77), [unique reservation asset_id without an Asset FK](https://github.com/Collaboration95/dc2/blob/76282d3/media/upload_models.py#L31), and [Envelope classmethod](https://github.com/Collaboration95/dc2/blob/76282d3/contracts/v1.py#L170).

**Fixed:** `+` public and `-` internal-by-convention visibility, class/module-scope underlining, multiplicities at both ends of current/successor references, and explicit logical/no-FK reservation association. `from_dict` is identified as @classmethod; self/cls remain implicit. Unannotated Python parameters/returns stay untyped. AST verification checks all 134 displayed fields/constants/operations against the actual definitions. No invented OO class/method remains; real module functions are stereotyped as modules rather than moved onto entities.

### F08 — Medium: frozen Claim was described as deeply immutable

**Location:** W3-04 title/legend, W3-10 Claim description and related speaker/report prose.

**Evidence:** [Claim is frozen but contains dict/list fields](https://github.com/Collaboration95/dc2/blob/76282d3/processing/lifecycle.py#L123).

**Fixed:** use “frozen”/“captured” authority, and explicitly distinguish frozen field bindings from mutable source/operations contents. The selected Claim fields are now visible on the main retry class figure, making A1/T1 versus A2 authority concrete.

### F09 — Medium: the pure engine shared an Adapter stereotype

**Location:** W3-02 Processing component view. Supervisor and all media_engine modules shared one Adapter box; launcher_trigger also appeared in the shared-library colour group despite belonging to Processing.

**Evidence:** [pure command builder](https://github.com/Collaboration95/dc2/blob/76282d3/media_engine/operations.py#L10), [Supervisor subprocess adapter](https://github.com/Collaboration95/dc2/blob/76282d3/processing/worker/supervisor.py#L111), [WakeOnWork](https://github.com/Collaboration95/dc2/blob/76282d3/processing/launcher_trigger.py#L32), [EcsPort](https://github.com/Collaboration95/dc2/blob/76282d3/processing/launcher_aws.py#L54), and [QueueDepth](https://github.com/Collaboration95/dc2/blob/76282d3/processing/launcher_aws.py#L96).

**Fixed:** separate pure engine functions from Supervisor's adapter role; place/name the Processing wrapper correctly. Retain justified roles: repositories.assets lookup/replay, Minio/boto3/subprocess adapters and transactional outbox. These are implementation-role annotations; the code does not establish a GoF Strategy hierarchy or a Protocol-based repository layer. Direct ORM dependencies remain visible.

### F10 — Medium: grant details overstated fixed POST length and its return value

**Location:** W3-06a. The Storage response was shown as a complete reservation response, and “fixes length” implied an exact POST size.

**Evidence:** [POST policy length range and grant dictionary](https://github.com/Collaboration95/dc2/blob/76282d3/media/services/storage.py#L42), [reserve response assembly](https://github.com/Collaboration95/dc2/blob/76282d3/media/services/direct_intake.py#L139), and [finalize verification enforces exact size/hash](https://github.com/Collaboration95/dc2/blob/76282d3/media/services/storage.py#L62).

**Fixed:** Storage returns method/url/fields to reserve, which returns the reservation dictionary through the API. The grant permits 1..declared-size bytes; finalize checks exact bytes. Finalized replay returns upload=None, pending expiry raises 410, hash conflict raises 409, and the 15-minute/100-MiB limits remain accurate.

### F11 — Medium: state labels hid cancellation side effects and terminal scope

**Location:** W3-15/16. “Repeat cancel / idempotent” concealed the fresh confirmation result of a new cancel message. Status-changing guards and terminal-record semantics needed qualification.

**Evidence:** [repeat cancel can call emit_state](https://github.com/Collaboration95/dc2/blob/76282d3/processing/messaging.py#L215), [snapshot overlays cancelled without adding jobs.status](https://github.com/Collaboration95/dc2/blob/76282d3/processing/messaging.py#L60), [live fence](https://github.com/Collaboration95/dc2/blob/76282d3/processing/lifecycle.py#L28), and [automatic live NotAdmitted successor](https://github.com/Collaboration95/dc2/blob/76282d3/processing/messaging.py#L412).

**Fixed:** keep Job.status and deletion orthogonal; qualify status transitions by current/nondeleted authority, show error/valid-output guards, and name fresh confirmation on repeated cancellation. Active Attempts become cancelled while terminal Attempts retain their state. Terminal Attempt states have no path back to queued; retry/redirect create new identities. Terminal states retain their rows; the figures do not model record deletion or a completed Python state-machine instance. The Job statechart now fits the main talk; s61 keeps its backup copy.

### F12 — Medium: evidence anchors landed on blanks or unrelated effects

**Location:** W3 HTML, PlantUML source ledgers and report notes. Examples: projections#L246 was a failure-message assignment rather than public signing; storage#L190 and lifecycle#L122 were blank; supervisor#L124 was a local flag assignment rather than run's definition.

**Evidence:** [actual public signing function](https://github.com/Collaboration95/dc2/blob/76282d3/media/projections.py#L258), [sign_output](https://github.com/Collaboration95/dc2/blob/76282d3/media/services/storage.py#L191), [Claim](https://github.com/Collaboration95/dc2/blob/76282d3/processing/lifecycle.py#L124), and [Supervisor.run](https://github.com/Collaboration95/dc2/blob/76282d3/processing/worker/supervisor.py#L111).

**Fixed:** replace blank/nearby anchors with exact definitions/effects. Publication links now point to the publish call, ACK links to the delete condition, the schedule link to its rate expression, and finalize to its own API function. The final permalink ledger records every target line and checks its pinned source bytes. This verifies the local commit/path/anchor; no remote browser/HTTP link-success claim is made.

### F13 — High: main-talk count, placement and legibility did not meet the brief

**Location:** `slides/W3.html` and main sequence images. There were 13 main sections, repeated competing `NEW after` anchors, and a two-panel edit sequence. Original slide-scale minima included A2 acceptance 11.84px, finalize 12.60px and edit 12.09px; the original main-set measurements are retained in [before-metrics.json](W3-qa/before-metrics.json).

**Evidence:** local HTML/PNG measurements above; the source interactions that require separate transactions/callers are [finalize](https://github.com/Collaboration95/dc2/blob/76282d3/media/services/direct_intake.py#L149), [edit](https://github.com/Collaboration95/dc2/blob/76282d3/media/services/v1_lifecycle.py#L105), [claim](https://github.com/Collaboration95/dc2/blob/76282d3/processing/messaging.py#L325), and [finish](https://github.com/Collaboration95/dc2/blob/76282d3/processing/lifecycle.py#L184).

**Fixed:** eight ordered main slides; all others have data-kind=back and NEW backup, preserving REPLACES s61/s67. Dense result/read, primary/HLS, edit/copy/adoption and claim/finish interactions are split. All 35 PlantUML figures were regenerated and rasterized with the requested tools. Main figures were visually inspected with the actual 1280×720 deck CSS, not inferred only from SVG dimensions. All fit above the footer; the smallest main figure text is 13.19px. The full-size PNG/slide-fit proofs and per-figure metrics are retained. The detailed Job statechart became legible after wrapping its guards, so it is included as the eighth main slide.

## Main-talk integration

| Order | Placement | Section / figure |
| --- | --- | --- |
| 1 | REPLACES s28 | s28 — Media components / W3-01 |
| 2 | NEW after s28 | w3-processing-components / W3-02 |
| 3 | NEW after w3-processing-components | w3-a-classes / W3-03 |
| 4 | REPLACES s29 | s29 — case A finalize sequence / W3-06 |
| 5 | REPLACES s30 | s30 — edit sequence / W3-14 |
| 6 | REPLACES s31 | s31 — case B classes / W3-10 |
| 7 | NEW after s31 | w3-stale — stale Claim sequence / W3-13 |
| 8 | NEW after w3-stale | w3-job-states / W3-15 |

37 sections total: 8 main and 29 backup. There are 35 unique diagrams, plus the intentional repeat of W3-15 in s61 and the retry-surfaces table. No integration into the shared deck was performed.

## Verification record and limits

- [Reproducible checks and counts](W3-qa/verification.json): pinned HEAD, source equality, protected-file hashes, class members/signatures, slide IDs/placements, image references, SVG parsing and minimum main text size.
- [Class member audit](W3-qa/class-signature-audit.json), [permalink target ledger](W3-qa/permalink-audit.json), [pinned source hashes](W3-qa/source-audit.json), [render metrics](W3-qa/render-metrics.json) and [slide manifest](W3-qa/slides-manifest.json).
- Main slide previews are `W3-qa/main-01.html` through `main-08.html`; raster proofs are in `../report-notes/W3-qa/`. Contact sheets cover all 35 rendered figures. Calls/guards/transitions were manually source-reviewed in addition to the AST check; the latter is not proof of runtime behavior.
- The shared `site/deck.html` changed during this review outside this task's writes. Its initial hash is retained in protected-hashes.json; final verification records the drift without overwriting the coordinator's work. Application-source hashes remain unchanged. This is not a claim that the entire shared worktree stayed unchanged.
- Regeneration used `java -Djava.awt.headless=true -jar ~/dc2-tools/plantuml-1.2026.9.jar -tsvg <file>` and `npx -y @resvg/resvg-js-cli@2.6.2-beta.1`. This was documentation/render validation; no new application tests, AWS operations, measured recovery run or course grading were performed.

No confirmed W3 defect remains open in the reviewed scope. The figures intentionally select fields and interactions; they do not claim every branch of the entire application is drawn. Python's unannotated function types remain unspecified. Entity rows retain their real field types and no entity methods were invented. Current deployment state, external HTTP availability and human acceptance remain outside this source/design review.
