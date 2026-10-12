VERDICT: PASS
ISSUE: #9 (F1), #10 (F2), #11 (F3); parent #2
PR: [#26](https://github.com/Collaboration95/dc2/pull/26), branch `wave/01-foundation`

RECORD STATUS: Attribution/history correction only; cache fix and re-review pending.
The verdict line records the initial PASS. This correction issues no
new verdict and does not assess the patch currently in flight.

Independent grouped foundation review, 13 October 2026 (Singapore).
Base: `Main`, `6ea8b9beca5235b75ad7a7552903b1267113e43a`.
Reviewed head and coordinator-tested commit:
`3ed9d03d3c9e982dff0346c127ad5c5e2dcd6e1d`.
The coordinator supplied the tested-commit identity; the reviewer inspected the
saved evidence without rerunning setup, tests, builds or infrastructure.
A subsequent review-report-only commit does not change this reviewed code.

Foundation functionality, local verification evidence and all remote checks pass
on the reviewed SHA. The review sequence was initial PASS, followed by the late
R1 REVISE during PR #26's merge, then the coordinator reopening #10/#2 and choosing
the cache correction. The assessment that no cache optimization was needed under
80/20 scope came from the coordinator, not the user. The reviewer incorrectly
recorded it as a user instruction or waiver; the user never gave that instruction.
There is no cache waiver. R1 remains pending review of the new code and actual
warm CI evidence. The coordinator reports that the correction is implemented
locally and will supply the new SHA for bounded re-review.

ACCEPTANCE:

| Issue gate | Assessment and evidence |
| --- | --- |
| F1 — locked setup and secret preservation | pass — `setup.py:13–21,55–67` uses locked uv/npm installation and exclusive .env creation. The tools report records two successful setup runs, unchanged configured .env contents/permissions and tracked-tree cleanliness. |
| F1 — root commands and diagnostics | pass — Make provides help/setup/doctor/lint/test/clean; doctor diagnoses prerequisites and later-wave targets fail explicitly. Coordinator setup/doctor-infra/lint and tools help/clean evidence cover the current interfaces. |
| F1 — ignored, local worktree state | pass — existing ignore rules cover .worktrees/.cache/.local/.venv/artifacts/secrets; `common.py:19–31` scopes caches and environments to the checkout. No command requires the former submodule directory. |
| F2 — fast, independent and reproducible tier | pass — service environment is stripped, real Python socket/DNS access is guarded, integration/e2e paths and live frontend tests are excluded. Three integrated runs each pass 458 Python and 124 frontend tests in 4.79s, 4.32s and 3.97s of recorded test-command time. Linux Python/frontend jobs also passed within their three-minute budgets. |
| F2 — real integration and failure visibility | pass — explicit resource configuration, bounded command/readiness waits and skipped-test rejection prevent disabled integration from counting as success. The reports retain an actual unavailable-database failure. Real Processing tests pass locally and remotely; full inherited integration also passed remotely. Full product e2e belongs to later waves. |
| F2 — separate package and frontend coverage | pass — current matching fast/real-DB fragments give app 86.77% combined / 78.70% raw branches and Processing 86.69% / 63.64%. All 38 app and 9 Processing production Python files are present. Frontend statements/branches/functions/lines are 99.44/95.50/96.82/99.44%, respectively. New named packages enter lint/coverage selection; their product lanes still own integration/image selection. |
| F2 — stable aggregate CI and separate cached expensive work | R1 resolution pending — Fast checks/Integration checks run without path filters, use always-running aggregates and reject failed/skipped dependencies; both aggregates and cross-runner combined coverage passed remotely. Other image jobs import/export GHA layers. Browser trust caches source/browser files and rebuilds MinIO on fresh runners; the full cold job passed in 3m49s. The previous acceptance attribution was incorrect; the cache fix is in flight and has not been re-reviewed. |
| F2 — inherited live-image scan policy | pass — both current app and Processing image scans passed on the reviewed SHA, with exit 1 for fixable HIGH/CRITICAL findings. Shared legacy API/worker image needs one scan. Guards require future Media/distinct worker selection; no future image acceptance is claimed. |
| F3 — fresh services, separate stores and retained data | pass — scoped Compose provides separate databases/roles, Redis and private MinIO, with migration/bootstrap readiness dependencies. The runtime report records fresh boot, real intake, down/up persistence and another stack remaining usable. Down has no volume deletion. |
| F3 — explicitly trusted TLS | pass — generated CA/server identity, SANs and AKI/SKI support strict verification. Host smoke, container signed-object smoke and real Firefox evidence use explicit CA trust. No certificate-error bypass or system trust modification appears in the changed code. Secure-cookie login remains V1. |
| F3 — usable source/playback topology and private secrets | pass — public signing retains localhost:port, raw bucket paths and Host/query signatures; internal storage uses minio:9000. Real signed source/output GETs and anonymous/principal denials passed. Private run configuration is ignored and public state excludes credentials. Product worker/source-renewal wiring remains later-wave work. |
| F3 — worktree isolation and resource preflight | pass — checkout hash plus run ID separates project/image/bucket/queue identities; generated ports/config and Compose volumes are scoped. Configuration tests cover distinct worktrees, and two live stacks passed smoke with distinct ports/volumes. Up reports selected Docker CPU/memory; overrides remain subprocess-local. |
| F3 — pinned fresh-cache MinIO | pass — immutable source fetch uses authenticated gh, safe archive extraction and a commit marker; build bases are digest-pinned. Runtime lane records a fresh source/image-cache build and cache reuse. Docker no longer fetches GitHub itself. |
| F3 — bounded capacity feasibility | pass — coordinator records project-local Lima 8 CPUs/8 GiB configuration, actual usable memory and cgroup v2 hard quota 200000/100000. Docker Desktop remains unchanged. This establishes feasibility, not scaling throughput or actual future worker quotas. |
| F3 — real Firefox trust controls | pass — pinned Playwright/Firefox, temporary NSS profile and certutil CA import retain verification. Saved local artifact records trusted navigation, unrelated-CA rejection and live https://localhost:54440/health. The documented policy-to-NSS correction is within the approved foundation gate. |

FINDINGS:

- R1 [P2] disposition — open; cache fix in flight, 13 October 2026.
  `.github/workflows/ci.yml:240–253` and
  `scripts/dev/runtime.py:272–274,349` restore source but do not persist MinIO
  build layers for the browser job. The actual compilation took 130.5s; the
  complete cold browser job passed in 3m49s, with all trust/smoke checks intact.
  After the initial PASS, the late R1 REVISE requested persistent build-layer
  caching or verified cached image reuse, with warm-run evidence. It arrived
  during PR #26's merge; the coordinator reopened #10/#2 and chose the correction.
  The report's intervening user-waiver attribution was false: the timing/80/20
  assessment was the coordinator's message, not a user instruction. The parent
  reports the correction is implemented locally and will supply a new SHA and
  actual warm CI evidence for bounded re-review. R1 remains pending; this history
  correction neither closes it nor issues a new verdict.

CHECKS:

- Read AGENTS.md, the review-work skill, worklog, execution plan/decisions,
  planning re-review, all three foundation result reports and the complete
  `6ea8b9b...3ed9d03` changes. Inspected all lock records/artifact hashes.
- Authenticated gh reads confirmed #9/#10/#11, parent #2 and completed dependency
  #8. PR #26 opened during review; its head matches the reviewed SHA.
- Read-only AST, execution JSON, lock dependency/hash and diff-whitespace checks
  passed. All 807 locked distribution artifacts have SHA-256 hashes and use
  files.pythonhosted.org; registries use public PyPI.
- Current source fingerprint equals both saved coverage metadata fingerprints:
  `e2c9b8b6ad2f8270c365029e991777ec42ca49bb79d36dcb02fd15b16b889cab`.
  Read-only coverage inspection confirmed branch data and complete current
  production-file inclusion. Raw root logs corroborate all three fast runs,
  21 real DB tests, coverage totals and infrastructure/storage/role smoke.
- [Remote CI run 38281486552](https://github.com/Collaboration95/dc2/actions/runs/38281486552)
  completed successfully on the reviewed SHA: Fast checks,
  Python job 36s, frontend job 25s, Processing intake/ownership 1m24s, both image
  scans, HTTPS/Firefox 3m49s, inherited real integration 3m53s, combined package
  coverage, Integration checks and SAST all passed. [DAST run 38281486465](https://github.com/Collaboration95/dc2/actions/runs/38281486465)
  also passed. Browser job logs show actual Go compilation `#24 DONE 130.5s`,
  followed by trusted-positive/untrusted-negative PASS; R1 does not allege a
  functionality failure or a missed fast-job timing target. Measured jobs are
  within the applicable foundation budgets.

SCOPE:

- Foundation only. Media, workers, Publisher, full login/video workflows,
  recovery/scaling and releases remain subsequent issue gates. `/api` returning
  503 is appropriate here. No broader security architecture is required.
- Reviewer wrote only this report. No code/runtime changes, GitHub writes,
  commits or additional agents. Concurrent coordinator documentation edits are
  outside the pinned committed diff reviewed above.

FOLLOW_UP:

- Await the parent's requested bounded re-review of the cache fix and actual warm
  CI evidence. Per the coordinator's reported disposition, #10/#2 are reopened
  and the fix will land before product work. No patch review, new checks or other
  work was performed as part of this attribution/history correction.
