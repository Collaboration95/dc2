# Project Conduct

## Project Plan

The briefing expects about 10 person-days (pd) per participant. The submitted proposal estimated
**31 pd** for three members across ten work packages (WBS). Each package had a lead member
(proposal §4.1). The table retains those planned leads; the agreed effort allocation appears
under Project Metrics.

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
| 10 | Progress report, presentation and final report | All | 3 |
| | **Total** | | **31** |

### Responsibility for analysis and design

The following allocation names the person responsible for each use case's **analysis and design**
and each design problem. It follows the team's three specialisms.

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

[GitHub Project 14](https://github.com/users/Collaboration95/projects/14) holds the delivery backlog.
Issues specify an outcome, acceptance criteria and verification. The retained local contracts are
in `docs/execution/backlog.json` and the versioned AWS backlog directories. At the 10 November
snapshot the board contains **118 items: 111 Done, 6 Todo and 1 In Progress**.

| Field | Values and purpose |
|:---|:---|
| Workflow | Backlog, Ready, In progress, Review, Blocked, Done; authoritative delivery state |
| Wave | Wave 0–4; dependency order for local delivery, followed by AWS bundles and close-out |
| Priority | P0, P1, P2; implementation ordering |
| Persona | Maya, Arun, Jules, Sam, or combinations; intended beneficiary |
| Risk / Area / Sequence | Delivery risk, affected component and execution order |
| Status | GitHub's Todo / In Progress / Done summary |

The Wave field orders work; the reporting iterations below give it a calendar context. The board
has no dated sprint or story-point field. The compact epic index is:

| Delivery group | Epics and acceptance focus |
|:---|:---|
| Local baseline and integration | [E0 #1](https://github.com/Collaboration95/dc2/issues/1) reviewed plan; [E1 #2](https://github.com/Collaboration95/dc2/issues/2) reproducible workspace; [E2 #3](https://github.com/Collaboration95/dc2/issues/3) Processing; [E3 #4](https://github.com/Collaboration95/dc2/issues/4) Media; [E4 #5](https://github.com/Collaboration95/dc2/issues/5) web/Publisher; [E5 #6](https://github.com/Collaboration95/dc2/issues/6) integrated evidence |
| Required AWS V1 | [#41](https://github.com/Collaboration95/dc2/issues/41) domain APIs and S3 intake; [#42](https://github.com/Collaboration95/dc2/issues/42) managed runtime and budget; [#43](https://github.com/Collaboration95/dc2/issues/43) Redis-free delivery and releases; [#44](https://github.com/Collaboration95/dc2/issues/44) acceptance and immutable baseline |
| Close-out | [#178](https://github.com/Collaboration95/dc2/issues/178) visible pipeline; [#179](https://github.com/Collaboration95/dc2/issues/179) cloud proof; [#180](https://github.com/Collaboration95/dc2/issues/180) as-built documentation; [#181](https://github.com/Collaboration95/dc2/issues/181) presentation/report; [#195](https://github.com/Collaboration95/dc2/issues/195) microservice hardening |
| Persistent demonstration environment | [#234](https://github.com/Collaboration95/dc2/issues/234) always-on in-place delivery and scale-to-zero; #235–#238 hold the supporting delivery and verification work. |
| Measured improvements | [E6 #33](https://github.com/Collaboration95/dc2/issues/33) performance experiments; [#159](https://github.com/Collaboration95/dc2/issues/159) selective CI and full verification. |
| Optional experiments | [#80](https://github.com/Collaboration95/dc2/issues/80) optional migrations; [#68](https://github.com/Collaboration95/dc2/issues/68) is the related launcher task, adopted into V2-live. #80 closed as not planned. |

### User stories

The following story index is derived from the backlog and the planning personas in
`project-roadmap/business-scope.json`; section 6.2 supplies the use-case descriptions and section
6.4 the detailed models.

| Use case | Persona story | Backlog link |
|:---|:---|:---|
| UC-1 | As a content owner (Arun), I want to register, log in and upload my video, so that I can prepare my own content for playback. | Media [#15](https://github.com/Collaboration95/dc2/issues/15), epic [#4](https://github.com/Collaboration95/dc2/issues/4) |
| UC-2 | As a content owner (Arun), I want the platform to convert my video to playable outputs, so that I can use it without running a converter myself. | Processing [#13](https://github.com/Collaboration95/dc2/issues/13), epic [#3](https://github.com/Collaboration95/dc2/issues/3) |
| UC-3 | As a course coordinator (Maya), I want to follow status and play my completed recordings, so that I can check each result while keeping access restricted to my account. | Media [#16](https://github.com/Collaboration95/dc2/issues/16), epic [#4](https://github.com/Collaboration95/dc2/issues/4) |
| UC-4 | As a content owner (Arun), I want to retry a failed encode from its stored source, so that I can recover without uploading the video again. | Media [#16](https://github.com/Collaboration95/dc2/issues/16), browser retry [#19](https://github.com/Collaboration95/dc2/issues/19) |
| UC-5 | As a course coordinator (Maya), I want to bulk-publish a folder and receive an outcome for every file, so that I can prepare a course's recordings with one command; Jules integrates this workflow through the published API. | Publisher [#18](https://github.com/Collaboration95/dc2/issues/18), epic [#5](https://github.com/Collaboration95/dc2/issues/5) |
| UC-6 | As a platform operator (Sam), I want to change Processing capacity independently, so that a backlog can be handled without scaling or redeploying Media. | Scaling [#22](https://github.com/Collaboration95/dc2/issues/22), launcher [#68](https://github.com/Collaboration95/dc2/issues/68) |
| UC-7 | As a platform operator (Sam), I want to release Processing separately and restore a failed candidate, so that I can change it while preserving Media's release. | Release [#23](https://github.com/Collaboration95/dc2/issues/23), pipeline epic [#178](https://github.com/Collaboration95/dc2/issues/178) |

### Iterations and sprint-plan summaries

Project 2 used delivery waves and phases rather than formally named sprints. These five iterations
summarise the proposal schedule, effort ledger and dated worklog. Their sprint-plan tables map
committed scope to issue/epic records, including issues registered after the work was planned.
Iteration 1 extends the proposal's 5–7 October baseline window to the recorded 9 October design
completion; Iteration 2 covers the remaining local-service work from 10–14 October. Iteration 4
combines the proposal's 21–25 October hardening period and 26 October presentation. Iteration 5
runs to the 16 November report deadline, with progress observed through 10 November.

The team's iteration review and retrospective notes below were prepared for v1.1 on 10 November
from `docs/project2-worklog.txt`, the retained review/fix and bug records, the effort ledger,
release manifest and presentation feedback. They record increments and lessons without asserting
past review meetings or attendees.

### Iteration 1 — Baseline and domain, 5–9 October

| Sprint-plan item | Plan and result |
|:---|:---|
| Goal | Freeze the inherited baseline, define ownership boundaries and agree the seven use cases. |
| Committed issues/epics | Proposal WBS 1–2; decisions F-01 and D-01–D-07. Later tracked by planning epic [#1](https://github.com/Collaboration95/dc2/issues/1) and [#7](https://github.com/Collaboration95/dc2/issues/7); no issues were registered during this window. |
| Outcome | Baseline and domain/design pack completed 7–9 October; personas, contracts and build preparation ready for implementation. |

**Review.** The 9 October roadmap/decision record captures the accepted frozen baseline and the
lecturer's request for detailed domain analysis. The prepared pack fed PR
[#25](https://github.com/Collaboration95/dc2/pull/25) in the next iteration.

**Retrospective.** Went well: domain and contract decisions gave implementation a shared starting
point. Improve: carry acceptance and environment prerequisites into executable issue contracts.
Action: use the Wave 0 planning review before the service waves (`docs/execution/reviews/planning-rereview.md`).

### Iteration 2 — Local services, 10–14 October

| Sprint-plan item | Plan and result |
|:---|:---|
| Goal | Deliver independently owned services, the browser flow and an API-only Publisher client, then verify locally. |
| Committed issues/epics | E0–E5 (#1–#6; linked in the epic index); foundation #9–#11, Processing #12–#14, Media #15–#17, clients #18–#19 and verification #20–#24, ordered as Wave 0–4. |
| Outcome | Processing landed 12 October; Media and Publisher 13 October. Integrated local workflow, fault, release and experiment evidence followed through 14 October. |

**Review.** PRs [#28](https://github.com/Collaboration95/dc2/pull/28),
[#29](https://github.com/Collaboration95/dc2/pull/29) and
[#30](https://github.com/Collaboration95/dc2/pull/30) accepted the service/client increments.
The worklog records a mixed batch of 30 valid files plus one refusal and stored-source retry;
`docs/execution/reviews/experiments-20261014-review.md` records the experiment review. These are local
results; AWS acceptance belongs to Iteration 3.

**Retrospective.** Went well: separate service branches and public-contract tests supported
integration. Improve: preserve request identity and fence delayed responses when users change
assets or sessions; the client review found these cases. Action: retain the client regressions and
source-pinned experiment receipts (`clients-fixes.md`, `clients-rereview.md` under the review directory).

### Iteration 3 — AWS delivery, 15–20 October

| Sprint-plan item | Plan and result |
|:---|:---|
| Goal | Deploy the two services on AWS, prove security and independent operations, and freeze an accepted demonstration release. |
| Committed issues/epics | V1 #41–#44; cloud proof #63–#67; close-out #178–#180; hardening #195; audit [#258](https://github.com/Collaboration95/dc2/issues/258) and release manifest #255. |
| Outcome | Cloud proof `r1017b`, then `r1018b`/`r1019a`; immutable `project2-v1` on 18 October; persistent `dc2-live` and CI/CD; security, scaling and rollback evidence; demo freeze accepted 20 October. |

**Review.** PR [#194](https://github.com/Collaboration95/dc2/pull/194) preserved the V1 acceptance
baseline. The 18 October audit #258 organised six defect handoffs and nine improvement handoffs.
PR [#278](https://github.com/Collaboration95/dc2/pull/278) recorded the 20 October freeze and effort
ledger. The release manifest separates accepted results, measured target misses and later addenda.

**Retrospective.** Went well: cloud receipts tied each operational claim to its environment and
source. Improve: test duplicate queue messages, quiet-state database behaviour and the deployment
scripts as operating behaviours. Action: retain the #270/#272 duplicate-drain re-test, #273
idle-backoff fix and #265/#267 pipeline regressions; archive final receipts through submission.

### Iteration 4 — Hardening and presentation, 21–26 October

| Sprint-plan item | Plan and result |
|:---|:---|
| Goal | Resolve release blockers, prepare demonstrable workflows and present the architecture and measured results. |
| Committed issues/epics | Presentation #192, recordings #254, audit #258; blocker repairs #285/#287 through PRs #286/#288; optional short-lane/database experiments #93/#94 after V1 acceptance. |
| Outcome | Verified repair delivery `c7c489c` on 21 October; short-encode and per-service database delivery on 21–22 October; D1–D5 recorded for the presentation; Team 17 presented on 26 October. |

**Review.** PRs [#286](https://github.com/Collaboration95/dc2/pull/286) and
[#288](https://github.com/Collaboration95/dc2/pull/288) and CD run
[39545554380](https://github.com/Collaboration95/dc2/actions/runs/39545554380) record the repair.
The D1–D5 clips and `feedback-20261026/FEEDBACK.md` establish the demonstration material and
26 October presentation feedback. The feedback asked for richer DDD, deployment, component,
schema and pipeline views.

**Retrospective.** Went well: a frozen baseline and recorded workflows supported a repeatable
presentation. Improve: make object responsibilities, lane selection and security tools visible in
the report's diagrams. Action: carry the feedback into the reviewed W1–W6 source packets and v1.1
report models. Keep release-addendum verification distinct from a new team freeze.

### Iteration 5 — Feedback and report, 27 October–16 November

| Sprint-plan item | Plan and result |
|:---|:---|
| Goal | Incorporate presentation feedback and assemble the final report against the course template. |
| Committed issues/epics | Report [#193](https://github.com/Collaboration95/dc2/issues/193), reporting epic #181, effort #191, durable recording access #254 and course checks #257. |
| Outcome through 10 Nov | Reviewed W1–W6 feedback material and v1.1 section revisions prepared; final report due 16 November. Final assembly, rendered-page review and submission remain close-out tasks. |

**Review.** The 26 October remarks are mapped to report changes in
`feedback-20261026/REPORT-CHANGES.md`; reviewed report notes and v1.1 gap/artifact inventories supply
traceability. The report's Presentation Feedback and Response section records the integrated response.

**Retrospective.** Went well: retained source, receipts and feedback made the revision traceable.
Improve: keep presentation outcomes, issue bookkeeping and submission receipts in step.
Action: finish report integration and print-size review, then verify the final upload and recording
access under #257/#254. These are the remaining iteration actions as of 10 November.

### Burndown, burnup and issue reduction

Figures {@fig:conduct-overall-issues}, {@fig:conduct-iteration-burndown} and
{@fig:conduct-issue-reduction} are derived from GitHub issue timestamps, captured on **10 November
2026 at 23:15 SGT**. The issue register contains 137 tasks and 19 parent epics. The charts separate
those groups; neither a parent closure nor an issue count represents additional delivered effort.
The remaining-work balance is opening open issues + newly created issues − closed issues.

![Figure {#fig:conduct-overall-issues}. Overall issue burnup and burndown, with task and parent-epic counts shown separately. Scope additions are visible; 6 tasks and 1 parent epic remain open at the snapshot.](figures/conduct-overall-issues.png){width=15cm}

![Figure {#fig:conduct-iteration-burndown}. Per-iteration issue burndown. Opening backlog is carried into each window; Iteration 5 stops at the 10 November observation, with the remaining planned period shaded.](figures/conduct-iteration-burndown.png){width=15cm}

| Iteration | Opening open | Issues added | Issues closed | Ending open |
|:---|---:|---:|---:|---:|
| 1: 5–9 Oct | 0 | 0 | 0 | 0 |
| 2: 10–14 Oct | 0 | 30 | 30 | 0 |
| 3: 15–20 Oct | 0 | 126 | 117 | 9 |
| 4: 21–26 Oct | 9 | 0 | 2 | 7 |
| 5: 27 Oct–10 Nov observed | 7 | 0 | 0 | 7 |

The table combines tasks and parent epics for register reconciliation. The overall charts use
daily balances; iteration panels show timestamp-level changes. All chart dates use Singapore time. Counts use creation and latest closure timestamps; they do not recover reopening
cycles, historical sprint membership or effort. A closure includes administrative dispositions,
such as optional epic #80 closed as not planned. The flat November line records issue state while
report work continues. No story points or original ideal sprint line are inferred.

![Figure {#fig:conduct-issue-reduction}. Issue reduction: all open issues over time, including parent epics. Seven remain open at the 10 November snapshot.](figures/conduct-issue-reduction.png){width=15cm}

The raw register is [conduct-issues.csv](data/conduct-issues.csv), with daily balances in
[conduct-daily-issues.csv](data/conduct-daily-issues.csv). Reproduce the three figures with
`python tools/conduct_burndown.py` from the report directory using matplotlib; `--refresh` repeats
`gh issue list --repo Collaboration95/dc2 --state all --limit 500 --json number,createdAt,closedAt,labels,title`
and captures a new timestamp. The script and snapshot metadata preserve the reporting windows,
timezone, source hash and chart dependency version.

## Project Status

**As of 10 November 2026**, the seven-use-case implementation is in release freeze and the team
has completed the 26 October presentation. Version 1.1 addresses its feedback for the
**16 November** final-report deadline. The status below distinguishes the retained release
records from the current repository/CI snapshot.

| Area | Status |
|:---|:---|
| Implementation | UC-1–UC-7 implemented; tests and dated local/AWS experiments indexed in `docs/evidence-index.md`. |
| Release freeze | Demo freeze accepted 20 October at `daee44b`; `project2-v1` stays immutable. Later engineering deliveries have their own verification/addenda in `docs/release/demo-release-manifest.md`; they do not constitute a replacement team freeze. |
| Live demonstration | `dc2-live` retained for the report period, with finite standard encoders and separate short-lane admission; teardown planned once after 16 November. On 10 November read-only checks returned 200 for the frontend, Media health and Processing health (the first request after an idle period wakes the paused Aurora database). |
| Report feedback | v1.1 adds the requested DDD, deployment, component, schema, analysis/design and pipeline detail. Section 6 records the feedback response. Final assembly and rendered-page review precede submission. |
| Current CI | On source `76282d3`, [1 Nov run 41294802851](https://github.com/Collaboration95/dc2/actions/runs/41294802851) succeeded. The latest scheduled [8 Nov run 42468024855](https://github.com/Collaboration95/dc2/actions/runs/42468024855) failed, including tool setup, image scans and dependent verification gates. The latest run remains failed; no rerun is claimed. |
| Remaining close-out | Complete report build/visual review and final upload (#193/#257); confirm shared recording access (#254), submission/peer-assessment receipts (#257) and reconcile remaining board/checklist records (#258). |

The measured quality results and target misses remain in section 4. Outstanding measurement
items, including the restore drill and final billing evidence, remain in the limitations/evidence
index; they do not expand the frozen implementation scope.

## Project Metrics

### Milestones planned against actual

| Planned (proposal §4.2) | Milestone | Actual / status at 10 Nov | Evidence |
|:---|:---|:---|:---|
| 4 Oct | Proposal | Submitted 4 Oct | `Team17-Proposal.docx` |
| 5–7 Oct | Baseline, domain/contracts and lecturer review | Completed 7–9 Oct | `project-roadmap/records/project-decisions.txt` |
| 8–14 Oct | Local Processing, Media, web and Publisher | Processing 12 Oct; Media/Publisher 13 Oct; integrated evidence to 14 Oct | PRs #28–#32; worklog |
| 15–20 Oct | Security, AWS, pipeline and experiments | AWS tooling 15 Oct; cloud proofs 17–18 Oct; `project2-v1` and `dc2-live` 18 Oct; CD 18–19 Oct; freeze 20 Oct | Evidence index; PR #278; release manifest |
| 21–25 Oct | Hardening and presentation preparation | Verified repair 21 Oct; lane/database delivery 21–22 Oct; demonstration clips documented as recorded 23 Oct | Engineering receipts; release addendum; presentation clips |
| 26 Oct | Team 17 presentation | Presented 26 Oct; feedback recorded the same day | `presentation/feedback-20261026/FEEDBACK.md` |
| 27 Oct–16 Nov | Feedback revision and final report | v1.1 revisions at 10 Nov; due 16 Nov | Feedback response; report sources; #193 |

Baseline/design finished on 9 October, two days beyond the proposal's window. Service extraction
landed within 8–14 October. The AWS phase included three proof runs and the persistent environment
within its 15–20 October window. The schedule keeps the final report deadline separate from
submission confirmation.

### Effort per member — agreed allocation and forecast

The effort ledger records the team's **agreed allocation** to 20 October and its **submission
forecast**, using 8 hours per person-day. GG is Guruprasath Gopal, IM is Ibrahim Mammadov and NKL
is Nguyễn Kim Long.

| # | Work package | Proposal pd | GG pd | IM pd | NKL pd | Agreed allocation pd |
|:---|:---|---:|---:|---:|---:|---:|
| 1 | Baseline, setup and inherited scan fix | 2 | 2 | 0 | 0 | 2 |
| 2 | Domain, contracts and OpenAPI | 3 | 0 | 0 | 3 | 3 |
| 3 | Processing extraction | 6 | 0 | 5 | 0 | 5 |
| 4 | Media adaptation | 3 | 0 | 3 | 0 | 3 |
| 5 | Boundary security | 3 | 0 | 2 | 0 | 2 |
| 6 | Publisher and contract tests | 2 | 0 | 0 | 2 | 2 |
| 7 | AWS and CI/CD | 4 | 6 | 0 | 0 | 6 |
| 8 | Scaling, recovery and playback experiments | 3 | 0 | 0 | 3 | 3 |
| 9 | Integration fixes and repeat checks | 2 | 2 | 0 | 1 | 3 |
| 10 | Progress, presentation and report work to 20 Oct | 3 | 1 | 1 | 1 | 3 |
| 11 | Freeze and evidence index | 0 | 0 | 0 | 1 | 1 |
| | **Agreed allocation to 20 Oct** | **31** | **11** | **11** | **11** | **33** |
| | Remaining presentation/feedback work (forecast) | — | 1 | 1 | 1 | 3 |
| | **Submission forecast** | **31** | **12** | **12** | **12** | **36** |

| Member | Agreed allocation to 20 Oct | Submission forecast recorded 21 Oct |
|:---|---:|---:|
| Guruprasath Gopal | 11 pd / 88 h | 12 pd / 96 h |
| Ibrahim Mammadov | 11 pd / 88 h | 12 pd / 96 h |
| Nguyễn Kim Long | 11 pd / 88 h | 12 pd / 96 h |
| **Total** | **33 pd / 264 h** | **36 pd / 288 h** |

The proposal estimated 31 pd. The agreed allocation is 33 pd, and the forecast is 36 pd (about
16% above the estimate), principally reflecting the added CD work and close-out verification.
These labels retain the ledger's basis. Project 1 effort is reported with each member's own
Project 1; inherited FlickPond capabilities are credited separately.

### Delivery and verification counts

Repository and Project counts were refreshed through authenticated `gh` on **10 November 2026**.
The underlying snapshot, board fields/items and PR records are retained under `data/conduct-*`.
Test counts below come from the dated CI or local validation source shown; overlapping suites
are not summed.

| Metric | Refreshed value and evidence |
|:---|:---|
| Issues | **156 total: 149 closed, 7 open**, created 12–19 Oct UTC. Of these, 137 are tasks and 19 carry the epic label. |
| Pull requests | **173 total: 164 merged, 5 closed unmerged, 4 open**. This refresh supersedes the earlier A4 total of 170. |
| Project 14 | **118 items: 111 Done, 6 Todo, 1 In Progress**. Project items are a selected board population, not the repository issue total. |
| Python fast suite | **2,986 passed, 3 skipped, 278 subtests** in the successful 1 Nov CI run at `76282d3`; separate real integrations passed 44 inherited, 47 Processing and 39 Media tests. |
| V1 operational checks | **1,520 passed** in the 1 Nov offline control-plane job. Other job suites overlap this coverage and the fast suite. |
| Frontend | **177 passed** in the same 1 Nov CI run. |
| Complete local regression | **3,697 Python tests passed plus 177 frontend tests**, retained 20 Oct validation at `514914a`; this is the dated full local baseline, not a new November run. |
| Coverage baseline | Media 93.91%, Processing 93.90% combined statement/branch coverage; frontend statements 96.24%, from `docs/results/engineering-20261020/local-validation-514914a.json`. |

The seven open issue records are the report/presentation umbrella #181, effort #191, presentation
#192, report #193, recording access #254, course checks #257 and audit index #258. The recorded
26 October presentation is complete even though its tracking issue remains open. The issue
reduction chart therefore measures register state rather than the amount of report prose produced.
