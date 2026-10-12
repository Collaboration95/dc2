# macOS native-HLS response observation correction

The full final-local verification at `2cb8da8` passed fast/frontend checks,
130 real integration cases, package coverage, TLS and CLI workflow, but its E2E
failed at the HLS response graph gate. Preserve the FAIL at
`artifacts/final-local/e2e-20261012T201714-03e9ac74/result.json` and supervisor
`artifacts/final-local/e2e-supervisor-8951f516.json`. Worker restoration passed.

A focused real-browser diagnostic then attached both response-header and
request-completion observers to the same playback, without changing the app.
The response-header observer reproduced Chromium's `Network.getResponseBody`
error: no data was available for the resource identifier. It was a native media
request. The completed-request observer read three playlists and two segments.
The same native-HLS video advanced from zero to 0.218521 seconds and from four to
nine decoded frames. Diagnostic record:
`artifacts/final-local/hls-observer-probe-20261012T202013-fcea1d2a/result.json`.

The full workflow now observes HLS bodies on Playwright `requestfinished`, when
response bodies are complete, instead of `response`, which announces headers.
The expected manifest/linked nonempty segments, selected HLS transport, advancing
clock/decoded frames and separate explicit MP4 assertions are unchanged. Errors
in completed-body observation still fail; this does not ignore failed assertions
or substitute MP4 fallback. The callable workflow regression requires the
completed-request event and rejects the old response-header binding.

A fresh complete workflow is required for acceptance. The diagnostic is evidence
for this correction only, and does not change the prior failed run to PASS.
