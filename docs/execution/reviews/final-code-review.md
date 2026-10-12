VERDICT: REVISE
ISSUE: #20–#23 (V1–V4), parent #6; final code review for #24 (V5)
PR: #31 / review/final-local
HEAD: c0a7315c44ce89c03c8adb7b51ab39a1aca569d9
BASE: ea3950c61f4f9eaa5ad8dcbe1f726303f85e0764 (merged product PR30)

Independent bounded integration/CI review, 13 October 2026, Singapore.
One unhandled V2 readiness failure requires a small harness correction. This is
a code-review verdict, not a rejection for scheduled evidence that has not run.
The parent owns implementation, integration, final evidence review and merging.

Inputs: review-work skill, supplied and repository AGENTS.md, worklog, execution
plan/decisions/interfaces, F1–F3/V1–V5/E5 contracts, prepared CT matrix, evidence
map and prior integration/performance/release rereviews. Reviewed assembled Make,
doctor/README, CI, runtime/release interfaces, client/recovery/evidence harnesses
and their tests. Product lanes PR28/29/30 retain their independent review verdicts.

ACCEPTANCE:

- [pass] V1 client/CI integration — the browser-trust job runs full E2E under a
  15-minute command bound and requires full-scope PASS, both CT-18 client cases,
  and HLS/MP4 decoded events. Integration checks requires this job; partial or
  failed reports cannot pass. Failure artifacts use a specific safe allowlist.
- [pass] Supplied actual Linux execution — CI38300284726 for PR31 head c0a7315
  tested GitHub merge SHA a9c14b925213fc5b3ff61d141be0bc74363144fc. Retained report:
  full PASS in 150.152s; Publisher 30 accepted/1 rejected; actual UI registration,
  logout and login; selected HLS with three playlists/two segments and advancing
  decoded frames; explicit MP4 frames; one upload/bodyless retry; owner deletion;
  successful worker restoration. Visible worker failure was 65.321s. Firefox155
  trusted HTTPS and unrelated-certificate rejection both pass with verification
  enabled. These are supplied raw artifacts independently inspected offline;
  this reviewer did not run a browser or query GitHub. The user reports all15 CI
  checks PASS. Package gate JSON separately confirms all five backend gates pass.
- [fail] V2 readiness after Media restart — the real recovery function aborts
  on a temporary connection failure inside its purported readiness loop. R1 below
  is a new startup failure path, separate from the resolved restoration findings.
  Other recovery injections, replica restoration and acceptance assertions remain
  within the already reviewed design.
- [pass] V3 assembled profile/provenance applicability — 621c03a and this HEAD
  have identical product sources, frontend, image/deployment/Compose inputs and
  locks; the only difference in those paths is processing/README.md. Fixed quotas
  total2vCPU, with2vCPU/1536MiB per worker. Make dispatch reaches the real runner;
  full/pilot eligibility, resource preflight, failure retention and target checks
  remain wired. The active nine-run measurement is not disturbed or claimed done.
- [pass] V4 integration within this snapshot — normal runtime startup loads the
  persisted immutable Processing override; candidate selection takes precedence;
  builds exclude persisted image IDs and generate current source labels. Release
  continues to gate exact-image artifact/scan evidence, independent Media identity
  and migrations, bounded drain, bad startup proof and rollback smoke. Nonempty
  active-work enhancement9b67832, now incorporated by the parent, and its separate
  Aristotle review are explicitly excluded from this verdict and findings.
- [pass] Root commands and local-start guidance within scope — Make exposes the
  actual workflow/evidence/release entry points and run ID/options; doctor-infra
  uses the same selected Docker environment as runtime. README leads with the new
  root stack, scoped browser and private credentials location. Parent c86ae2c has
  supplied handoff.md and cleaned worklog;5f850b8 links PR31. The snapshot's future
  handoff link is resolved in parent documentation and is not a finding.
- [pass] CT mapping integrity — all25 descriptions/inputs/expectations match the
  prepared matrix; all81 references resolve to62 distinct existing Python
  functions; all15 historical report files exist and their SHA-256 values match.
  Historical REVISE/CT-18 gaps and six shifted line references are identified as
  historical by the existing rereview. Current UI/HLS/MP4 assertions and the fresh
  Linux report resolve those code gaps. Final evidence reconciliation must retain
  historical failures and distinguish reviewed head from actual tested merge SHA.

FINDINGS:

- [P2] R1 — scripts/evidence/recovery.py:125–134, especially :129. After
  `compose restart media`, the readiness loop calls `client.get("health")`
  without handling an HTTPX transport exception. A restarted container can be
  running before Uvicorn accepts connections, so ConnectError escapes immediately
  instead of consuming the existing30s readiness budget. A healthy restart can
  therefore fail V2 and suppress CT-13/CT-14 evidence, even when scoped restoration
  succeeds. This is independent of whether the final scheduled V2 run has occurred.

  Direct controlled reproduction executed the actual `processing_outage` and
  actual `ServiceGuard`, replacing only Docker/HTTP/product boundaries. A first
  health ConnectError followed by an available200 response produced **FAIL
  ConnectError after one health request**, no CT cases, and PASS restoration of
  all three services. An initial503 followed by200 produced **PASS after two
  health requests** and both CT cases. No socket, container or encoder ran.

  Required bounded fix: tolerate transient HTTPX transport failures only in this
  health-readiness loop, continuing until health200 or the existing absolute
  deadline. Bound each health request by the remaining budget. Preserve immediate
  failures for the subsequent pending-state, replay and convergence assertions;
  do not retry the whole acceptance scenario. Add a controlled regression for
  ConnectError then200 and for persistent unavailability ending in a bounded
  readiness failure with restoration still attempted. No product change needed.

CHECKS:

- Full current fast Python selection using the root .venv, sanitized fast_env,
  PYTHONDONTWRITEBYTECODE=1, dummy Docker host, --offline-fast, --no-cov and no
  pytest cache: **1051 passed,1 deselected in8.75s**. Real integration/E2E paths
  were excluded; the separate Publisher HTTPS case was not executed.
- Root-venv Ruff `check --no-cache` across app/processing/media/media_engine/
  publisher/tests/migrations/scripts/dev/scripts/evidence: PASS.
- `git diff --check ea3950c..HEAD`: PASS.
- CI YAML parsed; all43 shell blocks pass `bash -n`; all four embedded Python
  blocks parse. No workflow shell block was executed against services.
- `make help` and dry runs of E2E/verify/evidence/release/browser/doctor targets:
  PASS. This validates entry-point wiring, not fresh installation/runtime boot.
- Independent AST/map/hash checks and the controlled R1 probe described above.

Supplied Linux source pack, now retained by the parent under
`docs/execution/evidence/linux-ci-38300284726/`, identifies c0a7315 and actual
tested merge a9c14b9. Inspected the original downloaded report plus parent index,
gate and handoff. Report SHA-256:
`27aa7a7bf2c769aa2620401aa882e9c07aa8dbc58898293a7b315c60c46628e0`.
Trust SHA-256:
`19a9753cdd3ca36ff6bdef0e9692d51dc8e2dd82aa4b690f66a6febd4666113f`.
The measured runner has4host/Docker CPUs and16,766,414,848 bytes Docker memory;
its single-worker client workflow is separate from fair scaling acceptance.

SCOPE:

Only this uncommitted review document is authored. No application, harness, tests,
evidence map or other documentation is edited. No agents spawned, GitHub access,
Docker/build/VM/runtime/FFmpeg/live-browser/network workload, cloud action or merge.
Existing scoped reviews and accepted design/security/browser choices are retained.

FOLLOW_UP:

- Parent fixes R1 and requests the bounded rereview; retain the successful Linux
  report as evidence for its actual tested merge, not as proof of later changes.
- Parent completes the already scheduled V1/V2, V3 and separately reviewed V4
  evidence, final source/check reconciliation and CT evidence refresh. These are
  existing completion work, not additional code findings. No issues are closed
  and no release/merge is authorized by this sidecar.
