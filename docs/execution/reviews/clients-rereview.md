VERDICT: PASS
ISSUE: #18 (C1), #19 (C2); parent #5 (E4)
PR: local branch work/clients-fixes; no GitHub publication

Reviewed and tested head: `5de8e270690ea4682abb3d272a45dfb15fdd1aa4`.
Correction implementation: `e654ea04ec1d1a627a55b78cb5f6b038f9301f47`.
Previously reviewed head / correction base:
`3dd50965be13a53dd8752f95e716faa4f30b37b8`.
Original lane review base: `e538819428d5586308d4e3288a66e99dd8d9de09`.
Review date: 13 October 2026, Singapore.

Final independent, bounded rereview of R1/R2/R3. Read the review-work skill,
root/worktree AGENTS.md, current root worklog, local C1/C2 and F3 contracts,
execution plan/interfaces, clients-review.md, clients-fixes.md and relevant
clients-implementation.md evidence. Inspected the complete eight-file correction
diff, surrounding production paths and regression assertions. The head after
e654ea0 changes review documentation only. All checks below ran against 5de8e27;
additional probes loaded 3dd5096 and 5de8e27 source in memory for comparison.
No remaining finding or missing check prevents this bounded client PASS.

ACCEPTANCE:

- [pass] C1: public API/cookie register/login, folder publish, per-file outcomes,
  status/output access and stored-source retry — the 57-test Publisher suite
  passes, including public schema/route/body checks and the corrected auth and
  persistence sequences. Real controlled-peer TLS/cookie restart also passes.
- [pass] C1: independent client, bounded waits/timeouts and meaningful partial
  failure exits — existing import/dependency and polling checks pass. Acceptance
  followed by journal/cookie failure preserves file accounting and returns exit 1.
- [pass] C1: machine-readable JSON, excluded credentials and recorded effort/size
  — one-document JSON, safe error/response fields and fault-output assertions
  pass. Existing measured effort/size evidence remains explicitly labelled as an
  incomplete implementation interval rather than the proposal allocation.
- [pass] C2: failed jobs retry their stored source without sending a video —
  library/active-card and auth-resumption assertions use bodyless public retry
  requests and assert no upload request for retry/edit resumption.
- [pass] C2: stable IDs/content for unresolved transport replay and fresh IDs for
  later confirmed actions — upload, retry and edit sequences preserve original
  keys/content across lost reply, 401 and same-owner login. Other-owner actions
  use separate records; deferred automatic replay cannot cross a changed session.
- [pass] C2: understandable pending/error503 states and preserved design/editor
  behavior — existing interaction/player checks and the new replacement controls
  pass. Deferred retry completion cannot replace a newer asset or its follower.
  The correction diff leaves HTML/CSS/assets and roadmap illustrations untouched.

FINDINGS:

- No open findings in the R1/R2/R3 rereview scope.
- R1 (prior P1): RESOLVED. `frontend/app.js:487` captures retry asset/intent,
  session and card generation; ownership is checked after JSON resolution, on
  error and before releasing controls. `frontend/app.js:570` fences uploads;
  `frontend/app.js:1143` fences edits; `frontend/app.js:397` drops replaced poll
  replies before handling 401. Tests at `frontend/app.test.js:2111` hold A's retry
  while B uploads, then release 202/401/503/lost replies. They assert B's filename,
  badge, next scheduled GET, confirmation text and exact DELETE /api/jobs/B.
  Tests at :2147 and :2305 separately retain B's unresolved upload key/content
  and keep B's newer retry disabled until its own completion. These are observable
  DOM/network assertions, not checks of internal generation values.
  A reviewer stdin-only jsdom probe additionally held A's response JSON after
  fetch had already resolved. On 3dd5096 it stopped B's polling, displayed B.mp4
  with A's failed state and DELETE targeted A. On 5de8e27 B remained Processing,
  its next GET still targeted B and `Delete "B.mp4"? This cannot be undone.`
  produced only DELETE /api/jobs/B.
- R2 (prior P1): RESOLVED. `publisher/cli.py:59` retains a pending key on both
  uncertain delivery and 401. Journal identities at `publisher/cli.py:107` and
  `publisher/state.py:17` include origin/owner/operation/content. The browser's
  owner maps at `frontend/app.js:140`, restoration at :167 and session fence at
  :335 retain the File, immutable edit JSON and bodyless retry identity through
  reauthentication. Tests at `tests/publisher/test_publisher.py:470` cover upload
  and retry across separate invocations: lost acknowledgement, mutation 401,
  identity 401, another owner's login/action, original-owner login/resumption and
  a later fresh action. They assert disk keys, request bytes/bodies, headers and
  IDs. Browser tests at `frontend/app.test.js:2170`, :2211 and :2256 exercise all
  three mutations through login, account switching and held-request session
  changes, checking exact File/JSON/body and original versus fresh keys.
  A reviewer stdin-only CLI probe also compares both revisions: 3dd5096 deletes
  the key on 401 and resumes with a new key; 5de8e27 retains it, isolates the other
  owner's action, resumes the original key/content and gives the later confirmed
  action a fresh key. Browser recovery is intentionally within the current page;
  page-reload persistence was not required by R2.
- R3 (prior P2): RESOLVED. `publisher/cli.py:59` constructs the confirmed ID/key
  outcome before cleanup and attaches a safe state_error on cleanup failure;
  :137 preserves batch outcomes and :143 preserves completed results when cookie
  saving fails. `publisher/state.py:28` restores its previous in-memory snapshot
  on a failed reserve/complete write, so later successful writes retain keys still
  on disk. Tests at `tests/publisher/test_publisher.py:541` fault the first accepted
  file's completion, then process an unsupported and another accepted file. They
  assert three outcomes, two distinct confirmed IDs, all keys, exit 1, retained
  disk key and successful later replay with that key. Tests at :594 cover cookie
  failure after both all-accepted and mixed batches; :632 and :655 cover accepted
  retry/rejection cleanup and reservation rollback. Error details are excluded.
  Reviewer stdin-only mixed-batch probes reproduce the baseline failures and
  verify the correction: first cleanup failure previously lost A's ID/key and a
  later save emptied the journal; the head keeps both confirmed IDs, all three
  outcome keys and A's persisted key. Cookie failure previously returned zero
  outcomes; the head keeps all three, both confirmed IDs and all keys. Both head
  probes return exit 1 with a safe state_error. Cookie failure after successful
  journal completion appropriately leaves the journal empty.

CHECKS:

Python commands used the root Python 3.12.11 venv by absolute path with the
clients-fixes worktree as cwd. Vitest and the jsdom probe ran from its frontend
directory using the intentional untracked node_modules symlink. TLS opt-in was
scoped to its single command; no global environment was set.

```sh
/Users/speedpowermac/Documents/projects/CODE_MAIN/NUS/dc2/.venv/bin/python -m ruff check publisher tests/publisher
/Users/speedpowermac/Documents/projects/CODE_MAIN/NUS/dc2/.venv/bin/python -m pytest --confcutdir=tests/publisher -p scripts.dev.pytest_plugin --offline-fast tests/publisher -m 'not integration and not e2e' -q -o addopts='' --cov=publisher --cov-branch --cov-report=term-missing
PUBLISHER_HTTPS_TEST=1 /Users/speedpowermac/Documents/projects/CODE_MAIN/NUS/dc2/.venv/bin/python -m pytest --confcutdir=tests/publisher tests/publisher/test_https.py -q -o addopts=''
node node_modules/vitest/vitest.mjs run --coverage --coverage.include=app.js --coverage.thresholds.statements=96 --coverage.thresholds.branches=96 --coverage.thresholds.functions=96 --coverage.thresholds.lines=96
git diff --check 3dd5096 5de8e27
```

- Ruff and correction whitespace checks: pass.
- Offline Publisher: 57 passed, 1 TLS test deselected; all five production modules
  measured. Combined coverage 98.43%, statements 257/260 (98.85%), raw branches
  56/58 (96.55%); the package's >=80 combined gate passes.
- Real loopback TLS: 1 passed, with explicit CA trust, Secure-cookie persistence
  across client instances and rejection with unrelated system trust.
- Frontend: 152 passed, 3 inherited live tests skipped. Statements/lines 99.75%,
  branches 96.00%, functions 98.55%; all four explicit >=96 gates pass.
- Independent stdin-only old/head behavioral probes: R1 held JSON, R2 lost reply
  then auth recovery/account isolation, R3 completion rollback and final cookie
  failure all distinguish the reproduced baseline failures from passing head
  behavior. They use in-memory source loading and temporary private fixture state;
  no application/test file was added or edited.

SCOPE:

- Bounded R1/R2/R3 client correction review under the approved 80/20 plan. The
  corrections implement those findings without new product features or auth
  infrastructure. No broader architecture/security work is required here.
- The shared root already declares and locks jsonschema (`pyproject.toml:39` and
  `uv.lock:648` inspected). Its absence in this older worktree baseline is a shared
  integration difference, not a renewed client finding or an undeclared root-venv
  dependency. Root Make/packaging/CI integration remains coordinator-owned.
- The user's parent evidence reports a full CLI 30-file live batch PASS on the
  old head for the normal path. That result is attributed to the parent and was
  not rerun or used as proof of corrected exceptional paths. Full V1 validation
  remains pending separately; this final client PASS does not claim V1 completion.
- No GitHub access, containers, AWS/Alibaba actions, child agents, code edits or
  shared-root writes. Only docs/execution/reviews/clients-rereview.md is authored
  by this review and left uncommitted for parent copy. HEAD remains 5de8e27;
  frontend/node_modules remains intentionally untracked and is not committed.

FOLLOW_UP:

- No further R1/R2/R3 correction required. Carry this final PASS into the parent's
  integration review and complete the separately planned V1 workflow validation.
