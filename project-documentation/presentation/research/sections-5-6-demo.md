# Sections 5–6 research — DevOps and recorded demo

- **Purpose:** research and recording instructions for Team 17, FlickPond, NUS Graduate Certificate in Architecting Scalable Systems; presentation on **26 October 2026, 14:35–15:15 Singapore, Zoom**. Authority: `project-documentation/original-reference/04 Project Presentation Guidelines & Schedule.pdf`, pp. 1–2; `project-documentation/presentation/ROAD-TO-PRESENTATION.md`.
- **Time contract:** §5 **6 minutes talk + 1 minute Q&A**; §6 **8 minutes recorded demonstration + 2 minutes Q&A**. Clip lengths below are proposed editorial budgets, not measured system durations. Source: the guideline and `ROAD-TO-PRESENTATION.md`.
- **Research boundary:** repository inspected read-only; GitHub inspected only with authenticated `gh issue view`, `gh run list`, and `gh run view`. No AWS access, public-endpoint probes, workflow dispatch, recording, benchmark, git mutation, or other file edits performed. Commands below are **future recorder recipes**, not operations performed by this research task.
- **Evidence labels:** `[CODE]` implemented/configured; `[LOCAL]` local verification; `[AWS-HIST]` retained cloud result; `[GH-READ]` workflow observation through `gh`; `[PLAN]` proposed capture. Keep these labels in narration/captions when the distinction matters.
- **Recording identity:** stamp each clip with capture date, `dc2-live` or local environment, checkout SHA, admitted CD SHA/run, and image identities when available. A successful CD of a documentation commit does not mean every image was rebuilt from that SHA. Reference: `docs/release/demo-release-manifest.md`; `docs/results/engineering-20261021/delivery-c7c489c.json`.
- **Issue context:** #192 accepts a recorded primary path; #254 originally describes fallback packaging, but its later comment and the current roadmap explicitly call for recordings. Its requested scaling/pipeline screen recordings were unavailable at the audit; private older footage and team access were not inspected here. Sources: `gh issue view 192 --json body,comments`; `gh issue view 254 --json body,comments`; `ROAD-TO-PRESENTATION.md`, Stage 5.

## Section 5 — slide/message plan

| Slide | Guideline bullet | Proposed talk time | Key message and evidence |
|---|---|---:|---|
| S5.1 — One repository, independent release units | 5(a), source and artifacts | 65 s | Monorepo coordinates contracts; owner-specific tests, images and releases preserve boundaries. `project-documentation/final-report/src/50-devops.md`, “Source Control Strategy”; `deploy/v1/check_runtime.py`; `.github/CODEOWNERS`. |
| S5.2 — Select tests, then verify the exact candidate | 5(b), pipeline | 65 s | Integration PRs select changed lanes; Main promotion and pushes receive full verification; omissions must be intentional. `docs/ci/policy.md`; `.github/workflows/ci.yml`; `scripts/ci/policy.py`. |
| S5.3 — Promote bytes, with a way back | 5(b), procedures | 80 s | Exact-source admission → OIDC → safe stack update → per-owner scan/plan/promotion → owner smoke/restore → adoption → public upload/playback smoke. `scripts/ci/cd.sh`; `.github/workflows/cd.yml`; `scripts/aws/v1/proof/release_plan.py`. |
| S5.4 — A security gate blocked its own remediation | 5(c), findings | 90 s | Candidate clean; rollback baseline newly vulnerable; preserve strict candidate/kept-image scans while recording replaced-baseline findings. Then explain the cold-database smoke failure this uncovered. `docs/results/engineering-20261021/delivery-c7c489c.json`. |
| S5.5 — Cloud constraints became tested procedures | 5(c), findings | 60 s | Account-specific Lambda memory ceiling; resumable update after rollback; separate database wake checks; acknowledge protection/staging gaps. `docs/execution/aws/v2/lambda-short-encodes.md`; `scripts/aws/v1/deploy.py`; `scripts/aws/v1/public_smoke.py`; `docs/ci/policy.md`. |
| **Total** | **5(a)–5(c)** | **360 s** | Editorial allocation of the guideline's six-minute talk; keep the remaining minute for examiner questions. `ROAD-TO-PRESENTATION.md`. |

### 5(a) — Source code and artifact strategy

| Topic | Say/show | Numbers, identity and source |
|---|---|---|
| Monorepo | `media/`, `processing/`, `media_engine/`, clients, contracts, IaC, verification and receipts live together. A contract change and its consumers fit in one PR. | **Two business services**, browser + Publisher clients, shared `contracts/`, `delivery/`, `runtime_support/`. `project-documentation/final-report/src/50-devops.md`; `README.md`; `contracts/README.md`. |
| Branches | Show `fix/*` / `v2/*` / `docs/*` → `dev/closeout` → `Main`; historical V1 used `dev/v1-integration` → `dev/v1` → `Main`. Merge commits retain release history. | Integration/closeout dates and examples in `project-documentation/final-report/src/50-devops.md`, branch-flow table. Historical tag **`project2-v1`** is distinct from the persistent environment; `docs/release/demo-release-manifest.md`. |
| Artifact units | Media image; Processing API/control image; worker image. Processing owns API + worker release inputs. Frontend is a bucket deployment; Publisher is independently installable. | **Three deployed image repositories**, not one image per Lambda and not a fourth short-encoder image. `deploy/v1/media.Dockerfile`; `deploy/v1/processing.Dockerfile`; `deploy/v1/worker.Dockerfile`; `scripts/aws/v1/definitions.py`; `publisher/README.md`. |
| Artifact identity | Distinguish source SHA, local image config ID, registry manifest digest, published Lambda version, and movable `live` alias. Scan the actual built candidate; verify the manifest points to the scanned config before promotion. | Historical read-back matched **three images and ten aliases**, before the short encoder was added. `docs/results/engineering-20261021/delivery-c7c489c.json`, `deployed_readback`; do not present ten as the current function count. `scripts/aws/v1/proof/release_plan.py`. |
| Rollback assets | Keep previous immutable image identities, versions and task definitions; restore code/aliases against a compatible schema. Do not rebuild a historical image and call it the baseline. | Additive migration compatibility is required/attested; changed migrations defer automatic owner release to manual attestation. `scripts/ci/cd.sh`, `release_changed_owners` / `release_owner`; `docs/execution/aws/v1/deploy-runbook.md`, “Release proof on an existing stack”. |
| Short-lane artifact | The short encoder runs **the worker image**, updated through stack adoption of `WorkerImageUri`; its alias is outside the ordinary owner-function promotion set. | Same **three** image repositories; no separate image recipe. `docs/execution/aws/v2/lambda-short-encodes.md`, “How to enable” / “Per-owner release”; `scripts/aws/v1/definitions.py`. |

- **Unique point:** service independence is enforced by image-import checks, lane selection and release identity inside the monorepo; repository count alone proves nothing. Sources: `deploy/v1/check_runtime.py`; `docs/ci/policy.md`.
- **Caveat to say once:** one shared lockfile and stack remain; branch protection/rulesets and a separate staging environment are absent. PR/check discipline is team practice, not enforced approvals. Source: `project-documentation/final-report/src/50-devops.md`; limitation AISS-04 in `docs/architecture/decisions.md`.

### 5(b) — Pipeline and procedures

| Stage | Key message | Evidence / useful number |
|---|---|---|
| CI selection | A PR to `dev/closeout` selects the union of changed-owner lanes; shared/workflow/dependency/unknown inputs conservatively select full mode. Main PRs, Main pushes, dispatches and weekly runs select full. | Stable gates: **Dev gate** / **Full verification**; intentional skips checked. `docs/ci/policy.md`; `.github/workflows/ci.yml`; `scripts/ci/policy.py`. |
| Behavior and packaging | Lint, unit/frontend, real PostgreSQL integration, browser and Publisher HTTPS, offline control-plane, exact service image/runtime checks, local V1 acceptance and source-bound coverage. | **Five** backend coverage fragments, **≥80%** package floors; frontend **90%** floor. `docs/ci/policy.md`; `.github/workflows/ci.yml`; `project-documentation/final-report/src/40-quality.md`. Local V1 uses Moto and is not AWS validation. |
| Hosted timing | Parallelism makes the broad gate practical; do not promise every change takes only a few minutes. | Historical full CI **39531399249**, source `4ae6a0b`, **25 passed / 3 intentional skips**, **7m09s**, longest browser job **405 s**. `project-documentation/final-report/src/50-devops.md`. Latest pair is recorded separately below. |
| Security | Explain each gate, not a wall of scanner logos; SARIF is a publication format, not another scanner. | Tool/rule table below; `docs/ci/policy.md`, “Publishing to the Security tab”. |
| CD admission/access | Automatic CD uses only its triggering successful **push** CI attempt on Main from this repository; exact source/full-selection artifacts must match. Use GitHub OIDC, the `aws` environment and pinned actions. | No stored AWS access key in GitHub; serialized delivery concurrency. `.github/workflows/cd.yml`; `scripts/ci/cd_gate.py`; `deploy/aws/v1/github-oidc.yaml`. Manual full-dispatch admission is a separate supported path; `docs/ci/policy.md`. |
| Infrastructure | Update the established persistent environment in place; inspect change sets and refuse protected resource replacement. | Aurora/buckets/distribution protected; current split takes snapshot → clone → switch/verify → upload/playback smoke → peer-database cleanup. `docs/execution/aws/v1/deploy-runbook.md`, “Persistent environment”; `scripts/ci/cd.sh`, `split_database` / `finish_database_split`. |
| Owner release | Build only changed image inputs; scan candidate and retained baseline; push the exact config; verify registry manifest/config binding and completed ECR scan; plan compatibility; migrate/publish/move aliases; owner smoke; restore on failure; adopt into stack. | Historical Processing `r1019a` release step **9m39s**, but with its separate upload smoke **15m38s**. Earlier releases **10.1–10.3 min** missed the **10 min** target. `docs/results/actual-vs-target.md`, DP-1–DP-4. |
| Public smoke | Two different checks: owner smoke gates promotion/automatic restore; the later upload-to-playback verification is after promotion and does not itself roll aliases back. | Current CD generates a **3 s** clip, exercises reserve → S3 → finalize → done → MP4/HLS. It routes through Lambda on current live configuration. `scripts/ci/cd.sh`, `cmd_smoke`; `docs/execution/aws/v2/lambda-short-encodes.md`, “What the CD smoke now exercises”. |
| Database wake | The deploy-ladder smoke retries the first DB-backed call for **each** independently pausing service. It does not rerun the entire smoke or retry arbitrary statuses. | Media login and Processing batch: **5/10/15 s** pauses for **502/503/504** or transport error within **180 s** overall deadline; both attempt lists retained. Release smoke defaults to one attempt. `scripts/aws/v1/public_smoke.py`; `scripts/aws/v1/deploy.py`, `step_public_smoke`. |
| Evidence retention | Keep public sanitized results separate from private journals/credentials, preserving failed attempts and identity. | CD and exact-image scan artifacts **60 days**; ZAP JSON **14 days**; selection artifact **14 days**; raw coverage fragments **7 days**. `.github/workflows/cd.yml`; `.github/workflows/v1.yml`; `.github/workflows/dast.yml`; `.github/workflows/ci.yml`. |

| Tool / feed | Role and actual gate | What to show / avoid claiming |
|---|---|---|
| CodeQL | GitHub-managed default setup; Python, JavaScript/TypeScript, GitHub Actions. It has no dedicated checked-in workflow. | Code-scanning triage evidence, not proof that every high finding was fixed. Policy records **12 High dismissals, 0 fixes**, with reasons. `docs/ci/policy.md`, final triage section. |
| Trivy | Exact V1 Media, Processing and worker images; zero **fixable HIGH/CRITICAL** on candidates and kept images. CD repeats scans on deployed-build candidates and retained digests. | Per-image summary and identity; unfixed findings remain. CI SARIF categories differ from inherited legacy-image categories. `.github/workflows/v1.yml`; `scripts/ci/v1_scan.py`; `scripts/ci/cd.sh`. |
| ECR scan | Completed registry scan plus accepted-unfixed policy forms another release-plan check. | Retained-mode Trivy is not a bypass for scanner errors, wrong-image evidence, or every ECR finding. `scripts/aws/v1/proof/release_plan.py`; `docs/execution/aws/v1/deploy-runbook.md`. |
| ZAP | Authenticated disposable **local** Media/Processing API scans. Full CI requires successful execution/report generation; findings are report-only. | **Eight Low + eight informational entries** in the retained confirmation; not a scan of the AWS edge. `docs/results/engineering-20261020/dast-confirmation-findings-514914a.json`; `.github/workflows/dast.yml`; `project-documentation/final-report/src/40-quality.md`. |
| gitleaks / Ruff | Whole-history redacted secret scan always required; Ruff `S` rules provide required source security lint. | SARIF uploads are publication-only and can fail without failing an otherwise passing job. `docs/ci/policy.md`; `.github/workflows/ci.yml`. |
| Dependabot / npm / Sonar | Dependabot alerts and npm audit are present; Sonar is advisory and unconfigured. | Do not count a skipped Sonar job as completed SAST, or claim automatic Dependabot update PRs are enabled. `docs/ci/policy.md`; `.github/workflows/ci.yml`. |

- **Unique points:** exact-source admission and exact-image identity are different checks; missing/skipped evidence fails closed; a replaced rollback image gets a different finding disposition from an image kept in production. Sources: `scripts/ci/cd_gate.py`; `scripts/ci/v1_scan.py`; `scripts/aws/v1/proof/release_plan.py`.

### 5(c) — Technical findings: main story and backup stories

- **Delivery dates below are UTC calendar dates**, matching Actions logs. Capture labels should also show Singapore time where useful; do not mix UTC and Singapore dates silently.
- **Main narration:** use the retained-image deadlock → cold Media database → safe redelivery sequence. Keep remaining rows as backup examples or one compact “constraints became tests” slide.

| Date / run | Symptom → cause | Fix / lesson / qualification | Sources |
|---|---|---|---|
| 21 Oct; CD **39532075705**, source `4ae6a0b` | Candidate passed; scan of running rollback image failed on certifi **2026.7.22**, GHSA-6q48-6c7w-9gw2; candidate **2026.10.19** fixed it. Advisory arrived after baseline shipped. | Replaced baseline becomes `RETAINED_FIXABLE`; candidate and kept images remain strict. Scanner/identity errors still block. Restoring that vulnerable baseline was not exercised in the successful remediation run. | `docs/results/engineering-20261021/delivery-c7c489c.json`, `trigger` / `failed_runs`; `project-documentation/final-report/src/50-devops.md`; `scripts/ci/cd.sh`, `scan_baseline`. |
| 21 Oct; CD **39542434067**, `6155951` | After fixing scans, `PublicSmoke failed: login:503`; no migration had woken Aurora. API request took about **10.7 s**; capacity then read **1.0 ACU**. | Retry only the transient DB-wake login, preserve attempts. Successful redelivery **39545554380** / `c7c489c`: job done **101.2 s** after acceptance; deploy **22m56s**, upload smoke **2m27s**. That successful run did **not** exercise the retry. | `docs/results/engineering-20261021/delivery-c7c489c.json`; `project-documentation/final-report/src/50-devops.md`. |
| 22 Oct; CD **39728501166**, **39729654137**, **39731426830** | `processing-jobs:503` after successful Media login; second run records login attempts **[503, 200]**, yet Processing still fails. After AD-29, waking Media no longer wakes Processing. | Current `_waking` helper covers login **and Processing batch**, with distinct receipts; PR history in local git records `fix/smoke-processing-wake`. Green CD **39733859422**, `f07b5e6`, follows. A green run alone does not prove a retry occurred. | `scripts/aws/v1/public_smoke.py`; `scripts/aws/v1/deploy.py`; `[GH-READ] gh run view <ID> --log-failed` and latest-run snapshot below. Report/runbook login-only wording is stale. |
| 21 Oct; CD **39596145564** | Creating the short encoder rolled the stack back: Lambda refused memory above **3008 MB**, while design requested **3584 MB**. | Configure **3008 MB**, about **1.7 vCPU**, rather than assuming this account accepts the generic service maximum. Fargate comparison has **2 vCPU**. | `docs/execution/aws/v2/lambda-short-encodes.md`, “Admission rule”; `docs/results/actual-vs-target.csv`, LV-S2; `[GH-READ] gh run view 39596145564 --log-failed`. |
| 21 Oct; CD **39600906024** → **39604910633** | The next deploy refused `UPDATE_ROLLBACK_COMPLETE`, even though a new update is permitted from that completed rollback state. | Treat completed rollback as updatable, while other failed/in-progress states stay blocked; add regression coverage. Separate split rehearsal re-used a change-set name without taking a second snapshot. | `scripts/aws/v1/deploy.py`, `UPDATABLE`; `docs/results/engineering-20261021/database-split-rehearsal.json`; `[GH-READ] gh run view 39600906024 --log-failed`; `gh run view 39604910633`. |
| 21 Oct; CI **39540956502**, attempt 1 → 2 | `coverage-fast exceeded 120s`; unchanged failed jobs passed on rerun. Same job had taken **95 s** on preceding PR. | Current traced-suite budget is **180 s**, hosted job **5 min**; no hidden automatic suite retry. Normal hosted range **95–115 s** is the policy's explanation, not a new measurement here. | `docs/results/engineering-20261021/delivery-c7c489c.json`, `fix_pull_requests.286`; `docs/ci/policy.md`, “Verification and timing limits”; `.github/workflows/ci.yml`. |
| 21 Oct; CD **39637798081** | ECR release plan rejected worker CVE-2025-52290, absent from accepted findings. | Accepted-unfixed entry records the FFmpeg crafted-media DoS rationale and review; it is not a fixed vulnerability. Keep the risk and policy visible. | `docs/execution/aws/v1/scan-accepted-unfixed-20261017.json`; `[GH-READ] gh run view 39637798081 --log-failed`; roadmap's outstanding decision on CVE wording. |
| 20 Oct; CD **39412315002** → **39416747925** | Formatting changed historical Media migration bytes; compatibility guard held release. | Restore original migration bytes, exclude released migrations from formatting, retain guard. A failing gate found a real lifecycle hazard. | `docs/results/engineering-20261020/delivery-629119c.json`; `docs/release/engineering-handoff.md`, “Hosted verification and cloud delivery”. |
| 19 Oct; duplicate-message retest | Backlog work left stale duplicates; smoke exposed them. Later run had **18 sends for 9 jobs** yet **9/9 done**, queues empty, no purge. | Drain stale work safely; at-least-once delivery remains. Do not claim duplicates were eliminated. | `docs/results/actual-vs-target.md`, LV-11; `docs/execution/aws/v1/evidence/v2live-verify-20261019/burst-270-recheck.json`; `project-documentation/final-report/src/60-other.md`. |

### Best existing visual material

| Material / exact path | Best use | Slide-readability / correctness note |
|---|---|---|
| `project-documentation/final-report/figures/report-cicd.png`; editable `project-documentation/final-report/figures/src/report-cicd.mmd` | S5.2–S5.3 master reference | **Too tall/dense as a whole slide**, visually inspected. Split into CI and CD crops/redraws; compress the long tests box. Its preflight block is conceptual: established deploy safeguards run within the deploy path; the separate workflow Preflight step is skipped during deploy. |
| `showcase-prep/content/delivery.json`, visuals “CI: decide and verify” and “CD: deploy and promote” | Simplest starting point for readable S5.2/S5.3 | Existing four-stage flow specifications; use local sources, not GitHub browser access. Update simplified admission wording for manual-dispatch support; retain the distinction between owner smoke and later upload smoke. |
| `project-documentation/final-report/figures/report-dp1-capacity-release.png`; editable `project-documentation/final-report/figures/src/report-dp1-capacity-release.mmd` | S5.5 or D4 transition from booked V1 to persistent live | **Too much text for one slide**; show only the persistent side, add the short lane separately. Older task-start path does not depict the full Lambda lane. |
| `project-documentation/final-report/figures/use-case-design-08-implemented-sequence-uc-6-capacity-and-uc-7-release.png`; matching `.mmd` under `figures/src/` | Examiner backup for capacity and rollback details | **Dense sequence diagram**; crop capacity and release separately. Historical session mechanics require persistent-mode qualification. |
| `docs/architecture/img/views-sequence.svg`; `project-documentation/final-report/figures/use-case-design-06-implemented-sequence-uc-1-uc-3-upload-process-and-play.png` | D1 caption/reference, architecture hand-off | **Too dense for the demo itself**; narrate the already-established upload → background work → playback journey. |
| `docs/results/actual-vs-target.svg`; `project-documentation/final-report/figures/actual-vs-target.png` | D4 result inset / backup | Existing plotted comparison separates misses from passes; use only relevant panels, retain environment/workload/timing labels. |
| `docs/architecture/img/views-physical.svg`; `showcase-prep/assets/aws-topology.svg` | AWS context before D4 | Supporting architecture only; **too busy to explain while counts change**. Verify worker-image label and separate Aurora topology before reusing. |

### Likely §5 examiner questions — concise answers

| Question | Answer | Source |
|---|---|---|
| Why a monorepo if these are independent services? | Atomic contract/consumer PRs; owner-specific images, import checks, IAM, lanes and releases supply independence. Shared lockfile/stack remain limits. | `project-documentation/final-report/src/50-devops.md`; `deploy/v1/check_runtime.py`. |
| Does “green CI” mean everything was tested? | Only every check selected for that source/tier; Main requires full selection, all mandatory fragments and intentional-skip validation. | `docs/ci/policy.md`; `scripts/ci/policy.py`. |
| How do you know deployed bytes were scanned? | Bind scan to local config ID/source; push that config, verify registry manifest/config digest; retain final deployed read-back separately. CI/CD builds are distinct. | `scripts/ci/cd.sh`; `scripts/aws/v1/proof/release_plan.py`; `docs/results/engineering-20261021/delivery-c7c489c.json`. |
| Why allow a vulnerable rollback target? | Only when replacing it with a clean candidate; record findings and residual rollback risk. Blocking replacement would retain exposure. Kept images and scanner/identity errors remain strict. | `scripts/ci/cd.sh`, `scan_baseline`; AD-28 in `docs/architecture/decisions.md`. |
| Does every smoke failure roll production back? | No. Owner release smoke triggers alias restore; later upload/playback verification does not automatically restore a successful promotion. | `scripts/ci/cd.sh`, `release_owner` / `cmd_smoke`; `docs/execution/aws/v1/deploy-runbook.md`. |
| What happens to the schema during rollback? | Code/aliases restore; schema is not reversed. Old and new code must both tolerate the additive schema; migration changes require explicit attestation. | `docs/execution/aws/v1/deploy-runbook.md`; `scripts/ci/cd.sh`. |
| Why retry a smoke—does that hide failure? | Retry only transient wake responses on the first Media/Processing DB-backed calls, within a finite budget, recording every status. Other failures stay failures. | `scripts/aws/v1/public_smoke.py`; `scripts/aws/v1/deploy.py`. |
| Are security alerts all resolved? | No. Fixable release findings gate images; accepted unfixed issues and report-only local ZAP findings remain; CodeQL dismissals have reasons. | `docs/ci/policy.md`; `docs/execution/aws/v1/scan-accepted-unfixed-20261017.json`. |
| What enforces approvals and staging? | Currently team PR discipline, not branch rules/reviewers; one persistent environment plus local exact-image acceptance. This is an acknowledged limitation. | `project-documentation/final-report/src/50-devops.md`; AISS-04 in `docs/architecture/decisions.md`. |

## Documentary inconsistencies and recording implications

| Conflict / scope trap | Use in deck/recording |
|---|---|
| `50-devops.md`, `60-other.md`, runbook “Database wake”, and `showcase-prep/content/delivery.json` still say **login only** is retried. | Current `scripts/aws/v1/public_smoke.py` also retries **Processing batch**; cite the 22 Oct failed runs and final success. Even `step_public_smoke` has an older login-only comment; follow executable behavior. |
| `project-documentation/final-report/src/32-physical.md` calls the short encoder the **Processing image**. | It uses **WorkerImageUri / worker image**; verify `scripts/aws/v1/definitions.py` and `docs/execution/aws/v2/lambda-short-encodes.md`. |
| README/runbook opening snapshots still say rollback cancelled, AWS negatives not run, Aurora pause unobserved. | Those describe earlier checkpoints. Later LV-6/LV-10/LV-12 rows in `docs/results/actual-vs-target.md` supersede the current-status interpretation, while preserving original misses/cancellations. |
| Freeze source `daee44b`; engineering `629119c`; remediation `c7c489c`; later topology/lane commits; latest green CD source `f07b5e6`. | Label each result with its own source. `docs/release/demo-release-manifest.md` is not a current probe. Latest `gh` read verifies workflow completion, not independent current AWS image read-back. |
| `20-conduct.md` still names `1d68eff` / `c7c489c` as current and both branches equal there. | Use the latest-run snapshot below for pipeline footage; do not assert current remote branch equality without a fresh allowed check. `ROAD-TO-PRESENTATION.md` is the newer checklist. |
| Short-lane plan says two separate stack states / strict keep-only-if-all-pass; actual receipt used one enabled stack with padded Fargate files and failed the cold-median rule. | Say lane is enabled despite **`meets_keep_rule:false`**, with a documented small-sample exception/rationale; `merge_decision:pending` is not an acceptance receipt. `docs/execution/aws/v2/lambda-short-encodes.md`; `docs/results/engineering-20261021/short-lane-sl1021.json`. |
| Original Lambda concurrency **10**, Fargate quota **6 vCPU** versus newer concurrency **1000**, Fargate **30 vCPU**. | Historical arithmetic is retained for its original account conditions. Current encoder limits remain deliberate **3 Fargate + 2 Lambda**, not a current account quota claim. `docs/execution/aws/v2/lambda-short-encodes.md`, concurrency update; `docs/execution/aws/v1/deploy-runbook.md`, persistent environment. |
| `actual-vs-target.md` header says last updated 20 Oct although later short-lane rows are present. | Cite individual receipt date/environment, not the stale page header. `docs/results/engineering-20261021/short-lane-sl1021.json`. |
| `50-devops.md` / `40-quality.md` describe CodeQL triage on 22 Oct; `docs/ci/policy.md` heading says 21 Oct. | Report a **documented triage of 12 High dismissals**, date discrepancy unresolved; do not claim current Security-tab counts from a workflow result. |
| “One CVE accepted” in report prose versus a multi-entry accepted-unfixed file. | FFmpeg is one discussed acceptance, not the whole list. `docs/execution/aws/v1/scan-accepted-unfixed-20261017.json` contains other historical accepted entries; avoid “zero vulnerabilities”. |
| Runbook's later CD/session examples include obsolete `run_id` / session window / manual Fargate smoke descriptions. | Use its “Persistent environment” section, current `.github/workflows/cd.yml`, and `scripts/ci/cd.sh`; current automatic public smoke takes the short lane and does not open/close a booked session. |
| Report calls login workload 20 users; `generator.py` actually registers one temporary account and runs concurrent virtual users/logins against it. | Describe **20 concurrent login requests / samples**, not distinct account diversity. Also status route is a fresh account's jobs list; it is not a large populated-library test. `scripts/aws/v1/proof/generator.py`; `docs/results/actual-vs-target.md`, PF-1/PF-3. |
| Older Publisher prose says no delete command; current CLI supports edit/delete. | Use `publisher/cli.py` parser and its current help. For this demo stick to publish/status and ownership; do not expand scope. |

## Read-only Actions snapshot retained in this research

- `[GH-READ]` Retrieved on **22 Oct 2026** using `gh run list --workflow cd.yml`, `gh run list --workflow ci.yml --branch Main`, and `gh run view <ID> --json databaseId,headSha,createdAt,updatedAt,conclusion,jobs`; no workflow was started. This subsection is the local evidence record for newer run numbers not yet in the older committed receipts. Workflow definitions: `.github/workflows/ci.yml`, `.github/workflows/cd.yml`.

| Evidence | Observed result | Reproduction / supporting code path |
|---|---|---|
| CI **39733112331** | `f07b5e6127f0200a8019f441ed4dbedcf48e282f`; push; success; **25 successful / 3 skipped jobs**; created **06:18:20Z**, completed **06:25:36Z**; Full verification succeeded. | `gh run view 39733112331 --json headSha,conclusion,jobs,createdAt,updatedAt`; `.github/workflows/ci.yml`. |
| CD **39733859422** | Same admitted source; success; created **06:25:38Z**, completed **06:34:03Z**; Deploy **06:27:33–06:31:46Z**; upload/playback smoke **06:31:46–06:33:54Z**, both success. | `gh run view 39733859422 --json headSha,conclusion,jobs,createdAt,updatedAt`; `.github/workflows/cd.yml`; `scripts/ci/cd.sh`. |
| CD failures **39728501166 / 39729654137 / 39731426830** | All fail in Deploy on `processing-jobs:503`; middle run has `login attempts: [503, 200]`, others `[200]`. | `gh run view <ID> --log-failed`; current fix: `scripts/aws/v1/public_smoke.py`; related `scripts/aws/v1/deploy.py`. |
| Short-lane failures **39596145564 / 39600906024** | First: MemorySize must be ≤ **3008**, stack `UPDATE_ROLLBACK_COMPLETE`; second: completed rollback rejected as non-resumable. | `gh run view <ID> --log-failed`; `docs/execution/aws/v2/lambda-short-encodes.md`; `scripts/aws/v1/deploy.py`. |

## Section 6 — six pre-recorded clips

- **Playback budget:** **460 s (7m40s)** of clips + **20 s** total hand-offs/title transitions = **480 s (8m)**; §6's separate **120 s** Q&A remains available. All durations below are `[PLAN]`, constrained by `ROAD-TO-PRESENTATION.md`.
- **Editing rule:** record real runs first, then remove waits with “wait trimmed: actual elapsed …” captions. Use actual elapsed timestamps from each take; never label a new take with an old result. No audience wait for deployments, encoding, metric publication, or a database resume. Source: #254 body/comment via `gh issue view 254`; roadmap Stage 5.

| Clip / slide | Purpose and screen | Target | Narration line | Cut first if long |
|---|---|---:|---|---|
| D1 — Owner uploads and plays | Browser sign-in → upload → visible job state → done → advancing MP4/HLS playback | **100 s** | “An owner submits once; the platform stores the source, processes asynchronously, and returns owner-authorized playback.” | Registration typing, file-picker navigation, waiting; retain submit, processing state, completed playback. |
| D2 — An independent producer | Publisher terminal → batch acceptance/status → same owner's browser library | **70 s** | “Publisher is a second application using the published HTTPS contract, with no service imports or database credentials.” | Repeated polling and full batch listing; retain command, accepted IDs, result and browser continuity. |
| D3 — Ownership and authorization | Second account cannot list/read/play the first owner's job; anonymous request denied | **45 s** | “Knowing an asset ID is insufficient: the platform checks the current owner at the API boundary.” | Login typing; retain positive owner control, foreign denial and anonymous denial. |
| D4 — Capacity follows work | ECS task counts/timestamps **0→3→0**; short-lane mapping cap and observed Lambda concurrency | **110 s** | “Standard work launches finite Fargate encoders; short work uses a separately bounded Lambda queue, and neither needs an idle encoder.” | Long zero-state hold and metric navigation; retain actual peak, terminal jobs, return to zero, short-lane bound and observed result. |
| D5 — Scripted performance | Existing Python generator command, timed run cut, actual summary beside labelled historical benchmark | **65 s** | “Here is a repeatable public-API test; this recording's smaller workload and internet path are separate from the historical in-region benchmark.” | Other-route detail; retain workload, duration, p90, errors, path/environment and original targets. |
| D6 — Maintainability through delivery | `gh` CI/CD job lists/logs, exact SHA/admission, scans/SARIF; supplied human Security-tab capture | **70 s** | “A change must carry matching test and artifact evidence into delivery, and scanner findings stay visible for triage.” | Setup logs and historical rollback inset; retain CI gate, CD smoke, exact identity and security disposition. |
| **Total footage** | **All significant paths and named quality examples** | **460 s** | **20 s reserved for presentation transitions** | Shorten within clips; do not remove the scripted test or either scaling lane. |

### Shared recorder prerequisites and cost basis

- **Prepared environment:** frontend `https://d1e1dpefd6hp9x.cloudfront.net`; public API `https://nqxf2hclhi.execute-api.ap-southeast-1.amazonaws.com`; API prefixes `/api/media` and `/api/processing`. Source: `project-documentation/final-report/src/60-other.md`; `README.md`. Availability was **not probed** during this research.
- **Warm before each take:** follow #254's advice to upload a clip about **10 minutes** before recording; additionally confirm authenticated Media list and Processing batch both work, because the clusters pause independently. Health alone is insufficient. Keep the warm-up close enough to the take to avoid another idle pause; source: `gh issue view 254 --json comments`; `scripts/aws/v1/public_smoke.py`; `docs/execution/aws/v1/deploy-runbook.md`.
- **Accounts:** disposable owner A used by browser and Publisher; different owner B for denial; separate private cookie jar per parallel Publisher process. Passwords entered through hidden prompts; cookies and signed playback URLs never shown. Sources: `publisher/README.md`; `docs/execution/aws/v1/evidence/v2live-verify-20261019/scaling-and-backlog.json`; #254.
- **Tools/material:** installed locked Python environment with HTTPX/Publisher, FFmpeg/FFprobe, `jq`, authenticated `gh`; recorder/editor already installed; small legal sample with audio. Avoid setup/install operations in footage. Sources: `README.md`; `publisher/README.md`; `scripts/aws/v1/proof/short_encode.py`.
- **C0 — estimate, not a bill:** use retained Singapore rate inputs, not a live price claim: Aurora **$0.20/ACU-hour**; worker **$0.12824/task-hour** including IPv4; API **$1.25×10⁻⁶/request**; Lambda **$0.0000166667/GB-second** plus requests. Source: `docs/execution/aws/v1/cost-inputs.json`, `rates_usd`; Fargate breakdown also in `docs/execution/aws/cost-worksheet.json`.
- **C0 — shared compute:** two clusters assumed awake at **0.5–2 ACU each** cost **$0.20–$0.80 per recording hour**, derived as `2 × ACU × $0.20`; this is a capacity assumption, not measured utilization. Add resume/auto-pause tails and usage-driven I/O, requests, logs, storage, transfer and retries. Sources: `docs/execution/aws/v1/cost-inputs.json`; `docs/execution/aws/v1/deploy-runbook.md`; AD-29 in `docs/architecture/decisions.md`.
- **C0 — short encode planning reference:** about **$0.0003/encode**, versus historical padded Fargate **$0.002137/encode**, billed compute only, workload-specific. Source: `docs/results/engineering-20261021/short-lane-sl1021.json`, `steps.lambda` / `steps.fargate`. Do not extrapolate into an invoice or assume every source costs the same.
- **Budget accounting:** allocate shared DB awake time once for the recording session, not once again for every overlapping clip. All per-clip costs below are rough marginal estimates from C0; raw capture time, not final playback time, determines cost. Local playback of finished clips adds **$0 AWS**. Source basis: `docs/execution/aws/v1/cost-inputs.json`; plan arithmetic.

### D1 — Sign in, upload, encode, playback

- **Prerequisites:** warmed owner A; known short video within short-lane limits; browser already at frontend, no DevTools Network/Application panels; prepared empty/recognizable library. Current input cap **100 MiB**; short admission **≤60 s / ≤64 MiB / ≤1080 px**. Sources: `project-documentation/final-report/src/40-quality.md`; `docs/execution/aws/v2/lambda-short-encodes.md`.
- **Exact take:** open frontend → sign in A → show library → choose prepared MP4 → submit once → retain accepted/queued or processing state → cut annotated wait → show done → open player → show advancing decoded frames and audio → switch MP4/HLS only if both are offered/working. Refresh/list under the same account to show persisted result.
- **Do not promise every brief state appears:** fast transitions may skip a UI poll; caption the actual observed state rather than manufacturing a progression. Trace: `frontend/`; `docs/architecture/use-case-design.md`, UC-1–UC-3.
- **On-screen proof:** account label, filename, accepted job, real completed player; no presigned query strings. Keep job ID for D2/D3 linkage. Source: `docs/architecture/use-case-design.md`; `publisher/README.md`.
- **Cost:** approximately **$0.0003** encode reference plus **$0.013–$0.053** DB compute for a planned **4-minute** raw take; other shared usage extra (C0, `docs/execution/aws/v1/cost-inputs.json`; `docs/results/engineering-20261021/short-lane-sl1021.json`).
- **Timing/cut/narration:** D1 row above; retain playback even if upload footage must shorten.

### D2 — Publisher as a producer

- **Prerequisites:** same owner A; `DEMO_PRIVATE` is a private recording-state directory outside Git, provisioned before the session; `DEMO_EMAIL_A` and `DEMO_VIDEOS` point to prepared account/folder. Folder contains a small pair of distinct MP4 files; do not include accidental originals/large media. Source: `publisher/README.md`, batch behavior.
- **Exact future commands:** all global options precede the subcommand; login hides password; use normal system certificate trust for the AWS origin. Sources: `publisher/README.md`; `publisher/cli.py`.

```sh
DEMO_MEDIA='https://d1e1dpefd6hp9x.cloudfront.net/api/media'
DEMO_PY='.venv/bin/python'
"$DEMO_PY" -m publisher --base-url "$DEMO_MEDIA" --cookie-jar "$DEMO_PRIVATE/a.txt" --json login "$DEMO_EMAIL_A"
"$DEMO_PY" -m publisher --base-url "$DEMO_MEDIA" --cookie-jar "$DEMO_PRIVATE/a.txt" --json publish "$DEMO_VIDEOS" | jq '{ok,files:[.files[]|{file,ok,job_id,error}]}'
"$DEMO_PY" -m publisher --base-url "$DEMO_MEDIA" --cookie-jar "$DEMO_PRIVATE/a.txt" --json status "$DEMO_ASSET_A" --wait --max-polls 180 --interval 2 | jq '{ok,job:{id:.job.id,filename:.job.filename,status:.job.status}}'
```

- **Operator step:** assign `DEMO_ASSET_A` from one accepted `files[].job_id`, then run status; browser refresh shows the same owner's asset. CLI field `job_id` refers to the public asset identifier; Processing's separate ID is not exposed by Publisher's status allowlist. Use `set -o pipefail` to preserve command failure through JSON filters, without `set -e` during the expected-denial clip. Sources: `publisher/cli.py`; `publisher/client.py`; `docs/architecture/use-case-design.md`, UC-5.
- **Recording output:** allowlisted fields only; avoid raw `output`/full completed-job JSON because it includes signed URLs. If polls exhaust, continue `status` for the accepted ID; do not republish. Source: `publisher/README.md`.
- **Cost:** pair of short encodes about **$0.0006**, plus **$0.017–$0.067** DB compute for planned **5-minute** raw take (C0; `docs/results/engineering-20261021/short-lane-sl1021.json`; `docs/execution/aws/v1/cost-inputs.json`).
- **Timing/cut/narration:** D2 row; optional stored-source retry only when an existing failed job and its provenance are available—no need to inject failure for this plan. `docs/architecture/use-case-design.md`, UC-4.

### D3 — Ownership / authorization

- **Prerequisites:** A's completed asset retained; B has a separate cookie jar and no rights to A's assets; prepared terminal filtering. Sources: `docs/execution/aws/v1/evidence/s229-live-results.md`; `publisher/README.md`.
- **Exact future commands:** first prove A can read; log in B, then request the same ID. Sources: `publisher/cli.py`; `publisher/client.py`; historical expected foreign response **404**, anonymous **401** in `docs/results/actual-vs-target.md`, LV-6 / `project-documentation/final-report/src/40-quality.md`.

```sh
"$DEMO_PY" -m publisher --base-url "$DEMO_MEDIA" --cookie-jar "$DEMO_PRIVATE/a.txt" --json status "$DEMO_ASSET_A" | jq '{ok,status:.job.status}'
"$DEMO_PY" -m publisher --base-url "$DEMO_MEDIA" --cookie-jar "$DEMO_PRIVATE/b.txt" --json login "$DEMO_EMAIL_B"
"$DEMO_PY" -m publisher --base-url "$DEMO_MEDIA" --cookie-jar "$DEMO_PRIVATE/b.txt" --json status "$DEMO_ASSET_A" | jq '{ok,error}'
"$DEMO_PY" -m publisher --base-url "$DEMO_MEDIA" --cookie-jar "$DEMO_PRIVATE/b.txt" --json output "$DEMO_ASSET_A" | jq '{ok,error}'
curl --silent --output /dev/null --write-out 'anonymous HTTP %{http_code}\n' "$DEMO_MEDIA/jobs/$DEMO_ASSET_A"
```

- **On-screen:** A's success; B's safe API error; B's browser library lacks A's job; anonymous status. Expected nonzero denial exits are successful demonstration outcomes, not broken recording takes. If exact foreign HTTP code is needed, capture a safe status-only API response through a prepared owner session; never display cookie headers. Source: `publisher/client.py`; `docs/execution/aws/v1/evidence/s229-live-results.md`.
- **Cost:** no new encode; **$0.007–$0.027** DB compute for planned **2-minute** raw take plus small request costs (C0; `docs/execution/aws/v1/cost-inputs.json`).
- **Timing/cut/narration:** D3 row; retaining A's positive control makes a denial meaningful.

### D4 — Fargate automatic scale and Lambda concurrency

- **Prerequisites:** future cloud recorder with approved read-only observation credentials; working Publisher sessions, no competing workload, baseline ECS worker count at zero; prepared long-lane fixture and short fixture. No deployment, quota change, manual `RunTask`, forced stop, session close or lane toggle is required for this capture.
- **Why a new fixture matters:** the old **20 s** scaling clips now enter Lambda. To demonstrate **Fargate** without first redirecting, make source size exceed **64 MiB** but stay below **100 MiB**. Historical `sl1021` used a **70 MiB** MP4 `free` atom with unchanged video/audio streams. Sources: `docs/results/engineering-20261021/short-lane-sl1021.json`; `docs/execution/aws/v2/lambda-short-encodes.md`.
- **Exact future fixture preparation, off-camera:** generate a **24 s, 640×360** audio/video MP4, then append padding. This is a planned synthetic sample, not the retained benchmark fixture. Bounds/source rationale: `scripts/aws/v1/proof/short_encode.py`; `docs/results/engineering-20261021/short-lane-sl1021.json`.

```sh
ffmpeg -y -loglevel error -f lavfi -i 'testsrc2=duration=24:size=640x360:rate=30' -f lavfi -i 'sine=frequency=440:duration=24' -c:v libx264 -pix_fmt yuv420p -c:a aac -shortest "$DEMO_PRIVATE/short24.mp4"
python3 - "$DEMO_PRIVATE/short24.mp4" "$DEMO_PRIVATE/fargate24.mp4" <<'PY'
from pathlib import Path
import struct, sys
source, target = map(Path, sys.argv[1:])
payload = 70 * 1024 * 1024
with target.open('wb') as out:
    out.write(source.read_bytes())
    out.write(struct.pack('>I4s', payload + 8, b'free'))
    out.write(b'\0' * payload)
assert 64 * 1024**2 < target.stat().st_size < 100 * 1024**2
PY
ffprobe -v error -show_entries format=duration,size -of json "$DEMO_PRIVATE/fargate24.mp4"
```

- **Exact future Fargate shot:** provision three folders, each containing the padded fixture, and three separately authenticated jars `scale-1.txt`…`scale-3.txt` before recording. Run these concurrently in separate terminal panes; never share the jar lock. Sample launcher-owned ECS tasks before submission, at the actual peak, and after completion. Sources: `publisher/README.md`; historical parallel setup in `docs/execution/aws/v1/evidence/v2live-verify-20261019/scaling-and-backlog.json`.

```sh
# Repeat in panes with DEMO_N=1, 2 and 3; all sessions belong to A.
"$DEMO_PY" -m publisher --base-url "$DEMO_MEDIA" --cookie-jar "$DEMO_PRIVATE/scale-$DEMO_N.txt" --json publish "$DEMO_PRIVATE/standard-$DEMO_N" --wait --max-polls 180 --interval 2 | jq '{ok,files:[.files[]|{file,ok,job_id,status:.job.status}]}'
```

- **Observation recipe, future operator only:** export explicit `AWS_PROFILE` and `AWS_REGION=ap-southeast-1`; get `ClusterArn`, `ProcessingShortEncoderFunctionName`, and `ProcessingShortEncoderMappingId` from the stack outputs. Sources: `deploy/aws/v1/template.json`, Outputs; AWS profile convention in `docs/execution/aws/v1/deploy-runbook.md`.

```sh
aws cloudformation describe-stacks --stack-name dc2-live --query 'Stacks[0].Outputs[?OutputKey==`ClusterArn` || OutputKey==`ProcessingShortEncoderFunctionName` || OutputKey==`ProcessingShortEncoderMappingId`]' --output table
# Set DEMO_CLUSTER, DEMO_SHORT_FUNCTION, DEMO_SHORT_MAPPING from those outputs.
aws ecs list-tasks --cluster "$DEMO_CLUSTER" --family dc2-live-worker --desired-status RUNNING --query taskArns --output json
# Copy listed ARNs into the --tasks arguments; inspect actual lastStatus, not only desired status.
aws ecs describe-tasks --cluster "$DEMO_CLUSTER" --tasks TASK_ARN_1 TASK_ARN_2 TASK_ARN_3 --query 'tasks[].{status:lastStatus,created:createdAt,started:startedAt,stopped:stoppedAt}' --output table
aws lambda get-event-source-mapping --uuid "$DEMO_SHORT_MAPPING" --query '{State:State,BatchSize:BatchSize,ScalingConfig:ScalingConfig}' --output json
```

- **Exact short-lane shot:** after standard jobs drain, submit a prepared burst of short files through separate Publisher processes/jars as above, using unpadded folders; retain job acceptances and terminal results. In the CloudWatch function metrics view, select `ConcurrentExecutions`, statistic **Maximum**, the exact capture interval, and show the actual peak. Mapping `MaximumConcurrency:2` is a bound, not an observation of two concurrent encodes. Source: `docs/execution/aws/v2/lambda-short-encodes.md`; `processing/short_lane.py`.
- **Burst command:** preauthenticate `short-1.txt` through `short-4.txt` as A and provision each `short-N` folder with one unpadded source. This planned four-job burst is separate from the historical serial comparison. Source for client/locking behavior: `publisher/README.md`; `publisher/cli.py`.

```sh
for DEMO_N in 1 2 3 4; do
  ("$DEMO_PY" -m publisher --base-url "$DEMO_MEDIA" --cookie-jar "$DEMO_PRIVATE/short-$DEMO_N.txt" --json publish "$DEMO_PRIVATE/short-$DEMO_N" --wait --max-polls 180 --interval 2 | jq '{ok,files:[.files[]|{file,ok,job_id,status:.job.status}]}') &
done
wait
```

- **CLI alternative to metric UI:** set `DEMO_BURST_START` / `DEMO_BURST_END` to the actual UTC capture interval and allow metric publication to settle before recording the result. Source: implemented concurrency/observability design in `scripts/aws/v1/definitions.py`; `docs/execution/aws/v2/lambda-short-encodes.md`.

```sh
aws cloudwatch get-metric-statistics --namespace AWS/Lambda --metric-name ConcurrentExecutions --dimensions "Name=FunctionName,Value=$DEMO_SHORT_FUNCTION" --start-time "$DEMO_BURST_START" --end-time "$DEMO_BURST_END" --period 60 --statistics Maximum --query 'sort_by(Datapoints,&Timestamp)[].{time:Timestamp,maximum:Maximum}' --output table
```

- **Acceptance/edit:** show actual Fargate **0→3→0**, job completion and timestamps; annotate trimmed waiting. If the burst never overlaps at three, it does not prove that sequence—repeat a planned take with more queued standard work or use the labelled historical receipt. Show Lambda observed peak separately from configured **2** cap; never invent a peak when the sample is absent/only one. Historical retained proof: `docs/results/actual-vs-target.md`, LV-7; `docs/execution/aws/v1/evidence/v2live-verify-20261019/scaling-and-backlog.json`.
- **Tool selection:** `scripts/aws/v1/proof/unattended.py` is the real launcher proof harness, but needs a matching prior cap-three `capacity` receipt, session state and IAM attestation. It is not a drop-in current-live recording command. `short_encode.py` submits jobs serially; its five-job receipt compares latency/cost, **not concurrent Lambda scaling**. Prefer Publisher burst + read-only observations for footage. Sources: `scripts/aws/v1/proof/unattended.py`, `baseline` / `preflight`; `scripts/aws/v1/proof/short_encode.py`, `lambda_arm`.
- **Result inset, clearly historical:** V1 speedup **1.449× at two** versus target **1.6×** (FAIL), **2.347× at three** versus **2.1×** (PASS), only **six clips / one run per cap**. Short lane median queue wait **0.26 s** versus padded Fargate **32.6 s**, **five jobs per arm**; warm submit-to-done **45.2 s**, cold **92.0 s**, not a sub-20-second end-to-end result. Sources: `docs/results/actual-vs-target.md`; `docs/results/engineering-20261021/short-lane-sl1021.json`.
- **Cost:** assuming **three Fargate tasks billed 60–300 s each**, compute **$0.0064–$0.0321**; a four-short-job burst references **$0.0012**; planned **10-minute** shared DB time **$0.033–$0.133**, excluding added requests/storage/transfer. Sources: C0 / `docs/execution/aws/v1/cost-inputs.json`; `scripts/aws/v1/proof/short_encode.py`, minimum billing; `docs/results/engineering-20261021/short-lane-sl1021.json`. Historical task durations are not a guarantee for the new take.
- **Timing/cut/narration:** D4 row; scale footage earns the auto-scaling bullet, while the result inset preserves measured limits.

### D5 — Scripted performance with an existing tool

- **Chosen tool:** `scripts/aws/v1/proof/generator.py`, standard-library HTTP/TLS workload generator. It can run directly on the recorder Mac with environment inputs; its harness wrapper `scripts/aws/v1/proof/latency.py` normally ships it into Fargate and judges eligibility. No new load-test implementation is required.
- **Important prerequisite:** current persistent Gateway default is **20 rps / burst 50**; canonical harness refuses less than **50 rps / burst 100** before side effects. Do **not** run the canonical fifty-user test against the default stage and call throttling service latency. Sources: `docs/execution/aws/v1/deploy-runbook.md`, persistent defaults; `scripts/aws/v1/proof/latency.py`, `require_load_edge`.
- **Recommended recording workload:** **10 virtual status users for 60 s**, **5 s** warmup, **5 concurrent login requests**, **5 s** for each supplementary route; no competing submissions. This is `[PLAN]` small-load scripted demonstration under the retained default rate, not a repeat of the proposal workload. Source for configurable inputs: `scripts/aws/v1/proof/generator.py`, `main`.
- **Exact future command:** print only the result marker; the generator's compressed sample chunks need not fill the screen. It creates a disposable account through the public API; it is not read-only traffic and was not run by this research.

```sh
DC2_BASE_URL='https://nqxf2hclhi.execute-api.ap-southeast-1.amazonaws.com' DC2_USERS=10 DC2_SECONDS=60 DC2_WARMUP=5 DC2_OTHER_SECONDS=5 DC2_LOGINS=5 python3 -m scripts.aws.v1.proof.generator | sed -n 's/^DC2-RESULT //p' | jq '{ok,users,python,windows,routes}'
```

- **On-screen:** command/workload; actual interval; `routes.status.count`, `p90_ms`, `errors`, other-route summaries and `routes.login`; explicitly calculate error rate as `errors/count` including every failure. `ok:true` means workload execution completed, **not** a passed latency target/eligibility verdict. Warmup excluded from timed route summaries. Sources: `scripts/aws/v1/proof/generator.py`, `describe` / `run`; `scripts/aws/v1/proof/latency.py`, `judge`.
- **Historical comparison card:** status **p90 58.2 ms / 9,000 requests / 0 errors**, **50 virtual users / 180 s**, target **≤700 ms / <1% errors**; login **p90 178 ms / 20 samples**, target **<2 s**. In-region Fargate → Gateway, earlier V1, not CloudFront browser/user latency. Source: `docs/results/actual-vs-target.md`, PF-1/PF-3; `docs/execution/aws/v1/evidence/cloud-proof-r1017b.json`, `#66.generator`.
- **Canonical full tool, only if separately planning the original experiment:** `python -m scripts.aws.v1.evidence latency --profile "$DEMO_AWS_PROFILE" --region ap-southeast-1 --account "$DEMO_ACCOUNT" --state-dir "$DEMO_STATE" --run-id "$DEMO_RUN" --only generator`. Requires compatible private operator state/session and already sufficient throttle; do not change the live throttle just for this clip. The runbook's historical session-opening recipe is not the current recording procedure. Sources: `scripts/aws/v1/evidence.py`; `scripts/aws/v1/proof/latency.py`; `docs/execution/aws/v1/deploy-runbook.md`, “Cloud proof in order”.
- **Cost:** Mac generator has no Fargate charge; planned **5-minute** shared DB compute **$0.017–$0.067** plus API/Lambda/authorizer/I/O charges. The proposed status count would be **600** only if every planned round occurs; show actual count. Request-rate/cost inputs: `scripts/aws/v1/proof/generator.py`; C0 / `docs/execution/aws/v1/cost-inputs.json`.
- **Timing/cut/narration:** D5 row; show actual run completion after a labelled edit, not a fake accelerated terminal countdown.

### D6 — CI + CD execution and security evidence

- **Primary capture:** show real completed executions of the latest green pair, then drill into their checks using authenticated `gh`; preserve run IDs, dates, source and step outcomes. This meets the guideline's **show/run** wording without starting a new deployment for footage. Sources: original guideline §6(b); current-run snapshot above; `.github/workflows/ci.yml`; `.github/workflows/cd.yml`.
- **Exact read-only capture commands:** `gh` only; no `--web`, API call, connector or browser navigation to GitHub.

```sh
gh run view 39733112331 --json headSha,conclusion,event,jobs --jq '{sha:.headSha,event,conclusion,jobs:[.jobs[]|{name,conclusion}]}'
gh run view 39733859422 --json headSha,conclusion,event,jobs --jq '{sha:.headSha,event,conclusion,jobs:[.jobs[]|{name,conclusion,steps:[.steps[]|select(.name=="Deploy" or .name=="Smoke test, upload to playback")|{name,conclusion}]}]}'
gh run view 39733112331 --log | rg 'Publish .*code scanning|Publish .*findings|Full verification|fixable|Secret scan'
gh run view 39733859422 --log | rg 'CI admission|public-smoke|Upload to playback|Releasing|RETAINED_FIXABLE'
```

- **Shot sequence:** CI exact SHA + Full verification → owner/image/coverage/security job rows → CD same source + admission → deploy + upload smoke → optional historical `release-processing.json` restored outcome → supplied Security-tab still/clip with actual capture date. Do not imply a no-change stack update released every service. Sources: `scripts/ci/cd.sh`; `.github/workflows/cd.yml`; `docs/execution/aws/v1/evidence/v2live-verify-20261019/cd-39271754470-bad-candidate-rollback/release-processing.json`.
- **Security-tab prerequisite:** this research has **not opened GitHub's Security tab**. Under the gh-only access rule, use a team-supplied human screenshot/recording of **Security → Code scanning**, Tools/categories and one documented triage reason; label its own date. If that footage is unavailable, show the local SARIF publication table plus `gh` job/log evidence and mark literal tab footage missing. No claim of current alert counts. Source policy: `docs/ci/policy.md`, “Publishing to the Security tab” / triage; user GitHub access instruction.
- **If fresh execution footage is wanted later:** record a separately approved ordinary Main delivery from start to finish off-clock, then edit it to the same D6 budget. No source change, CI/CD rerun, manual dispatch, bad-candidate release or merge is needed/authorized by this research. Preserve the existing freeze. Workflow triggers/procedures: `.github/workflows/ci.yml`; `.github/workflows/cd.yml`.
- **Cost:** viewing `gh` results and supplied images is **$0 incremental AWS**. A separately commissioned new CD execution would add shared awake DB time, possible migration tasks and a smoke encode; do not confuse that raw execution time with the short playback budget. Pricing basis if scheduled: C0 / `docs/execution/aws/v1/cost-inputs.json`.
- **Timing/cut/narration:** D6 row; retain evidence of an executed pipeline, rather than spending the clip reading YAML.

### Demo questions worth rehearsing

| Question | Crisp answer | Evidence |
|---|---|---|
| Is this live? | All clips are prerecorded real actions, labelled with capture/environment/source; edited waits preserve actual elapsed time. | `ROAD-TO-PRESENTATION.md`, Stage 5; #254 via `gh issue view 254`. |
| Is the scaling an ECS service autoscaler? | No. A SQL-fenced launcher starts finite tasks on work publication with a scheduled safety net; tasks exit when idle. | `docs/execution/aws/v1/deploy-runbook.md`; `processing/launcher.py`; `processing/launcher_trigger.py`. |
| Why does a short clip not prove Fargate scaling now? | Current short sources route to Lambda; standard-lane footage deliberately exceeds the dispatch size bound. | `processing/short_lane.py`; `docs/execution/aws/v2/lambda-short-encodes.md`. |
| Did Lambda solve the latency target? | It improved queue wait, not total latency; the retained cold-median keep rule failed and end-to-end delay remains unattributed. | `docs/results/engineering-20261021/short-lane-sl1021.json`; `docs/results/actual-vs-target.md`, LV-S1–LV-S4. |
| What proves concurrent Lambda execution? | The burst's actual ConcurrentExecutions observations; mapping configuration only proves the limit. Sequential short-lane benchmark does not prove concurrency. | `scripts/aws/v1/proof/short_encode.py`; `docs/execution/aws/v2/lambda-short-encodes.md`; D4 recording prerequisites. |
| Is the smaller recorded load a repeat of the original benchmark? | No; same tool, different workload and network path. Its output gets its own label and verdict; original in-region numbers remain historical. | `scripts/aws/v1/proof/generator.py`; `docs/results/actual-vs-target.md`. |
| How can a producer integrate without privileged access? | Public OpenAPI/cookie flow; direct S3 upload grant; no service imports or database credentials in Publisher. | `publisher/README.md`; `tests/publisher/test_publisher.py`. |
| What does the authorization clip establish? | Positive owner control and foreign/anonymous denial for the shown routes; it does not repeat the full historical security-negative campaign. | `docs/execution/aws/v1/evidence/s229-live-results.md`; D3 scope. |

### macOS tooling and shot-list order

| Tool / operation | Suggested use | Reference / limit |
|---|---|---|
| macOS Screenshot / QuickTime Player | **Shift–Command–5**, record selected region; microphone if desired; trim the resulting take. Prefer silent footage with later narration when that simplifies edits. | [Apple: record the screen](https://support.apple.com/en-gb/102618), [Apple: Screenshot and trimming](https://support.apple.com/en-gb/guide/mac-help/mh26782/mac); checked 22 Oct 2026. |
| OBS Studio | Capture browser/terminal scenes and separate microphone/application audio; useful for the playback demonstration and later narration. | [OBS macOS audio guide](https://obsproject.com/kb/macos-desktop-audio-capture-guide): macOS Audio Capture on supported OBS/macOS; verify the installed combination. Do not assume QuickTime's microphone setting captures system playback audio. |
| Existing editor + FFmpeg/FFprobe | Trim annotated waits, add source/title/elapsed captions, inspect final durations; use software the team already knows. Proposed export: **1920×1080, 30 fps, H.264 MP4**, readable terminal font and cropped browser. | Export settings are `[PLAN]` presentation choices, not system measurements; `README.md` already requires FFmpeg/FFprobe. |
| Playback package | Keep raw captures separate from sanitized final clips; provide local offline files and durable team-accessible copies with index, version/date/duration; second member checks playback/audio and access. | #254 acceptance via `gh issue view 254`; `ROAD-TO-PRESENTATION.md`, Stages 5–7. Existing private captures/sharing remain unverified. |

- **Capture order, separate from playback order:** prepare fixtures/accounts/jars and identity cards → warm both domains → D1 browser journey → D2 Publisher → D3 ownership → D5 small load → finish/drain other work → D4 Fargate zero/peak/zero → D4 short burst/metrics → D6 `gh` evidence and supplied human Security-tab footage → narration/edit/export → timed local playback check. Sequential workload capture prevents performance/scaling measurements from contaminating each other.
- **Playback order:** D1 → D2 → D3 → D4 → D5 → D6; six clips, using the timing table. Rehearsal on **25 Oct**, recordings **24–25 Oct**, per `ROAD-TO-PRESENTATION.md`.
- **Capture framing:** use a clean browser profile/desktop; hide notifications, credential prompts, private-state windows and signed URLs; narrate sign-in while password entry is cut. These are the concrete #254 artifact requirements, not a live-demo contingency plan.
- **Cut ladder:** remove waits/setup first → shorten secondary routes and repeated CLI results → remove optional rollback inset → shorten second playback format. Keep significant user journey, independent producer, ownership, both scaling lanes, actual scripted output and executed CI/CD evidence.
- **Verification command, future editor:** `ffprobe -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 CLIP.mp4`; sum actual final clip durations and reserve hand-offs within the **480 s** limit from `ROAD-TO-PRESENTATION.md`. Proposed clip labels/caps are the D1–D6 table, not timing claims about the service.

## Guideline coverage crosswalk — every §5–§6 bullet

| Official guideline bullet | Slide / clip coverage | Required visible proof / qualification | Source |
|---|---|---|---|
| **5(a): strategy to manage source code and artifacts** | S5.1; S5.3 backup | Monorepo/branch flow; owner image/repository units; source/config/digest/version/alias distinctions; retained rollback assets; worker-image short lane | `project-documentation/final-report/src/50-devops.md`; `deploy/v1/check_runtime.py`; `docs/execution/aws/v2/lambda-short-encodes.md`. |
| **5(b): DevOps pipeline and procedures** | S5.2–S5.3; D6 | CI selection/full gates, security disposition, exact-source OIDC CD, release plan, scans, promotion/restore/adoption, both public-smoke boundaries and database wake | `docs/ci/policy.md`; `.github/workflows/ci.yml`; `.github/workflows/cd.yml`; `scripts/ci/cd.sh`; `scripts/aws/v1/public_smoke.py`. |
| **5(c): technical findings and issues encountered** | S5.4–S5.5; backup war-story table | Dated failed runs → diagnosis → tested fixes → successful run; retained-image deadlock, cold/split DBs, memory/account ceiling, update after rollback, coverage timeout | `docs/results/engineering-20261021/delivery-c7c489c.json`; `docs/execution/aws/v2/lambda-short-encodes.md`; `docs/ci/policy.md`; read-only Actions snapshot in this file. |
| **6(a): significant use cases** | D1–D3; D4/D6 for operator paths | Sign-in/upload/process/status/playback; independent Publisher; owner positive/foreign/anonymous controls. UC-1–UC-3, UC-5 primary; UC-6/UC-7 via evidence; UC-4 optional rather than invented | `docs/architecture/use-case-design.md`; `publisher/README.md`; `docs/execution/aws/v1/evidence/s229-live-results.md`. |
| **6(b): important quality attributes — scalability (auto-scaling example)** | D4 | Actual automatic Fargate 0→3→0; no manual task starts; Lambda mapping cap plus real burst concurrency observation; distinguish capacity from speedup | `scripts/aws/v1/proof/unattended.py`; `docs/execution/aws/v2/lambda-short-encodes.md`; `docs/results/actual-vs-target.md`. |
| **6(b): important quality attributes — performance (scripted test example)** | D5 | Existing generator command and actual summary; workload, path, p90/errors/count/duration; historical full benchmark labelled separately | `scripts/aws/v1/proof/generator.py`; `scripts/aws/v1/proof/latency.py`; `docs/results/actual-vs-target.md`. |
| **6(b): important quality attributes — maintainability (show/run DevOps pipeline example)** | D6; S5.2–S5.3 | Executed CI + CD for matching source, owner/image checks, deployment smoke, SARIF publication; supplied human Security-tab capture or explicit missing-footage label under gh-only rule | `.github/workflows/ci.yml`; `.github/workflows/cd.yml`; `docs/ci/policy.md`; read-only Actions snapshot in this file. |
