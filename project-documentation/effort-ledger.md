# Team 17 effort and milestone ledger

Issue #191. Recorded 20 October 2026 by Guruprasath Gopal on behalf of the team.

**Basis.** The team agreed to split Project 2 effort **equally** across its three members. The rows
below allocate the proposal's work packages (Team17-Proposal §4.1) to match that split. They are a
team-agreed allocation, not timesheets. One person-day (pd) is counted as 8 hours.

## Members

| Member | GitHub | Project 1 team |
|---|---|---|
| Guruprasath Gopal | Collaboration95 | Own Project 1 team (not Flickpond) |
| Ibrahim Mammadov | 1brahim74 | Flickpond (track A: worker, queue, media type) |
| Nguyen Kim Long | — | Own Project 1 team (not Flickpond) |

## Specialisms

The effort is equal, but each member specialised. Each member led the work in their area and reviewed
the other two members' work.

| Member | Specialism | Led |
|---|---|---|
| Guruprasath Gopal | **Cloud and delivery:** AWS and CI/CD | Reproducible baseline; AWS environment (CloudFormation stack, Lambda, ECS Fargate encoders, Aurora Serverless, S3, CloudFront); CI quality gates and image scans; the CD workflow (deploy, release, rollback); the close-out CD and Aurora-pause fixes; the release freeze |
| Ibrahim Mammadov | **Backend services:** Processing and Media | Extracting Processing (its own database, migrations, worker and recovery); adapting Media (asset records, Processing client, retry); boundary security (service token, owner checks, database roles, presigned URLs) |
| Nguyen Kim Long | **Domain, contracts and verification** | Domain analysis and DDD; the service contracts and OpenAPI documents; Publisher CLI and contract tests; the scaling, recovery and playback experiments; the queue-drain re-test; evidence index |

## Project 2 effort by work package

| # | Work package (proposal §4.1) | Planned pd | Guruprasath | Ibrahim | Long | Actual pd |
|---|---|---|---|---|---|---|
| 1 | Freeze baseline, reproducible local setup, fix the inherited scan finding | 2 | 2 | | | 2 |
| 2 | Domain analysis, service contracts and OpenAPI documents | 3 | | | 3 | 3 |
| 3 | Extract Processing: service, own database and migrations, workers and recovery | 6 | | 5 | | 5 |
| 4 | Adapt Media Management: asset records, Processing client, web routes and retry | 3 | | 3 | | 3 |
| 5 | Boundary security: service token, owner checks, database roles, presigned URLs, negative tests | 3 | | 2 | | 2 |
| 6 | Publisher CLI and contract tests | 2 | | | 2 | 2 |
| 7 | AWS environment, per-service deployment, CI/CD pipeline (deploy, release, rollback), smoke test | 4 | 6 | | | 6 |
| 8 | Experiments: scaling, load, recovery and playback; raw results | 3 | | | 3 | 3 |
| 9 | Integration fixes and repeat checks (close-out fixes #265–#273 and their re-tests) | 2 | 2 | | 1 | 3 |
| 10 | Progress report, presentation and final report (to date) | 3 | 1 | 1 | 1 | 3 |
| 11 | Release freeze and evidence index (#255, #189; not in the proposal) | 0 | | | 1 | 1 |
| | **Total** | **31** | **11** | **11** | **11** | **33** |

Project 2 to date: 33 pd (264 h), **11 pd (88 h) per member**. The total is 2 pd over the 31 pd
estimate. Work package 7 grew from 4 to 6 pd because the CD workflow (#178) was added on 18–19
October. The close-out fixes also added time: the CD script bugs, the Aurora pause and the queue
drain. Processing and boundary security came in 1 pd under their estimates each. The presentation and the final report will add
effort after 20 October. Update this table when they are done.

## Project 1 effort

Team 17 combines members from two Project 1 teams. Prof Boon Kui Heng approved the three-member team
on 22 September 2026 (Team17-Proposal §1). Project 2 does not continue any member's own Project 1
work. As the proposal states, it carries over the frozen code of a different Project 1, FlickPond
(`Flickpond/Media_player`, commit `890c5ec`), and uses it as the baseline (Team17-Proposal §1, §4.4).

- **Carried over, not claimed:** FFmpeg processing, HLS output, worker replicas and the basic CI
  workflow are inherited FlickPond capabilities. They are not counted as Project 2 effort, and
  Project 2 did not add any missing Project 1 features.
- **Project 1 effort:** each member spent effort on their own Project 1 team's project. That effort is
  reported with that project and is not repeated here. The FlickPond effort behind the inherited
  baseline belongs to the FlickPond team, so it is not attributed to Team 17.
- **Counted here:** only Project 2 work, which starts from the frozen baseline: 11 pd per member
  (above).

When the presentation asks for average effort across both projects, report Project 2 as measured
here. Report Project 1 as each member's own Project 1 figure, stated as carried over from a different
project.

## Milestones: plan against actual

| Planned (proposal §4.2) | Milestone | Actual | Evidence |
|---|---|---|---|
| 4 Oct | Proposal submitted | 4 Oct | Team17-Proposal.docx |
| 5–7 Oct | Baseline frozen; domain model and contracts drafted; lecturer review 7 Oct | 7–9 Oct | `project-roadmap/records/project-decisions.txt` |
| 8–14 Oct | Processing extracted with its own data; web app end to end; CLI started; first progress report | Processing 12 Oct, Media and Publisher 13 Oct; progress report due 16 Oct (D-06) | `processing/`, `media/`, `publisher/`; receipt check in #257 |
| 15–20 Oct | Security controls and tests; AWS deployment and pipeline; experiments | AWS deploy code 15 Oct; `project2-v1` tagged 18 Oct; `dc2-live` up 18 Oct; CD 18–19 Oct; #229 security and #238/#186 scaling verified 19 Oct; freeze 20 Oct | `docs/release/demo-release-manifest.md`, `docs/evidence-index.md` |
| 21–25 Oct | Fixes, rehearsal, presentation preparation | Pending | #192 |
| 26 Oct, 14:35–15:15 | Team 17 presentation | Pending | |
| 31 Oct, 23:59 (tentative) | Code submission (internal date; not set by the course) | Pending | #257 |
| 27 Oct–16 Nov | Final report with presentation feedback | Pending | #193 |

## Progress report

The briefing asks for completed work, hours per member, problems and the next two weeks' tasks. Under
decision D-06, the report due 16 October is the only progress report. Whether it was submitted is
tracked in #257.

**Completed:** the work packages above. The live environment is frozen at `daee44b`.

**Hours:** 88 h per member to date (264 h in total).

**Problems:**
- Queue wait is about 37 s against a 20 s target, mostly encoder boot time.
- Aurora did not pause until #273 fixed it.
- The CD script stopped partway twice; #265 and #267 fixed it.
- Duplicate work messages broke a deploy smoke test (#270).
- Open: #271, a 503 that should be a 4xx.

**Next two weeks:**
- Demo recordings (#254).
- Deck and rehearsal (#192).
- Presentation on 26 Oct.
- Final report draft (#193).
