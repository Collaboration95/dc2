# Project Conduct

## Project Plan

The briefing expects about 10 person-days (pd) per participant. The proposal (§4.1) estimated
**31 pd** for three members across ten work packages (WBS), each with a lead member. Project
Metrics gives the effort per member against these estimates.

| # | Work package | Lead | Estimate (pd) |
|:--|:--------------------------------------------------------------|:------------|------:|
| 1 | Freeze baseline, reproducible local setup, fix the inherited scan finding | Guruprasath | 2 |
| 2 | Domain analysis, service contracts and OpenAPI documents | Long (team review) | 3 |
| 3 | Extract Processing: service, own database and migrations, workers and recovery task | Ibrahim | 6 |
| 4 | Adapt Media Management: asset records, Processing client, web app routes and retry | Ibrahim | 3 |
| 5 | Boundary security: identity, owner checks, database roles, presigned URLs, negative tests | Guruprasath | 3 |
| 6 | Publisher CLI and contract tests | Long | 2 |
| 7 | AWS environment, per-service deployment, pipeline updates, smoke test | Guruprasath | 4 |
| 8 | Experiments: scaling, load, recovery and playback; raw results | Long | 3 |
| 9 | Integration fixes and repeat checks | All | 2 |
| 10 | Presentation and final report | All | 3 |
| | **Total** | | **31** |

### Responsibility for analysis and design

Each use case's **analysis and design**, and each design problem, has one responsible member,
following the team's three specialisms.

| Item | Analysis and design responsibility |
|:---|:---|
| UC-1 Register, log in and upload an owned video | Ibrahim Mammadov |
| UC-2 Process the video into playable outputs | Ibrahim Mammadov |
| UC-3 Track status and play the result | Nguyễn Kim Long |
| UC-4 Retry from the stored source | Ibrahim Mammadov |
| UC-5 Bulk-publish a folder and report results | Nguyễn Kim Long |
| UC-6 Scale processing capacity independently | Guruprasath Gopal |
| UC-7 Release Processing on its own and demonstrate rollback | Guruprasath Gopal |
| DP-1 Bounded cloud capacity and safe per-owner release | Guruprasath Gopal |
| DP-2 Durable asynchronous Processing handoff | Ibrahim Mammadov |
| DP-3 Trusted owner identity and reusable public contract | Nguyễn Kim Long |

### Product backlog

[GitHub Project 14](https://github.com/users/Collaboration95/projects/14) holds the delivery
backlog. Each issue states an outcome, acceptance criteria and verification; the local contracts
are also kept in `docs/execution/backlog.json` and the versioned AWS backlog directories. On
10 November the board held **118 items: 111 Done, 6 Todo and 1 In Progress**.

| Field | Values and purpose |
|:---|:---|
| Workflow | Backlog, Ready, In progress, Review, Blocked, Done; authoritative delivery state |
| Wave | Wave 0–4; dependency order for local delivery, followed by AWS bundles and close-out |
| Priority | P0, P1, P2; implementation ordering |
| Persona | Maya, Arun, Jules, Sam, or combinations; intended beneficiary |
| Risk / Area / Sequence | Delivery risk, affected component and execution order |
| Status | GitHub's Todo / In Progress / Done summary |

The Wave field orders the work, and the iterations below give it a calendar. The epic index is:

| Delivery group | Epics and acceptance focus |
|:---|:---|
| Local baseline and integration | [E0 #1](https://github.com/Collaboration95/dc2/issues/1) reviewed plan; [E1 #2](https://github.com/Collaboration95/dc2/issues/2) reproducible workspace; [E2 #3](https://github.com/Collaboration95/dc2/issues/3) Processing; [E3 #4](https://github.com/Collaboration95/dc2/issues/4) Media; [E4 #5](https://github.com/Collaboration95/dc2/issues/5) web/Publisher; [E5 #6](https://github.com/Collaboration95/dc2/issues/6) integrated evidence |
| Required AWS V1 | [#41](https://github.com/Collaboration95/dc2/issues/41) domain APIs and S3 intake; [#42](https://github.com/Collaboration95/dc2/issues/42) managed runtime and budget; [#43](https://github.com/Collaboration95/dc2/issues/43) Redis-free delivery and releases; [#44](https://github.com/Collaboration95/dc2/issues/44) acceptance and immutable baseline |
| Close-out | [#178](https://github.com/Collaboration95/dc2/issues/178) visible pipeline; [#179](https://github.com/Collaboration95/dc2/issues/179) cloud proof; [#180](https://github.com/Collaboration95/dc2/issues/180) as-built documentation; [#181](https://github.com/Collaboration95/dc2/issues/181) presentation/report; [#195](https://github.com/Collaboration95/dc2/issues/195) microservice hardening |
| Persistent demonstration environment | [#234](https://github.com/Collaboration95/dc2/issues/234) always-on in-place delivery and scale-to-zero, with #235–#238 for supporting delivery and verification |
| Measured improvements | [E6 #33](https://github.com/Collaboration95/dc2/issues/33) performance experiments; [#159](https://github.com/Collaboration95/dc2/issues/159) selective CI and full verification |
| Optional experiments | [#80](https://github.com/Collaboration95/dc2/issues/80) optional migrations (closed as not planned); [#68](https://github.com/Collaboration95/dc2/issues/68) launcher task, adopted into V2-live |

### User stories

The stories come from the backlog and the planning personas in
`project-roadmap/business-scope.json`. Section 6.2 describes the use cases and section 6.4 gives
the detailed models.

| Use case | Persona story | Backlog link |
|:---|:---|:---|
| UC-1 | As a content owner (Arun), I want to register, log in and upload my video, so that I can prepare my own content for playback. | Media [#15](https://github.com/Collaboration95/dc2/issues/15), epic [#4](https://github.com/Collaboration95/dc2/issues/4) |
| UC-2 | As a content owner (Arun), I want the platform to convert my video to playable outputs, so that I can use it without running a converter myself. | Processing [#13](https://github.com/Collaboration95/dc2/issues/13), epic [#3](https://github.com/Collaboration95/dc2/issues/3) |
| UC-3 | As a course coordinator (Maya), I want to follow status and play my completed recordings, so that I can check each result while keeping access restricted to my account. | Media [#16](https://github.com/Collaboration95/dc2/issues/16), epic [#4](https://github.com/Collaboration95/dc2/issues/4) |
| UC-4 | As a content owner (Arun), I want to retry a failed encode from its stored source, so that I can recover without uploading the video again. | Media [#16](https://github.com/Collaboration95/dc2/issues/16), browser retry [#19](https://github.com/Collaboration95/dc2/issues/19) |
| UC-5 | As a course coordinator (Maya), I want to bulk-publish a folder and receive an outcome for every file, so that I can prepare a course's recordings with one command; Jules integrates this workflow through the published API. | Publisher [#18](https://github.com/Collaboration95/dc2/issues/18), epic [#5](https://github.com/Collaboration95/dc2/issues/5) |
| UC-6 | As a platform operator (Sam), I want to change Processing capacity independently, so that a backlog can be handled without scaling or redeploying Media. | Scaling [#22](https://github.com/Collaboration95/dc2/issues/22), launcher [#68](https://github.com/Collaboration95/dc2/issues/68) |
| UC-7 | As a platform operator (Sam), I want to release Processing separately and restore a failed candidate, so that I can change it while preserving Media's release. | Release [#23](https://github.com/Collaboration95/dc2/issues/23), pipeline epic [#178](https://github.com/Collaboration95/dc2/issues/178) |

### Iterations and sprint plans

The team delivered in five iterations that follow the proposal schedule (§4.2) and the delivery
waves. The sprint plans, reviews and retrospectives below are compiled from the dated worklog
(`docs/project2-worklog.txt`), review records, release manifest and issue register. Figure
{@fig:conduct-iteration-plan} shows the plan.

![Figure {#fig:conduct-iteration-plan}. Iteration plan: windows, proposal work packages and leads, with the main milestones.](figures/conduct-iteration-plan.png){width=15cm}

| Iteration | Goal | Committed issues and epics | Outcome |
|:---|:---|:---|:---|
| 1 Baseline and domain, 5–9 Oct | Freeze the baseline, define ownership boundaries and agree the seven use cases | WBS 1–2; decisions F-01 and D-01–D-07; later tracked by epics [#1](https://github.com/Collaboration95/dc2/issues/1) and [#7](https://github.com/Collaboration95/dc2/issues/7) | Baseline and domain/design pack completed 7–9 Oct; personas, contracts and build preparation ready |
| 2 Local services, 10–14 Oct | Deliver the independently owned services, the browser flow and an API-only Publisher, verified locally | E0–E5 (#1–#6); foundation #9–#11, Processing #12–#14, Media #15–#17, clients #18–#19, verification #20–#24 | Processing 12 Oct; Media and Publisher 13 Oct; integrated local workflow, fault, release and experiment evidence to 14 Oct |
| 3 AWS delivery, 15–20 Oct | Deploy both services on AWS, prove security and independent operations, freeze a demonstration release | V1 #41–#44; cloud proof #63–#67; close-out #178–#180; hardening #195; audit [#258](https://github.com/Collaboration95/dc2/issues/258); manifest #255 | Cloud proofs `r1017b`, `r1018b`, `r1019a`; `project2-v1` and `dc2-live` 18 Oct; CI/CD; security, scaling and rollback evidence; freeze 20 Oct |
| 4 Hardening and presentation, 21–26 Oct | Resolve release blockers, record the workflows and present | Presentation #192, recordings #254; repairs #285/#287 via PRs #286/#288; short lane #93 and per-service databases #94 | Verified repair `c7c489c` 21 Oct; short lane and database split 21–22 Oct; D1–D5 recorded; presented 26 Oct |
| 5 Feedback and report, 27 Oct–16 Nov | Incorporate the presentation feedback and complete the final report | Report [#193](https://github.com/Collaboration95/dc2/issues/193), epic #181, effort #191, recordings #254, course checks #257 | W1–W6 feedback packets and report v1.1, submitted for 16 Nov |

| Iteration | Review: increment and evidence | Went well | Improvement and action |
|:---|:---|:---|:---|
| 1 | Decision record of 9 Oct: frozen baseline accepted; lecturer asked for detailed domain analysis | Domain and contract decisions gave implementation a shared starting point | Carry acceptance and environment prerequisites into executable issue contracts; Wave 0 planning review (`docs/execution/reviews/planning-rereview.md`) |
| 2 | PRs [#28](https://github.com/Collaboration95/dc2/pull/28)–[#30](https://github.com/Collaboration95/dc2/pull/30); mixed batch of 30 valid files plus one refusal and a stored-source retry; experiment review of 14 Oct | Separate service branches and public-contract tests made integration straightforward | Preserve request identity and fence delayed responses when users change assets or sessions; client regressions kept (`clients-fixes.md`) |
| 3 | PR [#194](https://github.com/Collaboration95/dc2/pull/194) V1 acceptance baseline; audit #258; PR [#278](https://github.com/Collaboration95/dc2/pull/278) freeze and effort ledger | Cloud receipts tied each operational claim to its environment and source | Test duplicate messages, idle database behaviour and deployment scripts as operating behaviours; #270/#272 drain re-test, #273 idle fix, #265/#267 pipeline regressions |
| 4 | PRs [#286](https://github.com/Collaboration95/dc2/pull/286), [#288](https://github.com/Collaboration95/dc2/pull/288) and CD run [39545554380](https://github.com/Collaboration95/dc2/actions/runs/39545554380); D1–D5 clips; feedback of 26 Oct | A frozen baseline and recorded workflows made the presentation repeatable | Show object responsibilities, lane selection and security tools in diagrams; carried into the W1–W6 packets |
| 5 | Feedback mapped in `feedback-20261026/REPORT-CHANGES.md`; response in section 6.1 | Retained source, receipts and feedback made the revision traceable | Keep issue bookkeeping in step with delivery; close tracking issues at submission |

### Burndown, burnup and issue reduction

Figures {@fig:conduct-overall-issues} to {@fig:conduct-issue-reduction} are derived from GitHub
issue timestamps captured on **10 November 2026 at 23:15 SGT**. The register holds 156 issues:
137 tasks and 19 parent epics. Counts use each issue's creation time and latest closure time.

![Figure {#fig:conduct-overall-issues}. Overall burnup: issues registered (scope) against issues closed, with iteration windows shaded. The gap between the lines is the open work.](figures/conduct-overall-issues.png){width=15cm}

![Figure {#fig:conduct-iteration-burndown}. Per-iteration burndown: issues registered and closed in each iteration, and issues open at its end. Iteration 5 is counted to 10 November.](figures/conduct-iteration-burndown.png){width=15cm}

![Figure {#fig:conduct-issue-reduction}. Issue reduction: open tasks and open parent epics over time. Seven remain open on 10 November.](figures/conduct-issue-reduction.png){width=15cm}

Issues were registered from 13 October, once the wave plan existed, so Iteration 1 work appears
under its later planning epics. Scope peaked during the AWS iteration, when 126 issues were
registered and 117 closed. The seven open records are tracking issues for the presentation and
report (#181, #191, #192, #193), recordings (#254), course checks (#257) and the audit index
(#258). The data is in [conduct-issues.csv](data/conduct-issues.csv) and
[conduct-daily-issues.csv](data/conduct-daily-issues.csv); `python tools/conduct_burndown.py`
regenerates the four figures, and `--refresh` captures a new snapshot through `gh`.

## Project Status

Report v1.1 is submitted for **16 November 2026**. All seven use cases are implemented and the
release is frozen; status data was captured on 10 November.

| Area | Status |
|:---|:---|
| Implementation | UC-1 to UC-7 implemented; tests and dated local and AWS experiments indexed in `docs/evidence-index.md`. |
| Release freeze | Demo freeze accepted 20 October at `daee44b`; `project2-v1` is immutable. Later engineering deliveries have their own verification addenda in `docs/release/demo-release-manifest.md`. |
| Live demonstration | `dc2-live` runs with finite standard encoders and separate short-lane admission. On 10 November the frontend, Media health and Processing health returned 200; these are liveness checks, and the health endpoints neither query nor wake Aurora, so they do not establish database readiness. |
| Presentation and report | Presented 26 October. v1.1 adds the requested DDD, deployment, component, schema, analysis/design and pipeline views; section 6.1 maps each remark to its response. |
| CI | The scheduled run on Main at `76282d3` passed on 1 November ([41294802851](https://github.com/Collaboration95/dc2/actions/runs/41294802851)). The scheduled run of 8 November ([42468024855](https://github.com/Collaboration95/dc2/actions/runs/42468024855)) failed in its tool-installation and image-scan steps. |
| Outstanding | Rerun scheduled CI after the tool-installation failure; close the seven tracking issues at submission; tear down `dc2-live` once after 16 November. Open measurement items are in section 3.4 (AISS-05). |

Status is tracked in the effort ledger (`project-documentation/effort-ledger.md`, issue #191) and
GitHub Project 14. The measured quality results are in section 4.

## Project Metrics

### Milestones planned against actual

| Planned (proposal §4.2) | Milestone | Actual | Evidence |
|:---|:---|:---|:---|
| 4 Oct | Proposal | Submitted 4 Oct | `Team17-Proposal.docx` |
| 5–7 Oct | Baseline, domain/contracts and lecturer review | Completed 7–9 Oct | `project-roadmap/records/project-decisions.txt` |
| 8–14 Oct | Local Processing, Media, web and Publisher | Processing 12 Oct; Media/Publisher 13 Oct; integrated evidence 14 Oct | PRs #28–#32; worklog |
| 15–20 Oct | Security, AWS, pipeline and experiments | AWS tooling 15 Oct; cloud proofs 17–18 Oct; `project2-v1` and `dc2-live` 18 Oct; CD 18–19 Oct; freeze 20 Oct | Evidence index; PR #278; release manifest |
| 21–25 Oct | Hardening and presentation preparation | Verified repair 21 Oct; short lane and database split 21–22 Oct; clips recorded 23 Oct | Engineering receipts; release addendum |
| 26 Oct | Team 17 presentation | Presented 26 Oct; feedback recorded the same day | `presentation/feedback-20261026/FEEDBACK.md` |
| 27 Oct–16 Nov | Feedback revision and final report | Report v1.1 submitted for 16 Nov | Section 6.1; report sources; #193 |

Baseline and design finished on 9 October, two days after the proposal's window. Every later
milestone landed within its planned window.

### Effort per member

Team 17 was formed with the professor's special permission as a team different from the Project 1
teams, so these figures cover Project 2 only. Estimates come from the proposal WBS (§4.1), with
each package assigned to its lead and shared packages split evenly. Actual hours follow the work
allocation in the team's effort ledger (#191). One person-day is 8 hours.

| Member | # | Work package | Estimated hours | Actual (rough, team-agreed) hours |
|:---|:--|:---|---:|---:|
| Guruprasath Gopal | 1 | Baseline, setup and inherited scan fix | 16 | 14 |
| | 2 | Domain, contracts and OpenAPI (review) | 0 | 2 |
| | 5 | Boundary security | 24 | 5 |
| | 7 | AWS environment, CI/CD pipeline and smoke test | 32 | 46 |
| | 8 | Experiments (cloud runs) | 0 | 3 |
| | 9 | Integration fixes and repeat checks | 5 | 12 |
| | 10 | Presentation and final report | 8 | 14 |
| | 11 | Release freeze and evidence index | 0 | 1 |
| Ibrahim Mammadov | 1 | Baseline, setup and inherited scan fix | 0 | 2 |
| | 2 | Domain, contracts and OpenAPI (review) | 0 | 2 |
| | 3 | Processing extraction | 48 | 36 |
| | 4 | Media adaptation | 24 | 22 |
| | 5 | Boundary security | 0 | 13 |
| | 7 | AWS environment (service images) | 0 | 2 |
| | 9 | Integration fixes and repeat checks | 5 | 4 |
| | 10 | Presentation and final report | 8 | 14 |
| Nguyễn Kim Long | 2 | Domain, contracts and OpenAPI | 24 | 22 |
| | 3 | Processing extraction (contract review) | 0 | 2 |
| | 4 | Media adaptation (contract review) | 0 | 2 |
| | 6 | Publisher CLI and contract tests | 16 | 16 |
| | 8 | Scaling, recovery and playback experiments | 24 | 22 |
| | 9 | Integration fixes and repeat checks | 6 | 8 |
| | 10 | Presentation and final report | 8 | 17 |
| | 11 | Release freeze and evidence index | 0 | 7 |
| **Guruprasath Gopal total** | | | **85** | **97** |
| **Ibrahim Mammadov total** | | | **85** | **95** |
| **Nguyễn Kim Long total** | | | **78** | **96** |
| **Team total** | | | **248 (31 pd)** | **288 (36 pd)** |
| **Team average per member** | | | **82.7** | **96.0** |

The team spent about 16% more than the estimate. Work package 7 grew because the CD workflow
(#178) was added on 18–19 October, and package 10 grew with the feedback revision of the report.
Boundary security moved from Guruprasath to Ibrahim, next to the service code it protects, and
package 11 (release freeze and evidence index) was added after the proposal.

### Delivery and verification counts

Repository and Project counts were refreshed through `gh` on **10 November 2026**; the snapshot,
board items and PR records are under `data/conduct-*`. Overlapping test suites are not summed.

| Metric | Value and evidence |
|:---|:---|
| Issues | **156 total: 149 closed, 7 open**; 137 tasks and 19 parent epics |
| Pull requests | **173 total: 164 merged, 5 closed unmerged, 4 open** |
| Project 14 | **118 items: 111 Done, 6 Todo, 1 In Progress** |
| Python fast suite | **2,986 passed, 3 skipped, 278 subtests** in the scheduled 1 Nov CI run at `76282d3`; real integrations passed 44 inherited, 47 Processing and 39 Media tests |
| V1 operational checks | **1,520 passed** in the 1 Nov offline control-plane job |
| Frontend | **177 passed** in the same 1 Nov CI run |
| Complete local regression | **3,697 Python tests plus 177 frontend tests passed**, 20 Oct validation at `514914a` |
| Coverage | Media 93.91%, Processing 93.90% combined statement/branch coverage; frontend statements 96.24% (`docs/results/engineering-20261020/local-validation-514914a.json`) |
