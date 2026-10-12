VERDICT: PASS
R1: RESOLVED
ISSUE: #14 (P3); grouped #12/#13/#14, parent #3 (E2)
PR: [#28](https://github.com/Collaboration95/dc2/pull/28), `wave/02-processing`

Bounded independent R1 rereview, 13 October 2026 (Singapore).
Worktree: `.worktrees/processing`, branch `work/processing`.
Base: `0466f1a2779f689e0d046805094f3175314fe092`.
Head: `d0c610866ac638f9d9e5b810fd761be9d2edaee2`.

The cleanup correction satisfies R1. Slow old-attempt storage cleanup no longer
holds the healthy retry's Job lock. No further R1 changes are required for this
head. This is a final assessment of the correction and its regressions; the
parent retains the final-head CI and merge gates.

ACCEPTANCE:

- [pass] Check eligible prefixes in a short transaction —
  `processing/recovery.py:147` locks Job first, reads Attempt and locks its intent,
  verifies persisted identities and due time, and commits a durable scan
  reservation. Only terminal attempts are eligible. Queued/processing attempts
  are protected even with a tombstone; undeleted succeeded attempts and a
  current done prefix are protected. Missing/mismatched identities are rejected.
- [pass] Zero Job/Attempt locks during remote I/O — the transaction and session
  end before `delete_prefix()` at `processing/recovery.py:182`. The initial
  candidate-selection session also closes before the loop. No SQL session spans
  listing/deletion. The offline session-boundary test passes; the real-PG
  regression requires healthy retry heartbeats while storage remains blocked.
- [pass] Releasing eligibility authority is safe — reviewed lifecycle mutations
  consistently serialize on Job. Claim requires queued state; terminal finish
  requires the current live processing attempt and lease token. Retry allocates
  a new Attempt UUID; cancellation retains an irreversible tombstone. Thus an
  eligible old terminal prefix cannot become active or winning during I/O.
- [pass] Fence the result after I/O — `processing/recovery.py:187` locks only
  CleanupIntent and checks job identity, reserved try count and scheduled
  timestamp before changing its safe error/reschedule fields. It writes no Job
  or Attempt state. The new real-PG parameterized test covers both older success
  after newer failure and older failure after newer success, preserving the
  newer result and due time.
- [pass] Preserve current/active/winner/source protections and repeatable intent —
  every delete uses the UUID-derived `jobs/<job>/attempts/<attempt>/` prefix.
  No source prefix is selected. Intents survive empty/successful scans and
  cancellation; reservation commits before I/O, and completion schedules another
  pass after 60 seconds. Existing real-PG erroneous-intent/late-write tests and
  the retained real-MinIO late-PUT/source-denial test remain in the owned suite.
- [pass] Regression exercises the R1 race —
  `tests/integration/test_processing_recovery.py:132` fails A, reserves/claims B,
  and blocks A's deletion using Events. B runs the actual Supervisor; its
  observation wrapper calls the actual lifecycle heartbeat, then reads the
  committed timestamp and live lease in a separate PostgreSQL session. Three
  strictly increasing SQL timestamps must occur while deletion remains blocked
  for longer than the 0.5-second heartbeat timeout. B's guarded work must remain
  pending and uncancelled. After release, B successfully publishes its own
  primary, only A's prefix is deleted, source/B keys survive, and A cannot finish.
  There is no test sleep/poll ordering or substituted successful heartbeat.

FINDINGS:

- None. The original P1-severity R1 is resolved. No architecture expansion or
  additional Issue is required.

CHECKS:

- Reviewer: root `.venv/bin/python -B -m pytest -q
  -p scripts.dev.pytest_plugin --offline-fast tests/processing tests/media_engine
  --no-cov -p no:cacheprovider`, from this worktree with `fast_env()` and bytecode
  writes disabled — **247 passed in 1.02s**. Processing contracts are included
  through `tests/processing/test_contracts.py`. An initial invocation additionally
  named absent `tests/contracts`; it collected no tests and was corrected.
- Reviewer: Ruff check and format check with `--no-cache` on all three changed
  Python files; `git diff --check 0466f1a..d0c6108` — passed.
- Implementation's committed `processing-fixes.md` records this same real-PG
  regression failing before the production fix on `0466f1a` with `LeaseLost`
  in **0.70s**, then passing after the fix in **1.29s**. Inspection of the old
  implementation confirms its Job lock spans the blocked storage call and
  conflicts with the unchanged heartbeat's Job lock. These before/after run
  timings are implementation-reported, not independently rerun here.
- Read raw lane outputs `.local/r1-fast.log` and `.local/r1-owned.log` —
  **637 offline tests passed in 3.68s**, **39 owned tests passed in 7.50s**,
  with no selected skips. The owned suite includes the four new R1 cases.
  Its PostgreSQL fixture requires real PostgreSQL and pre-applied migrations;
  the lane helper enables the owned PostgreSQL/Redis/storage boundaries.
- Reviewer: both `.local/r1-coverage-{fast,owned}.json` fingerprints match the
  reviewed worktree content exactly:
  `06630fa9a2d3d27f5734f7afc94a5d646747a2d3385b041b26dbadd200f33539`.
  Recomputed existing combined JSON rates without writing artifacts:
  Processing **98.32% combined / 93.68% raw branches**; media engine
  **99.42% / 98.00%**. Every production Python file outside migrations in
  these packages is measured; the existing package gate agrees.
- Coordinator refresh was completed by local inspection: root
  `.cache/execution/processing-r1-{fast,owned,gate}.log` shows **644 offline
  tests passed in 4.36s**, **45 owned tests passed in 8.01s**, and passing
  app/Processing/media-engine gates. The owned command uses
  `--require-integration`, selects every Processing integration module plus
  the six DB ownership cases, and exits zero without skips. Both root coverage
  metadata fingerprints match the inspected parent sources. All three changed
  Python files match this reviewed worktree byte-for-byte. Parent source/tooling
  scope differs from the lane, so its offline count is recorded separately.
- Evidence limits: no live services or containers were operated by this reviewer.
  The concurrency regression uses real SQL, supervision and terminal writes,
  with controlled storage and guarded work; it does not itself run FFmpeg or
  block an actual MinIO request. Existing owned tests separately cover real
  FFmpeg/MinIO and retained late PUTs. Raw final pass logs/coverage were inspected;
  the earlier failing-run traceback was not independently reproduced.
- CI status is supplied by the parent/user: PR #28 was green before this fix,
  apart from the independent-review merge gate; corrected-head CI is pending
  separately. No GitHub access was made. Earlier green checks do not establish
  post-fix CI success.

SCOPE:

- R1 and introduced regressions only. Read the review-work skill, AGENTS.md,
  worklog, P3/E2 contracts, prior review and fix report; inspected the complete
  four-file `0466f1a..d0c6108` diff and relevant unchanged lifecycle/storage/
  supervisor code. The prior non-R1 acceptance assessment is not reopened.
- Only `docs/execution/reviews/processing-rereview.md` was written, left
  uncommitted for the parent to copy. No application changes, commits, GitHub
  access, container operations, coverage writes or child agents.

FOLLOW_UP:

- Parent copies this report and requires green checks on the corrected final PR
  head before merge. This PASS does not authorize merge, release, or Issue/Project
  state changes.
