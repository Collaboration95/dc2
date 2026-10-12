VERDICT: REVISE
ISSUE: #18 (C1), #19 (C2); parent #5 (E4)
PR: local branch work/clients; no GitHub access or publication

Reviewed head: `3dd50965be13a53dd8752f95e716faa4f30b37b8`.
Base: `e538819428d5586308d4e3288a66e99dd8d9de09`.
Review date: 13 October 2026, Singapore.

Independent review of the complete 13-file `base...head` diff, AGENTS.md,
docs/project2-worklog.txt, C1/C2 and F3 issue contracts, the E4 backlog entry,
docs/execution/plan.md, interfaces.md, clients-implementation.md, the prepared
public OpenAPI and contract cases. The implementation is viable, but the three
reproduced failures below require correction before a lane PASS.

ACCEPTANCE:

- [fail] C1: register/login, folder publish, per-file outcome/status, playback
  access and stored-source retry through public APIs/cookies — the commands and
  public routes are implemented; controlled-peer schema, batch and bodyless-retry
  checks pass. Authentication recovery loses unresolved intent identity (R2), and
  persistence failures erase confirmed per-file results (R3).
- [fail] C1: independent dependencies, bounded polls/timeouts and meaningful
  partial-batch exit codes — independence and bounds pass. Normal admission and
  completion failures retain every file and produce exit 1, but R3 breaks that
  accounting after local state failures.
- [pass] C1: machine-readable JSON, password/token exclusion, recorded effort and
  size — successful and failed invocations emit one JSON document; response fields
  are whitelisted and arbitrary error bodies are excluded. Effort is explicitly
  recorded as an incomplete measured interval, with production/test size, rather
  than presented as the proposal's person-day estimate.
- [pass] C2: failed jobs retry their stored source without resending a remembered
  video — active-card and library actions POST `/api/jobs/{asset_id}/retry` with
  no body. Tests assert no `/api/upload` request and cover library retry without
  a remembered File.
- [fail] C2: stable IDs for transport replay and fresh IDs for later intentional
  requests — ordinary lost-response/503 replay and subsequent confirmed actions
  pass, including immutable edit bodies. R2 loses those IDs on authentication
  expiry during replay, even without a page reload.
- [fail] C2: understandable pending/503 states and preserved existing behavior /
  visuals — pending copy, status-outage recovery and missing-asset termination
  pass; design/assets are unchanged. R1 corrupts the active card's identity and
  can make its existing Delete action target the wrong displayed video.

FINDINGS:

- [P1] R1 — `frontend/app.js:449`, `:461–466` (with `:522–527`, `:477–484`):
  a delayed stored-retry reply can overwrite a newer upload and delete the wrong
  displayed asset. `retryStoredSource` applies its response to mutable global
  state without checking whether that retry still owns the active card. The
  upload input remains enabled while retry is in flight; starting B resets the
  card and begins following B. A's later retry acknowledgement then stops B's
  polling, sets `activeJobId` to A and follows A, while the filename remains B.
  **Reproduced:** from a failed library item A.mp4, hold its retry response;
  upload B.mp4 and acknowledge B; release A's retry acknowledgement. The actual
  DOM confirmation was `Delete "B.mp4"? This cannot be undone.` and the following
  request was `DELETE /api/jobs/11111111-1111-4111-8111-111111111111` (A).
  **Required fix:** capture the retry's asset/key and fence its UI completion
  against a replaced card/session. A stale response must not replace the current
  ID, clear a newer intent or start/stop its follower. Add a deferred-response DOM
  regression asserting that B stays displayed/followed and Delete targets B.

- [P1] R2 — `publisher/client.py:87`, `publisher/cli.py:61–65`,
  `frontend/app.js:166–168` (401 callers at `:451`, `:538`, `:1086`):
  authentication expiry discards an unresolved transport intent. The CLI treats
  every 401 as definitive and removes the pending key. The browser clears every
  pending mutation in `showSignedOut`. A 401 on a replay only rejects that HTTP
  attempt; it does not establish that the earlier lost/503 attempt was rejected.
  After the same owner signs in again, the client can create a duplicate Asset,
  or another retry attempt if the previously accepted attempt has failed again.
  **Reproduced:** CLI upload loses its first reply, then gets 401 on replay after
  a successful `/auth/me`. The journal count changes 1 → 0; resumption uses K2
  instead of K1. A jsdom interaction also produced upload keys `[K1, K1, K2]`:
  first reply lost, automatic replay 401, same-owner login, resume the upload.
  All browser pending intents were null immediately after the 401.
  **Required fix:** preserve uncertain intent identity through reauthentication
  and provide same-owner resumption with the original key/content. Keep intents
  scoped to the owner so changing accounts cannot replay another owner's request.
  Retain fresh keys for confirmed later actions. Add lost-response → expired
  authentication → same-owner login/resume tests for CLI and browser mutations;
  a standalone 401 test does not cover this sequence. No new auth infrastructure
  is needed.

- [P2] R3 — `publisher/cli.py:65–66`, `:126–128`, `:144–151`
  (persistence at `publisher/client.py:62–66`, `publisher/state.py:26–28`):
  private state failures erase already confirmed acceptance and batch outcomes.
  If journal completion fails after a 202, `mutation` raises before returning the
  known Asset ID/key; the batch catches it as a generic failed file. If cookie
  persistence fails in `close`, `main` replaces the entire completed result with
  a generic error, dropping the whole `files` array. This prevents callers from
  accounting for accepted work and can encourage a duplicate publish. Completion
  also removes the key in memory before saving; a later file's successful state
  write can erase the earlier persisted key after the completion write failed.
  **Reproduced:** a controlled peer accepted two files. Injecting an OSError only
  during cookie save yielded exit 1 and
  `{"ok": false, "error": "Client state failed; verify configuration/session."}`
  with zero file outcomes. Injecting an OSError during `Intents.complete` yielded
  two generic failures without either confirmed `job_id` or `intent_key`.
  A separate fault in the first completion save, followed by a successful second
  file, left the first file without its accepted ID and the final journal empty:
  the second file's write discarded the first key that had survived on disk.
  **Required fix:** keep confirmed IDs/keys and all per-file outcomes when local
  cleanup or final cookie saving fails; attach a safe state error and return a
  meaningful nonzero overall exit. Preserve an unresolved persisted key when
  cleanup could not be saved, including in-memory rollback so later writes do
  not discard it. Add fault tests after acceptance and after mixed
  batch execution, asserting result cardinality, IDs, replayability and exit code.

CHECKS:

Commands used the root Python 3.12.11 venv by absolute path, with this worktree as
cwd; frontend commands used its frontend directory and existing untracked
node_modules symlink. No service stack or database was started.

```sh
REVIEW_PYTHON=/Users/speedpowermac/Documents/projects/CODE_MAIN/NUS/dc2/.venv/bin/python
"$REVIEW_PYTHON" -m ruff check publisher tests/publisher
"$REVIEW_PYTHON" -m pytest --confcutdir=tests/publisher -p scripts.dev.pytest_plugin --offline-fast tests/publisher -m 'not integration and not e2e' -q -o addopts='' --cov=publisher --cov-branch --cov-report=term-missing
PUBLISHER_HTTPS_TEST=1 "$REVIEW_PYTHON" -m pytest --confcutdir=tests/publisher tests/publisher/test_https.py -q -o addopts=''
node node_modules/vitest/vitest.mjs run --coverage --coverage.include=app.js --coverage.thresholds.statements=90 --coverage.thresholds.branches=90 --coverage.thresholds.functions=90 --coverage.thresholds.lines=90
git diff --check e538819...3dd50965be13a53dd8752f95e716faa4f30b37b8
```

- Ruff and diff whitespace — pass.
- Offline Publisher — 49 passed, 1 TLS test deselected; 97.97% combined coverage
  across all five production modules. Statements 238/242; raw branches 52/54.
- Frontend — 135 passed, 3 inherited live tests skipped. Coverage: statements /
  lines 99.73%, branches 96.13%, functions 98.46%; all four >=90 gates pass.
- Real loopback TLS peer — 1 passed. Explicit certificate trust, persisted Secure
  cookie across client instances and rejection under unrelated system trust are
  exercised with actual sockets. The schema test's mocked SSL context alone is
  not TLS evidence; this separate test supplies it.
- Offline wheel build and fresh temporary venv installation — pass using
  `uv build --offline --wheel`, `uv venv`, `uv pip install --offline`. From outside
  the repository, isolated `python -I -m publisher --help` and the installed
  console entry both pass. Wheel runtime dependency metadata is only HTTPX;
  production imports have no service/database dependency.
- Additional stdin-only controlled fixtures — normal mixed done/failed/exhausted
  folder wait preserves three IDs, exit 1 and exact per-asset GET counts 1/1/3.
  Separate fixtures reproduce R1–R3 as described above. No tests/product files
  were added or modified for these reproductions.
- Tests were evaluated for behavior: public routes/body/key assertions, resumed
  file bytes, session-cookie persistence, real TLS trust, schema checking, batch
  cardinality and bounded status requests provide meaningful evidence. They miss
  cross-operation deferred replies, auth expiry after uncertain mutation delivery,
  and state-write failure after acceptance; high coverage does not cover those
  sequences. No CI or deployed-workflow result is claimed.
- A fresh full locked environment was not established offline: the browser/dev
  attempt lacked a cached Playwright 1.63.0 wheel, and the dev-only attempt using
  the project cache lacked python-multipart 0.0.32. Neither attempt ran tests.
  These cache limitations do not alter the passing root-venv checks or substitute
  for clean CI verification. Missing jsonschema in the reviewed manifests was
  established by inspection; see the coordinator follow-up below.

SCOPE:

- CLI/web only. The diff contains the Publisher package/docs/tests, frontend
  behavior/tests and lane evidence. Shared root/runtime/CI files, backend code,
  roadmap visuals and original documents are unchanged.
- Full V1 HTTPS browser/CLI workflows with integrated Media/Processing, real
  output/playback and backend PostgreSQL ownership remain deferred by the approved
  plan. Their absence is not a finding or a reason to block this lane review.
- No GitHub, AWS, Alibaba, child agents, product edits or shared-root edits.
  This review file is left uncommitted for the coordinator to copy. The reviewed
  branch head remains the SHA above; node_modules remains untracked.

FOLLOW_UP:

- Fix R1–R3, add the specific regressions and obtain independent rereview of the
  new head. C1/C2 are not approved by this report.
- Coordinator must carry the already-requested `make test-cli` alias and locked
  jsonschema dev dependency into integration. At this head, Make has
  `test-publisher` only, and neither pyproject.toml nor uv.lock declares jsonschema,
  despite the new schema test importing it. The root venv supplied it for these
  runs; clean locked CI must not depend on that local installation. This shared
  packaging handoff is separate from the three client behavior findings.
- V1 owns the later live mixed batch, same-origin browser workflow, real MP4/HLS
  playback and backend persistence proof. Add no OIDC or unrelated features.
