# A4 — Agile, team and visual artifact inventory

Completed 10 November 2026, Asia/Singapore. Read-only inventory of `/Users/speedpowermac/Documents/projects/CODE_MAIN/NUS/dc2-report` at `a8c8072b667a039923563ac2612dedc7e7a54ce8`, branch `dev/report-v1.1`, plus explicitly identified sibling assets and authenticated `gh` reads. Only this findings file was written; no checkout/switch/commit/push or remote mutation was performed. Paths without an absolute prefix are relative to that repository. Dates are distinguished as activity dates, last committed changes, and filesystem mtimes.

## Findings to use in report revision

1. **Team-size conflict:** the five-member team is the inherited Project 1 FlickPond team. The Project 2 proposal, effort ledger and report front matter name **three Team 17 members**, approved 22 September. Confirm the intended assessed roster before attributing work to five Project 2 members.
2. **Backlog exists:** 156 issues (149 closed, 7 open), 170 PRs (164 merged, 5 closed unmerged, 1 open), and 118 Project 14 items (111 Done, 6 Todo, 1 In Progress), read live on 10 November. Issues were created 12–19 October. No milestones, issue assignees or Project iteration field. Board uses Workflow, Wave 0–4, Priority, Risk, Area and Persona. Complete issues, PRs, labels and board fields/items are below.
3. **Project 1 sprint artifacts exist; Project 2 used delivery waves.** Do not rename Project 1 sprint reports as Project 2 evidence. `src/20-conduct.md` explicitly says there were no formal Project 2 sprint reviews or retrospectives. Engineering reviews and audit/freeze records exist; a retrospective can be conducted now and dated honestly.
4. **Burnup exists:** 12–21 October CSV and rendered SVG/PNG show 156 opened / 147 closed at that snapshot. Current 149 closures differ. Issue-count reconstructed burndown is possible with declared scope and boundaries, but dated sprint commitment, estimates and membership history are missing.
5. **Contribution summary exists; individual account counts are not effort evidence.** Proposal/ledger name specialist leads and allocate 11 pd / 88 h each through 20 October, forecast 12 pd / 96 h each at submission. All 170 PRs use @Collaboration95. HEAD has 439 non-merge commits in the proposal-to-inventory window, all recorded under Guruprasath. No verified per-UC analysis/design owner table; the three design-problem owners are explicitly suggestions.
6. **UI/UX evidence is recoverable:** persona website at `project-roadmap/business-scope.html` (9 October fictional planning personas), local D1–D5 clips in sibling `dc2-rescue` (documented capture 23 October). Report checkout lacks clips. Existing image directories primarily hold technical diagrams. Asset manifests below list paths, bytes, dates and source-derived descriptions; visual readability was not audited.

## Sprint, iteration and progress evidence: curated index

| Project / artifact | Activity dates | Existing content / limits |
|---|---|---|
| P1 `docs/proposal.md` | September baseline; last committed change in detailed index | Five-person roster, goals, features and earlier personas; not Team 17 P2 proposal |
| P1 `docs/sprint1-plan.md` | 4–10 September 2026 | Seven story rows (US1–US5 plus operator/platform), A–E owners, done-when, day-by-day plan, integration contract, NFR targets |
| P1 `docs/sprint1-report.md` | Window 4–10 September; last updated 7 September | Delivered track contributions, tests/coverage, bug log, limitations/next steps, revision history. Mid-window record, not proof of a 10 September review meeting |
| P1 `docs/sprint2-backlog.md` | Written 7 September | Sprint 1 technical/security review outputs, P1–P9 decisions and priorities |
| P1 `docs/sprint2-plan.md` | Written/updated 10 September | Eight S2-01–S2-08 items, priority/dependencies, acceptance criteria, definition of done |
| P1 `docs/sprint2-report.md` | Window 10–11 September; written 11 September | Measured outcomes, contribution table, defect/lesson log, limitations/next tasks; AI-assistance disclosure |
| P1 `docs/c-recovery-input-safety.md` | Identifies Sprint 3; no verified complete sprint window | Track C recovery/input safety; not a complete third sprint plan/report |
| P1 historical references | Listed in `project-2-baseline-and-plan.txt` | Mentions `docs/roadmap.md` and `docs/sprint4-plan.md`; those paths do not exist in this checkout. No sprint3/4 complete report found |
| P2 `project-documentation/Team17-Proposal.docx` | 4 October; approval 22 September | Ten work packages, lead members, 31 pd estimate, six schedule periods, risks |
| P2 `project-documentation/project-2-baseline-and-plan.txt`, `project-2-requirements-and-scope.txt` | Baseline/planning snapshots; see committed dates below | Inherited/new boundary, course/scope extraction and planned delivery; not sprint review minutes |
| P2 `project-roadmap/README.txt`, `roadmap-data.json`, `records/project-decisions.txt` | Roadmap prepared 9 October | Milestones and decisions F-01 / D-01–D-07; D-06 says one progress report due 16 October |
| P2 `docs/execution/plan.md`, `backlog.json`, `issues/*.md`, `github-map.json`, `issue-map.md`, `progress.json` | Local execution starts 12 October | Persona-linked acceptance contracts, six epics, Wave 0–4 ordering, issue/PR mapping and retained status; historical pre-AWS phase |
| P2 `docs/execution/reviews/` | Dated review files in detailed index | Independent planning/technical reviews, not Scrum sprint ceremonies |
| P2 `docs/execution/aws/readiness/`, `aws/prep/`, `aws/v1/`, `aws/v2/` | AWS preparation 14–15 October; proofs/closeout 17–21 October | Versioned backlogs, issue maps, plans, contracts, acceptance/review/evidence records; old planning states intentionally retained |
| P2 `docs/project2-worklog.txt`, `docs/evidence-index.md`, `docs/execution/progress.json`, `docs/results/` | Dated entries / retained receipts; detailed index below | Progress and experiment/fix evidence; distinguish runtime/engineering results from course submission receipts |
| P2 `project-documentation/effort-ledger.md` | Recorded 20 October; forecast/resolution 21 October | Completed work, allocated hours per member, problems, next two weeks, milestone planned/actual table |
| P2 `project-documentation/final-report/src/20-conduct.md` | As-of 21 October with later edits | WBS, wave-based way of working, status/metrics, burnup/schedule, equal effort; several historical scheduled/pending statements need final-date reconciliation |
| P2 `project-roadmap/design/08-build-readiness/progress-template.txt` | 9 October preparation pack | Progress-report template only; not completed report/submission evidence |
| P2 course submission tracking | Issue #257, created 18 October, updated 20 October: https://github.com/Collaboration95/dc2/issues/257 | Progress-report receipt/Canvas/peer assessment checks; a separate submitted 16 October progress-report artifact or receipt was not established |
| P2 presentation feedback | 26 October, under `project-documentation/presentation/feedback-20261026/` | W1–W6 analysis/review and report notes, reusable post-presentation refinement; not a sprint retrospective |

P2 proposed periods (proposal §4.2): **5–7 Oct** baseline/domain; **8–14 Oct** extraction/web/CLI; **15–20 Oct** security/cloud/experiments; **21–25 Oct** fixes/rehearsal; **26 Oct** presentation; **27 Oct–16 Nov** report feedback revision. These are plan phases, not confirmed sprint commitments. Milestone actuals in ledger/report: baseline/domain 7–9 Oct; Processing 12 Oct; Media/Publisher 13 Oct; AWS tooling 15 Oct; tagged release/persistent environment 18 Oct; CD 18–19 Oct; freeze 20 Oct. Current status must be read separately from those historical snapshots.

## Burndown / burnup feasibility

- Existing `project-documentation/final-report/data/issue-burnup.csv`: ten UTC daily rows, **12–21 October 2026**. Columns: `date,opened,closed,cumulative_opened,cumulative_closed,open_at_end_of_day`. Endpoint **156/147/9**. These are issue counts, not stories completed, hours or velocity. Issue creation range in live snapshot is 12–19 October.
- Existing `tools/chart_burnup.py` reads that CSV and emits `figures/src/report-burnup.svg`; `tools/render_figures.py report-burnup` can render `figures/report-burnup.png`. Script has a fixed 160 y-axis and fixed date title; an updated window needs explicit changes. Neither tool was run during this read-only inventory.
- **Can generate per-period issue-count burndown:** choose/document phase boundaries from proposal periods, dated plan/PR merges (for example local 12–14 Oct, AWS 15–20 Oct, closeout after 20 Oct). Call them reconstructed reporting periods unless the team confirms actual sprint boundaries. Use timestamps listed in the complete issue inventory; pin the exact included issue IDs and snapshot date.
- For a fixed period commitment set S, remaining(t) = count of issues in S not closed by t. For changing scope, remaining(t) = initial open scope + additions(t) − closures(t), with additions and removals explicit. Carry issues created before period start into the opening balance. Treat parent epics separately to avoid double-counting child delivery. Closed-as-not-planned tasks are scope removal, not delivery. Use UTC or convert consistently to SGT; include the 4 October-to-11 October zero/no-issue interval when claiming the whole P2 period.
- **Limits:** current `createdAt`/`closedAt` cannot recover reopen/close cycles, historic board membership, estimates or historical sprint commitment. For exact closure/reopen transitions use authenticated `gh api --method GET repos/Collaboration95/dc2/issues/<n>/timeline --paginate`, preserving event dates/reasons; obtain archived commitment/scope records if available. Current Project fields have no dates/iterations/story points. No honest points-based burndown or historical velocity can be inferred from commit/PR counts. An ideal line may be a labeled retrospective reference, never represented as the original team plan.


## GitHub snapshot — 2026-11-10 (UTC timestamps)

Read through authenticated `gh` only. Repo https://github.com/Collaboration95/dc2 ; project https://github.com/users/Collaboration95/projects/14 . All-state listings, limit 1,000 (not reached). Issue counts are tasks, not story points or effort.

156 issues; states {'CLOSED': 149, 'OPEN': 7}. 170 PRs; states {'OPEN': 1, 'MERGED': 164, 'CLOSED': 5}. 118 Project items of reported 118.

### Milestones

| Title / URL | Created | Due | Closed | Open/closed issues |
|---|---|---|---|---|

### Labels

| Label | Description | Issue count |
|---|---|---|
| accessibility | Barrier affecting people with disabilities | 0 |
| bug | Something isn't working | 32 |
| documentation | Improvements or additions to documentation | 18 |
| duplicate | This issue or pull request already exists | 0 |
| enhancement | New feature or request | 33 |
| good first issue | Good for newcomers | 0 |
| help wanted | Extra attention is needed | 0 |
| invalid | This doesn't seem right | 0 |
| question | Further information is requested | 0 |
| wontfix | This will not be worked on | 0 |
| epic | Parent delivery outcome | 19 |
| pre-aws | Authorized local delivery; no AWS actions | 25 |
| planning | Planning and independent review | 21 |
| foundation | Reproducible local setup and checks | 11 |
| processing | Processing service and workers | 19 |
| clients | Browser and independent Publisher CLI | 9 |
| media | Media Management and data ownership | 11 |
| verification | Integrated evidence and release acceptance | 36 |
| v1 | Required visible microservices baseline | 49 |
| v2 | Optional measured experiments after accepted V1 | 11 |
| closeout | Post-V1 work needed for submission: pipeline, docs, presentation, report | 46 |
| needs-human-approval | Do not start without explicit human approval | 4 |
| v2-live | V2: one always-on environment that scales to zero | 7 |

### Project 14 fields

```json
{
  "fields": [
    {
      "id": "PVTF_lAHOBBatWM4BmtkxzhlVeNo",
      "name": "Title",
      "type": "ProjectV2Field"
    },
    {
      "id": "PVTF_lAHOBBatWM4BmtkxzhlVeNs",
      "name": "Assignees",
      "type": "ProjectV2Field"
    },
    {
      "id": "PVTSSF_lAHOBBatWM4BmtkxzhlVeNw",
      "name": "Status",
      "options": [
        {
          "id": "f75ad846",
          "name": "Todo"
        },
        {
          "id": "47fc9ee4",
          "name": "In Progress"
        },
        {
          "id": "98236657",
          "name": "Done"
        }
      ],
      "type": "ProjectV2SingleSelectField"
    },
    {
      "id": "PVTF_lAHOBBatWM4BmtkxzhlVeN0",
      "name": "Labels",
      "type": "ProjectV2Field"
    },
    {
      "id": "PVTF_lAHOBBatWM4BmtkxzhlVeN4",
      "name": "Linked pull requests",
      "type": "ProjectV2Field"
    },
    {
      "id": "PVTF_lAHOBBatWM4BmtkxzhlVeN8",
      "name": "Milestone",
      "type": "ProjectV2Field"
    },
    {
      "id": "PVTF_lAHOBBatWM4BmtkxzhlVeOA",
      "name": "Repository",
      "type": "ProjectV2Field"
    },
    {
      "id": "PVTF_lAHOBBatWM4BmtkxzhlVeOI",
      "name": "Reviewers",
      "type": "ProjectV2Field"
    },
    {
      "id": "PVTF_lAHOBBatWM4BmtkxzhlVeOM",
      "name": "Parent issue",
      "type": "ProjectV2Field"
    },
    {
      "id": "PVTF_lAHOBBatWM4BmtkxzhlVeOQ",
      "name": "Sub-issues progress",
      "type": "ProjectV2Field"
    },
    {
      "id": "PVTF_lAHOBBatWM4BmtkxzhlVeOU",
      "name": "Created",
      "type": "ProjectV2Field"
    },
    {
      "id": "PVTF_lAHOBBatWM4BmtkxzhlVeOY",
      "name": "Updated",
      "type": "ProjectV2Field"
    },
    {
      "id": "PVTF_lAHOBBatWM4BmtkxzhlVeOc",
      "name": "Closed",
      "type": "ProjectV2Field"
    },
    {
      "id": "PVTSSF_lAHOBBatWM4BmtkxzhlVeSE",
      "name": "Workflow",
      "options": [
        {
          "id": "c978a6e5",
          "name": "Backlog"
        },
        {
          "id": "e02f1ad4",
          "name": "Ready"
        },
        {
          "id": "ba99be3d",
          "name": "In progress"
        },
        {
          "id": "ea57a0a3",
          "name": "Review"
        },
        {
          "id": "70f40fab",
          "name": "Blocked"
        },
        {
          "id": "fa2d3a3f",
          "name": "Done"
        }
      ],
      "type": "ProjectV2SingleSelectField"
    },
    {
      "id": "PVTSSF_lAHOBBatWM4BmtkxzhlVeSc",
      "name": "Wave",
      "options": [
        {
          "id": "a61eb394",
          "name": "Wave 0"
        },
        {
          "id": "1e7f233e",
          "name": "Wave 1"
        },
        {
          "id": "5f0cbf3d",
          "name": "Wave 2"
        },
        {
          "id": "f761184d",
          "name": "Wave 3"
        },
        {
          "id": "84255653",
          "name": "Wave 4"
        }
      ],
      "type": "ProjectV2SingleSelectField"
    },
    {
      "id": "PVTSSF_lAHOBBatWM4BmtkxzhlVeSg",
      "name": "Priority",
      "options": [
        {
          "id": "1c24d7a6",
          "name": "P0"
        },
        {
          "id": "d0615693",
          "name": "P1"
        },
        {
          "id": "f8a22557",
          "name": "P2"
        }
      ],
      "type": "ProjectV2SingleSelectField"
    },
    {
      "id": "PVTSSF_lAHOBBatWM4BmtkxzhlVeU4",
      "name": "Risk",
      "options": [
        {
          "id": "dd7206c2",
          "name": "Low"
        },
        {
          "id": "62885e72",
          "name": "Medium"
        },
        {
          "id": "89dcbf8b",
          "name": "High"
        }
      ],
      "type": "ProjectV2SingleSelectField"
    },
    {
      "id": "PVTF_lAHOBBatWM4BmtkxzhlVeVQ",
      "name": "Area",
      "type": "ProjectV2Field"
    },
    {
      "id": "PVTF_lAHOBBatWM4BmtkxzhlVeVY",
      "name": "Persona",
      "type": "ProjectV2Field"
    },
    {
      "id": "PVTF_lAHOBBatWM4BmtkxzhlVeXM",
      "name": "Sequence",
      "type": "ProjectV2Field"
    }
  ],
  "totalCount": 20
}
```

### Project 14 items

| Title / URL | Status | Workflow | Iteration / dates / other metadata |
|---|---|---|---|
| [E0] Reviewed plan and auditable delivery | Done | Done | {"area": "planning", "linked pull requests": ["https://github.com/Collaboration95/dc2/pull/25"], "persona": "Jules, Sam", "priority": "P1", "risk": "Medium", "sequence": 0, "wave": "Wave 0"} https://github.com/Collaboration95/dc2/issues/1 |
| [G1] Define epics, persona stories, issue contracts and waves | Done | Done | {"area": "planning", "linked pull requests": ["https://github.com/Collaboration95/dc2/pull/25"], "persona": "Jules, Sam", "priority": "P0", "risk": "Medium", "sequence": 6, "wave": "Wave 0"} https://github.com/Collaboration95/dc2/issues/7 |
| [G2] Independently review and correct the delivery plan | Done | Done | {"area": "planning", "linked pull requests": ["https://github.com/Collaboration95/dc2/pull/25"], "persona": "Jules, Sam", "priority": "P0", "risk": "Medium", "sequence": 7, "wave": "Wave 0"} https://github.com/Collaboration95/dc2/issues/8 |
| [E1] Reproducible local workspace and fast checks | Done | Done | {"area": "foundation", "linked pull requests": ["https://github.com/Collaboration95/dc2/pull/26", "https://github.com/Collaboration95/dc2/pull/27"], "persona": "Jules, Sam", "priority": "P1", "risk": "Medium", "sequence": 1, "wave": "Wave 0"} https://github.com/Collaboration95/dc2/issues/2 |
| [F1] Install a reproducible root workspace with Make and environment doctor | Done | Done | {"area": "foundation", "linked pull requests": ["https://github.com/Collaboration95/dc2/pull/26"], "persona": "Jules, Sam", "priority": "P0", "risk": "Medium", "sequence": 8, "wave": "Wave 1"} https://github.com/Collaboration95/dc2/issues/9 |
| [F2] Establish fast deterministic test tiers and required CI checks | Done | Done | {"area": "foundation", "linked pull requests": ["https://github.com/Collaboration95/dc2/pull/26", "https://github.com/Collaboration95/dc2/pull/27"], "persona": "Jules, Sam", "priority": "P0", "risk": "High", "sequence": 9, "wave": "Wave 1"} https://github.com/Collaboration95/dc2/issues/10 |
| [F3] Provide isolated local services, storage and trusted HTTPS topology | Done | Done | {"area": "foundation", "linked pull requests": ["https://github.com/Collaboration95/dc2/pull/26"], "persona": "Arun, Sam", "priority": "P0", "risk": "High", "sequence": 10, "wave": "Wave 1"} https://github.com/Collaboration95/dc2/issues/11 |
| [E2] Independent processing and reliable attempts | Done | Done | {"area": "processing", "linked pull requests": ["https://github.com/Collaboration95/dc2/pull/28"], "persona": "Arun, Sam", "priority": "P1", "risk": "Medium", "sequence": 2, "wave": "Wave 0"} https://github.com/Collaboration95/dc2/issues/3 |
| [P1] Implement attempt lifecycle, stored-source retry and cancellation | Done | Done | {"area": "processing", "linked pull requests": ["https://github.com/Collaboration95/dc2/pull/28"], "persona": "Arun, Sam", "priority": "P1", "risk": "High", "sequence": 11, "wave": "Wave 2"} https://github.com/Collaboration95/dc2/issues/12 |
| [P2] Run attempt-aware FFmpeg workers with private source and output access | Done | Done | {"area": "processing", "linked pull requests": ["https://github.com/Collaboration95/dc2/pull/28"], "persona": "Arun, Maya", "priority": "P1", "risk": "High", "sequence": 12, "wave": "Wave 2"} https://github.com/Collaboration95/dc2/issues/13 |
| [P3] Recover worker interruptions and lost queue deliveries | Done | Done | {"area": "processing", "linked pull requests": ["https://github.com/Collaboration95/dc2/pull/28"], "persona": "Sam, Arun", "priority": "P1", "risk": "High", "sequence": 13, "wave": "Wave 2"} https://github.com/Collaboration95/dc2/issues/14 |
| [E3] Media ownership and compatible public workflow | Done | Done | {"area": "media", "linked pull requests": ["https://github.com/Collaboration95/dc2/pull/29"], "persona": "Arun, Jules", "priority": "P1", "risk": "Medium", "sequence": 3, "wave": "Wave 0"} https://github.com/Collaboration95/dc2/issues/4 |
| [M1] Create Media-owned Assets and durable idempotent submission | Done | Done | {"area": "media", "linked pull requests": ["https://github.com/Collaboration95/dc2/pull/29"], "persona": "Arun, Jules", "priority": "P1", "risk": "High", "sequence": 14, "wave": "Wave 2"} https://github.com/Collaboration95/dc2/issues/15 |
| [M2] Serve compatible status, retry and authorised MP4/HLS playback | Done | Done | {"area": "media", "linked pull requests": ["https://github.com/Collaboration95/dc2/pull/29"], "persona": "Arun, Maya, Jules", "priority": "P1", "risk": "High", "sequence": 15, "wave": "Wave 2"} https://github.com/Collaboration95/dc2/issues/16 |
| [M3] Reconcile pending submissions and preserve edit/delete/operator behavior | Done | Done | {"area": "media", "linked pull requests": ["https://github.com/Collaboration95/dc2/pull/29"], "persona": "Arun, Sam", "priority": "P1", "risk": "High", "sequence": 16, "wave": "Wave 2"} https://github.com/Collaboration95/dc2/issues/17 |
| [E4] Web and independent Publisher CLI | Done | Done | {"area": "clients", "linked pull requests": ["https://github.com/Collaboration95/dc2/pull/30"], "persona": "Maya, Arun, Jules", "priority": "P1", "risk": "Medium", "sequence": 4, "wave": "Wave 0"} https://github.com/Collaboration95/dc2/issues/5 |
| [C1] Build the independent Publisher CLI against public APIs | Done | Done | {"area": "clients", "linked pull requests": ["https://github.com/Collaboration95/dc2/pull/30"], "persona": "Maya, Jules", "priority": "P1", "risk": "Medium", "sequence": 17, "wave": "Wave 2"} https://github.com/Collaboration95/dc2/issues/18 |
| [C2] Complete browser stored-source retry and idempotent requests | Done | Done | {"area": "clients", "linked pull requests": ["https://github.com/Collaboration95/dc2/pull/30"], "persona": "Arun", "priority": "P1", "risk": "Medium", "sequence": 18, "wave": "Wave 2"} https://github.com/Collaboration95/dc2/issues/19 |
| [E5] Integrated evidence and local release readiness | Done | Done | {"area": "verification", "persona": "Sam, all personas", "priority": "P1", "risk": "Medium", "sequence": 5, "wave": "Wave 0"} https://github.com/Collaboration95/dc2/issues/6 |
| [V1] Integrate full local workflow and contract regression evidence | Done | Done | {"area": "verification", "linked pull requests": ["https://github.com/Collaboration95/dc2/pull/31"], "persona": "Arun, Maya, Jules", "priority": "P1", "risk": "High", "sequence": 19, "wave": "Wave 3"} https://github.com/Collaboration95/dc2/issues/20 |
| [V2] Exercise recovery faults across both services | Done | Done | {"area": "verification", "persona": "Sam, Arun", "priority": "P1", "risk": "High", "sequence": 20, "wave": "Wave 3"} https://github.com/Collaboration95/dc2/issues/21 |
| [V3] Measure local performance and worker scaling without misleading claims | Done | Done | {"area": "verification", "persona": "Sam", "priority": "P1", "risk": "High", "sequence": 21, "wave": "Wave 4"} https://github.com/Collaboration95/dc2/issues/22 |
| [V4] Automate independent local Processing release, smoke and rollback | Done | Done | {"area": "verification", "persona": "Sam", "priority": "P1", "risk": "High", "sequence": 22, "wave": "Wave 4"} https://github.com/Collaboration95/dc2/issues/23 |
| [V5] Review final delivery and publish evidence-based morning handoff | Done | Done | {"area": "verification", "linked pull requests": ["https://github.com/Collaboration95/dc2/pull/32"], "persona": "Maya, Arun, Jules, Sam", "priority": "P1", "risk": "High", "sequence": 23, "wave": "Wave 4"} https://github.com/Collaboration95/dc2/issues/24 |
| [E6] Measured performance improvements within demo budget | Done | Done | {"linked pull requests": ["https://github.com/Collaboration95/dc2/pull/40"]} https://github.com/Collaboration95/dc2/issues/33 |
| [PERF] Media API and data access: investigate and remove avoidable work | Done | Done | {"linked pull requests": ["https://github.com/Collaboration95/dc2/pull/37"]} https://github.com/Collaboration95/dc2/issues/34 |
| [PERF] Processing worker and media engine: investigate and remove avoidable work | Done | Done | {"linked pull requests": ["https://github.com/Collaboration95/dc2/pull/37"]} https://github.com/Collaboration95/dc2/issues/35 |
| [PERF] Frontend and Publisher: investigate and remove avoidable work | Done | Done | {"linked pull requests": ["https://github.com/Collaboration95/dc2/pull/37"]} https://github.com/Collaboration95/dc2/issues/36 |
| [PERF] Measure CPU quota redistribution under mixed workloads | Done | Done | {"linked pull requests": ["https://github.com/Collaboration95/dc2/pull/40"], "priority": "P2"} https://github.com/Collaboration95/dc2/issues/38 |
| [PERF] Validate bounded worker scheduling and demo run windows | Done | Done | {"linked pull requests": ["https://github.com/Collaboration95/dc2/pull/40"], "priority": "P2"} https://github.com/Collaboration95/dc2/issues/39 |
| [V1 epic] Visible domain APIs, ownership and S3 intake | Done | Done | {"area": "media", "priority": "P1", "risk": "High"} https://github.com/Collaboration95/dc2/issues/41 |
| [V1 epic] Managed runtime, session controls and budget | Done | Done | {"area": "foundation", "priority": "P1", "risk": "High"} https://github.com/Collaboration95/dc2/issues/42 |
| [V1 epic] Redis-free delivery, finite workers and independent releases | Done | Done | {"area": "processing", "priority": "P1", "risk": "High"} https://github.com/Collaboration95/dc2/issues/43 |
| [V1 epic] Authentic acceptance and immutable submission baseline | Done | Done | {"area": "verification", "priority": "P1", "risk": "High"} https://github.com/Collaboration95/dc2/issues/44 |
| [V1] Record actual project account, currency and scoped cloud authorization | Done | Done | {"area": "planning", "priority": "P0", "risk": "High"} https://github.com/Collaboration95/dc2/issues/45 |
| [V1 decision] Replace the public EC2 HTTP origin with managed HTTPS | Done | Done | {"area": "planning", "priority": "P1", "risk": "High"} https://github.com/Collaboration95/dc2/issues/46 |
| [AWS2] Wire refreshing ECS credentials into Media storage | Done | Done | {"area": "media", "priority": "P1", "risk": "Medium"} https://github.com/Collaboration95/dc2/issues/47 |
| [AWS2] Wire ECS writer and cleanup credentials into Processing | Done | Done | {"area": "processing", "priority": "P1", "risk": "Medium"} https://github.com/Collaboration95/dc2/issues/48 |
| [AWS2] Bound signed URL lifetime to the credentials actually used | Done | Done | {"area": "media", "priority": "P1", "risk": "Medium"} https://github.com/Collaboration95/dc2/issues/49 |
| [AWS2] Define one-subnet state, storage and IAM infrastructure offline | Done | Done | {"area": "infrastructure", "priority": "P1", "risk": "High"} https://github.com/Collaboration95/dc2/issues/50 |
| [AWS2] Bootstrap only PostgreSQL, Redis and nginx on retained EBS | Done | Done | {"area": "infrastructure", "priority": "P1", "risk": "High"} https://github.com/Collaboration95/dc2/issues/51 |
| [AWS2] Define three services, owner migrations and disposable worker tasks | Done | Done | {"area": "infrastructure", "priority": "P1", "risk": "High"} https://github.com/Collaboration95/dc2/issues/52 |
| [AWS2] Configure CloudFront and nginx for private authenticated API traffic | Done | Done | {"area": "infrastructure", "priority": "P1", "risk": "High"} https://github.com/Collaboration95/dc2/issues/53 |
| [AWS2] Bind amd64 owner artifacts to tests, scans and ECR digest receipts | Done | Done | {"area": "delivery", "priority": "P1", "risk": "High"} https://github.com/Collaboration95/dc2/issues/54 |
| [AWS2] Cover extracted services in delivery scans and report execution honestly | Done | Done | {"area": "delivery", "priority": "P1", "risk": "Medium"} https://github.com/Collaboration95/dc2/issues/55 |
| [AWS2] Start at most three worker tasks with one serialized operator | Done | Done | {"area": "processing", "priority": "P1", "risk": "High"} https://github.com/Collaboration95/dc2/issues/56 |
| [AWS2] Bound cloud worker lifetime and warm-drain before StopTask | Done | Done | {"area": "processing", "priority": "P1", "risk": "High"} https://github.com/Collaboration95/dc2/issues/57 |
| [AWS2] Add a small cloud client and safe evidence context | Done | Done | {"area": "verification", "priority": "P1", "risk": "Medium"} https://github.com/Collaboration95/dc2/issues/58 |
| [AWS2] Promote and roll back Processing alone on ECS | Done | Done | {"area": "processing", "priority": "P1", "risk": "High"} https://github.com/Collaboration95/dc2/issues/59 |
| [AWS2] Release Media API and reconciler without changing Processing | Done | Done | {"area": "media", "priority": "P1", "risk": "Medium"} https://github.com/Collaboration95/dc2/issues/60 |
| [AWS2] Open and close sessions with complete task and IP accounting | Done | Done | {"area": "infrastructure", "priority": "P1", "risk": "High"} https://github.com/Collaboration95/dc2/issues/61 |
| [AWS2] Export both owned databases at one quiescent boundary | Done | Done | {"area": "infrastructure", "priority": "P1", "risk": "Medium"} https://github.com/Collaboration95/dc2/issues/62 |
| [V1 evidence] Deploy the approved target and prove real workflow boundaries | Done | Done | {"area": "verification", "priority": "P1", "risk": "High"} https://github.com/Collaboration95/dc2/issues/63 |
| [V1 evidence] Prove 1/2/3 encoders and bounded SQS recovery on AWS | Done | Done | {"area": "verification", "priority": "P1", "risk": "High"} https://github.com/Collaboration95/dc2/issues/64 |
| [V1 evidence] Capture independent Lambda/Fargate release and rollback | Done | Done | {"area": "verification", "priority": "P1", "risk": "High"} https://github.com/Collaboration95/dc2/issues/65 |
| [V1 evidence] Measure warm API latency with an independent Fargate generator | Done | Done | {"area": "verification", "priority": "P1", "risk": "Medium"} https://github.com/Collaboration95/dc2/issues/66 |
| [V1 evidence] Reconcile actual spend, close state and final V1 handoff | Done | Done | {"area": "verification", "linked pull requests": ["https://github.com/Collaboration95/dc2/pull/194"], "priority": "P1", "risk": "High"} https://github.com/Collaboration95/dc2/issues/67 |
| [V2 experiment] Optional unattended worker starts and further cost cuts | Done | Backlog | {"area": "processing", "priority": "P2", "risk": "Medium"} https://github.com/Collaboration95/dc2/issues/68 |
| [V1] Freeze gateway routes, trusted identity and message contracts | Done | Done | {"area": "planning", "priority": "P0", "risk": "High"} https://github.com/Collaboration95/dc2/issues/81 |
| [V1] Package Media Lambda with native credentials and owned SQL | Done | Done | {"area": "media", "priority": "P1", "risk": "High"} https://github.com/Collaboration95/dc2/issues/82 |
| [V1] Package Processing Lambda API and owned job lifecycle | Done | Done | {"area": "processing", "priority": "P1", "risk": "High"} https://github.com/Collaboration95/dc2/issues/83 |
| [V1] Replace Redis/RQ delivery with SQS and durable SQL repair | Done | Done | {"area": "processing", "priority": "P1", "risk": "High"} https://github.com/Collaboration95/dc2/issues/84 |
| [V1] Replace peer calls with commands, results and owned projections | Done | Done | {"area": "media", "priority": "P1", "risk": "High"} https://github.com/Collaboration95/dc2/issues/85 |
| [V1] Move browser and Publisher uploads directly to authorized S3 | Done | Done | {"area": "clients", "priority": "P1", "risk": "High"} https://github.com/Collaboration95/dc2/issues/86 |
| [V1] Run finite SQS Fargate encoders and remove source callbacks | Done | Done | {"area": "processing", "priority": "P1", "risk": "High"} https://github.com/Collaboration95/dc2/issues/87 |
| [V1] Implement bounded Lambda repair and late-output cleanup | Done | Done | {"area": "processing", "priority": "P1", "risk": "High"} https://github.com/Collaboration95/dc2/issues/88 |
| [V1] Define managed Gateway/Lambda/SQS/Aurora infrastructure offline | Done | Done | {"area": "foundation", "priority": "P1", "risk": "High"} https://github.com/Collaboration95/dc2/issues/89 |
| [V1] Adapt independent releases, migrations and rollback to Lambda/Fargate | Done | Done | {"area": "verification", "priority": "P1", "risk": "High"} https://github.com/Collaboration95/dc2/issues/90 |
| [V1] Adapt session open/close, cost model and evidence protocols | Done | Done | {"area": "foundation", "priority": "P1", "risk": "High"} https://github.com/Collaboration95/dc2/issues/91 |
| [V1] Verify the complete Redis-free workflow locally | Done | Done | {"area": "verification", "priority": "P1", "risk": "High"} https://github.com/Collaboration95/dc2/issues/92 |
| [V2 epic] Optional measured migrations after accepted V1 | Done | Backlog | {"area": "planning", "priority": "P2", "risk": "Medium"} https://github.com/Collaboration95/dc2/issues/80 |
| [V2 experiment] Benchmark bounded short encodes on Lambda | Done | Backlog | {"area": "processing", "priority": "P2", "risk": "High"} https://github.com/Collaboration95/dc2/issues/93 |
| [V2 experiment] Measure separate database clusters and pause behavior | Done | Backlog | {"area": "foundation", "priority": "P2", "risk": "Medium"} https://github.com/Collaboration95/dc2/issues/94 |
| [Close-out epic] Visible DevOps pipeline: CI, deploy, smoke, release and rollback | Done | Done | {} https://github.com/Collaboration95/dc2/issues/178 |
| [Close-out epic] One cloud session from project2-v1: pipeline run, backlog scaling, demo recording | Done | In progress | {} https://github.com/Collaboration95/dc2/issues/179 |
| [Close-out epic] As-built architecture, DDD and evidence documentation | Done | Done | {} https://github.com/Collaboration95/dc2/issues/180 |
| [Close-out epic] Presentation (26 Oct) and final report (16 Nov) — DO NOT START without human approval | Todo | Blocked | {} https://github.com/Collaboration95/dc2/issues/181 |
| [Close-out] GitHub Actions CD workflow wrapping the V1 deploy, release and teardown scripts | Done | Done | {} https://github.com/Collaboration95/dc2/issues/182 |
| [Close-out] Add secret scanning to CI | Done | Done | {} https://github.com/Collaboration95/dc2/issues/183 |
| [Close-out] Publish OpenAPI documents for the Media and Processing public APIs with a drift check | Done | Done | {} https://github.com/Collaboration95/dc2/issues/184 |
| [Close-out] Backlog throughput mode for the capacity proof (jobs/min at cap 1, 2, 3) | Done | Done | {} https://github.com/Collaboration95/dc2/issues/185 |
| [Close-out] Run the single cloud session: pipeline deploy, smoke, backlog scaling, independent release, demo recording, teardown | Done | Blocked | {} https://github.com/Collaboration95/dc2/issues/186 |
| [Close-out] As-built DDD model: language, two bounded contexts, aggregates, commands/events, context map | Done | Done | {} https://github.com/Collaboration95/dc2/issues/187 |
| [Close-out] ADR register and proposal→V1 deviation table, logical and physical diagrams | Done | Done | {} https://github.com/Collaboration95/dc2/issues/188 |
| [Close-out] Evidence index: quality scenarios, targets and results, with local and cloud labelled | Done | Done | {} https://github.com/Collaboration95/dc2/issues/189 |
| [Close-out] Submission repo hygiene: start-here README, historical docs labelled, stale branches and worktrees removed | Done | Done | {} https://github.com/Collaboration95/dc2/issues/190 |
| [Close-out] Effort and milestone ledger per member, plus progress report | Todo | Blocked | {} https://github.com/Collaboration95/dc2/issues/191 |
| [Close-out] Presentation deck, demo script and rehearsal for 26 Oct | Todo | Blocked | {} https://github.com/Collaboration95/dc2/issues/192 |
| [Close-out] Final report per the course template, with presentation feedback | Todo | Blocked | {} https://github.com/Collaboration95/dc2/issues/193 |
| [Close-out epic] Microservices hardening from the architecture audit | Done | Done | {} https://github.com/Collaboration95/dc2/issues/195 |
| [Close-out] Prove failure isolation: Media accepts uploads while Processing is down | Done | Done | {} https://github.com/Collaboration95/dc2/issues/196 |
| [Close-out] Remove legacy peer-HTTP code from the V1 service images | Done | Done | {} https://github.com/Collaboration95/dc2/issues/197 |
| [Close-out] Contract versioning policy and consumer-driven contract tests per service | Done | Done | {} https://github.com/Collaboration95/dc2/issues/198 |
| [Close-out] Per-service CI: path-filtered Media and Processing jobs, plus CODEOWNERS | Done | Done | {} https://github.com/Collaboration95/dc2/issues/199 |
| [Close-out] Per-service observability: DLQ and error alarms, dashboard, least-privilege environment | Done | Done | {} https://github.com/Collaboration95/dc2/issues/200 |
| [Close-out] Remove peer-era leftovers from the V1 packages (found by the architecture docs review) | Done | Done | {} https://github.com/Collaboration95/dc2/issues/210 |
| [Close-out] AWS security-negatives proof: cross-owner, tampered/expired URLs, oversize upload, external port scan | Done | Blocked | {} https://github.com/Collaboration95/dc2/issues/229 |
| [V2 epic] One always-on environment that updates in place and scales to zero | Done | In progress | {} https://github.com/Collaboration95/dc2/issues/234 |
| [V2-live] Persistent named environment: CD updates one stack in place | Done | Done | {} https://github.com/Collaboration95/dc2/issues/235 |
| [V2-live] Remove booked sessions from the normal path: always-on API and consumers | Done | Done | {} https://github.com/Collaboration95/dc2/issues/236 |
| [V2-live] Encoders scale 0→3→0 with the queue, started on enqueue | Done | Blocked | {} https://github.com/Collaboration95/dc2/issues/237 |
| [V2-live] Deploy dc2-live once, verify, and keep it running | Done | In progress | {} https://github.com/Collaboration95/dc2/issues/238 |
| [P1][Clients] Account switching exposes prior-owner library cards and playback capabilities | Done | Done | {"priority": "P1"} https://github.com/Collaboration95/dc2/issues/243 |
| [P1][V2-live] Processing API retry/cancel bypass idle activity markers and can stall repair | Done | Done | {"priority": "P1"} https://github.com/Collaboration95/dc2/issues/244 |
| [P2][Publisher] Quick-start and CLI help use /api instead of the V1 /api/media base | Done | Done | {"priority": "P2"} https://github.com/Collaboration95/dc2/issues/245 |
| [P2][Clients] Library and Admin list failures are shown as successful empty results | Done | Done | {"priority": "P2"} https://github.com/Collaboration95/dc2/issues/246 |
| [P2][Local V1] Clean-checkout quick-start omits pinned Moto and required Chromium | Done | Done | {"priority": "P2"} https://github.com/Collaboration95/dc2/issues/247 |
| [P2][Demo] Local V1 fallback has no interactive web/worker entry point; v1-serve is API-only | Done | Done | {"priority": "P2"} https://github.com/Collaboration95/dc2/issues/248 |
| [P2][Docs] Refresh V1/V2 status, as-built limitations and broken documentation links | Done | Done | {"priority": "P2"} https://github.com/Collaboration95/dc2/issues/249 |
| [P2][Evidence] Archive redacted proof receipts and retain CI artifacts through submission | Done | Done | {"priority": "P2"} https://github.com/Collaboration95/dc2/issues/250 |
| [P3][CI] Scan exact V1 Media, Processing and encoder images with source/image identities | Done | In progress | {} https://github.com/Collaboration95/dc2/issues/251 |
| [P2][Evidence] Publish actual-versus-target results with correct workload and source attribution | Done | Done | {"priority": "P2"} https://github.com/Collaboration95/dc2/issues/252 |
| [P2][Planning] Reconcile Project 14, native issue relationships and stale epic acceptance | Done | Done | {"priority": "P2"} https://github.com/Collaboration95/dc2/issues/253 |
| [P2][Demo] Package durable web, CLI and pipeline recordings and verify team access | Todo | Backlog | {"priority": "P2"} https://github.com/Collaboration95/dc2/issues/254 |
| [P2][Release] Pin a sanitized demo release manifest and final freeze checklist | Done | Backlog | {"linked pull requests": ["https://github.com/Collaboration95/dc2/pull/278"], "priority": "P2"} https://github.com/Collaboration95/dc2/issues/255 |
| [P2][V2-live] Clarify lost-marker recovery bounds and test the degraded dependency path | Done | Done | {"priority": "P2"} https://github.com/Collaboration95/dc2/issues/256 |
| [P2][Submission prep] Verify course cutoffs, progress-report receipt and peer assessment | Todo | Backlog | {"priority": "P2"} https://github.com/Collaboration95/dc2/issues/257 |
| [Close-out] Audit handoff: 6 bugs, 9 easy wins, dependencies and freeze order | In Progress | In progress | {} https://github.com/Collaboration95/dc2/issues/258 |

### Complete issue inventory

| Issue / URL | State | Created UTC | Closed UTC | Updated UTC | Assignees | Milestone | Labels |
|---|---|---|---|---|---|---|---|
| #1 [E0] Reviewed plan and auditable delivery https://github.com/Collaboration95/dc2/issues/1 | CLOSED | 2026-10-12T16:03:54Z | 2026-10-12T16:22:29Z | 2026-10-12T16:22:29Z | — | — | epic, pre-aws, planning |
| #2 [E1] Reproducible local workspace and fast checks https://github.com/Collaboration95/dc2/issues/2 | CLOSED | 2026-10-12T16:03:56Z | 2026-10-12T17:19:37Z | 2026-10-12T17:19:37Z | — | — | epic, pre-aws, foundation |
| #3 [E2] Independent processing and reliable attempts https://github.com/Collaboration95/dc2/issues/3 | CLOSED | 2026-10-12T16:03:58Z | 2026-10-12T18:28:29Z | 2026-10-12T18:28:29Z | — | — | epic, pre-aws, processing |
| #4 [E3] Media ownership and compatible public workflow https://github.com/Collaboration95/dc2/issues/4 | CLOSED | 2026-10-12T16:04:00Z | 2026-10-12T19:08:05Z | 2026-10-12T19:08:05Z | — | — | epic, pre-aws, media |
| #5 [E4] Web and independent Publisher CLI https://github.com/Collaboration95/dc2/issues/5 | CLOSED | 2026-10-12T16:04:02Z | 2026-10-12T19:44:42Z | 2026-10-12T19:44:42Z | — | — | epic, pre-aws, clients |
| #6 [E5] Integrated evidence and local release readiness https://github.com/Collaboration95/dc2/issues/6 | CLOSED | 2026-10-12T16:04:04Z | 2026-10-13T01:20:22Z | 2026-10-13T01:20:22Z | — | — | epic, pre-aws, verification |
| #7 [G1] Define epics, persona stories, issue contracts and waves https://github.com/Collaboration95/dc2/issues/7 | CLOSED | 2026-10-12T16:04:07Z | 2026-10-12T16:22:28Z | 2026-10-12T20:06:54Z | — | — | pre-aws, planning |
| #8 [G2] Independently review and correct the delivery plan https://github.com/Collaboration95/dc2/issues/8 | CLOSED | 2026-10-12T16:04:10Z | 2026-10-12T16:22:29Z | 2026-10-12T20:06:57Z | — | — | pre-aws, planning |
| #9 [F1] Install a reproducible root workspace with Make and environment doctor https://github.com/Collaboration95/dc2/issues/9 | CLOSED | 2026-10-12T16:04:14Z | 2026-10-12T17:09:09Z | 2026-10-12T20:06:59Z | — | — | pre-aws, foundation |
| #10 [F2] Establish fast deterministic test tiers and required CI checks https://github.com/Collaboration95/dc2/issues/10 | CLOSED | 2026-10-12T16:04:18Z | 2026-10-12T17:10:15Z | 2026-10-12T20:07:03Z | — | — | pre-aws, foundation |
| #11 [F3] Provide isolated local services, storage and trusted HTTPS topology https://github.com/Collaboration95/dc2/issues/11 | CLOSED | 2026-10-12T16:04:22Z | 2026-10-12T17:09:10Z | 2026-10-12T20:07:05Z | — | — | pre-aws, foundation |
| #12 [P1] Implement attempt lifecycle, stored-source retry and cancellation https://github.com/Collaboration95/dc2/issues/12 | CLOSED | 2026-10-12T16:04:26Z | 2026-10-12T18:28:27Z | 2026-10-12T20:07:08Z | — | — | pre-aws, processing |
| #13 [P2] Run attempt-aware FFmpeg workers with private source and output access https://github.com/Collaboration95/dc2/issues/13 | CLOSED | 2026-10-12T16:04:31Z | 2026-10-12T18:28:28Z | 2026-10-12T20:07:11Z | — | — | pre-aws, processing |
| #14 [P3] Recover worker interruptions and lost queue deliveries https://github.com/Collaboration95/dc2/issues/14 | CLOSED | 2026-10-12T16:04:35Z | 2026-10-12T18:28:28Z | 2026-10-12T20:07:13Z | — | — | pre-aws, processing |
| #15 [M1] Create Media-owned Assets and durable idempotent submission https://github.com/Collaboration95/dc2/issues/15 | CLOSED | 2026-10-12T16:04:39Z | 2026-10-12T19:08:04Z | 2026-10-12T20:07:16Z | — | — | pre-aws, media |
| #16 [M2] Serve compatible status, retry and authorised MP4/HLS playback https://github.com/Collaboration95/dc2/issues/16 | CLOSED | 2026-10-12T16:04:44Z | 2026-10-12T19:08:04Z | 2026-10-12T20:07:18Z | — | — | pre-aws, media |
| #17 [M3] Reconcile pending submissions and preserve edit/delete/operator behavior https://github.com/Collaboration95/dc2/issues/17 | CLOSED | 2026-10-12T16:04:48Z | 2026-10-12T19:08:05Z | 2026-10-12T20:07:21Z | — | — | pre-aws, media |
| #18 [C1] Build the independent Publisher CLI against public APIs https://github.com/Collaboration95/dc2/issues/18 | CLOSED | 2026-10-12T16:04:52Z | 2026-10-12T19:44:41Z | 2026-10-12T20:07:23Z | — | — | pre-aws, clients |
| #19 [C2] Complete browser stored-source retry and idempotent requests https://github.com/Collaboration95/dc2/issues/19 | CLOSED | 2026-10-12T16:04:55Z | 2026-10-12T19:44:41Z | 2026-10-12T20:07:26Z | — | — | pre-aws, clients |
| #20 [V1] Integrate full local workflow and contract regression evidence https://github.com/Collaboration95/dc2/issues/20 | CLOSED | 2026-10-12T16:05:00Z | 2026-10-13T00:49:04Z | 2026-10-13T00:49:04Z | — | — | pre-aws, verification |
| #21 [V2] Exercise recovery faults across both services https://github.com/Collaboration95/dc2/issues/21 | CLOSED | 2026-10-12T16:05:05Z | 2026-10-13T00:49:07Z | 2026-10-13T00:49:07Z | — | — | pre-aws, verification |
| #22 [V3] Measure local performance and worker scaling without misleading claims https://github.com/Collaboration95/dc2/issues/22 | CLOSED | 2026-10-12T16:05:09Z | 2026-10-13T00:49:09Z | 2026-10-13T00:49:09Z | — | — | pre-aws, verification |
| #23 [V4] Automate independent local Processing release, smoke and rollback https://github.com/Collaboration95/dc2/issues/23 | CLOSED | 2026-10-12T16:05:14Z | 2026-10-13T00:49:12Z | 2026-10-13T00:49:12Z | — | — | pre-aws, verification |
| #24 [V5] Review final delivery and publish evidence-based morning handoff https://github.com/Collaboration95/dc2/issues/24 | CLOSED | 2026-10-12T16:05:17Z | 2026-10-13T01:20:21Z | 2026-10-13T01:20:21Z | — | — | pre-aws, verification |
| #33 [E6] Measured performance improvements within demo budget https://github.com/Collaboration95/dc2/issues/33 | CLOSED | 2026-10-13T03:25:43Z | 2026-10-14T14:13:27Z | 2026-10-14T14:24:16Z | — | — | enhancement, epic, pre-aws |
| #34 [PERF] Media API and data access: investigate and remove avoidable work https://github.com/Collaboration95/dc2/issues/34 | CLOSED | 2026-10-13T03:26:08Z | 2026-10-13T03:45:28Z | 2026-10-13T03:45:28Z | — | — | enhancement, media |
| #35 [PERF] Processing worker and media engine: investigate and remove avoidable work https://github.com/Collaboration95/dc2/issues/35 | CLOSED | 2026-10-13T03:26:12Z | 2026-10-13T03:45:29Z | 2026-10-13T03:45:29Z | — | — | enhancement, processing |
| #36 [PERF] Frontend and Publisher: investigate and remove avoidable work https://github.com/Collaboration95/dc2/issues/36 | CLOSED | 2026-10-13T03:26:15Z | 2026-10-13T03:45:29Z | 2026-10-13T03:45:29Z | — | — | enhancement, clients |
| #38 [PERF] Measure CPU quota redistribution under mixed workloads https://github.com/Collaboration95/dc2/issues/38 | CLOSED | 2026-10-13T03:38:49Z | 2026-10-14T14:13:25Z | 2026-10-14T14:24:13Z | — | — | enhancement, verification |
| #39 [PERF] Validate bounded worker scheduling and demo run windows https://github.com/Collaboration95/dc2/issues/39 | CLOSED | 2026-10-13T03:39:21Z | 2026-10-14T14:13:26Z | 2026-10-14T14:24:14Z | — | — | enhancement, processing |
| #41 [V1 epic] Visible domain APIs, ownership and S3 intake https://github.com/Collaboration95/dc2/issues/41 | CLOSED | 2026-10-14T17:39:42Z | 2026-10-17T17:15:29Z | 2026-10-17T17:15:29Z | — | — | epic, planning, media, v1 |
| #42 [V1 epic] Managed runtime, session controls and budget https://github.com/Collaboration95/dc2/issues/42 | CLOSED | 2026-10-14T17:39:47Z | 2026-10-17T17:15:32Z | 2026-10-17T17:15:32Z | — | — | epic, planning, foundation, v1 |
| #43 [V1 epic] Redis-free delivery, finite workers and independent releases https://github.com/Collaboration95/dc2/issues/43 | CLOSED | 2026-10-14T17:39:52Z | 2026-10-17T17:15:35Z | 2026-10-17T17:15:35Z | — | — | epic, planning, processing, v1 |
| #44 [V1 epic] Authentic acceptance and immutable submission baseline https://github.com/Collaboration95/dc2/issues/44 | CLOSED | 2026-10-14T17:39:57Z | 2026-10-17T17:15:37Z | 2026-10-17T17:15:37Z | — | — | epic, planning, verification, v1 |
| #45 [V1] Record actual project account, currency and scoped cloud authorization https://github.com/Collaboration95/dc2/issues/45 | CLOSED | 2026-10-14T17:40:03Z | 2026-10-16T19:27:22Z | 2026-10-16T19:27:22Z | — | — | planning, v1 |
| #46 [V1 decision] Replace the public EC2 HTTP origin with managed HTTPS https://github.com/Collaboration95/dc2/issues/46 | CLOSED | 2026-10-14T17:40:10Z | 2026-10-15T05:44:03Z | 2026-10-15T05:44:03Z | — | — | planning, v1 |
| #47 [AWS2] Wire refreshing ECS credentials into Media storage https://github.com/Collaboration95/dc2/issues/47 | CLOSED | 2026-10-14T17:40:19Z | 2026-10-14T21:49:52Z | 2026-10-14T21:53:29Z | — | — | enhancement |
| #48 [AWS2] Wire ECS writer and cleanup credentials into Processing https://github.com/Collaboration95/dc2/issues/48 | CLOSED | 2026-10-14T17:40:25Z | 2026-10-14T21:49:59Z | 2026-10-14T21:53:31Z | — | — | enhancement |
| #49 [AWS2] Bound signed URL lifetime to the credentials actually used https://github.com/Collaboration95/dc2/issues/49 | CLOSED | 2026-10-14T17:40:31Z | 2026-10-14T21:50:08Z | 2026-10-14T21:53:33Z | — | — | enhancement |
| #50 [AWS2] Define one-subnet state, storage and IAM infrastructure offline https://github.com/Collaboration95/dc2/issues/50 | CLOSED | 2026-10-14T17:40:40Z | 2026-10-14T21:50:18Z | 2026-10-14T21:53:35Z | — | — | enhancement |
| #51 [AWS2] Bootstrap only PostgreSQL, Redis and nginx on retained EBS https://github.com/Collaboration95/dc2/issues/51 | CLOSED | 2026-10-14T17:40:46Z | 2026-10-14T21:50:25Z | 2026-10-14T21:53:36Z | — | — | enhancement |
| #52 [AWS2] Define three services, owner migrations and disposable worker tasks https://github.com/Collaboration95/dc2/issues/52 | CLOSED | 2026-10-14T17:40:52Z | 2026-10-14T21:50:32Z | 2026-10-14T21:53:38Z | — | — | enhancement |
| #53 [AWS2] Configure CloudFront and nginx for private authenticated API traffic https://github.com/Collaboration95/dc2/issues/53 | CLOSED | 2026-10-14T17:41:01Z | 2026-10-14T21:50:39Z | 2026-10-14T21:53:40Z | — | — | enhancement |
| #54 [AWS2] Bind amd64 owner artifacts to tests, scans and ECR digest receipts https://github.com/Collaboration95/dc2/issues/54 | CLOSED | 2026-10-14T17:41:09Z | 2026-10-14T21:50:46Z | 2026-10-14T21:53:42Z | — | — | enhancement |
| #55 [AWS2] Cover extracted services in delivery scans and report execution honestly https://github.com/Collaboration95/dc2/issues/55 | CLOSED | 2026-10-14T17:41:16Z | 2026-10-14T21:50:54Z | 2026-10-14T21:53:44Z | — | — | enhancement |
| #56 [AWS2] Start at most three worker tasks with one serialized operator https://github.com/Collaboration95/dc2/issues/56 | CLOSED | 2026-10-14T17:41:22Z | 2026-10-14T21:51:01Z | 2026-10-14T21:53:46Z | — | — | enhancement |
| #57 [AWS2] Bound cloud worker lifetime and warm-drain before StopTask https://github.com/Collaboration95/dc2/issues/57 | CLOSED | 2026-10-14T17:41:28Z | 2026-10-14T21:51:08Z | 2026-10-14T21:53:48Z | — | — | enhancement |
| #58 [AWS2] Add a small cloud client and safe evidence context https://github.com/Collaboration95/dc2/issues/58 | CLOSED | 2026-10-14T17:41:35Z | 2026-10-14T21:51:15Z | 2026-10-14T21:53:50Z | — | — | enhancement |
| #59 [AWS2] Promote and roll back Processing alone on ECS https://github.com/Collaboration95/dc2/issues/59 | CLOSED | 2026-10-14T17:41:42Z | 2026-10-14T21:51:22Z | 2026-10-14T21:53:52Z | — | — | enhancement |
| #60 [AWS2] Release Media API and reconciler without changing Processing https://github.com/Collaboration95/dc2/issues/60 | CLOSED | 2026-10-14T17:41:51Z | 2026-10-14T21:51:30Z | 2026-10-14T21:53:53Z | — | — | enhancement |
| #61 [AWS2] Open and close sessions with complete task and IP accounting https://github.com/Collaboration95/dc2/issues/61 | CLOSED | 2026-10-14T17:41:58Z | 2026-10-14T21:51:37Z | 2026-10-14T21:53:55Z | — | — | enhancement |
| #62 [AWS2] Export both owned databases at one quiescent boundary https://github.com/Collaboration95/dc2/issues/62 | CLOSED | 2026-10-14T17:42:09Z | 2026-10-14T21:51:44Z | 2026-10-14T21:53:57Z | — | — | enhancement |
| #63 [V1 evidence] Deploy the approved target and prove real workflow boundaries https://github.com/Collaboration95/dc2/issues/63 | CLOSED | 2026-10-14T17:42:16Z | 2026-10-17T12:08:37Z | 2026-10-17T12:08:37Z | — | — | planning, verification, v1 |
| #64 [V1 evidence] Prove 1/2/3 encoders and bounded SQS recovery on AWS https://github.com/Collaboration95/dc2/issues/64 | CLOSED | 2026-10-14T17:42:29Z | 2026-10-17T12:08:39Z | 2026-10-17T12:08:39Z | — | — | planning, verification, v1 |
| #65 [V1 evidence] Capture independent Lambda/Fargate release and rollback https://github.com/Collaboration95/dc2/issues/65 | CLOSED | 2026-10-14T17:42:36Z | 2026-10-17T12:08:41Z | 2026-10-17T12:08:41Z | — | — | planning, verification, v1 |
| #66 [V1 evidence] Measure warm API latency with an independent Fargate generator https://github.com/Collaboration95/dc2/issues/66 | CLOSED | 2026-10-14T17:42:46Z | 2026-10-17T16:36:16Z | 2026-10-17T16:36:16Z | — | — | verification, v1 |
| #67 [V1 evidence] Reconcile actual spend, close state and final V1 handoff https://github.com/Collaboration95/dc2/issues/67 | CLOSED | 2026-10-14T17:42:53Z | 2026-10-17T17:15:08Z | 2026-10-18T00:12:46Z | — | — | planning, verification, v1 |
| #68 [V2 experiment] Optional unattended worker starts and further cost cuts https://github.com/Collaboration95/dc2/issues/68 | CLOSED | 2026-10-14T17:43:45Z | 2026-10-21T07:45:02Z | 2026-10-21T07:45:02Z | — | — | enhancement, processing, v2 |
| #80 [V2 epic] Optional measured migrations after accepted V1 https://github.com/Collaboration95/dc2/issues/80 | CLOSED | 2026-10-15T05:07:58Z | 2026-10-21T07:45:00Z | 2026-10-21T07:45:00Z | — | — | epic, planning, v2 |
| #81 [V1] Freeze gateway routes, trusted identity and message contracts https://github.com/Collaboration95/dc2/issues/81 | CLOSED | 2026-10-15T05:08:00Z | 2026-10-16T19:16:45Z | 2026-10-16T19:16:45Z | — | — | planning, v1 |
| #82 [V1] Package Media Lambda with native credentials and owned SQL https://github.com/Collaboration95/dc2/issues/82 | CLOSED | 2026-10-15T05:08:04Z | 2026-10-16T19:16:48Z | 2026-10-16T19:16:48Z | — | — | media, v1 |
| #83 [V1] Package Processing Lambda API and owned job lifecycle https://github.com/Collaboration95/dc2/issues/83 | CLOSED | 2026-10-15T05:08:08Z | 2026-10-16T19:16:51Z | 2026-10-16T19:16:51Z | — | — | processing, v1 |
| #84 [V1] Replace Redis/RQ delivery with SQS and durable SQL repair https://github.com/Collaboration95/dc2/issues/84 | CLOSED | 2026-10-15T05:08:11Z | 2026-10-16T19:16:54Z | 2026-10-16T19:16:54Z | — | — | processing, v1 |
| #85 [V1] Replace peer calls with commands, results and owned projections https://github.com/Collaboration95/dc2/issues/85 | CLOSED | 2026-10-15T05:08:14Z | 2026-10-16T19:16:57Z | 2026-10-16T19:16:57Z | — | — | media, v1 |
| #86 [V1] Move browser and Publisher uploads directly to authorized S3 https://github.com/Collaboration95/dc2/issues/86 | CLOSED | 2026-10-15T05:08:18Z | 2026-10-16T19:17:00Z | 2026-10-16T19:17:00Z | — | — | clients, v1 |
| #87 [V1] Run finite SQS Fargate encoders and remove source callbacks https://github.com/Collaboration95/dc2/issues/87 | CLOSED | 2026-10-15T05:08:21Z | 2026-10-16T19:17:03Z | 2026-10-16T19:17:03Z | — | — | processing, v1 |
| #88 [V1] Implement bounded Lambda repair and late-output cleanup https://github.com/Collaboration95/dc2/issues/88 | CLOSED | 2026-10-15T05:08:25Z | 2026-10-16T19:17:06Z | 2026-10-16T19:17:06Z | — | — | processing, v1 |
| #89 [V1] Define managed Gateway/Lambda/SQS/Aurora infrastructure offline https://github.com/Collaboration95/dc2/issues/89 | CLOSED | 2026-10-15T05:08:28Z | 2026-10-16T19:17:09Z | 2026-10-16T19:17:09Z | — | — | foundation, v1 |
| #90 [V1] Adapt independent releases, migrations and rollback to Lambda/Fargate https://github.com/Collaboration95/dc2/issues/90 | CLOSED | 2026-10-15T05:08:32Z | 2026-10-16T19:17:11Z | 2026-10-16T19:17:11Z | — | — | verification, v1 |
| #91 [V1] Adapt session open/close, cost model and evidence protocols https://github.com/Collaboration95/dc2/issues/91 | CLOSED | 2026-10-15T05:08:35Z | 2026-10-16T19:17:14Z | 2026-10-16T19:17:14Z | — | — | foundation, v1 |
| #92 [V1] Verify the complete Redis-free workflow locally https://github.com/Collaboration95/dc2/issues/92 | CLOSED | 2026-10-15T05:08:38Z | 2026-10-16T19:17:17Z | 2026-10-16T19:17:17Z | — | — | verification, v1 |
| #93 [V2 experiment] Benchmark bounded short encodes on Lambda https://github.com/Collaboration95/dc2/issues/93 | CLOSED | 2026-10-15T05:10:25Z | 2026-10-17T17:00:15Z | 2026-10-21T15:39:52Z | — | — | processing, v2 |
| #94 [V2 experiment] Measure separate database clusters and pause behavior https://github.com/Collaboration95/dc2/issues/94 | CLOSED | 2026-10-15T05:10:28Z | 2026-10-17T17:00:18Z | 2026-10-17T17:00:18Z | — | — | foundation, v2 |
| #96 Prevent unattended local VM resource use; replace 8 CPU / 8 GiB defaults https://github.com/Collaboration95/dc2/issues/96 | CLOSED | 2026-10-15T06:38:45Z | 2026-10-17T18:21:57Z | 2026-10-17T18:21:57Z | — | — | bug, enhancement |
| #107 [V1] Documented local DLQ redrive crashes on pinned Moto https://github.com/Collaboration95/dc2/issues/107 | CLOSED | 2026-10-16T17:08:51Z | 2026-10-16T17:22:20Z | 2026-10-16T17:22:20Z | — | — | bug, v1 |
| #108 [V1] Primary handoff still describes implemented local runtime as pending https://github.com/Collaboration95/dc2/issues/108 | CLOSED | 2026-10-16T17:08:53Z | 2026-10-16T17:22:22Z | 2026-10-16T17:22:22Z | — | — | bug, v1 |
| #111 [V1] Latency window validation rejects exact 180s windows on float clock values https://github.com/Collaboration95/dc2/issues/111 | CLOSED | 2026-10-16T17:43:14Z | 2026-10-16T18:15:55Z | 2026-10-16T18:15:55Z | — | — | bug, v1 |
| #113 [V1] Deploy resume publishes DB passwords that bootstrap never applied https://github.com/Collaboration95/dc2/issues/113 | CLOSED | 2026-10-16T17:54:03Z | 2026-10-16T18:15:40Z | 2026-10-16T18:15:40Z | — | — | bug, v1 |
| #114 [V1] Adopted-bucket teardown deletes other runs' template object versions https://github.com/Collaboration95/dc2/issues/114 | CLOSED | 2026-10-16T17:54:05Z | 2026-10-16T18:15:44Z | 2026-10-16T18:15:44Z | — | — | bug, v1 |
| #115 [V1] Processing cleanup roles lack s3:ListBucketVersions, so outputs are never cleaned https://github.com/Collaboration95/dc2/issues/115 | CLOSED | 2026-10-16T17:54:07Z | 2026-10-16T18:24:57Z | 2026-10-16T18:24:57Z | — | — | bug, v1 |
| #116 [V1] SQS queue policies block native DLQ redrive and operator poison injection https://github.com/Collaboration95/dc2/issues/116 | CLOSED | 2026-10-16T17:54:09Z | 2026-10-16T18:25:00Z | 2026-10-16T18:25:00Z | — | — | bug, v1 |
| #117 [V1] Failed edits leave permanent staged source-object orphans https://github.com/Collaboration95/dc2/issues/117 | CLOSED | 2026-10-16T17:54:11Z | 2026-10-16T18:25:03Z | 2026-10-16T18:25:03Z | — | — | bug, v1 |
| #118 [V1] Teardown empties storage before writers are quiescent https://github.com/Collaboration95/dc2/issues/118 | CLOSED | 2026-10-16T17:54:14Z | 2026-10-16T18:15:46Z | 2026-10-16T18:15:46Z | — | — | bug, v1 |
| #119 [V1] Queued-work repair backoff exceeds the 120-second recovery bound https://github.com/Collaboration95/dc2/issues/119 | CLOSED | 2026-10-16T17:54:16Z | 2026-10-16T18:25:06Z | 2026-10-16T18:25:06Z | — | — | bug, v1 |
| #120 [V1] Cloud workflow evidence cannot resume after finalization https://github.com/Collaboration95/dc2/issues/120 | CLOSED | 2026-10-16T17:54:18Z | 2026-10-16T18:15:49Z | 2026-10-16T18:15:49Z | — | — | bug, v1 |
| #121 [V1] Standalone DLQ commands can fall back to the wrong AWS account https://github.com/Collaboration95/dc2/issues/121 | CLOSED | 2026-10-16T17:54:20Z | 2026-10-16T18:15:51Z | 2026-10-16T18:15:51Z | — | — | bug, v1 |
| #124 [V1] Bootstrap password-loss recovery forgets a possibly live bootstrap task https://github.com/Collaboration95/dc2/issues/124 | CLOSED | 2026-10-16T18:34:41Z | 2026-10-16T18:47:28Z | 2026-10-16T18:47:28Z | — | — | bug, v1 |
| #125 [V1] Bootstrap resume crashes when ECS no longer lists the stopped task https://github.com/Collaboration95/dc2/issues/125 | CLOSED | 2026-10-16T18:34:43Z | 2026-10-16T18:47:31Z | 2026-10-16T18:47:31Z | — | — | bug, v1 |
| #126 [V1] Teardown cannot recover from late writes via still-valid presigned grants https://github.com/Collaboration95/dc2/issues/126 | CLOSED | 2026-10-16T18:34:45Z | 2026-10-16T18:47:33Z | 2026-10-16T18:47:33Z | — | — | bug, v1 |
| #127 [V1] Stale repair duplicates can exhaust an encoder's whole message allowance https://github.com/Collaboration95/dc2/issues/127 | CLOSED | 2026-10-16T18:34:47Z | 2026-10-16T18:54:30Z | 2026-10-16T18:54:30Z | — | — | bug, v1 |
| #128 [V1] Staged-object cleanup timeout releases the adoption lock before S3 deletion finishes https://github.com/Collaboration95/dc2/issues/128 | CLOSED | 2026-10-16T18:34:49Z | 2026-10-16T18:54:33Z | 2026-10-16T18:54:33Z | — | — | bug, v1 |
| #131 [V1] Unjournaled bootstrap tasks found via startedBy are not awaited until STOPPED https://github.com/Collaboration95/dc2/issues/131 | CLOSED | 2026-10-16T18:59:17Z | 2026-10-16T19:10:32Z | 2026-10-16T19:10:32Z | — | — | bug, v1 |
| #134 [V1] Image verifier expects pre-sanitization handler errors; 4 RIE checks fail (LOCAL_ARTIFACT_FAIL) https://github.com/Collaboration95/dc2/issues/134 | CLOSED | 2026-10-16T19:20:21Z | 2026-10-16T19:38:39Z | 2026-10-16T19:38:39Z | — | — | bug, v1 |
| #137 [V1] Browser acceptance leg is flaky in CI and its failure detail is not surfaced https://github.com/Collaboration95/dc2/issues/137 | CLOSED | 2026-10-16T19:52:21Z | 2026-10-16T20:43:10Z | 2026-10-16T20:43:10Z | — | — | bug, v1 |
| #138 [V1] deploy --dry-run always fails at images when given real build evidence https://github.com/Collaboration95/dc2/issues/138 | CLOSED | 2026-10-16T19:53:04Z | 2026-10-16T20:55:17Z | 2026-10-16T20:55:17Z | — | — | bug, v1 |
| #143 [V1] Browser acceptance still flaky after #139: native HLS leg 'No redirected segment read' https://github.com/Collaboration95/dc2/issues/143 | CLOSED | 2026-10-17T01:05:26Z | 2026-10-17T01:22:54Z | 2026-10-17T01:22:54Z | — | — | bug, v1 |
| #147 [V1] Teardown receipt reports ITEMS_REMAIN for resources the tagging API still lists after deletion https://github.com/Collaboration95/dc2/issues/147 | CLOSED | 2026-10-17T02:08:41Z | 2026-10-17T03:17:59Z | 2026-10-17T03:17:59Z | — | — | bug, v1 |
| #150 [V1] Release proof (#65) needs an in-VPC SQL station that V1 does not have; read schema revision via a finite task https://github.com/Collaboration95/dc2/issues/150 | CLOSED | 2026-10-17T03:18:29Z | 2026-10-17T03:53:38Z | 2026-10-17T03:53:38Z | — | — | bug, v1 |
| #151 [V1] #66 latency harness: cold-wake gives up instead of waiting for pause; generator runs against the 5 rps session gate https://github.com/Collaboration95/dc2/issues/151 | CLOSED | 2026-10-17T03:41:05Z | 2026-10-17T12:08:44Z | 2026-10-17T12:08:44Z | — | — | bug, v1 |
| #156 [V1] release abandon: accept a migration task ECS has forgotten when it is provably not running https://github.com/Collaboration95/dc2/issues/156 | CLOSED | 2026-10-17T10:12:59Z | 2026-10-17T15:28:12Z | 2026-10-17T15:28:12Z | — | — | v1 |
| #159 [Improvement] Reduce development CI wait with selective checks and staged full verification https://github.com/Collaboration95/dc2/issues/159 | CLOSED | 2026-10-17T12:27:49Z | 2026-10-17T14:31:08Z | 2026-10-17T14:31:08Z | — | — | enhancement, epic |
| #160 [CI improvement] Define a small dev gate and preserve strict full-mode coverage https://github.com/Collaboration95/dc2/issues/160 | CLOSED | 2026-10-17T12:28:02Z | 2026-10-17T14:30:45Z | 2026-10-17T14:30:45Z | — | — | enhancement |
| #161 [CI improvement] Select dev checks by changed paths with conservative fallbacks https://github.com/Collaboration95/dc2/issues/161 | CLOSED | 2026-10-17T12:28:05Z | 2026-10-17T14:30:49Z | 2026-10-17T14:30:49Z | — | — | enhancement |
| #162 [CI improvement] Run V1 offline checks and live acceptance in parallel https://github.com/Collaboration95/dc2/issues/162 | CLOSED | 2026-10-17T12:28:09Z | 2026-10-17T14:30:53Z | 2026-10-17T14:30:53Z | — | — | enhancement |
| #163 [CI improvement] Move inherited full browser acceptance out of routine dev PRs https://github.com/Collaboration95/dc2/issues/163 | CLOSED | 2026-10-17T12:28:12Z | 2026-10-17T14:30:57Z | 2026-10-17T14:30:57Z | — | — | enhancement |
| #164 [CI improvement] Schedule expensive scans appropriately and report inactive checks honestly https://github.com/Collaboration95/dc2/issues/164 | CLOSED | 2026-10-17T12:28:16Z | 2026-10-17T14:31:00Z | 2026-10-17T14:31:00Z | — | — | enhancement |
| #165 [CI improvement] Measure the new dev gate and document agent wait behavior https://github.com/Collaboration95/dc2/issues/165 | CLOSED | 2026-10-17T12:28:20Z | 2026-10-17T14:31:04Z | 2026-10-17T14:31:04Z | — | — | enhancement |
| #178 [Close-out epic] Visible DevOps pipeline: CI, deploy, smoke, release and rollback https://github.com/Collaboration95/dc2/issues/178 | CLOSED | 2026-10-17T16:47:10Z | 2026-10-18T14:28:22Z | 2026-10-18T14:28:22Z | — | — | epic, verification, closeout |
| #179 [Close-out epic] One cloud session from project2-v1: pipeline run, backlog scaling, demo recording https://github.com/Collaboration95/dc2/issues/179 | CLOSED | 2026-10-17T16:47:11Z | 2026-10-19T18:09:32Z | 2026-10-19T18:09:32Z | — | — | epic, verification, closeout |
| #180 [Close-out epic] As-built architecture, DDD and evidence documentation https://github.com/Collaboration95/dc2/issues/180 | CLOSED | 2026-10-17T16:47:13Z | 2026-10-18T14:28:24Z | 2026-10-18T14:28:24Z | — | — | documentation, epic, closeout |
| #181 [Close-out epic] Presentation (26 Oct) and final report (16 Nov) — DO NOT START without human approval https://github.com/Collaboration95/dc2/issues/181 | OPEN | 2026-10-17T16:47:15Z | — | 2026-10-17T17:00:10Z | — | — | documentation, epic, planning, closeout, needs-human-approval |
| #182 [Close-out] GitHub Actions CD workflow wrapping the V1 deploy, release and teardown scripts https://github.com/Collaboration95/dc2/issues/182 | CLOSED | 2026-10-17T16:47:17Z | 2026-10-18T02:52:36Z | 2026-10-18T02:52:43Z | — | — | enhancement, verification, closeout |
| #183 [Close-out] Add secret scanning to CI https://github.com/Collaboration95/dc2/issues/183 | CLOSED | 2026-10-17T16:47:18Z | 2026-10-17T17:30:23Z | 2026-10-17T17:30:23Z | — | — | verification, closeout |
| #184 [Close-out] Publish OpenAPI documents for the Media and Processing public APIs with a drift check https://github.com/Collaboration95/dc2/issues/184 | CLOSED | 2026-10-17T16:47:20Z | 2026-10-17T17:30:25Z | 2026-10-17T17:30:25Z | — | — | documentation, verification, closeout |
| #185 [Close-out] Backlog throughput mode for the capacity proof (jobs/min at cap 1, 2, 3) https://github.com/Collaboration95/dc2/issues/185 | CLOSED | 2026-10-17T16:47:22Z | 2026-10-17T17:24:27Z | 2026-10-17T17:24:27Z | — | — | processing, verification, closeout |
| #186 [Close-out] Run the single cloud session: pipeline deploy, smoke, backlog scaling, independent release, demo recording, teardown https://github.com/Collaboration95/dc2/issues/186 | CLOSED | 2026-10-17T16:47:24Z | 2026-10-19T18:09:29Z | 2026-10-19T18:09:29Z | — | — | verification, closeout |
| #187 [Close-out] As-built DDD model: language, two bounded contexts, aggregates, commands/events, context map https://github.com/Collaboration95/dc2/issues/187 | CLOSED | 2026-10-17T16:47:25Z | 2026-10-17T18:06:55Z | 2026-10-17T18:06:55Z | — | — | documentation, closeout |
| #188 [Close-out] ADR register and proposal→V1 deviation table, logical and physical diagrams https://github.com/Collaboration95/dc2/issues/188 | CLOSED | 2026-10-17T16:47:27Z | 2026-10-17T18:06:57Z | 2026-10-17T18:06:57Z | — | — | documentation, closeout |
| #189 [Close-out] Evidence index: quality scenarios, targets and results, with local and cloud labelled https://github.com/Collaboration95/dc2/issues/189 | CLOSED | 2026-10-17T16:47:29Z | 2026-10-18T00:29:54Z | 2026-10-18T00:29:54Z | — | — | documentation, verification, closeout |
| #190 [Close-out] Submission repo hygiene: start-here README, historical docs labelled, stale branches and worktrees removed https://github.com/Collaboration95/dc2/issues/190 | CLOSED | 2026-10-17T16:47:31Z | 2026-10-17T18:20:34Z | 2026-10-17T18:20:34Z | — | — | documentation, closeout |
| #191 [Close-out] Effort and milestone ledger per member, plus progress report https://github.com/Collaboration95/dc2/issues/191 | OPEN | 2026-10-17T16:47:33Z | — | 2026-10-21T06:10:52Z | — | — | planning, closeout, needs-human-approval |
| #192 [Close-out] Presentation deck, demo script and rehearsal for 26 Oct https://github.com/Collaboration95/dc2/issues/192 | OPEN | 2026-10-17T16:47:35Z | — | 2026-10-17T17:00:06Z | — | — | documentation, closeout, needs-human-approval |
| #193 [Close-out] Final report per the course template, with presentation feedback https://github.com/Collaboration95/dc2/issues/193 | OPEN | 2026-10-17T16:47:37Z | — | 2026-10-21T06:10:51Z | — | — | documentation, closeout, needs-human-approval |
| #195 [Close-out epic] Microservices hardening from the architecture audit https://github.com/Collaboration95/dc2/issues/195 | CLOSED | 2026-10-17T17:05:42Z | 2026-10-18T14:28:26Z | 2026-10-18T14:28:26Z | — | — | epic, closeout |
| #196 [Close-out] Prove failure isolation: Media accepts uploads while Processing is down https://github.com/Collaboration95/dc2/issues/196 | CLOSED | 2026-10-17T17:05:44Z | 2026-10-18T00:12:42Z | 2026-10-18T00:12:42Z | — | — | processing, verification, closeout |
| #197 [Close-out] Remove legacy peer-HTTP code from the V1 service images https://github.com/Collaboration95/dc2/issues/197 | CLOSED | 2026-10-17T17:05:46Z | 2026-10-17T17:55:53Z | 2026-10-17T17:55:53Z | — | — | processing, media, closeout |
| #198 [Close-out] Contract versioning policy and consumer-driven contract tests per service https://github.com/Collaboration95/dc2/issues/198 | CLOSED | 2026-10-17T17:05:47Z | 2026-10-17T17:55:56Z | 2026-10-17T17:55:56Z | — | — | verification, closeout |
| #199 [Close-out] Per-service CI: path-filtered Media and Processing jobs, plus CODEOWNERS https://github.com/Collaboration95/dc2/issues/199 | CLOSED | 2026-10-17T17:05:49Z | 2026-10-17T17:40:07Z | 2026-10-17T17:40:07Z | — | — | verification, closeout |
| #200 [Close-out] Per-service observability: DLQ and error alarms, dashboard, least-privilege environment https://github.com/Collaboration95/dc2/issues/200 | CLOSED | 2026-10-17T17:05:51Z | 2026-10-17T17:55:58Z | 2026-10-17T17:55:58Z | — | — | foundation, closeout |
| #210 [Close-out] Remove peer-era leftovers from the V1 packages (found by the architecture docs review) https://github.com/Collaboration95/dc2/issues/210 | CLOSED | 2026-10-17T18:06:59Z | 2026-10-18T00:37:44Z | 2026-10-18T00:37:44Z | — | — | processing, media, closeout |
| #223 CD smoke: the single encoder can start before the command reaches the work queue (race after a Processing release) https://github.com/Collaboration95/dc2/issues/223 | CLOSED | 2026-10-17T23:22:38Z | 2026-10-18T02:52:33Z | 2026-10-18T02:52:33Z | — | — | — |
| #225 CD teardown fails at td-session-close on a stack with the unattended launcher (laptop close works) https://github.com/Collaboration95/dc2/issues/225 | CLOSED | 2026-10-18T00:06:10Z | 2026-10-18T02:52:30Z | 2026-10-18T02:52:30Z | — | — | — |
| #229 [Close-out] AWS security-negatives proof: cross-owner, tampered/expired URLs, oversize upload, external port scan https://github.com/Collaboration95/dc2/issues/229 | CLOSED | 2026-10-18T00:30:18Z | 2026-10-19T13:32:45Z | 2026-10-19T13:32:45Z | — | — | verification, closeout |
| #234 [V2 epic] One always-on environment that updates in place and scales to zero https://github.com/Collaboration95/dc2/issues/234 | CLOSED | 2026-10-18T02:25:35Z | 2026-10-19T18:09:35Z | 2026-10-19T18:09:35Z | — | — | epic, v2, v2-live |
| #235 [V2-live] Persistent named environment: CD updates one stack in place https://github.com/Collaboration95/dc2/issues/235 | CLOSED | 2026-10-18T02:25:37Z | 2026-10-18T14:28:27Z | 2026-10-18T14:28:27Z | — | — | v2, closeout, v2-live |
| #236 [V2-live] Remove booked sessions from the normal path: always-on API and consumers https://github.com/Collaboration95/dc2/issues/236 | CLOSED | 2026-10-18T02:25:39Z | 2026-10-18T14:28:29Z | 2026-10-18T14:28:29Z | — | — | v2, closeout, v2-live |
| #237 [V2-live] Encoders scale 0→3→0 with the queue, started on enqueue https://github.com/Collaboration95/dc2/issues/237 | CLOSED | 2026-10-18T02:25:41Z | 2026-10-19T18:09:27Z | 2026-10-19T18:09:27Z | — | — | v2, closeout, v2-live |
| #238 [V2-live] Deploy dc2-live once, verify, and keep it running https://github.com/Collaboration95/dc2/issues/238 | CLOSED | 2026-10-18T02:25:42Z | 2026-10-19T18:09:24Z | 2026-10-19T18:09:24Z | — | — | v2, closeout, v2-live |
| #243 [P1][Clients] Account switching exposes prior-owner library cards and playback capabilities https://github.com/Collaboration95/dc2/issues/243 | CLOSED | 2026-10-18T10:55:34Z | 2026-10-18T13:32:05Z | 2026-10-18T13:32:05Z | — | — | bug, media, clients, closeout |
| #244 [P1][V2-live] Processing API retry/cancel bypass idle activity markers and can stall repair https://github.com/Collaboration95/dc2/issues/244 | CLOSED | 2026-10-18T10:55:36Z | 2026-10-18T13:32:14Z | 2026-10-18T13:32:14Z | — | — | bug, processing, v2, closeout, v2-live |
| #245 [P2][Publisher] Quick-start and CLI help use /api instead of the V1 /api/media base https://github.com/Collaboration95/dc2/issues/245 | CLOSED | 2026-10-18T10:55:37Z | 2026-10-18T13:32:08Z | 2026-10-18T13:32:08Z | — | — | bug, documentation, clients, closeout |
| #246 [P2][Clients] Library and Admin list failures are shown as successful empty results https://github.com/Collaboration95/dc2/issues/246 | CLOSED | 2026-10-18T10:55:39Z | 2026-10-18T13:32:11Z | 2026-10-18T13:32:11Z | — | — | bug, clients, closeout |
| #247 [P2][Local V1] Clean-checkout quick-start omits pinned Moto and required Chromium https://github.com/Collaboration95/dc2/issues/247 | CLOSED | 2026-10-18T10:55:41Z | 2026-10-18T13:32:19Z | 2026-10-18T13:32:19Z | — | — | bug, documentation, foundation, verification, closeout |
| #248 [P2][Demo] Local V1 fallback has no interactive web/worker entry point; v1-serve is API-only https://github.com/Collaboration95/dc2/issues/248 | CLOSED | 2026-10-18T10:55:43Z | 2026-10-18T13:32:22Z | 2026-10-18T13:32:22Z | — | — | bug, documentation, foundation, verification, closeout |
| #249 [P2][Docs] Refresh V1/V2 status, as-built limitations and broken documentation links https://github.com/Collaboration95/dc2/issues/249 | CLOSED | 2026-10-18T11:06:18Z | 2026-10-18T13:32:24Z | 2026-10-18T13:32:24Z | — | — | documentation, closeout |
| #250 [P2][Evidence] Archive redacted proof receipts and retain CI artifacts through submission https://github.com/Collaboration95/dc2/issues/250 | CLOSED | 2026-10-18T11:06:20Z | 2026-10-18T13:32:26Z | 2026-10-18T13:32:26Z | — | — | documentation, verification, closeout |
| #251 [P3][CI] Scan exact V1 Media, Processing and encoder images with source/image identities https://github.com/Collaboration95/dc2/issues/251 | CLOSED | 2026-10-18T11:06:22Z | 2026-10-18T14:49:15Z | 2026-10-18T14:49:15Z | — | — | enhancement, verification, closeout |
| #252 [P2][Evidence] Publish actual-versus-target results with correct workload and source attribution https://github.com/Collaboration95/dc2/issues/252 | CLOSED | 2026-10-18T11:06:24Z | 2026-10-18T13:32:29Z | 2026-10-18T13:32:29Z | — | — | documentation, verification, closeout |
| #253 [P2][Planning] Reconcile Project 14, native issue relationships and stale epic acceptance https://github.com/Collaboration95/dc2/issues/253 | CLOSED | 2026-10-18T11:06:26Z | 2026-10-18T14:30:52Z | 2026-10-18T14:30:52Z | — | — | planning, closeout |
| #254 [P2][Demo] Package durable web, CLI and pipeline recordings and verify team access https://github.com/Collaboration95/dc2/issues/254 | OPEN | 2026-10-18T11:06:27Z | — | 2026-10-20T04:45:30Z | — | — | documentation, clients, verification, closeout |
| #255 [P2][Release] Pin a sanitized demo release manifest and final freeze checklist https://github.com/Collaboration95/dc2/issues/255 | CLOSED | 2026-10-18T11:06:29Z | 2026-10-20T04:51:21Z | 2026-10-20T04:51:21Z | — | — | planning, verification, closeout |
| #256 [P2][V2-live] Clarify lost-marker recovery bounds and test the degraded dependency path https://github.com/Collaboration95/dc2/issues/256 | CLOSED | 2026-10-18T11:06:31Z | 2026-10-18T13:32:17Z | 2026-10-18T13:32:17Z | — | — | documentation, processing, verification, v2, closeout, v2-live |
| #257 [P2][Submission prep] Verify course cutoffs, progress-report receipt and peer assessment https://github.com/Collaboration95/dc2/issues/257 | OPEN | 2026-10-18T11:06:32Z | — | 2026-10-20T04:58:23Z | — | — | documentation, planning, closeout |
| #258 [Close-out] Audit handoff: 6 bugs, 9 easy wins, dependencies and freeze order https://github.com/Collaboration95/dc2/issues/258 | OPEN | 2026-10-18T11:08:10Z | — | 2026-10-18T14:49:29Z | — | — | planning, verification, closeout |
| #270 [V2-live] Duplicate ProcessingWork sends: 21 messages for 9 jobs, 10 left visible after all jobs finished https://github.com/Collaboration95/dc2/issues/270 | CLOSED | 2026-10-19T15:06:27Z | 2026-10-19T15:33:07Z | 2026-10-19T17:23:02Z | — | — | closeout |
| #271 [Media] Finalize returns 503 when S3 refused an oversized upload; should be 4xx https://github.com/Collaboration95/dc2/issues/271 | CLOSED | 2026-10-19T15:06:30Z | 2026-10-20T10:57:26Z | 2026-10-20T10:57:26Z | — | — | closeout |

### Project 2 PR authorship

Window: 2026-10-04 00:00 UTC (proposal submission) through inventory time. Counts use PR creation date; merged count is those PRs whose current state is MERGED. This measures recorded account authorship, not human hours or design ownership.

| GitHub author | PRs opened in window | Merged | Closed unmerged | Open |
|---|---|---|---|---|
| Collaboration95 | 170 | 164 | 5 | 1 |

| PR / URL | Author | Created UTC | Merged UTC | State |
|---|---|---|---|---|
| #25 Plan pre-AWS delivery with persona-linked issues and staged acceptance https://github.com/Collaboration95/dc2/pull/25 | Collaboration95 | 2026-10-12T16:10:36Z | 2026-10-12T16:22:26Z | MERGED |
| #26 Establish reproducible local setup and fast isolated verification https://github.com/Collaboration95/dc2/pull/26 | Collaboration95 | 2026-10-12T17:01:46Z | 2026-10-12T17:09:08Z | MERGED |
| #27 Reuse verified cached storage builds in browser CI https://github.com/Collaboration95/dc2/pull/27 | Collaboration95 | 2026-10-12T17:14:07Z | 2026-10-12T17:19:35Z | MERGED |
| #28 Complete Processing attempts, worker execution and recovery https://github.com/Collaboration95/dc2/pull/28 | Collaboration95 | 2026-10-12T18:00:22Z | 2026-10-12T18:28:25Z | MERGED |
| #29 Integrate independent Media ownership and durable public workflows https://github.com/Collaboration95/dc2/pull/29 | Collaboration95 | 2026-10-12T18:52:14Z | 2026-10-12T19:08:02Z | MERGED |
| #30 Deliver independent Publisher and reliable browser mutation replay https://github.com/Collaboration95/dc2/pull/30 | Collaboration95 | 2026-10-12T19:30:29Z | 2026-10-12T19:44:39Z | MERGED |
| #31 Complete local workflow, recovery, scaling and release acceptance https://github.com/Collaboration95/dc2/pull/31 | Collaboration95 | 2026-10-12T19:47:27Z | 2026-10-13T00:41:36Z | MERGED |
| #32 Wait for PostgreSQL TCP readiness before starting migrations https://github.com/Collaboration95/dc2/pull/32 | Collaboration95 | 2026-10-13T01:06:09Z | 2026-10-13T01:13:20Z | MERGED |
| #37 Reduce login connection occupancy and media file I/O https://github.com/Collaboration95/dc2/pull/37 | Collaboration95 | 2026-10-13T03:37:45Z | 2026-10-13T03:45:27Z | MERGED |
| #40 Resolve local quota and worker-window experiments; prepare AWS demo https://github.com/Collaboration95/dc2/pull/40 | Collaboration95 | 2026-10-14T13:52:58Z | 2026-10-14T14:13:23Z | MERGED |
| #69 Publish audited lean AWS readiness backlog https://github.com/Collaboration95/dc2/pull/69 | Collaboration95 | 2026-10-14T18:05:58Z | 2026-10-14T18:27:19Z | MERGED |
| #70 Integrate reviewed AWS preparation and audited V1/V2 plan https://github.com/Collaboration95/dc2/pull/70 | Collaboration95 | 2026-10-14T18:10:17Z | 2026-10-15T05:43:24Z | MERGED |
| #71 Prepare lean AWS boundaries and bounded local operations https://github.com/Collaboration95/dc2/pull/71 | Collaboration95 | 2026-10-14T20:07:14Z | 2026-10-14T21:48:50Z | MERGED |
| #72 Handle local startup probes and preserve composed phase evidence https://github.com/Collaboration95/dc2/pull/72 | Collaboration95 | 2026-10-14T20:12:01Z | 2026-10-14T21:41:30Z | MERGED |
| #73 Complete local preparation contracts and repair scanner startup https://github.com/Collaboration95/dc2/pull/73 | Collaboration95 | 2026-10-14T20:32:26Z | 2026-10-14T21:34:42Z | MERGED |
| #74 Match owned private API header rejection contracts https://github.com/Collaboration95/dc2/pull/74 | Collaboration95 | 2026-10-14T20:42:08Z | 2026-10-14T21:21:40Z | MERGED |
| #75 Satisfy the final private probe lint gate https://github.com/Collaboration95/dc2/pull/75 | Collaboration95 | 2026-10-14T20:55:47Z | 2026-10-14T21:13:17Z | MERGED |
| #76 Publish AWS preparation completion ledger and scoped closures https://github.com/Collaboration95/dc2/pull/76 | Collaboration95 | 2026-10-14T21:55:55Z | 2026-10-14T22:03:16Z | MERGED |
| #77 Keep completion report links visible and fold the outcome table https://github.com/Collaboration95/dc2/pull/77 | Collaboration95 | 2026-10-14T22:03:43Z | 2026-10-14T22:10:40Z | MERGED |
| #78 Make completion report phase labels readable in dark mode https://github.com/Collaboration95/dc2/pull/78 | Collaboration95 | 2026-10-14T22:11:00Z | 2026-10-14T22:17:10Z | MERGED |
| #79 Keep required AWS evidence open and blocked after preparation https://github.com/Collaboration95/dc2/pull/79 | Collaboration95 | 2026-10-14T23:15:20Z | 2026-10-14T23:22:08Z | MERGED |
| #95 Publish audited V1 architecture and gated V2 execution plan https://github.com/Collaboration95/dc2/pull/95 | Collaboration95 | 2026-10-15T05:25:20Z | 2026-10-15T05:35:16Z | MERGED |
| #97 V1 seed: import prior sprint work (#81–#92 partial) https://github.com/Collaboration95/dc2/pull/97 | Collaboration95 | 2026-10-16T03:45:49Z | 2026-10-16T03:52:11Z | MERGED |
| #98 V1 Lane A: domain API, TLS, intake pinning and contract fixtures (#81 #82 #83 #86) https://github.com/Collaboration95/dc2/pull/98 | Collaboration95 | 2026-10-16T04:01:41Z | 2026-10-16T04:02:01Z | MERGED |
| #99 V1 Lane B: SQS delivery hardening, repair dedupe and projections (#84 #85 #87 #88) https://github.com/Collaboration95/dc2/pull/99 | Collaboration95 | 2026-10-16T04:07:38Z | 2026-10-16T04:08:05Z | MERGED |
| #100 V1 Lane C: real session/release operators, concurrency model and V1 cost (#89 #90 #91) https://github.com/Collaboration95/dc2/pull/100 | Collaboration95 | 2026-10-16T04:11:14Z | 2026-10-16T04:11:29Z | MERGED |
| #101 V1 wave 2: ECS stop events, upload cleanup backoff, handler self-heal (#82 #83 #86 #87 #88) https://github.com/Collaboration95/dc2/pull/101 | Collaboration95 | 2026-10-16T04:18:30Z | 2026-10-16T04:18:44Z | MERGED |
| #102 V1 artifacts: reproducible amd64 images verified with Lambda RIE https://github.com/Collaboration95/dc2/pull/102 | Collaboration95 | 2026-10-16T04:19:14Z | 2026-10-16T04:19:33Z | MERGED |
| #103 V1 error hygiene: sanitized handler failures, worker config errors, uvicorn to legacy https://github.com/Collaboration95/dc2/pull/103 | Collaboration95 | 2026-10-16T04:23:26Z | 2026-10-16T04:23:57Z | MERGED |
| #104 V1 verification: full local flows, browser leg, CI and VM defaults (#92 #96) https://github.com/Collaboration95/dc2/pull/104 | Collaboration95 | 2026-10-16T04:30:25Z | 2026-10-16T16:56:38Z | MERGED |
| #105 V1 HLS: native playback across Gateway/S3 redirects https://github.com/Collaboration95/dc2/pull/105 | Collaboration95 | 2026-10-16T04:40:05Z | 2026-10-16T17:04:11Z | MERGED |
| #106 V1 deploy pipeline: journaled offline-verified first deploy and teardown (#63 #67 prep) https://github.com/Collaboration95/dc2/pull/106 | Collaboration95 | 2026-10-16T04:46:21Z | 2026-10-16T04:46:37Z | MERGED |
| #109 fix(v1): local DLQ redrive fallback and refreshed V1 handoff https://github.com/Collaboration95/dc2/pull/109 | Collaboration95 | 2026-10-16T17:14:39Z | 2026-10-16T17:22:13Z | MERGED |
| #110 feat(aws-v1): MFA session, SPA upload and cloud-proof evidence harnesses https://github.com/Collaboration95/dc2/pull/110 | Collaboration95 | 2026-10-16T17:35:30Z | 2026-10-16T17:42:47Z | MERGED |
| #112 V1: Redis-free Lambda/SQS/Aurora implementation, verified locally (#81–#92) https://github.com/Collaboration95/dc2/pull/112 | Collaboration95 | 2026-10-16T17:43:17Z | 2026-10-16T19:16:34Z | MERGED |
| #122 fix(aws-v1): safe deploy resume, teardown ordering, DLQ scope, proof replay https://github.com/Collaboration95/dc2/pull/122 | Collaboration95 | 2026-10-16T18:08:48Z | 2026-10-16T18:15:37Z | MERGED |
| #123 fix(v1): runtime IAM and recovery bounds (#115 #116 #117 #119) https://github.com/Collaboration95/dc2/pull/123 | Collaboration95 | 2026-10-16T18:10:50Z | 2026-10-16T18:24:53Z | MERGED |
| #129 fix(v1): stale receipts spare the encode allowance; fence staged cleanup (#127 #128) https://github.com/Collaboration95/dc2/pull/129 | Collaboration95 | 2026-10-16T18:39:51Z | 2026-10-16T18:54:28Z | MERGED |
| #130 fix(aws-v1): retire stale bootstrap tasks, journal verdict, re-sweep buckets before delete https://github.com/Collaboration95/dc2/pull/130 | Collaboration95 | 2026-10-16T18:39:53Z | 2026-10-16T18:47:25Z | MERGED |
| #132 fix(aws-v1): track every discovered bootstrap task until STOPPED https://github.com/Collaboration95/dc2/pull/132 | Collaboration95 | 2026-10-16T19:03:28Z | 2026-10-16T19:10:29Z | MERGED |
| #133 docs(aws-v1): account, currency, quota and scoped authorization receipt https://github.com/Collaboration95/dc2/pull/133 | Collaboration95 | 2026-10-16T19:20:16Z | 2026-10-16T19:27:17Z | MERGED |
| #135 Fix V1 image verifier for sanitized handler errors; run image job on relevant changes https://github.com/Collaboration95/dc2/pull/135 | Collaboration95 | 2026-10-16T19:23:50Z | 2026-10-16T19:38:35Z | MERGED |
| #136 V1 follow-ups: account receipt (#45) and image verifier (#134) https://github.com/Collaboration95/dc2/pull/136 | Collaboration95 | 2026-10-16T19:38:48Z | 2026-10-16T19:52:18Z | MERGED |
| #139 V1: stop the browser leg flaking on a slow runner; surface failing test detail (#137) https://github.com/Collaboration95/dc2/pull/139 | Collaboration95 | 2026-10-16T20:34:03Z | 2026-10-16T20:43:06Z | MERGED |
| #140 V1: deploy --dry-run observes image ids from the local Docker daemon (#138) https://github.com/Collaboration95/dc2/pull/140 | Collaboration95 | 2026-10-16T20:47:29Z | 2026-10-16T20:55:13Z | MERGED |
| #141 V1 follow-ups: browser-leg flake (#137) and dry-run with real image evidence (#138) https://github.com/Collaboration95/dc2/pull/141 | Collaboration95 | 2026-10-16T20:55:19Z | 2026-10-16T21:02:23Z | MERGED |
| #142 feat(aws-v1): accept principals the MFA deny does not cover (dc2-agent) https://github.com/Collaboration95/dc2/pull/142 | Collaboration95 | 2026-10-17T00:52:14Z | 2026-10-17T01:05:11Z | MERGED |
| #144 V1: judge the native HLS redirected segment read from server-side logs (#143) https://github.com/Collaboration95/dc2/pull/144 | Collaboration95 | 2026-10-17T01:15:49Z | 2026-10-17T01:22:52Z | MERGED |
| #145 V2: opt-in unattended encoder launcher (Refs #68) https://github.com/Collaboration95/dc2/pull/145 | Collaboration95 | 2026-10-17T01:24:07Z | 2026-10-17T01:31:00Z | MERGED |
| #146 fix(aws-v1): first real AWS run fixes (change set, Aurora resume, rds_superuser) https://github.com/Collaboration95/dc2/pull/146 | Collaboration95 | 2026-10-17T01:35:36Z | 2026-10-17T02:08:38Z | MERGED |
| #148 V2: opt-in Lambda lane for bounded short encodes (#93) https://github.com/Collaboration95/dc2/pull/148 | Collaboration95 | 2026-10-17T02:09:21Z | 2026-10-17T02:16:28Z | MERGED |
| #149 V2 #94: opt-in separate database topology + #147 teardown receipt fix https://github.com/Collaboration95/dc2/pull/149 | Collaboration95 | 2026-10-17T02:52:50Z | 2026-10-17T03:17:56Z | MERGED |
| #152 fix(aws-v1): read the release schema revision in the VPC; add release-plan (#150) https://github.com/Collaboration95/dc2/pull/152 | Collaboration95 | 2026-10-17T03:46:10Z | 2026-10-17T03:53:35Z | MERGED |
| #153 fix(aws-v1): release gate accepts an audited list of unfixed CVEs (#65) https://github.com/Collaboration95/dc2/pull/153 | Collaboration95 | 2026-10-17T09:42:55Z | 2026-10-17T09:55:50Z | MERGED |
| #154 fix(aws-v1): #66 latency harness waits for pause and gate, closes its window, --fresh reruns (#151) https://github.com/Collaboration95/dc2/pull/154 | Collaboration95 | 2026-10-17T09:52:07Z | 2026-10-17T10:06:04Z | MERGED |
| #155 fix(aws-v1): release abandon for intents that moved nothing; Lambda-only failing candidate (#65) https://github.com/Collaboration95/dc2/pull/155 | Collaboration95 | 2026-10-17T10:05:21Z | 2026-10-17T10:19:22Z | MERGED |
| #157 docs(aws-v1): redacted r1017b cloud receipts https://github.com/Collaboration95/dc2/pull/157 | Collaboration95 | 2026-10-17T12:08:17Z | 2026-10-17T12:15:27Z | MERGED |
| #158 test(ci): stabilize throttle and JavaScript checks without excluding coverage https://github.com/Collaboration95/dc2/pull/158 | Collaboration95 | 2026-10-17T12:17:46Z | 2026-10-17T13:49:49Z | MERGED |
| #166 ci: select development checks and parallelize V1 verification https://github.com/Collaboration95/dc2/pull/166 | Collaboration95 | 2026-10-17T13:55:12Z | 2026-10-17T14:09:56Z | MERGED |
| #167 test(ci): docs selection validation only (#165; do not merge) https://github.com/Collaboration95/dc2/pull/167 | Collaboration95 | 2026-10-17T14:11:16Z | — | CLOSED |
| #168 test(ci): aws selection validation only (#165; do not merge) https://github.com/Collaboration95/dc2/pull/168 | Collaboration95 | 2026-10-17T14:11:22Z | — | CLOSED |
| #169 test(ci): media selection validation only (#165; do not merge) https://github.com/Collaboration95/dc2/pull/169 | Collaboration95 | 2026-10-17T14:11:29Z | — | CLOSED |
| #170 test(ci): processing selection validation only (#165; do not merge) https://github.com/Collaboration95/dc2/pull/170 | Collaboration95 | 2026-10-17T14:11:36Z | — | CLOSED |
| #171 test(ci): negative selection validation only (#165; do not merge) https://github.com/Collaboration95/dc2/pull/171 | Collaboration95 | 2026-10-17T14:11:42Z | — | CLOSED |
| #172 docs(ci): publish measured selective-gate and full-verification evidence https://github.com/Collaboration95/dc2/pull/172 | Collaboration95 | 2026-10-17T14:21:55Z | 2026-10-17T14:29:50Z | MERGED |
| #173 fix(v1): reuse Lambda DB connections per warm environment (#66); abandon accepts forgotten tasks (#156) https://github.com/Collaboration95/dc2/pull/173 | Collaboration95 | 2026-10-17T15:11:03Z | 2026-10-17T15:27:51Z | MERGED |
| #174 fix(aws-v1): generator paces rounds on a fixed grid (#66) https://github.com/Collaboration95/dc2/pull/174 | Collaboration95 | 2026-10-17T15:53:17Z | 2026-10-17T15:57:27Z | MERGED |
| #175 fix(aws-v1): generator keeps its last status round (#66) https://github.com/Collaboration95/dc2/pull/175 | Collaboration95 | 2026-10-17T16:05:03Z | 2026-10-17T16:09:13Z | MERGED |
| #176 docs(aws-v1): final r1017b receipts — #66 PASS, #67 teardown and spend https://github.com/Collaboration95/dc2/pull/176 | Collaboration95 | 2026-10-17T16:24:32Z | 2026-10-17T16:36:12Z | MERGED |
| #177 V1: cloud-proven close-out (#63–#67), connection reuse, release abandon, CI selection https://github.com/Collaboration95/dc2/pull/177 | Collaboration95 | 2026-10-17T16:36:24Z | 2026-10-17T16:48:18Z | MERGED |
| #194 Project 2 V1: Lambda/SQS/Aurora platform, cloud-proven (#63–#67) https://github.com/Collaboration95/dc2/pull/194 | Collaboration95 | 2026-10-17T16:57:03Z | 2026-10-17T17:15:07Z | MERGED |
| #201 feat(aws-v1): backlog throughput mode for the capacity proof (#185) https://github.com/Collaboration95/dc2/pull/201 | Collaboration95 | 2026-10-17T17:15:51Z | 2026-10-17T17:24:07Z | MERGED |
| #202 feat(ci): CD workflow over OIDC, secret scan and published OpenAPI documents https://github.com/Collaboration95/dc2/pull/202 | Collaboration95 | 2026-10-17T17:22:56Z | 2026-10-17T17:30:19Z | MERGED |
| #203 Close-out wave 1: CD pipeline (OIDC), secret scanning, OpenAPI, backlog scaling proof https://github.com/Collaboration95/dc2/pull/203 | Collaboration95 | 2026-10-17T17:30:35Z | 2026-10-17T17:40:00Z | MERGED |
| #204 feat(ci): per-service Media and Processing lanes, CODEOWNERS, required secret scan https://github.com/Collaboration95/dc2/pull/204 | Collaboration95 | 2026-10-17T17:32:57Z | 2026-10-17T17:40:04Z | MERGED |
| #205 feat(aws-v1): processing-down isolation proof, --unattended-launch flag and unattended harness (#196, #68) https://github.com/Collaboration95/dc2/pull/205 | Collaboration95 | 2026-10-17T17:37:37Z | 2026-10-17T17:44:33Z | MERGED |
| #206 refactor(closeout): microservices hardening - legacy peer code out of V1 images, contract versioning, per-service observability https://github.com/Collaboration95/dc2/pull/206 | Collaboration95 | 2026-10-17T17:40:35Z | 2026-10-17T17:55:50Z | MERGED |
| #207 feat(ci): unattended_launch input and operator handoff of the CD state https://github.com/Collaboration95/dc2/pull/207 | Collaboration95 | 2026-10-17T17:52:40Z | 2026-10-17T17:59:37Z | MERGED |
| #208 Close-out wave 2: microservices hardening, per-service CI, isolation and unattended proofs https://github.com/Collaboration95/dc2/pull/208 | Collaboration95 | 2026-10-17T17:56:07Z | 2026-10-17T18:00:27Z | MERGED |
| #209 docs(architecture): as-built DDD model, ADR register and views https://github.com/Collaboration95/dc2/pull/209 | Collaboration95 | 2026-10-17T17:59:03Z | 2026-10-17T18:06:52Z | MERGED |
| #211 docs: start-here README, historical banners and status fixes (#190) https://github.com/Collaboration95/dc2/pull/211 | Collaboration95 | 2026-10-17T18:12:59Z | 2026-10-17T18:20:30Z | MERGED |
| #212 chore(agents): untrack AGENTS.md and ignore it locally https://github.com/Collaboration95/dc2/pull/212 | Collaboration95 | 2026-10-17T18:21:00Z | 2026-10-18T00:14:32Z | MERGED |
| #213 fix(cd): install ffmpeg for the smoke clip https://github.com/Collaboration95/dc2/pull/213 | Collaboration95 | 2026-10-17T18:34:26Z | 2026-10-17T18:58:51Z | MERGED |
| #214 fix(aws-v1): give the encoder task its work queue URL again https://github.com/Collaboration95/dc2/pull/214 | Collaboration95 | 2026-10-17T18:58:38Z | 2026-10-17T19:05:28Z | MERGED |
| #215 chore(processing): API version 1.0.1 (independent release proof) https://github.com/Collaboration95/dc2/pull/215 | Collaboration95 | 2026-10-17T19:30:02Z | 2026-10-17T20:13:36Z | MERGED |
| #216 chore(media): API version 1.0.1 (independent release proof) https://github.com/Collaboration95/dc2/pull/216 | Collaboration95 | 2026-10-17T19:30:12Z | 2026-10-17T20:13:46Z | MERGED |
| #217 fix(images): upgrade libexpat1 (new fixable HIGH findings) https://github.com/Collaboration95/dc2/pull/217 | Collaboration95 | 2026-10-17T19:50:29Z | 2026-10-17T20:01:44Z | MERGED |
| #218 fix(proof): Lambda call deadline above the transport allowance (#196 live run) https://github.com/Collaboration95/dc2/pull/218 | Collaboration95 | 2026-10-17T20:36:21Z | 2026-10-17T20:44:31Z | MERGED |
| #219 fix(publisher): accept the accepted and cancelled job statuses https://github.com/Collaboration95/dc2/pull/219 | Collaboration95 | 2026-10-17T20:59:59Z | 2026-10-17T21:07:42Z | MERGED |
| #220 fix(cd): wait for the Gateway gate before the smoke upload https://github.com/Collaboration95/dc2/pull/220 | Collaboration95 | 2026-10-17T21:22:49Z | 2026-10-17T21:31:10Z | MERGED |
| #221 fix(aws): tolerate stopped tasks ECS purged between list and describe https://github.com/Collaboration95/dc2/pull/221 | Collaboration95 | 2026-10-17T22:12:11Z | 2026-10-17T22:18:06Z | MERGED |
| #222 fix(cd): retry the upload smoke once on a Gateway 429 https://github.com/Collaboration95/dc2/pull/222 | Collaboration95 | 2026-10-17T22:26:46Z | 2026-10-17T22:33:31Z | MERGED |
| #224 docs(aws-v1): r1018b cloud receipts and results https://github.com/Collaboration95/dc2/pull/224 | Collaboration95 | 2026-10-18T00:06:00Z | 2026-10-18T00:12:07Z | MERGED |
| #226 refactor(closeout): peer-era leftovers out of the V1 packages, retained schema documented https://github.com/Collaboration95/dc2/pull/226 | Collaboration95 | 2026-10-18T00:18:28Z | 2026-10-18T00:37:40Z | MERGED |
| #227 docs(evidence): evidence index against proposal targets (#189) https://github.com/Collaboration95/dc2/pull/227 | Collaboration95 | 2026-10-18T00:23:35Z | 2026-10-18T00:29:50Z | MERGED |
| #228 fix(cd): green pipeline: smoke encoder race (#223), close retry (#225), bad-candidate rollback https://github.com/Collaboration95/dc2/pull/228 | Collaboration95 | 2026-10-18T00:23:55Z | 2026-10-18T00:38:44Z | MERGED |
| #230 Close-out: green CD pipeline, cloud receipts r1018b, peer leftovers moved to legacy https://github.com/Collaboration95/dc2/pull/230 | Collaboration95 | 2026-10-18T00:38:56Z | 2026-10-18T01:04:57Z | MERGED |
| #231 chore(processing): API version 1.0.2 (r1019a release proof) https://github.com/Collaboration95/dc2/pull/231 | Collaboration95 | 2026-10-18T00:39:19Z | 2026-10-18T01:05:01Z | MERGED |
| #232 feat(aws-v1): evidence security proof for #229 https://github.com/Collaboration95/dc2/pull/232 | Collaboration95 | 2026-10-18T00:49:49Z | 2026-10-18T00:56:44Z | MERGED |
| #233 fix(evidence): security proof accepts 403 for forged tokens https://github.com/Collaboration95/dc2/pull/233 | Collaboration95 | 2026-10-18T01:51:51Z | 2026-10-18T02:00:57Z | MERGED |
| #239 V2-live: one persistent always-on environment updated in place (#235 #236 #237) https://github.com/Collaboration95/dc2/pull/239 | Collaboration95 | 2026-10-18T02:55:05Z | 2026-10-18T04:20:37Z | MERGED |
| #240 V2-live: always-on dc2-live environment (in-place CD updates, scale to zero) + close-out wave 3 https://github.com/Collaboration95/dc2/pull/240 | Collaboration95 | 2026-10-18T04:20:40Z | 2026-10-18T04:28:04Z | MERGED |
| #241 Processing 1.0.3 and an alarm wording fix (#238 in-place checks) https://github.com/Collaboration95/dc2/pull/241 | Collaboration95 | 2026-10-18T07:26:27Z | 2026-10-19T13:00:22Z | MERGED |
| #242 docs: add the full Team 17 wrap-up timeline https://github.com/Collaboration95/dc2/pull/242 | Collaboration95 | 2026-10-18T08:30:04Z | 2026-10-18T08:34:25Z | MERGED |
| #259 fix(clients): account-switch privacy, list-load errors, Publisher /api/media docs https://github.com/Collaboration95/dc2/pull/259 | Collaboration95 | 2026-10-18T13:02:35Z | 2026-10-18T13:31:21Z | MERGED |
| #260 fix(processing): idle-marker activity for direct retry/cancel; document lost-marker bounds https://github.com/Collaboration95/dc2/pull/260 | Collaboration95 | 2026-10-18T13:05:06Z | 2026-10-18T13:15:26Z | MERGED |
| #261 fix(local-v1): clean-clone setup-v1 bootstrap and interactive v1-demo https://github.com/Collaboration95/dc2/pull/261 | Collaboration95 | 2026-10-18T13:09:53Z | 2026-10-18T13:29:57Z | MERGED |
| #262 docs: reconcile V1/V2 status, archive r1019a receipts, publish actual-vs-target results https://github.com/Collaboration95/dc2/pull/262 | Collaboration95 | 2026-10-18T13:19:30Z | 2026-10-18T13:31:48Z | MERGED |
| #263 ci(v1): scan exact built V1 images (#251) https://github.com/Collaboration95/dc2/pull/263 | Collaboration95 | 2026-10-18T14:25:00Z | 2026-10-18T14:49:12Z | MERGED |
| #264 Close-out: merge dev/closeout into Main (#259–#263, #241) https://github.com/Collaboration95/dc2/pull/264 | Collaboration95 | 2026-10-19T13:00:27Z | 2026-10-19T13:07:10Z | MERGED |
| #265 fix(cd): release evidence jq reads the build file https://github.com/Collaboration95/dc2/pull/265 | Collaboration95 | 2026-10-19T13:21:52Z | 2026-10-19T13:36:07Z | MERGED |
| #266 test(aws): #229 security negatives proof on dc2-live https://github.com/Collaboration95/dc2/pull/266 | Collaboration95 | 2026-10-19T13:25:27Z | 2026-10-19T13:32:41Z | MERGED |
| #267 fix(cd): adopt step no longer blanks the baseline evidence https://github.com/Collaboration95/dc2/pull/267 | Collaboration95 | 2026-10-19T14:12:04Z | 2026-10-19T14:19:36Z | MERGED |
| #268 docs(evidence): V2-live verification receipts, 19 October (#238, #186) https://github.com/Collaboration95/dc2/pull/268 | Collaboration95 | 2026-10-19T14:58:52Z | 2026-10-19T15:05:16Z | MERGED |
| #269 Close-out: CD release fixes and dc2-live receipts into Main (#265–#268) https://github.com/Collaboration95/dc2/pull/269 | Collaboration95 | 2026-10-19T15:05:59Z | 2026-10-19T15:12:54Z | MERGED |
| #272 fix(processing): sweep stale work duplicates after a worker's encode https://github.com/Collaboration95/dc2/pull/272 | Collaboration95 | 2026-10-19T15:09:46Z | 2026-10-19T15:17:50Z | MERGED |
| #273 fix(media): let Aurora auto-pause (upload-cleanup rescan wake-ups) https://github.com/Collaboration95/dc2/pull/273 | Collaboration95 | 2026-10-19T15:10:40Z | 2026-10-19T15:19:14Z | MERGED |
| #274 Close-out: Aurora auto-pause and duplicate work-message fixes into Main (#272, #273) https://github.com/Collaboration95/dc2/pull/274 | Collaboration95 | 2026-10-19T15:19:17Z | 2026-10-19T15:33:06Z | MERGED |
| #275 docs: #270 re-test receipt and V2-live demo release manifest (#255) https://github.com/Collaboration95/dc2/pull/275 | Collaboration95 | 2026-10-19T17:15:50Z | 2026-10-19T17:23:20Z | MERGED |
| #276 docs(release): record the observed Aurora pause on daee44b https://github.com/Collaboration95/dc2/pull/276 | Collaboration95 | 2026-10-19T18:09:12Z | 2026-10-19T18:15:49Z | MERGED |
| #277 Close-out: demo release manifest and dc2-live receipts into Main (#275, #276) https://github.com/Collaboration95/dc2/pull/277 | Collaboration95 | 2026-10-19T18:15:58Z | 2026-10-19T18:22:28Z | MERGED |
| #278 docs: freeze the demo release and add the team effort ledger https://github.com/Collaboration95/dc2/pull/278 | Collaboration95 | 2026-10-20T04:45:12Z | 2026-10-20T04:51:20Z | MERGED |
| #279 docs: add member specialisms and a tentative code submission date https://github.com/Collaboration95/dc2/pull/279 | Collaboration95 | 2026-10-20T04:58:20Z | 2026-10-20T05:07:44Z | MERGED |
| #280 Simplify runtime code and verify releases against tested source https://github.com/Collaboration95/dc2/pull/280 | Collaboration95 | 2026-10-20T10:39:23Z | 2026-10-20T10:57:24Z | MERGED |
| #281 Fix DAST workflow context before job startup https://github.com/Collaboration95/dc2/pull/281 | Collaboration95 | 2026-10-20T10:46:40Z | 2026-10-20T10:47:15Z | MERGED |
| #282 Preserve released migration bytes during formatting https://github.com/Collaboration95/dc2/pull/282 | Collaboration95 | 2026-10-20T11:25:12Z | 2026-10-20T11:34:34Z | MERGED |
| #283 Complete the verified engineering and course handoff https://github.com/Collaboration95/dc2/pull/283 | Collaboration95 | 2026-10-20T12:25:03Z | 2026-10-20T12:34:20Z | MERGED |
| #284 Publish the showcase study guide on GitHub Pages https://github.com/Collaboration95/dc2/pull/284 | Collaboration95 | 2026-10-21T01:52:30Z | 2026-10-21T02:09:03Z | MERGED |
| #285 Record fixable findings on a replaced rollback target instead of blocking its release https://github.com/Collaboration95/dc2/pull/285 | Collaboration95 | 2026-10-21T03:44:53Z | 2026-10-21T03:52:19Z | MERGED |
| #286 Record fixable findings on a replaced rollback target instead of blocking its release https://github.com/Collaboration95/dc2/pull/286 | Collaboration95 | 2026-10-21T03:52:27Z | 2026-10-21T04:03:03Z | MERGED |
| #287 Wait for a resuming database in the deploy smoke instead of failing on the first login https://github.com/Collaboration95/dc2/pull/287 | Collaboration95 | 2026-10-21T04:22:33Z | 2026-10-21T04:29:08Z | MERGED |
| #288 Wait for a resuming database in the deploy smoke instead of failing on the first login https://github.com/Collaboration95/dc2/pull/288 | Collaboration95 | 2026-10-21T04:29:17Z | 2026-10-21T04:36:17Z | MERGED |
| #289 Record the certifi delivery recovery with a receipt, handoff update and manifest addendum https://github.com/Collaboration95/dc2/pull/289 | Collaboration95 | 2026-10-21T05:16:49Z | 2026-10-21T05:24:18Z | MERGED |
| #290 Record the certifi delivery recovery with a receipt, handoff update and manifest addendum https://github.com/Collaboration95/dc2/pull/290 | Collaboration95 | 2026-10-21T05:24:36Z | 2026-10-21T05:32:01Z | MERGED |
| #291 Add the Team 17 final report and close the report gaps https://github.com/Collaboration95/dc2/pull/291 | Collaboration95 | 2026-10-21T05:51:43Z | 2026-10-21T06:02:43Z | MERGED |
| #292 Promote the final report to Main https://github.com/Collaboration95/dc2/pull/292 | Collaboration95 | 2026-10-21T06:02:47Z | 2026-10-21T06:10:27Z | MERGED |
| #293 Trim the report's limitations to six architectural issues https://github.com/Collaboration95/dc2/pull/293 | Collaboration95 | 2026-10-21T07:45:49Z | 2026-10-21T07:54:02Z | MERGED |
| #294 Promote the trimmed limitations section to Main https://github.com/Collaboration95/dc2/pull/294 | Collaboration95 | 2026-10-21T07:54:05Z | 2026-10-21T08:05:25Z | MERGED |
| #295 Publish scanner results to GitHub code scanning https://github.com/Collaboration95/dc2/pull/295 | Collaboration95 | 2026-10-21T08:31:30Z | 2026-10-21T08:38:29Z | MERGED |
| #296 Enable the Lambda short-encode lane on dc2-live (#93) https://github.com/Collaboration95/dc2/pull/296 | Collaboration95 | 2026-10-21T08:34:49Z | 2026-10-21T08:41:58Z | MERGED |
| #297 Promote code scanning publication to Main https://github.com/Collaboration95/dc2/pull/297 | Collaboration95 | 2026-10-21T08:38:46Z | 2026-10-21T08:50:42Z | MERGED |
| #298 Cap the short-encoder memory at the account's 3008 MB (#93) https://github.com/Collaboration95/dc2/pull/298 | Collaboration95 | 2026-10-21T12:14:39Z | 2026-10-21T12:21:24Z | MERGED |
| #299 Promote the short-encoder memory fix to Main https://github.com/Collaboration95/dc2/pull/299 | Collaboration95 | 2026-10-21T12:21:37Z | 2026-10-21T12:29:20Z | MERGED |
| #300 Accept an update on a stack that CloudFormation rolled back to its previous state https://github.com/Collaboration95/dc2/pull/300 | Collaboration95 | 2026-10-21T12:45:26Z | 2026-10-21T12:49:55Z | MERGED |
| #301 Promote the update-after-rollback deploy fix to Main https://github.com/Collaboration95/dc2/pull/301 | Collaboration95 | 2026-10-21T12:50:11Z | 2026-10-21T12:57:56Z | MERGED |
| #302 Record code scanning triage https://github.com/Collaboration95/dc2/pull/302 | Collaboration95 | 2026-10-21T15:10:06Z | 2026-10-21T15:11:19Z | MERGED |
| #303 Split Media and Processing onto their own Aurora clusters in place (#94) https://github.com/Collaboration95/dc2/pull/303 | Collaboration95 | 2026-10-21T15:26:36Z | 2026-10-21T15:36:50Z | MERGED |
| #304 Measure the Lambda short lane on dc2-live and record the result (#93) https://github.com/Collaboration95/dc2/pull/304 | Collaboration95 | 2026-10-21T15:29:42Z | 2026-10-21T15:49:01Z | MERGED |
| #305 Promote the per-service Aurora split to Main (#94) https://github.com/Collaboration95/dc2/pull/305 | Collaboration95 | 2026-10-21T15:37:23Z | 2026-10-21T16:01:35Z | MERGED |
| #306 Accept a registry receipt for a digest that carries several tags https://github.com/Collaboration95/dc2/pull/306 | Collaboration95 | 2026-10-21T16:25:21Z | 2026-10-21T16:30:44Z | MERGED |
| #307 Promote the registry-receipt fix to Main https://github.com/Collaboration95/dc2/pull/307 | Collaboration95 | 2026-10-21T16:30:48Z | 2026-10-21T16:38:39Z | MERGED |
| #308 Accept ffmpeg CVE-2025-52290 (unfixed in Debian 13) on the audited list https://github.com/Collaboration95/dc2/pull/308 | Collaboration95 | 2026-10-21T16:55:50Z | 2026-10-21T16:56:17Z | MERGED |
| #309 Promote the ffmpeg CVE-2025-52290 acceptance to Main https://github.com/Collaboration95/dc2/pull/309 | Collaboration95 | 2026-10-21T16:56:25Z | 2026-10-21T17:05:08Z | MERGED |
| #310 Report: short lane, per-service databases, code scanning https://github.com/Collaboration95/dc2/pull/310 | Collaboration95 | 2026-10-21T19:07:12Z | 2026-10-21T19:14:55Z | MERGED |
| #311 Report: short lane, per-service databases, code scanning (to Main) https://github.com/Collaboration95/dc2/pull/311 | Collaboration95 | 2026-10-21T19:14:59Z | 2026-10-21T19:23:18Z | MERGED |
| #312 Docs: align stale shared-cluster and short-lane statements with dc2-live https://github.com/Collaboration95/dc2/pull/312 | Collaboration95 | 2026-10-22T05:13:31Z | 2026-10-22T05:14:12Z | MERGED |
| #313 Promote docs consistency (AD-29, short lane) to Main https://github.com/Collaboration95/dc2/pull/313 | Collaboration95 | 2026-10-22T05:14:15Z | 2026-10-22T05:22:27Z | MERGED |
| #314 Rebuild the final report DOCX and PDF https://github.com/Collaboration95/dc2/pull/314 | Collaboration95 | 2026-10-22T05:22:08Z | 2026-10-22T05:30:13Z | MERGED |
| #315 Promote the rebuilt final report to Main https://github.com/Collaboration95/dc2/pull/315 | Collaboration95 | 2026-10-22T05:30:25Z | 2026-10-22T05:37:14Z | MERGED |
| #316 Refresh showcase guide and cut verbosity (~31%) https://github.com/Collaboration95/dc2/pull/316 | Collaboration95 | 2026-10-22T05:38:17Z | 2026-10-22T05:46:18Z | MERGED |
| #317 Release dev/closeout: refreshed showcase guide https://github.com/Collaboration95/dc2/pull/317 | Collaboration95 | 2026-10-22T05:46:21Z | 2026-10-22T05:54:03Z | MERGED |
| #318 Retry the Processing smoke call while its own database wakes https://github.com/Collaboration95/dc2/pull/318 | Collaboration95 | 2026-10-22T05:56:40Z | 2026-10-22T06:10:35Z | MERGED |
| #319 Promote the Processing database-wake smoke fix to Main https://github.com/Collaboration95/dc2/pull/319 | Collaboration95 | 2026-10-22T06:10:38Z | 2026-10-22T06:18:18Z | MERGED |
| #320 Replace the explainer site with a study guide and HTML slides for the 26 Oct presentation https://github.com/Collaboration95/dc2/pull/320 | Collaboration95 | 2026-10-22T11:13:16Z | 2026-10-22T11:45:50Z | MERGED |
| #321 Publish the new study guide and HTML slides https://github.com/Collaboration95/dc2/pull/321 | Collaboration95 | 2026-10-22T11:45:53Z | 2026-10-22T12:04:50Z | MERGED |
| #322 Simplify the slides, add the video storyboard and demo recording tools https://github.com/Collaboration95/dc2/pull/322 | Collaboration95 | 2026-10-23T06:12:10Z | 2026-10-23T07:30:36Z | MERGED |
| #323 Publish the simplified slides, video storyboard and demo recording tools https://github.com/Collaboration95/dc2/pull/323 | Collaboration95 | 2026-10-23T07:30:39Z | 2026-10-23T08:15:11Z | MERGED |
| #324 Keyboard-only slide navigation; pin CI runners to Ubuntu 24.04 https://github.com/Collaboration95/dc2/pull/324 | Collaboration95 | 2026-10-23T08:33:06Z | 2026-10-23T08:48:39Z | MERGED |
| #325 Publish keyboard-only slide navigation and the Ubuntu 24.04 runner pin https://github.com/Collaboration95/dc2/pull/325 | Collaboration95 | 2026-10-23T08:48:42Z | 2026-10-23T09:19:51Z | MERGED |
| #326 Report v1.1: presentation feedback and final report revision https://github.com/Collaboration95/dc2/pull/326 | Collaboration95 | 2026-11-10T14:37:42Z | — | OPEN |


## Local source snapshot and date conventions

Root: `/Users/speedpowermac/Documents/projects/CODE_MAIN/NUS/dc2-report`; branch `dev/report-v1.1`; HEAD `a8c8072b667a039923563ac2612dedc7e7a54ce8`. Inventory date 10 November 2026 (Asia/Singapore). Git dates below are last committed path-change dates on HEAD, not dates of the underlying activity. Filesystem modification times are explicitly labeled; checkout/copy dates do not prove creation or recording dates. No source file was edited. Only this inventory was created/updated.

## Agile / plan / progress document index

The following index records all text documentation matching the requested story/backlog/sprint/retro/review/burn/velocity terms, plus structured backlog, progress and ownership records. Engineering/code review is distinct from sprint review; operational queue backlog is distinct from product backlog.

| Path | Last committed change | Terms | Evidence locator / summary |
|---|---|---|---|
| docs/README.md | 2026-10-20T17:06:59+08:00 | backlog, sprint | L30: \| `sprint1-*`, `sprint2-*`, `a-worker.md`, `c-recovery-input-safety.md`, `contract.md`, `known-traps.md`, `proposal.md`, `s2-03-au; L32: \| [`execution/`](execution/) top level (`plan.md`, `handoff.md`, `decisions.md`, `interfaces.md`, `issue-map.md`, `backlog.json`,  |
| docs/a-worker.md | 2026-10-18T02:12:43+08:00 | as a, sprint | L7: Written for sprint 1 and kept current: the integration parameters below are; L8: still in force, and sprint 2 changed what "processing" means without changing |
| docs/architecture/ddd.md | 2026-10-22T13:13:28+08:00 | as a | L55: \| Owner \| An account (`users.id`); the only principal that may read, retry, edit, delete or play its assets. Processing holds the ; L135: \| Cancel before submit is permanent: the guard is tombstoned and a later submit is accepted as a no-op, not resurrected. \| `messag |
| docs/architecture/decisions.md | 2026-10-22T13:13:28+08:00 | as a, backlog | L150: in the cloud (#94). RDS Data API, DSQL, DynamoDB: V2 backlog, each needing a compatibility spike.; L392: the backlog and the unattended run, no transition to `ALARM`; `ServicesDashboard` captured three |
| docs/architecture/use-case-design.md | 2026-10-22T13:13:28+08:00 | backlog, review | L72: - **Pre:** persistent environment enabled with durable Processing backlog; Media remains independently deployed.; L73: - **Normal:** V2-live work sends wake the backlog launcher; a one-minute schedule is fallback. It checks SQL and visible SQS deman |
| docs/architecture/views.md | 2026-10-22T13:13:28+08:00 | as a | L380: \| `assets.submission_state` \| Media \| Written only by `apply_result` (`pending` to `submitted` or `error`), purely as a status lab |
| docs/c-recovery-input-safety.md | 2026-10-18T02:12:43+08:00 | as a, review, sprint | L1: > **Historical (Project 1 sprint 3, track C), superseded by the as-built V1 ([architecture](architecture/README.md)).** Retry, cro; L3: # Sprint 3 track C: recovery and input safety |
| docs/ci/policy.md | 2026-10-21T23:10:01+08:00 | as a, backlog, review | L56: the staged backlog/map/price provenance or its validator changes. Full mode; L80: \| Staged planning backlog/map/price provenance and raw price snapshots \| Planning validation \| |
| docs/ci/receipts-20261017.txt | 2026-10-17T22:21:18+08:00 | backlog | L9: {"run_id":39039703862,"url":"https://github.com/Collaboration95/dc2/actions/runs/39039703862","head_sha":"048052ebbc6a88e263d5e84c |
| docs/ci/results-20261017.md | 2026-10-17T22:21:18+08:00 | as a, review | L6: change. Review round 2 passed at `99e4a7bd72c76de2afb0b88d9bf0252ec4ca0ef6` after fixing; L20: initial runner/start delay. Whole workflow uses REST updated_at as a completion proxy. |
| docs/contract.md | 2026-10-18T02:12:43+08:00 | as a, review, sprint | L1: > **Historical (Project 1 sprint 1 contract), superseded.** The V1 contracts are [`contracts/README.md`](../contracts/README.md), ; L3: # Sprint 1 Integration Contract |
| docs/evidence-index.md | 2026-10-20T01:15:39+08:00 | as a, backlog | L4: result against the target as written. Targets were not revised. A FAIL is reported as a FAIL. Nothing; L42: \| Scalability, 2 workers at least 1.6x \| **FAIL** (1.449x) \| 6-clip backlog, not 30. Local pre-V1 passed at 2.03x. \| |
| docs/execution/aws/README-20261014.md | 2026-10-18T02:12:43+08:00 | backlog, review | L7: #38/#39 are complete with rejection decisions. [Independent review](../reviews/experiments-20261014-review.md) PASS;; L47: Stop the host between booked windows and verify durable backlog recovery before |
| docs/execution/aws/README.md | 2026-10-15T13:25:01+08:00 | backlog, review | L8: - [Backlog](v1/backlog.json) and [GitHub identities](v1/github-map.json); L15: include cloud evidence, review, fixes, writeup and rehearsal. |
| docs/execution/aws/architecture-plan-20261014.md | 2026-10-18T02:12:43+08:00 | as a, backlog, review | L9: Use **one Linux On-Demand `c6a.2xlarge` EC2 host (8 vCPU, 16 GiB), Docker Compose, two private S3 buckets, and public HTTPS throug; L21: - PR37: 1,107 Python tests, all 15 PR/all 14 Main checks and fresh review passed per parent context. Login releases its SQL connec |
| docs/execution/aws/architecture-plan-aws2-prep-20261015.md | 2026-10-18T02:12:43+08:00 | as a, backlog, review | L5: 15 October 2026 · proposal for review · no provisioning or spending approval.; L8: for the [readiness backlog](readiness/README.md): `af0b21e`. No application code, running |
| docs/execution/aws/architecture-plan.md | 2026-10-21T23:26:22+08:00 | backlog, review | L4: See [the V1 backlog and handoff](v1/README.md) for execution order. The; L22: The user authorizes plan/backlog publication, commits, push and merge into Main |
| docs/execution/aws/cost-worksheet-20261014.json | 2026-10-14T17:16:39Z | backlog, review | L314: "backlog_escalation": 3,; L397: "experiment_dispositions": "Both REJECT; fresh independent Sol review PASS at632cac5. Baseline quotas/fixed workers retained; exac |
| docs/execution/aws/job-inputs.template.json | 2026-10-14T17:16:39Z | review | L13: "origin_transport_tradeoff": "Proposed CloudFront-restricted HTTP to nginx; review before deployment", |
| docs/execution/aws/prep/README.md | 2026-10-15T13:25:01+08:00 | review | L13: Final independent review round 5 passed local preparation at `57f7c5f` ([audits](audits/), [review response](review-response.md)). |
| docs/execution/aws/prep/audits/review-r1.md | 2026-10-15T05:55:26+08:00 | as a, backlog, review | L4: BRANCH: frozen review/aws2-prep-r1; proposed integration work/aws2-prep-20261015; L8: IDENTITY AND REVIEW INPUTS |
| docs/execution/aws/prep/audits/review-r2.md | 2026-10-15T05:55:26+08:00 | backlog, review | L3: PR: Frozen worktree review; PR71 and draft umbrella70 are supplied context only, not independently certified host state.; L11: Fresh independent round-2 review; no spawned agents. Applied /Users/speedpowermac/.codex/skills/review-work/SKILL.md. Read worktre |
| docs/execution/aws/prep/audits/review-r3.md | 2026-10-15T05:55:26+08:00 | backlog, review | L3: PR: Frozen-source review. Stack71→integration,72→71 branch,73→72 branch and draft umbrella70 are coordinator-supplied context, not; L6: WORKTREE: /Users/speedpowermac/Documents/projects/CODE_MAIN/NUS/dc2/.worktrees/aws2-prep-review-r3 |
| docs/execution/aws/prep/audits/review-r4.md | 2026-10-15T05:55:26+08:00 | backlog, review | L3: PR: Frozen-source review only. Coordinator-supplied draft/unmerged stack #71 → integration, #72 → #71, #73 → #72, #74 → #73; umbre; L6: WORKTREE: /Users/speedpowermac/Documents/projects/CODE_MAIN/NUS/dc2/.worktrees/aws2-prep-review-r4 |
| docs/execution/aws/prep/audits/review-r5.md | 2026-10-15T05:55:26+08:00 | as a, backlog, review | L3: PR: Frozen-source review only; integration target work/aws2-prep-20261015. Coordinator owns stack #71–#75 publication/checks/merge; L6: WORKTREE: /Users/speedpowermac/Documents/projects/CODE_MAIN/NUS/dc2/.worktrees/aws2-prep-review-r5 |
| docs/execution/aws/prep/bundles/delivery-operations.md | 2026-10-15T02:55:38+08:00 | review | L139: root test-tier/dependency/Makefile integration, CI execution, review, GitHub and |
| docs/execution/aws/prep/bundles/storage-evidence.md | 2026-10-15T02:40:05+08:00 | review | L57: The implementation needs independent consolidated review and coordinator-owned cross-bundle/local-service/Moto integration. No new |
| docs/execution/aws/prep/completion.json | 2026-10-15T07:15:01+08:00 | as a | L9: "local_run_note": "R11 ran on clean 53f9dca; 57f7c5f only splits one generated assertion into equivalent lines and is not relabele |
| docs/execution/aws/prep/implementation-plan.json | 2026-10-15T02:08:28+08:00 | review | L4: "subagent_policy": "Three implementation bundles covering 21 implementation/evidence-preparation issues (7 issues per implementati; L85: "bundle merges, independent consolidated review, source/evidence ledger, worklog and final HTML" |
| docs/execution/aws/prep/review-response.md | 2026-10-15T05:55:26+08:00 | as a, review | L4: preparation (see coordinator retained review-r1.md). Actual AWS absence was not a; L5: review defect. Coordinator corrections are additive to the three bundle commits. |
| docs/execution/aws/prep/summary.md | 2026-10-15T13:25:01+08:00 | review | L16: ## Review and merge; L18: Rounds 1–4 of the independent review returned REVISE, and every finding was corrected. Round 5 passed local preparation at `57f7c5 |
| docs/execution/aws/readiness/README.md | 2026-10-15T13:25:01+08:00 | backlog | L5: Readiness analysis and real GitHub backlog; application/cloud implementation remains future. Source inspected: `af0b21e3c10d6ad62a; L17: - [#49](https://github.com/Collaboration95/dc2/issues/49) Bound signed URL lifetime to the credentials actually used — **Backlog** |
| docs/execution/aws/readiness/audit-inputs-round1.json | 2026-10-15T02:05:27+08:00 | backlog | L15: "docs/execution/aws/readiness/backlog.json": "af3f37222d47a7bc31cefe0cc8637b37ea8b771fd36ca3ced55b1342c8a06f90",; L20: "readiness_snapshot": "analysis and actual remote backlog complete before audit; no product/cloud implementation" |
| docs/execution/aws/readiness/audit-sol.md | 2026-10-15T02:05:27+08:00 | backlog, review | L3: **Verdict: PASS for the readiness analysis and implementation backlog. Deployment remains BLOCKED.** No substantive correction to ; L5: Audit completed on 15 October 2026 Singapore time; final arithmetic/provenance receipt at `2026-10-14T17:57:51.984997+00:00`. This |
| docs/execution/aws/readiness/backlog.json | 2026-10-15T02:05:27+08:00 | backlog, review | L4: "status": "Readiness backlog only; no application implementation/AWS deployment",; L22: "readiness": "Backlog", |
| docs/execution/aws/readiness/gap-analysis.md | 2026-10-15T02:05:27+08:00 | backlog | L4: implement small AWS adapters and operator controls. This is analysis/backlog work,; L24: \| Component / evidence \| Disposition and smallest necessary outcome \| Backlog owner / acceptance boundary \| |
| docs/execution/aws/readiness/github-map.json | 2026-10-15T02:05:27+08:00 | backlog | L9: "workflow": "Backlog",; L34: "workflow": "Backlog", |
| docs/execution/aws/readiness/lanes/a-storage.md | 2026-10-15T02:05:27+08:00 | review | L191: \| Reuse Lane B/D owned-state and per-service migration issue \| A-09/10; reuse PostgreSQL bootstrap/smoke, owner-specific task secr |
| docs/execution/aws/readiness/lanes/b-placement.md | 2026-10-15T02:05:27+08:00 | as a, review | L18: The accepted topology is credible as a **deployment target**, not an implemented; L60: \| **B-05** medium / **configure** \| **Plan:** architecture `:208–214` says private DNS queries are free; worksheet `cloudmap_api_c |
| docs/execution/aws/readiness/lanes/c-lifecycle.md | 2026-10-15T02:05:27+08:00 | backlog | L24: \| **C-L04 / Info / retain** \| `processing/service.py:49–117` commits queued intent before returning; `processing/main.py:75–79,127; L31: \| **C-L11 / Optional / optional** \| `architecture-plan.md:153–168,445–449` makes unattended launching optional; diagrams `70–73,10 |
| docs/execution/aws/readiness/lanes/d-delivery.md | 2026-10-15T02:05:27+08:00 | backlog, review | L62: \| **D-08 · High · configure** \| **O:** `compose/local/docker-compose.yml:61–68,95–102` runs separate `alembic -c media/alembic.ini; L67: \| **D-13 · High · blocked** \| **O:** `job-inputs.template.json` leaves account/profile/billing owner/currency/windows/source/appro |
| docs/execution/aws/readiness/remote-state.json | 2026-10-15T02:05:27+08:00 | backlog, review, sprint | L20: "readme": "Current phase: lean AWS readiness backlog; local delivery remains complete. Source: docs/execution/aws/readiness/README; L21: "shortDescription": "Completed local media platform plus dependency-ordered lean AWS adaptation backlog.", |
| docs/execution/aws/readiness/task-ledger.json | 2026-10-15T02:05:27+08:00 | backlog, review | L48: "role": "review",; L60: "verdict": "PASS for backlog readiness; deployment blocked" |
| docs/execution/aws/readiness/validation.json | 2026-10-15T02:05:27+08:00 | backlog | L2: "backlog_unique_keys": 28, |
| docs/execution/aws/v1/README.md | 2026-10-21T23:26:22+08:00 | as a, backlog, review | L22: and added backlog scaling, independent releases, the Processing-down proof (#196) and the unattended; L141: contracts live in [readiness/backlog.json](../readiness/backlog.json); legacy |
| docs/execution/aws/v1/audit.md | 2026-10-15T13:25:01+08:00 | as a, backlog, review | L11: One independent review of the uncommitted working tree against the stated; L12: baseline, authoritative architecture, V1 handoff/backlog/map, costs, current |
| docs/execution/aws/v1/backlog.json | 2026-10-15T13:25:01+08:00 | backlog, review | L142: "workflow": "Backlog",; L192: "workflow": "Backlog", |
| docs/execution/aws/v1/cloud-operator-20261015.md | 2026-10-18T02:12:43+08:00 | as a, sprint | L79: - Stack `dc2-v1-20261015t1146-bootstrap` from the previous sprint is present; L155: retained as a failure receipt. V1 foundation execution did not begin. |
| docs/execution/aws/v1/contracts/README.md | 2026-10-16T12:00:16+08:00 | as a | L18: row. `viewer` is accepted as a read-only actor for Processing. |
| docs/execution/aws/v1/deploy-runbook.md | 2026-10-21T20:30:29+08:00 | as a, backlog, review | L56: `db-bootstrap` and `migrations` are skipped, `applications` updates the stack as a change set; L131: **Dedicated agent user (authorized 2026-10-17).** The IAM user `flickpond-agent` (AdministratorAccess and `FlickPondRegionLock`; n |
| docs/execution/aws/v1/dlq-runbook.md | 2026-10-18T01:37:37+08:00 | as a | L64: envelope; treat it as a producer defect or injection and do not redrive it. |
| docs/execution/aws/v1/evidence/archive-20261018/README.md | 2026-10-18T21:19:04+08:00 | review | L47: deadline and a review period after it: |
| docs/execution/aws/v1/evidence/v2live-verify-20261019/README.md | 2026-10-20T01:15:39+08:00 | as a, backlog | L3: Sanitized receipts of the in-place update, the scaling and backlog measurements, the Processing; L19: \| Deploy smoke after the in-place update \| **FAIL** (run 39268999121) \| [`cd-39268999121-deploy-adopt/cloud-proof-smoke-3926899912 |
| docs/execution/aws/v1/fast-execution-review-20261015.txt | 2026-10-16T11:33:15+08:00 | backlog, review | L1: V1 FAST EXECUTION REVIEW — 15 OCTOBER 2026; L3: Result: implement existing #81–#92. The backlog is sufficient; tighten the |
| docs/execution/aws/v1/github-map.json | 2026-10-15T13:25:01+08:00 | backlog, review | L21: "workflow": "Backlog",; L34: "workflow": "Backlog", |
| docs/execution/aws/v1/local-runtime.md | 2026-10-18T21:15:45+08:00 | as a | L141: <assertion>`, and as a `::error` annotation in GitHub Actions. Beside the junit report the |
| docs/execution/aws/v2/database-topology.md | 2026-10-21T20:49:01+08:00 | as a, review | L164: which the change-set review refuses. The same review lets this one update remove; L255: needed. If only the pause or ceiling change is promising, take that alone as a third stack and |
| docs/execution/aws/v2/lambda-short-encodes.md | 2026-10-21T23:29:38+08:00 | as a, review | L161: review, the deploy and the stack update that adopts a release. The mapping is created; L311: for the Aurora resume, which is outside the lane. Do not read the 4 s as a Lambda defect. |
| docs/execution/aws/v2/unattended-launch.md | 2026-10-18T10:54:40+08:00 | as a, backlog | L38: \| Is there backlog? \| `demand = min(queued attempts in SQL, visible SQS messages)`. SQL is the durable truth; the queue count says; L131: A start that tracks real backlog replaces the operator-batch latency, not its cost. |
| docs/execution/backlog.json | 2026-10-13T00:41:46+08:00 | backlog, review | L58: "Multi-issue PR groups, review gates, resource isolation and stop conditions are explicit."; L61: "Validate backlog dependency DAG and unique stable keys.", |
| docs/execution/contract-evidence.json | 2026-10-13T05:08:10+08:00 | as a, review | L87: "scope": "Read-only V1/V2 review; runtime V4/performance independently reviewed and excluded.",; L96: "docs/execution/reviews/integration-review.md" |
| docs/execution/decisions.md | 2026-10-18T02:12:43+08:00 | review | L7: - Use GPT-6.1 Sol high implementers and xhigh planning review; isolated worktrees.; L23: - Planning review R1: V5 may deliver an honest handoff after an assessed V3 blocker; |
| docs/execution/experiments-20261014/README.md | 2026-10-18T02:12:43+08:00 | review | L80: [Fresh independent Sol review](../reviews/experiments-20261014-review.md) PASS |
| docs/execution/github-map.json | 2026-10-13T00:19:31+08:00 | backlog, review | L242: "name": "Backlog"; L254: "name": "Review" |
| docs/execution/handoff.md | 2026-10-16T12:21:27+08:00 | review | L14: [Independent correction review](reviews/postgres-readiness-review.md) PASS.; L29: [one fresh independent Sol review](reviews/experiments-20261014-review.md) PASS. |
| docs/execution/issue-map.md | 2026-10-18T02:12:43+08:00 | — | Structured planning/progress record |
| docs/execution/issues/C1.md | 2026-10-13T04:08:22+08:00 | review | L28: A grouped PR may close multiple related issues after independent review and checks. Record commands/results and the exact tested c |
| docs/execution/issues/C2.md | 2026-10-13T04:08:22+08:00 | review | L28: A grouped PR may close multiple related issues after independent review and checks. Record commands/results and the exact tested c |
| docs/execution/issues/E0.md | 2026-10-13T00:09:45+08:00 | review | L9: Completion requires all children merged with acceptance evidence and independent review. No AWS actions. Source: `docs/execution/p |
| docs/execution/issues/E1.md | 2026-10-13T00:09:45+08:00 | review | L9: Completion requires all children merged with acceptance evidence and independent review. No AWS actions. Source: `docs/execution/p |
| docs/execution/issues/E2.md | 2026-10-13T00:09:45+08:00 | review | L9: Completion requires all children merged with acceptance evidence and independent review. No AWS actions. Source: `docs/execution/p |
| docs/execution/issues/E3.md | 2026-10-13T00:09:45+08:00 | review | L9: Completion requires all children merged with acceptance evidence and independent review. No AWS actions. Source: `docs/execution/p |
| docs/execution/issues/E4.md | 2026-10-13T00:09:45+08:00 | review | L9: Completion requires all children merged with acceptance evidence and independent review. No AWS actions. Source: `docs/execution/p |
| docs/execution/issues/E5.md | 2026-10-13T00:09:45+08:00 | review | L9: Completion requires all children merged with acceptance evidence and independent review. No AWS actions. Source: `docs/execution/p |
| docs/execution/issues/F1.md | 2026-10-13T04:08:22+08:00 | review | L28: A grouped PR may close multiple related issues after independent review and checks. Record commands/results and the exact tested c |
| docs/execution/issues/F2.md | 2026-10-13T04:08:22+08:00 | review | L30: A grouped PR may close multiple related issues after independent review and checks. Record commands/results and the exact tested c |
| docs/execution/issues/F3.md | 2026-10-13T04:08:22+08:00 | review | L33: A grouped PR may close multiple related issues after independent review and checks. Record commands/results and the exact tested c |
| docs/execution/issues/G1.md | 2026-10-13T04:08:22+08:00 | backlog, review | L13: - [x] Multi-issue PR groups, review gates, resource isolation and stop conditions are explicit.; L17: - Validate backlog dependency DAG and unique stable keys. |
| docs/execution/issues/G2.md | 2026-10-13T04:08:22+08:00 | review | L3: As Jules, Sam, we need **independently review and correct the delivery plan** to complete the approved reusable-media workflow loc; L13: - [x] No implementation wave starts before the corrected plan passes review. |
| docs/execution/issues/M1.md | 2026-10-13T04:08:22+08:00 | review | L29: A grouped PR may close multiple related issues after independent review and checks. Record commands/results and the exact tested c |
| docs/execution/issues/M2.md | 2026-10-13T04:08:22+08:00 | review | L29: A grouped PR may close multiple related issues after independent review and checks. Record commands/results and the exact tested c |
| docs/execution/issues/M3.md | 2026-10-13T04:08:22+08:00 | review | L29: A grouped PR may close multiple related issues after independent review and checks. Record commands/results and the exact tested c |
| docs/execution/issues/P1.md | 2026-10-13T04:08:22+08:00 | review | L29: A grouped PR may close multiple related issues after independent review and checks. Record commands/results and the exact tested c |
| docs/execution/issues/P2.md | 2026-10-13T04:08:22+08:00 | review | L30: A grouped PR may close multiple related issues after independent review and checks. Record commands/results and the exact tested c |
| docs/execution/issues/P3.md | 2026-10-13T04:08:22+08:00 | review | L30: A grouped PR may close multiple related issues after independent review and checks. Record commands/results and the exact tested c |
| docs/execution/issues/V1.md | 2026-10-13T00:19:31+08:00 | review | L19: - Review CT mapping with exact test names and raw outputs.; L29: A grouped PR may close multiple related issues after independent review and checks. Record commands/results and the exact tested c |
| docs/execution/issues/V2.md | 2026-10-13T00:09:45+08:00 | review | L27: A grouped PR may close multiple related issues after independent review and checks. Record commands/results and the exact tested c |
| docs/execution/issues/V3.md | 2026-10-13T00:09:45+08:00 | review | L29: A grouped PR may close multiple related issues after independent review and checks. Record commands/results and the exact tested c |
| docs/execution/issues/V4.md | 2026-10-13T00:19:31+08:00 | review | L29: A grouped PR may close multiple related issues after independent review and checks. Record commands/results and the exact tested c |
| docs/execution/issues/V5.md | 2026-10-13T00:19:31+08:00 | review | L3: As Maya, Arun, Jules, Sam, we need **review final delivery and publish evidence-based morning handoff** to complete the approved r; L11: - [ ] Prerequisites: V2/V4 complete and V3 assessed with full scaling evidence OR a reproducible runner/pilot plus documented capa |
| docs/execution/performance-20261013/README.md | 2026-10-18T02:12:43+08:00 | review | L17: The linked epic/issues and PR retain the subsequent clean-context review gists, exact CI results, merge state and follow-up decisi |
| docs/execution/performance-20261013/clients.md | 2026-10-13T11:32:56+08:00 | review | L9: files remain those of the tested head. Independent review, secret-gist publication,; L111: were not rerun. The parent must obtain independent review and required CI. |
| docs/execution/performance-20261013/media.md | 2026-10-13T11:32:18+08:00 | as a, review | L106: change. Independent clean-context Sol review, live PostgreSQL integration and; L108: publishes this report as a secret gist and links tracking/PR/review evidence. |
| docs/execution/performance-20261013/processing.md | 2026-10-13T11:36:42+08:00 | review | L10: publication, independent Sol review, PR and CI. Those gates are not claimed here. |
| docs/execution/plan.md | 2026-10-15T13:25:01+08:00 | as a, backlog, review | L12: days maximum. This run is authorized to plan, implement, test, review, publish and; L20: visuals remain unchanged. The current issue contracts are in `backlog.json` and |
| docs/execution/progress.json | 2026-10-14T21:51:44+08:00 | backlog, review | L16: "docs/execution/plan.md, backlog.json and Project14 native hierarchy verified.",; L69: "PR28 draft; 635fast+41realowned checks and package gates pass; independent review and remoteCI running.", |
| docs/execution/reviews/clients-fixes.md | 2026-10-13T03:08:06+08:00 | review | L1: # C1/C2 review corrections; L13: ## Review snapshot |
| docs/execution/reviews/clients-rereview.md | 2026-10-13T03:24:43+08:00 | review | L9: Original lane review base: `e538819428d5586308d4e3288a66e99dd8d9de09`.; L10: Review date: 13 October 2026, Singapore. |
| docs/execution/reviews/clients-review.md | 2026-10-13T03:08:06+08:00 | as a, backlog, review | L7: Review date: 13 October 2026, Singapore.; L9: Independent review of the complete 13-file `base...head` diff, AGENTS.md, |
| docs/execution/reviews/clients-validation.md | 2026-10-13T03:24:43+08:00 | review | L4: browser retry, with all three independent-review corrections applied.; L27: review-driven assertion/restoration corrections are being completed before |
| docs/execution/reviews/contract-final.md | 2026-10-13T04:40:00+08:00 | review | L9: current PASS fields explicit and places the original review metadata in; L48: final-code-review Media-readiness R1 is resolved by final-code-rereview PASS and |
| docs/execution/reviews/contract-fixes.md | 2026-10-13T03:45:01+08:00 | review | L1: # Integration review R3 contract corrections; L5: The original integration review remains historical input. This is not final |
| docs/execution/reviews/delivery-review.md | 2026-10-13T08:35:03+08:00 | review | L7: Independent bounded final premerge review, 13 October 2026 Singapore.; L12: historical CHECKPOINT preserved verbatim below. No broad review or workload rerun. |
| docs/execution/reviews/final-code-rereview.md | 2026-10-13T04:06:15+08:00 | review | L2: ISSUE: #21 (V2), parent #6; R1 from final-code-review.md only; L3: PR: #31 (parent); local branch review/readiness |
| docs/execution/reviews/final-code-review.md | 2026-10-13T04:01:55+08:00 | review | L2: ISSUE: #20–#23 (V1–V4), parent #6; final code review for #24 (V5); L3: PR: #31 / review/final-local |
| docs/execution/reviews/foundation-cache-fix.md | 2026-10-13T01:25:34+08:00 | as a, review | L4: review update added R1 while PR26 was merging: the browser job rebuilt MinIO; L10: the existing integration cache as a fallback, loads the pinned image, and lets |
| docs/execution/reviews/foundation-cache-review.md | 2026-10-13T01:25:34+08:00 | review | L6: Bounded independent R1 re-review, 13 October 2026 (Singapore).; L70: Only this new review file was written. |
| docs/execution/reviews/foundation-coordinator-results.md | 2026-10-13T01:00:32+08:00 | review | L41: - Remote CI and independent grouped foundation review remain pending. |
| docs/execution/reviews/foundation-review.md | 2026-10-13T01:25:34+08:00 | as a, review | L5: RECORD STATUS: Attribution/history correction only; cache fix and re-review pending.; L9: Independent grouped foundation review, 13 October 2026 (Singapore). |
| docs/execution/reviews/foundation-runtime-results.md | 2026-10-13T00:52:37+08:00 | as a | L103: Parent packaging needs **HTTPX as a production dependency** for the upcoming |
| docs/execution/reviews/foundation-tools-results.md | 2026-10-13T00:50:04+08:00 | review | L4: `.worktrees/foundation-tools`. Plan PR #25 (`6ea8b9b`) and planning re-review PASS |
| docs/execution/reviews/integration-rereview.md | 2026-10-13T03:46:51+08:00 | review | L5: Independent, bounded R1–R4 correction review, 13 October 2026, Singapore. This; L18: integration-review.md, integration-fixes.md, contract-fixes.md and |
| docs/execution/reviews/integration-review.md | 2026-10-13T03:46:51+08:00 | as a, review | L14: - [blocked] Final V1 workflow/fresh-start evidence and full V2 raw recovery report are not yet run on the final combined head. Thi; L18: - [P2] R1 — scripts/dev/e2e_clients.py:53; scripts/evidence/recovery.py:40; scripts/evidence/recovery.py:62; scripts/evidence/reco |
| docs/execution/reviews/local-capacity-options.md | 2026-10-13T00:19:31+08:00 | review | L1: # Project-local scaling capacity: bounded feasibility review; L7: VMs started, or settings changed; this review is the only file written. |
| docs/execution/reviews/login-performance.md | 2026-10-13T02:50:21+08:00 | review | L85: Full-precision durations are also recorded below so the committed review retains |
| docs/execution/reviews/mac-hls-observer-rereview.md | 2026-10-13T04:34:11+08:00 | review | L5: PR: `review/hls-observer`, commit `422609b434102fd132b41c5bd9ab113d03984ed0`; L39: - Read supplied user guidance, worktree `AGENTS.md`, review-work skill, |
| docs/execution/reviews/media-fixes.md | 2026-10-13T02:29:40+08:00 | review | L1: # Media review R1 fix and regression evidence; L3: 13 October 2026. Review input: `media-review.md`, reviewed head |
| docs/execution/reviews/media-implementation.md | 2026-10-13T02:29:40+08:00 | review | L16: review-file-only commit does not change tested production or test files.; L19: `tests/integration/test_media_persistence.py`. This review is the only owned |
| docs/execution/reviews/media-rereview.md | 2026-10-13T02:50:21+08:00 | review | L59: - [pass] M1/M2/M3 regression scope — The previous review's passing dispositions; L69: - None. R1 is RESOLVED; no additional revision is required for this bounded review. |
| docs/execution/reviews/media-review.md | 2026-10-13T02:50:21+08:00 | review | L137: generated migration SQL strings**. Cosmetic, not a substantive review finding;; L143: - Review writes only this file. No product/shared-file edits, GitHub access, |
| docs/execution/reviews/media-validation.md | 2026-10-13T02:50:21+08:00 | review | L3: M1/M2/M3 (#15/#16/#17) are ready for independent-review reconciliation and remote; L14: - Independent initial review identified uncertain-write cleanup losing authority. |
| docs/execution/reviews/performance-runner-fixes.md | 2026-10-13T03:44:48+08:00 | backlog, review | L1: # V3 runner corrections for independent review R1–R5; L5: `performance-runner-review.md`, ready for independent recheck. Live V3 acceptance |
| docs/execution/reviews/performance-runner-rereview.md | 2026-10-13T03:45:01+08:00 | backlog, review | L11: Read the review-work skill, AGENTS.md, docs/project2-worklog.txt, V3/V1/E5 issue; L13: performance-runner-review.md, performance-runner-fixes.md and the full original |
| docs/execution/reviews/performance-runner-review.md | 2026-10-13T03:44:48+08:00 | backlog, review | L7: Independent bounded review of the runner only, completed 13 October 2026.; L62: - [pending, outside this review] Real pilots; 50 users/180 seconds and separate |
| docs/execution/reviews/performance-runner.md | 2026-10-13T03:44:48+08:00 | as a, backlog, review | L9: `tests/evidence/test_performance.py`, and this review. Shared dispatcher, Make,; L81: and is explicitly recorded as a local limitation. These are local observations, |
| docs/execution/reviews/performance-validation.md | 2026-10-13T08:35:03+08:00 | review | L6: This bounded offline review adds the completed latency delta to the accepted; L7: [scaling review](scaling-validation.md) and the independent delivery CHECKPOINT |
| docs/execution/reviews/planning-fixes.md | 2026-10-13T00:19:31+08:00 | backlog, review | L1: # Planning review dispositions; L3: All five must-fix findings from planning-review.md are addressed in plan.md, |
| docs/execution/reviews/planning-inspections.txt | 2026-10-13T00:09:45+08:00 | review | L7: produced by these inspections. Independent planning review is still pending. |
| docs/execution/reviews/planning-rereview.md | 2026-10-13T00:19:31+08:00 | backlog, review | L5: REVIEW: Independent planning re-review, 13 October 2026.; L6: SCOPE: R1–R5 and optional P3 from `planning-review.md`, their planning diffs and `planning-fixes.md`. No broader source audit or n |
| docs/execution/reviews/planning-review.md | 2026-10-13T00:19:31+08:00 | backlog, review | L6: REVIEW: Independent planning review, 13 October 2026. No implementation has begun.; L12: - [pass] The backlog has unique keys, valid dependencies and an acyclic DAG. Grouped PRs may build internal dependencies sequentia |
| docs/execution/reviews/postgres-readiness-fix.md | 2026-10-13T09:06:04+08:00 | review | L3: **Implementation/probe and [independent peer review](postgres-readiness-review.md) PASS;; L68: benchmark rerun. [Peer review](postgres-readiness-review.md) PASS. Parent owns corrective PR32 |
| docs/execution/reviews/postgres-readiness-review.md | 2026-10-13T09:06:04+08:00 | review | L6: Independent bounded peer review, 13 October 2026 Singapore. Reviewed the; L66: Only docs/execution/reviews/postgres-readiness-review.md written. No other edit, |
| docs/execution/reviews/processing-fixes.md | 2026-10-13T02:16:48+08:00 | review | L1: # Processing review R1 fix; L5: recovery tests, and this report. The copied independent review remains unchanged |
| docs/execution/reviews/processing-implementation.md | 2026-10-13T02:01:47+08:00 | review | L16: The final documentation commit updates `processing/README.md` and this review.; L17: Coordinator owns integration/publishing and independent review; issue closure is |
| docs/execution/reviews/processing-rereview.md | 2026-10-13T02:50:21+08:00 | review | L106: apart from the independent-review merge gate; corrected-head CI is pending; L112: - R1 and introduced regressions only. Read the review-work skill, AGENTS.md, |
| docs/execution/reviews/processing-review.md | 2026-10-13T02:50:21+08:00 | review | L5: Independent grouped review, 13 October 2026 (Singapore).; L10: including `processing/README.md`. This review also includes the parent's |
| docs/execution/reviews/processing-validation.md | 2026-10-13T01:59:23+08:00 | review | L3: P1/P2/P3 (#12/#13/#14) are implemented for independent review and CI. This is |
| docs/execution/reviews/release-active-rereview.md | 2026-10-13T04:01:55+08:00 | review | L3: PR: local review branch `review/release-active`; integrated change `862b482`; L5: Review date: 13 October 2026, Singapore. |
| docs/execution/reviews/release-active-work.md | 2026-10-13T03:55:03+08:00 | review | L7: `V4/release-rereview.md` path was absent; the existing review above is the source.; L72: DC2_DOCKER_HOST=unix:///offline-review-do-not-connect.sock \ |
| docs/execution/reviews/release-diagnostic-rereview.md | 2026-10-13T04:46:47+08:00 | review | L3: PR: local branch `review/release-diagnostic`; L46: - Read user instructions, root/worktree `AGENTS.md`, review-work skill, |
| docs/execution/reviews/release-fixes.md | 2026-10-13T03:45:01+08:00 | review | L1: # V4 release review R1–R3 corrections; L9: changed. The supplied `release-review.md` remains unchanged (SHA-256 |
| docs/execution/reviews/release-fixture-rereview.md | 2026-10-13T04:40:00+08:00 | review | L5: PR: `review/release-fixture`, commit `5d6c0cdba9789b555f3216b02e53a3c0852eb2fa`; L47: - Read user guidance, worktree `AGENTS.md`, review-work skill, |
| docs/execution/reviews/release-rereview.md | 2026-10-13T03:46:51+08:00 | review | L8: Review date: 13 October 2026, Singapore.; L109: - Read review-work `SKILL.md`, root/worktree `AGENTS.md`, worklog, local V4/E5/V1 |
| docs/execution/reviews/release-runner.md | 2026-10-13T03:44:48+08:00 | as a | L38: release status. Only `evidence` treats the expected bad candidate as a successful; L144: `DC2_PROCESSING_IMAGE` as a mutable build tag in `runtime.env`; never build/tag |
| docs/execution/reviews/scaling-session-rereview.md | 2026-10-13T04:21:10+08:00 | review | L3: PR: local branch review/scaling-session; no GitHub access; L9: Read the review-work skill, user/repository AGENTS.md, project2-worklog.txt, |
| docs/history/HANDOFF-20261015-aws-reconsideration.md | 2026-10-18T02:12:43+08:00 | as a, review, sprint | L31: The user requests a fresh architecture review by a more capable planning agent.; L88: The legacy `docs/proposal.md` and Project 1 sprint documents are not the current proposal. |
| docs/history/README-project1-and-pre-aws-local-stack.md | 2026-10-20T16:26:13+08:00 | as a, backlog, review, sprint | L63: Flickpond is a practice-module team project: an asynchronous video upload and processing platform. Sprint 1 proved the request pat; L88: \| [`docs/c-recovery-input-safety.md`](../c-recovery-input-safety.md)                   \| Sprint 3, track C: retry API, crop/clip v |
| docs/history/handoff-aws2-readiness-swarm-20261015.md | 2026-10-18T02:12:43+08:00 | as a, backlog, review | L8: # Handoff to GPT-6.1 Sol: swarm the AWS readiness gaps, build the backlog, audit it; L14: standard GPT-6.1 Sol agent independently audit the final findings and remote backlog**. |
| docs/known-traps.md | 2026-10-18T02:12:43+08:00 | as a, review, sprint | L9: Sprint 1's three functional bugs (BUG-01 to BUG-03) and ENV-01 are in; L10: [`sprint1-report.md`](sprint1-report.md) §4. This file covers the traps found |
| docs/project2-worklog.txt | 2026-10-18T21:19:04+08:00 | as a, backlog, review | L16: release/rollback evidence PASS at 331354d. These issues remain in Review under; L17: draft PR31, which covers V1-V5. V3 measurements and V5 final review/merge remain |
| docs/proposal.md | 2026-10-18T02:12:43+08:00 | as a, backlog, retrospective, review, sprint | L35: Overall, Flickpond will serve as a practical demonstration of modern software engineering principles—Agile development, microservi; L47: - Role-based access control will restrict Users to their own content, allow Content Moderators to review reported videos, and allo |
| docs/release/demo-release-manifest.md | 2026-10-22T13:13:28+08:00 | as a, backlog | L69: \| Scaling \| 0 to N to 0 from SQL backlog (launcher), not queue depth \|; L86: \| #238 scale 0 to 3 to 0 \| **PASS** \| PR #268; evidence-index Q7m; [`scaling-and-backlog.json`](../execution/aws/v1/evidence/v2liv |
| docs/release/engineering-handoff.md | 2026-10-22T13:13:28+08:00 | as a, backlog, burndown, retrospective, review, sprint | L28: - A 9 October roadmap snapshot still said implementation had not started. Treat it as a dated planning record, not current status.; L39: 5. V1 used per-run stacks and operator-started finite Fargate batches. The later V2-live mode keeps one persistent stack, updates  |
| docs/s2-03-auth-design.md | 2026-10-18T02:12:43+08:00 | as a, backlog, sprint | L1: > **Historical (Project 1 sprint 2).** The login, JWT-cookie and bcrypt decisions carried into Media (`media/services/security.py`; L7: as the record of *why*, not as a plan. |
| docs/scaling-notes.md | 2026-10-18T02:12:43+08:00 | as a, backlog, review, sprint | L6: **Status:** capacity analysis. Written before sprint 2; parts of it have since; L11: Companion to [`sprint1-report.md`](sprint1-report.md), which records what exists |
| docs/sprint1-plan.md | 2026-10-18T02:12:43+08:00 | as a, review, sprint, user stor | L3: # Sprint 1 — Team Plan & Contract; L5: **Sprint 1 goal:** Upload → queue → worker → status → play. No real transcoding — worker does a copy job as a stand-in for FFmpeg. |
| docs/sprint1-report.md | 2026-10-18T02:12:43+08:00 | as a, backlog, review, sprint | L3: # Sprint 1 — Team Record; L6: **Sprint window:** 4–10 September 2026 |
| docs/sprint2-backlog.md | 2026-10-18T02:12:43+08:00 | as a, backlog, review, sprint | L3: # Sprint 2 Backlog — what the sprint 1 review left open; L5: **Written:** 7 September 2026 · against `main` @ `40d5e6b` plus the review's fixes |
| docs/sprint2-plan.md | 2026-10-18T02:12:43+08:00 | as a, backlog, review, sprint | L3: # Sprint 2 — Plan; L8: **Sprint 1 ended:** 10 September 2026 |
| docs/sprint2-report.md | 2026-10-18T02:12:43+08:00 | as a, review, sprint | L3: # Sprint 2 — Team Record; L6: the sprint's first commit to the one deployed on 11 September |
| project-documentation/course-evidence-checklist.md | 2026-10-22T13:13:28+08:00 | backlog, burndown, retrospective, review, sprint | L38: \| Three design-problem bundles with alternatives, before/after, behavior, decisions and tests \| **Integrated / source-backed.** Th; L43: \| Backlog, stories, plans, burndown, reviews and retrospectives \| **Mixed.** GitHub issue/project history, proposal scope, dated r |
| project-documentation/effort-ledger.md | 2026-10-21T13:48:11+08:00 | review | L87: \| 5–7 Oct \| Baseline frozen; domain model and contracts drafted; lecturer review 7 Oct \| 7–9 Oct \| `project-roadmap/records/projec |
| project-documentation/final-report/README.md | 2026-10-21T13:48:11+08:00 | burnup | L14: \| `data/issue-burnup.csv` \| Issue counts per day from `gh issue list --state all`; drawn by `tools/chart_burnup.py` \|; L23: python3 project-documentation/final-report/tools/chart_burnup.py      # only if the CSV changed |
| project-documentation/final-report/src/10-introduction.md | 2026-10-22T03:07:07+08:00 | as a, backlog | L5: **FlickPond** began as a Project 1 video application. Users register and upload their own videos.; L72: backlog of uploads competes with logins and status checks. |
| project-documentation/final-report/src/20-conduct.md | 2026-10-22T03:07:07+08:00 | as a, backlog, burnup, retrospective, review, sprint | L12: \| 2 \| Domain analysis, service contracts and OpenAPI documents \| Long (team review) \| 3 \|; L44: - **Backlog.** Work was planned as GitHub issues with outcome, acceptance and verification |
| project-documentation/final-report/src/30-logical.md | 2026-10-22T03:07:07+08:00 | as a, backlog | L108: \| Capacity \| Start finite encoders from the SQL backlog, at most three; clips of 60 s or less go to the short-encode Lambda instea; L137: holds the owner as a plain UUID, never a foreign key. |
| project-documentation/final-report/src/32-physical.md | 2026-10-22T03:07:07+08:00 | as a, backlog | L27: \| Short encoder \| `ProcessingShortEncoder`: the Processing image as a Lambda container; SQS event source mapping on `ProcessingSho; L66: \| AD-27 \| **One persistent, always-on environment, updated in place, scaling to zero** \| Per-run stacks cost a 25-minute deploy an |
| project-documentation/final-report/src/34-persistence-detailed.md | 2026-10-22T03:07:07+08:00 | as a, backlog | L49: lifecycle of this deployment as a whole is set by AD-08 (fresh demonstration data only) and AD-27; L135: handling. They were left to the V2 backlog because the lease and outbox logic depends on SQL |
| project-documentation/final-report/src/36-other-limitations.md | 2026-10-22T03:07:07+08:00 | as a, backlog | L27: \| #271 \| A 503 instead of a 4xx when S3 refused an oversized upload was accepted as a known limitation at the freeze \| Fixed in th; L53: \| AISS-01 \| Measured performance misses \| Queue wait on the short lane is met: median 0.26 s against 32.6 s on Fargate (5 jobs per |
| project-documentation/final-report/src/40-quality.md | 2026-10-22T03:07:07+08:00 | backlog | L15: \| Scalability \| V2-live automatic scale 0 → 3 → 0 \| 0 → 3 → 0 with 3 concurrent clips; 9-clip backlog at cap 3 in 239 s (2.26 jobs; L95: of 13 alarms were `OK` after the backlog tests **[AWS]**. |
| project-documentation/final-report/src/50-devops.md | 2026-10-22T03:07:07+08:00 | review | L82: - require "Full verification" and one review on `Main` and `dev/closeout` through a ruleset; |
| project-documentation/final-report/src/60-other.md | 2026-10-22T03:07:07+08:00 | review | L84: OpenAI GPT models for independent review) during the project: |
| project-documentation/final-report/src/70-appendices.md | 2026-10-21T13:48:11+08:00 | as a, backlog | L68: - *Pre:* a durable Processing backlog; Media is deployed independently.; L99: \| UC-6 \| Operator, ProcessingCapacity \| `LauncherControl`, `LaunchReservation`, `AttemptTask`; `processing/launcher.py`, `launcher |
| project-documentation/original-reference/report-template-notes.md | 2026-10-09T04:07:29+08:00 | as a | L7: Project 1's [README](../../Media_player/README.md) describes Flickpond as a video upload/processing system with a browser frontend; L30: The course asks for logical and physical architecture, decisions, trade-offs, and measured quality attributes. A possible Project  |
| project-documentation/presentation/OUTLINE.md | 2026-10-22T17:30:50+08:00 | as a | L382: \| V3 \| S05/S46 \| Four theme tiles with icons, reused as a corner badge \| new (CSS) \| |
| project-documentation/presentation/SCRIPT-1-2.md | 2026-10-26T14:05:42+08:00 | sprint | L99: - **Why waves, not sprints?** It was four weeks with three people and hard dependencies, so issues were grouped by dependency. |
| project-documentation/presentation/SCRIPT-3-4.md | 2026-10-26T14:05:42+08:00 | as a | L87: > *(bottom row)* The result comes back the same way and lands in Media as a projection.; L133: > The Asset, in Media, pins the exact source, allows one job per asset, and is deleted as a tombstone so that late |
| project-documentation/presentation/SCRIPT-5-6.md | 2026-10-26T14:05:42+08:00 | backlog | L321: - **Is D4 ECS auto-scaling?** No. A launcher starts finite tasks from the backlog, capped at 3 by a database check, |
| project-documentation/presentation/SCRIPT-guruprasath.md | 2026-10-26T13:39:26+08:00 | backlog, sprint | L328: - **Why waves, not sprints?** It was four weeks with three people and hard dependencies, so issues were grouped by dependency.; L339: - **Is D4 ECS auto-scaling?** No. A launcher starts finite tasks from the backlog, capped at 3 by a database check, with a one-min |
| project-documentation/presentation/SLIDE-CHANGES.md | 2026-10-26T13:39:26+08:00 | review | L66: ## Round 3 (Guruprasath's review) |
| project-documentation/presentation/STYLE.md | 2026-10-22T17:30:50+08:00 | as a | L21: \| Headline **44 px** bold, body **30 px**, absolute minimum **24 px** for anything the audience must read. Footer/receipt line **1; L120: \| Never re-label a miss as a pass. Keep the original targets, the workload and the environment on the chip. \| Claims with receipts |
| project-documentation/presentation/feedback-20261026/FEEDBACK.md | 2026-11-10T22:36:59+08:00 | as a | L51: `76282d3` as a GitHub permalink: |
| project-documentation/presentation/feedback-20261026/REPORT-CHANGES.md | 2026-11-10T22:36:59+08:00 | as a, backlog, burnup, retrospective, review | L15: \| `attempts/{attempt}` can be read as a retry number \| Outputs use `jobs/{job_uuid}/attempts/{attempt_uuid}/`; `attempt_number` is; L25: \| All Main CI is green; all scanners publish SARIF and findings block merges \| The 25 Oct scheduled full CI failed in inherited im |
| project-documentation/presentation/feedback-20261026/WORKPLAN.md | 2026-11-10T22:36:59+08:00 | backlog | L28: 1. **No code, IaC or workflow changes.** Code-only fixes go in your report notes under "CODE backlog".; L35: - `report-notes/Wn.md`: the report changes for your scope. Give the target file and heading in `final-report/src/`, then draft tex |
| project-documentation/presentation/feedback-20261026/report-notes/W1.md | 2026-11-10T22:36:59+08:00 | as a, backlog, review | L107: Add `W1-network.svg`; preserve any dated port-scan claim only with its existing receipt, not as a source-derived fresh scan.; L124: Publication labelled `processing-work` calls `WakeOnWork.send` and asynchronously invokes ProcessingLauncher only after its SQS se |
| project-documentation/presentation/feedback-20261026/report-notes/W2.md | 2026-11-10T22:36:59+08:00 | as a, backlog, review | L9: `slides/W2.html` contains complete sections using the existing deck CSS. Do not paste the review page into the deck. Preserve the ; L62: Aggregate boundaries protect invariants rather than collect all related tables. References to another root do not make it a child. |
| project-documentation/presentation/feedback-20261026/report-notes/W3-qa/slides-manifest.json | 2026-11-10T22:36:59+08:00 | review | L2: "superseded_by": "../../review/W3-qa/verification.json", |
| project-documentation/presentation/feedback-20261026/report-notes/W3-qa/source-signatures.json | 2026-11-10T22:36:59+08:00 | review | L1361: "superseded_by": "../../review/W3-qa/class-signature-audit.json" |
| project-documentation/presentation/feedback-20261026/report-notes/W3-qa/verification.json | 2026-11-10T22:36:59+08:00 | review | L281: "superseded_by": "../../review/W3-qa/verification.json" |
| project-documentation/presentation/feedback-20261026/report-notes/W3-qa/visual-inspection.json | 2026-11-10T22:36:59+08:00 | as a, review | L37: "Checked final edit as a complete two-panel slide in html_preview at width 1280.",; L43: "superseded_by": "../../review/W3-qa/verification.json" |
| project-documentation/presentation/feedback-20261026/report-notes/W3.md | 2026-11-10T22:36:59+08:00 | as a, backlog, review | L20: All other sections are `data-kind="back"` and `<!-- NEW backup -->`, except the preserved `<!-- REPLACES s61 -->` and `<!-- REPLAC; L24: The coordinator renumbers the finished talk and integrates these fragments. `site/deck.html` remains untouched by this review. |
| project-documentation/presentation/feedback-20261026/report-notes/W4.md | 2026-11-10T22:36:59+08:00 | as a, backlog, review | L9: Target `project-documentation/final-report/src/32-physical.md`, heading **Technology and Services**: add the proposed ADR below af; L60: A received command commits its inbox identity, domain changes and newly staged work/result envelopes in one Processing transaction |
| project-documentation/presentation/feedback-20261026/report-notes/W5.md | 2026-11-10T22:36:59+08:00 | as a, backlog, review | L22: Slide 32 needs no replacement for this scope. If the coordinator keeps the old slide 37 incident story, retain it as a dated histo; L57: The independent review refreshed this setting through authenticated `gh api`: Main returned `protected=false`, its protection endp |
| project-documentation/presentation/feedback-20261026/report-notes/W6-QA.md | 2026-11-10T22:36:59+08:00 | review | L7: - Every final slide was rendered by T3 `html_preview` at **1280×720** and visually inspected, including all six figures. Seven PNG |
| project-documentation/presentation/feedback-20261026/report-notes/W6.md | 2026-11-10T22:36:59+08:00 | as a, backlog, review | L29: \| Context and scenarios \| Who uses the platform, and why? \| Scope/use cases; ARCHSS 4+1 scenarios; C4 context as a scope compariso; L40: The course mapping explains how we apply earlier design skills. The [ARCHSS course description](https://www.iss.nus.edu.sg/executi |
| project-documentation/presentation/feedback-20261026/research/R1-old-deck-lessons.md | 2026-11-10T22:36:59+08:00 | as a | L59: 3. **Abstraction levels are named and connected.** The overview p. 6, analysis objects p. 7, interactions pp. 8-9, design abstract; L88: - The right half is explicitly **proposed**, with Media -> Processing `token`, Redis/RQ and persistent worker/recovery boxes. It i |
| project-documentation/presentation/feedback-20261026/research/R2-runtime-deployment-truth.md | 2026-11-10T22:36:59+08:00 | as a, backlog | L36: 2. `read_token()` verifies the HS256 JWT using Media's secret, requires `sub`, `exp`, `iat`, and parses `sub` as a UUID. There is ; L137: 2. The launcher reads SQL queued current Attempts and **approximate visible depth of standard ProcessingWorkQueue**; it observes E |
| project-documentation/presentation/feedback-20261026/research/R3-ddd-design-data.md | 2026-11-10T22:36:59+08:00 | as a, backlog, review | L126: \| Invariants \| `_reserve` locks control and open reservations, reconciles ECS observations and reserves only available capacity us; L1680: Payloads reject keys suggestive of secrets/credentials/tokens/media bytes and HTTP(S) URL strings; the envelope validates data, wh |
| project-documentation/presentation/feedback-20261026/research/R4-feedback-audit.md | 2026-11-10T22:36:59+08:00 | as a, backlog, burndown, retrospective, review, user stor | L3: Audit date: 26 October 2026. Source: `76282d3b5a141f6548056f2506f9d5aff0742692` (`76282d3`), in the `dc2-rescue` worktree. Read `F; L44: - **verdict:** **weak** in the deck; the report contains substantially more workflow detail. Interpretation: the assessor likely u |
| project-documentation/presentation/feedback-20261026/research/R5-external-references.md | 2026-11-10T22:36:59+08:00 | as a, backlog, review, user stor | L30: \| C4 \| [Software Analysis & Design](https://www.iss.nus.edu.sg/executive-education/course/detail/object--oriented-analysis-design/; L79: \| D8 \| [DDD Aggregate](https://martinfowler.com/bliki/DDD_Aggregate.html) \| Martin Fowler \| An aggregate groups domain objects as  |
| project-documentation/presentation/feedback-20261026/review/DECK-QA/initial-pdf-text.txt | 2026-11-10T22:36:59+08:00 | as a | L1702: Clip D2 · Publisher as a producer   the public contract |
| project-documentation/presentation/feedback-20261026/review/DECK-QA/initial-slides.json | 2026-11-10T22:36:59+08:00 | as a, backlog, review | L109: "notes": "S10a \u00b7 W6 integration fragment Point across a single row: question, model, course, then the slide that answers it. ; L203: "notes": "Point to the Asset entity root, the 0..1 derived SourceVersion value record and the six-field Source value. SourceVersio |
| project-documentation/presentation/feedback-20261026/review/DECK-QA/initial-text.txt | 2026-11-10T22:36:59+08:00 | as a, backlog, review | L43: NOTES: S10a · W6 integration fragment Point across a single row: question, model, course, then the slide that answers it. The tabl; L75: NOTES: Point to the Asset entity root, the 0..1 derived SourceVersion value record and the six-field Source value. SourceVersion i |
| project-documentation/presentation/feedback-20261026/review/DECK-QA.md | 2026-11-10T22:36:59+08:00 | as a, review | L3: **PASS after corrections for slide layout, source consistency, ordering and navigation. One presentation-media issue remains OPEN:; L15: \| DQA-03 \| P2 \| 17 `s11` (initially slide 12), followed by 18 `s16` through 21 `w2-messages` \| DDD boundary rationale interrupted  |
| project-documentation/presentation/feedback-20261026/review/W1-qa.json | 2026-11-10T22:36:59+08:00 | review | L2: "schema": "w1-review-qa-v1", |
| project-documentation/presentation/feedback-20261026/review/W1-review.md | 2026-11-10T22:36:59+08:00 | as a, backlog, review | L1: # W1 independent review — 26 October 2026; L5: Scope: [12 slide sections](../slides/W1.html), all nine `W1-*.puml/.svg/.png` figure sets, and [W1 report notes](../report-notes/W |
| project-documentation/presentation/feedback-20261026/review/W2-review.md | 2026-11-10T22:36:59+08:00 | as a, review | L1: # W2 independent review, 26 October 2026; L3: **PASS for the documentation handoff after the fixes below.** This is a review of the as-built explanation, not a claim of assesso |
| project-documentation/presentation/feedback-20261026/review/W3-qa/before-sources.json | 2026-11-10T22:36:59+08:00 | as a, backlog | L2: "project-documentation/presentation/feedback-20261026/slides/W3.html": "<!-- REPLACES s28 -->\n<section class=\"slide\" id=\"s28\"; L3: "project-documentation/presentation/feedback-20261026/report-notes/W3.md": "# W3 detailed design handoff\n\nBaseline: Main `76282d |
| project-documentation/presentation/feedback-20261026/review/W3-qa/verification.json | 2026-11-10T22:36:59+08:00 | review | L20: "/Users/speedpowermac/Documents/projects/CODE_MAIN/NUS/dc2-rescue/project-documentation/presentation/feedback-20261026/review/W3-q; L21: "/Users/speedpowermac/Documents/projects/CODE_MAIN/NUS/dc2-rescue/project-documentation/presentation/feedback-20261026/review/W3-q |
| project-documentation/presentation/feedback-20261026/review/W3-review.md | 2026-11-10T22:36:59+08:00 | as a, review | L1: # W3 independent review — 26 October 2026; L3: **Result: PASS with corrections applied.** Scope is the two selected detailed-design cases, edit, components and state models at M |
| project-documentation/presentation/feedback-20261026/review/W4-qa/baseline-hashes.json | 2026-11-10T22:36:59+08:00 | review | L37: "project-documentation/presentation/feedback-20261026/report-notes/W4-review.py": "a870f33c7731880992e856978e7ef5da3400e0d182d720b |
| project-documentation/presentation/feedback-20261026/review/W4-qa/permalinks-final.json | 2026-11-10T22:36:59+08:00 | as a, review | L10: "project-documentation/presentation/feedback-20261026/review/W4-review.md:25",; L751: "project-documentation/presentation/feedback-20261026/review/W4-review.md:25", |
| project-documentation/presentation/feedback-20261026/review/W4-review.md | 2026-11-10T22:36:59+08:00 | backlog, review | L1: # W4 independent review — 26 October 2026; L5: Read FEEDBACK.md and WORKPLAN.md first. Work was confined to W4 documentation, figures and review evidence in the dc2-rescue workt |
| project-documentation/presentation/feedback-20261026/review/W5-review.md | 2026-11-10T22:36:59+08:00 | as a, backlog, review | L17: - **Finding:** CodeQL appeared as a PR activity branch without explicit completion, while `A` was drawn as an ordinary rounded act; L33: - **Fix applied:** Named `RETAINED_FIXABLE` as a Trivy-only exception. Added ECR COMPLETE/no-unaccepted-HIGH/CRITICAL requirements |
| project-documentation/presentation/feedback-20261026/review/W6-review-qa/manifest.json | 2026-11-10T22:36:59+08:00 | review | L4: "project-documentation/presentation/feedback-20261026/review/W6-review.md": "1c24c9c992ba5c5ee73dfbf424285c018dfbc618f057d080e1286; L5: "project-documentation/presentation/feedback-20261026/review/W6-review-preview.html": "f0d66315bd3cdd267f4253c9b979448ca57a8b94906 |
| project-documentation/presentation/feedback-20261026/review/W6-review-qa/permalinks.json | 2026-11-10T22:36:59+08:00 | review | L82: "file": "project-documentation/presentation/feedback-20261026/review/W6-review.md",; L150: "file": "project-documentation/presentation/feedback-20261026/review/W6-review.md", |
| project-documentation/presentation/feedback-20261026/review/W6-review.md | 2026-11-10T22:36:59+08:00 | as a, backlog, review | L12: \| W6-R02 · P2 \| `s10-views`; report “Architecture views” \| The pipeline was attributed to 4+1 development. That view concerns stat; L20: \| W6-R10 · P3 \| `s12`/`s13`/`s19` notes; report citations \| The Media publishing link began at SQS transport construction instead  |
| project-documentation/presentation/feedback-20261026/slides/W5-qa/verification.json | 2026-11-10T22:36:59+08:00 | review | L4: "reviewer": "Independent W5 review",; L206: "settings_receipt": "review-settings.json", |
| project-documentation/presentation/research/sections-1-4.md | 2026-10-22T17:24:26+08:00 | as a, backlog, burnup, review, sprint, velocity | L5: - **Research boundary:** repository-only review on 22 Oct; no AWS or GitHub access, no live-system verification. “Deployed” below ; L56: \| What business problem is different from building a video site? \| Applications repeatedly need the same safe intake-to-playback w |
| project-documentation/presentation/research/sections-5-6-demo.md | 2026-10-22T17:24:26+08:00 | as a, backlog, review | L74: \| 21 Oct; CD **39637798081** \| ECR release plan rejected worker CVE-2025-52290, absent from accepted findings. \| Accepted-unfixed ; L76: \| 19 Oct; duplicate-message retest \| Backlog work left stale duplicates; smoke exposed them. Later run had **18 sends for 9 jobs** |
| project-documentation/presentation/site/BRIEF.md | 2026-10-23T13:56:12+08:00 | as a | L66: ("Maya uploads…", "As a … I want …"). Say "an owner uploads a video". |
| project-documentation/project-2-baseline-and-plan.txt | 2026-10-09T04:07:29+08:00 | review, sprint | L23: The review checked code, representative tests, reports and GitHub CI results.; L51: Reports, review decisions, hide/restore and moderation audit history do not exist. |
| project-documentation/project-2-requirements-and-scope.txt | 2026-10-09T04:07:29+08:00 | review | L257: - 7 October: lecturer proposal review. |
| project-documentation/report-authoring-handover.md | 2026-10-21T15:45:43+08:00 | as a, backlog, burndown, retrospective, review, sprint | L126: \| 5.1 Source Control Strategy \| [Repository map](../README.md); [contract change policy](../contracts/README.md); current Git/PR h; L141: \| G4 \| Current source-control authentication and governance are not fully documented. \| Record the real developer login/access met |
| project-roadmap/README.txt | 2026-10-09T04:07:29+08:00 | review | L16: The review is a 9 October planning snapshot. Dates do not imply completed work.; L18: Review marks are stored only in this browser. They are not team completion records. |
| project-roadmap/business-scope.json | 2026-10-09T04:07:29+08:00 | as a, backlog, review | L13: "channel": "Publisher CLI, then browser review",; L88: "context": "Sam operates the demonstration platform. Backlogs and new releases require changes to processing capacity and software |
| project-roadmap/design/03-ddd/content.json | 2026-10-09T04:07:29+08:00 | review | L11: "Draft design for team review, grounded in the accepted Team 17 proposal and selected local baseline 885453726d629c524bf511d665311; L403: "If genuinely independent identity or delivery rules/consumers emerge, consolidation may need review; current personas and owner-o |
| project-roadmap/design/03-ddd/diagram-manifest.json | 2026-10-09T04:07:29+08:00 | review | L61: "review": "Reconciled to step 05: queued attempt reservation, live read-time composition and primary output compatibility; visuall; L114: "review": "Reconciled to step 05: queued attempt reservation, live read-time composition and primary output compatibility; visuall |
| project-roadmap/design/04-architecture/AD-01.md | 2026-10-09T04:07:29+08:00 | review | L4: Owner: Long (architecture documentation); Ibrahim (implementation review); team review pending; L33: - Review aggregates and invariants against detailed step 03 DDD and F-01. |
| project-roadmap/design/04-architecture/AD-02.md | 2026-10-09T04:07:29+08:00 | review | L4: Owner: Long (architecture documentation); Ibrahim (implementation review); team review pending |
| project-roadmap/design/04-architecture/AD-03.md | 2026-10-09T04:07:29+08:00 | backlog, review | L4: Owner: Long (architecture documentation); Ibrahim (implementation review); team review pending; L30: - Pending admission can build backlog while P is unavailable; durability does not guarantee a finish time. |
| project-roadmap/design/04-architecture/AD-04.md | 2026-10-09T04:07:29+08:00 | review | L4: Owner: Long (architecture documentation); Ibrahim (implementation review); team review pending |
| project-roadmap/design/04-architecture/AD-05.md | 2026-10-09T04:07:29+08:00 | review | L4: Owner: Long (architecture documentation); Ibrahim (implementation review); team review pending |
| project-roadmap/design/04-architecture/AD-06.md | 2026-10-09T04:07:29+08:00 | review | L4: Owner: Long (architecture documentation); Ibrahim (implementation review); team review pending |
| project-roadmap/design/04-architecture/AD-07.md | 2026-10-09T04:07:29+08:00 | backlog, review | L4: Owner: Long (architecture documentation); Ibrahim (implementation review); team review pending; L36: - Record CPU, memory, queue and storage contention under fixed backlog; verify MM release unchanged. |
| project-roadmap/design/04-architecture/AD-08.md | 2026-10-09T04:07:29+08:00 | review | L4: Owner: Long (architecture documentation); Ibrahim (implementation review); team review pending |
| project-roadmap/design/04-architecture/README.md | 2026-10-09T04:07:29+08:00 | review | L3: Status: designed for team review; not implemented or measured. Reconciled with owner step 05 content and all three OpenAPI files. |
| project-roadmap/design/04-architecture/architecture-decisions.json | 2026-10-09T04:07:29+08:00 | backlog, review | L8: "owner": "Long (architecture documentation); Ibrahim (implementation review); team review pending",; L26: "Review aggregates and invariants against detailed step 03 DDD and F-01.", |
| project-roadmap/design/04-architecture/content.json | 2026-10-09T04:07:29+08:00 | as a, backlog, review | L14: "Draft architecture prepared for team review on 9 October 2026. All proposed components, decisions and checks are designed, not im; L16: "P-01 Maya and P-02 Arun own and review their own content. P-03 Jules integrates the same public API; P-04 Sam operates releases a |
| project-roadmap/design/04-architecture/logical-architecture.md | 2026-10-09T04:07:29+08:00 | as a, backlog, review | L7: Draft architecture prepared for team review on 9 October 2026. All proposed components, decisions and checks are designed, not imp; L11: P-01 Maya and P-02 Arun own and review their own content. P-03 Jules integrates the same public API; P-04 Sam operates releases an |
| project-roadmap/design/05-contracts/content.json | 2026-10-09T04:07:29+08:00 | backlog | L48: "Backlogs do not require long-lived source credentials." |
| project-roadmap/design/05-contracts/design-review.txt | 2026-10-09T04:07:29+08:00 | review | L1: Independent step 05 design review — PASS; L4: Design review only: no app execution, runtime tests, dependency installation, |
| project-roadmap/design/05-contracts/processing.openapi.json | 2026-10-09T04:07:29+08:00 | as a | L142: "description": "Owner filter must run in the database query. No unscoped list operation. MM detects missing submitted jobs as a re |
| project-roadmap/design/06-security-recovery/choices.json | 2026-10-09T04:07:29+08:00 | review | L34: "confirmation": "Team confirmation pending; heartbeat is the documented default. Modal click is personal review only." |
| project-roadmap/design/06-security-recovery/content.json | 2026-10-09T04:07:29+08:00 | review | L9: "Recommended defaults below permit later local implementation. Team confirmation means recording a choice; clicking a website moda |
| project-roadmap/design/07-deployment/content.json | 2026-10-09T04:07:29+08:00 | review | L11: "Website choices and status clicks are personal review aids. They do not approve spending, deployment, or a proposal amendment."; L38: "MM, worker and Processing cleanup receive separate secret mounts. A worker uses its local digest and successful upload/checksum a |
| project-roadmap/design/07-deployment/deployment-plan.md | 2026-10-09T04:07:29+08:00 | review | L13: Website choices and status clicks are personal review aids. They do not approve spending, deployment, or a proposal amendment.; L29: MM, worker and Processing cleanup receive separate secret mounts. A worker uses its local digest and successful upload/checksum ac |
| project-roadmap/design/08-build-readiness/content.json | 2026-10-12T21:10:20+08:00 | backlog, review | L10: "31 person-days is the accepted estimate, never actual hours. Confirm day length before converting logged hours; do not assume eig; L30: "Use 30 distinct fresh Assets containing identical owned 60s 720p video with audio; record source SHA-256, codec/audio metadata. S |
| project-roadmap/design/08-build-readiness/effort-log.csv | 2026-10-09T04:07:29+08:00 | — | Structured planning/progress record |
| project-roadmap/design/08-build-readiness/progress-template.txt | 2026-10-12T21:10:20+08:00 | — | Structured planning/progress record |
| project-roadmap/earlier-choices.json | 2026-10-09T04:07:29+08:00 | backlog, review | L50: "confirmation": "Proposal decision already recorded. Detailed design remains for team review; validation is not run. Comparing alt; L116: "confirmation": "Proposal decision already recorded. Detailed design remains for team review; validation is not run. Comparing alt |
| project-roadmap/records/project-decisions.txt | 2026-10-12T21:10:20+08:00 | as a, review | L25: The user plans to stop using Media_player as a submodule and move to the; L60: This is a design response for team review, not a new lecturer approval or |
| project-roadmap/roadmap-data.json | 2026-10-12T21:10:20+08:00 | backlog, review | L8: "owner": "Guruprasath \u00b7 team review",; L55: "done": "Step 02 material is prepared for team review. There is no unresolved business-scope question blocking the next discussion |

### Retained runtime results and progress evidence

| Path | Last committed change | Bytes |
|---|---|---|
| docs/execution/aws/README-20261014.md | 2026-10-18T02:12:43+08:00 | 3930 |
| docs/execution/aws/README.md | 2026-10-15T13:25:01+08:00 | 1981 |
| docs/execution/aws/prep/README.md | 2026-10-15T13:25:01+08:00 | 4004 |
| docs/execution/aws/readiness/README.md | 2026-10-15T13:25:01+08:00 | 12070 |
| docs/execution/aws/v1/README.md | 2026-10-21T23:26:22+08:00 | 13287 |
| docs/execution/aws/v1/contracts/README.md | 2026-10-16T12:00:16+08:00 | 7951 |
| docs/execution/aws/v1/evidence/archive-20261018/README.md | 2026-10-18T21:19:04+08:00 | 5746 |
| docs/execution/aws/v1/evidence/r1018b-results.md | 2026-10-18T08:05:57+08:00 | 7966 |
| docs/execution/aws/v1/evidence/s229-live-results.md | 2026-10-19T21:25:15+08:00 | 4376 |
| docs/execution/aws/v1/evidence/v2live-verify-20261019/README.md | 2026-10-20T01:15:39+08:00 | 11036 |
| docs/execution/experiments-20261014/README.md | 2026-10-18T02:12:43+08:00 | 4786 |
| docs/execution/experiments-20261014/progress-history.json | 2026-10-14T21:37:05+08:00 | 11059 |
| docs/execution/handoff.md | 2026-10-16T12:21:27+08:00 | 16981 |
| docs/execution/performance-20261013/README.md | 2026-10-18T02:12:43+08:00 | 2723 |
| docs/execution/progress.json | 2026-10-14T21:51:44+08:00 | 21970 |
| docs/execution/reviews/foundation-coordinator-results.md | 2026-10-13T01:00:32+08:00 | 2679 |
| docs/execution/reviews/foundation-runtime-results.md | 2026-10-13T00:52:37+08:00 | 12483 |
| docs/execution/reviews/foundation-tools-results.md | 2026-10-13T00:50:04+08:00 | 9684 |

## Reusable visual asset manifest

Sizes are exact bytes. Descriptions below are derived from SVG text, PlantUML titles, filenames, adjacent source files and documented captions, rather than a visual quality/readability assessment. All requested report figures, architecture figures, image-directory assets, presentation assets and showcase assets are listed, including source/render pairs. Font/code support files are omitted. SVG/PNG pairs typically show the same diagram; `.puml`/`.mmd` are editable sources.

| Path | Bytes | Last committed change | What it depicts / source-derived description |
|---|---|---|---|
| project-documentation/final-report/figures/actual-vs-target.png | 113091 | 2026-10-21T13:48:11+08:00 | actual vs target |
| project-documentation/final-report/figures/architecture-before-after.png | 216912 | 2026-10-21T13:48:11+08:00 | architecture before after |
| project-documentation/final-report/figures/aws-topology.png | 480814 | 2026-10-22T03:07:07+08:00 | aws topology |
| project-documentation/final-report/figures/cover-logo.png | 68559 | 2026-10-21T13:48:11+08:00 | cover logo |
| project-documentation/final-report/figures/ddd-01-context-map.png | 232784 | 2026-10-21T13:48:11+08:00 | ddd 01 context map |
| project-documentation/final-report/figures/ddd-context-map.png | 250820 | 2026-10-21T13:48:11+08:00 | ddd context map |
| project-documentation/final-report/figures/deployment-pipeline.png | 104122 | 2026-10-21T13:48:11+08:00 | deployment pipeline |
| project-documentation/final-report/figures/domain-model.png | 214468 | 2026-10-21T13:48:11+08:00 | domain model |
| project-documentation/final-report/figures/platform-context.png | 167840 | 2026-10-21T13:48:11+08:00 | platform context |
| project-documentation/final-report/figures/report-burnup.png | 86319 | 2026-10-21T13:48:11+08:00 | report burnup |
| project-documentation/final-report/figures/report-cicd.png | 276409 | 2026-10-21T13:51:17+08:00 | report cicd |
| project-documentation/final-report/figures/report-context-map.png | 209001 | 2026-10-21T13:48:11+08:00 | report context map |
| project-documentation/final-report/figures/report-dp1-capacity-release.png | 163873 | 2026-10-21T13:48:11+08:00 | report dp1 capacity release |
| project-documentation/final-report/figures/report-dp2-handoff.png | 159129 | 2026-10-21T13:48:11+08:00 | report dp2 handoff |
| project-documentation/final-report/figures/report-dp3-identity.png | 127836 | 2026-10-21T13:48:11+08:00 | report dp3 identity |
| project-documentation/final-report/figures/report-logical.png | 211585 | 2026-10-21T13:48:11+08:00 | report logical |
| project-documentation/final-report/figures/report-schedule.png | 122498 | 2026-10-21T13:51:17+08:00 | report schedule |
| project-documentation/final-report/figures/report-seq-encode.png | 330110 | 2026-10-22T03:07:07+08:00 | report seq encode |
| project-documentation/final-report/figures/report-seq-intake.png | 216238 | 2026-10-21T13:48:11+08:00 | report seq intake |
| project-documentation/final-report/figures/report-seq-play.png | 246540 | 2026-10-21T13:48:11+08:00 | report seq play |
| project-documentation/final-report/figures/report-use-cases.png | 213946 | 2026-10-21T13:51:17+08:00 | report use cases |
| project-documentation/final-report/figures/src/ddd-01-context-map.mmd | 1174 | 2026-10-21T13:48:11+08:00 | ddd 01 context map |
| project-documentation/final-report/figures/src/report-burnup.svg | 4880 | 2026-10-21T13:48:11+08:00 | GitHub issues, cumulative opened and closed per day (UTC), 12–21 October 2026; 0; 40; 80; 120 |
| project-documentation/final-report/figures/src/report-cicd.mmd | 1427 | 2026-10-21T13:48:11+08:00 | report cicd |
| project-documentation/final-report/figures/src/report-context-map.mmd | 1175 | 2026-10-21T13:48:11+08:00 | report context map |
| project-documentation/final-report/figures/src/report-dp1-capacity-release.mmd | 1014 | 2026-10-21T13:48:11+08:00 | report dp1 capacity release |
| project-documentation/final-report/figures/src/report-dp2-handoff.mmd | 902 | 2026-10-21T13:48:11+08:00 | report dp2 handoff |
| project-documentation/final-report/figures/src/report-dp3-identity.mmd | 731 | 2026-10-21T13:48:11+08:00 | report dp3 identity |
| project-documentation/final-report/figures/src/report-logical.mmd | 1239 | 2026-10-21T13:48:11+08:00 | report logical |
| project-documentation/final-report/figures/src/report-schedule.mmd | 1230 | 2026-10-21T13:48:11+08:00 | report schedule |
| project-documentation/final-report/figures/src/report-seq-encode.mmd | 1341 | 2026-10-22T03:07:07+08:00 | report seq encode |
| project-documentation/final-report/figures/src/report-seq-intake.mmd | 896 | 2026-10-21T13:48:11+08:00 | report seq intake |
| project-documentation/final-report/figures/src/report-seq-play.mmd | 927 | 2026-10-21T13:48:11+08:00 | report seq play |
| project-documentation/final-report/figures/src/report-use-cases.mmd | 1111 | 2026-10-21T13:48:11+08:00 | report use cases |
| project-documentation/final-report/figures/src/use-case-design-01-shared-analysis-class-model.mmd | 682 | 2026-10-21T13:48:11+08:00 | use case design 01 shared analysis class model |
| project-documentation/final-report/figures/src/use-case-design-02-common-implemented-design-class-model.mmd | 1241 | 2026-10-21T13:48:11+08:00 | use case design 02 common implemented design class model |
| project-documentation/final-report/figures/src/use-case-design-03-analysis-sequence-uc-1-uc-3-core-workflow.mmd | 953 | 2026-10-21T13:48:11+08:00 | use case design 03 analysis sequence uc 1 uc 3 core workflow |
| project-documentation/final-report/figures/src/use-case-design-04-analysis-sequence-uc-4-and-uc-5-retry-integration.mmd | 672 | 2026-10-21T13:48:11+08:00 | use case design 04 analysis sequence uc 4 and uc 5 retry integration |
| project-documentation/final-report/figures/src/use-case-design-05-analysis-sequence-uc-6-and-uc-7-operations.mmd | 816 | 2026-10-21T13:48:11+08:00 | use case design 05 analysis sequence uc 6 and uc 7 operations |
| project-documentation/final-report/figures/src/use-case-design-06-implemented-sequence-uc-1-uc-3-upload-process-and-play.mmd | 2690 | 2026-10-21T13:48:11+08:00 | use case design 06 implemented sequence uc 1 uc 3 upload process and play |
| project-documentation/final-report/figures/src/use-case-design-07-implemented-sequence-uc-4-and-uc-5-publisher-stored-source-retry.mmd | 1611 | 2026-10-21T13:48:11+08:00 | use case design 07 implemented sequence uc 4 and uc 5 publisher stored source retry |
| project-documentation/final-report/figures/src/use-case-design-08-implemented-sequence-uc-6-capacity-and-uc-7-release.mmd | 2049 | 2026-10-21T13:48:11+08:00 | use case design 08 implemented sequence uc 6 capacity and uc 7 release |
| project-documentation/final-report/figures/use-case-design-01-shared-analysis-class-model.png | 91232 | 2026-10-21T13:48:11+08:00 | use case design 01 shared analysis class model |
| project-documentation/final-report/figures/use-case-design-02-common-implemented-design-class-model.png | 181426 | 2026-10-21T13:48:11+08:00 | use case design 02 common implemented design class model |
| project-documentation/final-report/figures/use-case-design-03-analysis-sequence-uc-1-uc-3-core-workflow.png | 214139 | 2026-10-21T13:48:11+08:00 | use case design 03 analysis sequence uc 1 uc 3 core workflow |
| project-documentation/final-report/figures/use-case-design-04-analysis-sequence-uc-4-and-uc-5-retry-integration.png | 154265 | 2026-10-21T13:51:17+08:00 | use case design 04 analysis sequence uc 4 and uc 5 retry integration |
| project-documentation/final-report/figures/use-case-design-05-analysis-sequence-uc-6-and-uc-7-operations.png | 168078 | 2026-10-21T13:48:11+08:00 | use case design 05 analysis sequence uc 6 and uc 7 operations |
| project-documentation/final-report/figures/use-case-design-06-implemented-sequence-uc-1-uc-3-upload-process-and-play.png | 758263 | 2026-10-21T13:48:11+08:00 | use case design 06 implemented sequence uc 1 uc 3 upload process and play |
| project-documentation/final-report/figures/use-case-design-07-implemented-sequence-uc-4-and-uc-5-publisher-stored-source-retry.png | 420419 | 2026-10-21T13:48:11+08:00 | use case design 07 implemented sequence uc 4 and uc 5 publisher stored source retry |
| project-documentation/final-report/figures/use-case-design-08-implemented-sequence-uc-6-capacity-and-uc-7-release.png | 543038 | 2026-10-21T13:48:11+08:00 | use case design 08 implemented sequence uc 6 capacity and uc 7 release |
| project-documentation/final-report/figures/views-er-media.png | 98507 | 2026-10-21T13:48:11+08:00 | views er media |
| project-documentation/final-report/figures/views-er-processing.png | 82723 | 2026-10-21T13:48:11+08:00 | views er processing |
| project-documentation/final-report/figures/views-job-states.png | 81277 | 2026-10-21T13:48:11+08:00 | views job states |
| project-documentation/final-report/figures/views-logical.png | 276125 | 2026-10-21T13:48:11+08:00 | views logical |
| project-documentation/final-report/figures/views-physical.png | 474281 | 2026-10-21T13:48:11+08:00 | views physical |
| project-documentation/final-report/figures/views-sequence.png | 829982 | 2026-10-21T13:48:11+08:00 | views sequence |
| docs/architecture/img/ddd-context-map.svg | 220105 | 2026-10-18T01:58:58+08:00 | ddd context map |
| docs/architecture/img/views-er-media.svg | 193434 | 2026-10-18T01:58:58+08:00 | views er media |
| docs/architecture/img/views-er-processing.svg | 189111 | 2026-10-18T01:58:58+08:00 | views er processing |
| docs/architecture/img/views-job-states.svg | 194082 | 2026-10-18T01:58:58+08:00 | views job states |
| docs/architecture/img/views-logical.svg | 226794 | 2026-10-18T01:58:58+08:00 | views logical |
| docs/architecture/img/views-physical.svg | 255563 | 2026-10-22T13:13:28+08:00 | views physical |
| docs/architecture/img/views-sequence.svg | 235249 | 2026-10-18T01:58:58+08:00 | MediaResults; Processing repair or event Lambda; Output bucket; Fargate encoder; processing_db |
| project-documentation/presentation/site/assets/img/architecture-before-after.svg | 7513 | 2026-10-22T18:49:28+08:00 | Cert 1 baseline (inherited); FlickPond web app; One FlickPond API; identity · upload · jobs · playback; Redis / RQ queue |
| project-documentation/presentation/site/assets/img/ddd-context-map.svg | 220105 | 2026-10-22T18:49:28+08:00 | ddd context map |
| project-documentation/presentation/site/assets/img/deployment-pipeline.svg | 3990 | 2026-10-22T18:49:28+08:00 | Automated pipeline; Pull request; peer review; Build and test; unit · contract · integration |
| project-documentation/presentation/site/assets/img/domain-model.svg | 6283 | 2026-10-22T18:49:28+08:00 | Media Management; Owner; account · role; password hash; Asset |
| project-documentation/presentation/site/assets/img/platform-context.svg | 5126 | 2026-10-22T18:49:28+08:00 | PEOPLE; APPLICATIONS; PLATFORM; OPERATIONS; Content owners |
| project-documentation/presentation/site/assets/img/views-er-media.svg | 193434 | 2026-10-22T18:49:28+08:00 | views er media |
| project-documentation/presentation/site/assets/img/views-er-processing.svg | 189111 | 2026-10-22T18:49:28+08:00 | views er processing |
| project-documentation/presentation/site/assets/img/views-job-states.svg | 194082 | 2026-10-22T18:49:28+08:00 | views job states |
| project-documentation/presentation/site/assets/img/views-logical.svg | 226794 | 2026-10-22T18:49:28+08:00 | views logical |
| project-documentation/presentation/site/assets/img/views-physical.svg | 255563 | 2026-10-22T18:49:28+08:00 | views physical |
| project-documentation/presentation/site/assets/img/views-sequence.svg | 235249 | 2026-10-22T18:49:28+08:00 | MediaResults; Processing repair or event Lambda; Output bucket; Fargate encoder; processing_db |
| project-documentation/presentation/site/assets/uml/W1-artifacts.png | 228485 | 2026-11-10T22:36:59+08:00 | Deployment view · images and runtime configuration · 76282d3 |
| project-documentation/presentation/site/assets/uml/W1-artifacts.puml | 2463 | 2026-11-10T22:36:59+08:00 | Deployment view · images and runtime configuration · 76282d3 |
| project-documentation/presentation/site/assets/uml/W1-artifacts.svg | 18347 | 2026-11-10T22:36:59+08:00 | Deployment view · images and runtime configuration · 76282d3; MediaImageUri; MediaRepository · digest; ProcessingImageUri; ProcessingRepository · digest |
| project-documentation/presentation/site/assets/uml/W1-authorizer.png | 97455 | 2026-11-10T22:36:59+08:00 | Sequence view · protected request authorization · 76282d3 |
| project-documentation/presentation/site/assets/uml/W1-authorizer.puml | 1327 | 2026-11-10T22:36:59+08:00 | Sequence view · protected request authorization · 76282d3 |
| project-documentation/presentation/site/assets/uml/W1-authorizer.svg | 17425 | 2026-11-10T22:36:59+08:00 | HTTP API; MediaAuthorizer; Media DB; Selected API |
| project-documentation/presentation/site/assets/uml/W1-deployment-main.png | 187258 | 2026-11-10T22:36:59+08:00 | W1 deployment main |
| project-documentation/presentation/site/assets/uml/W1-deployment-main.puml | 2039 | 2026-11-10T22:36:59+08:00 | W1 deployment main |
| project-documentation/presentation/site/assets/uml/W1-deployment-main.svg | 18993 | 2026-11-10T22:36:59+08:00 | Deployment view · dc2-live · ap-southeast-1 · source configuration 76282d3; Vpc · 2 AZs · 10.62.0.0/16 + IPv6; Private A+B · compute / SQL choices; Public A+B · task deployment set; «executionEnvironment» |
| project-documentation/presentation/site/assets/uml/W1-dispatch.png | 133842 | 2026-11-10T22:36:59+08:00 | Activity view · queue selection for a queued Job / Attempt · 76282d3 |
| project-documentation/presentation/site/assets/uml/W1-dispatch.puml | 1432 | 2026-11-10T22:36:59+08:00 | Activity view · queue selection for a queued Job / Attempt · 76282d3 |
| project-documentation/presentation/site/assets/uml/W1-dispatch.svg | 12810 | 2026-11-10T22:36:59+08:00 | Activity view · queue selection for a queued Job / Attempt · 76282d3; messaging.emit_state; → short_lane.work_lane; enabled AND integer size; 0 &lt; bytes ≤64 MiB |
| project-documentation/presentation/site/assets/uml/W1-events.png | 141667 | 2026-11-10T22:36:59+08:00 | W1 events |
| project-documentation/presentation/site/assets/uml/W1-events.puml | 1773 | 2026-11-10T22:36:59+08:00 | W1 events |
| project-documentation/presentation/site/assets/uml/W1-events.svg | 14800 | 2026-11-10T22:36:59+08:00 | Deployment view · five EventBridge rules and standard-work wake · dc2-live at 76282d3; MediaRepairRule; rate(1 minute); ProcessingRepairRule; rate(1 minute) |
| project-documentation/presentation/site/assets/uml/W1-network.png | 145600 | 2026-11-10T22:36:59+08:00 | Deployment view · subnet placement and egress · dc2-live at 76282d3 |
| project-documentation/presentation/site/assets/uml/W1-network.puml | 1875 | 2026-11-10T22:36:59+08:00 | Deployment view · subnet placement and egress · dc2-live at 76282d3 |
| project-documentation/presentation/site/assets/uml/W1-network.svg | 19522 | 2026-11-10T22:36:59+08:00 | Deployment view · subnet placement and egress · dc2-live at 76282d3; ap-southeast-1; Vpc · 10.62.0.0/16 + IPv6; Private deployment set · all 11 Lambdas; Public task placement set · Fargate |
| project-documentation/presentation/site/assets/uml/W1-probe-redirect.png | 132595 | 2026-11-10T22:36:59+08:00 | Activity view · source admission and fenced redirect · 76282d3 |
| project-documentation/presentation/site/assets/uml/W1-probe-redirect.puml | 1496 | 2026-11-10T22:36:59+08:00 | Activity view · source admission and fenced redirect · 76282d3 |
| project-documentation/presentation/site/assets/uml/W1-probe-redirect.svg | 11590 | 2026-11-10T22:36:59+08:00 | Activity view · source admission and fenced redirect · 76282d3; claim + lambda-* binding + COMMIT; download → FFprobe → check_probe; finite 0 &lt; duration ≤60 s; AND source height ≤1080 px? |
| project-documentation/presentation/site/assets/uml/W1-stores.png | 156748 | 2026-11-10T22:36:59+08:00 | W1 stores |
| project-documentation/presentation/site/assets/uml/W1-stores.puml | 1762 | 2026-11-10T22:36:59+08:00 | W1 stores |
| project-documentation/presentation/site/assets/uml/W1-stores.svg | 15583 | 2026-11-10T22:36:59+08:00 | Deployment view · databases, S3 buckets and byte paths · dc2-live at 76282d3; ap-southeast-1 · managed storage; Vpc · subnet choices shown on each runtime set; FrontendBucket; static default origin |
| project-documentation/presentation/site/assets/uml/W1-triggers.png | 166837 | 2026-11-10T22:36:59+08:00 | W1 triggers |
| project-documentation/presentation/site/assets/uml/W1-triggers.puml | 1989 | 2026-11-10T22:36:59+08:00 | W1 triggers |
| project-documentation/presentation/site/assets/uml/W1-triggers.svg | 17547 | 2026-11-10T22:36:59+08:00 | Deployment view · four physical queue lanes and consumers · dc2-live at 76282d3; MediaRepair; Processing relay; ProcessingCommands; ProcessingRepair |
| project-documentation/presentation/site/assets/uml/W2-context-map.png | 72929 | 2026-11-10T22:36:59+08:00 | Strategic context map · as built at 76282d3 |
| project-documentation/presentation/site/assets/uml/W2-context-map.puml | 1538 | 2026-11-10T22:36:59+08:00 | Strategic context map · as built at 76282d3 |
| project-documentation/presentation/site/assets/uml/W2-context-map.svg | 9271 | 2026-11-10T22:36:59+08:00 | Strategic context map · as built at 76282d3; Media Management; Processing; Asset / ownership / public view; Command adapters: enqueue_submit(), command() |
| project-documentation/presentation/site/assets/uml/W2-delivery-ledgers.png | 56709 | 2026-11-10T22:36:59+08:00 | Technical consistency · owned delivery ledgers · 76282d3 |
| project-documentation/presentation/site/assets/uml/W2-delivery-ledgers.puml | 1654 | 2026-11-10T22:36:59+08:00 | Technical consistency · owned delivery ledgers · 76282d3 |
| project-documentation/presentation/site/assets/uml/W2-delivery-ledgers.svg | 10440 | 2026-11-10T22:36:59+08:00 | Technical consistency · owned delivery ledgers · 76282d3; Media (own database); Processing (own database); «delivery ledger»; MediaInbox |
| project-documentation/presentation/site/assets/uml/W2-launcher-control.png | 55853 | 2026-11-10T22:36:59+08:00 | Technical consistency · Processing launcher control · 76282d3 |
| project-documentation/presentation/site/assets/uml/W2-launcher-control.puml | 1412 | 2026-11-10T22:36:59+08:00 | Technical consistency · Processing launcher control · 76282d3 |
| project-documentation/presentation/site/assets/uml/W2-launcher-control.svg | 7287 | 2026-11-10T22:36:59+08:00 | Technical consistency · Processing launcher control · 76282d3; «technical singleton»; LauncherControl; id: int; enabled: bool |
| project-documentation/presentation/site/assets/uml/W2-media-asset.png | 99096 | 2026-11-10T22:36:59+08:00 | Tactical DDD · Media Asset / source identity · 76282d3 |
| project-documentation/presentation/site/assets/uml/W2-media-asset.puml | 2002 | 2026-11-10T22:36:59+08:00 | Tactical DDD · Media Asset / source identity · 76282d3 |
| project-documentation/presentation/site/assets/uml/W2-media-asset.svg | 12946 | 2026-11-10T22:36:59+08:00 | Tactical DDD · Media Asset / source identity · 76282d3; Asset consistency grouping (interpretation); «principal root»; Asset; id: UUID |
| project-documentation/presentation/site/assets/uml/W2-media-intake.png | 67048 | 2026-11-10T22:36:59+08:00 | Tactical DDD · Media identity / pre-adoption intake · 76282d3 |
| project-documentation/presentation/site/assets/uml/W2-media-intake.puml | 1624 | 2026-11-10T22:36:59+08:00 | Tactical DDD · Media identity / pre-adoption intake · 76282d3 |
| project-documentation/presentation/site/assets/uml/W2-media-intake.svg | 8586 | 2026-11-10T22:36:59+08:00 | Tactical DDD · Media identity / pre-adoption intake · 76282d3; «supporting root»; User; id: UUID; email: str |
| project-documentation/presentation/site/assets/uml/W2-media-support.png | 86012 | 2026-11-10T22:36:59+08:00 | Supporting records · Media projection and ledgers · 76282d3 |
| project-documentation/presentation/site/assets/uml/W2-media-support.puml | 1979 | 2026-11-10T22:36:59+08:00 | Supporting records · Media projection and ledgers · 76282d3 |
| project-documentation/presentation/site/assets/uml/W2-media-support.svg | 10185 | 2026-11-10T22:36:59+08:00 | Supporting records · Media projection and ledgers · 76282d3; «read model»; ProcessingProjection; asset_id: UUID; job_id: UUID |
| project-documentation/presentation/site/assets/uml/W2-processing-authority.png | 89098 | 2026-11-10T22:36:59+08:00 | Execution values / cleanup · Processing · 76282d3 |
| project-documentation/presentation/site/assets/uml/W2-processing-authority.puml | 1848 | 2026-11-10T22:36:59+08:00 | Execution values / cleanup · Processing · 76282d3 |
| project-documentation/presentation/site/assets/uml/W2-processing-authority.svg | 10193 | 2026-11-10T22:36:59+08:00 | Execution values / cleanup · Processing · 76282d3; «frozen execution value»; lifecycle.Claim; job_id: UUID; attempt_id: UUID |
| project-documentation/presentation/site/assets/uml/W2-processing-job.png | 106481 | 2026-11-10T22:36:59+08:00 | Tactical DDD · Processing Job / Attempt · 76282d3 |
| project-documentation/presentation/site/assets/uml/W2-processing-job.puml | 2052 | 2026-11-10T22:36:59+08:00 | Tactical DDD · Processing Job / Attempt · 76282d3 |
| project-documentation/presentation/site/assets/uml/W2-processing-job.svg | 12866 | 2026-11-10T22:36:59+08:00 | Tactical DDD · Processing Job / Attempt · 76282d3; Job business consistency grouping (interpretation); «principal root»; Job; id: UUID |
| project-documentation/presentation/site/assets/uml/W2-processing-support.png | 72842 | 2026-11-10T22:36:59+08:00 | Supporting boundaries · Processing control / idempotency · 76282d3 |
| project-documentation/presentation/site/assets/uml/W2-processing-support.puml | 1798 | 2026-11-10T22:36:59+08:00 | Supporting boundaries · Processing control / idempotency · 76282d3 |
| project-documentation/presentation/site/assets/uml/W2-processing-support.svg | 8920 | 2026-11-10T22:36:59+08:00 | Supporting boundaries · Processing control / idempotency · 76282d3; «independent cancellation gate»; SubmissionGuard; asset_id: UUID; owner_id: UUID |
| project-documentation/presentation/site/assets/uml/W3-01-media-components.puml | 2665 | 2026-11-10T22:36:59+08:00 | Component view · Media owns adoption and public projections\nAs built at 76282d3 |
| project-documentation/presentation/site/assets/uml/W3-01-media-components.svg | 17710 | 2026-11-10T22:36:59+08:00 | Component view · Media owns adoption and public projections; As built at 76282d3; lambda_handler / main; api.uploads / v1_jobs / v1_hls; authorizer / api.deps |
| project-documentation/presentation/site/assets/uml/W3-02-processing-components.puml | 2792 | 2026-11-10T22:36:59+08:00 | Component view · Processing separates control from execution\nAs built at 76282d3 |
| project-documentation/presentation/site/assets/uml/W3-02-processing-components.svg | 20816 | 2026-11-10T22:36:59+08:00 | Component view · Processing separates control from execution; As built at 76282d3; lambda_handler / v1_api / auth; processing.handlers; «Transactional Outbox» |
| project-documentation/presentation/site/assets/uml/W3-03-a-intake-classes.puml | 2468 | 2026-11-10T22:36:59+08:00 | Class view · UC-1 adopts one verified source and its command\nAs built at 76282d3 |
| project-documentation/presentation/site/assets/uml/W3-03-a-intake-classes.svg | 15064 | 2026-11-10T22:36:59+08:00 | Class view · UC-1 adopts one verified source and its command; As built at 76282d3; «module»; direct_intake (media.services); +reserve(session, storage, owner_id, request) |
| project-documentation/presentation/site/assets/uml/W3-04-a-execution-classes.puml | 2432 | 2026-11-10T22:36:59+08:00 | Class view · UC-2 executes under a frozen Claim\nAs built at 76282d3 |
| project-documentation/presentation/site/assets/uml/W3-04-a-execution-classes.svg | 14333 | 2026-11-10T22:36:59+08:00 | Class view · UC-2 executes under a frozen Claim; As built at 76282d3; «ORM»; Job (processing.models); +id: UUID |
| project-documentation/presentation/site/assets/uml/W3-05-a-projection-classes.puml | 1997 | 2026-11-10T22:36:59+08:00 | Class view · UC-3 reads the Media-owned result model\nAs built at 76282d3 |
| project-documentation/presentation/site/assets/uml/W3-05-a-projection-classes.svg | 9673 | 2026-11-10T22:36:59+08:00 | Class view · UC-3 reads the Media-owned result model; As built at 76282d3; «module»; projections (media); +apply_result(session, envelope) |
| project-documentation/presentation/site/assets/uml/W3-06-a1-upload.puml | 2109 | 2026-11-10T22:36:59+08:00 | Sequence view · UC-1 verifies bytes before adopting the source\nAs built at 76282d3 |
| project-documentation/presentation/site/assets/uml/W3-06-a1-upload.svg | 18221 | 2026-11-10T22:36:59+08:00 | direct_intake; ; storage. Storage; ; messaging; ; s. AsyncSession |
| project-documentation/presentation/site/assets/uml/W3-06a-reserve.puml | 1757 | 2026-11-10T22:36:59+08:00 | Sequence view · UC-1 reserves a key before direct upload\nAs built at 76282d3 |
| project-documentation/presentation/site/assets/uml/W3-06a-reserve.svg | 20064 | 2026-11-10T22:36:59+08:00 | owner; api.uploads; ; direct_intake; ; s. AsyncSession; storage. Storage; ; source. S3 |
| project-documentation/presentation/site/assets/uml/W3-07-a2-submit-execute.puml | 2508 | 2026-11-10T22:36:59+08:00 | Sequence view · Processing handler publishes after command acceptance · 76282d3 |
| project-documentation/presentation/site/assets/uml/W3-07-a2-submit-execute.svg | 15343 | 2026-11-10T22:36:59+08:00 | handlers; ; messaging; ; ; t. WakeOnWork . SQS |
| project-documentation/presentation/site/assets/uml/W3-07a-submit-transaction.puml | 2272 | 2026-11-10T22:36:59+08:00 | Sequence view · Submit commits inbox, Job, Attempt and outbox intents · 76282d3 |
| project-documentation/presentation/site/assets/uml/W3-07a-submit-transaction.svg | 14930 | 2026-11-10T22:36:59+08:00 | messaging; ; s. AsyncSession |
| project-documentation/presentation/site/assets/uml/W3-08-a3-result-play.puml | 2306 | 2026-11-10T22:36:59+08:00 | Sequence view · UC-3 commits a Media result projection · 76282d3 |
| project-documentation/presentation/site/assets/uml/W3-08-a3-result-play.svg | 21560 | 2026-11-10T22:36:59+08:00 | handlers; ; messaging; ; projections; ; s. AsyncSession |
| project-documentation/presentation/site/assets/uml/W3-08a-public-read.png | 65803 | 2026-11-10T22:36:59+08:00 | Sequence view · UC-3 reads the Media projection before signing output\nAs built at 76282d3 |
| project-documentation/presentation/site/assets/uml/W3-08a-public-read.puml | 2144 | 2026-11-10T22:36:59+08:00 | Sequence view · UC-3 reads the Media projection before signing output\nAs built at 76282d3 |
| project-documentation/presentation/site/assets/uml/W3-08a-public-read.svg | 16349 | 2026-11-10T22:36:59+08:00 | owner; api.v1_jobs; ; projections; ; s. AsyncSession; storage. Storage;  |
| project-documentation/presentation/site/assets/uml/W3-09a-probe.puml | 2441 | 2026-11-10T22:36:59+08:00 | Sequence view · UC-2 downloads and probes before source admission\nAs built at 76282d3 |
| project-documentation/presentation/site/assets/uml/W3-09a-probe.svg | 17613 | 2026-11-10T22:36:59+08:00 | tasks; ; source. SourceStore; ; sup. Supervisor; ; media_engine.probe; ; ; short_lane;  |
| project-documentation/presentation/site/assets/uml/W3-09b-encode.puml | 2411 | 2026-11-10T22:36:59+08:00 | Sequence view · UC-2 builds and uploads a verified primary\n76282d3 |
| project-documentation/presentation/site/assets/uml/W3-09b-encode.svg | 15712 | 2026-11-10T22:36:59+08:00 | worker.sqs; tasks; ; media_engine.operations; sup. Supervisor; ; store. OutputStore;  |
| project-documentation/presentation/site/assets/uml/W3-09c-hls.puml | 2316 | 2026-11-10T22:36:59+08:00 | Sequence view · UC-2 uploads optional HLS with the master last\n76282d3 |
| project-documentation/presentation/site/assets/uml/W3-09c-hls.svg | 14207 | 2026-11-10T22:36:59+08:00 | tasks; ; media_engine.hls; sup. Supervisor; ; store. OutputStore;  |
| project-documentation/presentation/site/assets/uml/W3-10-b-classes.puml | 1968 | 2026-11-10T22:36:59+08:00 | Class view · UC-4 replaces an Attempt and fences old authority\nAs built at 76282d3 |
| project-documentation/presentation/site/assets/uml/W3-10-b-classes.svg | 13462 | 2026-11-10T22:36:59+08:00 | Class view · UC-4 replaces an Attempt and fences old authority; As built at 76282d3; «ORM»; Job; +id: UUID |
| project-documentation/presentation/site/assets/uml/W3-11-b1-expiry.puml | 2250 | 2026-11-10T22:36:59+08:00 | Sequence view · UC-4 expires execution authority · 76282d3 |
| project-documentation/presentation/site/assets/uml/W3-11-b1-expiry.svg | 16541 | 2026-11-10T22:36:59+08:00 | recovery_v1; recovery; ; lifecycle; ; messaging; s. AsyncSession |
| project-documentation/presentation/site/assets/uml/W3-12-b2-retry.puml | 2025 | 2026-11-10T22:36:59+08:00 | Sequence view · UC-4 stages Media retry intent · 76282d3 |
| project-documentation/presentation/site/assets/uml/W3-12-b2-retry.svg | 15355 | 2026-11-10T22:36:59+08:00 | v1_lifecycle; ; projections; ; s. AsyncSession |
| project-documentation/presentation/site/assets/uml/W3-12a-processing-retry.puml | 1542 | 2026-11-10T22:36:59+08:00 | Sequence view · UC-4 commits one successor · 76282d3 |
| project-documentation/presentation/site/assets/uml/W3-12a-processing-retry.svg | 17602 | 2026-11-10T22:36:59+08:00 | messaging; ; lifecycle; s. AsyncSession |
| project-documentation/presentation/site/assets/uml/W3-13-b3-fence.puml | 2249 | 2026-11-10T22:36:59+08:00 | Sequence view · UC-4 fences a stale Claim before any mutation\nAs built at 76282d3 |
| project-documentation/presentation/site/assets/uml/W3-13-b3-fence.svg | 14256 | 2026-11-10T22:36:59+08:00 | worker.sqs; ; messaging; ; lifecycle; ; s. AsyncSession |
| project-documentation/presentation/site/assets/uml/W3-13a-projection-fence.puml | 1663 | 2026-11-10T22:36:59+08:00 | Sequence view · UC-4 independently fences delayed result snapshots\nAs built at 76282d3 |
| project-documentation/presentation/site/assets/uml/W3-13a-projection-fence.svg | 14008 | 2026-11-10T22:36:59+08:00 | projections; ; s. AsyncSession |
| project-documentation/presentation/site/assets/uml/W3-14-edit.puml | 2514 | 2026-11-10T22:36:59+08:00 | Sequence view · Edit adopts a derived Asset · 76282d3 |
| project-documentation/presentation/site/assets/uml/W3-14-edit.svg | 18640 | 2026-11-10T22:36:59+08:00 | v1_lifecycle; ; storage. Storage; ; s. AsyncSession |
| project-documentation/presentation/site/assets/uml/W3-14a-edit-relay.puml | 1791 | 2026-11-10T22:36:59+08:00 | Sequence view · A scheduled relay publishes committed edit intent\nAs built at 76282d3 |
| project-documentation/presentation/site/assets/uml/W3-14a-edit-relay.svg | 18526 | 2026-11-10T22:36:59+08:00 | handlers; ; messaging; ; delivery.sql; ; s. AsyncSession; t. SQS;  |
| project-documentation/presentation/site/assets/uml/W3-14b-edit-detail.puml | 2464 | 2026-11-10T22:36:59+08:00 | Sequence view · Edit durably stages and copies a derived source · 76282d3 |
| project-documentation/presentation/site/assets/uml/W3-14b-edit-detail.svg | 16387 | 2026-11-10T22:36:59+08:00 | v1_lifecycle; ; intake; ; storage. Storage; ; s. AsyncSession |
| project-documentation/presentation/site/assets/uml/W3-14c-edit-adoption.puml | 2566 | 2026-11-10T22:36:59+08:00 | Sequence view · Edit adopts the pin and submit intent atomically · 76282d3 |
| project-documentation/presentation/site/assets/uml/W3-14c-edit-adoption.svg | 19110 | 2026-11-10T22:36:59+08:00 | v1_lifecycle; ; direct_intake; ; storage. Storage; ; messaging; ; s. AsyncSession |
| project-documentation/presentation/site/assets/uml/W3-15-job-states.puml | 2625 | 2026-11-10T22:36:59+08:00 | Statechart · Job processing status and deletion are separate dimensions\nAs built at 76282d3 |
| project-documentation/presentation/site/assets/uml/W3-15-job-states.svg | 16505 | 2026-11-10T22:36:59+08:00 | Statechart · Job processing status and deletion are separate dimensions; As built at 76282d3; Job (persisted record; not a Python state-machine class); status; queued |
| project-documentation/presentation/site/assets/uml/W3-16-attempt-states.puml | 2351 | 2026-11-10T22:36:59+08:00 | Statechart · Each Attempt ends once; retry creates another identity\nAs built at 76282d3 |
| project-documentation/presentation/site/assets/uml/W3-16-attempt-states.svg | 13584 | 2026-11-10T22:36:59+08:00 | Statechart · Each Attempt ends once; retry creates another identity; As built at 76282d3; Terminal Attempt states (persisted rows); succeeded; failed |
| project-documentation/presentation/site/assets/uml/W3-17-recovery-branches.puml | 1839 | 2026-11-10T22:36:59+08:00 | Activity view · Queued delivery repair and interrupted execution · 76282d3 |
| project-documentation/presentation/site/assets/uml/W3-17-recovery-branches.svg | 10084 | 2026-11-10T22:36:59+08:00 | Activity view · Queued delivery repair and interrupted execution · 76282d3; Current nondeleted queued pair, dispatch due?; yes; no; repair_work: lock/recheck; |
| project-documentation/presentation/site/assets/uml/W3-18-lane-policy.puml | 2075 | 2026-11-10T22:36:59+08:00 | Class view · Dispatch policy and execution admission use different facts\nAs built at 76282d3 |
| project-documentation/presentation/site/assets/uml/W3-18-lane-policy.svg | 9611 | 2026-11-10T22:36:59+08:00 | Class view · Dispatch policy and execution admission use different facts; As built at 76282d3; «module, routing policy»; short_lane (processing); +MAX_SOURCE_BYTES = 64 * 1024 * 1024 |
| project-documentation/presentation/site/assets/uml/W3-19-execution-adapters.puml | 1692 | 2026-11-10T22:36:59+08:00 | Class view · UC-2 injects storage and supervises FFmpeg\nAs built at 76282d3 |
| project-documentation/presentation/site/assets/uml/W3-19-execution-adapters.svg | 10856 | 2026-11-10T22:36:59+08:00 | Class view · UC-2 injects storage and supervises FFmpeg; As built at 76282d3; «module»; tasks (processing.worker); +pipeline(work, settings, supervisor, client, store, directory, *, downloader, admit=None) |
| project-documentation/presentation/site/assets/uml/W3-20-contract-classes.puml | 1451 | 2026-11-10T22:36:59+08:00 | Class view · Source and Envelope carry versioned immutable identity\nAs built at 76282d3 |
| project-documentation/presentation/site/assets/uml/W3-20-contract-classes.svg | 8505 | 2026-11-10T22:36:59+08:00 | Class view · Source and Envelope carry versioned immutable identity; As built at 76282d3; «frozen dataclass»; Envelope (contracts.v1); +schema_version: int |
| project-documentation/presentation/site/assets/uml/W3-21-lease-functions.puml | 1747 | 2026-11-10T22:36:59+08:00 | Class view · UC-4 mutating operations live in modules\nAs built at 76282d3 |
| project-documentation/presentation/site/assets/uml/W3-21-lease-functions.svg | 10060 | 2026-11-10T22:36:59+08:00 | Class view · UC-4 mutating operations live in modules; As built at 76282d3; «module»; messaging (processing); -_retry_locked(session, job, request_id) |
| project-documentation/presentation/site/assets/uml/W3-22-hls-playback.puml | 1649 | 2026-11-10T22:36:59+08:00 | Sequence view · HLS segments redirect from Media to private S3\nAs built at 76282d3 |
| project-documentation/presentation/site/assets/uml/W3-22-hls-playback.svg | 21703 | 2026-11-10T22:36:59+08:00 | owner player; v1_hls; ; ; s. AsyncSession; storage. Storage; ; ; output. S3 |
| project-documentation/presentation/site/assets/uml/W3-23-claim-finish.puml | 1978 | 2026-11-10T22:36:59+08:00 | Sequence view · UC-2 successfully claims the current queued pair · 76282d3 |
| project-documentation/presentation/site/assets/uml/W3-23-claim-finish.svg | 19369 | 2026-11-10T22:36:59+08:00 | worker.sqs; messaging; ; ; ; lifecycle; ; s. AsyncSession |
| project-documentation/presentation/site/assets/uml/W3-23a-finish.puml | 1900 | 2026-11-10T22:36:59+08:00 | Sequence view · UC-2 commits a live finish and its result outbox\n76282d3 |
| project-documentation/presentation/site/assets/uml/W3-23a-finish.svg | 17936 | 2026-11-10T22:36:59+08:00 | worker.sqs; messaging; ; ; lifecycle; ; s. AsyncSession |
| project-documentation/presentation/site/assets/uml/W3-24-intake-types.puml | 1298 | 2026-11-10T22:36:59+08:00 | Class view · Intake DTOs and the edit-specific pin\nAs built at 76282d3 |
| project-documentation/presentation/site/assets/uml/W3-24-intake-types.svg | 7905 | 2026-11-10T22:36:59+08:00 | Class view · Intake DTOs and the edit-specific pin; As built at 76282d3; «Pydantic DTO»; ReserveRequest (direct_intake); +request_id: UUID |
| project-documentation/presentation/site/assets/uml/W4-media-assets.puml | 1738 | 2026-11-10T22:36:59+08:00 | Physical data view · Media identity and assets · 76282d3 |
| project-documentation/presentation/site/assets/uml/W4-media-assets.svg | 10868 | 2026-11-10T22:36:59+08:00 | Physical data view · Media identity and assets · 76282d3; users; id : uuid «PK»; email : varchar(320) «UK»; password_hash : text |
| project-documentation/presentation/site/assets/uml/W4-media-cleanup.puml | 1192 | 2026-11-10T22:36:59+08:00 | Physical data view · Media deletion progress · 76282d3 |
| project-documentation/presentation/site/assets/uml/W4-media-cleanup.svg | 6310 | 2026-11-10T22:36:59+08:00 | Physical data view · Media deletion progress · 76282d3; cleanup_intents; asset_id : uuid «PK,FK»; processing_deleted_at ? : timestamptz; source_deleted_at ? : timestamptz |
| project-documentation/presentation/site/assets/uml/W4-media-delivery.puml | 1554 | 2026-11-10T22:36:59+08:00 | Physical data view · Media durable delivery and orphan ledger · 76282d3 |
| project-documentation/presentation/site/assets/uml/W4-media-delivery.svg | 8178 | 2026-11-10T22:36:59+08:00 | Physical data view · Media durable delivery and orphan ledger · 76282d3; message_inbox; message_id : uuid «PK»; body_hash : varchar(64); received_at : timestamptz |
| project-documentation/presentation/site/assets/uml/W4-media-intents.puml | 1305 | 2026-11-10T22:36:59+08:00 | Physical data view · Media request identity · 76282d3 |
| project-documentation/presentation/site/assets/uml/W4-media-intents.svg | 8945 | 2026-11-10T22:36:59+08:00 | Physical data view · Media request identity · 76282d3; request_keys; owner_id : uuid «PK,FK»; operation : varchar(20) «PK»; request_key : uuid «PK» |
| project-documentation/presentation/site/assets/uml/W4-media-main.puml | 1941 | 2026-11-10T22:36:59+08:00 | Physical data view · media_db · media_0008 · 76282d3 |
| project-documentation/presentation/site/assets/uml/W4-media-main.svg | 15719 | 2026-11-10T22:36:59+08:00 | Physical data view · media_db · media_0008 · 76282d3; users; id : uuid «PK»; email : varchar(320) «UK»; assets |
| project-documentation/presentation/site/assets/uml/W4-media-pins.puml | 1200 | 2026-11-10T22:36:59+08:00 | Physical data view · Media derived source pins · 76282d3 |
| project-documentation/presentation/site/assets/uml/W4-media-pins.svg | 7081 | 2026-11-10T22:36:59+08:00 | Physical data view · Media derived source pins · 76282d3; asset_source_versions; asset_id : uuid «PK,FK»; bucket : text; key : text |
| project-documentation/presentation/site/assets/uml/W4-media-projection.puml | 1307 | 2026-11-10T22:36:59+08:00 | Physical data view · Media result projection · 76282d3 |
| project-documentation/presentation/site/assets/uml/W4-media-projection.svg | 7712 | 2026-11-10T22:36:59+08:00 | Physical data view · Media result projection · 76282d3; processing_projections; asset_id : uuid «PK,FK»; job_id : uuid «UK»; attempt_id ? : uuid |
| project-documentation/presentation/site/assets/uml/W4-media-retry.puml | 1327 | 2026-11-10T22:36:59+08:00 | Physical data view · Media retained legacy retry ledger · 76282d3 |
| project-documentation/presentation/site/assets/uml/W4-media-retry.svg | 8142 | 2026-11-10T22:36:59+08:00 | Physical data view · Media retained legacy retry ledger · 76282d3; retry_intents; id : uuid «PK»; asset_id : uuid «FK»; confirmed_at ? : timestamptz |
| project-documentation/presentation/site/assets/uml/W4-media-upload.puml | 1694 | 2026-11-10T22:36:59+08:00 | Physical data view · Media upload pins · 76282d3 |
| project-documentation/presentation/site/assets/uml/W4-media-upload.svg | 10712 | 2026-11-10T22:36:59+08:00 | Physical data view · Media upload pins · 76282d3; upload_reservations; id : uuid «PK»; owner_id : uuid «FK,UK3»; request_id : uuid «UK3» |
| project-documentation/presentation/site/assets/uml/W4-processing-attempts.puml | 2061 | 2026-11-10T22:36:59+08:00 | Physical data view · Processing jobs and fenced attempts · 76282d3 |
| project-documentation/presentation/site/assets/uml/W4-processing-attempts.svg | 13587 | 2026-11-10T22:36:59+08:00 | Physical data view · Processing jobs and fenced attempts · 76282d3; jobs; id : uuid «PK»; asset_id : uuid «UK»; owner_id : uuid |
| project-documentation/presentation/site/assets/uml/W4-processing-bindings.puml | 1301 | 2026-11-10T22:36:59+08:00 | Physical data view · Processing versions and task binding · 76282d3 |
| project-documentation/presentation/site/assets/uml/W4-processing-bindings.svg | 8652 | 2026-11-10T22:36:59+08:00 | Physical data view · Processing versions and task binding · 76282d3; job_messaging; job_id : uuid «PK,FK»; state_version : integer; attempt_tasks |
| project-documentation/presentation/site/assets/uml/W4-processing-cleanup.puml | 1351 | 2026-11-10T22:36:59+08:00 | Physical data view · Processing retained output cleanup · 76282d3 |
| project-documentation/presentation/site/assets/uml/W4-processing-cleanup.svg | 8872 | 2026-11-10T22:36:59+08:00 | Physical data view · Processing retained output cleanup · 76282d3; cleanup_intents; attempt_id : uuid «PK,FK»; job_id : uuid «FK»; next_try_at : timestamptz |
| project-documentation/presentation/site/assets/uml/W4-processing-delivery.puml | 1336 | 2026-11-10T22:36:59+08:00 | Physical data view · Processing durable delivery · 76282d3 |
| project-documentation/presentation/site/assets/uml/W4-processing-delivery.svg | 6639 | 2026-11-10T22:36:59+08:00 | Physical data view · Processing durable delivery · 76282d3; message_inbox; message_id : uuid «PK»; body_hash : varchar(64); received_at : timestamptz |
| project-documentation/presentation/site/assets/uml/W4-processing-intents.puml | 1625 | 2026-11-10T22:36:59+08:00 | Physical data view · Processing retry and cancellation · 76282d3 |
| project-documentation/presentation/site/assets/uml/W4-processing-intents.svg | 12551 | 2026-11-10T22:36:59+08:00 | Physical data view · Processing retry and cancellation · 76282d3; retry_requests; id : uuid «PK»; job_id : uuid «FK,UK1»; request_id : uuid «UK1» |
| project-documentation/presentation/site/assets/uml/W4-processing-launcher.puml | 1777 | 2026-11-10T22:36:59+08:00 | Physical data view · Optional unattended launcher · 76282d3 |
| project-documentation/presentation/site/assets/uml/W4-processing-launcher.svg | 9183 | 2026-11-10T22:36:59+08:00 | Physical data view · Optional unattended launcher · 76282d3; launcher_control; id : integer «PK»; enabled : boolean; enabled_at ? : timestamptz |
| project-documentation/presentation/site/assets/uml/W4-processing-main.puml | 1875 | 2026-11-10T22:36:59+08:00 | Physical data view · processing_db · processing_0007 · 76282d3 |
| project-documentation/presentation/site/assets/uml/W4-processing-main.svg | 16235 | 2026-11-10T22:36:59+08:00 | Physical data view · processing_db · processing_0007 · 76282d3; jobs; id : uuid «PK»; asset_id : uuid «UK»; status : varchar(16) |
| project-documentation/presentation/site/assets/uml/W5-pipeline-full.puml | 1213 | 2026-11-10T22:36:59+08:00 | Activity view · full CI dependencies · as built at 76282d3 |
| project-documentation/presentation/site/assets/uml/W5-pipeline-full.svg | 14899 | 2026-11-10T22:36:59+08:00 | Activity view · full CI dependencies · as built at 76282d3; CI event; GitHub Actions · full verification; Full CI event; PR / Main / dispatch / weekly |
| project-documentation/presentation/site/assets/uml/W5-pipeline-main.puml | 1118 | 2026-11-10T22:36:59+08:00 | Activity view · full CI security controls · as built at 76282d3 |
| project-documentation/presentation/site/assets/uml/W5-pipeline-main.svg | 14226 | 2026-11-10T22:36:59+08:00 | Activity view · full CI security controls · as built at 76282d3; CI event; GitHub Actions · full verification; Full CI event; PR / Main / dispatch / weekly |
| project-documentation/presentation/site/assets/uml/W5-pipeline-release.puml | 941 | 2026-11-10T22:36:59+08:00 | Activity view · executed CD owner release · as built at 76282d3 |
| project-documentation/presentation/site/assets/uml/W5-pipeline-release.svg | 10444 | 2026-11-10T22:36:59+08:00 | Activity view · executed CD owner release · as built at 76282d3; CD workflow; AWS operations via CD; Exact-source full CI admission; Main push or manual full dispatch |
| project-documentation/presentation/site/assets/uml/W6-command-handoff.png | 102596 | 2026-11-10T22:36:59+08:00 | Process view · Media acceptance and command handoff · 76282d3 |
| project-documentation/presentation/site/assets/uml/W6-command-handoff.puml | 1200 | 2026-11-10T22:36:59+08:00 | Process view · Media acceptance and command handoff · 76282d3 |
| project-documentation/presentation/site/assets/uml/W6-command-handoff.svg | 13237 | 2026-11-10T22:36:59+08:00 | MediaApi; media_db; MediaRepair; Processing; Processing; processing_db |
| project-documentation/presentation/site/assets/uml/W6-logical.png | 171742 | 2026-11-10T22:36:59+08:00 | Logical view · service interfaces and owned data · 76282d3 |
| project-documentation/presentation/site/assets/uml/W6-logical.puml | 2252 | 2026-11-10T22:36:59+08:00 | Logical view · service interfaces and owned data · 76282d3 |
| project-documentation/presentation/site/assets/uml/W6-logical.svg | 18340 | 2026-11-10T22:36:59+08:00 | Logical view · service interfaces and owned data · 76282d3; «clients»; frontend/ + publisher/; «HTTP API»; HttpApi / GatewayAuthorizer |
| project-documentation/presentation/site/assets/uml/W6-processing-components.png | 148696 | 2026-11-10T22:36:59+08:00 | Logical view · Processing component expansion · 76282d3 |
| project-documentation/presentation/site/assets/uml/W6-processing-components.puml | 1614 | 2026-11-10T22:36:59+08:00 | Logical view · Processing component expansion · 76282d3 |
| project-documentation/presentation/site/assets/uml/W6-processing-components.svg | 15008 | 2026-11-10T22:36:59+08:00 | Logical view · Processing component expansion · 76282d3; Processing · processing/; ProcessingApi; ProcessingCommands; ProcessingRepair |
| project-documentation/presentation/site/assets/uml/W6-result-replay.png | 131126 | 2026-11-10T22:36:59+08:00 | Information flow · result replay and version fencing · 76282d3 |
| project-documentation/presentation/site/assets/uml/W6-result-replay.puml | 1430 | 2026-11-10T22:36:59+08:00 | Information flow · result replay and version fencing · 76282d3 |
| project-documentation/presentation/site/assets/uml/W6-result-replay.svg | 11048 | 2026-11-10T22:36:59+08:00 | MediaResults; MediaInbox; media.projections |
| project-documentation/presentation/site/assets/uml/W6-trust-boundary.png | 167757 | 2026-11-10T22:36:59+08:00 | Trust view · protected routes · 76282d3 |
| project-documentation/presentation/site/assets/uml/W6-trust-boundary.puml | 1930 | 2026-11-10T22:36:59+08:00 | Trust view · protected routes · 76282d3 |
| project-documentation/presentation/site/assets/uml/W6-trust-boundary.svg | 16191 | 2026-11-10T22:36:59+08:00 | Trust view · protected routes · 76282d3; «trust boundary»; Backend invocation boundary; Media identity authority; MediaApi |
| project-documentation/presentation/site/assets/uml/W6-work-results.png | 176244 | 2026-11-10T22:36:59+08:00 | Process view · Processing work and return projection · 76282d3 |
| project-documentation/presentation/site/assets/uml/W6-work-results.puml | 1637 | 2026-11-10T22:36:59+08:00 | Process view · Processing work and return projection · 76282d3 |
| project-documentation/presentation/site/assets/uml/W6-work-results.svg | 17558 | 2026-11-10T22:36:59+08:00 | processing_db; Processing; ProcessingWorkQueue; Encoder; MediaResults; MediaResults; media_db |
| project-documentation/images/architecture-before-after.png | 216912 | 2026-10-09T04:07:29+08:00 | Cert 1 baseline (inherited); FlickPond web app; One FlickPond API; identity · upload · jobs · playback; Redis / RQ queue |
| project-documentation/images/architecture-before-after.svg | 7513 | 2026-10-09T04:07:29+08:00 | Cert 1 baseline (inherited); FlickPond web app; One FlickPond API; identity · upload · jobs · playback; Redis / RQ queue |
| project-documentation/images/deployment-pipeline.png | 104122 | 2026-10-09T04:07:29+08:00 | Automated pipeline; Pull request; peer review; Build and test; unit · contract · integration |
| project-documentation/images/deployment-pipeline.svg | 3990 | 2026-10-09T04:07:29+08:00 | Automated pipeline; Pull request; peer review; Build and test; unit · contract · integration |
| project-documentation/images/domain-model.png | 214468 | 2026-10-09T04:07:29+08:00 | Media Management; Owner; account · role; password hash; Asset |
| project-documentation/images/domain-model.svg | 6283 | 2026-10-09T04:07:29+08:00 | Media Management; Owner; account · role; password hash; Asset |
| project-documentation/images/platform-context.png | 167840 | 2026-10-09T04:07:29+08:00 | PEOPLE; APPLICATIONS; PLATFORM; OPERATIONS; Content owners |
| project-documentation/images/platform-context.svg | 5126 | 2026-10-09T04:07:29+08:00 | PEOPLE; APPLICATIONS; PLATFORM; OPERATIONS; Content owners |
| showcase-prep/assets/aws-topology.svg | 116726 | 2026-10-22T13:38:08+08:00 | Persistent V2-live: requests, state and video bytes |
| showcase-prep/assets/favicon.svg | 273 | 2026-10-21T09:52:26+08:00 | fp. |
| showcase-prep/assets/icons/docker.svg | 1780 | 2026-10-21T09:52:26+08:00 | Docker |
| showcase-prep/assets/icons/github.svg | 837 | 2026-10-21T09:52:26+08:00 | GitHub |
| showcase-prep/assets/icons/postgresql.svg | 5220 | 2026-10-21T09:52:26+08:00 | PostgreSQL |
| showcase-prep/assets/icons/python.svg | 1533 | 2026-10-21T09:52:26+08:00 | Python |
| project-roadmap/assets/business-context.svg | 3063 | 2026-10-09T04:07:29+08:00 | FlickPond business context |
| project-roadmap/assets/persona-cast.png | 1348220 | 2026-10-09T04:07:29+08:00 | Fictional planning persona doodle cast (Maya, Arun, Jules, Sam); generated illustration, not user research |
| project-roadmap/assets/persona-poses.png | 808436 | 2026-10-09T04:07:29+08:00 | Transparent pose variants of fictional persona illustrations |
| project-roadmap/design/03-ddd/aggregates.mmd | 922 | 2026-10-09T04:07:29+08:00 | aggregates |
| project-roadmap/design/03-ddd/aggregates.svg | 119539 | 2026-10-09T04:07:29+08:00 | aggregates |
| project-roadmap/design/03-ddd/context.mmd | 778 | 2026-10-09T04:07:29+08:00 | context |
| project-roadmap/design/03-ddd/context.svg | 111821 | 2026-10-09T04:07:29+08:00 | context |
| project-roadmap/design/03-ddd/lifecycle.mmd | 1114 | 2026-10-09T04:07:29+08:00 | lifecycle |
| project-roadmap/design/03-ddd/lifecycle.svg | 135064 | 2026-10-09T04:07:29+08:00 | lifecycle |
| project-roadmap/design/04-architecture/inherited-vs-proposed.mmd | 4108 | 2026-10-09T04:07:29+08:00 | inherited vs proposed |
| project-roadmap/design/04-architecture/inherited-vs-proposed.svg | 227802 | 2026-10-09T04:07:29+08:00 | inherited vs proposed |
| project-roadmap/design/04-architecture/success-sequence.mmd | 4664 | 2026-10-09T04:07:29+08:00 | success sequence |
| project-roadmap/design/04-architecture/success-sequence.svg | 299256 | 2026-10-09T04:07:29+08:00 | success sequence |
| project-roadmap/design/05-contracts/contract-map.mmd | 742 | 2026-10-09T04:07:29+08:00 | contract map |
| project-roadmap/design/05-contracts/contract-map.svg | 112755 | 2026-10-09T04:07:29+08:00 | contract map |
| project-roadmap/design/05-contracts/persistence.mmd | 918 | 2026-10-09T04:07:29+08:00 | persistence |
| project-roadmap/design/05-contracts/persistence.svg | 105977 | 2026-10-09T04:07:29+08:00 | persistence |
| project-roadmap/design/06-security-recovery/recovery-board.svg | 223559 | 2026-10-09T04:07:29+08:00 | recovery board |
| project-roadmap/design/06-security-recovery/recovery.mmd | 1277 | 2026-10-09T04:07:29+08:00 | recovery |
| project-roadmap/design/06-security-recovery/recovery.svg | 3412 | 2026-10-09T04:07:29+08:00 | Recovery and irreversible lease fencing |
| project-roadmap/design/07-deployment/physical-architecture.mmd | 1295 | 2026-10-09T04:07:29+08:00 | physical architecture |
| project-roadmap/design/07-deployment/physical-architecture.svg | 119748 | 2026-10-09T04:07:29+08:00 | physical architecture |
| project-roadmap/design/07-deployment/release-pipeline.mmd | 734 | 2026-10-09T04:07:29+08:00 | release pipeline |
| project-roadmap/design/07-deployment/release-pipeline.svg | 109269 | 2026-10-09T04:07:29+08:00 | release pipeline |


## GitHub cross-checks

Default branch `Main` live head: `76282d3b5a141f6548056f2506f9d5aff0742692` (GET branch on 10 November); local remote-tracking head: `76282d3b5a141f6548056f2506f9d5aff0742692`. No fetch was performed. Project current Status counts: {'Done': 111, 'Todo': 6, 'In Progress': 1}; Wave counts: {'Wave 0': 8, 'Wave 1': 3, 'Wave 2': 8, 'Wave 3': 2, 'Wave 4': 3, None: 94}. No milestones (open or closed), no issue assignees, no Iteration/date/story-point field in the inspected Project schema. Wave is a single-select ordering field, not a dated sprint.

A broad case-insensitive lexical issue-body search for `As a` / `user story` found 13 matching issues; these include incidental prose such as “as a registry digest”, not necessarily role–goal–benefit user stories. Treat the following as lexical hits only, not 13 verified user stories. Issue acceptance/outcome contracts remain useful backlog evidence even when not in story syntax.

- #256 https://github.com/Collaboration95/dc2/issues/256: 1. Domain is idle and has a recent valid quiet snapshot.
- #254 https://github.com/Collaboration95/dc2/issues/254: - [ ] The package has a durable team/reviewer access path and a documented local presentation backup; developer-home paths alone are insufficient.
- #251 https://github.com/Collaboration95/dc2/issues/251: For each image record candidate source SHA, owning domain/role, Dockerfile/build receipt, exact local image config ID and scanner report. If a registry digest is available, record it separately; do not rename a config ID as a registry digest. Preserve full findings plus the gate's fixability/severity verdict, including on failure.
- #248 https://github.com/Collaboration95/dc2/issues/248: The API bridge itself is behaving according to its API-only design. The defect is presenting the documented local stack as a usable interactive demo/fallback without a command that exposes the frontend and completes background processing. A passing headless browser test is useful evidence, but its temporary test harness is not a persistent interactive demo entry point.; If the team explicitly chooses recording-only fallback instead, narrow the technical handoff and #192's claim to that verified fallback and provide the actual accessible recording path/link. Merely renaming the API server as a web demo does not close this ticket. Editing the assessed deck/report is outside this local tooling ticket and still follows #181's existing hold.
- #246 https://github.com/Collaboration95/dc2/issues/246: - Either keep clearly marked last-known data for the **same owner/session**, or replace it with an explicit error state. Do not silently present stale data as a successful current response.
- #244 https://github.com/Collaboration95/dc2/issues/244: 4. The API has neither touched the marker nor been configured as a marker writer.
- #243 https://github.com/Collaboration95/dc2/issues/243: 3. Sign in as a different owner B.
- #196 https://github.com/Collaboration95/dc2/issues/196: Real microservices need failure isolation as well as a code split. The design says this already holds: Media finalize writes its outbox and never calls Processing. There is no V1 test or receipt for it, though. The only outage scenario, `scripts/evidence/recovery.py:processing_outage`, exercises the legacy peer stack.
- #195 https://github.com/Collaboration95/dc2/issues/195: Out of scope, explained as a trade-off in #188: one CloudFormation stack, the shared Aurora cluster (cost; #94 closed), and the monorepo with a single lockfile.
- #182 https://github.com/Collaboration95/dc2/issues/182: - [ ] The smoke step covers an upload through to playback, preferably using the Publisher CLI as the proposal states, and its result is uploaded as a run artifact.
- #163 https://github.com/Collaboration95/dc2/issues/163: - Keep a minimal dev smoke only if it covers a useful gap and is genuinely cheaper; do not relabel the full e2e suite as a smoke.
- #137 https://github.com/Collaboration95/dc2/issues/137: 1. **Flakiness.** The browser test has a timing dependency, most likely a fixed wait on job completion or HLS playback readiness under CI load.
- #8 https://github.com/Collaboration95/dc2/issues/8: - [x] Every substantive finding has a disposition and fix or explicit evidence-backed limitation.

## UI/UX pages and persona website

Primary persona page: `project-roadmap/business-scope.html`; structured source `project-roadmap/business-scope.json`, content date **9 October 2026**. Fictional Maya (course coordinator), Arun (trainer), Jules (integrator), Sam (operator) are planning assumptions, not interview participants. The site maps UC-1–UC-7 and scope decisions. Illustrations are not UI screenshots. The original Project 1 plan used Maya/Daniel/Priya; preserve separate provenance.

| Path | Bytes | Last committed change | Page content / title |
|---|---|---|---|
| project-roadmap/build-preparation.html | 164405 | 2026-10-12T21:11:58+08:00 | Team 17 · Build preparation |
| project-roadmap/business-scope.html | 33055 | 2026-10-12T21:11:58+08:00 | Team 17 · Business and scope |
| project-roadmap/design-studio.html | 235964 | 2026-10-12T21:11:58+08:00 | Team 17 · Design studio |
| project-roadmap/explanation.html | 24915 | 2026-10-12T21:11:58+08:00 | Team 17 · Project explained |
| project-roadmap/index.html | 87063 | 2026-10-12T21:11:58+08:00 | Team 17 · Project roadmap |
| showcase-prep/all-in-one.html | 166212 | 2026-10-22T13:38:08+08:00 | Complete study edition · FlickPond study guide |
| showcase-prep/architecture.html | 24946 | 2026-10-22T13:38:08+08:00 | How the platform fits together · FlickPond study guide |
| showcase-prep/aws.html | 28040 | 2026-10-22T13:38:08+08:00 | AWS: a small cloud, with clear boundaries · FlickPond study guide |
| showcase-prep/basics.html | 20428 | 2026-10-22T13:38:08+08:00 | What did we actually build? · FlickPond study guide |
| showcase-prep/code.html | 27591 | 2026-10-22T13:38:08+08:00 | How the code turns design into behavior · FlickPond study guide |
| showcase-prep/data.html | 17994 | 2026-10-22T13:38:08+08:00 | How does work survive failures? · FlickPond study guide |
| showcase-prep/delivery.html | 18251 | 2026-10-22T13:38:08+08:00 | From commit to running release · FlickPond study guide |
| showcase-prep/glossary.html | 22562 | 2026-10-22T13:38:08+08:00 | Glossary · FlickPond study guide |
| showcase-prep/index.html | 9887 | 2026-10-22T13:38:08+08:00 | Start here · FlickPond study guide |
| showcase-prep/meeting.html | 25282 | 2026-10-22T13:38:08+08:00 | Prepare the GC2 project presentation · FlickPond study guide |
| showcase-prep/quality.html | 21107 | 2026-10-22T13:38:08+08:00 | What the checks really tell you · FlickPond study guide |
| showcase-prep/questions.html | 28531 | 2026-10-22T13:38:08+08:00 | Practise Q&amp;A · FlickPond study guide |
| showcase-prep/security.html | 17132 | 2026-10-22T13:38:08+08:00 | Who can do what, and why? · FlickPond study guide |
| showcase-prep/sources.html | 22463 | 2026-10-22T13:38:08+08:00 | Sources and evidence · FlickPond study guide |
| project-documentation/presentation/site/1-overview.html | 20971 | 2026-10-23T13:56:12+08:00 | 1 · Context and problem — FlickPond |
| project-documentation/presentation/site/2-conduct.html | 16531 | 2026-10-23T13:56:12+08:00 | 2 · Project conduct — FlickPond |
| project-documentation/presentation/site/3-logical.html | 75026 | 2026-10-23T13:56:12+08:00 | 3 · Logical architecture — FlickPond |
| project-documentation/presentation/site/4-physical.html | 76380 | 2026-10-23T13:56:12+08:00 | 4 · Physical architecture — FlickPond |
| project-documentation/presentation/site/5-devops.html | 55847 | 2026-10-23T13:56:12+08:00 | 5 · DevOps and lifecycle — FlickPond |
| project-documentation/presentation/site/6-demo.html | 43868 | 2026-10-23T14:10:29+08:00 | 6 · Demo plan — FlickPond |
| project-documentation/presentation/site/_template.html | 4151 | 2026-10-23T13:56:12+08:00 | 3 · Logical architecture — FlickPond |
| project-documentation/presentation/site/deck-before.html | 127341 | 2026-11-10T22:37:12+08:00 | FlickPond · Team 17 · 26 Oct 2026 |
| project-documentation/presentation/site/deck-presented-20261026.html | 127341 | 2026-11-10T22:36:59+08:00 | FlickPond · Team 17 · 26 Oct 2026 |
| project-documentation/presentation/site/deck.html | 424902 | 2026-11-10T22:36:59+08:00 | FlickPond · Team 17 · 26 Oct 2026 |
| project-documentation/presentation/site/index.html | 8625 | 2026-10-23T13:56:12+08:00 | FlickPond — how the system works |
| project-documentation/presentation/site/references.html | 27847 | 2026-10-23T14:05:02+08:00 | References — FlickPond |
| project-documentation/presentation/site/script-1-2.html | 8741 | 2026-10-26T14:05:42+08:00 | Script · sections 1 &amp; 2 |
| project-documentation/presentation/site/script-3-4.html | 21783 | 2026-10-26T14:05:42+08:00 | Script · sections 3 &amp; 4 |
| project-documentation/presentation/site/script-5-6.html | 22509 | 2026-10-26T14:05:42+08:00 | Script · sections 5 &amp; 6 |
| project-documentation/presentation/site/storyboard.html | 32704 | 2026-10-23T14:05:02+08:00 | Video storyboard — FlickPond |

`showcase-prep/` is an explanatory website (architecture, code, data, quality, security, delivery, AWS, meeting prep), not captured product UI. It has SVG technical illustrations and no PNG/JPG/GIF/MP4 files. `project-documentation/images/` holds technical diagrams rather than UI screens. `frontend/index.html`, `frontend/app.js` and `frontend/style.css` are product UI source; recover UI visual evidence from D1/D3 and label it as frames from the dated recording.

Sibling HTML search covered `/Users/speedpowermac/Documents/projects/CODE_MAIN/NUS/`, excluding `.git`, dependencies and build/dist caches. Found the persona page in seven checkouts (no independent persona website found by searched title/section/text patterns):

| Absolute path | Bytes | Filesystem mtime UTC (not content date) | What it shows |
|---|---|---|---|
| /Users/speedpowermac/Documents/projects/CODE_MAIN/NUS/dc2-report/project-roadmap/business-scope.html | 33055 | 2026-11-10T14:37:21+00:00 | Fictional persona cards, goals, pains, channels, use cases |
| /Users/speedpowermac/Documents/projects/CODE_MAIN/NUS/dc2/project-roadmap/business-scope.html | 33055 | 2026-10-12T13:11:34+00:00 | Fictional persona cards, goals, pains, channels, use cases |
| /Users/speedpowermac/Documents/projects/CODE_MAIN/NUS/dc2-wt-v2-live/project-roadmap/business-scope.html | 33055 | 2026-10-18T02:26:27+00:00 | Fictional persona cards, goals, pains, channels, use cases |
| /Users/speedpowermac/Documents/projects/CODE_MAIN/NUS/dc2-before-flatten-20261012-211019/project-roadmap/business-scope.html | 33120 | 2026-10-08T20:00:19+00:00 | Fictional persona cards, goals, pains, channels, use cases |
| /Users/speedpowermac/Documents/projects/CODE_MAIN/NUS/dc2-presentation/project-roadmap/business-scope.html | 33055 | 2026-10-22T09:11:18+00:00 | Fictional persona cards, goals, pains, channels, use cases |
| /Users/speedpowermac/Documents/projects/CODE_MAIN/NUS/dc2-quality-20261020/project-roadmap/business-scope.html | 33055 | 2026-10-20T07:54:26+00:00 | Fictional persona cards, goals, pains, channels, use cases |
| /Users/speedpowermac/Documents/projects/CODE_MAIN/NUS/dc2-rescue/project-roadmap/business-scope.html | 33055 | 2026-10-26T07:50:25+00:00 | Fictional persona cards, goals, pains, channels, use cases |

### D1–D5 local recordings

All are physically present in `dc2-rescue/project-documentation/presentation/site/clips/`, 1920×1080 MP4. `ffprobe` confirmed durations below. The report checkout only has `clips/.gitignore`. `deck.html` notes **recorded on dc2-live on 23 October 2026**; filesystem dates are later and do not independently verify capture date. Content descriptions are from the retained deck/storyboard, not a frame-by-frame audit. D6 push-to-production is marked planned/not recorded. Some deck placeholders still say “recording pending”; those labels are stale relative to these local files. Storyboard planned timings differ from actual clip durations.

| Absolute path | Bytes | Filesystem mtime UTC | Actual duration | Documented content |
|---|---|---|---|---|
| /Users/speedpowermac/Documents/projects/CODE_MAIN/NUS/dc2-rescue/project-documentation/presentation/site/clips/D1.mp4 | 800211 | 2026-10-26T10:44:17+00:00 | 24.333333 s | Owner browser sign-in/upload, processing/status and playback (UC-1/2/3); product UI frame source |
| /Users/speedpowermac/Documents/projects/CODE_MAIN/NUS/dc2-rescue/project-documentation/presentation/site/clips/D2.mp4 | 465134 | 2026-10-26T10:44:17+00:00 | 30.833333 s | Independent Publisher CLI batch submission through public API (UC-5), browser library |
| /Users/speedpowermac/Documents/projects/CODE_MAIN/NUS/dc2-rescue/project-documentation/presentation/site/clips/D3.mp4 | 436955 | 2026-10-26T10:44:17+00:00 | 26.700000 s | Owner succeeds; second owner and anonymous denied (UC-3 exception) |
| /Users/speedpowermac/Documents/projects/CODE_MAIN/NUS/dc2-rescue/project-documentation/presentation/site/clips/D4.mp4 | 3247288 | 2026-10-26T10:44:17+00:00 | 60.100000 s | Fargate and Lambda short-encode capacity/scalability demonstration |
| /Users/speedpowermac/Documents/projects/CODE_MAIN/NUS/dc2-rescue/project-documentation/presentation/site/clips/D5.mp4 | 4886795 | 2026-10-26T10:44:17+00:00 | 77.666667 s | Scripted live API performance/load test and measured results |

### Additional raster/video assets outside the main manifest

Presentation feedback preview PNGs are rendered design/slides, not product-interaction screenshots. Names identify their depicted design/slide. No GIF was found in inspected documentation/site/showcase asset trees.

| Path | Bytes | Last committed change | What it depicts (filename-derived) |
|---|---|---|---|
| project-documentation/presentation/feedback-20261026/report-notes/W3-qa/W3-01-media-components-fit.png | 99453 | 2026-11-10T22:36:59+08:00 | Filename-derived subject: W3 01 media components fit |
| project-documentation/presentation/feedback-20261026/report-notes/W3-qa/W3-01-media-components.png | 114064 | 2026-11-10T22:36:59+08:00 | Filename-derived subject: W3 01 media components |
| project-documentation/presentation/feedback-20261026/report-notes/W3-qa/W3-02-processing-components-fit.png | 102358 | 2026-11-10T22:36:59+08:00 | Filename-derived subject: W3 02 processing components fit |
| project-documentation/presentation/feedback-20261026/report-notes/W3-qa/W3-02-processing-components.png | 124277 | 2026-11-10T22:36:59+08:00 | Filename-derived subject: W3 02 processing components |
| project-documentation/presentation/feedback-20261026/report-notes/W3-qa/W3-03-a-intake-classes-fit.png | 99547 | 2026-11-10T22:36:59+08:00 | Filename-derived subject: W3 03 a intake classes fit |
| project-documentation/presentation/feedback-20261026/report-notes/W3-qa/W3-03-a-intake-classes.png | 104287 | 2026-11-10T22:36:59+08:00 | Filename-derived subject: W3 03 a intake classes |
| project-documentation/presentation/feedback-20261026/report-notes/W3-qa/W3-04-a-execution-classes-fit.png | 95680 | 2026-11-10T22:36:59+08:00 | Filename-derived subject: W3 04 a execution classes fit |
| project-documentation/presentation/feedback-20261026/report-notes/W3-qa/W3-04-a-execution-classes.png | 95680 | 2026-11-10T22:36:59+08:00 | Filename-derived subject: W3 04 a execution classes |
| project-documentation/presentation/feedback-20261026/report-notes/W3-qa/W3-05-a-projection-classes-fit.png | 74489 | 2026-11-10T22:36:59+08:00 | Filename-derived subject: W3 05 a projection classes fit |
| project-documentation/presentation/feedback-20261026/report-notes/W3-qa/W3-05-a-projection-classes.png | 74489 | 2026-11-10T22:36:59+08:00 | Filename-derived subject: W3 05 a projection classes |
| project-documentation/presentation/feedback-20261026/report-notes/W3-qa/W3-06-a1-upload-fit.png | 78091 | 2026-11-10T22:36:59+08:00 | Filename-derived subject: W3 06 a1 upload fit |
| project-documentation/presentation/feedback-20261026/report-notes/W3-qa/W3-06-a1-upload.png | 87798 | 2026-11-10T22:36:59+08:00 | Filename-derived subject: W3 06 a1 upload |
| project-documentation/presentation/feedback-20261026/report-notes/W3-qa/W3-06a-reserve-fit.png | 80379 | 2026-11-10T22:36:59+08:00 | Filename-derived subject: W3 06a reserve fit |
| project-documentation/presentation/feedback-20261026/report-notes/W3-qa/W3-06a-reserve.png | 99508 | 2026-11-10T22:36:59+08:00 | Filename-derived subject: W3 06a reserve |
| project-documentation/presentation/feedback-20261026/report-notes/W3-qa/W3-07-a2-submit-execute-fit.png | 84588 | 2026-11-10T22:36:59+08:00 | Filename-derived subject: W3 07 a2 submit execute fit |
| project-documentation/presentation/feedback-20261026/report-notes/W3-qa/W3-07-a2-submit-execute.png | 100420 | 2026-11-10T22:36:59+08:00 | Filename-derived subject: W3 07 a2 submit execute |
| project-documentation/presentation/feedback-20261026/report-notes/W3-qa/W3-07a-submit-transaction-fit.png | 65283 | 2026-11-10T22:36:59+08:00 | Filename-derived subject: W3 07a submit transaction fit |
| project-documentation/presentation/feedback-20261026/report-notes/W3-qa/W3-07a-submit-transaction.png | 77440 | 2026-11-10T22:36:59+08:00 | Filename-derived subject: W3 07a submit transaction |
| project-documentation/presentation/feedback-20261026/report-notes/W3-qa/W3-08-a3-result-play-fit.png | 77174 | 2026-11-10T22:36:59+08:00 | Filename-derived subject: W3 08 a3 result play fit |
| project-documentation/presentation/feedback-20261026/report-notes/W3-qa/W3-08-a3-result-play.png | 98586 | 2026-11-10T22:36:59+08:00 | Filename-derived subject: W3 08 a3 result play |
| project-documentation/presentation/feedback-20261026/report-notes/W3-qa/W3-08a-public-read-fit.png | 80507 | 2026-11-10T22:36:59+08:00 | Filename-derived subject: W3 08a public read fit |
| project-documentation/presentation/feedback-20261026/report-notes/W3-qa/W3-08a-public-read.png | 81108 | 2026-11-10T22:36:59+08:00 | Filename-derived subject: W3 08a public read |
| project-documentation/presentation/feedback-20261026/report-notes/W3-qa/W3-09a-probe-fit.png | 77890 | 2026-11-10T22:36:59+08:00 | Filename-derived subject: W3 09a probe fit |
| project-documentation/presentation/feedback-20261026/report-notes/W3-qa/W3-09a-probe.png | 91933 | 2026-11-10T22:36:59+08:00 | Filename-derived subject: W3 09a probe |
| project-documentation/presentation/feedback-20261026/report-notes/W3-qa/W3-09b-encode-fit.png | 83302 | 2026-11-10T22:36:59+08:00 | Filename-derived subject: W3 09b encode fit |
| project-documentation/presentation/feedback-20261026/report-notes/W3-qa/W3-09b-encode.png | 98399 | 2026-11-10T22:36:59+08:00 | Filename-derived subject: W3 09b encode |
| project-documentation/presentation/feedback-20261026/report-notes/W3-qa/W3-09c-hls-fit.png | 72816 | 2026-11-10T22:36:59+08:00 | Filename-derived subject: W3 09c hls fit |
| project-documentation/presentation/feedback-20261026/report-notes/W3-qa/W3-09c-hls.png | 78471 | 2026-11-10T22:36:59+08:00 | Filename-derived subject: W3 09c hls |
| project-documentation/presentation/feedback-20261026/report-notes/W3-qa/W3-10-b-classes-fit.png | 84386 | 2026-11-10T22:36:59+08:00 | Filename-derived subject: W3 10 b classes fit |
| project-documentation/presentation/feedback-20261026/report-notes/W3-qa/W3-10-b-classes.png | 84386 | 2026-11-10T22:36:59+08:00 | Filename-derived subject: W3 10 b classes |
| project-documentation/presentation/feedback-20261026/report-notes/W3-qa/W3-11-b1-expiry-fit.png | 78961 | 2026-11-10T22:36:59+08:00 | Filename-derived subject: W3 11 b1 expiry fit |
| project-documentation/presentation/feedback-20261026/report-notes/W3-qa/W3-11-b1-expiry.png | 96249 | 2026-11-10T22:36:59+08:00 | Filename-derived subject: W3 11 b1 expiry |
| project-documentation/presentation/feedback-20261026/report-notes/W3-qa/W3-12-b2-retry-fit.png | 65123 | 2026-11-10T22:36:59+08:00 | Filename-derived subject: W3 12 b2 retry fit |
| project-documentation/presentation/feedback-20261026/report-notes/W3-qa/W3-12-b2-retry.png | 82038 | 2026-11-10T22:36:59+08:00 | Filename-derived subject: W3 12 b2 retry |
| project-documentation/presentation/feedback-20261026/report-notes/W3-qa/W3-12a-processing-retry-fit.png | 68852 | 2026-11-10T22:36:59+08:00 | Filename-derived subject: W3 12a processing retry fit |
| project-documentation/presentation/feedback-20261026/report-notes/W3-qa/W3-12a-processing-retry.png | 83146 | 2026-11-10T22:36:59+08:00 | Filename-derived subject: W3 12a processing retry |
| project-documentation/presentation/feedback-20261026/report-notes/W3-qa/W3-13-b3-fence-fit.png | 73676 | 2026-11-10T22:36:59+08:00 | Filename-derived subject: W3 13 b3 fence fit |
| project-documentation/presentation/feedback-20261026/report-notes/W3-qa/W3-13-b3-fence.png | 83840 | 2026-11-10T22:36:59+08:00 | Filename-derived subject: W3 13 b3 fence |
| project-documentation/presentation/feedback-20261026/report-notes/W3-qa/W3-13a-projection-fence-fit.png | 77643 | 2026-11-10T22:36:59+08:00 | Filename-derived subject: W3 13a projection fence fit |
| project-documentation/presentation/feedback-20261026/report-notes/W3-qa/W3-13a-projection-fence.png | 79470 | 2026-11-10T22:36:59+08:00 | Filename-derived subject: W3 13a projection fence |
| project-documentation/presentation/feedback-20261026/report-notes/W3-qa/W3-14-edit-fit.png | 71264 | 2026-11-10T22:36:59+08:00 | Filename-derived subject: W3 14 edit fit |
| project-documentation/presentation/feedback-20261026/report-notes/W3-qa/W3-14-edit.png | 93040 | 2026-11-10T22:36:59+08:00 | Filename-derived subject: W3 14 edit |
| project-documentation/presentation/feedback-20261026/report-notes/W3-qa/W3-14a-edit-relay-fit.png | 77483 | 2026-11-10T22:36:59+08:00 | Filename-derived subject: W3 14a edit relay fit |
| project-documentation/presentation/feedback-20261026/report-notes/W3-qa/W3-14a-edit-relay.png | 96743 | 2026-11-10T22:36:59+08:00 | Filename-derived subject: W3 14a edit relay |
| project-documentation/presentation/feedback-20261026/report-notes/W3-qa/W3-14b-edit-detail-fit.png | 79512 | 2026-11-10T22:36:59+08:00 | Filename-derived subject: W3 14b edit detail fit |
| project-documentation/presentation/feedback-20261026/report-notes/W3-qa/W3-14b-edit-detail.png | 83569 | 2026-11-10T22:36:59+08:00 | Filename-derived subject: W3 14b edit detail |
| project-documentation/presentation/feedback-20261026/report-notes/W3-qa/W3-14c-edit-adoption-fit.png | 79638 | 2026-11-10T22:36:59+08:00 | Filename-derived subject: W3 14c edit adoption fit |
| project-documentation/presentation/feedback-20261026/report-notes/W3-qa/W3-14c-edit-adoption.png | 94079 | 2026-11-10T22:36:59+08:00 | Filename-derived subject: W3 14c edit adoption |
| project-documentation/presentation/feedback-20261026/report-notes/W3-qa/W3-15-job-states-fit.png | 94719 | 2026-11-10T22:36:59+08:00 | Filename-derived subject: W3 15 job states fit |
| project-documentation/presentation/feedback-20261026/report-notes/W3-qa/W3-15-job-states.png | 122393 | 2026-11-10T22:36:59+08:00 | Filename-derived subject: W3 15 job states |
| project-documentation/presentation/feedback-20261026/report-notes/W3-qa/W3-16-attempt-states-fit.png | 90094 | 2026-11-10T22:36:59+08:00 | Filename-derived subject: W3 16 attempt states fit |
| project-documentation/presentation/feedback-20261026/report-notes/W3-qa/W3-16-attempt-states.png | 91480 | 2026-11-10T22:36:59+08:00 | Filename-derived subject: W3 16 attempt states |
| project-documentation/presentation/feedback-20261026/report-notes/W3-qa/W3-17-recovery-branches-fit.png | 76615 | 2026-11-10T22:36:59+08:00 | Filename-derived subject: W3 17 recovery branches fit |
| project-documentation/presentation/feedback-20261026/report-notes/W3-qa/W3-17-recovery-branches.png | 76615 | 2026-11-10T22:36:59+08:00 | Filename-derived subject: W3 17 recovery branches |
| project-documentation/presentation/feedback-20261026/report-notes/W3-qa/W3-18-lane-policy-fit.png | 73893 | 2026-11-10T22:36:59+08:00 | Filename-derived subject: W3 18 lane policy fit |
| project-documentation/presentation/feedback-20261026/report-notes/W3-qa/W3-18-lane-policy.png | 73893 | 2026-11-10T22:36:59+08:00 | Filename-derived subject: W3 18 lane policy |
| project-documentation/presentation/feedback-20261026/report-notes/W3-qa/W3-19-execution-adapters-fit.png | 77132 | 2026-11-10T22:36:59+08:00 | Filename-derived subject: W3 19 execution adapters fit |
| project-documentation/presentation/feedback-20261026/report-notes/W3-qa/W3-19-execution-adapters.png | 82431 | 2026-11-10T22:36:59+08:00 | Filename-derived subject: W3 19 execution adapters |
| project-documentation/presentation/feedback-20261026/report-notes/W3-qa/W3-20-contract-classes-fit.png | 70042 | 2026-11-10T22:36:59+08:00 | Filename-derived subject: W3 20 contract classes fit |
| project-documentation/presentation/feedback-20261026/report-notes/W3-qa/W3-20-contract-classes.png | 70042 | 2026-11-10T22:36:59+08:00 | Filename-derived subject: W3 20 contract classes |
| project-documentation/presentation/feedback-20261026/report-notes/W3-qa/W3-21-lease-functions-fit.png | 82616 | 2026-11-10T22:36:59+08:00 | Filename-derived subject: W3 21 lease functions fit |
| project-documentation/presentation/feedback-20261026/report-notes/W3-qa/W3-21-lease-functions.png | 82616 | 2026-11-10T22:36:59+08:00 | Filename-derived subject: W3 21 lease functions |
| project-documentation/presentation/feedback-20261026/report-notes/W3-qa/W3-22-hls-playback-fit.png | 79728 | 2026-11-10T22:36:59+08:00 | Filename-derived subject: W3 22 hls playback fit |
| project-documentation/presentation/feedback-20261026/report-notes/W3-qa/W3-22-hls-playback.png | 94798 | 2026-11-10T22:36:59+08:00 | Filename-derived subject: W3 22 hls playback |
| project-documentation/presentation/feedback-20261026/report-notes/W3-qa/W3-23-claim-finish-fit.png | 79932 | 2026-11-10T22:36:59+08:00 | Filename-derived subject: W3 23 claim finish fit |
| project-documentation/presentation/feedback-20261026/report-notes/W3-qa/W3-23-claim-finish.png | 96158 | 2026-11-10T22:36:59+08:00 | Filename-derived subject: W3 23 claim finish |
| project-documentation/presentation/feedback-20261026/report-notes/W3-qa/W3-23a-finish-fit.png | 74530 | 2026-11-10T22:36:59+08:00 | Filename-derived subject: W3 23a finish fit |
| project-documentation/presentation/feedback-20261026/report-notes/W3-qa/W3-23a-finish.png | 89285 | 2026-11-10T22:36:59+08:00 | Filename-derived subject: W3 23a finish |
| project-documentation/presentation/feedback-20261026/report-notes/W3-qa/W3-24-intake-types-fit.png | 62861 | 2026-11-10T22:36:59+08:00 | Filename-derived subject: W3 24 intake types fit |
| project-documentation/presentation/feedback-20261026/report-notes/W3-qa/W3-24-intake-types.png | 70255 | 2026-11-10T22:36:59+08:00 | Filename-derived subject: W3 24 intake types |
| project-documentation/presentation/feedback-20261026/report-notes/W4-preview/W4-media-assets.png | 89492 | 2026-11-10T22:36:59+08:00 | Design/slide preview: W4 media assets |
| project-documentation/presentation/feedback-20261026/report-notes/W4-preview/W4-media-cleanup.png | 98635 | 2026-11-10T22:36:59+08:00 | Design/slide preview: W4 media cleanup |
| project-documentation/presentation/feedback-20261026/report-notes/W4-preview/W4-media-delivery.png | 102199 | 2026-11-10T22:36:59+08:00 | Design/slide preview: W4 media delivery |
| project-documentation/presentation/feedback-20261026/report-notes/W4-preview/W4-media-intents.png | 95791 | 2026-11-10T22:36:59+08:00 | Design/slide preview: W4 media intents |
| project-documentation/presentation/feedback-20261026/report-notes/W4-preview/W4-media-main.png | 90102 | 2026-11-10T22:36:59+08:00 | Design/slide preview: W4 media main |
| project-documentation/presentation/feedback-20261026/report-notes/W4-preview/W4-media-pins.png | 94495 | 2026-11-10T22:36:59+08:00 | Design/slide preview: W4 media pins |
| project-documentation/presentation/feedback-20261026/report-notes/W4-preview/W4-media-projection.png | 86494 | 2026-11-10T22:36:59+08:00 | Design/slide preview: W4 media projection |
| project-documentation/presentation/feedback-20261026/report-notes/W4-preview/W4-media-retry.png | 81359 | 2026-11-10T22:36:59+08:00 | Design/slide preview: W4 media retry |
| project-documentation/presentation/feedback-20261026/report-notes/W4-preview/W4-media-upload.png | 78278 | 2026-11-10T22:36:59+08:00 | Design/slide preview: W4 media upload |
| project-documentation/presentation/feedback-20261026/report-notes/W4-preview/W4-processing-attempts.png | 113431 | 2026-11-10T22:36:59+08:00 | Design/slide preview: W4 processing attempts |
| project-documentation/presentation/feedback-20261026/report-notes/W4-preview/W4-processing-bindings.png | 92193 | 2026-11-10T22:36:59+08:00 | Design/slide preview: W4 processing bindings |
| project-documentation/presentation/feedback-20261026/report-notes/W4-preview/W4-processing-cleanup.png | 97566 | 2026-11-10T22:36:59+08:00 | Design/slide preview: W4 processing cleanup |
| project-documentation/presentation/feedback-20261026/report-notes/W4-preview/W4-processing-delivery.png | 94663 | 2026-11-10T22:36:59+08:00 | Design/slide preview: W4 processing delivery |
| project-documentation/presentation/feedback-20261026/report-notes/W4-preview/W4-processing-intents.png | 79995 | 2026-11-10T22:36:59+08:00 | Design/slide preview: W4 processing intents |
| project-documentation/presentation/feedback-20261026/report-notes/W4-preview/W4-processing-launcher.png | 102617 | 2026-11-10T22:36:59+08:00 | Design/slide preview: W4 processing launcher |
| project-documentation/presentation/feedback-20261026/report-notes/W4-preview/W4-processing-main.png | 99001 | 2026-11-10T22:36:59+08:00 | Design/slide preview: W4 processing main |
| project-documentation/presentation/feedback-20261026/report-notes/W4-preview/slide-w4-adr.png | 164862 | 2026-11-10T22:36:59+08:00 | Design/slide preview: slide w4 adr |
| project-documentation/presentation/feedback-20261026/report-notes/W4-preview/slide-w4-cancel-ack.png | 87892 | 2026-11-10T22:36:59+08:00 | Design/slide preview: slide w4 cancel ack |
| project-documentation/presentation/feedback-20261026/report-notes/W4-preview/slide-w4-envelope.png | 104986 | 2026-11-10T22:36:59+08:00 | Design/slide preview: slide w4 envelope |
| project-documentation/presentation/feedback-20261026/report-notes/W4-preview/slide-w4-json-descriptors.png | 152099 | 2026-11-10T22:36:59+08:00 | Design/slide preview: slide w4 json descriptors |
| project-documentation/presentation/feedback-20261026/report-notes/W4-preview/slide-w4-keys.png | 153463 | 2026-11-10T22:36:59+08:00 | Design/slide preview: slide w4 keys |
| project-documentation/presentation/feedback-20261026/report-notes/W4-preview/slide-w4-kinds.png | 162389 | 2026-11-10T22:36:59+08:00 | Design/slide preview: slide w4 kinds |
| project-documentation/presentation/feedback-20261026/report-notes/W4-preview/slide-w4-media-assets.png | 156794 | 2026-11-10T22:36:59+08:00 | Design/slide preview: slide w4 media assets |
| project-documentation/presentation/feedback-20261026/report-notes/W4-preview/slide-w4-media-cleanup.png | 112013 | 2026-11-10T22:36:59+08:00 | Design/slide preview: slide w4 media cleanup |
| project-documentation/presentation/feedback-20261026/report-notes/W4-preview/slide-w4-media-delivery.png | 137911 | 2026-11-10T22:36:59+08:00 | Design/slide preview: slide w4 media delivery |
| project-documentation/presentation/feedback-20261026/report-notes/W4-preview/slide-w4-media-intents.png | 124643 | 2026-11-10T22:36:59+08:00 | Design/slide preview: slide w4 media intents |
| project-documentation/presentation/feedback-20261026/report-notes/W4-preview/slide-w4-media-main.png | 146697 | 2026-11-10T22:36:59+08:00 | Design/slide preview: slide w4 media main |
| project-documentation/presentation/feedback-20261026/report-notes/W4-preview/slide-w4-media-pins.png | 111153 | 2026-11-10T22:36:59+08:00 | Design/slide preview: slide w4 media pins |
| project-documentation/presentation/feedback-20261026/report-notes/W4-preview/slide-w4-media-projection.png | 120511 | 2026-11-10T22:36:59+08:00 | Design/slide preview: slide w4 media projection |
| project-documentation/presentation/feedback-20261026/report-notes/W4-preview/slide-w4-media-retry.png | 123827 | 2026-11-10T22:36:59+08:00 | Design/slide preview: slide w4 media retry |
| project-documentation/presentation/feedback-20261026/report-notes/W4-preview/slide-w4-media-upload.png | 137777 | 2026-11-10T22:36:59+08:00 | Design/slide preview: slide w4 media upload |
| project-documentation/presentation/feedback-20261026/report-notes/W4-preview/slide-w4-operations.png | 118561 | 2026-11-10T22:36:59+08:00 | Design/slide preview: slide w4 operations |
| project-documentation/presentation/feedback-20261026/report-notes/W4-preview/slide-w4-processing-attempts.png | 185926 | 2026-11-10T22:36:59+08:00 | Design/slide preview: slide w4 processing attempts |
| project-documentation/presentation/feedback-20261026/report-notes/W4-preview/slide-w4-processing-bindings.png | 118164 | 2026-11-10T22:36:59+08:00 | Design/slide preview: slide w4 processing bindings |
| project-documentation/presentation/feedback-20261026/report-notes/W4-preview/slide-w4-processing-cleanup.png | 124200 | 2026-11-10T22:36:59+08:00 | Design/slide preview: slide w4 processing cleanup |
| project-documentation/presentation/feedback-20261026/report-notes/W4-preview/slide-w4-processing-delivery.png | 128258 | 2026-11-10T22:36:59+08:00 | Design/slide preview: slide w4 processing delivery |
| project-documentation/presentation/feedback-20261026/report-notes/W4-preview/slide-w4-processing-intents.png | 131468 | 2026-11-10T22:36:59+08:00 | Design/slide preview: slide w4 processing intents |
| project-documentation/presentation/feedback-20261026/report-notes/W4-preview/slide-w4-processing-launcher.png | 162660 | 2026-11-10T22:36:59+08:00 | Design/slide preview: slide w4 processing launcher |
| project-documentation/presentation/feedback-20261026/report-notes/W4-preview/slide-w4-processing-main.png | 157021 | 2026-11-10T22:36:59+08:00 | Design/slide preview: slide w4 processing main |
| project-documentation/presentation/feedback-20261026/report-notes/W4-preview/slide-w4-stores.png | 192289 | 2026-11-10T22:36:59+08:00 | Design/slide preview: slide w4 stores |
| project-documentation/presentation/feedback-20261026/report-notes/W4-preview/slide-w4-support-ops.png | 100238 | 2026-11-10T22:36:59+08:00 | Design/slide preview: slide w4 support ops |
| project-documentation/presentation/feedback-20261026/report-notes/W4-preview/slide-w4-support-stores.png | 113032 | 2026-11-10T22:36:59+08:00 | Design/slide preview: slide w4 support stores |
| project-documentation/presentation/feedback-20261026/slides/W5-qa/W5-pipeline-full.png | 81187 | 2026-11-10T22:36:59+08:00 | Filename-derived subject: W5 pipeline full |
| project-documentation/presentation/feedback-20261026/slides/W5-qa/W5-pipeline-main.png | 74423 | 2026-11-10T22:36:59+08:00 | Filename-derived subject: W5 pipeline main |
| project-documentation/presentation/feedback-20261026/slides/W5-qa/W5-pipeline-release.png | 79532 | 2026-11-10T22:36:59+08:00 | Filename-derived subject: W5 pipeline release |
| project-documentation/presentation/feedback-20261026/slides/W5-qa/W5-s33.png | 131931 | 2026-11-10T22:36:59+08:00 | Filename-derived subject: W5 s33 |
| project-documentation/presentation/feedback-20261026/slides/W5-qa/W5-s34.png | 137723 | 2026-11-10T22:36:59+08:00 | Filename-derived subject: W5 s34 |
| project-documentation/presentation/feedback-20261026/slides/W5-qa/W5-s35.png | 149052 | 2026-11-10T22:36:59+08:00 | Filename-derived subject: W5 s35 |
| project-documentation/presentation/feedback-20261026/slides/W5-qa/W5-s36.png | 194379 | 2026-11-10T22:36:59+08:00 | Filename-derived subject: W5 s36 |
| project-documentation/presentation/feedback-20261026/slides/W5-qa/W5-s37.png | 135142 | 2026-11-10T22:36:59+08:00 | Filename-derived subject: W5 s37 |
| project-documentation/presentation/feedback-20261026/slides/W5-qa/W5-s66.png | 159647 | 2026-11-10T22:36:59+08:00 | Filename-derived subject: W5 s66 |
| project-documentation/presentation/feedback-20261026/slides/W5-qa/W5-s68.png | 137743 | 2026-11-10T22:36:59+08:00 | Filename-derived subject: W5 s68 |
| project-documentation/presentation/feedback-20261026/slides/W5-qa/W5-w5-dast.png | 192932 | 2026-11-10T22:36:59+08:00 | Filename-derived subject: W5 w5 dast |
| project-documentation/presentation/feedback-20261026/slides/W5-qa/W5-w5-extra-scans.png | 171556 | 2026-11-10T22:36:59+08:00 | Filename-derived subject: W5 w5 extra scans |
| project-documentation/presentation/feedback-20261026/slides/W5-qa/W5-w5-release.png | 122270 | 2026-11-10T22:36:59+08:00 | Filename-derived subject: W5 w5 release |
| project-documentation/presentation/feedback-20261026/slides/W5-qa/review-before-W5-s34.png | 178222 | 2026-11-10T22:36:59+08:00 | Filename-derived subject: review before W5 s34 |
| project-documentation/presentation/feedback-20261026/slides/W5-qa/review-before-W5-s68.png | 195285 | 2026-11-10T22:36:59+08:00 | Filename-derived subject: review before W5 s68 |
| project-documentation/presentation/feedback-20261026/slides/W6-QA/S10a.png | 187230 | 2026-11-10T22:36:59+08:00 | Filename-derived subject: S10a |
| project-documentation/presentation/feedback-20261026/slides/W6-QA/S12.png | 180001 | 2026-11-10T22:36:59+08:00 | Filename-derived subject: S12 |
| project-documentation/presentation/feedback-20261026/slides/W6-QA/S12a.png | 167653 | 2026-11-10T22:36:59+08:00 | Filename-derived subject: S12a |
| project-documentation/presentation/feedback-20261026/slides/W6-QA/S13.png | 120704 | 2026-11-10T22:36:59+08:00 | Filename-derived subject: S13 |
| project-documentation/presentation/feedback-20261026/slides/W6-QA/S14.png | 140474 | 2026-11-10T22:36:59+08:00 | Filename-derived subject: S14 |
| project-documentation/presentation/feedback-20261026/slides/W6-QA/S15.png | 152132 | 2026-11-10T22:36:59+08:00 | Filename-derived subject: S15 |
| project-documentation/presentation/feedback-20261026/slides/W6-QA/S19.png | 139106 | 2026-11-10T22:36:59+08:00 | Filename-derived subject: S19 |
| docs/execution/evidence/linux-ci-38300284726/browser-playing.png | 93406 | 2026-10-13T03:59:14+08:00 | Filename-derived subject: browser playing |
| docs/execution/evidence/linux-ci-38306733800/browser-playing.png | 92638 | 2026-10-13T05:26:39+08:00 | Filename-derived subject: browser playing |
| docs/execution/evidence/local-workflow-422609b/browser-playing.png | 74342 | 2026-10-13T04:40:00+08:00 | Filename-derived subject: browser playing |
| frontend/vendor/blank.mp4 | 1777 | 2026-10-12T21:11:58+08:00 | Filename-derived subject: blank |

## Team membership, attribution and effort

### Resolve the team-size conflict

The request calls Team 17 a five-member team. Evidence identifies **five people for inherited FlickPond Project 1** and **three for Team 17 Project 2**. `docs/proposal.md` names the Project 1 five; `Team17-Proposal.docx` (4 October) explicitly says the lecturer approved the three-member team on **22 September 2026**; `project-documentation/effort-ledger.md` (recorded 20 October, resolved 21 October) and `final-report/src/00-front.md` list the same Project 2 three. Confirm the roster before silently adding names to the Project 2 report.

| Project 2 member | Handle evidence | Recorded specialism |
|---|---|---|
| Guruprasath Gopal | @Collaboration95 in effort ledger | Cloud, AWS, CI/CD, release |
| Ibrahim Mammadov | @1brahim74 in ledger and Project 1 reports | Processing/Media/backend, boundary security |
| Nguyễn Kim Long (ledger spells Nguyen Kim Long) | Not documented; ledger shows em dash | Domain/DDD/contracts/OpenAPI, Publisher, experiments, verification/evidence |

Project 1 roster in `docs/proposal.md` §2: Jiang Yibai, Zhang Jizhang, Yang Dongwei, Lu Jingxing, Ibrahim Mammadov. `docs/sprint1-report.md` §3: @JiangYibai666 (D), @zhanj384 (B), David @ttydw-ch (C), @Dilute-l (E), Ibrahim @1brahim74 (A). Jiang/Zhang name-to-handle mappings are supported by name resemblance, not an explicit mapping table in these sources. Yang↔David/@ttydw-ch and Lu↔@Dilute-l need confirmation. Do not label inferred mappings verified. Sprint 1 recorded commit counts A=14, B=4, C=2, D=2, E=1; Sprint 2 recorded 22 commits by Ibrahim and zero for the other four in its historical baseline range. These are historical Project 1 report claims.

### Current git authorship for Project 2 period

Window: 4 October 2026 00:00 UTC (proposal submission) through inventory date. Approval/planning began earlier (22 September). Counts exclude merges and use `git log --since` (committer-date filtering). No fetch performed.

| Local ref (not fetched) | SHA | Recorded author | Non-merge commits |
|---|---|---|---|
| HEAD | a8c8072b667a039923563ac2612dedc7e7a54ce8 | Guruprasath <guruprasath3200@gmail.com> | 439 |
| origin/Main | 76282d3b5a141f6548056f2506f9d5aff0742692 | Guruprasath <guruprasath3200@gmail.com> | 435 |
| Main | 8152edee88d6ac1bc8692b9e79dc80c06efb188f | Guruprasath <guruprasath3200@gmail.com> | 388 |

All 170 current PRs in the listed Project 2 period are authored through @Collaboration95 (PR dates/statuses above). No PR author entry for Ibrahim or Long is recorded; this does **not** show zero human contribution. Local all-ref authors also include `T3 Code <t3code@users.noreply.github.com>` checkpoints, a tooling identity. `src/20-conduct.md` discloses shared-account GitHub usage. Counts cannot substantiate per-member effort. All GitHub issue assignees are empty.

### Ownership tables and effort

- `Team17-Proposal.docx` §4.1 and `src/20-conduct.md` Project Plan: ten work packages with named leads. Domain/contracts → Long; Processing/Media → Ibrahim; baseline/cloud/CI/CD → Guruprasath; integration/reporting → All. Boundary security has **planned lead Guruprasath**, while the ledger **allocates effort to Ibrahim**. Distinguish the two.
- `project-documentation/effort-ledger.md`: member/handle table, specialisms, equal per-work-package allocation, actual milestones and progress narrative. **33 pd / 264 h total; 11 pd / 88 h per member** through 20 October is an agreed allocation, **not timesheets**. **36 pd / 288 h total; 12 pd / 96 h each** is a submission forecast. No final actual-hours update established. Project 1 hours are deferred to each member's own team's report, not repeated here.
- `project-roadmap/design/08-build-readiness/effort-log.csv` is a template, not recorded hours (contents below).
- `docs/sprint1-plan.md`: A–E component/story ownership for inherited Project 1 only.
- `docs/architecture/use-case-design.md`: seven use cases with shared conceptual/design class models and grouped analysis/design sequences; three design-problem bundles. Lines 454–458 explicitly call the named reviewers/explainers **suggestions, not verified original authorship**. Bundle 1 bounded cloud capacity/release → Guruprasath; bundle 2 SQL outbox/inbox messaging → Ibrahim; bundle 3 trusted identity/public contract → Long. These do not establish confirmed historical design responsibility.
- **Not found:** named Project 2 owner for each UC-1–UC-7's analysis and design; confirmed design-problem responsibility per member; five-person Project 2 contribution/effort table.

Effort CSV template:

```csv
id,project,member,date,task,actual_hours,evidence,notes
08-effort-1-0,Project 1,Guruprasath Gopal,,,,,Not collected; estimate excluded
08-effort-1-1,Project 1,Ibrahim Mammadov,,,,,Not collected; estimate excluded
08-effort-1-2,Project 1,Nguyễn Kim Long,,,,,Not collected; estimate excluded
08-effort-2-0,Project 2,Guruprasath Gopal,,,,,Not collected; estimate excluded
08-effort-2-1,Project 2,Ibrahim Mammadov,,,,,Not collected; estimate excluded
08-effort-2-2,Project 2,Nguyễn Kim Long,,,,,Not collected; estimate excluded

```

## Report figure shortlist and reuse notes

The complete 293-entry primary visual/source manifest above includes editable and rendered variants with exact sizes and committed dates; additional presentation preview rasters have a separate manifest. Useful candidates:

| Report purpose | Existing files (relative to repository root) | Reuse boundary |
|---|---|---|
| Product and actor scope | `project-documentation/final-report/figures/report-use-cases.png`, `project-documentation/images/platform-context.png`; persona illustrations under `project-roadmap/assets/` | Correct report paths are `project-documentation/final-report/figures/report-use-cases.png` and `project-documentation/images/platform-context.png` (also copied to report figures). Fictional personas, not usability-study results |
| Analysis/design | `project-documentation/final-report/figures/use-case-design-01-shared-analysis-class-model.png`, `use-case-design-02-common-implemented-design-class-model.png`, `use-case-design-03-*` through `use-case-design-08-*` | Shared class models and grouped sequences; do not claim unique per-member authored diagrams without confirmation |
| Design problems | `project-documentation/final-report/figures/report-dp1-capacity-release.png`, `report-dp2-handoff.png`, `report-dp3-identity.png` | Three bundles; names are suggested explanation owners only |
| Plan/progress | `project-documentation/final-report/figures/report-schedule.png`, `report-burnup.png`, editable `figures/src/report-burnup.svg` | Snapshot dates/captions need matching to data; burnup is issue counts |
| Logical/physical architecture | `project-documentation/final-report/figures/report-logical.png`, `views-logical.png`, `views-physical.png`, `architecture-before-after.png`, `aws-topology.png`; `docs/architecture/img/views-*.svg`, `ddd-context-map.svg` | Prefer editable original with current architecture; distinguish inherited/local/AWS stages |
| Persistence | `project-documentation/final-report/figures/views-er-media.png`, `views-er-processing.png`; corresponding SVGs in `docs/architecture/img/` | Current database split and logical ownership must match final text |
| Intake/encode/play flows | `project-documentation/final-report/figures/report-seq-intake.png`, `report-seq-encode.png`, `report-seq-play.png` | Match exact release and lane qualifications |
| Delivery/security/quality | `project-documentation/final-report/figures/report-cicd.png`, `deployment-pipeline.png`, `actual-vs-target.png` | Captions retain measured target misses and scan/cloud evidence limits |
| Newer feedback diagrams | `project-documentation/presentation/site/assets/uml/W1-*` through `W6-*` (`.puml`, `.svg`, selected `.png`) | W1 infrastructure/trust; W2 DDD/entities; W3 components/classes/sequences/state/recovery; W4 persistence/delivery/cleanup; W5 CI/CD/security; W6 architectural views/contracts. Use companion `feedback-20261026/report-notes/` and `review/W*-review.md` for corrections/qualifiers |

The root `project-documentation/images/` has four SVG/PNG pairs: architecture-before-after, deployment-pipeline, domain-model and platform-context. `showcase-prep/assets/aws-topology.svg` is another presentation-oriented technical diagram. Source `.puml`/`.mmd` files allow re-layout without redrawing; export/print QA remains future work.

## Gaps

| Needed artifact / unresolved fact | What exists now | Cheapest truthful way to fill the gap |
|---|---|---|
| Confirmed assessed Project 2 roster (request says five, documents say three) | Five-member P1 roster; approved three-member P2 proposal, ledger and cover | Confirm course/team roster with the parent author/team. If five are actually assessed, obtain the additional names, roles and evidence before changing the cover; preserve separate P1 inheritance credit |
| Project 2 user-story catalogue linked to the backlog | P1 US1–US5/operator/platform stories; P2 UC-1–UC-7 and persona/acceptance contracts in JSON/issues | Derive a dated retrospective story index from existing persona goals/use cases and link issue IDs/acceptance criteria. Label it reconstructed for report traceability, not a contemporaneous sprint backlog |
| Dated sprint plans / commitment records | P1 September plans; P2 proposal periods and Wave 0–4, PR/issue timestamps | Use the P2 delivery-phase plan honestly, or obtain confirmed sprint boundaries and original commitment evidence. If reconstructing periods, mark them reconstructed and show scope additions; do not equate a wave field with a timeboxed sprint |
| Per-sprint burndown | Ten-day 12–21 Oct issue burnup CSV/SVG/PNG; current created/closed timestamps | Generate a phase-based issue-count remaining-work chart from fixed issue sets and explicit dates as described above. For exact history, read close/reopen events and scope membership records through `gh` GET. Retain additions/removals/not-planned reasons; do not invent points, hours or original ideal scope |
| Formal Project 2 sprint review evidence | Technical/planning reviews, PR acceptance, 18 Oct audit (#253/#258), 20 Oct release freeze | Build a dated evidence crosswalk showing increments, acceptance outcomes and feedback from retained reviews. Call it delivery review evidence. Only call an event a sprint review when actual meeting/date/participants/outcomes are confirmed |
| Formal Project 2 retrospective | Explicit report statement that none was held; bugs, worklog, misses and feedback notes exist | Conduct and date a retrospective now with actual participants; record what helped, problems and agreed actions. A retrospective reconstruction of earlier lessons may cite the worklog but cannot claim an earlier ceremony occurred |
| Named responsibility for every UC analysis and design | UC-1–UC-7 catalogue and shared models; work-package leads and specialisms | Team-confirm a seven-row table with separate analysis/design responsible person(s), evidence and date. If assigning explanation/report work now, mark it current responsibility, not historical authorship |
| Confirmed design problem per member | Three technical bundles with explicitly suggested review/explanation owners | Ask each actual member to confirm the bundle they can defend and whether responsibility is current or historical. If roster has five, identify two additional real, evidence-backed design problems; do not split or fabricate problems merely to reach five |
| Verified handles and member-level contribution record | Guruprasath and Ibrahim handles documented; Long handle absent; P1 David/name mapping uncertain; all P2 PRs shared account | Confirm Long's handle and unresolved P1 name/handle mappings. Use dated member-reviewed contribution statements linked to work packages/PRs; disclose that account history cannot identify individual human authorship |
| Final actual effort / Project 1 effort | Equal agreed P2 allocation to 20 Oct and forecast to submission; no individual timesheets; P1 figures deferred | Obtain final member-confirmed actuals or clearly labeled retrospective estimates with basis/cutoff. Keep 88 h allocation and 96 h forecast labeled; retrieve each member's own P1 report rather than divide commit counts into hours |
| Submitted 16 October progress report / receipt | Template, ledger progress narrative, D-06, open #257 verification task | Locate actual submitted report and timestamp/receipt through the team/course owner. If absent, disclose missing submission evidence; adapt existing ledger narrative only as a newly dated reconstructed progress summary |
| Report-ready UI journey visuals | Product source and D1/D3 browser recordings in sibling rescue checkout | Extract and annotate a few representative frames (upload, status, library/playback, foreign-owner denial), record clip/timecode, source date and release limits. These would be reused recording evidence, not fresh usability testing |
| Durable shared D1–D5 delivery location | Five local gitignored files; report checkout lacks them; deck labels inconsistent | Place copies in the team's chosen durable access-controlled submission destination and record access/capture provenance after explicit delivery authorization. Current inventory only establishes local existence, bytes and metadata, not assessor accessibility |
| D6 maintainability clip | Planned storyboard; deck states not recorded | If required, record an authorized reproducible pipeline demonstration with release/run IDs. Otherwise state no clip and cite existing dated CI/CD receipts without claiming a video exists |
| Readability/currentness of reused figures | Many SVG/PNG/PlantUML sources, post-presentation corrections and preview renders | Select the latest corrected diagram family, retain honest captions, then render the revised report and inspect each figure at print size. Asset existence/source text does not establish visual quality |

No existing source artifact was edited and no remote state was changed to fill these gaps. This inventory distinguishes missing evidence from documentation that can be reconstructed and labeled truthfully.
