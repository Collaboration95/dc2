# Integration harness fixes: R1, R2, R4

13 October 2026. Branch `work/integration-fixes`, base
`0b24c9da4007bd44db9671f07924571d98e68e5b`, implementation commit
`dd102cadb963574e4ddb746a66f8daab3f94c20c`.

The three requested harness corrections are implemented. Controlled offline
regressions and scoped Ruff checks pass. New live browser, full V1, and V2
recovery verification remain **parent pending** on the combined source.
No container commands, live browser, full integration, GitHub operations, or
child agents were invoked here. Controlled subprocess tests launch inert Python
and Node programs only. Production, contracts, R3 tests/mapping, Make/CI,
`common.py`, and `browser.py` were not changed.

## Corrections

- **R1:** `scripts/dev/scenario.py::ServiceGuard` snapshots the entirely running
  baseline before mutation, including the original worker replica count. A
  stopped/mixed baseline is rejected before injection. Every browser/recovery
  stop or kill is now inside that guard. The processing outage also guards Media
  because its restart can mutate state before raising. Each scoped service is
  restored independently with `up --no-deps --no-build --pull never --scale`,
  with a 30-second command bound and a 10-second replica verification bound.
  No dependencies or global Docker actions are involved. Restoration records
  expected/actual counts, PASS/FAIL and failure types; original failures are
  re-raised, with a note if cleanup fails. Cleanup failure alone fails the run.
  Resume steps inside faults preserve the same original replica counts.
- **R1 outer timeout:** `scripts/dev/verify.py::supervised_e2e` replaces the
  unguarded 900-second child call. Its parent snapshots only the run's worker
  replicas before launching the child in a separate process group. On failure
  or timeout it sends TERM, waits at most five seconds, sends KILL to any
  remaining group members, and bounds child reaping at five seconds before
  restoring workers. The parent retains its own FAIL report and restoration
  outcome at `artifacts/<run-id>/e2e-supervisor-<id>.json`, even if child cleanup
  never executes. Its nominal post-timeout cleanup budget is 50 seconds
  (10 for cancellation/reaping, 30 for restore, 10 for inventory).
- **R2:** `scripts/dev/e2e_clients.py::browser_login` requires actual UI POST
  registration 201, UI POST logout 204, a hidden app/visible authentication
  screen, then existing credentials submitted through the login UI. The actual
  POST `/api/auth/login` must return 200 for the registered owner, and the app
  must become visible before upload proceeds. The separate HTTPX client is
  retained only for state polling.
- **R4:** `browser_playback` requires `hls_url`; the browser response observer
  links the expected successful manifest through loaded variant playlists to
  successful nonempty segment responses, including redirects. The app video
  must select an HLS blob source with hls.js support or its exact native HLS
  source. MP4 fallback cannot satisfy that gate. Playback must advance both
  time (>0.2 seconds from the sample) and video frame count, with readyState>=2
  and no decoder error. A small explicit MP4 video then plays the primary URL
  in the same trusted browser/session and meets the same decoding/progress
  checks with exact MP4 source selection. The existing callable browser
  workflow includes both gates before deletion.

Signed links and playlist contents stay in memory. Evidence contains only
source-kind/selection booleans, counts, timings, frame/ready/error metrics and
safe identifiers; no currentSrc, signed links, credentials or capability tokens
are persisted. The accepted macOS Chrome for Testing leaf pin and unrelated
certificate negative proof remain unchanged in `browser.py`.

## Offline evidence

Executed from this worktree using the root virtual environment, against the
implementation commit above (before this documentation-only commit):

```sh
/Users/speedpowermac/Documents/projects/CODE_MAIN/NUS/dc2/.venv/bin/python -m pytest -q -p scripts.dev.pytest_plugin --offline-fast tests/dev/test_scenario_restore.py tests/dev/test_scenario_browser.py
/Users/speedpowermac/Documents/projects/CODE_MAIN/NUS/dc2/.venv/bin/ruff check scripts/dev/e2e.py scripts/dev/e2e_clients.py scripts/dev/scenario.py scripts/dev/verify.py scripts/evidence/recovery.py tests/dev/test_scenario_restore.py tests/dev/test_scenario_browser.py
/Users/speedpowermac/Documents/projects/CODE_MAIN/NUS/dc2/.venv/bin/ruff format --check scripts/dev/e2e_clients.py scripts/dev/scenario.py scripts/dev/verify.py scripts/evidence/recovery.py tests/dev/test_scenario_restore.py tests/dev/test_scenario_browser.py
git diff --check
```

Results: **33 passed in 1.42s**, Ruff **All checks passed**, six files already
formatted, and no whitespace errors. Ignored raw logs are retained locally:

| Log | SHA-256 |
| --- | --- |
| [.cache/execution/integration-fixes-offline.log](../../../.cache/execution/integration-fixes-offline.log) | `a67674c13572e4f7ecf51fdc2ceba9b7d5a952d7185526e429d8bc26fee33e07` |
| [.cache/execution/integration-fixes-ruff.log](../../../.cache/execution/integration-fixes-ruff.log) | `82b3e6a6c090a57601d22943bd23fca9218d1031dbe5a7b754092f9a156b4f18` |

`tests/dev/test_scenario_restore.py` covers partial mutation followed by an
exception/timeout, restoration failure preserving the original exception,
independent cleanup of remaining services, stopped-baseline refusal, and each
callable fault entering its guard before injection. Real controlled child
processes mutate a stand-in worker count and time out without running finally;
both TERM and forced KILL cases restore three original replicas and retain FAIL
with successful restoration. A nonzero child exit remains a failure too.

`tests/dev/test_scenario_browser.py` covers UI registration/logout/login ordering,
actual POST response matching and rejection of failed/wrong-owner login; HLS
manifest/segment matching, redirects and missing/unrelated/empty/failed segments;
rejection of MP4 fallback, clock-only progress and decoder failure; explicit MP4
selection; and the exact media-sampling JavaScript executed against controlled
plain objects in Node. These are harness regression checks, not real UI or
decoder acceptance evidence.

## Parent verification still required

After combining these fixes with the independently owned R3 changes and after
the parent's serialized fair scaling run, the parent must run the existing full
E2E workflow and recovery command against its owned integrated namespace. Check
`browser-ui-login`, `browser-hls-decoded`, `browser-mp4-decoded`, the bodyless
retry/one-upload evidence, and every `service-restore` outcome. Full verify now
uses the supervisor, whose report must also retain the worker baseline/outcome.
Live cleanup and the newly tightened browser assertions are not certified by
these offline checks. Linux playback and final combined-head V1/V2 acceptance
remain pending.

The historical browser result (78.802s total, 66.521s visible worker failure,
retry body zero bytes) remains supporting evidence for the earlier workflow;
it does not validate the new UI login or transport/decoded-frame assertions.
