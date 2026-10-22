# Presentation research: sections 1-4

- **Audience/slot:** NUS Graduate Certificate in Architecting Scalable Systems, Team 17, FlickPond; 26 Oct 2026, 14:35-15:15 SGT, Zoom. The slot includes questions. Sources: `project-documentation/presentation/ROAD-TO-PRESENTATION.md`; `project-documentation/original-reference/04 Project Presentation Guidelines & Schedule.pdf`, pp. 1-2.
- **Authority:** official guideline for coverage/timing; `project-documentation/final-report/src/*.md` for the presentation narrative; architecture documents, implementation and retained receipts for detail and explicit discrepancies below. Explainer JSON is study material, not independent evidence.
- **Research boundary:** repository-only review on 22 Oct; no AWS or GitHub access, no live-system verification. “Deployed” below means reported by retained sources. Paths are repository-relative. `[AWS receipt]`, `[Local]`, `[Code]` and `NOT_RUN` must remain distinct on slides.
- **Slide rule:** one claim or diagram per slide; put paths and evidence dates in notes/footers. Use the risks as backup material, not a narrated catalogue.

## 1. Overview - 2 min talk + 1 min Q&A

Timing source: `project-documentation/presentation/ROAD-TO-PRESENTATION.md`, time-budget row 1; original guideline §1(a-c).

### (a) Key messages, covering every guideline bullet

- **1a - Problem/context:** small training/content teams repeatedly rebuild upload, conversion, status and protected playback; CPU-heavy bursts should not compete with interactive requests. Source: `project-documentation/final-report/src/10-introduction.md`, Business Needs.
- **1b - Platform thinking:** the reusable seed is an owned Asset plus its processing Job; uploaders produce it, owners consume playable output, integrators use the public contract, operators manage capacity/releases. Source: `project-documentation/final-report/src/30-logical.md`, Platform Design.
- **1b - Concrete reuse:** the browser and independently built Publisher CLI use the same public API, without client access to service internals or databases. Source: `project-documentation/final-report/src/40-quality.md`, Extensibility and Maintainability.
- **1c - Contribution:** preserve the working video engine, then change ownership, communication, deployment and reuse; credit the inherited capabilities explicitly. Source: `project-documentation/final-report/src/10-introduction.md`, Background/scope table.
- **1c - Scope:** owner-only asynchronous video processing, status/playback, stored-source retry, batch publishing, independent capacity and release; public sharing, tenants, live streaming and regional failover are excluded. Source: `project-documentation/final-report/src/10-introduction.md`, Project Scope.

**Scope contrast to show visually** - source for every row: `project-documentation/final-report/src/10-introduction.md`, inherited/added table and scope.

| Area | Inherited Project 1 | Added/reshaped in Project 2 |
|---|---|---|
| Product/engine | Accounts, upload/playback UI, FFmpeg, MP4, adaptive HLS, worker replicas, basic CI | API platform and new Publisher CLI; do not claim encoding/HLS as new |
| Ownership | FastAPI monolith; shared job code/database; jobs linked to users | Media and Processing contexts; owned schemas, migrations, roles, images and release units |
| Integration | Redis/RQ, MinIO, nginx on a VM | SQS outbox/inbox, immutable S3 source pins, Media projection, trusted Gateway actor |
| Cloud/operations | Manual deployment | Persistent serverless environment; bounded finite encoders; short Lambda lane; per-service Aurora clusters; automated release/smoke/restore |
| Additional built scope | Baseline capability | Edit-derived assets, deletion/tombstones, operator admin routes; acknowledge these small additions without turning the talk into a feature tour |

### (b) Hard numbers worth showing

| Number | Meaning / presentation limit | Source |
|---|---|---|
| 2 business services; 2 clients; UC-1 through UC-7 implemented | A bounded reuse demonstration, not external adoption | `project-documentation/final-report/src/10-introduction.md`, Current status/Functionality in scope |
| 100 MiB upload maximum; HLS 360p/480p/720p, capped at source height | HLS is best effort; no upscaling claim | `project-documentation/final-report/src/10-introduction.md`, UC-1/UC-2 |
| Publisher: 491 Python lines in 6 files; 0 service imports; 0 DB credentials | Use the independence figures as the headline; size as optional context | `project-documentation/final-report/src/40-quality.md`, Extensibility and Maintainability |
| 5-member inherited team; 3-member Project 2 team | Ibrahim came from FlickPond; Guruprasath and Long came from another team | `project-documentation/final-report/src/10-introduction.md`, Background |

### (c) Existing visuals to reuse

| Exact path | Reuse / simplification |
|---|---|
| `project-documentation/final-report/figures/platform-context.png` | Best overview starting point; landscape and readable. Relabel “Viewers” as “owners viewing their own output”; label the Media-to-Processing arrow asynchronous. |
| `project-documentation/final-report/figures/architecture-before-after.png` | Reuse the inherited left half only. Right half explicitly says **proposed** and still shows token/Redis; redraw it as contexts, queues, owned data and clients before presenting as current. |
| `project-documentation/final-report/figures/report-use-cases.png` | Backup for scope questions; too much detail for the opening. Simplify to upload/process/play, retry/batch, operate/release; put exclusions in a short side strip. |

### (d) What is distinctive

- Reuse is demonstrated by a separately bounded client, rather than asserted from a box labelled “API.” Source: `project-documentation/final-report/src/30-logical.md`, platform-role table.
- The contribution is the evolution of a functioning monolith into owned capabilities with durable integration; it is not another list of video-player features. Source: `project-documentation/final-report/src/60-other.md`, contribution list.

### (e) Likely examiner questions

| Question | Crisp answer grounded in sources |
|---|---|
| What business problem is different from building a video site? | Applications repeatedly need the same safe intake-to-playback workflow. We expose that workflow as a reusable contract and separate encoding capacity from interactive work. `project-documentation/final-report/src/10-introduction.md`, Business Needs. |
| Why call it a platform? | Browser and Publisher consume the public contract without importing the backend or reading its databases. That establishes bounded client reuse; it does not establish a marketplace or external adoption. `showcase-prep/content/basics.json`, “Why call this a platform?” |
| Who are the producers and consumers? | Content owners upload through the browser or Publisher; the same owners consume output through the player. Integrators build clients and operators manage the platform; there is no separate viewer-sharing product. `project-documentation/final-report/src/30-logical.md`, platform-role table. |
| What exactly did you inherit? | FFmpeg processing, HLS, worker replicas and the basic CI workflow were already FlickPond capabilities. Our work changed boundaries, contracts, cloud runtime, delivery and reuse. `project-documentation/final-report/src/10-introduction.md`, Background. |
| Can a teacher share these videos with students? | Not in the delivered scope: ownership belongs to the uploading account, with no student/LMS access or shared team ownership. The teaching persona is a planning assumption. `project-documentation/final-report/src/10-introduction.md`, Stakeholders/out-of-scope list. |
| Why is Processing the extracted capability? | It has distinct job/attempt/lease rules and a CPU-heavy scaling profile. Ownership and playback still need the account and Asset together, so their rules stay inside Media. `docs/architecture/ddd.md`, §3; AD-01 in `docs/architecture/decisions.md`. |

### (f) Risks / disagreements

- **Proposed diagram versus built system:** `project-documentation/final-report/figures/architecture-before-after.png` retains peer HTTP/token and Redis on its right; `project-documentation/final-report/src/30-logical.md` records asynchronous SQS and trusted identity. Do not show its proposed side as delivered.
- **Viewer wording:** `project-documentation/final-report/figures/platform-context.png` separates “Viewers”; `docs/architecture/ddd.md` §7 and `media/authorizer.py` say the contract's `viewer` role is never issued. State owner-as-viewer.
- **Provenance is resolved in the report:** `showcase-prep/content/meeting.json` and earlier portions of `docs/release/engineering-handoff.md` still request resolution of Ibrahim's baseline membership; `project-documentation/effort-ledger.md`, Project 1 effort, and `project-documentation/final-report/src/10-introduction.md` explicitly credit his FlickPond membership and the others' different team. Also distinguish proposal baseline `890c5ec` from local working baseline `8854537` (same sources).
- **Overbroad “no new features”:** `project-documentation/final-report/src/60-other.md` says the project did not add product features; `project-documentation/final-report/src/10-introduction.md` lists edit, delete and admin additions. Say architecture/reuse was the central contribution, with those limited additions.

## 2. Project conduct - 1.5 min talk + 0.5 min Q&A

Timing source: `project-documentation/presentation/ROAD-TO-PRESENTATION.md`, row 2; original guideline §2(a-b).

### (a) Key messages, covering every guideline bullet

- **2a - Status:** committed functionality is reported complete; presentation, recordings, rehearsal, course checks and post-presentation report feedback remain. Source: `project-documentation/final-report/src/20-conduct.md`, Project Status; `project-documentation/presentation/ROAD-TO-PRESENTATION.md`.
- **2a - Outstanding architecture:** name performance, public-edge hardening, schema compatibility on rollback, operational hardening and missing evidence as the remaining issue classes. Source: `project-documentation/final-report/src/36-other-limitations.md`, AISS register.
- **2b - Actual conduct:** delivery proceeded in waves, from frozen baseline/domain analysis through extraction, cloud proofs and persistent operation; do not invent sprint ceremonies. Source: `project-documentation/final-report/src/20-conduct.md`, Way of working/Milestones.
- **2b - Effort:** show team-agreed allocation with specialist leads; distinguish recorded effort from the submission forecast and from timesheets. Source: `project-documentation/effort-ledger.md`, Basis/Specialisms/effort table.

### (b) Hard numbers: status, actual milestones, effort

**Actual milestone strip** - all dates from `project-documentation/final-report/src/20-conduct.md`, Milestones, except the final row's additional sources.

| Actual date | Outcome | Source |
|---|---|---|
| 4 Oct | Proposal submitted | `project-documentation/final-report/src/20-conduct.md` |
| 7-9 Oct | Lecturer feedback, frozen baseline, DDD/contracts; design finished 2 days beyond plan | `project-documentation/final-report/src/20-conduct.md` |
| 12 Oct; 13 Oct | Processing extracted; Media and Publisher adapted | `project-documentation/final-report/src/20-conduct.md` |
| 15 Oct; 17-18 Oct | AWS tooling; cloud proof runs and `project2-v1` tag | `project-documentation/final-report/src/20-conduct.md` |
| 18-19 Oct; 20 Oct | Persistent environment/CD, security/scaling evidence; accepted demo freeze | `project-documentation/final-report/src/20-conduct.md` |
| 21 Oct | Report draft/remediation delivery; short lane and per-service database split delivered later | `project-documentation/final-report/src/20-conduct.md`; `project-documentation/final-report/src/32-physical.md`; `project-documentation/presentation/ROAD-TO-PRESENTATION.md` |

**Member effort** - all numbers from `project-documentation/effort-ledger.md`, cross-checked with `project-documentation/final-report/src/20-conduct.md`, Effort per member. One person-day = 8 hours; these are allocations, not logged elapsed hours.

| Member | Specialism / lead work | Recorded through 20 Oct | Submission forecast |
|---|---|---|---|
| Guruprasath Gopal | Cloud, CI/CD, release/rollback, freeze | 11 pd / 88 h | 12 pd / 96 h |
| Ibrahim Mammadov | Processing extraction, Media adaptation, boundary security | 11 pd / 88 h | 12 pd / 96 h |
| Nguyễn Kim Long | DDD/contracts, Publisher, experiments, evidence | 11 pd / 88 h | 12 pd / 96 h |
| Total | Plan: 31 pd | 33 pd / 264 h | 36 pd / 288 h; about 16% above plan |

**Outstanding limitations** - authoritative register: `project-documentation/final-report/src/36-other-limitations.md`. Put issue classes on the main slide; keep details in backup.

| ID | Current impact / useful numbers | Owner and disposition |
|---|---|---|
| AISS-01 | AWS scaling 1.449× vs 1.6× at 2 workers; standard queue wait about 37 s vs 20 s; short-lane wait 0.26 s, but reported warm submit-to-done 45.2 s and Fargate 87.7 s still exceed the 20 s aim. AWS used 6 clips, not the proposal's 30. | Long + Guruprasath; trace unexplained latency and repeat the larger workload. Sources: `project-documentation/final-report/src/36-other-limitations.md`; `docs/results/actual-vs-target.md`. |
| AISS-02 | Direct `execute-api` endpoint reachable; no WAF | Guruprasath; proposed origin restriction and WAF. Source: `project-documentation/final-report/src/36-other-limitations.md`. |
| AISS-03 | Rollback restores code/aliases, not schema | Ibrahim; additive migration policy today; automated compatibility testing is future work. Source: `project-documentation/final-report/src/36-other-limitations.md`. |
| AISS-04 | Broad deploy role, no staging/reviewer/branch-protection gate; alarms have no paging target; logs retained 7 days | Guruprasath; operational hardening remains. Source: `project-documentation/final-report/src/36-other-limitations.md`; alarm-count caveat in §4(f). |
| AISS-05 | AWS lost-entry timing, post-kill duplicate-output check, backup restore drill, Publisher build effort and actual bill not established | Long + Guruprasath; bill check before 16 Nov; remaining experiments on roadmap. Source: `project-documentation/final-report/src/36-other-limitations.md`. |

- Also retain the **release-time miss:** CD Release step 10.1-10.3 min vs 10 min in the earlier run; a later 9m39s step plus separate 5m59s upload smoke totals 15m38s. These are different boundaries, not a retroactive pass. Source: `docs/results/actual-vs-target.md`, DP-1/DP-3/DP-4.

### (c) Existing visuals to reuse

| Exact path | Reuse / simplification |
|---|---|
| `project-documentation/final-report/figures/report-schedule.png` | Too dense for the short conduct slot. Reduce to proposal → extraction → AWS proof → persistent operation/freeze → preparation; mark future presentation/revision as scheduled. It omits the latest lane/database additions. |
| `project-documentation/final-report/figures/report-burnup.png` | Backup only; issue counts are dated scope/closure evidence, not effort or velocity. |
| `project-documentation/final-report/figures/actual-vs-target.png` | Crop the relevant miss/pass comparison if needed; not a current live dashboard and does not explain short-lane latency. |

### (d) What is distinctive

- Equal agreed effort with different specialist leads, plus transparent inherited credit; account history is not used as a member-timesheet proxy. Source: `project-documentation/final-report/src/20-conduct.md`, Effort/Delivery metrics.
- A completed functional scope is reported alongside measured misses and unrun evidence; targets were retained rather than rewritten. Source: `docs/results/actual-vs-target.md`, Read this first.

### (e) Likely examiner questions

| Question | Crisp answer grounded in sources |
|---|---|
| Is the project finished? | The committed use cases are implemented and tested according to the report. Presentation/submission work and explicitly recorded quality/evidence limitations remain. `project-documentation/final-report/src/20-conduct.md`, Project Status. |
| Are the member hours actual timesheets? | No: they are a team-agreed equal allocation of work packages. The ledger is the attribution record; repository activity cannot establish individual effort. `project-documentation/effort-ledger.md`, Basis; `project-documentation/final-report/src/20-conduct.md`, Delivery metrics. |
| Why did effort exceed the plan? | Cloud delivery automation and integration close-out grew, including deploy-script, database-pause and duplicate-message fixes. The report separately identifies the remaining presentation/revision forecast. `project-documentation/final-report/src/20-conduct.md`, Total effort. |
| What slipped? | Baseline/design finished later than planned, but extraction and the main AWS work still landed inside their planned windows. Rehearsal is scheduled work, not evidence of an already completed milestone. `project-documentation/final-report/src/20-conduct.md`, Milestones. |
| What is the most significant unresolved issue? | Latency: removing Fargate startup for eligible clips improved queue wait, but substantial time remains outside queueing and encoding. The next investigation is per-stage tracing, not a claim that the end-to-end aim is met. `project-documentation/final-report/src/36-other-limitations.md`, AISS-01. |
| What did each member own? | Guruprasath led cloud/delivery; Ibrahim led backend services; Long led domain/contracts/verification. They reviewed across areas; this is the agreed responsibility split, not authorship inferred from commits. `project-documentation/effort-ledger.md`, Specialisms. |
| What evidence is still missing? | Cloud lost-entry timing and duplicate-output recovery checks, a backup restore drill, measured client-build effort and actual billed spend remain unestablished. Automatic image restore after a bad release is a different, evidenced scenario. `project-documentation/final-report/src/36-other-limitations.md`, AISS-05; `project-documentation/final-report/src/40-quality.md`. |

### (f) Risks / disagreements

- **Stale conduct snapshot:** `project-documentation/effort-ledger.md`, Progress report, still says frozen `daee44b`, issue #271 open, and report draft pending. `project-documentation/final-report/src/36-other-limitations.md` says #271's missing-object error was fixed; `20-conduct.md` records later releases/report completion. Use the ledger for allocation, not current runtime status.
- **Forecast is not recorded effort:** the ledger mixes “2 pd over” with the later 36-pd forecast. The recorded comparison is 33 vs 31 pd; the forecast comparison is 36 vs 31 pd, as separated in `project-documentation/final-report/src/20-conduct.md`.
- **Release identities differ by snapshot:** `20-conduct.md` calls `c7c489c` current and records `Main` at `1d68eff`; `ROAD-TO-PRESENTATION.md` records a later green CD run `39733859422`. Lane benchmark/split references are later again than the original accepted freeze. Label the receipt's source/date; do not claim the report's SHA is today's running SHA.
- **Stale administrative prompts:** `showcase-prep/content/meeting.json` and the ledger still list final-report preparation/provenance checks as pending where the report already resolves them. Presentation, recordings, peer assessment and receipt checks still need team/course confirmation; no completion is inferred here.
- **Historical delivery counts:** PR/issues/tests in `20-conduct.md` are explicitly dated before later changes; omit them from the short main segment unless labelled as snapshots. Project 1 hours are absent from this ledger; do not manufacture a combined-project total.

## 3. Logical architecture and design - 7 min talk + 2 min Q&A

Timing source: `project-documentation/presentation/ROAD-TO-PRESENTATION.md`, row 3; original guideline §3(a-c), including producer/consumer interaction.

### (a) Key messages, covering every guideline bullet

- **3a - Boundary decision:** Processing owns job execution rules; Media keeps identity, asset ownership and playback together. Source: AD-01/AD-02, `docs/architecture/decisions.md`; `docs/architecture/ddd.md` §3.
- **3a - Integration decision:** commands/results cross an asynchronous contract; outbox/inbox, projections and fences make duplicate/reordered delivery safe. Source: AD-11/AD-21/AD-24, `docs/architecture/decisions.md`.
- **3b - Components:** clients → edge → domain API/domain/persistence layers → execution adapters → owned stores; Lambdas and encoders are roles within a service, not extra business services. Source: `project-documentation/final-report/src/30-logical.md`, Tiers/Nodes.
- **3c - DDD:** Asset and ProcessingJob are separate local consistency boundaries linked by identifier values and translated messages, not shared ORM objects. Source: `docs/architecture/ddd.md` §§2-6.
- **3c - Producers/consumers:** both clients reserve/upload/finalize through the public contract; owners read Media's projection and receive temporary playback access. Source: `project-documentation/final-report/src/30-logical.md`, platform-role table.

**Decision spine for 3a** - identifiers/rationale: `project-documentation/final-report/src/30-logical.md`, Key Architectural Decisions; full records in `docs/architecture/decisions.md`.

| Decisions | Explain the causal choice | Accepted cost |
|---|---|---|
| AD-01, AD-02 | Split rules/data at the encoding lifecycle; own migrations and credentials | More integration than a monolith; shared infrastructure remains |
| AD-09, AD-20 | Media authorizer supplies trusted Actor; IAM authenticates queue principals | Public API authorization still depends on Media's current user lookup |
| AD-11 | SQL state + outbox locally; SQS + inbox across contexts | At-least-once delivery, repair and delayed publication |
| AD-14 | Direct upload, verify, pin exact source version before adoption | Client hashing and orphan cleanup |
| AD-21, AD-24, AD-26 | Owned projection; versioned published language/shared kernel; no legacy/opposite-domain imports in images | Eventual consistency; coordinated evolution for breaking contracts |

**Component/deployment explanation for 3b** - source: `project-documentation/final-report/src/30-logical.md`, element/tier/subsystem tables.

| Group | Logical responsibility / deployment relationship |
|---|---|
| Web SPA + Publisher | Public clients; no privileged storage, queue or database integration |
| CloudFront + Gateway + MediaAuthorizer | Public HTTPS, route groups, trusted actor before domain handlers |
| Media image | API/ownership/intake; result consumer updates projection; repair publishes commands and cleans sources; its own DB |
| Processing image + worker image | Job/attempt rules; command consumption; repair/events; bounded launching; Lambda/Fargate encoding adapters; its own DB |
| Shared kernel | `contracts/`, `delivery/`, `runtime_support/` copied into images; contract values and delivery/runtime mechanics, not shared domain tables |
| Data/transport | Owned SQL state; S3 source/output bytes; commands/work/results queues; no synchronous business handoff between contexts |

**DDD elements for 3c** - source: `docs/architecture/ddd.md` §§2-7; `project-documentation/final-report/src/30-logical.md`, Platform Design.

| Element | Concrete explanation |
|---|---|
| Bounded contexts | Media: User, ownership, intake, source pins, public projection/playback. Processing: Job, Attempt, lease, retry/cancel, output descriptors and launch reservations. |
| Asset aggregate | Root `Asset`; reservations/source versions, request keys and cleanup state support owner checks, immutable adopted source, atomic adoption + submit, tombstoned deletion. |
| ProcessingJob aggregate | Root `Job`; Attempts, RetryRequest, AttemptTask and SubmissionGuard enforce current attempt, serialised commands, live-lease completion, cancel-before-submit and one job per asset. |
| Context map | Media is customer, Processing supplier. Media translates Asset → command and result → local projection; Processing translates messages → owned job model. Published language plus a small shared kernel. |
| Ubiquitous language | **Asset** = owned resource; **Job** = requested processing; **Attempt** = numbered execution; **Source revision** = pinned VersionId + size/hash; **Lease** = temporary DB-clock authority; **Projection** = Media's local view. |
| Outbox/inbox | State and outgoing intent commit together; send occurs outside SQL locks under a claim token. Inbox identity + canonical body hash commits with domain mutation before ACK. |
| Projection/event semantics | Full result snapshots ordered by `state_version` and attempt; older results ignored, conflicts rejected. Event-carried state transfer, not event sourcing or a replayed domain-event log. |
| Producer interaction | Owner/browser or Publisher: reserve → direct S3 POST → finalize; status/retry/edit/delete by public API. Publisher batch keeps per-file outcomes. |
| Consumer interaction | Owner/player: Media asset + projection read → signed MP4; HLS playlist through Media, segments redirected to S3. Integrator uses OpenAPI; operator uses delivery/capacity tooling. |

### (b) Hard numbers worth showing

| Number | Evidence boundary | Source |
|---|---|---|
| 2 contexts, 1 Job per Asset; attempts numbered independently | Ownership/uniqueness invariants, not service-per-function counting | `docs/architecture/ddd.md`, §§3-4 |
| 5 message kinds: submit/retry/cancel/work/result | Short work is an additional transport lane, not another message kind | `project-documentation/final-report/src/30-logical.md`, message table; `processing/short_lane.py` |
| 2 OpenAPI documents at 1.0.0; wire version 1; N/N-1 policy | Only version 1 exists live; previous-version compatibility is tested, not a real multi-version production history | `docs/architecture/ddd.md`, §6; `project-documentation/final-report/src/40-quality.md`, limits |
| Consumer disabled 48 s; Media accepted 202; job done 58.9 s after re-enable | AWS V1 isolation receipt; command consumer only, Processing API stayed available | `docs/results/actual-vs-target.md`, AV-5 |
| 9/9 jobs done, 18 work sends, no manual purge | Historical persistent-environment burst; duplicates occurred and were tolerated | `docs/results/actual-vs-target.md`, LV-11 |

### (c) Existing visuals to reuse

| Exact path | Reuse / simplification |
|---|---|
| `project-documentation/final-report/figures/report-logical.png` | Best report logical-detail starting point, but very tall/dense. Redraw landscape: two client boxes, edge, two layered service boxes, each own SQL store, explicit async seam, execution adapters and a small shared-kernel strip. Its combined Aurora cylinder must not imply a shared current cluster. Source: `project-documentation/final-report/figures/src/report-logical.mmd`. |
| `docs/architecture/img/views-logical.svg` | Vector alternative, source `docs/architecture/views.md` §1. Baseline view omits short Lambda adapter and combines databases visually; use for layers, not current topology counts. |
| `project-documentation/final-report/figures/report-context-map.png` | Tall enough to be unreadable when fitted; simplify to side-by-side Asset and Job contexts, command/result arrows, Media projection and published-language label. Source: `project-documentation/final-report/figures/src/report-context-map.mmd`. |
| `docs/architecture/img/ddd-context-map.svg` | Editable/vector context-map reference; same dense content. Use as backup, preserving direct client-to-Processing routes separately from service-to-service traffic. |
| `project-documentation/final-report/figures/report-dp2-handoff.png` | Before/after durable-handoff backup; simplify main slide to local commit → outbox → queue → inbox → local commit, with result/projection return path. |
| `docs/architecture/img/views-job-states.svg` | Good focused backup for retry/attempt questions; annotate that cancellation is a public/result state, not a `jobs.status` enum value. Source: `docs/architecture/views.md`, §5. |

### (d) What is distinctive

- Invariants justify the service split: the account/Asset join stays local while job execution has its own authority and lifecycle. Sources: `docs/architecture/ddd.md` §§3-4; AD-01.
- Worker authority and integration authority are separate: a leased encoder updates Processing SQL but cannot publish queue results; a Processing publisher does that. Source: `project-documentation/final-report/src/30-logical.md`, relationships/message table.
- Monotonic result projections remove peer calls from status/playback while preserving owner/source/attempt checks. Source: AD-21; `media/projections.py`.

### (e) Likely examiner questions

| Question | Crisp answer grounded in sources |
|---|---|
| Why not split Identity and Delivery too? | Both decisions require account and Asset together; separate services would turn local joins into remote coordination without a distinct rule set or release need. `docs/architecture/ddd.md` §3; AD-01. |
| Are all these Lambdas microservices? | No. A service has its own rules, data and release unit; handlers/encoders are execution roles of Media or Processing. `project-documentation/final-report/src/30-logical.md`, Nodes and Subsystems. |
| Is this exactly-once processing? | Delivery is at least once. Inbox dedupe, idempotent transitions, attempt namespaces and lease/version fences protect logical outcomes despite duplicates; the cloud worker-kill duplicate-output criterion remains unproven. `docs/architecture/use-case-design.md`, Actual fences; AISS-05. |
| Why SQL outbox if SQS is durable? | Durability begins after SQS receives a message; it does not make the earlier database commit/send atomic. The outbox preserves intent with local state, and send replay plus inbox dedupe handles lost replies. `docs/architecture/ddd.md` §5; `delivery/sql.py`. |
| What if results arrive out of order? | Media accepts newer state in the right job/source/attempt namespace, ignores older snapshots and rejects conflicting content at the same version. It does not query Processing to repair every read. `media/projections.py`; AD-21. |
| Is this event sourcing or CQRS? | Media has a separate projected read model, but SQL rows remain authoritative and messages are full state snapshots. It is not event sourcing; describe the concrete projection rather than claiming an elaborate framework. `project-documentation/final-report/src/30-logical.md`, Commands/results/domain events. |
| Can the services be released in any order? | Additive contract changes follow a consumer-first compatibility policy; shared libraries remain a shared kernel. Breaking changes need staged releases, while schema compatibility is still attested rather than fully automated. `docs/architecture/ddd.md` §6; AD-24; AISS-03. |
| What if an old worker finishes after a retry? | Completion requires the current attempt and live DB-clock lease token; an older worker cannot commit success. Its output keys belong to its old attempt and are subject to cleanup. `processing/lifecycle.py`; `docs/architecture/use-case-design.md`, UC-4. |
| Do separate databases eliminate all dependencies? | They remove shared-table ownership and, after the cluster split, shared database capacity. Public Processing requests still require Media's authorizer; account/VPC/edge infrastructure and shared contract evolution remain coupled. `media/authorizer.py`; `project-documentation/final-report/src/30-logical.md`; AD-23/AD-29. |

### (f) Risks / disagreements

- **“No runtime dependency” is too broad:** `project-documentation/final-report/src/70-appendices.md`, analysis-to-design table, uses that wording; `30-logical.md` and `media/authorizer.py` require Media's current-user lookup on protected Processing routes. Claim no synchronous **business handoff/peer status call**, not complete availability independence.
- **Failure-isolation proof has limited scope:** `docs/architecture/decisions.md` §6 retains the heading “not yet proven on AWS,” but its own text and `docs/results/actual-vs-target.md` AV-5 record a passing command-consumer outage test. State exactly that scenario; not a whole-service or database outage.
- **State-machine naming:** `showcase-prep/content/data.json` lists cancelled among job states; `docs/architecture/views.md` §5 says the database `jobs.status` excludes it, represented by deletion state/result snapshots. Distinguish DB state, attempt state and public projection state.
- **Diagram/data ownership drift:** `report-logical.png` and `docs/architecture/img/views-logical.svg` visually combine Aurora; current report text and AD-29 specify owned clusters. Logical grouping is not a current physical node count.
- **Version-policy overclaim:** `docs/architecture/ddd.md` §6 explicitly says only wire version 1 exists; do not describe N/N-1 tests as demonstrated real dual-version deployment.

## 4. Physical architecture and design - 7 min talk + 2 min Q&A

Timing source: `project-documentation/presentation/ROAD-TO-PRESENTATION.md`, row 4; original guideline §4(a-d).

### (a) Key messages, covering every guideline bullet

- **4a - Cost/latency decisions:** scale compute down when idle; avoid NAT and persistent encoders; accept measured wake/start delays. Source: AD-10/AD-12/AD-13/AD-18/AD-27 in `docs/architecture/decisions.md`.
- **4b - Nodes/network:** managed public edge, private dual-stack Lambda/Aurora subnets, finite public-subnet Fargate tasks with no inbound access, private S3 access policies and role-scoped SQS. Source: `project-documentation/final-report/src/32-physical.md`.
- **4b - Current execution:** eligible short clips use the Lambda adapter; other work uses finite Fargate tasks; both share Processing's leased Job/Attempt model. Source: `processing/short_lane.py`; `project-documentation/final-report/src/34-persistence-detailed.md`, Launch/Encode.
- **4c - Persistence:** each context owns a separate Aurora cluster and SQL transaction boundary; S3 stores pinned sources and attempt-scoped outputs; queues transport recoverable metadata. Source: `project-documentation/final-report/src/34-persistence-detailed.md`, Persistence Design; AD-29.
- **4d - Representative use case:** explain upload → encode → play, with an explicit branch for executor admission and a failure fence at each cross-system step. Source: `project-documentation/final-report/src/34-persistence-detailed.md`, Case 1, plus short-lane implementation below.

**Decision spine for 4a** - full records in `docs/architecture/decisions.md`; report summary in `project-documentation/final-report/src/32-physical.md`.

| Decisions | Why / trade-off to say |
|---|---|
| AD-10, AD-12, AD-29 | Container Lambdas and pausing relational clusters; separate cluster capacity/failure boundaries, with extra storage/wake cost and no database replica failover |
| AD-13, AD-22, AD-27 | Finite bounded work, persistent environment, short-encode experiment adopted; low idle compute cost versus cold-start latency |
| AD-14, AD-15 | S3 transfers avoid public API payload limits; CloudFront provides HTTPS/static frontend, while API and signed playback remain uncached |
| AD-18, AD-20 | IPv6 egress/S3 gateway instead of NAT; separate handler roles; encoder source reads are bucket-wide and owner/source binding is enforced in code |
| AD-16, AD-17, AD-23 | Owner code releases by immutable digest/alias over OIDC; infrastructure remains a shared stack and rollback does not restore schema |

**Network, nodes, technologies and services for 4b**

| Area | Explain / numbers | Source |
|---|---|---|
| Region/network | `ap-southeast-1`; VPC `10.62.0.0/16` + IPv6, 2 AZs, private/public subnet in each; DB ingress 5432 only from permitted internal groups | `project-documentation/final-report/src/32-physical.md`, Network; `scripts/aws/v1/definitions.py`, `SEPARATE_DATABASE_SOURCES` |
| Public edge | CloudFront → API Gateway HTTP API; stage 20 requests/s, burst 50; private frontend S3 origin/OAC | `project-documentation/final-report/src/32-physical.md`, component table |
| Private egress | No IPv4 default route/NAT for Lambda; IPv6 egress-only gateway for dual-stack AWS endpoints; S3 gateway endpoint, including regional ECR layer reads | `docs/architecture/views.md`, §3.1; `docs/architecture/decisions.md`, AD-18 |
| Media deployment | Image runs MediaApi, MediaAuthorizer, MediaResults, MediaRepair: 4 functions | `project-documentation/final-report/src/32-physical.md`, component table |
| Processing deployment | Image runs API, Commands, Repair, ECS events, S3 events, Launcher, ShortEncoder: 7 functions | `project-documentation/final-report/src/32-physical.md`, component table |
| Standard encoder | ECS Fargate, no ECS service; 2 vCPU / 4 GiB; 0-3 tasks, one attempt each; temporary public IPv4, outbound only | `project-documentation/final-report/src/32-physical.md`, Encoder/AD-13 |
| Short encoder | Lambda container, 3008 MB, 900 s timeout, 2048 MB scratch; SQS mapping max concurrency 2; admitted source ≤64 MiB, duration ≤60 s, height ≤1080 px | `processing/short_lane.py`; `scripts/aws/v1/definitions.py`; `project-documentation/final-report/src/32-physical.md` |
| Databases | Aurora PostgreSQL 16 Serverless v2: 2 clusters, 1 instance each, 0-2 ACU each, auto-pause setting 300 s, verified TLS | `project-documentation/final-report/src/32-physical.md`; `scripts/aws/v1/definitions.py`, DatabaseOptions |
| Storage/messages | 3 application S3 buckets: source/output/frontend. Baseline queues: commands/work/results; enabled short lane adds short-work + its DLQ. CD also uses a private state bucket | `scripts/aws/v1/definitions.py`; `project-documentation/final-report/src/34-persistence-detailed.md`, telemetry/delivery evidence |
| Supporting services | EventBridge repair/event hints; SSM role DSNs/JWT secret; RDS-managed Secrets Manager secret; ECR; IAM/OIDC; CloudWatch dashboard/alarms; Budgets | `project-documentation/final-report/src/32-physical.md`, Technology and Services |
| Runtime stack | Python 3.12/FastAPI/Pydantic/SQLAlchemy/Alembic; FFmpeg/ffprobe; plain JS SPA with hls.js/Plyr; stdlib + httpx Publisher | `project-documentation/final-report/src/32-physical.md`, Technology and Services |

**Persistence for 4c** - sources: `project-documentation/final-report/src/34-persistence-detailed.md`; `docs/architecture/views.md` §4.

| Store / boundary | Design and invariant |
|---|---|
| `media_db` | Users/Assets, upload reservations and source pins, request keys, projections, cleanup; owner-local joins; adoption + outgoing submit in one transaction |
| `processing_db` | Jobs/Attempts, SubmissionGuard, RetryRequest, AttemptTask, lease/version state, launch reservations and cleanup; no foreign keys into Media |
| DB roles | Owner cannot log in; migrator can change schema; runtime is DML-only. Domain login/SSM credentials do not grant the peer's database access |
| Outbox/inbox | Local atomic state + intent; `SKIP LOCKED` publisher claim, network outside lock, token-fenced acknowledgement; inbox message ID/body hash committed with consumption |
| S3 source | `staging/{owner}/{reservation}/source` remains the adopted key; VersionId + size/hash fixes accepted bytes. Edit-derived pins use `sources/{owner}/{asset}/source` |
| S3 output | `jobs/{job}/attempts/{attempt}/primary.*` plus optional `hls/`; exactly one primary; version-aware deletion of every object version, with tombstones/cleanup surviving late messages |
| Retention | Grant 15 min; signed output up to 900 s; standard queues 7 days/DLQs 14 days; standard visibility 420 s, short-work 960 s; logs 7 days; automated DB backups 1 day. Sources: `project-documentation/final-report/src/34-persistence-detailed.md`, retention table; `processing/short_lane.py`, queue visibility |
| Lifetime limits | Active content has no age-based purge; tombstones/outbox/inbox retained for deployment lifetime; final snapshot retained on teardown. No restore drill evidenced. Source: `project-documentation/final-report/src/34-persistence-detailed.md` |

**ONE recommended detailed use case for 4d: upload → encode → play (UC-1 through UC-3).** It traverses trust, bytes, transactions, messaging, scheduling, execution and read models; use it instead of explaining unrelated CRUD endpoints. Main source: `project-documentation/final-report/src/34-persistence-detailed.md`, Case 1.

| Phase | Concrete mechanism / class-module hook | Failure/invariant to explain |
|---|---|---|
| Authenticate/reserve | Gateway → `media.authorizer.authorize`; `direct_intake.reserve` returns scoped S3 POST | Trusted Actor, owner/request identity, bounded grant; caller cannot select another owner |
| Upload/finalize | Client POSTs to S3; `storage.verify_direct_upload` reads the exact version outside row locks; `direct_intake.finalize` commits pin + Asset + submit outbox | Wrong/missing bytes are not adopted; repeated finalize returns existing Asset; later overwrite cannot change the pin |
| Handoff/accept | MediaRepair publishes; ProcessingCommands calls `messaging.handle_command`: inbox + SubmissionGuard + Job/Attempt + work/result outbox | Local atomicity across each commit; duplicate message harmless; cancel-before-submit cannot resurrect work |
| Route/launch | `short_lane.work_lane` uses size only; eligible candidate reaches ShortEncoder through SQS. Lambda probes duration/height after claim/download; standard-lane work wakes SQL-reserving launcher/RunTask | Lambda admission failure uses fenced `redirect_to_long_lane`: abandon old Attempt, queue successor on Fargate. Stable RunTask identity protects ambiguous launch replies. Sources: `processing/short_lane.py`; `processing/messaging.py`; `processing/short_encoder.py` |
| Claim/encode/finish | `lifecycle.claim/finish`; shared `worker.tasks.pipeline`/`media_engine`; pinned download/hash, MP4, optional HLS; output then state/result commit before ACK | DB-clock lease/current-attempt fence; stale worker cannot finish. Ordinary worker failure becomes visible failure; owner retry reuses source. Admission redirect is a separate automatic successor path |
| Project/play | Processing publisher → MediaResults → `projections.apply_result`; owner read → `storage.sign_output` / `media/api/v1_hls.py` | Newer valid snapshots only; owner/source/output namespace checked; signed MP4 range response 206 and HLS segment redirect 307. Sources: `project-documentation/final-report/src/34-persistence-detailed.md`; `docs/architecture/views.md` §5 |

### (b) Hard numbers worth showing (measurements, not settings)

| Claim | Numbers and limitations | Source |
|---|---|---|
| Automatic finite capacity | 0 → 3 → 0; 9-clip backlog, 239 s, 2.26 jobs/min; fixed-cap run, no speedup comparison | `docs/results/actual-vs-target.md`, LV-7/LV-9 |
| Queue-wait trade-off | Standard lane about 37 s vs 20 s target; Fargate created-to-start median 25.6 s, n=12 | `docs/results/actual-vs-target.md`, LV-8 |
| Short-lane queue wait | 0.26 s vs 32.6 s Fargate; 5 jobs per arm, same 24 s clip streams but 2,523,463-byte vs 75,923,783-byte padded files | `docs/results/engineering-20261021/short-lane-sl1021.json`, scope/compare |
| Short-lane processing/end-to-end | Processing 5.3 vs 8.0 s. Reported submit-to-done: warm Lambda 45.2 s, cold 92.0 s (n=1), Fargate 87.7 s; 35-80 s unattributed. “Warm median” uses nearest-rank p50, see risk below | `project-documentation/final-report/src/40-quality.md`; `docs/results/engineering-20261021/short-lane-sl1021.json`; `scripts/aws/v1/proof/core.py`, percentile |
| Encode compute cost | USD 0.0003 vs 0.0021 per success; shared services excluded; not a platform bill | `docs/results/engineering-20261021/short-lane-sl1021.json`, cost_basis/compare |
| Interactive latency | Status p90 58.2 ms vs 700 ms, 9,000 requests/50 users/3 min, 0 errors; login p90 178 ms/20 samples | `docs/results/actual-vs-target.md`, PF-1/PF-3; in-region generator, not internet users |
| Recovery / cold resume | Worker-stop reaction 5.8 s vs 300 s; first database read 4.7 s after pause | `docs/results/actual-vs-target.md`, AV-1; `docs/architecture/decisions.md`, AD-12. Neither proves full recovery/restore or a resume SLA |
| Idle-cost planning | USD 3-5/month estimate; USD 20/month budget alerts at 50/80/100% | `docs/architecture/decisions.md`, AD-27. Estimate predates final split; budget alerts do not cap spend; actual bill unestablished |

### (c) Existing visuals to reuse

| Exact path | Reuse / simplification |
|---|---|
| `showcase-prep/assets/aws-topology.svg` | Best existing current physical overview; includes short Lambda and separate Aurora clusters. Raster copy: `project-documentation/final-report/figures/aws-topology.png`; structured source: `showcase-prep/content/aws-map.json`. Use overview then zoom into network/executors; move supporting-service strip to notes. Show separate short-work lane and clarify that SNS here covers budget notifications, not service paging. |
| `docs/architecture/img/views-physical.svg` | Dense engineering backup; includes split clusters but still baseline booked-session labels and no short encoder. Do not use unchanged as current deployment. |
| `docs/architecture/img/views-er-media.svg`; `docs/architecture/img/views-er-processing.svg` | Canonical vector table views; PNGs at `project-documentation/final-report/figures/views-er-media.png` and `project-documentation/final-report/figures/views-er-processing.png`. Too dense together; main slide shows Asset/pin/projection vs Job/Attempt/lease, each with outbox/inbox; full ERs in backup. |
| `project-documentation/final-report/figures/report-seq-intake.png` | Use phase crop/rebuild; long endpoint labels wrap awkwardly. Show reserve, S3 upload, verify, atomic adopt/outbox; source `project-documentation/final-report/figures/src/report-seq-intake.mmd`. |
| `project-documentation/final-report/figures/report-seq-encode.png` | Dense even at full screen; split handoff/dispatch from claim/finish. Existing yellow short-lane note is an annotation, not a fully drawn branch; draw queue → Lambda admission and fallback separately. Source `project-documentation/final-report/figures/src/report-seq-encode.mmd`. |
| `project-documentation/final-report/figures/report-seq-play.png` | Separate result projection from playback arrows; retain owner check and direct signed S3 bytes. Source `project-documentation/final-report/figures/src/report-seq-play.mmd`. |
| `docs/architecture/img/views-sequence.svg` | Entire long baseline sequence is too dense and operator-started; backup only. Also `project-documentation/final-report/figures/use-case-design-06-implemented-sequence-uc-1-uc-3-upload-process-and-play.png` is too wide/dense for a main slide. |

### (d) What is distinctive

- Low-idle-cost design includes the network and repair behaviour, not merely Lambda: NAT avoidance, finite tasks, paused SQL, activity markers and cleanup backoff. Sources: AD-18/AD-27; `project-documentation/final-report/src/60-other.md`, lessons.
- Two execution adapters reuse the same domain/lease pipeline; size is the cheap routing filter, executor probe makes the final admission decision, and fallback cannot ping-pong. Sources: `processing/short_lane.py`; `processing/messaging.py:redirect_to_long_lane`.
- Database independence was strengthened after logical ownership: snapshot, idle check, copy-on-write clone, credential switch, public smoke, then peer-DB cleanup. Source: AD-29; `docs/results/engineering-20261021/database-split-rehearsal.json`.

### (e) Likely examiner questions

| Question | Crisp answer grounded in sources |
|---|---|
| Why Fargate and Lambda rather than one encoder runtime? | Short bounded work avoids task startup on Lambda; longer/larger/taller sources use finite Fargate tasks. Both call the same leased execution pipeline, so this is an adapter choice inside Processing. `processing/short_lane.py`; `project-documentation/final-report/src/32-physical.md`, AD-13. |
| Does the launcher probe the clip? | No: dispatch knows source size only. The short executor claims/downloads/probes, then either encodes or performs a fenced successor transition to the standard lane; repeat Lambda use for that job is prevented. `processing/short_lane.py`; `processing/messaging.py:redirect_to_long_lane`. |
| How can a source remain immutable while a grant is unexpired? | Finalize adopts a specific S3 VersionId after checking stored size/hash/signature. A replayed upload creates another version; it cannot change the accepted pin. `media/services/storage.py:verify_direct_upload`; `media/services/direct_intake.py`. |
| Why is an encoder on a public subnet safe? | It needs outbound access to pull images/reach managed endpoints; its security group has no inbound rules and SQL remains private. A temporary public address is not an application listener. `docs/architecture/views.md` §§3.1/3.4. |
| How do private Lambdas reach AWS without NAT? | Dual-stack endpoints use IPv6 egress-only routing, with an S3 gateway endpoint for object access. This reduces fixed network cost but requires compatible endpoint paths; the smoke verifies the workflow, not every route independently. AD-18 in `docs/architecture/decisions.md`. |
| Why split the Aurora cluster, and is it HA? | Separate roles protected ownership but not shared capacity/failure. Media retains the original cluster and Processing uses its clone; each is still a single database instance in one region, and public authorization remains shared. AD-29; `media/authorizer.py`; `project-documentation/final-report/src/40-quality.md`, Availability. |
| What happens if a worker dies or a result is late? | Lease/deadline recovery marks the attempt abandoned and the job failed; the owner retries against the retained source. Late finish/result is fenced, while the AWS duplicate-output recovery criterion remains unestablished. `processing/recovery.py`; AISS-05. |
| Why is playback not simply CloudFront-cached video? | CloudFront serves static frontend and forwards API requests; Media checks ownership and returns temporary S3 capabilities. HLS playlists are private/uncached and segments redirect to signed S3 reads. AD-15; `media/api/v1_hls.py`. |
| Did the short lane solve performance and cost? | It improved measured queue wait and billed compute for the tested clip, while cold end-to-end comparison failed and total latency remains too high. The receipt excludes shared services and uses a larger padded Fargate input, so it is not an equal-byte CPU benchmark or monthly-cost proof. `docs/results/engineering-20261021/short-lane-sl1021.json`, scope/limits. |
| What happens if SQS loses a work item? | SQL owns queued attempts and retained send intentions; repair reconstructs work. The cloud lost-entry timing bound is not measured, and idle-marker failure can delay discovery beyond the ordinary repair interval. AD-27; `processing/recovery_v1.py`; AISS-05. |

### (f) Risks / disagreements to carry into slide notes

| Risk | Conflicting paths / precise treatment |
|---|---|
| Baseline counts copied as live counts | `docs/architecture/views.md` tables describe 9 functions, shared-cluster defaults and 3 queues/DLQs; `32-physical.md` reports 4 Media + 7 Processing functions but still 3 queues/DLQs and 13 alarms. `scripts/aws/v1/definitions.py` defines enabled short-work queue/DLQ plus launcher/short-encoder error alarms: **11 functions, 4 work/command/result queues + 4 DLQs, 15 configured alarms** with both flags enabled. This is a source-derived count, not a fresh AWS inventory. |
| Baseline visibility/total concurrency | `34-persistence-detailed.md` gives queue visibility 420 s without a short-lane exception; `processing/short_lane.py` sets short-work to 960 s. Fargate cap 3 plus short mapping cap 2 gives configured combined encoder ceiling 5, not a global cap 3 (`COMBINED_ENCODER_CAP`); invocation availability is not guaranteed by those caps. |
| Wrong admission location | `showcase-prep/content/aws.json`, “Short-lane routing,” says launcher probes length/height; `architecture.json`, `code.json` and `processing/short_lane.py` correctly distinguish size dispatch from executor probe. Use the latter explanation. |
| Automatic retry wording | `docs/execution/aws/v2/lambda-short-encodes.md`, Interruption, says timeout recovery queues a successor. `processing/recovery.py:interrupt/recover_expired` instead marks failed/abandoned without automatic requeue; owner retry later routes to Fargate. Automatic successor creation is the explicit admission redirect in `processing/messaging.py:redirect_to_long_lane`. |
| Isolation overstatement | `40-quality.md` and AD-29 wording imply a database outage no longer affects the peer. Separate clusters isolate SQL capacity, but `media/authorizer.py` fails closed when its Media user lookup fails: protected Processing APIs still depend on that lookup. Background execution and public API availability are different claims. |
| Quotas are dated | `32-physical.md`/AD-10 and `processing/short_lane.py` retain account concurrency 10; `docs/execution/aws/v2/lambda-short-encodes.md`, Concurrency update, records 1000 on 21 Oct, with mapping cap unchanged. AD-13's old Fargate quota is 6 vCPU; AD-27 records 30 vCPU. Present configured caps, not either historical quota as freshly current. |
| Short-lane benchmark is not an unconditional pass | `short-lane-sl1021.json` records `meets_keep_rule=false`, `lambda_cold_median_lower=false`, `merge_decision=pending`; `docs/execution/aws/v2/lambda-short-encodes.md` explicitly says it stays enabled on persistent live despite that strict per-run keep-rule miss. Show queue-wait/compute improvement alongside the failed cold comparison. |
| “Median” convention | `short-lane-sl1021.json` reports warm p50 45.23 s for 4 samples rounded as 45.2/38.5/88.1/60.0. `scripts/aws/v1/proof/core.py:percentile` uses nearest rank; the usual midpoint median of those rounded samples is 52.6 s. Label 45.2 s **reported nearest-rank p50**, not a recomputed conventional median; do not silently change the report value. |
| Queue wait versus total latency | `40-quality.md` explicitly calls 20 s end-to-end an aim with no proposal target; `36-other-limitations.md`/site shorthand can sound like the original proposal target. The 20 s queue-wait comparison and the 20 s end-to-end aim have different timing boundaries. `actual-vs-target.md` retains both historical and later lane rows despite its old “Last updated” line. |
| No bytes through Lambda is overbroad | `40-quality.md` and site shorthand should mean the **client upload/playback is not proxied through the public API**. `media/services/storage.py:verify_direct_upload` streams source bytes inside Media for verification; `processing/short_encoder.py` also handles media bytes. Avoid the literal claim that Lambda never reads a video. |
| Idle estimate and pause proof | AD-27's USD 3-5/month is a model, not a bill; it predates the extra cluster. `actual-vs-target.md` LV-12 is a pre-split, point-in-time 0-ACU observation, not proof both current clusters stay paused or monthly spend is negligible. AISS-05 keeps actual spend open. |
| Repair bound has a failure caveat | AD-27 in `decisions.md` records a lost activity-marker write potentially delaying SQL discovery up to 30 minutes plus tick/invocation time. The 120 s lost-entry comparison assumes healthy markers and is not measured on AWS. Do not promise unconditional recovery within that bound. |
| Current drawing versus proof | `showcase-prep/assets/aws-topology.svg` is the best current design picture; `views-physical.svg` retains baseline omissions; `database-split-rehearsal.json` proves a disposable rehearsal, not itself the live split. The report/site identify live CD `39644028238`; no live read-back was performed for this research. |

## Proposed “remember us for this” themes

- **A real application became a reusable capability:** inherited engine, independent client, explicit ownership and honest scope. Sources: `project-documentation/final-report/src/10-introduction.md`; `30-logical.md`.
- **Correctness lives at the boundaries:** immutable source pin; local state + outbox; inbox/version/lease fences; owner-authorized projection/playback. Sources: `docs/architecture/ddd.md`; `project-documentation/final-report/src/34-persistence-detailed.md`.
- **Idle cost and latency were designed and measured together:** no NAT, finite workers, pausing databases, bounded Lambda lane, and visible latency misses. Sources: AD-18/AD-27/AD-29; `docs/results/engineering-20261021/short-lane-sl1021.json`.
- **Independence is enforced, with remaining coupling stated:** owned data/images/roles/releases and build checks, alongside shared authorizer/contracts/stack and image-only rollback. Sources: `project-documentation/final-report/src/30-logical.md`; `32-physical.md`; `36-other-limitations.md`.
- **Claims carry receipts and limits:** compare unchanged targets, distinguish workload/mode/source, retain failures and NOT_RUN evidence. Sources: `docs/results/actual-vs-target.md`; `project-documentation/final-report/src/40-quality.md`.

## Proposed slide count and pacing

Counts and internal pacing below are editorial recommendations; official talk/Q&A budgets are from `project-documentation/presentation/ROAD-TO-PRESENTATION.md`. Progressive builds count as one slide; keep optional technical detail in backup.

| Section | Main slides | Suggested content / talk pacing | Backup slides |
|---|---|---|---|
| 1 Overview | 3 | Person/problem + platform roles (45 s); inherited → added scope (45 s); reusable-client proof/exclusions (30 s) | 1 scope/use-case view |
| 2 Conduct | 2 | Actual milestone/effort strip (50 s); status and issue classes (40 s) | 2: effort detail; AISS/evidence status |
| 3 Logical | 6 | Boundary/decision (60 s); layered logical deployment (75 s); aggregates/language (75 s); context map/outbox/inbox (90 s); projections/fences (60 s); producers/consumers (60 s) | 3: state machine; contract compatibility; detailed context map |
| 4 Physical | 7 | Current topology/decisions (60 s); network/executor placement (60 s); owned persistence (60 s); intake sequence (60 s); encoding/admission/fences (75 s); projection/playback (45 s); measured trade-off/limits (60 s) | 4: ERs; routing/recovery detail; benchmark method; split/retention/limits |

- Recommended main total for these sections: **18 slides / 17.5 talk minutes**, plus **5.5 Q&A minutes**, reaching the end of section 4 at **23:00**. Remaining official allocation is **17 minutes** for DevOps and demo, including their questions. Sources for budget arithmetic: `project-documentation/presentation/ROAD-TO-PRESENTATION.md`; slide counts/pacing are proposals above.
