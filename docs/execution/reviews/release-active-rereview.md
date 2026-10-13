VERDICT: PASS
ISSUE: #23 (V4), parent #6, dependency #20
PR: local review branch `review/release-active`; integrated change `862b482`

Review date: 13 October 2026, Singapore.
Reviewed HEAD: `5f850b89d06591493b9f269292eb3228c9c24867`.
Original change: `9b67832fc5ea029b5a9abb8bae3c107bd85e2fa4`, against
`4a71f6779e499d072f9a9fac864f536f6fb03532`.
Both reviewed runner/test files are byte-identical between that original change
and this integrated HEAD (`git diff --exit-code 9b67832 HEAD -- ...` passed).

This verdict covers only the new active-work evidence implementation and its
regressions in `scripts/dev/release.py` and `tests/dev/test_release.py`. The prior
R1–R3 PASS in `release-rereview.md` remains accepted. Parent-owned live V4
execution is pending; that is not a finding against this bounded review. This
report does not assert measured live promotion, drain or recovery results, or
authorize merge or release.

ACCEPTANCE:

- [pass] **A real public upload is bound to an owned Processing Attempt.**
  `release.py:867` introduces evidence work only after baseline public smoke,
  candidate build/artifact/scan proof, migration policy and the source recheck.
  The existing public HTTPS helper generates the actual 30-second 1280x720,
  24fps testsrc2 MP4 with one encoding thread and uploads it through `/api/upload`
  (`1176`–`1225`). It saves the accepted Asset ID and fixture hash/parameters
  before polling. Public `processing` alone is insufficient: the parameterized
  owned SELECT requires that Asset's Job and current unfinished processing
  Attempt, then persists both UUIDs and confirmation time (`1226`–`1257`).
  Already-terminal work fails preparation without a substitute upload or retry.
  The real helper control flow is tested with HTTP/FFmpeg boundaries mocked;
  reviewer also joined that helper to real release/drain/outcome control flow.

- [pass] **The upload must still be active in the actual pre-stop snapshot.**
  `release.py:434` retains the drain's own SELECT and requires the exact confirmed
  Attempt to be unfinished, processing, attached to a processing Job and still
  current. The captured row and timestamp are durably saved immediately before
  the existing worker stop (`445`–`461`). Empty snapshots, other IDs, finished
  attempts, replacement current IDs and already-done Jobs reject before stop;
  the five negative cases at `test_release.py:1280` pass. The existing post-stop
  SELECT still unions final claims with pre-stop IDs and waits for all captured
  Attempts to finish visibly within the original bound (`release.py:462`).

- [pass] **Terminal and public evidence cannot pass an idle or mismatched drain.**
  `release.py:1077` selects the same Attempt from `attempts_after`, requires the
  inherited terminal predicate and persists its row before polling the accepted
  Asset through the public Job endpoint. Public `done`/`failed` must match the
  owned Job status; public failure additionally needs a visible error. Only
  queued/processing replies wait. The outcome is saved before owner deletion,
  and deletion precedes candidate apply/smoke. `active_drain_evidence` (`1045`)
  additionally requires the exact captured/terminal rows to occur in the
  nonempty drain records, the processing/capture/public/deletion timestamps and
  completed drain. The full experiment now adds this predicate to its prior
  good/bad gates (`965`). Existing tests plus reviewer probes reject empty or
  missing rows, wrong IDs, superseded/finished capture, unfinished terminal,
  both directions of public status mismatch, missing error, missing public
  evidence/deletion and unfinished drain.

- [pass] **Normal completion during the 60-second grace is valid V4 evidence.**
  The unchanged stop uses `--timeout 60`; a captured Attempt that succeeds and
  has a public `done` outcome passes without an artificial wait. A naturally
  failed Attempt can pass with its required owned/public failure evidence.
  Both outcomes and immediate successful completion are covered at
  `test_release.py:1303` and `1418`. The 30-second fixture is media duration,
  not a guaranteed processing wall time. Normal completion within grace is the
  intended valid path; completion before capture fails honestly. V4 does not
  force a worker kill or require lease expiry. V2 provides separate kill proof.

- [pass] **Original release and actual exit-42 bad-candidate proof are preserved.**
  Ordinary release/rollback retain their existing smoke and drain paths; only
  the good evidence promotion requests active work (`release.py:830`, `958`).
  The ordinary-release isolation regression passes (`test_release.py:1230`).
  The experiment's prior bad-candidate conditions are unchanged apart from the
  added active-drain conjunction: distinct injected image derived from good,
  passed migration, failed startup, matching deployed API CID/image/injection,
  actual start/finish, marker and exit 42, no OOM/runtime error or promotion
  deadline exhaustion, exact good-image restoration and cleared pending intent.
  Durable capture before restoration and all 13 unrelated-failure rejection
  cases remain green (`986`, `1019`). Prior accepted security, browser and
  architecture decisions were not reopened.

- [pass] **Deadlines and durable recovery intent remain correct.**
  Evidence fixture generation has a 30-second command cap within the original
  600-second promotion deadline. Preparation, capture, terminal/public polling
  and deletion share that deadline; they do not allocate a fresh promotion
  budget. The drain remains bounded at 300 seconds. Pending intent is saved
  after preparation and before the worker stop. Preparation failure leaves no
  deployment intent; capture/outcome failures after intent use the existing
  restoration path. Reviewer probes verified preparation expiry rejects before
  intent, lost capture restores the prior image, public-outcome expiry receives
  the separate at-most-300-second recovery budget, and failed restoration keeps
  the matching pending intent on disk with `recovery_required`/exit 3. Successful
  restoration clears it and returns the failed-release exit 2. The inherited
  final deadline, retry/final-claim drain and restarted rollback checks pass.

FINDINGS:

- None requiring revision within the requested scope.

CHECKS:

- Read review-work `SKILL.md`, root/worktree `AGENTS.md`, current worklog,
  `release-active-work.md`, prior `release-rereview.md`, and local V4/E5 contracts
  and active-work decision. No additional scoped `AGENTS.md` was present.
  Reviewed the complete original two-file diff and surrounding runner/test
  control flow; confirmed identical integrated bytes. No GitHub access was used.
- Independently executed from `.worktrees/release-active-review` using the root
  virtual environment:

  ```sh
  PYTHONDONTWRITEBYTECODE=1 \
    DC2_DOCKER_HOST=unix:///offline-review-do-not-connect.sock \
    /Users/speedpowermac/Documents/projects/CODE_MAIN/NUS/dc2/.venv/bin/python \
    -m pytest --confcutdir=tests/dev -p no:cacheprovider \
    -p scripts.dev.pytest_plugin --offline-fast \
    tests/dev/test_release.py tests/dev/test_runtime.py -q
  /Users/speedpowermac/Documents/projects/CODE_MAIN/NUS/dc2/.venv/bin/ruff \
    check --no-cache scripts/dev/release.py tests/dev/test_release.py
  git diff --check 9b67832^ 9b67832 -- scripts/dev/release.py tests/dev/test_release.py
  git diff --check
  ```

  Result: **150 passed in 2.42s**; Ruff and whitespace checks passed. The runtime
  tests are regression evidence only. Network guard, disabled bytecode/test
  caches and a dummy Docker socket kept execution offline.
- **19 additional offline reviewer probes passed**, executed from stdin with
  root `.venv` Python, temporary mock runtime state, and explicit rejection of
  network connections and child commands. These joined the real public helper,
  drain, outcome and promotion paths; exercised 13 incomplete/mismatched
  aggregate records; checked preparation expiry, lost capture, expired-outcome
  recovery and failed-recovery pending intent; and checked failed owned terminal
  versus public `done` rejection before deletion. No source or test file was
  replaced or edited.

SCOPE:

Only this uncommitted report was authored. No application/test edits, child
agents, GitHub mutations/access, live HTTP, browser, FFmpeg workload, Docker
commands, builds/scans, VM operations or cloud actions were performed. Full
scaling and latency retain exclusive use of the shared live environment.

FOLLOW_UP:

Parent runs the already-planned complete V4 experiment after protected scaling
and latency work finish, with clean integrated source and a dedicated run ID.
Retain exact source/image/scan proof, the matched Asset/Job/Attempt and nonempty
pre-stop/terminal drain records, public outcome/deletion, measured timings,
unchanged Media identity/revisions, actual bad API marker/exit 42, restored good
image/replicas/public smoke and cleared pending intent. Report normal successful
drain as such; keep V2 worker-kill evidence separate. Pending live execution is
not a new finding or a condition on this implementation-review PASS.
