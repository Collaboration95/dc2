# macOS native-HLS observer bounded rereview

VERDICT: PASS
ISSUE: Scoped native-HLS observer correction; no Issue lookup performed.
PR: `review/hls-observer`, commit `422609b434102fd132b41c5bd9ab113d03984ed0`
BASE: `2cb8da833cb7f20b6f4fb41ff4b318f01530266b` (latest commit's parent)

This PASS covers the observer correction only. It does not certify a successful
full workflow or close final acceptance gates.

ACCEPTANCE:
- [pass] Observe completed HLS bodies without a callback type mismatch —
  `scripts/dev/e2e_clients.py:182` binds `requestfinished` to a synchronous
  adapter that calls `request.response()` and passes the resulting Response to
  `BrowserMediaRequests.seen`. The observer continues to consume Response URL,
  status, text/body and request redirect-chain properties.
- [pass] Preserve playback and response-graph gates — the diff changes no
  assertions. Expected-manifest traversal, linked nonempty segments, selected
  HLS transport, clock advance greater than 0.2 seconds, increasing decoded
  frames and the separate explicit MP4 probe remain required. Body/parse errors
  still populate `failures`; `counts()` still rejects any recorded failure.
  Playback exceptions still record failure and re-raise.
- [pass] Protect event binding in the callable regression —
  `tests/dev/test_scenario_restore.py:148-169` records actual workflow bindings
  and requires `requestfinished` while rejecting `response`. Original injected
  failure identity and service-restoration assertions remain intact. This test
  checks binding, not callback execution; the adapter was checked by inspection.
- [pass] Support the change with a controlled native-HLS comparison — the
  read-only parent probe records the response observer's Chromium
  `Network.getResponseBody` protocol error (recorded failure type `Error`) and
  failed graph assertion, while `requestfinished` reads three playlists and two
  segments. Both observations share the same native-HLS decoding samples:
  time 0 to 0.218521 seconds, frames 4 to 9, HLS selected and MP4 unselected.

FINDINGS:
- None within the requested scope.

CHECKS:
- Read supplied user guidance, worktree `AGENTS.md`, review-work skill,
  `docs/project2-worklog.txt` and `mac-hls-observer-fix.md`.
- Inspected latest-commit diff and necessary unchanged context only in
  `scripts/dev/e2e_clients.py` and `tests/dev/test_scenario_restore.py`.
- Read parent-root
  `artifacts/final-local/hls-observer-probe-20261012T202013-fcea1d2a/result.json`.
  Its revision is the base SHA, not the corrected commit; its PASS is diagnostic
  evidence for the event change, not a full-workflow result on the new head.
- Offline test counts (33/35) are parent-reported in the task; no test commands
  or raw test-log verification were performed in this bounded rereview.

SCOPE:
- Only the two specified files were reviewed for code changes. Only this review
  document was written, uncommitted. No live operations, Docker, browser, VM,
  network, FFmpeg, code changes, AGENTS changes or GitHub mutations occurred.

FOLLOW_UP:
- Parent must complete fresh full verify/E2E on the corrected source. Preserve
  the original full-workflow FAIL at
  `artifacts/final-local/e2e-20261012T201714-03e9ac74/result.json` and supervisor
  `artifacts/final-local/e2e-supervisor-8951f516.json`, along with the probe's
  response-observer failure. This rereview does not relabel those failures.
