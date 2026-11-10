# Final report v1.0 → v1.1: consolidated change plan

Prepared 26 October 2026. Final report due **16 November 2026**. Baseline: Main `76282d3b5a141f6548056f2506f9d5aff0742692`. This is a written plan; no report source, application, infrastructure or workflow is changed. All source lines below refer to that baseline, before insertions. The existing PDF is **66 pages**, with **22 numbered figures** excluding the cover logo.

## Corrections first

Apply these corrections through the RC entries below. This index is not a second set of edits. Preserve dated receipts rather than changing historical observations to match later configuration.

| Wrong or overbroad v1.0 statement | Required correction | Apply in |
|---|---|---|
| The launcher chooses clips for Lambda by duration/resolution | `messaging.emit_state → short_lane.work_lane` selects the staged lane from enable flag, source size and previous Lambda binding. The executor probes duration/height later. | RC-11, RC-17, RC-25 |
| Short encoder uses the Processing image; all seven Processing functions use one image | Six Processing functions use `ProcessingImageUri`; `ProcessingShortEncoder` and Fargate use `WorkerImageUri`, with different entrypoints. | RC-11, RC-15, RC-17 |
| Three queues and three DLQs describe enabled dc2-live | Three logical flows; **four source queues plus four DLQs** with short encoding enabled. Five message kinds; `work` has two internal Processing lanes. | RC-06, RC-14, RC-15 |
| 13 configured alarms in enabled V2-live | **15 = 11 Lambda error alarms + 4 DLQ alarms**. The earlier 13/13 `OK` observation remains an earlier receipt, not a test of the 15-alarm configuration. | RC-15, RC-30, RC-31 |
| `attempts/{attempt}` can be read as a retry number | Outputs use `jobs/{job_uuid}/attempts/{attempt_uuid}/`; `attempt_number` is separate. Sources stay at the adopted reservation key or an edit-derived key. | RC-21, RC-25 |
| Every interaction between the services is SQS | Business handoff is asynchronous. Protected Processing HTTP requests depend synchronously on Media's authorizer/current User lookup; S3 access is another dependency. | RC-02, RC-06, RC-07, RC-40 |
| Adapter discards the session cookie; TTL 0 revokes executing requests immediately | It discards the raw header and reconstructs Cookie from Gateway's cookie list. Media revalidates it; Processing trusts Actor. TTL 0 prevents authorization-result reuse. | RC-07, RC-32 |
| UploadReservation is always an Asset child; SubmissionGuard is always a Job child | Both can exist before the respective Asset/Job. Show independent lifecycles, interpreted roots and explicit multi-root local transactions. SourceVersion is a persisted pin value record. | RC-13 |
| Customer/Supplier and Shared Kernel are established DDD relationships | Formal team governance is UNKNOWN. Keep Published Language and the evidenced incoming Media validation/mapping; distinguish shared libraries from a Shared Kernel agreement. | RC-09, RC-12, RC-33 |
| Consumers currently support N and N−1 | Producers emit 1 and consumers accept only 1 at this commit. N/N−1 is rollout policy/future compatibility, not two deployed versions. | RC-09, RC-31 |
| No committed message can ever be lost | State and recoverable publication intent commit together; future successful relay/repair and retained SQL state are required. Uncertain sends can duplicate. | RC-20, RC-25, RC-31 |
| Retry replay always returns the originally created Attempt; jobs are never automatically requeued | Replay returns the current Attempt. Execution expiry/error needs owner retry; live `NotAdmitted` creates a new standard-lane Attempt automatically. | RC-27, RC-40 |
| Cancellation is a `jobs.status` state | Job status is queued/processing/done/failed; deletion and Attempt cancellation produce the cancelled snapshot. Claim is shallow-frozen, not recursively immutable. | RC-27 |
| Private networking does not exist between Lambdas | Functions are VPC-attached. Peer business HTTP is unused; Gateway/Actor and IAM are the implemented invocation boundary. | RC-29, RC-37 |
| All Main CI is green; all scanners publish SARIF and findings block merges | The 25 Oct scheduled full CI failed in inherited image scans. Per-engine failure/publication policies differ; ZAP findings are report-only, Sonar analysis skipped, CodeQL independent, Main protection absent in the dated review. | RC-03, RC-32–RC-36 |
| Equal allocations are measured personal effort; recordings were prepared | Retain the allocation/not-timesheet qualifier. Team confirmation and accessible demonstration evidence remain pending. | RC-04, RC-39 |

Evidence: [routing and admission][lane], [work staging][emit], [redirect][redirect], [image assignment][images], [queues][queues], [alarms][alarms], [output prefix][prefix], [adapter][adapter], [finalize][finalize], [guard/cancel][cancel], [version contract][contract], [relay][relay], [25 Oct CI][ci25]. Detailed anchors and qualifications follow each change.

## Integration decisions and evidence rules

Read together: [FEEDBACK.md](FEEDBACK.md), [WORKPLAN.md](WORKPLAN.md), the six [report notes](report-notes/), [R4 audit](research/R4-feedback-audit.md), [R5 references](research/R5-external-references.md), and the independent [W1](review/W1-review.md), [W2](review/W2-review.md), [W3](review/W3-review.md), [W4](review/W4-review.md), [W5](review/W5-review.md), [W6](review/W6-review.md) reviews. Their reviewed corrections supersede earlier drafts and producer QA records.

| Overlap | Consolidated choice and reason |
|---|---|
| W1/W6 both explain authorization | **W1 wins the one embedded request/authorizer sequence**. W6's reviewed trust prerequisite and Media revalidation qualify its prose. Do not embed both W1-authorizer and W6-trust-boundary. |
| W1/W3/W6 describe lane selection and runtime handoff | **W1 owns policy and physical distribution**; **W3 owns object/function interactions**. W6 supplies the logical overview and concise relay explanation. Omit W6's two service-level handoff sequences because selected W3 sequences provide the requested detail. |
| W3/W6 both decompose Processing | **W3's two component diagrams win internal decomposition**. Use W6-logical only at service level; omit W6-processing-components. |
| W2/W3 both replace the empty implemented class model | **W2 owns domain grouping** in Platform Design; **W3 owns use-case class/module collaborations** in Detailed Design. Remove the old common class figure; do not print both entire figure libraries. |
| W2/W4 describe the same records | **W2 wins entity/value/root interpretation; W4 migrations win SQL fields, defaults, constraints and cardinalities**. A DDD composition arrow is not a database FK. |
| W2/W4/W6 describe messages | **W2 owns kind, direction and domain cause**. **W4 owns wire/JSON/S3 shapes**. **W6 owns relay ordering**. One six-row transport table; one schema table; no three competing payload inventories. |
| W1/W4 differ from historical report counts | Enabled source configuration wins current explanatory text. Historical three-queue/13-alarm tests keep their original scope/date. |
| W4/W5 say SVGs can go directly into the report | **The report README/build workflow wins**: embed PNGs. Keep `.puml`/`.svg` as editable/vector sources and export explicitly below. |
| W1/W4 alternative decisions sound historical | Their reviews win: the ALB comparison and NoSQL ADR are **26 Oct design responses**, pending report adoption; no earlier experiment, migration or benchmark is inferred. |
| W5/R4 status differs from v1.0 | Reviewed per-engine inventory and exact-SHA 23/25 Oct results win. CI success does not establish the currently deployed release. |
| R5's SAD syllabus claim versus W6 review | W6's correction wins: use the programme listing and direct assessor request; the redirected SAD course URL does not verify a detailed syllabus. |

Retain `[AWS]`, `[Local]`, `[Code]` and `NOT_RUN`, adding dates/source/workload where needed. New figures describe **source/configuration at 76282d3**, not a fresh AWS inventory. Uncommitted W1–W6 figures have local links, not fabricated baseline permalinks. External references explain a method or capability; repository code/run evidence establishes its use here. Preserve the old proposal feedback **F-01**, distinct from this audit's **F1–F24**.

Use the actual Practice Project template/briefing and R4's course crosswalk as the requirement authority. `original-reference/report-template-notes.md` is an early planning interpretation, not approval or a newer rubric. Preserve Introduction, Project Conduct, logical/physical/persistence/detailed design, limitations, all four quality attributes and source-control/CI/CD headings. The requested changes fill the specific gaps; they do not invent mandatory retrospectives, an ALB, a database migration or a security vendor.

## Changes by report file and heading

Paths in this section are relative to `project-documentation/final-report/src/`. Figure paths are relative to `project-documentation/presentation/`. For every selected SVG, embed the same-stem PNG under `final-report/figures/` using the export procedure below. “None” means no new figure for that change. Suggested labels are stable build labels, not final figure numbers.

### 00-front.md

**RC-01 · F20, F23 · correct**

**Location:** cover repository/version line, **L26**. Change to `Report version 1.1, <actual finalisation date>`. Keep the 16 Nov deadline in Project Conduct; do not backdate completion or treat the deadline as a submission receipt. **Figures:** none. **Evidence:** [report rebuild and post-presentation instructions][readme]; [Practice Project briefing, p.6][briefing].

### 10-introduction.md

**RC-02 · F2, F16, F18, F19, F22, F23 · correct**

**Location:** Background, **L29–42**, comparison table **L48, L53**, Business Needs **L80–82**, Functionality in scope **L142, L146–147**. Replace the current-status lead and service-dependency wording:

> **Status at the 26 October review.** The implemented source reviewed for this revision is Main `76282d3`. Media and Processing own separate business models and exchange commands/results asynchronously. Protected HTTP requests use a Media-owned Gateway authorizer. The dated cloud results in section 4 retain their original release identities; this revision does not establish a new live deployment. The team presented on 26 October and is revising the report in response to the assessors' remarks, for submission by 16 November.

Change UC-2 to “shared pipeline on finite Fargate or admitted short Lambda execution”; UC-6 to “SQL and visible standard-queue demand, Fargate cap 3”; qualify restore as the owner-release smoke's attempted recovery. Replace “every change passes security gates” with “CI executes the checks selected by policy; release admission applies the image policy.” Keep inherited capability and measured results intact. **Figures:** retain `fig:usecases`. **Evidence:** [authorizer][auth-config], [worker-image mapping][images], [launcher][launcher], [CI aggregate][aggregate], [source-matched CI][ci25], [report's historical release record][release-report].

### 20-conduct.md

**RC-03 · F18, F20–F23 · correct / add text**

**Location:** Project Status, **L63–86**. Date the review **26 October 2026**. Replace “Every Main run green” and the unqualified current-release/branch rows with:

> Main `76282d3` is the source baseline of this design review. Push CI 39931072197 passed on 23 October. Scheduled CI 40174362164 failed on 25 October in the inherited app/processing image-scan steps; V1 image verification and local ZAP passed. Independent CodeQL analysis 40189407647 passed on the same source. Current AWS aliases, digests, gates and health were not read during this review; the earlier verified releases remain dated historical evidence.

Update outstanding rows to distinguish report/figure integration pending, missing demonstration evidence, current scanner failures and optional CODE proposals. Do not describe #192/#254 as delivered from storyboards. Replace the feedback promise with “26 Oct remarks received; response plan prepared; report integration/rebuild pending.” **Figures:** none. **Evidence:** [23 Oct CI][ci23], [25 Oct CI][ci25], [CodeQL][codeql], [v1.0 status][status-report], [baseline clip placeholders][demo-plan].

**RC-04 · F20, F21, F23 · correct / move**

**Location:** Project Metrics, milestone table **L100–102**, effort **L110–140**, delivery metrics **L142–162**. Record the presentation as held on **26 Oct**, without asserting its exact duration or which demos were shown. Record v1.1 as planned/pending until rebuilt. Keep 33 pd/36 pd as **team-agreed allocation to 20 Oct / submission forecast, not timesheets or verified personal hours**. Obtain team-confirmed rough effort and any revised forecast before replacing them. Keep the GitHub metrics explicitly dated 21 Oct; remove the stale implication that the nine issues are still open. Move the burn-up image out of the PDF to linked historical evidence, retaining a short sentence and the dated table. **Figures:** retain `fig:schedule`, refresh only confirmed milestone data; remove `fig:burnup` at **L158** and its references. **Evidence:** [effort/metrics source][metrics-report], [feedback record](FEEDBACK.md), [template][template]. No new personal effort or final submission is verified.

### 30-logical.md

**RC-05 · F7–F11, F19, F20 · add text**

**Location:** Logical Architecture & Design, insert at **L19**, new short heading **Architecture views**. Use a bold subheading (`**Architecture views.**`) to preserve the template's existing numbered headings. If promoted to `###`, renumber affected section references throughout the report. Paste:

> Each view answers a different design question. Names and identifiers remain consistent across the views; source configuration and dated execution evidence are kept separate.

| View | Report home / selected figures | Course connection |
|---|---|---|
| Context and scenarios | Introduction: scope and use cases; Detailed Design: two critical cases | ARCHSS; SAD |
| Logical responsibilities and source structure | Logical Architecture; Tiers and Layers: `logical`, `media-components`, `processing-components` | ARCHSS; selected 4+1 logical/development concerns |
| Domain boundaries and consistency | Platform Design: `contextmap`, `asset-domain`, `job-domain` | Platform Engineering |
| Runtime and trust | Public request boundary; Detailed Design: `authorizer`, `intake-sequence`, `edit-sequence`, `stale-finish` | ARCHSS; SAD; SDP |
| Deployment and capacity | Physical Architecture: `topology`, `lane-dispatch`; artifact/trigger table | ARCHSS; Cloud Native Solution Design |
| Information | Persistence Design and schema appendix: `ermedia`, `erprocessing` | Platform Engineering; SAD |
| Delivery activity and verification | CI/CD: `cicd`, `release-activity`; scanner inventory | DevSecOps |

Add one sentence: “These are view correspondences, not claims of full conformance to C4, 4+1 or arc42. Development structure means static source organization; the delivery pipeline is a separate activity view.” The assessor feedback supplies the specific DDD and object-level expectations. **Figures:** no new views-map image. **Evidence:** [arc42 deployment][arc42], [Kruchten 4+1][kruchten], [ARCHSS][archss], [PE][pe], [SAD programme listing][sad-programme], [SDP][sdp], [template][template].

**RC-06 · F2, F7, F11, F18, F19 · replace figure / correct**

**Location:** Logical Architecture & Design, inventory **L27–43**, `fig:logical` **L45**, dependency bullets **L47–54**. Replace the figure with `site/assets/uml/W6-logical.svg`, keeping label `logical`. Change the shared-kernel row to “shared contract and technical libraries”; messaging to four source queues/four DLQs in the enabled configuration. Paste:

> Media and Processing have separate HTTP integrations and owned databases. Business commands and state snapshots cross SQS; neither service handler calls the other's business API or database. A protected Processing HTTP request still invokes Media's authorizer at Gateway, which reads the current Media User. Media also reads source/output objects for verification, edit and playback. Encoders write Processing state and result intent in SQL; a relay publishes results later.

**Figures:** W6-logical only; omit W6-processing-components. **Evidence:** [Gateway routes/integrations][integrations], [authorizer lookup][authorizer], [Media storage grants][media-grants], [claim/finish callbacks][claim], [Processing relay handler][processing-handler].

**RC-07 · F1, F2, F11 · add text / add figure**

**Location:** after dependency bullets, before current dynamic-view introduction **L56**, new **Public request and identity boundary**. Paste:

> The normal API path is CloudFront `/api/*` → API Gateway HTTP API → the selected API alias. For protected routes, Gateway first invokes `MediaAuthorizer`, a Lambda REQUEST authorizer using Cookie identity, payload v2, simple responses and TTL 0. It verifies the session JWT and current User, then returns Actor context. Gateway invokes the API separately. Health and Media register/login/logout bypass this hook. The adapter strips supplied owner/role headers, rebuilds Cookie from Gateway's cookie list and injects Actor. Media revalidates the cookie/current User; Processing trusts Actor. Restricted Gateway invocation permissions support that trust. TTL 0 prevents cached authorization decisions; it does not revoke an executing request.

Note that execute-api remains publicly reachable; CloudFront is the normal entry, not an enforced sole entry. Do not claim raw duplicate cookie names are strictly rejected: the parser counts parsed cookie-list entries. **Figure:** `site/assets/uml/W1-authorizer.svg` → `fig:authorizer`. **Evidence:** [hook and permissions][auth-config], [public routes][routes], [authorizer parser/lookup][authorizer], [adapter][adapter], [Media revalidation][media-deps], [Processing trust][processing-auth].

**RC-08 · F1, F3, F7–F9, F19 · move / add text**

**Location:** dynamic-view introduction and three phase figures, **L56–63**. Remove `report-seq-intake.png`, `report-seq-encode.png`, `report-seq-play.png` from this location and retire labels `seqintake`, `seqencode`, `seqplay`. Replace with:

> Detailed Design follows upload/process/play and stored-source retry. Media commits acceptance before its scheduled relay sends commands. Processing commits inbox, domain state and outgoing intent before command acknowledgment; its handler then attempts publication. Encoders claim and finish in separate transactions. Media commits inbox and projection before result acknowledgment. Publication can repeat after an uncertain reply; repair depends on later successful invocations.

Point to RC-25–RC-27's named figures; update all old label references under RC-40. The new diagrams replace the old phase illustrations rather than supplementing them. **Figures:** none here. **Evidence:** [Media relay][media-handler], [Processing handler][processing-handler], [SQL relay][relay], [claim/finish][lifecycle], [result consumer][media-consumer].

**RC-09 · F2, F4–F6, F19 · correct**

**Location:** Key Architectural Decisions, **L74, L77–78**, plus “Shared kernel” in inventory/layers **L35, L87, L110**. Update AD-09 from RC-07. AD-21: older or semantically identical snapshots are no-ops; conflicting equal-version content is rejected, and higher versions still pass identity/attempt/transition checks. Replace AD-24's current two-version/shared-governance claim:

> `contracts/` defines the published wire/API values and is copied into each image. At this source, producers emit version 1 and consumers accept only version 1. Additive N/N−1 evolution is policy; formal Shared Kernel governance is not established by code reuse.

Keep AD identifiers; do not rewrite historical decision records as if governance had been verified. **Figures:** none. **Evidence:** [accepted versions/Actor/Envelope][contract], [projection fences][projection], [image copies][media-image], [Processing image copies][processing-image].

**RC-10 · F7, F8, F11 · add figure / add text**

**Location:** Tiers and Layers, after table **L89**, before dependency rules **L91**. Add `site/assets/uml/W3-01-media-components.svg` (`media-components`) and `site/assets/uml/W3-02-processing-components.svg` (`processing-components`). Paste:

> Component views expand the two service responsibilities into real handler, service, repository and adapter modules. Media uses repository helpers for repeated owned lookup and replay; both services also query SQLAlchemy records directly. Storage and subprocess adapters perform I/O; `media_engine` builds commands without I/O. Interface symbols name provided exports, not new Python Protocol classes. The decomposition does not imply strict dependency inversion or a GoF Strategy hierarchy.

**Evidence:** [owned lookup][asset-repo], [Media direct ORM imports][edit], [Processing command functions][command], [subprocess Supervisor][supervisor], [pure engine][engine]. Do not repeat these figures in Detailed Design or the appendix.

**RC-11 · F12, F16, F18 · correct**

**Location:** Nodes and Subsystems, **L108–116**. Split Capacity/Encoding into dispatch, standard capacity, short execution and standard execution rows. State: dispatch stages the lane inside Processing's transaction; launcher observes SQL plus standard-queue visibility and reserves Fargate capacity; short Lambda uses WorkerImageUri; finite workers long-poll and claim at most one Attempt. Replace “each runs under that context's image” with the exact three-artifact mapping in RC-15. **Figures:** cross-reference `lane-dispatch` and `topology`; no duplicates. **Evidence:** [emit][emit], [lane policy][lane], [launcher][launcher], [worker polling][worker], [image branch][images].

**RC-12 · F4, F6, F11, F19 · add text / replace figure**

**Location:** Platform Design, introduction **L120–123**, context map **L125**, bounded-context table **L127–132**, relationships **L192–200**. Retain the earlier F-01 history, then add:

> The 26 October review derives the boundary from language, invariants and change responsibilities. Media groups current identity, owned intake/adoption, derived edits and authorized playback. These require Asset ownership and its local projection together. Processing groups Job/Attempt transitions, leases, retry/cancel and execution recovery. Splitting Identity, Upload or Delivery would introduce additional boundaries around the existing owned operations; no independent implemented model is established for them. Separate models and execution needs support the split, while adding asynchronous integration and operational cost. This is the current rationale, not a recovered record of team negotiation.

Use a compact capability → vocabulary/rule → required consistency → context table from W2; retain five rows: ownership, source adoption/edit, playback/projection, execution/recovery, pre-Job cancellation. Replace `fig:contextmap` with `site/assets/uml/W2-context-map.svg`. Replace Customer/Supplier bullets with scoped Processing-result-model upstream/Media downstream interpretation, Published Language (`Envelope`/`Source`), and incoming Media validation/mapping as an ACL interpretation. Actor is separate API context; Shared Kernel/Customer-Supplier governance remains UNKNOWN. **Evidence:** [adoption][finalize], [edit][edit], [projection][projection], [Job/Attempt][job-model], [guard][cancel], [Evans patterns][evans].

**RC-13 · F4–F6, F8 · correct / add figure**

**Location:** Platform Design, Aggregates and their invariants, **L149–171**. Replace the two universal membership lists with:

> Asset and Job are the principal business-root interpretations. Asset owns source identity; an edit-derived pin is a `SourceVersion` value record, while a direct-upload pin remains on `UploadReservation`. Job owns the numbered Attempt history and current execution authority; Source/Output field data are embedded values. User, pre-adoption UploadReservation and pre-Job SubmissionGuard have independent lifecycles. Request/retry/binding, cleanup and inbox/outbox records support local invariants; they are not all child domain entities. No transaction crosses the databases.
>
> The ORM classes mainly declare fields and constraints. Service functions enforce ownership, transitions and lease fences. Finalize spans reservation/new Asset, and Processing commands can span guard/Job; these are explicit local multi-root transactions. The diagrams describe the implemented grouping and its limits rather than claiming rich, encapsulated aggregate objects.

Add a four-row boundary table: Asset/pin; User/reservation; Job/Attempt; independent guard/supporting ledgers. State `lock_pair` locks Job then reads/checks Attempt; claim acquires authority, heartbeat/finish require live authority. **Figures:** `site/assets/uml/W2-media-asset.svg` (`asset-domain`), `site/assets/uml/W2-processing-job.svg` (`job-domain`); link W2's intake/support sheets rather than print them. **Evidence:** [Media records][media-model], [pin/reservation records][upload-model], [Processing records][job-model], [finalize][finalize], [guard/cancel][cancel], [lock/live][lifecycle], [aggregate guidance][vernon].

**RC-14 · F5, F6, F10, F18 · correct / add text**

**Location:** Platform Design, vocabulary **L140–145**, Messages **L173–190**, producer/consumer mapping **L207–211**. Distinguish positive integer `source_revision` from S3 VersionId; Asset/public job ID from internal Job ID. Keep the table's five kinds, expanding work to two rows:

| Kind | Logical lane | Sender → consumer |
|---|---|---|
| submit | processing-commands | MediaRepair → ProcessingCommands |
| retry | processing-commands | MediaRepair → ProcessingCommands |
| cancel | processing-commands | MediaRepair → ProcessingCommands |
| work | processing-work | Processing relay → finite Fargate worker |
| work | processing-work-short | Processing relay → ProcessingShortEncoder |
| result | media-results | Processing relay → MediaResults |

Result is a full snapshot on accepted state changes, not only completion; heartbeat emits none. Work stays inside Processing. There are no separately named persisted domain events and no event sourcing. Label the three-queue send-denial observation as its original historical AWS scope; four-queue authority is source configuration until separately tested. **Figures:** none. **Evidence:** [five kinds and source types][contract], [lanes][transport], [state emission][emit], [heartbeat][lifecycle], [configured producer policies][queue-policy].

### 32-physical.md

**RC-15 · F11, F18, F19, F23 · replace figure / correct**

**Location:** Physical Architecture & Design, operating modes **L3–17**, component table **L20–34**. Caption the new view “Configured dc2-live with applications, unattended launch, short encodes and separate databases enabled; Main 76282d3; not a deployment receipt.” Replace `fig:topology` with `site/assets/uml/W1-deployment-main.svg`. Correct the table:

- Four Media functions use MediaImageUri; six Processing functions use ProcessingImageUri. Short encoder and finite worker use WorkerImageUri; Lambda overrides its entrypoint with `python -m awslambdaric`.
- Eleven functions total; four source queues/four DLQs; five EventBridge rules including the launcher fallback; 15 configured alarms, no paging.
- Two separate Aurora clusters, one instance each, default 0–2 ACU. Two-AZ subnet choices do not imply replica failover.
- Five SecureString DSN/JWT parameters plus four String activity markers. Do not publish values.

Add a compact source → image → handler/task → alias/trigger → placement → owned data/authority table. Use W1-artifacts/triggers/events/stores as source references, not four more PDF figures. Map both APIs, authorizer, command/result consumers, repair/hint handlers, launcher, short encoder and finite worker; retain exact names from the generator. Keep earlier deployment dates as dated receipts; remove “always open” as an independently verified current state. **Evidence:** [handler map][handler-map], [image/function settings][images], [mappings][mappings], [alarms][alarms], [rules][rules], [database options][db-options], [activity parameters][activity-params], [persistent feature selection][persistent].

**RC-16 · F11, F18 · correct**

**Location:** Network, **L38–47**. Expand the source-based network explanation without adding a second body topology:

> VPC-attached Lambdas use private subnets in two AZ choices, IPv6 egress-only routing for dual-stack AWS APIs and no IPv4 default route/NAT. Finite workers use public subnet choices, temporary public IPv4 and HTTPS egress through the internet gateway; they have no inbound compute rule. The S3 gateway endpoint covers all four route tables and permits source/output plus the regional ECR layer bucket. Shared Lambda security groups reach both database groups; finer ownership uses IAM parameter scope and database roles. Worker SQL ingress is limited to Processing.

Keep the external port scan only as its dated receipt. **Figures:** link `site/assets/uml/W1-network.svg` from the appendix evidence index; do not embed under the budget. **Evidence:** [subnets/endpoint/SG definitions][network], [worker RunTask networking][worker-network], [parameter scope][parameter-policy].

**RC-17 · F11, F12, F16, F18 · add text / add figure / correct**

**Location:** Key Architectural Decisions, **L55–66**; add **Load distribution and execution admission** after the table, before Technology and Services **L68**. Correct AD-10/13/15/18/25/27 consistently with RC-15/16. Add current review decision **RD-01**, a report-local ID, leaving AD-01…29 unchanged:

> **RD-01 — retain direct Lambda integration and queue-driven workers; no ALB.** Gateway routes/throttles HTTP requests and Lambda supplies concurrent invocations. SQS buffers asynchronous work; mappings invoke consumers and finite workers issue ReceiveMessage themselves. The custom launcher reserves standard-worker capacity before ECS RunTask. An ALB plus ECS HTTP service would add health-checked HTTP targets and standing infrastructure, but would still need a separate queue-capacity policy. These workers expose no HTTP listener. Retain the current arrangement for this release; reconsider when sustained warm HTTP containers are required. This is a 26 October alternative analysis, not a historical ALB trial or measured cost comparison.

Add a five-row bounds table: HTTP throttle 20/s, burst 50; command/results mappings max 2 each; short batch 1/max 2; standard launcher cap 3; one 0–2 ACU instance per cluster. No reserved/provisioned Lambda concurrency is configured. The combined encoder ceiling is **5**, subject to quota/capacity, not a demonstrated five-way benchmark. SQL backlog plus visible standard work constrains launch; reservations are separate from Attempt claims.

> Dispatch stages short work only when enabled, source size is a strict positive integer ≤64 MiB and no prior Lambda task binding exists for the Job. After claim/download, the short executor probes finite duration `(0,60]` seconds and source height ≤1080. A live-lease `NotAdmitted` redirect abandons that Attempt and creates a new standard-lane Attempt. Ordinary failure/expiry waits for owner retry. Duration and height are not dispatch inputs.

**Figure:** `site/assets/uml/W1-dispatch.svg` (`lane-dispatch`). Link W1-probe-redirect as supporting detail; do not embed a second policy figure. **Evidence:** [Gateway limits][gateway-limits], [mapping caps][mappings], [launcher reservations][launcher], [lane predicates][lane], [redirect][redirect], [single instances][database], [AWS ECS service traffic][ecs-lb].

**RC-18 · F13 · add text**

**Location:** Technology and Services, after the table **L87**, before Runtime and development tools **L89**. Add **RD-02 — retain PostgreSQL authority; reassess document reads when justified**. This is W4's NoSQL ADR, shortened:

> Asset/source/output metadata is document-shaped, and the current schemas already embed variable descriptors as JSONB; video bytes remain in S3. Retain each context's PostgreSQL authority for v1.1 because atomic state/inbox/outbox updates, uniqueness, DB-clock lease fences and due-work queries already operate together. MongoDB and DynamoDB can implement comparable guarantees, but require an explicit model, concurrency/clock policy and publication design. No comparative cost or performance benchmark was run.

| Requirement | PostgreSQL now | MongoDB alternative | DynamoDB alternative |
|---|---|---|---|
| Owned Asset and local result read | Owner-filtered local join plus JSONB | Owner/Asset document and indexes | Owner partition/Asset key plus listing index |
| State + inbox + outgoing intent | One local SQL transaction | Bounded embedding or multi-document transaction | Conditional item writes and transaction/CDC design |
| Message/request and task uniqueness | Unique/composite constraints | Suitable unique indexes | Explicit identity reservation items/conditional transactions |
| Lease, current Attempt, due work and capacity | DB-time fences, locks, due indexes | CAS/transaction and due-index/clock policy | Conditional updates, partition/due-query and clock policy |

> MongoDB supports single-document atomicity and multi-document ACID transactions on supported replica-set/sharded deployments. DynamoDB supplies all-or-nothing item transactions. Neither makes an external SQS send part of a database transaction. Revisit a separate owner-facing read projection only after measured read patterns, cost and latency justify it; plan backfill, version/attempt fences, tombstones and reconciliation. Current result messages are snapshots, not a complete retained event log for rebuilding a store.

Cross-reference Persistence Design; do not repeat the ADR there. RD-01/RD-02 are proposed report responses until adopted, not additions already made to the repository ADR register. **Figures:** none. **Evidence:** [local owner query][owner-list], [SQL publication][relay], [lease clock][lifecycle], [JSONB model][job-model], [MongoDB transactions][mongo], [DynamoDB transactions][dynamo], [transactional outbox guidance][outbox-guidance].

### 34-persistence-detailed.md

**RC-19 · F10, F24 · replace figure / add text**

**Location:** Persistence Design, **L3–11**. Replace the two table-name ERs with `site/assets/uml/W4-media-main.svg` (`ermedia`) and `site/assets/uml/W4-processing-main.svg` (`erprocessing`). Caption them “selected typed columns and database-enforced relationships”; do not call them exhaustive schemas. Paste:

> Migration-head reconstruction gives 11 application tables per database: Media `media_0008`, Processing `processing_0007`. The appendix supplies the complete dictionary; Alembic bookkeeping is excluded. Cross-context UUIDs have no foreign keys. A reservation's unique asset_id is not an Asset FK. SubmissionGuard.job_id is nullable/non-unique; current_attempt_id is deferred/non-unique, with same-Job membership checked in code. These are reconstructed schemas, not a live catalog read.

Keep database-role and classification text. **Evidence:** [Media migration head][media-head], [Processing migration head][processing-head], [base Job/Attempt FKs][processing-ddl], [reservation DDL][reservation-ddl], [membership fence][lifecycle]. Independent schema coverage: [W4 review](review/W4-review.md), 22 tables/172 columns/61 constraints/12 explicit indexes; no new live verification is implied.

**RC-20 · F5, F9, F10, F19 · correct**

**Location:** Transactions and concurrency, **L23–40**. Replace the unconditional loss claim with recoverable intent and replay/repair assumptions. Limit guard-first ordering to the command path; direct Processing retry locks Job directly. Distinguish `lock_pair`'s Job lock from its Attempt read. Explain same message ID/body no-op, same ID/different body conflict, and new-ID same-version semantic replay versus conflicting content. **Draft:**

> Each accepted command commits inbox, domain state and outgoing intent locally. The publisher commits a reservation before SQS I/O, then acknowledges by the same claim token. Uncertain sends may repeat; retained SQL and later successful repair permit replay. No SQL/SQS or cross-database atomic transaction exists. Media commits inbox and projection together; identity or transition conflicts roll both back.

**Figures:** none; refer to the detailed sequences. **Evidence:** [relay][relay], [command transaction][command], [direct retry][direct-retry], [Job lock/current check][lifecycle], [projection][projection], [Media inbox transaction][media-consumer].

**RC-21 · F3, F10, F18 · correct / add text**

**Location:** Object storage, **L42–46**. Replace with a compact key table:

| Object | Exact namespace and authoritative pin |
|---|---|
| Direct upload source | `staging/{owner_id}/{reservation_id}/source`; finalized UploadReservation retains VersionId. Adopted in place, not copied into sources/. |
| Edit-derived source | `sources/{owner_id}/{asset_id}/source`; SourceVersion retains the copied-source pin. |
| Primary output | `jobs/{job_uuid}/attempts/{attempt_uuid}/primary.{mp4,mkv,mp3}`; extension follows operations, default mp4. |
| Optional HLS | Same Attempt prefix: `hls/master.m3u8`, `hls/v{n}/index.m3u8`, `hls/v{n}/seg%05d.ts`; master uploaded last. |

> Output descriptors carry no output VersionId. SQL finish determines which Attempt's descriptors are published. Cleanup enumerates object versions and retains authority to rescan late writes. An edit creates a new source/Asset; it does not modify the accepted original.

**Figures:** none. **Evidence:** [pin selection][source-pin], [edit source key/adoption][edit], [UUID prefix][prefix], [output/HLS publication][pipeline], [HLS filenames][hls], [cleanup rescans][cleanup].

**RC-22 · F10, F18 · correct**

**Location:** retention table, **L61**; account controls **L83–84**; secrets **L153–163**. Split visibility from retention: base queue visibility 420 s; short queue 960 s; Fargate normally requests a 60 s receive override. Retain 7-day source-queue/14-day DLQ retention and five receives. Change immediate-role-revocation wording to current-row authorization with TTL 0. Add the four non-secret String activity hints alongside the five SecureStrings, without duplicating the data inventory. **Figures:** none. **Evidence:** [queue definitions][queues], [short constants][short-constants], [worker receive override][worker-visibility], [authorizer][authorizer], [activity parameters][activity-params].

**RC-23 · F10, F13 · add text**

**Location:** Asset/upload metadata and Processing job data, **L113–136**. Keep classification, security and retention; add one **JSONB value schemas** table after the Processing paragraph, and point the store-choice trade-off to RD-02:

| Value | Shape and validation boundary |
|---|---|
| Source | `{bucket, key, version_id, sha256, size_bytes, content_type}`; native contract requires all six, pinned VersionId, digest and strict positive bounded size. Distinguish from legacy response Source DTO. |
| Operations | `[{operation, params}]`; clip/crop/scale/convert validation in request/Processing code. Probe-dependent bounds are checked during execution. |
| Outputs | `[{kind, object_key, media_type, size_bytes, sha256}]`; kinds primary/hls_manifest. DTO permits nullable size/hash; successful finish requires positive size, digest, unique kinds, one primary and current Attempt namespace. |
| Projection | Job/Attempt IDs, attempt_number, state_version, status, Source, outputs/error and semantic result hash. Local Media read model, not a shared Job row. |

State that these are application contracts, not SQL JSONB CHECKs. **Figures:** none; link W4's descriptor/operation tables as supplementary detail. **Evidence:** [native Source/Envelope][contract], [operation validation][operation-validation], [Output DTO][output-dto], [finish validation][finish], [projection fields][projection-model].

**RC-24 · F5, F6, F10, F18 · add text**

**Location:** Messages in transit, **L140–151**. Add the ten required Envelope keys, marking nullable values explicitly: `schema_version`, `message_id`, `kind`, `owner_id`, `asset_id`, `job_id?`, `attempt_id?`, `state_version`, `source?`, `payload`. Required key presence differs from non-nullness. Use W4's producer-derived payload shapes: submit/work `{operations}`, retry/cancel `{}`, normal result `{status, outputs, error, attempt_number}`. Keep routing in RC-14 instead of repeating it.

> Cancel-before-submit can return a result with null Job/Attempt/Source, version 0 and exactly `{status:"cancelled", cancellation_confirmed:true, command_message_id:<UUID>}`. It confirms a durable guard, not an invented Job. Media matches its retained cancel command before releasing source cleanup. DLQs retain the same body. Validation rejects forbidden payload content; IAM/queue policy establishes sender authority separately.

**Figures:** none. **Evidence:** [Envelope validation][envelope], [cancel producer][cancel], [cancel confirmation][cancel-confirm], [work/result producer][emit], [Media command producer][media-command], [queue policy][queue-policy].

**RC-25 · F1, F7–F9, F16 · add text / add figure / correct**

**Location:** Detailed Design opening **L188–207**, Case 1 upload/process/play. Replace the introduction:

> Two critical business scenarios receive class/module and function/object interaction views: upload/process/play and stored-source retry after authority expires. Python modules are marked «module» and typed records retain their actual names. Operations belong to the functions that implement them; no controller, repository interface or Strategy class is invented. Release remains an additional operational example.

Use `site/assets/uml/W3-03-a-intake-classes.svg` (`intake-classes`) and `site/assets/uml/W3-06-a1-upload.svg` (`intake-sequence`) in the body. Keep the step table, shortened where diagrams now supply detail. Correct its launch row by splitting dispatch/admission from capacity as RC-17 states, and its output namespace to Attempt UUID. Add:

> Finalize verifies one S3 version outside row locks, then locks/rechecks the reservation and commits its pin, new Asset and submit intent. Direct uploads do not create a separate SourceVersion row. MediaRepair later publishes. Processing's batch handler commits command consumption before best-effort publication; handle_command itself is not the publisher. Claim and finish commit separately. Command ACK follows committed acceptance, work ACK follows durable outcome or SQL-proved staleness, and result ACK follows Media inbox/projection commit. Short Lambda returns batch failures to its mapping rather than deleting Fargate receipts itself.

Print `site/assets/uml/W3-07a-submit-transaction.svg` (`submit-transaction`) once in the appendix, linked here. The existing table retains encode, result and playback functions; link W3-04/05, 08/08a, 09a/b/c, 19, 22, 23/23a for expansion rather than importing all phases. **Evidence:** [finalize][finalize], [command acceptance][command], [batch handler][processing-handler], [claim callback][claim], [finish][finish], [worker ACK][work-ack], [short ACK][short-ack], [Media result][media-consumer].

**RC-26 · F1, F3, F7, F9 · add text / add figure**

**Location:** Detailed Design, after Case 1 table **L207**, before Case 2 **L209**. Add **Edit-derived intake**, a variation of Case 1 rather than a third critical case:

> Media first resolves replay and checks an owned, nondeleted completed parent with a primary output. It durably stages a source key, then copies the parent's verified primary under parent/staged-row locks. A separate adoption transaction creates the derived Asset, verifies/pins the copied source, writes SourceVersion and optional RequestKey, stages submit and removes the staged record. Pin verification is inside edit adoption; the upload-finalize rule about verification outside row locks does not apply here. An independent MediaRepair relay may send only after commit. It can run before HTTP 202 reaches the caller: the guarantee is commit-before-send. Failed or losing copies retain/discard cleanup authority and replay the winner as appropriate.

**Figure:** `site/assets/uml/W3-14-edit.svg` (`edit-sequence`). Link W3-14a/b/c for relay/copy/adoption expansion; do not print them all. **Evidence:** [edit route][edit-route], [copy/adoption/replay][edit], [copy verification][copy], [source pin][pin-copy], [independent relay][media-handler], [relay fence][relay].

**RC-27 · F8–F10, F16 · correct / add figure / replace figure**

**Location:** Case 2, **L209–228**. Use `site/assets/uml/W3-10-b-classes.svg` (`retry-classes`) and `site/assets/uml/W3-13-b3-fence.svg` (`stale-finish`) in the body; `site/assets/uml/W3-12a-processing-retry.svg` (`retry-transaction`) once in the appendix. Replace `fig:jobstates` with `site/assets/uml/W3-16-attempt-states.svg`, retaining label `jobstates` but captioning it **Attempt lifecycle**. Explain Job status/deletion in text and link W3-15, rather than printing two similar statecharts. Paste:

> Expiry is rechecked under the Job lock using database time. The Attempt becomes abandoned, the Job failed, and cleanup/result intent is staged. Owner retry over the same source creates a new Attempt. The caller acquires locks before `_retry_locked`; idempotent replay returns the current Attempt, not necessarily the first one in its ledger. Direct Processing retry has its own transaction and omits the Media command leg. A stale Claim cannot finish after its Attempt is superseded or authority expires. Claim freezes field bindings, not nested dict/list contents. Independently, Media ignores older snapshots and identical equal-version semantics, and rejects conflicting equal-version content. An inbox conflict rolls back acceptance and projection together.

> Job status is queued/processing/done/failed; deleted_at supplies cancelled snapshots. Lost unclaimed queue work can be repaired on the same queued Attempt. Execution failure/expiry needs owner retry; only live short-lane refusal automatically creates a standard-lane successor.

**Evidence:** [expiry][recovery], [retry/guard logic][retry], [direct retry][direct-retry], [lock/live/Claim][lifecycle], [projection][projection], [queued-work repair][work-repair], [short redirect][redirect], [Job status constraint][processing-ddl].

**RC-28 · F8, F9, F19, F22 · move / correct**

**Location:** Case 3 independent release, **L230–250**. Move the six-step operational example into Continuous Delivery's existing steps; replace here with a short pointer to `release-activity` and DP-1's textual alternatives. Keep its tests and bad-candidate historical receipt in UC-7 traceability. Correct guarantee-of-restore wording through RC-36. **Figures:** none here. **Evidence:** [CD implementation][cd-script], [owner-release proof][release-proof], [recorded bad candidate][bad-candidate].

### 36-other-limitations.md

**RC-29 · F2, F11, F18, F19, F22 · correct / add text**

**Location:** Other Architectural Decisions, **L11–12, L17**, project decision F-01 **L23**, rationale pointers **L29–34**. Replace “no private network exists” with “peer business HTTP is unused; Gateway-trusted Actor and IAM establish the invocation boundary.” Correct “only … run as containers” to distinguish Lambda container images from Fargate tasks. Qualify AD-28: retained-fixable exception is Trivy-only; ECR validation still applies. Add pointer rows for RD-01/RD-02, naming their 26 Oct report-response status and home in Physical Architecture. Keep old F-01 as earlier feedback. **Figures:** none. **Evidence:** [VPC/image configuration][images], [Trivy retained mode][baseline-policy], [ECR policy][ecr]; current alternative analysis is drafted in RC-17/18.

**RC-30 · F13, F17, F18, F20, F22, F23 · correct / add text**

**Location:** Architectural Limitation, **L51–57**. Update AISS-04's configured alarm count to 15 and date the no-protection setting. Keep AISS-01/05 measurements, missing evidence and existing owners/horizons. Add a compact **CODE follow-ups — not implemented** table linked to AISS-04 and the feedback response:

| Tracking ID | Current disposition / evidence needed before closure |
|---|---|
| CODE-DAST-CLOUD (F17) | Optional proposed staging scan; cloud edge NOT_RUN. Define authorized candidate-bound target, fixtures, scope and cleanup; retain exact-source hosted receipt. |
| CODE-DAST-POLICY (F17/F22) | ZAP findings remain report-only. Agree severity/exception owner/expiry and add policy checks plus hosted evidence before claiming a finding gate. |
| CODE-BRANCH-PROTECTION (F22) | Proposed settings change. Agree required stable checks/bypass; verify a missing/failing check prevents merge. No rule is configured by this plan. |
| CODE-SCHEMA-PARITY (F10) | Conditional follow-up if model-created schema parity is required: two migration-only recovery indexes and SERIAL/default mismatch. No live index absence established. |
| CODE-MODEL (F5/F6) | Optional richer policy/aggregate encapsulation and pin-immutability enforcement. Current multi-root transactions/record models are documented limitations. |
| CODE-COOKIE (F2) | Optional stricter repeated-cookie contract. Parser collapses repeated names within one entry; Gateway normalization not tested. |

Do not invent owners, approved deadlines or a migration/ALB project. Use “team triage pending” for new ownership; existing AISS owners remain. NoSQL read-store experiments, capacity tuning and CloudFront-only restriction stay conditional future decisions. **Figures:** none. **Evidence:** [current cloud-scan limit][dast-cloud], [finding publication policy][dast-workflow], [schema migration][processing-head], [ORM default][launcher-model], [cookie parser][authorizer], [dated W5 settings review](review/W5-review.md).

### 40-quality.md

**RC-31 · F12, F16, F18, F19, F22 · correct**

**Location:** summary Security row **L26**, Performance tactics **L40–48**, short-lane explanation **L65**, Availability **L76–95**, contract evolution **L165–169, L199–202**. Keep original targets/workloads/results. Say HTTP invocation distribution and queue competing consumers, with Fargate cap 3 plus separate short max 2; refer to RD-01. Qualify durable-state recovery and owner-smoke restore as RC-20/36. Change observability to:

> The enabled source configuration defines 15 alarms and a services dashboard. The earlier backlog receipt recorded 13/13 alarms OK under its then-current configuration; no fresh 15-alarm inventory or notification drill was run.

Separate historical AWS negative tests, release image policy, local DAST execution and cloud DAST NOT_RUN in the summary instead of one current “Security PASS.” Describe v1-only contract support and shared libraries as RC-09. **Figures:** retain `fig:results`; do not change measured values. **Evidence:** [mapping/cap settings][mappings], [alarms][alarms], [relay][relay], [version contract][contract], [historical quality source][quality-report], [25 Oct CI][ci25].

**RC-32 · F2, F14, F15, F17, F18, F22 · correct / add text**

**Location:** Security controls **L113, L117, L121–123**, Verification **L133, L139**, Scope limits **L143–150**. Correct cookie handling and current/default IAM count scope; 17 is default, enabled application configuration has 19 IAM roles, distinct from database identities. Preserve historical three-queue denial scope. Replace scanner prose:

> Source analysis uses Ruff S and independent GitHub-managed CodeQL. npm audit is dependency analysis, gitleaks scans secrets, and Trivy scans separate image sets. ZAP actively scans seven selected GET operations against the disposable HTTPS loopback V1 bridge, real PostgreSQL and Moto S3/SQS. It does not scan deployed API Gateway/CloudFront/IAM. Scanner execution, authenticated coverage and cleanup failures block the job; finding severity is report-only. Auth lifecycle POST, upload, HLS, admin and other mutation operations are excluded. Fixture ownership-negative tests are separate from active-scan coverage. The DevOps inventory records each trigger, gate and result location.

List the seven selected GETs once here: Media `auth/me`, `health`, `jobs`, `jobs/{job_id}`; Processing `health`, `jobs`, `jobs/{job_id}`, each under its `/api/<service>/` prefix. Retain request cap 1,600, two fixture users/uploads, zero worker invocations, and cleanup. Date CodeQL dismissals/FFmpeg acceptance as historical records, not remediation or current alert counts. State Sonar analysis skipped in the audited runs; SARIF upload is best-effort publication, with JSON/log/receipt exceptions. **Figures:** none; inventory in RC-34 is authoritative. **Evidence:** [adapter][adapter], [IAM resource generation][roles], [Ruff S][ruff], [DAST target/scope][dast-target], [DAST result policy][dast-result], [DAST workflow][dast-workflow], [accepted-unfixed record][ffmpeg], [CodeQL run][codeql].

### 50-devops.md

**RC-33 · F4, F14, F22 · correct**

**Location:** Source Control Strategy, shared-code labels **L6, L16**, PR policy **L49–51**, access/scanner bullets **L62–71**. Use shared contract/technical libraries rather than an established DDD Shared Kernel. Describe dev selection only for PRs into `dev/closeout`, subject to escalation; other PR bases select full. Retain dated no-protection/team-practice distinction. Replace universal SARIF paragraph with a short pointer to the inventory. CodeQL is independent default setup, Ruff S is Bandit-derived rules rather than standalone Bandit, and Sonar configuration success is not analysis execution. **Figures:** none. **Evidence:** [selection][selection], [aggregate][aggregate], [Ruff invocation][ruff], [W5 dated settings](review/W5-review.md), [CodeQL execution][codeql].

**RC-34 · F14, F15, F17, F22 · add text / replace figure**

**Location:** Continuous Integration, trigger table **L94–98**, jobs table **L104–124**. Keep non-security test jobs; move scanner details into one **Security verification inventory**, replacing duplicate abbreviated rows. Move the old `fig:cicd` from Continuous Delivery **L136** here and replace its image with `site/assets/uml/W5-pipeline-main.svg`, keeping label `cicd`. CodeQL sits outside the custom aggregate flow; pipeline stages are not merge protection.

| Engine/scope | Category and trigger | Failure policy | Result location |
|---|---|---|---|
| Ruff S | SAST; lint lane/all full CI | Findings fail lint | Best-effort ruff-security SARIF/summary |
| CodeQL default setup | Independent SAST; GitHub-managed | No alert-severity requirement in custom Full verification | Native code-scanning analysis; dated run |
| npm audit | SCA; frontend lane/all full CI | audit-level=high fails frontend job | Workflow logs |
| gitleaks | Secrets; every CI event, full history | Findings fail; both aggregates require job | Redacted SARIF/summary |
| Trivy inherited app/media/processing | Image scan; selected scope/full CI | Fixable HIGH/CRITICAL | Filtered JSON/identity, 60 days; filtered SARIF |
| Trivy V1 Media/Processing/Worker | Image scan; selected/full CI or manual V1 images=true | Exact image/source/report completeness plus fixable HIGH/CRITICAL | Full configured HIGH/CRITICAL JSON incl. unfixed, 60 days; filtered fixable SARIF |
| Trivy manual preparation | Selected-owner image; aws-prep dispatch | Exact-image fixable HIGH/CRITICAL | Preparation JSON/provenance/artifacts, 14 days; no SARIF here |
| Trivy + ECR release proof | CD candidate/kept/restore image sets | RC-36's distinct Trivy/ECR policy | CD receipts/artifacts, 60 days; no CD SARIF stage |
| OWASP ZAP | DAST; selected/full CI, standalone weekly or exact-source dispatch | Execution/coverage/cleanup block; findings report-only | Sanitized JSON, 14 days; best-effort zap-dast SARIF |
| SonarCloud | Conditional advisory source/coverage analysis | Not required by Full verification; analysis skipped in audited runs | Configuration/disposition artifacts; no evidenced analysis result |

Add a Dated evidence column from RC-35: actual run references for CI/CodeQL rows, “source configuration only; no run checked” for manual preparation/CD inventory rows. Never substitute those CI IDs for a CD scan receipt. SARIF filtering means unfixed Trivy rows can remain only in JSON. No standalone Semgrep, Bandit or pip-audit invocation is evidenced by these workflows. **Figures:** W5-pipeline-main only; link W5-pipeline-full from appendix, not another embedded CI overview. **Evidence:** [CI workflow][ci-workflow], [V1 scans][v1-scans], [manual preparation][prep], [ZAP workflow][dast-workflow], [Sonar][sonar], [release proof][release-proof], [aggregate semantics][aggregate].

**RC-35 · F14, F15, F22, F23 · add text / correct**

**Location:** Continuous Integration, representative-run paragraph **L126–130**. Keep the 21 Oct duration as a historical example; add **Dated exact-source evidence, reviewed 26 October**:

| Run | Exact source/event | Outcome and limit |
|---|---|---|
| [39931072197][ci23], 23 Oct | 76282d3; Main push | Full CI successful. |
| [40174362164][ci25], 25 Oct | 76282d3; schedule | Full CI failed in inherited app/processing Trivy; V1 image verification and local ZAP succeeded. Failure cause at vulnerability level not diagnosed. |
| [40189407647][codeql], 25 Oct | 76282d3; independent CodeQL | Python, JavaScript/TypeScript and Actions analyses succeeded; no zero-alert conclusion. |

Both ZAP runs recorded seven routes, 16 findings, 146 out-of-scope requests blocked and cleanup PASS, with successful SARIF publication. Cite W5's retained run/log review for those counters; this consolidation re-read run/job conclusions through authenticated gh, without rerunning scans. Sonar analysis jobs were skipped. **Figures:** none. **Evidence:** run links above and [W5 run/step review](review/W5-review.md), [workflow scope][dast-cloud].

**RC-36 · F14, F17, F22, F23 · add figure / correct / move**

**Location:** Continuous Delivery, **L136–182**, retained-image policy **L211–220**, historical delivery claims **L184–245**. Place `site/assets/uml/W5-pipeline-release.svg` (`release-activity`) in the appendix and reference it here. Fold in RC-28's operational steps. Paste:

> Automatic admission binds the successful triggering Main push CI run/attempt to the exact source. Manual deploy/release can instead use a successful exact-source full CI dispatch; scheduled/PR CI does not qualify. CD verifies the image bytes actually promoted using config/source identity and registry digest evidence; source CI alone does not prove those bytes are reused. Owner smoke failure attempts restore and records restored/abandoned/restore-failed outcomes. The later upload-to-playback smoke fails CD on error but does not independently promise alias restore. Schema rollback is not performed.
>
> Candidates and kept-running companions remain strict. A replaced restore-target image may record fixable Trivy findings as RETAINED_FIXABLE. This exception does not waive ECR: every image set still needs a completed scan for the matching digest and no unaccepted HIGH/CRITICAL findings. Identity/completeness errors block throughout.

Retain dated delivery/incident receipts; remove “only time” unless its audit horizon is supplied. State production-demo/no-staging and team merge approval separately from configured reviewer enforcement. **Evidence:** [admission validator][admission], [release execution/restore][cd-script], [later smoke][later-smoke], [Trivy baseline policy][baseline-policy], [image-set proof][release-proof], [ECR policy][ecr], [bad-candidate historical run][bad-candidate].

### 60-other.md

**RC-37 · F2, F5, F6, F11, F19, F22 · correct**

**Location:** What Team 17 Contributed, **L8–18**; Lessons Learned, **L24–27**. Replace the universal aggregate/image wording with “two context-owned models and principal business-root interpretations, with documented supporting lifecycles and local transaction exceptions.” Qualify restore as RC-36. Remove the false historical rationale “Lambdas with no private network”; say that asynchronous business handoff removes direct request-time Processing availability from Media acceptance. **Figures:** none. **Evidence:** [models][media-model], [Processing models][job-model], [VPC/image settings][images], [Media adoption][finalize], [relay][relay].

**RC-38 · F1–F24 · add text**

**Location:** after Lessons Learned **L51**, before Responsibilities **L53**. Add `## Presentation Feedback and Response`, dated **26 October 2026**, as required by the report README. Paste the following introduction and table. This is a response plan today; change a documentation status to **Addressed in v1.1** only after the named edit/figure is in the rebuilt document and checked. Do not imply that this plan already changed the report or that assessors accepted the response.

> The assessors requested more design detail and clearer links between views. The following crosswalk records the 26 October remarks, the report response and outstanding work. F1–F24 are audit identifiers; the earlier proposal feedback F-01 is separate. Documentation completion does not close code or execution-evidence items.

| Remark / feedback | Response | Change made / destination in v1.1 | Status on 26 Oct |
|---|---|---|---|
| “Report → Slide 20”; “More detailed” (F1) | Trace client acceptance into detailed design | Public request boundary `authorizer`; Case 1 `intake-classes`, `intake-sequence`, `submit-transaction` (RC-07/25) | Drafted; report integration pending |
| Authorizer tied to Gateway (F2) | Separate authorizer decision from API invocation; show Actor and User dependency | Logical Architecture `authorizer`; Security (RC-07/32) | Drafted; integration pending; optional CODE-COOKIE open |
| Editing does not go directly to SQS (F3) | Show copy, source pin, Asset/outbox adoption and independent relay | Detailed Design `edit-sequence` (RC-26) | Drafted; integration pending |
| How bounded contexts are grouped (F4) | Capability/rule/consistency derivation and scoped context relationships | Platform Design `contextmap` (RC-12) | Drafted; integration pending; formal governance UNKNOWN |
| How aggregates are grouped (F5) | Root/member/value distinctions and independent lifecycles | Platform Design `asset-domain`, `job-domain` (RC-13) | Drafted; integration pending; optional CODE-MODEL open |
| Detailed DDD diagrams with entities; revisit PE (F6) | Typed entities/values, multiplicities, enforcing functions and transaction exceptions | Platform Design domain figures; complete schema appendix (RC-13/42) | Drafted; integration pending |
| Detailed design at component level (F7) | Real exported interfaces and dependencies inside each owner | Tiers and Layers `media-components`, `processing-components` (RC-10) | Drafted; integration pending |
| Class and sequence diagrams at class/object level for 1–2 critical cases; revisit SAD/SDP (F8/F9) | Intake and expiry/retry collaborations; functions remain on modules | Detailed Design `intake-classes`, `intake-sequence`, `retry-classes`, `stale-finish`; appendix `retry-transaction` (RC-25/27) | Drafted; integration pending |
| Database schemas/models (F10; deck legibility F24) | Separate typed owned schemas plus full column/constraint dictionary | Persistence `ermedia`, `erprocessing`; schema appendix (RC-19/42) | Drafted; report has no click-layer defect; CODE-SCHEMA-PARITY conditional/open |
| More architectural perspectives, e.g. deployment; revisit ARCHSS (F11) | Map concerns, components, artifacts, triggers and runtime placement | Architecture views; Physical `topology` and mapping table (RC-05/15) | Drafted; integration pending |
| Physical architecture does not explain load balancing (F12) | Separate HTTP distribution, queue consumption, launcher capacity and SQL limits; explain no ALB | RD-01 / Load distribution (RC-17) | Analysis drafted; no ALB implementation selected |
| Consider NoSQL/MongoDB (F13) | Compare access/consistency requirements and retain SQL authority with JSONB | Technology and Services RD-02 (RC-18) | ADR proposed for report adoption; migration not selected |
| SAST not visible in pipeline (F14) | Name Ruff S/independent CodeQL; distinguish dependency, secret and image scans | CI `cicd`, security inventory and dated runs (RC-34/35) | Existing controls evidenced; report integration pending; Sonar NOT_RUN |
| DAST not visible in pipeline; clarify gates (F15/F17/F22) | Show local authenticated ZAP and its report-only findings | Security scope; CI inventory; `cicd` (RC-32/34) | Local execution evidenced; CODE-DAST-CLOUD and CODE-DAST-POLICY open; cloud NOT_RUN; branch protection proposal open |
| Where Lambda/Fargate choice happens; diagrams sometimes wrong (F16/F18/F19) | Locate dispatch/admission and correct image, queue, alarm and provenance claims | Nodes and Subsystems; Physical `topology`, `lane-dispatch`; object keys (RC-11/15/17/21) | Source-verified draft; report integration/live inventory pending |
| Incorporate actual presentation remarks (F20) | Keep this dated crosswalk and update after rebuilt-document checks | Presentation Feedback and Response (RC-38) | Plan written; final response verification pending |
| Required use-case/quality demonstrations (F21, course follow-up) | Retain accessible source-labelled recording or live/fallback evidence | Evidence and How to Reproduce It / Project Status (RC-03/39) | Delivery/playback during talk UNKNOWN; evidence open |
| Current status, milestones and rough member effort (F23, course follow-up) | Refresh exact-source CI/date; keep allocations distinct from actual effort | Project Conduct (RC-03/04) | CI refreshed; team effort/final milestone confirmation open |

**Figures:** none in this section; use label cross-references to the single embedded instance. **Evidence:** [briefing p.6][briefing], [README after-presentation steps][readme], [actual remarks](FEEDBACK.md), [R4 course crosswalk](research/R4-feedback-audit.md#course-requirement-crosswalk). These are not new mandatory ALB/MongoDB/vendor requirements.

**RC-39 · F19–F21, F23 · add text / correct**

**Location:** Evidence and How to Reproduce It, table **L67–79**. Add one row for this feedback response/reviewed figure sources and one for a dated demonstration evidence index. For D1–D6, require accessible artifact, recording date, source/release, demonstrated use case/quality attribute and any trimmed wait. Until supplied, write “recording/live-demo delivery evidence not verified”; do not assert the talk failed. Keep cloud URLs as historical environment references with last-verified date/UNKNOWN current health. Preserve submission/peer-assessment receipts as separate human follow-ups. **Figures:** none. **Evidence:** [baseline pending recording references][demo-plan], [historical evidence index][evidence-index], [FEEDBACK](FEEDBACK.md), [presentation guide §6][guide].

### 70-appendices.md

**RC-40 · F1, F2, F5–F11, F16, F19, F22 · correct**

**Location:** Use-Case Specifications and Traceability, **L13–14, L25–31, L48–50, L69–85**, traceability **L88–100**; analysis/design transition **L108–115**. Align ID meanings, both execution lanes, retry replay/current Attempt, guard scope, owner smoke and synchronous authorization qualifications with the body. In UC-1 remove SourceVersion as a normal direct-finalize creation. Replace references to retired `seqintake/seqencode/seqplay/designclass` with the selected class/sequence labels. UC-5 and UC-6/7 retain their own operational tests; W3's two scenarios do not replace all their evidence. **Figures:** cross-references only. **Evidence:** [upload route response][uploads], [finalize][finalize], [retry][retry], [launcher][launcher], [admission][admission], [owner smoke/restore][cd-script].

**RC-41 · F7–F9, F11, F19 · move / replace figure**

**Location:** Analysis and Design Models **L117–138**, Design Problems **L170, L192, L215**. Remove empty `fig:designclass` and retire its references. Preserve the analysis→implementation transition table; replace the four conceptual panorama embeddings (`analysisclass`, `analysisseq1/2/3`) with explicit links to their baseline source, labelled **conceptual analysis, not implemented design**. Replace the “too wide to print” paragraph with links to the selected readable implemented figures. Remove the three DP before/after embeddings; retain each DP's problem, alternatives, decision and evidence in text, pointing to the single body figure instead. This changes print placement, not the historical analysis source files.

Embed only `site/assets/uml/W3-07a-submit-transaction.svg`, `site/assets/uml/W3-12a-processing-retry.svg` and `site/assets/uml/W5-pipeline-release.svg` here, with labels listed above. Use landscape only where needed. Add a small source index linking the unprinted reviewed W1 network/artifact/queue/event/store, W2 supporting-domain, W3 execution/projection/expiry, W4 complete ER and W5 full-CI figures. Do not print their full libraries. **Evidence:** [baseline analysis/design models][appendix-models], [actual submit transaction][command], [retry][retry], [release proof][release-proof].

**RC-42 · F10, F13, F18, F19 · add text**

**Location:** after Analysis and Design Models, insertion before Design Problems **L140**; new **Schema reference**. Import the independently corrected W4 dictionary from [W4.md, Appendix draft](report-notes/W4.md#appendix-draft--full-physical-data-dictionary), preserving all **22 tables, 172 columns, 61 constraints and 12 explicit indexes**. Compress formatting to one table block per database with columns `table.column`, `type/nullability/default`, `key/constraint/index`; keep complete composite members, CHECK predicates, FK actions/deferred status and partial-index predicates. Do not reduce this to a table-name inventory. Put the 16 full-schema ER vectors in the linked supporting index rather than adding 16 PDF pages.

Call out three reconstructed-schema/ORM differences: migration-only `ix_attempts_recovery`, migration-only partial `ix_cleanup_intents_due`, and `launcher_control.id` SERIAL/sequence default versus ORM Python default 1. Migrations are authoritative; these are not proof of deployed drift. Preserve legacy columns/tables and the no-FK/current-membership distinctions. **Figures:** none additional. **Evidence:** [migration heads][media-head], [Processing head/SERIAL][processing-head], [recovery index][attempt-index], [cleanup partial index][cleanup-index], [ORM launcher default][launcher-model], [W4 independent DDL/schema checks](review/W4-review.md). Target four appendix pages; actual legible pagination must be checked before finalising the budget.

## Figure budget and export procedure

**Ceiling: 24 numbered figures, compared with v1.0's 22. Target: no increase beyond the existing 66 pages.** This is an integration constraint, not a verified v1.1 page count. New detail replaces weak/duplicate figures and repeated prose. Do not meet the target by shrinking labels below readable print size or dropping schema fields. Confirm pagination after Word export; recover space from duplicate narrative/tables before revisiting this selection.

| v1.0 figure(s) | v1.1 disposition / budget |
|---|---|
| usecases, schedule, results | Retain: **3** |
| logical, contextmap, topology, ermedia, erprocessing, jobstates, cicd | Replace with W6-logical, W2-context-map, W1-deployment-main, W4-media-main, W4-processing-main, W3-16-attempt-states, W5-pipeline-main: **7** |
| seqintake, seqencode, seqplay | Remove old overview embeddings; requested detailed interactions take their place |
| designclass | Remove empty common model; focused domain/use-case models replace it |
| analysisclass, analysisseq1/2/3 | Move to linked conceptual-analysis evidence; retain transition/traceability tables |
| dp1, dp2, dp3 | Remove duplicate before/after pictures; keep alternatives/decisions as text and refer to revised body figures |
| burnup | Move dated graphic to supporting evidence; retain dated metrics text |
| New body figures | W1-authorizer, W3-01/02 components, W2-media-asset/processing-job, W1-dispatch, W3-03 intake classes, W3-06 intake sequence, W3-14 edit, W3-10 retry classes, W3-13 stale finish: **11** |
| New appendix figures | W3-07a submit transaction, W3-12a Processing retry, W5-pipeline-release: **3** |
| Total | **21 body + 3 appendix = 24**; the cover logo is unchanged |

Keep the seven replacement labels where compatible; explicitly update removed labels everywhere. Prefer section/figure labels to hard-coded numbers. Body additions are justified by the assessor's request; no decorative views-map figure is needed. The full schema dictionary is appendix text, while body ERs retain explicit selected-column captions. W2/W3 class diagrams serve different questions; do not duplicate their supporting sheets in print.

All selected new figure files are `project-documentation/presentation/site/assets/uml/<stem>.svg`, with same-stem editable `.puml`. Their **PNG** exports go to `project-documentation/final-report/figures/<stem>.png`. `tools/build_report.py` is the report assembly/numbering step, not a PlantUML exporter. The current `render_figures.py` does not discover `presentation/site/assets/uml/`; do not assume a general rebuild imports those files.

At the later implementation step, from the worktree root, use this example for each of the **21 selected new stems** (the 24 total less the three retained originals):

```sh
# Recompile only if the reviewed PUML changed.
java -Djava.awt.headless=true -jar "$HOME/dc2-tools/plantuml-1.2026.9.jar" \
  -tsvg project-documentation/presentation/site/assets/uml/W1-authorizer.puml

# Export the reviewed vector at print resolution; repeat for each selected stem.
npx -y @resvg/resvg-js-cli@2.6.2-beta.1 --background white --fit-width 3200 \
  project-documentation/presentation/site/assets/uml/W1-authorizer.svg \
  project-documentation/final-report/figures/W1-authorizer.png

# Alternative existing report workflow: copy selected SVGs into figures/src/,
# then call render_figures.py with those exact stems (no application/tool edits).
# python3 project-documentation/final-report/tools/render_figures.py W1-authorizer
```

Use `![Figure {#fig:authorizer}. Gateway request/authorizer interaction, source configuration at Main 76282d3.](figures/W1-authorizer.png)` and `Figure {@fig:authorizer}`. For wide appendix figures, reuse the raw `LANDSCAPE-START` / `LANDSCAPE-END` blocks; do not create one multi-panel panorama. Inspect the actual Word/PDF size: prior 1280×720 slide QA does not verify report print legibility. Do not rerun authoring generators over the reviewed W1–W6 handoffs.

Build evidence: [figure discovery/export implementation][figure-renderer], [numbering/resource path][report-builder], [report README][readme]. Existing and new figure sources retain their own provenance; do not silently relabel a proposal picture as current.

## Ordered work checklist

1. [ ] Confirm this written plan with the coordinator before editing report sources. Preserve existing unrelated deck/workstream edits; no commit is requested.
2. [ ] Record source SHA and 66-page/22-figure v1.0 baseline. Keep the historical PDF/DOCX accessible before replacing generated submission artifacts.
3. [ ] Apply factual corrections in RC-02/03/06/07/09/11/14–17/20–24/27/29/31–36 first. Keep historical receipts and current configuration distinct.
4. [ ] Integrate Architecture views, context derivation, domain models, component views, deployment mapping and RD-01/RD-02. Preserve every required template heading.
5. [ ] Integrate the two selected detailed cases and edit variation; move release into CD. Replace old figure references in traceability, DP prose and all other files.
6. [ ] Export only the selected 21 new SVGs to PNG; preserve their reviewed PUML/SVG sources. Apply the 24-figure ceiling and remove the 12 retired v1.0 embeddings.
7. [ ] Add the complete corrected schema appendix and supporting source index. Check migration-head defaults, deferred/composite constraints and all 172 columns survived reformatting.
8. [ ] Insert the 26 Oct feedback crosswalk with honest pending/CODE/UNKNOWN statuses. Update each documentation row only after its revised content is present and reviewed.
9. [ ] Obtain team-confirmed rough effort, actual post-presentation milestones, accessible demo evidence and any required submission-format/receipt information. Leave explicit UNKNOWN where confirmation is unavailable; do not infer from Git history.
10. [ ] Update version/date and Project Conduct. Keep old CI metrics dated; include mixed 23/25 Oct exact-source outcomes. Re-read settings/live state only if making a new current claim, using authenticated gh for all GitHub access; no cloud operations are implied by this plan.
11. [ ] Run `python3 project-documentation/final-report/tools/build_report.py --no-word` for assembly/label checks, then the normal `python3 project-documentation/final-report/tools/build_report.py` for Word TOC and PDF export. Run the burn-up generator only if its underlying data is deliberately refreshed; the burn-up is no longer embedded by this plan.
12. [ ] Inspect DOCX and every PDF page: readable fields/arrows, no clipped tables, correct landscape transitions, captions/links/TOC and all references resolved. Confirm ≤66 pages and exactly the selected figure set. If too long, remove repeated prose/unused whitespace and consolidate tables; do not add every backup diagram or silently omit dictionary content.
13. [ ] Review every F1–F24 disposition, all CODE items and evidence qualifiers against the final document. Only then mark documentation rows Addressed in v1.1; keep unimplemented/NOT_RUN items open. Final upload by 16 Nov and its receipt are separate coordinator/human steps, not completed here.

## Still unverified

- v1.1 integration, DOCX/PDF rendering, final page count, print legibility and assessor acceptance. This pass writes only this plan and performs no report build.
- Current AWS inventory, actual AZ names, gate/mapping/schedule state, deployed source/image/alias identity, runtime health, quotas and alarm states. Counts/bounds here describe enabled source configuration.
- Actual recordings or live/fallback playback during the presentation; accessible D1–D6 footage and demonstration provenance remain unverified. No report text can establish delivery by itself.
- Rough actual personal effort and revised forecast, final submission format/receipt, peer-assessment and other Canvas administration. Equal allocation is not time measurement.
- Cloud-edge DAST, additional mutation/HLS/admin active-scan coverage, severity-based ZAP finding gate, branch enforcement and all other CODE proposals. Local scan execution is already evidenced; those extensions are not.
- Current security-alert totals and the individual vulnerability/root cause behind the 25 Oct inherited Trivy failures. Successful CodeQL/ZAP jobs do not establish clean security results; historic dismissals are not fixes.
- Live applied schema and alternate-database economics/performance; W4 is migration-head reconstruction. Formal DDD relationship governance and historical ALB/NoSQL deliberations are UNKNOWN.
- Existing open evidence in AISS-05: AWS lost-work timing, duplicate-output inspection after worker kill, restore drill, Publisher effort measurement and actual final spend. Preserve those limits rather than close them editorially.

## Short summary

The plan makes the report's as-built mechanisms inspectable: corrected source facts, distinct architecture views, detailed domain/component/use-case models, owned schemas, explicit ALB/NoSQL decisions and a truthful security inventory. It resolves workstream overlap, caps the report at 24 selected figures with a 66-page target, and leaves code, live verification and human acceptance visibly open. All report sources remain unchanged.

<!-- Pinned implementation and report evidence. New local handoffs are linked locally above. -->
[readme]: https://github.com/Collaboration95/dc2/blob/76282d3/project-documentation/final-report/README.md#L34
[briefing]: https://github.com/Collaboration95/dc2/blob/76282d3/project-documentation/original-reference/01%20Briefing.pdf
[template]: https://github.com/Collaboration95/dc2/blob/76282d3/project-documentation/original-reference/02%20Project%20Report%20Template%20for%20Practice%20Project.docx
[guide]: https://github.com/Collaboration95/dc2/blob/76282d3/project-documentation/original-reference/04%20Project%20Presentation%20Guidelines%20%26%20Schedule.pdf
[lane]: https://github.com/Collaboration95/dc2/blob/76282d3/processing/short_lane.py#L81-L130
[short-constants]: https://github.com/Collaboration95/dc2/blob/76282d3/processing/short_lane.py#L30-L70
[emit]: https://github.com/Collaboration95/dc2/blob/76282d3/processing/messaging.py#L102-L129
[redirect]: https://github.com/Collaboration95/dc2/blob/76282d3/processing/messaging.py#L412-L449
[images]: https://github.com/Collaboration95/dc2/blob/76282d3/scripts/aws/v1/definitions.py#L1198-L1266
[queues]: https://github.com/Collaboration95/dc2/blob/76282d3/scripts/aws/v1/definitions.py#L596-L662
[alarms]: https://github.com/Collaboration95/dc2/blob/76282d3/scripts/aws/v1/definitions.py#L1306-L1364
[prefix]: https://github.com/Collaboration95/dc2/blob/76282d3/processing/lifecycle.py#L20-L21
[adapter]: https://github.com/Collaboration95/dc2/blob/76282d3/contracts/gateway.py#L33-L104
[finalize]: https://github.com/Collaboration95/dc2/blob/76282d3/media/services/direct_intake.py#L149-L204
[cancel]: https://github.com/Collaboration95/dc2/blob/76282d3/processing/messaging.py#L186-L230
[contract]: https://github.com/Collaboration95/dc2/blob/76282d3/contracts/v1.py#L20-L218
[relay]: https://github.com/Collaboration95/dc2/blob/76282d3/delivery/sql.py#L18-L115
[ci23]: https://github.com/Collaboration95/dc2/actions/runs/39931072197
[ci25]: https://github.com/Collaboration95/dc2/actions/runs/40174362164
[codeql]: https://github.com/Collaboration95/dc2/actions/runs/40189407647
[auth-config]: https://github.com/Collaboration95/dc2/blob/76282d3/scripts/aws/v1/definitions.py#L1529-L1554
[launcher]: https://github.com/Collaboration95/dc2/blob/76282d3/processing/launcher.py#L238-L382
[aggregate]: https://github.com/Collaboration95/dc2/blob/76282d3/scripts/ci/policy.py#L406-L439
[release-report]: https://github.com/Collaboration95/dc2/blob/76282d3/project-documentation/final-report/src/50-devops.md#L184-L245
[status-report]: https://github.com/Collaboration95/dc2/blob/76282d3/project-documentation/final-report/src/20-conduct.md#L61-L86
[demo-plan]: https://github.com/Collaboration95/dc2/blob/76282d3/project-documentation/presentation/site/deck.html#L198-L237
[metrics-report]: https://github.com/Collaboration95/dc2/blob/76282d3/project-documentation/final-report/src/20-conduct.md#L110-L162
[arc42]: https://docs.arc42.org/section-7/
[kruchten]: https://arxiv.org/pdf/2006.04975v1
[archss]: https://www.iss.nus.edu.sg/executive-education/course/detail/architecting-software--solutions
[pe]: https://www.iss.nus.edu.sg/executive-education/course/detail/platform--engineering/software-systems
[sad-programme]: https://www.iss.nus.edu.sg/stackable-certificate-programmes/graduate-certificate/smart-systems-platforms/graduate-certificate-in-designing-modern-software-systems
[sdp]: https://www.iss.nus.edu.sg/executive-education/course/detail/software-design-patterns/software-systems
[integrations]: https://github.com/Collaboration95/dc2/blob/76282d3/scripts/aws/v1/definitions.py#L1560-L1621
[authorizer]: https://github.com/Collaboration95/dc2/blob/76282d3/media/authorizer.py#L13-L60
[media-grants]: https://github.com/Collaboration95/dc2/blob/76282d3/scripts/aws/v1/definitions.py#L720-L746
[claim]: https://github.com/Collaboration95/dc2/blob/76282d3/processing/messaging.py#L325-L370
[processing-handler]: https://github.com/Collaboration95/dc2/blob/76282d3/processing/handlers.py#L52-L68
[routes]: https://github.com/Collaboration95/dc2/blob/76282d3/scripts/aws/v1/definitions.py#L1602-L1621
[media-deps]: https://github.com/Collaboration95/dc2/blob/76282d3/media/api/deps.py#L16-L49
[processing-auth]: https://github.com/Collaboration95/dc2/blob/76282d3/processing/auth.py#L6-L17
[media-handler]: https://github.com/Collaboration95/dc2/blob/76282d3/media/handlers.py#L58-L78
[lifecycle]: https://github.com/Collaboration95/dc2/blob/76282d3/processing/lifecycle.py#L24-L221
[media-consumer]: https://github.com/Collaboration95/dc2/blob/76282d3/media/messaging.py#L16-L28
[projection]: https://github.com/Collaboration95/dc2/blob/76282d3/media/projections.py#L36-L118
[media-image]: https://github.com/Collaboration95/dc2/blob/76282d3/deploy/v1/media.Dockerfile#L16-L27
[processing-image]: https://github.com/Collaboration95/dc2/blob/76282d3/deploy/v1/processing.Dockerfile#L16-L27
[asset-repo]: https://github.com/Collaboration95/dc2/blob/76282d3/media/repositories/assets.py#L31-L55
[edit]: https://github.com/Collaboration95/dc2/blob/76282d3/media/services/v1_lifecycle.py#L105-L179
[command]: https://github.com/Collaboration95/dc2/blob/76282d3/processing/messaging.py#L232-L305
[supervisor]: https://github.com/Collaboration95/dc2/blob/76282d3/processing/worker/supervisor.py#L111-L131
[engine]: https://github.com/Collaboration95/dc2/blob/76282d3/media_engine/operations.py#L10-L50
[worker]: https://github.com/Collaboration95/dc2/blob/76282d3/processing/worker/sqs.py#L305-L378
[job-model]: https://github.com/Collaboration95/dc2/blob/76282d3/processing/models.py#L15-L107
[evans]: https://www.domainlanguage.com/wp-content/uploads/2016/05/DDD_Reference_2015-03.pdf
[media-model]: https://github.com/Collaboration95/dc2/blob/76282d3/media/models.py#L26-L103
[upload-model]: https://github.com/Collaboration95/dc2/blob/76282d3/media/upload_models.py#L25-L74
[vernon]: https://www.dddcommunity.org/wp-content/uploads/files/pdf_articles/Vernon_2011_2.pdf
[transport]: https://github.com/Collaboration95/dc2/blob/76282d3/delivery/sqs.py#L12-L75
[queue-policy]: https://github.com/Collaboration95/dc2/blob/76282d3/scripts/aws/v1/definitions.py#L863-L894
[handler-map]: https://github.com/Collaboration95/dc2/blob/76282d3/scripts/aws/v1/definitions.py#L283-L299
[mappings]: https://github.com/Collaboration95/dc2/blob/76282d3/scripts/aws/v1/definitions.py#L1267-L1301
[rules]: https://github.com/Collaboration95/dc2/blob/76282d3/scripts/aws/v1/definitions.py#L1739-L1790
[db-options]: https://github.com/Collaboration95/dc2/blob/76282d3/scripts/aws/v1/definitions.py#L47-L78
[activity-params]: https://github.com/Collaboration95/dc2/blob/76282d3/scripts/aws/v1/definitions.py#L896-L919
[persistent]: https://github.com/Collaboration95/dc2/blob/76282d3/scripts/ci/cd.sh#L52-L61
[network]: https://github.com/Collaboration95/dc2/blob/76282d3/scripts/aws/v1/definitions.py#L316-L489
[worker-network]: https://github.com/Collaboration95/dc2/blob/76282d3/processing/launcher.py#L90-L124
[parameter-policy]: https://github.com/Collaboration95/dc2/blob/76282d3/scripts/aws/v1/definitions.py#L809-L821
[gateway-limits]: https://github.com/Collaboration95/dc2/blob/76282d3/scripts/aws/v1/definitions.py#L1514-L1526
[database]: https://github.com/Collaboration95/dc2/blob/76282d3/scripts/aws/v1/definitions.py#L501-L547
[ecs-lb]: https://docs.aws.amazon.com/AmazonECS/latest/developerguide/service-load-balancing.html
[owner-list]: https://github.com/Collaboration95/dc2/blob/76282d3/media/repositories/assets.py#L81-L93
[mongo]: https://www.mongodb.com/docs/manual/core/transactions/
[dynamo]: https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/transaction-apis.html
[outbox-guidance]: https://docs.aws.amazon.com/prescriptive-guidance/latest/cloud-design-patterns/transactional-outbox.html
[media-head]: https://github.com/Collaboration95/dc2/blob/76282d3/media/migrations/versions/0008_upload_cleanup_schedule.py#L10-L33
[processing-head]: https://github.com/Collaboration95/dc2/blob/76282d3/processing/migrations/versions/0007_launch_reservations.py#L11-L59
[processing-ddl]: https://github.com/Collaboration95/dc2/blob/76282d3/processing/migrations/versions/0001_intake.py#L14-L67
[reservation-ddl]: https://github.com/Collaboration95/dc2/blob/76282d3/media/migrations/versions/0004_direct_uploads.py#L23-L49
[direct-retry]: https://github.com/Collaboration95/dc2/blob/76282d3/processing/messaging.py#L308-L322
[source-pin]: https://github.com/Collaboration95/dc2/blob/76282d3/media/services/direct_intake.py#L43-L72
[pipeline]: https://github.com/Collaboration95/dc2/blob/76282d3/processing/worker/tasks.py#L16-L81
[hls]: https://github.com/Collaboration95/dc2/blob/76282d3/media_engine/hls.py#L108-L117
[cleanup]: https://github.com/Collaboration95/dc2/blob/76282d3/processing/recovery.py#L113-L187
[worker-visibility]: https://github.com/Collaboration95/dc2/blob/76282d3/processing/worker/sqs.py#L255-L278
[operation-validation]: https://github.com/Collaboration95/dc2/blob/76282d3/processing/messaging.py#L260-L271
[output-dto]: https://github.com/Collaboration95/dc2/blob/76282d3/processing/schemas.py#L90-L95
[finish]: https://github.com/Collaboration95/dc2/blob/76282d3/processing/lifecycle.py#L184-L221
[projection-model]: https://github.com/Collaboration95/dc2/blob/76282d3/media/projection_models.py#L12-L29
[envelope]: https://github.com/Collaboration95/dc2/blob/76282d3/contracts/v1.py#L158-L218
[cancel-confirm]: https://github.com/Collaboration95/dc2/blob/76282d3/media/projections.py#L139-L174
[media-command]: https://github.com/Collaboration95/dc2/blob/76282d3/media/services/v1_lifecycle.py#L17-L48
[work-ack]: https://github.com/Collaboration95/dc2/blob/76282d3/processing/worker/sqs.py#L343-L378
[short-ack]: https://github.com/Collaboration95/dc2/blob/76282d3/processing/short_encoder.py#L73-L101
[edit-route]: https://github.com/Collaboration95/dc2/blob/76282d3/media/api/v1_jobs.py#L55-L66
[copy]: https://github.com/Collaboration95/dc2/blob/76282d3/media/services/storage.py#L209-L249
[pin-copy]: https://github.com/Collaboration95/dc2/blob/76282d3/media/services/direct_intake.py#L75-L96
[recovery]: https://github.com/Collaboration95/dc2/blob/76282d3/processing/recovery.py#L24-L67
[retry]: https://github.com/Collaboration95/dc2/blob/76282d3/processing/messaging.py#L155-L184
[work-repair]: https://github.com/Collaboration95/dc2/blob/76282d3/processing/recovery_v1.py#L84-L134
[cd-script]: https://github.com/Collaboration95/dc2/blob/76282d3/scripts/ci/cd.sh#L608-L665
[release-proof]: https://github.com/Collaboration95/dc2/blob/76282d3/scripts/aws/v1/proof/release_plan.py#L209-L263
[bad-candidate]: https://github.com/Collaboration95/dc2/actions/runs/39271754470
[baseline-policy]: https://github.com/Collaboration95/dc2/blob/76282d3/scripts/ci/cd.sh#L471-L512
[ecr]: https://github.com/Collaboration95/dc2/blob/76282d3/scripts/aws/v1/artifacts.py#L59-L133
[dast-cloud]: https://github.com/Collaboration95/dc2/blob/76282d3/.github/workflows/dast.yml#L58-L65
[dast-workflow]: https://github.com/Collaboration95/dc2/blob/76282d3/.github/workflows/dast.yml#L42-L101
[launcher-model]: https://github.com/Collaboration95/dc2/blob/76282d3/processing/launcher_models.py#L18-L29
[quality-report]: https://github.com/Collaboration95/dc2/blob/76282d3/project-documentation/final-report/src/40-quality.md#L10-L150
[roles]: https://github.com/Collaboration95/dc2/blob/76282d3/scripts/aws/v1/definitions.py#L742-L821
[ruff]: https://github.com/Collaboration95/dc2/blob/76282d3/scripts/dev/checks.py#L206-L231
[dast-target]: https://github.com/Collaboration95/dc2/blob/76282d3/scripts/dev/v1_dast.py#L1-L88
[dast-result]: https://github.com/Collaboration95/dc2/blob/76282d3/scripts/dev/v1_dast.py#L611-L685
[ffmpeg]: https://github.com/Collaboration95/dc2/blob/76282d3/docs/execution/aws/v1/scan-accepted-unfixed-20261017.json#L1
[selection]: https://github.com/Collaboration95/dc2/blob/76282d3/scripts/ci/policy.py#L194-L290
[ci-workflow]: https://github.com/Collaboration95/dc2/blob/76282d3/.github/workflows/ci.yml#L596-L817
[v1-scans]: https://github.com/Collaboration95/dc2/blob/76282d3/.github/workflows/v1.yml#L194-L274
[prep]: https://github.com/Collaboration95/dc2/blob/76282d3/.github/workflows/aws-prep.yml#L45-L107
[sonar]: https://github.com/Collaboration95/dc2/blob/76282d3/.github/workflows/ci.yml#L763-L877
[admission]: https://github.com/Collaboration95/dc2/blob/76282d3/scripts/ci/cd_gate.py#L16-L113
[later-smoke]: https://github.com/Collaboration95/dc2/blob/76282d3/.github/workflows/cd.yml#L230-L251
[evidence-index]: https://github.com/Collaboration95/dc2/blob/76282d3/docs/evidence-index.md#L1
[uploads]: https://github.com/Collaboration95/dc2/blob/76282d3/media/api/uploads.py#L18-L44
[appendix-models]: https://github.com/Collaboration95/dc2/blob/76282d3/project-documentation/final-report/src/70-appendices.md#L102-L138
[attempt-index]: https://github.com/Collaboration95/dc2/blob/76282d3/processing/migrations/versions/0002_lifecycle.py#L28-L34
[cleanup-index]: https://github.com/Collaboration95/dc2/blob/76282d3/processing/migrations/versions/0006_cleanup_retirement.py#L23-L29
[figure-renderer]: https://github.com/Collaboration95/dc2/blob/76282d3/project-documentation/final-report/tools/render_figures.py#L56-L63
[report-builder]: https://github.com/Collaboration95/dc2/blob/76282d3/project-documentation/final-report/tools/build_report.py#L205-L239
