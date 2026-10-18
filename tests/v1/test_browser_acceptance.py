"""The real frontend in headless Chromium against the local V1 Gateway bridge.

Real: the shipped page and scripts, browser cookies and CORS enforcement, Media and
Processing handlers, PostgreSQL, the direct S3 POST path, FFmpeg, hls.js and Chromium's
native HLS, with the bucket CORS rules the V1 template ships. Emulated:
API Gateway (loopback bridge), S3/SQS (Moto) and the queue-to-Lambda/Fargate triggers (a
thread). Opt in with V1_BROWSER=1 after `make setup-v1`; once requested, a missing
browser is a failure, not a skip.

Every wait polls something the test can observe (the job's status, the video element, the
requests the page made) under a bounded deadline, and a timeout says what was last seen.
This leg shares two CPUs with the encoder, Moto and PostgreSQL in CI, so it must not depend
on how fast any one of them answers.
"""

import os
import time
from urllib.parse import urlsplit
from uuid import uuid4

import pytest

pytestmark = [pytest.mark.integration, pytest.mark.e2e, pytest.mark.timeout(300)]

# Seconds, except where a Playwright call takes milliseconds. Locally the encode takes about
# a second; a loaded two-CPU runner gets a generous but finite multiple of that.
ENCODE_TIMEOUT = 150
PLAYBACK_TIMEOUT = 60
STEP_TIMEOUT_MS = 60_000

HIDE_NATIVE_HLS = """
const canPlayType = HTMLMediaElement.prototype.canPlayType;
HTMLMediaElement.prototype.canPlayType = function (type) {
  return /mpegurl/i.test(type) ? "" : canPlayType.call(this, type);
};
"""

JOB_STATE = """
async id => {
  // A hung API must end this poll, not the test's five-minute budget.
  const r = await fetch('/api/media/jobs/' + id, {signal: AbortSignal.timeout(20000)});
  return {http: r.status, job: r.ok ? await r.json() : null};
}
"""

VIDEO_STATE = (
    "v => ({t: v.currentTime, e: v.error && v.error.code, r: v.readyState,"
    " ended: v.ended, paused: v.paused, src: v.currentSrc.slice(0, 12)})"
)


@pytest.mark.parametrize("playback", ["hlsjs", "native"])
def test_browser_signs_in_uploads_directly_waits_for_encode_plays_and_deletes(tmp_path, playback):
    """`native` is the path Safari and iOS always take and recent Chromium now takes too.

    Its segments come from the facade's 307 to another origin, which is what failed with
    MEDIA_ERR_SRC_NOT_SUPPORTED until the player asked for CORS. `hlsjs` hides native HLS
    so the MSE path every other browser takes stays covered.
    """
    if not os.environ.get("V1_RUNTIME_CONFIG"):
        pytest.skip("Explicit Lead C runtime attachment required")
    if os.environ.get("V1_BROWSER") != "1":
        pytest.skip("Set V1_BROWSER=1 to run the real-browser leg (make setup-v1 first)")
    from scripts.dev.v1_acceptance import app_runtime, short_video
    from scripts.dev.v1_browser import (
        FrontendGateway,
        WorkPump,
        allow_origin,
        capture_failure,
        chromium,
        failure_dir,
    )

    source = short_video(tmp_path / "browser.mp4", seconds=4, size="640x360")
    email, password = f"browser-{uuid4().hex}@example.com", uuid4().hex
    with app_runtime(os.environ["V1_RUN_ID"], gateway=FrontendGateway) as runtime:
        allow_origin(runtime, runtime["url"])
        work = WorkPump(runtime)
        work.start()
        seen, console = [], []
        try:
            with chromium(runtime["ca"], tmp_path / "profile") as browser:
                page = browser.new_page()
                page.set_default_timeout(STEP_TIMEOUT_MS)
                # Hermetic: the page's web-font links must neither hang nor reach the internet.
                page.route(
                    lambda url: urlsplit(url).hostname != "127.0.0.1", lambda route: route.abort()
                )
                if playback == "hlsjs":
                    # Chromium plays HLS natively, which is not the path hls.js browsers take.
                    page.add_init_script(HIDE_NATIVE_HLS)

                def record(response):
                    seen.append(
                        (response.request.method, urlsplit(response.url).path, response.status)
                    )

                page.on("response", record)
                # Paths only: a request URL may carry a presigned signature in its query.
                page.on("console", lambda m: console.append(f"console.{m.type}: {m.text}"))
                page.on("pageerror", lambda e: console.append(f"pageerror: {e}"))
                page.on(
                    "requestfailed",
                    lambda r: console.append(
                        f"requestfailed: {r.method} {urlsplit(r.url).path} {r.failure}"
                    ),
                )
                try:
                    drive(page, runtime, work, source, email, password, playback, seen)
                except BaseException:
                    # Evidence while the page is still alive; the original error still wins.
                    capture_failure(
                        page,
                        failure_dir(playback),
                        playback=playback,
                        recent_responses=[f"{m} {p} {s}" for m, p, s in seen[-40:]],
                        console=console[-40:],
                        pump_errors=work.errors[-10:],
                    )
                    raise
        finally:
            work.stop()
        assert work.problem() is None, work.problem()
        assert work.encodes >= 1


def drive(page, runtime, work, source, email, password, playback, seen):
    from scripts.dev.v1_browser import segment_redirect_gap

    page.goto(runtime["url"], wait_until="domcontentloaded")
    assert page.evaluate("window.isSecureContext")

    register = sign_up_logout_and_sign_in(page, email, password)
    assert register["status"] == 201

    with page.expect_response(
        lambda r: r.request.method == "POST" and r.url.endswith("/finalize")
    ) as finalized:
        page.locator("#file-input").set_input_files(str(source))
    assert finalized.value.status in {200, 202}
    asset = finalized.value.json()["job_id"]
    # Bytes went browser -> object store; only metadata crossed the API origin.
    assert any(
        method == "POST" and not path.startswith("/api/") and status in {200, 201, 204}
        for method, path, status in seen
    ), "No direct object-store POST succeeded"
    assert ("POST", "/api/media/upload", 202) not in seen

    # Wait on the job itself, which is what the encode and the result delivery produce, so
    # a stuck pipeline is reported as "stuck at <status>" rather than as a missing <video>.
    latest = {}

    def job_finished():
        latest.update(page.evaluate(JOB_STATE, asset))
        return (latest["job"] or {}).get("status") in {"done", "failed", "cancelled"}

    wait_for(
        page,
        job_finished,
        lambda: f"Job {asset} did not finish in {ENCODE_TIMEOUT}s: {describe(latest)}",
        timeout=ENCODE_TIMEOUT,
        interval=500,
        abort=work.problem,
    )
    job = latest["job"]
    assert job["status"] == "done", f"Job {asset} ended as {describe(latest)}"
    assert job["output_url"] and job["hls_url"], f"Done job has no playable output: {job.keys()}"

    # The page polls every two seconds, so the player appears a moment after the job is done.
    video = page.locator("#player video")
    video.wait_for(state="visible")
    hls_url = page.evaluate("u => new URL(u, location.href).href", job["hls_url"])

    if playback == "native":
        assert video.evaluate("v => !!v.canPlayType('application/vnd.apple.mpegurl')"), (
            "This Chromium has no native HLS, so the native variant proves nothing"
        )
        # The element itself holds the playlist URL; there is no MSE blob. currentSrc is
        # chosen by the media element's own resource selection, a task after `src` is set.
        wait_for(
            page,
            lambda: video.evaluate("v => v.currentSrc") == hls_url,
            lambda: f"Native player is not on the playlist: {video.evaluate(VIDEO_STATE)}",
            timeout=PLAYBACK_TIMEOUT,
        )
        assert video.evaluate("v => v.crossOrigin") == "anonymous"
    else:
        # blob: means hls.js attached through MSE rather than a plain URL.
        wait_for(
            page,
            lambda: video.evaluate("v => v.currentSrc.startsWith('blob:')"),
            lambda: f"hls.js did not attach through MSE: {video.evaluate(VIDEO_STATE)}",
            timeout=PLAYBACK_TIMEOUT,
        )
    # Not awaited: play() settles only once frames flow, and a stalled one must be reported
    # by the bounded waits below rather than hang this call.
    video.evaluate("v => { v.muted = true; v.play().catch(() => null); }")
    wait_for(
        page,
        lambda: (
            any(p.endswith(".m3u8") and s == 200 for _, p, s in seen)
            and any(p.endswith(".ts") and s in {200, 206} for _, p, s in seen)
        ),
        lambda: f"The player did not fetch a playlist and a segment: {seen[-12:]}",
        timeout=PLAYBACK_TIMEOUT,
    )
    # Direct MP4 range read, subject to the browser's CORS enforcement.
    ranged = page.evaluate(
        "async url => { const r = await fetch(url, {headers: {Range: 'bytes=0-31'},"
        " signal: AbortSignal.timeout(30000)});"
        " return {status: r.status, bytes: (await r.arrayBuffer()).byteLength}; }",
        job["output_url"],
    )
    assert ranged == {"status": 206, "bytes": 32}
    playable = video.evaluate("v => v.canPlayType('video/mp4; codecs=\"avc1.42E01E, mp4a.40.2\"')")
    if playable or playback == "native":
        wait_for(
            page,
            lambda: video.evaluate("v => v.currentTime > 0 && !v.error"),
            lambda: f"Clock stuck: {video.evaluate(VIDEO_STATE)}; recent {seen[-12:]}",
            timeout=PLAYBACK_TIMEOUT,
        )
    if playback == "native":
        # The player drops to the MP4 if native HLS errors; that must not pass here.
        assert video.evaluate("v => v.currentSrc") == hls_url
        # The facade 307s each segment to the object store, which must have been asked in
        # CORS mode, from this page's origin and without the session. Having a clock moving
        # does not mean the first segment has been reported yet, and the browser's own event
        # stream can lag or reorder under load, so wait on the bridge's redirect log and on
        # what the object store itself received.
        gateway, reads = runtime["gateway"], runtime["observations"]["segment_reads"]
        wait_for(
            page,
            lambda: segment_redirect_gap(gateway.redirects, reads) is None,
            lambda: (
                f"No redirected segment read within {PLAYBACK_TIMEOUT}s: "
                f"{segment_redirect_gap(gateway.redirects, reads)}; "
                f"gateway 307s={len(gateway.redirects)}, store segment reads={len(reads)}; "
                f"video {video.evaluate(VIDEO_STATE)}; recent {seen[-12:]}"
            ),
            timeout=PLAYBACK_TIMEOUT,
        )
        assert {read["origin"] for read in reads} == {runtime["url"]}, reads
        assert not any(read["cookie"] for read in reads), (
            "The session cookie leaked to the object store"
        )

    page.on("dialog", lambda dialog: dialog.accept())
    with page.expect_response(
        lambda r: r.request.method == "DELETE" and r.url.endswith(f"/jobs/{asset}")
    ) as removed:
        page.locator("#job-delete").click()
    assert removed.value.status == 204
    wait_for(
        page,
        lambda: page.evaluate(JOB_STATE, asset)["http"] in {404, 410},
        "The deleted job is still readable",
        timeout=PLAYBACK_TIMEOUT,
        interval=500,
    )


def describe(latest):
    """What the job poll last saw, for a failure message (never the URLs in the document)."""
    job = latest.get("job") or {}
    return f"HTTP {latest.get('http')} status={job.get('status')} error={job.get('error')}"


def sign_up_logout_and_sign_in(page, email, password):
    """Register, sign out, then sign in again through the real form."""

    def submit(path):
        with page.expect_response(
            lambda r: r.request.method == "POST" and urlsplit(r.url).path == path
        ) as reply:
            page.locator("#auth-submit").click()
        return reply.value

    page.locator("#auth-toggle").click()
    page.locator("#auth-email").fill(email)
    page.locator("#auth-password").fill(password)
    registered = submit("/api/media/auth/register")
    owner = registered.json()["id"]
    page.locator("#app").wait_for(state="visible")
    with page.expect_response(
        lambda r: r.request.method == "POST" and urlsplit(r.url).path == "/api/media/auth/logout"
    ) as logout:
        page.locator("#logout").click()
    assert logout.value.status == 204
    page.locator("#auth").wait_for(state="visible")
    # The form stays in registration mode after sign-out, so switch back to sign in.
    page.locator("#auth-toggle").click()
    page.locator("#auth-email").fill(email)
    page.locator("#auth-password").fill(password)
    login = submit("/api/media/auth/login")
    assert login.status == 200 and login.json()["id"] == owner
    page.locator("#app").wait_for(state="visible")
    return {"status": registered.status}


def wait_for(page, condition, message, timeout=45, *, interval=250, abort=None):
    """Poll `condition` until it holds; AssertionError with `message` at the deadline.

    `abort` returns a reason as soon as waiting longer is pointless (a pipeline fault), so the
    run fails with that reason instead of burning the whole timeout.
    """
    # page.wait_for_timeout keeps Playwright's event loop running, so response callbacks fire.
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if condition():
            return
        if abort and (reason := abort()):
            raise AssertionError(reason)
        page.wait_for_timeout(interval)
    raise AssertionError(message() if callable(message) else message)
