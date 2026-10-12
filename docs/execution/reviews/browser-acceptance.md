# Browser acceptance setup and diagnostic evidence

The existing Python Playwright1.63.0 lock is retained. macOS now uses its pinned
Chrome for Testing153.0.8010.12; Linux uses its pinned Firefox155.0. Installation
stays under `.local/playwright`. No global browser/profile/trust configuration
is changed, and the web application's HTML/CSS/assets are preserved.

On this macOS26/Apple Silicon host, Firefox155 and a separately tested Firefox157
received the MP4 and HLS bytes and buffered media, but never advanced past
readyState1. Decoder diagnostics reported `VideoData::SetVideoDataToImage`
failed to copy decoded AppleVT frames. Headed, software-decoder and renderer
experiments did not correct it. Those experimental settings are absent from the
final launcher. This is a measured browser/platform failure; a matching known
Firefox bug was not established. The application output was not altered to hide it.

The macOS launcher validates its local certificate/hostname with the generated
CA, then supplies only that leaf's SHA-256 SPKI to the browser process's
certificate pin list. `ignore_https_errors` remains false. This is scoped key
trust, rather than adding the CA to macOS Keychain. Linux retains NSS CA import.
Real positive and unrelated-key/certificate negative controls pass; the live
HTTPS health route passes through the same browser. The source TLS helper also
checks certificate expiry. Browser trust metadata states the actual mechanism.

The corrected automated browser flow passed in78.802s against the integrated
services: UI registration/upload, real SIGKILL during processing, visible failure
in66.521s (target<=300s), one bodyless retry with Idempotency-Key, no second upload,
real video readyState>=2/currentTime>0.2, then UI deletion and public404. The
screenshot shows the decoded moving test pattern. This run used the original
uncoloured source fixture; video metadata/encoder settings were not changed.

Evidence remains under the integration worktree's ignored artifacts:
`artifacts/integ/browser-chromium-20261012T183755-d6938518/result.json` and
`browser-playing.png`. The independent media probe also played both HLS and MP4
in the actual browser. Failed diagnostic runs and raw logs are retained, and the
acceptance harness now records each invocation separately with a latest pointer.
A hanging `play()` promise has an explicit15-second bound and failure diagnostics;
UI deletion waits for its actual HTTP response before asserting404.

The complete V1 run on the final combined source, Linux CI and final metadata
reconciliation remain pending at this checkpoint. These facts do not close V1.
