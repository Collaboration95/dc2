# W5 independent verification

**Outcome: PASS after corrections.** Reviewed Main `76282d3b5a141f6548056f2506f9d5aff0742692` in `dc2-rescue` on 26 October 2026. The original author's conclusions were checked against source and fresh authenticated GitHub reads. No application, infrastructure, workflow, repository-settings or integrated-deck changes were made. No commit was made.

## Findings and fixes

### W5-R1 — High — The activity diagrams placed image scanning and DAST after merge

- **Location:** `slides/W5.html`, sections `s34` and `s68`; `site/assets/uml/W5-pipeline-main.puml` and `W5-pipeline-full.puml`.
- **Finding:** The original diagrams put Ruff/npm/gitleaks under PR CI, then crossed a `merge / repeat full CI` edge into image scanning and DAST under “Full verification on Main”. This visually contradicted the real full-PR policy and obscured the assessor's requested pipeline view.
- **Evidence:** [PR-base selection](https://github.com/Collaboration95/dc2/blob/76282d3/scripts/ci/policy.py#L385) selects full for PRs except the default `dev/closeout` path-selection case; [full selection](https://github.com/Collaboration95/dc2/blob/76282d3/scripts/ci/policy.py#L352) enables all lanes. [DAST selection](https://github.com/Collaboration95/dc2/blob/76282d3/.github/workflows/ci.yml#L627), [image selection](https://github.com/Collaboration95/dc2/blob/76282d3/.github/workflows/ci.yml#L638) and [Full verification dependencies](https://github.com/Collaboration95/dc2/blob/76282d3/.github/workflows/ci.yml#L596) are part of that CI run.
- **Fix applied:** Both CI figures now put the relevant security jobs in one full-verification partition with a matching fork/join. The aggregate receives completed job dispositions and still requires tests. The figures explicitly describe full policy; `s33` retains the dev/full selection boundary. Main push repeats full CI. The main-talk `s34` shows SAST and DAST together at a glance.

### W5-R2 — Medium — Independent-workflow and continuation notation was ambiguous

- **Location:** Both original W5 activity figures; `s34`/`s68` notes and the report figure description.
- **Finding:** CodeQL appeared as a PR activity branch without explicit completion, while `A` was drawn as an ordinary rounded action but described as a continuation connector between separately rendered diagrams. The figure boundary could be mistaken for a connected workflow. Rendering successfully did not establish that intended meaning.
- **Evidence:** CodeQL is absent from the [custom aggregate's dependencies](https://github.com/Collaboration95/dc2/blob/76282d3/.github/workflows/ci.yml#L601). The live default-setup response is `state=configured`, with a weekly schedule. [The dated CodeQL run](https://github.com/Collaboration95/dc2/actions/runs/40189407647) is independent of the custom CI runs.
- **Fix applied:** Removed CodeQL's control-flow branch and the `A` pseudo-connectors. CodeQL remains visible as independent SAST in the main caption, inventory and notes. Every final figure has an initial and final node. CI fork/join bars have five matching branches. The separate release figure has a guarded promotion edge and a yes/no promotion decision; AWS operations occupy their own partition. Restore is an attempt with recorded outcomes, rather than a guaranteed successful recovery. The figures abstract grouped jobs, not every Actions scheduling dependency.

### W5-R3 — Medium — The generic CD-admission claim excluded a supported manual path

- **Location:** `s35` admission row, `s33` speaker notes, original release panels, and the Continuous Delivery draft in `report-notes/W5.md`.
- **Finding:** “Successful Main push CI” was presented as the general admission requirement. That is the automatic trigger boundary, but manual deploy/release can also use an exact-source full CI dispatch.
- **Evidence:** [Admission validation](https://github.com/Collaboration95/dc2/blob/76282d3/scripts/ci/cd_gate.py#L16) accepts Main push or full dispatch and requires a successful Full verification result. [Manual selection](https://github.com/Collaboration95/dc2/blob/76282d3/scripts/ci/cd_gate.py#L87) selects the latest eligible run; [automatic provenance](https://github.com/Collaboration95/dc2/blob/76282d3/scripts/ci/cd_gate.py#L102) requires the triggering Main push. Scheduled CI and PR runs do not qualify.
- **Fix applied:** Split automatic and manual admission in the table, release figure/caption and report draft. Preserved the same-repository/source and automatic Main-push restrictions. No manual dispatch was performed.

### W5-R4 — Medium — The baseline exception needed an explicit Trivy/ECR boundary

- **Location:** `s35`, `s37`, `w5-extra-scans`, the release figure, and report inventory/CD draft.
- **Finding:** Generic “retained baseline exception” and “recorded fixable findings” wording could imply that the exception also waived registry findings. ECR has its own stricter matching/acceptance policy.
- **Evidence:** [Baseline/kept-image handling](https://github.com/Collaboration95/dc2/blob/76282d3/scripts/ci/cd.sh#L471) permits retained Trivy findings only on replaced rollback targets. [Image-set proof](https://github.com/Collaboration95/dc2/blob/76282d3/scripts/aws/v1/proof/release_plan.py#L229) still calls ECR validation for every role. [ECR validation](https://github.com/Collaboration95/dc2/blob/76282d3/scripts/aws/v1/artifacts.py#L59) requires COMPLETE, the matching digest, valid counts/pagination, and no HIGH/CRITICAL findings outside the explicit acceptance list. It does not apply Trivy's fixability test.
- **Fix applied:** Named `RETAINED_FIXABLE` as a Trivy-only exception. Added ECR COMPLETE/no-unaccepted-HIGH/CRITICAL requirements. Candidate and kept-image Trivy identity/completeness/finding policy remains strict. No claim of zero vulnerabilities or a newly verified release was added.

### W5-R5 — Medium — The full pipeline compressed too much detail into one figure

- **Location:** Original `s68` composite and figure-generation instructions; secondary effect on `s34`.
- **Finding:** The five-partition, two-panel backup visibly reduced activity and guard labels at 1280×720. Splitting the panels within the same image did not provide enough space for the full detail.
- **Evidence:** Before previews are retained as `slides/W5-qa/review-before-W5-s34.png` and `review-before-W5-s68.png`. Final slide PNGs and geometry checks are recorded in `verification.json`.
- **Fix applied:** Main CI, detailed full CI and CD owner release now have three separate directly rendered figures. `s68` shows the detailed CI view; new backup `w5-release` carries CD. Replaced the SVG compositor with direct PlantUML rendering and updated the report/integration map. Inspected all ten final slide canvases at 1280×720, including headings, table wrapping, diagram labels, partitions, guards, legends and footers. All final renders have no detected body overflow and all embedded figures load.

### W5-R6 — Low — The scanner inventory omitted standalone manual triggers

- **Location:** `s36`, V1-image and ZAP rows; report V1-image trigger row.
- **Finding:** The original shorthand did not explicitly expose standalone V1 image dispatch or standalone manual DAST.
- **Evidence:** [V1 dispatch inputs](https://github.com/Collaboration95/dc2/blob/76282d3/.github/workflows/v1.yml#L28) make images an explicit choice; [DAST triggers](https://github.com/Collaboration95/dc2/blob/76282d3/.github/workflows/dast.yml#L3) include workflow call, exact-SHA dispatch and weekly scheduling. In ordinary CI, lane selection still controls these jobs.
- **Fix applied:** Added `Manual V1: images=true` and manual/weekly DAST. Kept the Media/Processing/Worker identities visible in the inventory's explanatory line. No new hosted execution claim was made for a manual run.

### W5-R7 — Low — “Auth lifecycle” was broader than the actual exclusion

- **Location:** `w5-dast`, “Excluded from ZAP active scan”.
- **Finding:** The shorthand could be read as excluding all authentication routes, although the route table includes `GET /api/media/auth/me`.
- **Evidence:** [The exclusion predicate](https://github.com/Collaboration95/dc2/blob/76282d3/scripts/dev/v1_dast.py#L52) excludes Media auth lifecycle POST operations, not the imported GET identity route.
- **Fix applied:** Changed the visible exclusion to “Auth lifecycle POST”. The seven-route table and separate fixture controls remain intact.

### W5-R8 — Low, requested editorial improvement — Lead the headline with implemented controls

- **Location:** `s34` headline.
- **Finding:** “Full CI requires checks; Main has no merge protection” was truthful but led with a vague aggregate claim and did not immediately answer the SAST/DAST feedback.
- **Evidence:** Implemented [Ruff S](https://github.com/Collaboration95/dc2/blob/76282d3/scripts/dev/checks.py#L206), [local ZAP](https://github.com/Collaboration95/dc2/blob/76282d3/.github/workflows/ci.yml#L627), the full aggregate, and the dated live settings receipt below.
- **Fix applied:** Applied **“Full CI runs SAST and DAST. Main is unprotected”**. The main slide still states the limitation clearly and links the mixed dated CI outcomes.

## Coverage of every slide and figure

| Section / asset | Final verification |
|---|---|
| `s33` | PR base, conservative full escalation, dev exclusions, Main/full/weekly triggers, automatic-CD boundary and current Main setting agree with policy. Notes now distinguish manual CD. |
| `s34` / `W5-pipeline-main` | Main-talk SAST/DAST visibility, five correct categories, full-CI sequencing, independent CodeQL, aggregate scope, dated outcomes and unprotected-Main limitation pass after fixes. |
| `s35` | Automatic/manual admission, source SHA versus image bytes, Trivy/ECR identity/policy, owner smoke/restore attempt and separate upload-to-playback smoke checked. Artifact retention is 60 days. |
| `s36` | Ruff S and CodeQL are SAST; npm audit is SCA; gitleaks is secrets; Trivy is image scanning; ZAP is DAST. Triggers, policy, log/JSON/SARIF locations, fork restrictions, unfixed JSON and Sonar NOT_RUN checked. |
| `w5-dast` | Exact seven GET routes, disposable HTTPS target, V1 handlers/authorizer, PostgreSQL/Moto, fixture ownership/auth checks, cookie scope, exclusions, request cap, execution versus findings, 16 findings and cleanup checked. Cloud DAST stays NOT_RUN. |
| `s37` | Replaced restore-target versus kept/new image roles checked; Trivy exception now explicitly separated from ECR validation. |
| `s66` | All three run dates, events, exact SHAs and conclusions re-read. Historical 22 Oct CodeQL triage and accepted-unfixed FFmpeg rationale verified as statements in pinned report/acceptance files, not current alert or remediation audits. |
| `w5-extra-scans` | Manual selected-owner preparation, CD-only release scans, evidence locations and missing execution receipts correctly bounded. Sonar is conditional/advisory and skipped in dated runs. No Semgrep, standalone Bandit or pip-audit invocation found in inspected workflows/entry points. |
| `s68` / `W5-pipeline-full` | Full tests/coverage/security requirements, separate inherited/V1 scope and V1 identity validation, five-branch fork/join, initial/final nodes and narrower Dev aggregate checked. |
| `w5-release` / `W5-pipeline-release` | New readable backup with correct CD/AWS partitions, admission/image gate, guarded promotion, yes/no outcome, restore/abandon disposition and distinct later smoke. Source-verified behavior, not a new CD or AWS receipt. |

The category terminology agrees with the [OWASP DevSecOps Guideline](https://owasp.org/www-project-devsecops-guideline/), which distinguishes credential scanning, SCA, SAST and DAST. The classification here follows each actual invocation. An `upload-sarif` step is publication, not evidence that CodeQL analysis executed. Trivy image scanning is not labelled SAST, and Ruff's Bandit-derived S rules are not represented as a standalone Bandit job.

## Independent GitHub evidence

All GitHub access used authenticated `gh` CLI, read-only. Commands included `gh run view <id> --repo Collaboration95/dc2 --json ...`, targeted `--log` reads and `gh api` GETs. No workflow was triggered or rerun and no repository state was changed.

| Run | Created UTC | Source | Verified result |
|---|---|---|---|
| [CI 39931072197](https://github.com/Collaboration95/dc2/actions/runs/39931072197) | 23 Oct 09:19:53 | `76282d3…` | Main push; success. Local ZAP: 7 routes, 16 findings, 146 out-of-scope requests blocked; runtime/private-file cleanup PASS. |
| [CI 40174362164](https://github.com/Collaboration95/dc2/actions/runs/40174362164) | 25 Oct 07:51:27 | `76282d3…` | Schedule; inherited app/processing Trivy and Full verification failed. V1 image and ZAP jobs succeeded. ZAP has the same route/finding/blocked counts and cleanup PASS. |
| [CodeQL 40189407647](https://github.com/Collaboration95/dc2/actions/runs/40189407647) | 25 Oct 11:34:06 | `76282d3…` | Independent dynamic workflow; Python, JavaScript/TypeScript and Actions analyses succeeded. |

Both inspected CI runs published ZAP SARIF successfully; both Sonar analysis jobs were skipped. This is execution/publication evidence, not a clean-alert claim. The individual cause of the inherited Trivy failures was not diagnosed.

Current-settings GETs, dated 26 Oct:

- `repos/Collaboration95/dc2/branches/Main`: `protected=false`.
- `repos/Collaboration95/dc2/branches/Main/protection`: HTTP 404, `Branch not protected`.
- `repos/Collaboration95/dc2/rules/branches/Main`: `[]`, meaning no effective branch rules returned for Main; this is not a claim that no inactive rulesets exist anywhere.
- `repos/Collaboration95/dc2/code-scanning/default-setup`: `state=configured`, `schedule=weekly`, Python/JavaScript/TypeScript/Actions languages. A configured scan is distinct from an enforced merge check.

Dated settings and exact run/job/step evidence are retained in `slides/W5-qa/review-settings.json` and `review-runs.json`.

## Validation, scope and remaining limits

- Read all six workflow files, CI policy, Ruff security invocation, full DAST harness and the relevant release/registry proof code. Checked 147 pinned source links for existing paths/line anchors and report reference definitions.
- Independently matched the seven displayed routes against the committed OpenAPI documents and reviewed exclusions; operation counts remain Media 15 and Processing 5. Auth-negative fixture requests do not expand active-scan coverage.
- Re-rendered all three `.puml` sources with `java -Djava.awt.headless=true -jar ~/dc2-tools/plantuml-1.2026.9.jar -tsvg <file>`, and PNGs with the specified resvg CLI. Each source produces one final SVG directly.
- Rendered and visually inspected all ten final 1280×720 PNG canvases. `html_preview` uses a 1280×800 browser viewport and captures the fixed 1280×720 slide canvas; this distinction is recorded honestly in `verification.json`. The original collaborative-browser snapshot step twice timed out with `Preview automation snapshot timed out after 15000ms`; native headless HTML rendering completed the QA.
- Verified source/workflow and `site/deck.html` hashes remain identical to the review's starting values, and HEAD remains `76282d3`. The integrated deck already had other changes on entry; this review preserved them. Other workstreams were not edited.
- No new application/security scan, AWS inventory, CD/preparation run or deployed cloud-edge DAST was performed. No current alert counts were queried. Historical triage/acceptance records remain dated. CODE backlog items remain proposals.

**Short summary:** Corrected CI stage placement, activity-flow boundaries, manual-CD admission, Trivy/ECR exception scope, trigger/exclusion wording and the main headline. The handoff now contains ten sections: replacements for 33–37, 66 and 68, plus DAST detail, scan-inventory backup and a new release-activity backup. Three figures and all ten final PNGs pass the stated presentation checks. No confirmed defect remains open within this review scope.
