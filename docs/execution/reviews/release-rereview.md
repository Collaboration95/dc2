VERDICT: PASS
ISSUE: #23 (V4), parent #6, dependency #20
PR: local branch `work/release-integration`

Reviewed HEAD: `f5ba469ca2a43b243b4806f9adfffa4daf7f7353`.
Fix implementation: `5418bf6b07bd058f6c9b38be182270b329bfd98c`.
Rereview base: `fcb0bf656363229c548e7770c2dd8a7a1c343156`.
Review date: 13 October 2026, Singapore.

This is the final independent verdict on the R1–R3 corrections and their
regressions at this HEAD. All three prior findings are resolved within the
reviewed implementation scope. Full live V4 acceptance remains parent-owned:
the complete good/bad release experiment has not yet run. That scheduled next
step is not a finding against these fixes. This PASS does not authorize merge
or release, or assert measured live promotion, recovery, scan or drain results.

ACCEPTANCE:

- [pass] **R1 — supported local BuildKit base with verified parent binding.**
  `scripts/dev/release.py:547` inspects the retained immutable ID, creates a
  project/operation-unique parent tag, verifies its exact binding before and
  after build, and records both verification times and `build.derived_from`.
  The Dockerfile uses the named local reference with `--pull=false` and
  `--network none`; the output is resolved back to an immutable ID. An injected
  release must derive from the tested running baseline (`release.py:830`).
  Parent-tag uniqueness and retained/before/after mismatch tests pass
  (`tests/dev/test_release.py:567`, `1000`, `1023`). Promotion and restoration
  continue selecting immutable IDs, with the parent tag confined to build input
  (`release.py:98`, `648`, `678`, `774`, `864`).

  Read the actual scratch-build report in `release-fixes.md:87`: the corrected
  real `Runner.build` completed on Engine 29.9.0 / BuildKit 0.34.0 with containerd
  in **0.911s**, deriving
  `sha256:d5bf8fad8ed90f6266ee5816c7a9931b946e11129d9981f283f14b23decd5114`
  from
  `sha256:647c02742b4f697327c9bc16f211c92ef0c1106caeaf2cbbf71de3f9965e47a5`.
  Its unique parent binding was verified at
  `2026-10-12T18:56:33.475187+00:00` and
  `2026-10-12T18:56:34.064063+00:00`; the distinct output carried the injection
  label. This is supplied actual-build evidence, not a reviewer build. Its
  recorded older source labels establish compatibility only, and are not used
  as this HEAD's artifact/scan acceptance.

- [pass] **R2 — actual injected API deployment failure required.**
  `release.py:678` records migration and startup as separate steps. Only a
  startup exception initiates failure capture, which is saved before restoration
  replaces the candidate (`release.py:712`). Capture selects the Processing API
  with `ps --all`, retaining CID, exact image ID, injection label, exited state,
  exit code, start/finish timestamps, OOM/runtime-error flags and the declared
  marker from merged Docker logs (`release.py:734`). Logs are hashed rather than
  retained raw. Capture failure still permits recovery and cannot satisfy the
  experiment.

  `release.py:935` and `969` require a distinct candidate derived from the good
  image, its injection proof, successful migration, failed startup, exactly one
  matching API that actually started and exited 42 with the marker, no OOM or
  runtime error, no exhausted promotion deadline, exact good-image restoration
  and cleared pending intent. A pre-mutation failure cannot pass these gates.
  Tests execute real apply/capture/restore/evidence paths with external boundaries
  mocked (`test_release.py:880`). Positive coverage verifies durable capture
  before restoration (`952`); all 13 negative cases reject migration,
  missing-image/pre-start, unrelated Compose, wrong image/exit, missing marker
  or label, OOM, runtime error, never-started, deadline and capture failures even
  when recovery succeeds (`967`). The inherited scan-before-deployment rejection
  remains covered (`337`).

- [pass] **R3 — legitimate replacement attempts accepted; unfinished/current
  interruption and final claims remain guarded.** Both diagnostic queries now
  include `Attempt.error` and `Job.current_attempt_id` (`release.py:411`, `422`).
  `terminal_attempt` requires completion and a durable attempt error before
  accepting a failed/abandoned attempt superseded by a different current ID;
  a still-current failure continues requiring visible Job failure/error
  (`release.py:130`). This matches the owner-authorized, locked retry transition
  that creates a new Attempt and clears Job error (`processing/lifecycle.py:63`),
  and recovery's atomic durable abandonment (`processing/recovery.py:43`).
  Unfinished, still-processing and same-attempt requeued work remain rejected.

  Drain still stops workers with 60-second grace, unions the pre-stop and
  post-stop processing IDs to catch a final claim, and waits for every captured
  attempt within the original five-minute bound (`release.py:434`). Real drain
  tests cover retry plus final claim in both release and automatic rollback
  (`test_release.py:1075`); the old-attempt matrix covers queued, processing,
  done and failed replacement Jobs (`1056`). Current-attempt visible failure,
  same-attempt requeue timeout and late terminal DB reply rejection remain
  covered (`392`, `433`, `844`). The recovery service is restored before rollback
  drain, and failed recovery retains pending intent (`release.py:767`).

- [pass] **Inherited gates and scope preserved.** Exact-ID artifact tests and
  Trivy metadata/OS-package/zero-fixable-HIGH-or-CRITICAL gates remain before
  pending deployment intent and worker stop (`release.py:103`, `517`, `648`,
  `839`). Shared candidate API/worker/recovery image receives one candidate scan.
  Clean source revision/index fingerprint and source rechecks remain enforced
  (`310`, `467`, `847`); runtime persisted/candidate selection and clean/dirty
  bootstrap labels remain covered by the passing runtime suite. Processing-only
  apply preserves `--no-deps --no-build --pull never`, replica verification and
  separate migration ownership. Media API/recovery identity, images, revision
  labels and owned DB revisions still gate promotion and recovery (`398`, `405`,
  `801`, `861`). The 600-second promotion, 300-second drain and separate
  300-second automatic recovery limits, final deadline checks, public workflow
  smoke and distinct failure/recovery result codes remain intact. No new
  deployment or security architecture was introduced.

FINDINGS:

- None requiring revision within the bounded R1–R3 rereview.

CHECKS:

- Read review-work `SKILL.md`, root/worktree `AGENTS.md`, worklog, local V4/E5/V1
  contracts, prior review, fixes/scratch-build report and runner/runtime handoffs.
  Reviewed the complete three-file diff against `fcb0bf6`, changed runner/tests
  and relevant unchanged runtime, Compose, lifecycle, recovery and worker code.
  No additional scoped `AGENTS.md` was present. No GitHub access was used.
- Independently executed from this worktree:

  ```sh
  PYTHONDONTWRITEBYTECODE=1 \
    DC2_DOCKER_HOST=unix:///offline-review-do-not-connect.sock \
    /Users/speedpowermac/Documents/projects/CODE_MAIN/NUS/dc2/.venv/bin/python \
    -m pytest --confcutdir=tests/dev -p no:cacheprovider \
    -p scripts.dev.pytest_plugin --offline-fast tests/dev -q
  /Users/speedpowermac/Documents/projects/CODE_MAIN/NUS/dc2/.venv/bin/ruff \
    check --no-cache scripts/dev/release.py scripts/dev/runtime.py \
    tests/dev/test_release.py tests/dev/test_runtime.py
  git diff --check fcb0bf6..f5ba469
  ```

  Result: **140 passed in 1.66s**, including all **81 release cases**; Ruff and
  diff whitespace checks passed. Network guard, disabled bytecode/cache writes
  and an explicit dummy Docker socket kept this execution offline.
- Independently corroborated the reported red/green check by loading only
  `git show fcb0bf6:scripts/dev/release.py` through an in-memory import-loader
  override and running the current tests with the same offline settings:
  `bad_build_rejects_parent_binding_mismatch or
  bad_experiment_rejects_other_failures or
  retry_during_stop_and_final_claim_finish_drain`.
  **18 failed, 63 deselected in 0.71s** against the old runner: three R1 binding
  cases, thirteen R2 negative cases and two R3 release/rollback races. All are
  green in the fixed 140-case run. No repository runner was substituted or
  rewritten.
- Verified runner and release-test bytes match `5418bf6` exactly; documentation
  HEAD adds no further source/test changes. Product/build/test paths are clean.
  Exact UTF-8 source-index SHA-256 including the trailing newline is
  `4b853e6ccb6c225e8b302846f8aee4d3457547702ca62c7e0a583e3276840682`.
  The supplied prior review remains unchanged, SHA-256
  `4bb86cd8b97f90c65a0f29a27fc1860fd76a6f2bc0f113e25b49ec17e30ebd00`.

SCOPE:

Only `docs/execution/reviews/release-rereview.md` was written. Repository
inspection and offline tests only; no application/test edits, GitHub access,
child agents, containers, image builds, live operations, scans, shared Lima
changes, cloud actions or expanded scope. The scratch build was read as supplied
evidence. Preserve the existing 80/20 implementation and inherited release gates.

FOLLOW_UP:

The parent runs the already-planned complete good/bad experiment on clean
integrated source when its shared Lima scaling work permits. Retain exact
source/image and passing artifact/scan evidence; the real injected API
CID/image/marker/exit record before restoration; restored immutable good IDs,
replicas, public smoke and cleared recovery intent; unchanged Media
snapshots/revisions and separate Processing revisions; and honest, separately
measured promotion/recovery/drain times with nonempty interrupted work. This is
the existing live V4 acceptance step, not a new rereview finding or a condition
that makes this fixes verdict provisional.
