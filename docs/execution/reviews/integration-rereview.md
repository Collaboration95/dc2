VERDICT: PASS
ISSUE: #20 (V1), #21 (V2); parent #6. Contracts and identifiers read locally; no GitHub access.
PR: work/integration-corrections at 775330e718b6ae5b9342829a8dfb11ada6dad14e.

Independent, bounded R1–R4 correction review, 13 October 2026, Singapore. This
is a PASS for the reviewed code and harness corrections. V1/V2 execution
acceptance and issue closure remain pending. Missing final combined-head or
Linux execution is an explicit parent checklist, not a new code finding.

Reviewed correction diff: `0b24c9d..775330e`. The supplied harness implementation
`dd102ca` is present as `a763ed0`, its documentation `0ccdf90` as `0e2ef6f`, and
R3 `20a06bf` as `775330e`. Direct file comparisons found no differences between
the original and cherry-picked harness implementation, harness documentation,
and R3 implementation/documentation in their respective scopes.

Inputs: repository and parent-root AGENTS.md, docs/project2-worklog.txt,
docs/execution/issues/V1.md, V2.md and E5.md, relevant execution-plan rules,
integration-review.md, integration-fixes.md, contract-fixes.md and
contract-evidence.json. Supporting worker, Media lifecycle/replay, frontend
authentication/player and runtime Compose code was inspected read-only.

ACCEPTANCE:

| Finding | Disposition | Direct current-code evidence | Execution limit |
| --- | --- | --- | --- |
| R1: guarded fault injection and bounded restoration | PASS | `ServiceGuard` snapshots running service counts before injection, restores each service independently, verifies original worker replicas and preserves the original exception. `verify.supervised_e2e` owns restoration after child failure/timeout. | Controlled service doubles and inert child processes passed; real Docker restoration was not executed. |
| R2: actual browser logout then login | PASS | The callable browser workflow registers through the UI, awaits logout 204 and signed-out UI, submits existing credentials through the UI, requires POST login 200 for the same owner and a visible app. | Controlled page regressions passed; this reviewer did not execute a real browser or HTTP endpoint. |
| R3: missing CT-20/21/23 variants | PASS | Both source-invalid edits execute the real worker path in the new PG tests; deleted derived-Asset edit-key replay asserts 410 and no recreation; every prepared example has an owning schema and a negative variant. | Schema checks passed. The new PG/FFmpeg cases were collected and inspected only, with live fixtures unexecuted. |
| R4: selected HLS decoding and explicit MP4 | PASS | Expected HLS manifest/segment observation, selected blob/native HLS, video clock/frame progress and a separate exact-source MP4 probe are required by the callable workflow. Direct MP4 fallback cannot satisfy the HLS gate. | Controlled response/sample regressions and sampling JavaScript passed; actual transport/decoder behavior still needs parent browser execution. |

R1 details:

- `scripts/dev/scenario.py:28` arms the guard only after every scoped service has
  a nonzero, entirely running baseline. A stopped/mixed baseline fails before
  any fault. Replica counts come from the owned project's service inventory,
  rather than assuming one worker.
- Static inspection and an AST ancestry check confirmed every browser/recovery
  fault command is inside its guard: browser stop/kill at
  `scripts/dev/e2e_clients.py:209` and `:222`; recovery kill at
  `scripts/evidence/recovery.py:41`, worker/reconciler stop at `:61`, Redis-list
  mutation at `:75`, API/reconciler stop at `:119`, and Media restart at `:125`.
  The queue probe at `:85` is also inside the guard. The restart's Media service
  is included in the outage guard, so a partial restart failure is covered.
- Resume and cleanup use `up -d --no-deps --no-build --pull never --scale` with
  the recorded count. Each service gets a 30s command bound and, if that succeeds,
  a 10s inventory bound. Cleanup continues for other services after one fails.
  Expected/actual replica counts and failure types enter restoration evidence.
  A cleanup failure annotates and re-raises the original error; cleanup failure
  without an original error fails the run. These are bounded cleanup attempts,
  not a promise that an unavailable Docker daemon can always restore services.
- `scripts/dev/verify.py:34` snapshots workers before launching E2E in its own
  process group. At the 900s child timeout or nonzero exit it sends TERM, allows
  at most 5s, kills remaining group members, and bounds reaping at another 5s
  before restoring workers. Nominal post-timeout cancellation/restoration budget
  is 50s. Only workers are mutated by E2E, so the parent guard correctly scopes
  workers; recovery has its separate service guards. The supervisor saves FAIL
  and restoration outcomes independently of the child's finally block.
- `tests/dev/test_scenario_restore.py:74`, `:92`, `:105`, `:112`, `:128`, `:174`
  and `:217` directly cover partial mutation followed by exception/timeout,
  original exception identity after cleanup failure, independent remaining
  service restoration, cleanup-only failure, baseline refusal, guard-before-
  injection in all four workflows, TERM/forced-KILL timeout restoration to
  three workers with no child finally, and preservation of child exit 7.

R2 details:

- `scripts/dev/e2e_clients.py:12` waits on actual POST paths, not a registration
  response or the separate HTTPX polling login. It requires registration 201,
  logout 204, hidden `#app`/visible `#auth`, login 200 with the registered owner,
  then visible `#app`. `browser_workflow` invokes it before upload at `:195`.
- The authentication-mode toggle matches `frontend/app.js`: registration mode
  survives logout, so toggling back selects existing-account login. The
  controlled tests at `tests/dev/test_scenario_browser.py:80` and `:95` assert
  ordering, POST matching, signed-out/app states, and rejection of login 401 or
  a different owner. They validate assertion logic, not live UI acceptance.

R3 details:

- `tests/integration/test_processing_worker.py:185` has collected parameters
  `[out-of-source-crop]` and `[over-duration-clip]`. Both public/P schemas accept
  the operation; actual Processing submission reserves a queued Job/Attempt.
  Actual `tasks.execute` downloads a digest-matched 160×120, 0.6s FFmpeg fixture
  through the controlled source peer and performs real ffprobe/source validation.
  Its observer delegates to the real crop/clip validator and requires the exact
  source-dependent rejection. An unrelated download/probe failure cannot pass.
  The test then reads persisted current Job/Attempt state, failure/error/start/
  finish fields, empty outputs and zero output PUTs, checks the owner-read schema,
  and invokes actual MM public projection with failed status/error and no MP4/HLS
  URLs. Processing PG and source probing are real when executed; the source HTTP
  and output store are controlled, and the MM Asset is in memory. This is not
  evidence of live MM persistence/public HTTP, Redis, MinIO or HTTPS execution.
- `tests/integration/test_media_persistence.py:395` uses actual MM edit/delete/
  replay ASGI handlers and real Media PG when enabled. It retains the parent,
  deletes the derived child, proves the child's source is removed, reads the
  retained edit key/tombstone, and repeats the same edit key twice. Both responses
  must be 410. Exactly parent/child rows remain, the child stays deleted, key/hash
  remain unchanged, and no staged row, source/output, deletion, submission,
  Processing job or cancellation is added. The Processing HTTP peer and object
  store are controlled. This is not a real Processing/MinIO result.
- `scripts/dev/contracts.py:46` maps all eight prepared payloads explicitly to
  their owning public/P/MM operation schemas, including requests and responses;
  only the textual note is metadata. Missing/extra names cannot silently skip
  validation. `tests/contracts/test_prepared_contracts.py:23`, `:40` and `:47`
  validate all examples, separately corrupt each of the eight and require
  `ValidationError`, and reject an unmapped example. All 16 schema tests passed.

R4 details:

- `scripts/dev/e2e_clients.py:45` observes successful HLS playlist/segment
  responses in memory and links them from the expected manifest through loaded
  variant playlists. It requires a nonempty matching segment, handles segment
  redirect ancestry, and rejects failed/empty/unrelated segment evidence.
- `MEDIA_SAMPLE` at `:96` and `decoded_playback` at `:116` require selected
  blob HLS with Hls support or the exact native HLS source, readyState >=2,
  no decoder error, >0.2s additional clock progress and an increasing video
  frame counter (`getVideoPlaybackQuality().totalVideoFrames`, with the WebKit
  decoded counter fallback). The play promise is bounded at 15s and the progress
  wait at 30s. This establishes frame/clock progress, not a dropped-frame or
  visual-quality assessment.
- `browser_playback` at `:143` requires `hls_url`, executes that selected HLS
  gate and expected response-graph check, then creates a separate MP4 element
  for the exact `output_url` and requires the same progress/error checks. It
  cleans up that element in finally. The workflow calls both before owner
  deletion. Inspection of `frontend/app.js:744` and `:783` confirms the current
  HLS failure fallback mounts a direct MP4 URL, which fails HLS source selection.
- The controlled tests reject manifest-only evidence, missing/unrelated/empty/
  failed segments, direct MP4 fallback, clock-only progress, no progress,
  insufficient readyState and decoder errors. They exercise explicit MP4 source
  selection and execute the exact sampling JavaScript in Node against plain
  objects for blob, native HLS, MP4 and unsupported-blob cases. These are neither
  a browser implementation nor a real decoder. Signed links remain in memory;
  returned evidence contains source-selection booleans and aggregate metrics.

FINDINGS:

- None requiring revision. R1–R4 are resolved in the reviewed implementation.
- Historical evidence metadata is not promoted to current acceptance:
  contract-evidence.json still identifies the original reviewed `0b24c9d` head
  and REVISE verdict, with old R1/R2/R4/CT-18 dispositions. Six line-number
  references shifted after the harness cherry-pick; all 81 mapped function
  references still exist. Current anchors are `queue_loss:58`,
  `processing_outage:113`, `cli_workflow:275`, and `browser_workflow:170`.
  This document supplies the current dispositions; the historical JSON was
  left unchanged as required by this review's single-file ownership.

CHECKS:

Executed from this worktree using the existing root virtual environment. Tests
used `PYTHONDONTWRITEBYTECODE=1`, all three live-test flags set to `0`,
`--offline-fast`, and no pytest cache. No live fixtures ran.

```sh
env PYTHONDONTWRITEBYTECODE=1 RUN_PROCESSING_TESTS=0 RUN_MEDIA_TESTS=0 RUN_INTEGRATION_TESTS=0 /Users/speedpowermac/Documents/projects/CODE_MAIN/NUS/dc2/.venv/bin/python -m pytest -q -p scripts.dev.pytest_plugin --offline-fast -p no:cacheprovider tests/dev/test_scenario_restore.py tests/dev/test_scenario_browser.py tests/contracts/test_prepared_contracts.py
env PYTHONDONTWRITEBYTECODE=1 RUN_PROCESSING_TESTS=0 RUN_MEDIA_TESTS=0 RUN_INTEGRATION_TESTS=0 /Users/speedpowermac/Documents/projects/CODE_MAIN/NUS/dc2/.venv/bin/python -m pytest --collect-only -q -p no:cacheprovider -p scripts.dev.pytest_plugin --offline-fast tests/contracts/test_prepared_contracts.py tests/integration/test_processing_worker.py tests/integration/test_media_persistence.py
```

- Offline execution: **49 passed in 1.48s** (33 harness + 16 schema).
- Collection: **61 tests collected in 0.16s**; both new CT-20 parameters and
  the new CT-21 test are present. Collection is not a live-test PASS.
- Root-venv Ruff, `--no-cache`: all checks passed across the 11 scoped Python
  files; format check passed for the 10 correction Python files.
- `git diff --check 0b24c9d..HEAD`: passed. AST checked all 81 evidence-map
  function references and fault-command guard ancestry.
- All 15 historical report paths in contract-evidence.json exist and their
  SHA-256 values match. These reports remain historical evidence; their hashes
  do not prove this head or its running images were tested. The earlier combined
  invocation remains FAIL even where individual CLI subsections passed.

SCOPE:

Only this uncommitted `docs/execution/reviews/integration-rereview.md` is authored
for parent copy. The supplied untracked integration-review.md is retained.
No application/test/harness code, other review files or evidence JSON changed.
No containers, real network/browser/PG/FFmpeg tests, GitHub, other agents,
AWS/Alibaba or shared-Lima operations were invoked. Controlled child Python/Node
processes and temporary stand-in state are the only executed harness boundaries.
The accepted scoped macOS Chrome leaf-pin choice remains valid and unchanged;
no trust rerun, OIDC, security redesign, architecture or performance expansion
is requested. This review is not merge, deployment or issue-close authorization.

FOLLOW_UP:

- After the parent's serialized fair-scaling measurement, run the three new live
  cases through the existing migrated real-service lanes: both CT-20 parameters
  and `test_deleted_derived_asset_edit_key_replay_is_410_without_recreation`.
- Build/start the final combined source in the parent's owned namespace; run
  full `make verify-local RUN_ID=<owned-id>` and `make e2e RUN_ID=<owned-id>`.
  Retain complete raw output and full-scope result, successful UI logout/login,
  selected HLS playlists/segments and advancing frames, explicit MP4 playback,
  one-upload/bodyless retry, owner deletion, and supervisor/restoration outcomes.
- Run full `make evidence-recovery RUN_ID=<owned-id>`; retain actual worker
  visible failure <=300s, surviving-hash queue repair <=120s, pending upload and
  Media restart/replay, unchanged repair Attempt, successful retry with a new
  Attempt, and exactly one published primary. Preserve failed runs and cleanup
  outcomes. Controlled timings above are not production recovery measurements.
- Run the full Linux browser workflow and scoped trust check. Existing trust-only
  CI and historical macOS subset/probe reports do not satisfy full Linux or final
  V1/V2 execution. Record final commit/build identity, configuration, IDs, timings
  and raw results; reconcile the historical CT map during that evidence assembly.
- **Parent must complete full Linux and final V1/V2 verification before closing
  #20/#21.** This PASS clears R1–R4 code corrections only.
