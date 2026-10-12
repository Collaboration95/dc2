# Processing grouped validation

P1/P2/P3 (#12/#13/#14) are implemented for independent review and CI. This is
coordinator validation, not the independent verdict and not full V1 acceptance.

Tested product head: `810a8a6` on `wave/02-processing`. Later documentation-only
commits do not change the measured production, tests, locks or dev helpers.

- `make lint`: PASS.
- `python -m scripts.dev.checks coverage-fast`: 635 passed in 4.00s; command4.897s.
- `python -m scripts.dev.owned_checks --run-id p-owned-full`: 41 real PostgreSQL,
  Redis, scoped MinIO and FFmpeg checks passed in6.70s. All three Processing
  RUN flags were enabled. Selected skips fail the tier; no skipped case passed.
- Combined package gate: Processing98.31% (raw branches93.60%), media engine99.42%
  (raw branches98.00%), inherited app86.77% (raw branches78.70%). Unexecuted source
  files are included; this is combined statements/branches, not a pure branch claim.
- `make up RUN_ID=local`: actual API, worker and recovery image builds/starts;
  migrations, TLS, DB-role isolation, Redis, source/output signatures and storage
  privilege denials pass. Worker cap2CPU/1536MiB; recovery uses cleanup credentials.
- Updated workflow parses with actionlint1.7.12. The Processing job now builds its
  actual image and pinned cached MinIO, then runs the same owned checks with real
  dependencies. Fast checks remain offline. Actual image scans remain mandatory.

Raw local logs: `.cache/execution/processing-final-{fast,owned,gate,runtime}.log`.
Coverage source data and machine-readable gates: `artifacts/coverage/`.
The full-suite run found a test module name collision that focused tests missed;
`8ce679d`/integrated `810a8a6` renamed it. The corrected full suite passes.

The worker tests use a controlled reverse-HTTP Media peer while exercising real
owned PostgreSQL, FFmpeg and output storage. A separate integration worktree has
already passed a first two-service public workflow, but browser/CLI/fault/load/
release evidence remains in V1–V4. No AWS or Alibaba operation was performed.
