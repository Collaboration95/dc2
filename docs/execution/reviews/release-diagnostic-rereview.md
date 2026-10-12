VERDICT: PASS
ISSUE: #23 (V4), bounded cold diagnostic cap correction only
PR: local branch `review/release-diagnostic`
HEAD: `331354da512224d49e7bdd1206a4fc89d1dcc0a9`
FIX: `ea708397d4b3a18c202a139171e1a8382d411402`
BASE: `5d6c0cdba9789b555f3216b02e53a3c0852eb2fa`

This PASS covers the correction's boundaries and regression preservation. It
does not certify the fresh parent-owned good/bad experiment or full live V4.

ACCEPTANCE:

- [pass] Bounded cold allowance — `scripts/dev/release.py:391` changes the shared
  diagnostic subprocess cap from 15 to 45 seconds. `Runner.compose` still passes
  `self.remaining(cap)` to the subprocess: the allowance is clipped to the
  existing absolute operation deadline. There is one diagnostic invocation,
  with no added retry, deadline reset or extension.
- [pass] Preserve inner and operation limits — diagnostic DB connect and query
  timeouts remain 5 seconds each. Promotion remains 600 seconds; drain and
  automatic recovery retain their respective 300-second bounds. Existing manual
  rollback budgeting is unchanged. After normalizing only cap 45 back to 15,
  the entire release module AST matches BASE, proving all other executable
  behavior is preserved, including exact-image, public-smoke, unchanged-Media,
  pending-intent, active-work and injected-exit-42 acceptance guards.
- [pass] Regression boundaries — the appended test at
  `tests/dev/test_release.py:1452` uses the real diagnostic/compose deadline path
  with a controlled subprocess boundary. A 20-second cold diagnostic succeeds
  with 300 seconds available and receives a 45-second timeout. With only
  10 seconds available, it receives exactly 10 seconds and times out. Both cases
  assert one invocation and the unchanged deadline. All prior test bytes remain
  intact; the complete 109-case offline release suite passes.
- [pass] Rationale and evidence remain scoped — Compose retains the recovery
  service's 0.0625 CPU quota. The supplied correction note records good promotion
  in 96.887 seconds, active drain in 31.873 seconds, the intended bad API exit 42,
  and the first cold recovery diagnostic timing out at 15 seconds. It preserves
  the original automatic experiment's FAIL and distinguishes the warm manual
  rollback PASS (exact good image, public smoke, unchanged Media, cleared intent).
  These are supplied historical results, not independently rerun live evidence.

FINDINGS:

- None requiring revision within this bounded scope.

CHECKS:

- Read user instructions, root/worktree `AGENTS.md`, review-work skill,
  `docs/project2-worklog.txt`, `release-diagnostic-fix.md` and prior release reviews.
- Inspected the complete executable diff and necessary unchanged context;
  offline AST comparison and prior-test preservation checks passed.
- Root `.venv/bin/python -m pytest --confcutdir=tests/dev -p no:cacheprovider
  -p scripts.dev.pytest_plugin --offline-fast tests/dev/test_release.py -q`
  from this worktree — **109 passed in 2.09 seconds**. Bytecode writes disabled;
  network guard enabled and explicit dummy Docker socket selected.
- Root `.venv/bin/ruff check --no-cache scripts/dev/release.py
  tests/dev/test_release.py` and `git diff --check 5d6c0cd..HEAD` — PASS.

SCOPE:

- HEAD adds CT documentation only. FIX also carries workflow evidence,
  V1/V2 progress metadata and a prior fixture review; those records introduce
  no executable change and are outside this V4 correction verdict.
- Only this uncommitted report was written. No code or AGENTS edits, GitHub
  access/mutations, Docker/VM/FFmpeg/browser/network/live operations occurred.
  Security and architecture were not reopened.

FOLLOW_UP:

- Parent retains ownership of the fresh complete good/bad experiment already
  running. Its live result is required for V4 acceptance; this review neither
  predicts that result nor relabels the original failed automatic experiment.
