# V1 final verification: report v1.1 (11 Nov 2026)

Scope: a fresh end-to-end read of `src/00`–`70` on `dev/report-v1.1` (head `1abbd56` plus the
edits below). The read checked the template, `coverage-list.md`, `FEEDBACK.md`,
`FIX-DECISIONS.md`, a 25-claim code spot-check, 15 random diagrams plus all 5 charts, and the
build. Nothing was committed or pushed. The only checkout was the DOCX restore after each build.

**Verdict: READY TO SUBMIT, after one packaging step (H1 below).** The text, models, numbers and
cross-references are submission quality. There are 6 fixes applied, 1 High (packaging),
2 Medium and 5 Low remaining issues, and no content gaps against the template or the coverage list.

## 1. Fixes applied (src/*.md)

| # | File:line | Before → after | Why |
|---|---|---|---|
| F1 | `20-conduct.md:140` | "…The scheduled run of 8 November (42468024855) failed in its tool-installation and image-scan steps." → "…(42468024855) stopped in its tool-installation steps; Full verification passed again on 11 November for PR #326 into Main ([42949129268](https://github.com/Collaboration95/dc2/actions/runs/42949129268))." | Stale status. Run 42949129268 (`3d75dd9`) passed Full verification, coverage, all image scans, gitleaks and DAST (25 jobs, 3 intentional skips). |
| F2 | `20-conduct.md:141` | "Rerun scheduled CI after the tool-installation failure; close the seven…" → "Close the seven…"; "(AISS-05)" → "(AISS-01, AISS-05)" | The rerun is no longer outstanding. The open measurement items are AISS-01 (stage timing/profiling) and AISS-05 (restore drill). |
| F3 | `50-devops.md:117` (new row) | Added "CI 42949129268, 11 November \| `3d75dd9`, PR #326 into Main \| Full verification passed, including coverage, image scans, secrets and CI-called local DAST" | The dated evidence table ended on a failed run, although a later green run exists. |
| F4 | `40-quality.md:3–5` | Added "Figure {@fig:results} charts the speedup and release-time results." | `fig:results` was the only figure the text never referenced. |
| F5 | `62-ad-ibrahim.md:19,27,41` | `uc1-analysis-class` 15→14 cm; `uc1-analysis-upload` and `uc1-design-upload` 15→13.5 cm | At 15 cm they rendered 23.6, 25.5 and 25.6 cm tall, against an A4 text height of 24.6 cm (2.54 cm margins), so two would overflow the page. They now render at 22.0/22.9/23.0 cm. The smallest text is still 8.0 pt (`figure_readability.py 7` is clean). |
| F6 | `62-ad-ibrahim.md:83`; `64-ad-guru.md:9` | "The thresholds are in AD-30" → "…in the lane-decision table of section 3.2.1"; "(AD-30, UC-2)" → "(section 3.2.1, UC-2)" | AD-30 is the load-distribution decision. The lane thresholds live in the lane-decision table that follows it. |

Post-fix build: `build_report.py --no-word` succeeded with 86 figures numbered, no unresolved
`{@fig}`/`{#fig}` labels, no leftover TOC or landscape markers, and a tallest figure of 23.1 cm.
The DOCX was restored with `git checkout`.

## 2. Remaining issues, by severity

### High

- **H1. The committed submission files are still v1.0.** `Team17-Final-Report.docx` and `.pdf` were
  last committed in `18c1ea4`. The PDF's CreationDate is 22 Oct 2026, and it has 66 pages and
  no v1.1 content. Before submission, run the full build with Word (`build_report.py`, without
  `--no-word`) so that Word fills the contents page and exports the PDF. Check the TOC and the
  landscape pages (component figures), then commit both files on this branch. This is a packaging
  step, not a text change.

### Medium

- **M1. Branch protection does not enforce the named approver.** `Main` protection requires a PR
  and the "Full verification" check, which matches 50-devops §5.1/§5.3. However,
  `required_approving_review_count` is 0. The report says Guruprasath Gopal approves promotion
  (`50-devops.md:31,135`; `68-contributions.md:30`; Figure devops-cd), which is true as team
  process but not enforced by GitHub. Either require 1 approving review, or accept it as process.
  No text change is needed if the team keeps it as process.
- **M2. The PR #326 head check was still running.** CI 42967443158 on `1abbd56` (head before
  these edits) was in progress at verification time, and the commit carrying these edits will
  trigger another run. Merge only on green Full verification (required by protection anyway).

### Low (optional)

- **L1.** `50-devops.md` dated tables still list the 25 Oct and 8 Nov scheduled CI failures and
  the two failed 21 Oct deliveries. They are factual, dated evidence followed by the fix, and are
  acceptable under the tone rule. Trim the two scheduled-run failure rows if a lighter tone is wanted.
- **L2.** DP subheadings differ slightly: DP-1/DP-2 use "Solution models" / "Implementation
  decisions", while DP-3 uses "Solution class and sequence diagrams" / "Implementation decisions
  and verification". This is cosmetic, and all required parts are present.
- **L3.** Four 15 cm figures render 22.4–23.1 cm tall (`uc2-design-intake`, `uc2-design-exceptions`,
  `uc4-analysis-class`, `uc4-design-successor`). They fit, but each takes a full page, so check
  for large gaps in the Word PDF.
- **L4.** `40-quality.md:22` gives "release plus the separate upload smoke 15 min 38 s" without a
  stack; the chart labels it `r1019a + smoke`. Optionally add "(`r1019a`)" to the table.
- **L5.** `68-contributions.md` uses "He" for each member. Members should confirm their pronouns
  in the final read.

## 3. Coverage and template

Every template heading is present, with matching numbering: 1.1–1.4.2, 2.1–2.3, 3.1–3.1.4,
3.2–3.2.4, 3.3, 3.4, 4.1–4.4, 5.1–5.3 and 6. The AISS table has the template's six columns plus a
dated R1/R2 roadmap. The data groups give format, store, controls and trade-off.

Coverage-list items:

- **Agile artifacts** (§2.1): backlog with Project 14 fields and epics; user stories per UC;
  five sprint plans with review/retro tables; burnup, per-iteration burndown and issue reduction.
- **Project plan** (§2.1): names an owner for every UC and DP.
- **Transition strategies** (§6.3): TR-1–TR-6 each give analysis objects, UCs, class and sequence
  changes and reasons.
- **Use-case model** (§6.2): diagram with in- and out-of-scope cases. Each UC in §6.4 has a
  description with normal and exception flows.
- **Analysis and design models** (§6.4): every member owns at least one UC. Each UC has analysis
  class, analysis sequence(s), design class and design sequence(s).
- **Design problems** (§6.5): DP-1/2/3, one per member, each with problem class and sequence,
  candidates, rationale, solution class and sequence, and implementation decisions.
- **Other required sections:** schema (§3.2.3), source control, CI, and CD with environments,
  approver and verification (§5); contributions (§6.6); unit tests for complex modules (§4.4).
- **Presentation feedback** (§6.1): every verbatim remark in `FEEDBACK.md` maps to a response
  row, including the team's Lambda-or-Fargate question.

FIX-DECISIONS 1–8 have landed:

1. Team permission is stated in Background and in Metrics.
2. There is no progress-report mention.
3. The effort table matches the decision: 97/95/96 h, team 288 h (36 pd) against 248 h (31 pd),
   average 96.0, and +16%. All rows sum correctly.
4. Protection is described as in place.
5. The named approver is given.
6. Tone (R3 §9) is applied: the replacement sentences are present, and the misses appear only in
   the §4 results table and AISS-01's neutral pointer.
7. The cuts are applied and no model was removed.
8. All figures are ≥ 7 pt, and the burndown was redesigned as grouped bars with no defensive notes.

The R1 code-truth fixes are present, spot-checked for R1-01, 02, 04, 05, 06, 07, 08 and 09.

## 4. Consistency checks (all pass)

- **AD-01–AD-31** each appear exactly once across §3.1.1, §3.2.1 and §3.3; AD-30 and AD-31 are
  introduced as report analyses.
- **Section references** (3.1.4, 3.2.1–3.2.4, 3.4, 4.1, 4.3, 4.4, 5.3, 6.1–6.5) point to the
  right headings.
- **Figures:** all 86 `{@fig}` refs resolve, and all `figures/`, `assets/` and `data/` links exist.
- **Members and owners** agree across §2.1, §6.2, §6.4–6.6 and the appendix matrix.
- **Counts:** issues 156 = 149 + 7, PRs 173 = 164 + 5 + 4, and Project 14 has 118 = 111 + 6 + 1.
  The burndown bars (30/30, 126/117, 0/2, open 9 → 7) match the text and the burnup.
- **Test inventory:** 386 = 150 + 167 + 25 + 34 + 7 + 3, and 1,316 = 820 + 496.
- **Infrastructure:** 11 Lambdas (4 Media + 7 Processing), 15 alarms (11 + 4 DLQ), and 19/17 IAM
  roles all match `deploy/aws/v1/template.json` conditions.
- **Dates:** 4 Oct proposal, 9 Oct D-01, 18 Oct tag/dc2-live, 20 Oct freeze, 21–22 Oct
  short lane and DB split, 23 Oct clips and 26 Oct presentation, consistent throughout.

## 5. Code spot-check (25 claims, all confirmed)

1. Authorizer settings (`scripts/aws/v1/definitions.py:1530–1554`): GatewayAuthorizer uses
   payload 2.0, `$request.header.Cookie` and TTL 0, and targets `MediaAuthorizerAlias`.
2. `media/authorizer.py:13–52` maps user/operator to `publisher` and denies otherwise.
3. `contracts/gateway.py:58–61` strips `x-owner-id`/`x-role` and injects the actor from
   authorizer context.
4. Edit flow (`media/services/v1_lifecycle.py:105–167`): `copy_output_source` runs, then
   adoption with `pin_copied_source` and `stage_submit` in one transaction.
   `media/messaging.stage_command` exists, and nothing under `media/api` or `media/services`
   sends to SQS. `media/handlers.py` relays through `publish_commands`.
5. Direct finalize uses `enqueue_submit` inside adoption (`direct_intake.py:199`).
6. Lane rule (`processing/short_lane.py`): `work_lane` requires the flag, size in
   (0, 64 MiB] and no `lambda-` task; `check_probe` requires a finite duration in (0, 60 s] and
   height ≤ 1080.
7. Short Lambda constants: 3008 MB, 2048 MB scratch, 900 s, headroom 180 s, visibility 960 s,
   concurrency 2, account limit 10.
8. `emit_state` calls `work_lane` (`processing/messaging.py:121`), and `redirect_to_long_lane`
   exists at `:412`.
9. `processing/launcher.py`: `HARD_CAP = 3` with `slots` clamping, `_reserve` uses FOR UPDATE,
   `_send` uses FOR SHARE (`with_for_update(read=True)`), `set_enabled` uses FOR UPDATE, and
   `run_payload` passes `clientToken`.
10. `lifecycle.db_now` uses `clock_timestamp()`, and `lock_pair`/`live`/`claim`/`heartbeat`/
    `finish` exist.
11. Stage throttle defaults to 20/50, and the integration timeout is 29000 ms.
12. Fargate tasks are 2048/4096 for the worker and 256/512 for operations tasks.
13. Aurora: MinCapacity 0, configured max/auto-pause, and backup retention 1.
14. SQS: visibility 420, maxReceiveCount 5, retention 7 days (DLQ 14 days).
15. The VPC is `10.62.0.0/16` with /24 subnets.
16. Migration heads are `media_0008` and `processing_0007`, with 11 tables each (9 + inbox/outbox).
17. `contracts/v1.py` Envelope has exactly the 10 fields listed.
18. `ci.yml`: push to Main, all PRs, dispatch with `candidate_sha`, cron `0 3 * * 0` (Sunday);
    `coverage-gate` starts at line 581 and Full verification at 614.
19. `dast.yml` runs on cron `0 3 * * 1`; `security-scans.yml` runs on PR, Main push and
    `30 3 * * 1` with pip-audit 2.10.1 and Checkov 3.4.3, keeping reports 14 days. Job names match.
20. CD: `cd.yml:230–241` runs the post-deploy/release playback smoke; `cd.sh:600–640`
    implements promote → restore → abandon / restore-failed; `release.py` has promote at 240 and
    restore at 397; `cd_gate.py` admits only push to Main or dispatch.
21. `public_smoke.py` retries on 502/503/504 with (5, 10, 15) s pauses.
22. Security settings: bcrypt rounds 10, `jwt_ttl_seconds` 3600, `signed_url_ttl_seconds` 900.
23. The coverage gates (90/85 per service, 80/75 for recovery modules) are in `scripts/dev/coverage.py`.
24. Publisher has 5 files and 495 lines.
25. Test files and counts match all 21 rows of the §4.4 table. Both parameterized files collect
    13 + 12 cases, and running them gave 25 passed. All 24 named test functions cited in §3.2.4,
    §6.4, §6.5 and the appendix exist in the cited files.

Main protection, checked through the `gh` API: required check `Full verification`, PR required.

## 6. Figures checked

**Charts (all 5):** conduct-iteration-plan, conduct-overall-issues, conduct-iteration-burndown,
conduct-issue-reduction and results-actual-vs-target. All are legible and match their captions
and text values: 156/149, 7 open (6 tasks and 1 epic), and 9.65 / 15.63 min.

**Random diagrams (15, seed 1111):**

| Group | Figures |
|---|---|
| Use-case models | uc1-analysis-class, uc3-analysis-read, uc4-design-fences, uc4-design-successor, uc5-design-exceptions, uc6-analysis-class, uc7-analysis-class |
| Architecture and delivery | arch-artifacts, arch-deployment-main, arch-triggers, devops-cd |
| Data | data-delivery-schema, data-edit-sequence, data-media-support |
| Design problem | dp3-problem-sequence |

All are legible and match their captions, and their names agree with the code (for example
`stage_command`, `discard_stage`, `verify_direct_upload(check_content=False)`, 4 + 7 Lambdas, and
batch/cap 10/2 and 1/2). `figure_readability.py 7` reports no figure below 7 pt.
