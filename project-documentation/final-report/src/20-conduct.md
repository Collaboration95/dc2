# Project Conduct

## Project Plan

The briefing expects about 10 person-days (pd) per participant. The submitted proposal estimated
**31 pd** for three members across ten work packages (WBS). Each package had a lead member
(proposal §4.1).

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

The proposal's schedule had six periods:

- 5–7 October: baseline and domain model.
- 8–14 October: extraction and the web app end to end.
- 15–20 October: security, AWS, pipeline and experiments.
- 21–25 October: fixes and rehearsal.
- 26 October: the presentation.
- 27 October – 16 November: the final report.

The plan recorded four main risks:

- Tangled shared code.
- AWS account or cost issues.
- Little scaling gain.
- A three-member team.

Each had a mitigation: extract first; set up AWS in week 1 with cost alerts; cap CPU per worker
and report honestly; narrow the scope.

**Way of working.**

- **Backlog.** Work was planned as GitHub issues with outcome, acceptance and verification
  sections. The issues sat on a GitHub Project board (Project 14) with Workflow, Wave, Priority,
  Risk and Area fields.
- **Delivery waves, not timeboxed sprints.** Wave 0–4 locally, then the AWS V1 bundles, then
  close-out.
- **Integration.** Pull requests went into integration branches (section 5.1), with CI on every
  change.
- **Decisions.** Recorded as ADRs and project decisions (F-01, D-01 to D-07).
- **Reporting.** One progress report was due on 16 October (decision D-06).

There were no formal sprint reviews or retrospectives. Their place was taken by:

- the 9 October planning review;
- independent plan reviews (`docs/execution/reviews/`);
- the 18 October audit and board reconciliation (#253, #258);
- the 20 October freeze, with its acceptance checklist.

## Project Status

**As of 21 October 2026, the project is complete for its committed scope, and is in the
presentation and report phase.**

| Area | Status |
|:----------------|:--------------------------------------------------------------------------|
| Use cases UC-1 to UC-7 | All implemented and tested; cloud evidence for each (section 4) |
| Architecture | Two bounded contexts; asynchronous contracts; persistent AWS environment (AD-27) |
| Live environment | `dc2-live` up since 18 October; scales to zero; torn down once, after 16 November |
| Release identity | Team-accepted demo freeze at `daee44b` (20 October). Engineering release `629119c` (20 October). The current verified release is **`c7c489c` (21 October)**: the certifi remediation plus two delivery fixes, delivered by CD 39545554380 with an upload-to-playback smoke and a read-back of all images and aliases. The manifest records it as a post-freeze addendum. |
| CI | Every `Main` run green. Code release `c7c489c`: CI 39544952625 (Full verification); latest documentation push `1d68eff`: CI 39550093697 |
| CD | Two runs failed on 21 October, at the scan of the retained rollback image (39532075705) and at a cold-database login in the deploy smoke (39542434067). Both were fixed without weakening a gate (AD-28; PRs #285–#288) and redelivered by run 39545554380 (section 5.3). `Main` and `dev/closeout` are both at `1d68eff`. |
| Evidence | Results against every proposal target, including three measured misses (section 4) |
| Submission | Presentation 26 October 14:35–15:15 SGT; code submission 31 October (internal date); final report 16 November |

**Outstanding issues.**

| Item | Disposition |
|:------------------------------------------|:------------------------------------------------------------|
| Three measured misses: two-worker scaling 1.449× (target 1.6×); Processing release 10.1–10.3 min (target 10 min); queue wait about 37 s (target 20 s) | Reported against the unchanged targets. Improvement options are in AISS-02 (section 3.4). |
| Evidence not established on AWS: lost-queue-entry timing, duplicate-output check after a worker kill, a restore drill, actual spend | AISS-06. The final October bill is read before 16 November. |
| Optional V2 experiments #68 and #80 | Closed on 21 October. #68 (unattended launcher) was adopted into V2-live, so it was closed as completed. #80 (the optional V2 migration epic) was closed as not planned, because the experiments live behind template flags (AD-22). |
| Presentation deck and rehearsal (#192), recordings (#254) | Prepared from this report and the frozen demo release before 26 October |
| Presentation feedback | Incorporated into the final submission after 26 October, as the briefing requires |
| Course administration (#257) | Canvas checks for the progress-report receipt, peer assessment and the final upload; owned by Guruprasath Gopal |

## Project Metrics

**Milestones: planned against actual.**

![Figure {#fig:schedule}. Planned (proposal §4.2) and actual milestones.](figures/report-schedule.png){width=15.5cm}

| Planned (proposal §4.2) | Milestone | Actual | Evidence |
|:-------------|:----------------------------------------------|:--------------------------------------|:--------------------|
| 4 Oct | Proposal submitted | 4 Oct | `Team17-Proposal.docx` |
| 5–7 Oct | Baseline frozen; domain model and contracts drafted; lecturer review | 7–9 Oct (lecturer accepted; F-01, D-01 to D-07) | `project-roadmap/records/project-decisions.txt` |
| 8–14 Oct | Processing extracted with its own data; web app end to end; CLI started | Processing 12 Oct; Media and Publisher 13 Oct (PRs #28–#30) | `processing/`, `media/`, `publisher/` |
| 15–20 Oct | Security controls; AWS deployment and pipeline; experiments | AWS template and deploy tooling 15 Oct; CD workflow 18–19 Oct; cloud proof `r1017b` 17 Oct, `r1018b` and `r1019a` 18 Oct; tag `project2-v1` 18 Oct; `dc2-live` 18 Oct; security negatives and V2-live scaling 19 Oct; freeze 20 Oct | `docs/evidence-index.md`, `docs/release/demo-release-manifest.md` |
| 21–25 Oct | Fixes, rehearsal, presentation preparation | Engineering release `629119c` 20 Oct; final report v1.0 and CD scan fix 21 Oct; rehearsal 22–25 Oct | `docs/release/engineering-handoff.md`; this report |
| 26 Oct | Team 17 presentation, 14:35–15:15 | Scheduled | Presentation guide p. 2 |
| 27 Oct – 16 Nov | Final report with presentation feedback | Report v1.0 complete 21 Oct; feedback revision after 26 Oct | This report |

Baseline and design finished two days late, on 9 October, because the full design pack was
completed before any code changed. Extraction still landed inside its planned window (12–13
October), helped by parallel integration branches. The AWS work grew from one deployment to three
proof runs plus a persistent environment, and still finished inside the planned 15–20 October
period.

**Effort per member.** The team agreed to split Project 2 effort **equally** across the three
members (effort ledger, issue #191). The allocation below maps the proposal's work packages onto
that split; it is not a timesheet. One person-day is 8 hours. GG is Guruprasath Gopal, IM is Ibrahim
Mammadov and NKL is Nguyễn Kim Long.

| # | Work package | Planned | GG | IM | NKL | Actual |
|:--|:--------------------------------------------------|----:|----:|----:|----:|----:|
| 1 | Baseline, reproducible setup, inherited scan fix | 2 | 2 | | | 2 |
| 2 | Domain analysis, contracts, OpenAPI | 3 | | | 3 | 3 |
| 3 | Extract Processing (database, migrations, worker, recovery) | 6 | | 5 | | 5 |
| 4 | Adapt Media (asset records, Processing integration, retry) | 3 | | 3 | | 3 |
| 5 | Boundary security | 3 | | 2 | | 2 |
| 6 | Publisher CLI and contract tests | 2 | | | 2 | 2 |
| 7 | AWS environment, per-service deployment, CI/CD (deploy, release, rollback), smoke | 4 | 6 | | | 6 |
| 8 | Experiments: scaling, load, recovery, playback | 3 | | | 3 | 3 |
| 9 | Integration fixes and re-tests (close-out #265–#273) | 2 | 2 | | 1 | 3 |
| 10 | Progress report, presentation and final report (to 20 Oct) | 3 | 1 | 1 | 1 | 3 |
| 11 | Release freeze and evidence index (not in the proposal) | 0 | | | 1 | 1 |
| | **Recorded to 20 October** | **31** | **11** | **11** | **11** | **33** |
| 10 | Remaining: rehearsal, presentation and feedback revision (forecast) | | 1 | 1 | 1 | 3 |
| | **Total at submission (forecast)** | **31** | **12** | **12** | **12** | **36** |

**Total effort.**

- **Recorded to 20 October:** 33 pd (264 h), 11 pd (88 h) per member. This is 2 pd over the
  31 pd estimate, because the CD workflow (#178) and the close-out fixes (CD script bugs, Aurora
  pause, queue drain) were added.
- **Forecast at submission:** 36 pd (288 h), 12 pd (96 h) per member, about 16 % over the estimate.
- **Project 1 effort.** Each member's Project 1 effort is reported with their own Project 1. For
  Ibrahim Mammadov, that is FlickPond itself. The inherited FlickPond capabilities are credited to
  the FlickPond team and are not counted here.

**Delivery metrics (GitHub and CI, collected on 21 October before PRs #285–#290).** All commits, pull requests and issues in the
repository were made through one GitHub account, `Collaboration95`, which owns the repository. The
git history therefore cannot attribute work to individual members; the effort table above is the
attribution of record.

| Metric | Value |
|:-------------------------------------------|:------------------------------------------------------------|
| Pull requests | 128 opened, **123 merged** over 9 days (12–21 Oct): 27 into `Main`, 42 into `dev/closeout`, 39 into `dev/v1-integration`, 4 into `dev/v1`, 11 into short-lived `work/*` and `quality/*` integration branches |
| Issues | **156** created (12–19 Oct); 147 closed, 9 open (deck, report, recordings, Canvas checks, audit index, two optional V2 items) |
| Project board | 118 items: 109 Done, 8 Todo, 1 In Progress |
| Commits on `Main` | 533 (140 merge commits), 28 September – 21 October |
| CI runs | 246 runs of the CI workflow: 201 pull request, 32 push, 12 manual, 1 weekly |
| Automated tests | 3,982 Python tests collected (2,452 test functions in 197 files) plus 177 frontend tests; full offline regression 3,697 passed **[Local]** |
| Coverage | Media 93.91 %, Processing 93.90 % (statements plus branches); all packages pass the 80 % floor; frontend 96.24 % of statements |
| Code size | Service and client code 10,062 lines of Python (Media, Processing, engine, contracts, delivery, runtime support, Publisher) plus 1,822 lines of frontend JavaScript; operator and CI tooling 42,075 lines; tests 54,011 lines |

![Figure {#fig:burnup}. Issue burn-up derived from GitHub issue timestamps: scope (opened) grew in steps as the AWS readiness and close-out backlogs were added, and closure tracked it within one to two days.](figures/report-burnup.png){width=15.5cm}

The burn-up counts issues, not estimates; the issues carry no story points. The scope steps on
14–15 and 17 October are the AWS readiness backlog and the close-out backlog. The nine open issues
are submission tasks and two optional experiments.
