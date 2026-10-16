"""The real frontend in headless Chromium against the local V1 Gateway bridge.

Real: the shipped page and scripts, browser cookies and CORS enforcement, Media and
Processing handlers, PostgreSQL, the direct S3 POST path, FFmpeg and hls.js. Emulated:
API Gateway (loopback bridge), S3/SQS (Moto) and the queue-to-Lambda/Fargate triggers (a
thread). Opt in with V1_BROWSER=1 after installing Chromium; once requested, a missing
browser is a failure, not a skip.
"""

import os
import time
from urllib.parse import urlsplit
from uuid import uuid4

import pytest

pytestmark = [pytest.mark.integration, pytest.mark.e2e, pytest.mark.timeout(300)]


HIDE_NATIVE_HLS = """
const canPlayType = HTMLMediaElement.prototype.canPlayType;
HTMLMediaElement.prototype.canPlayType = function (type) {
  return /mpegurl/i.test(type) ? "" : canPlayType.call(this, type);
};
"""


def test_browser_signs_in_uploads_directly_waits_for_encode_plays_and_deletes(tmp_path):
    if not os.environ.get("V1_RUNTIME_CONFIG"):
        pytest.skip("Explicit Lead C runtime attachment required")
    if os.environ.get("V1_BROWSER") != "1":
        pytest.skip("Set V1_BROWSER=1 to run the real-browser leg (make browser-install first)")
    from scripts.dev.v1_acceptance import app_runtime, short_video
    from scripts.dev.v1_browser import FrontendGateway, WorkPump, allow_origin, chromium

    source = short_video(tmp_path / "browser.mp4", seconds=4, size="640x360")
    email, password = f"browser-{uuid4().hex}@example.com", uuid4().hex
    with app_runtime(os.environ["V1_RUN_ID"], gateway=FrontendGateway) as runtime:
        allow_origin(runtime, runtime["url"])
        work = WorkPump(runtime)
        work.start()
        seen = []
        try:
            with chromium(runtime["ca"], tmp_path / "profile") as browser:
                page = browser.new_page()
                page.set_default_timeout(30000)
                # Hermetic: the page's web-font links must neither hang nor reach the internet.
                page.route(
                    lambda url: urlsplit(url).hostname != "127.0.0.1", lambda route: route.abort()
                )
                # Recent Chromium plays HLS natively, which is not the path the other browsers
                # take. Hide it so the page uses hls.js and MSE, as every non-Safari browser does.
                page.add_init_script(HIDE_NATIVE_HLS)
                page.on(
                    "response",
                    lambda r: seen.append((r.request.method, urlsplit(r.url).path, r.status)),
                )
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

                video = page.locator("#player video")
                video.wait_for(state="visible", timeout=120000)
                job = page.evaluate(
                    "async id => (await fetch('/api/media/jobs/' + id)).json()", asset
                )
                assert job["status"] == "done" and job["output_url"] and job["hls_url"]

                # blob: means hls.js attached through MSE rather than a plain URL.
                assert video.evaluate("v => v.currentSrc.startsWith('blob:')")
                video.evaluate("v => { v.muted = true; return v.play().catch(() => null); }")
                wait_for(
                    page,
                    lambda: any(p.endswith(".m3u8") and s == 200 for _, p, s in seen)
                    and any(p.endswith(".ts") and s in {200, 206} for _, p, s in seen),
                    "hls.js did not fetch a playlist and a segment",
                )
                # Direct MP4 range read, subject to the browser's CORS enforcement.
                ranged = page.evaluate(
                    "async url => { const r = await fetch(url, {headers: {Range: 'bytes=0-31'}});"
                    " return {status: r.status, bytes: (await r.arrayBuffer()).byteLength}; }",
                    job["output_url"],
                )
                assert ranged == {"status": 206, "bytes": 32}
                playable = video.evaluate(
                    "v => v.canPlayType('video/mp4; codecs=\"avc1.42E01E, mp4a.40.2\"')"
                )
                if playable:
                    state = (
                        "v => ({t: v.currentTime, e: v.error && v.error.code, r: v.readyState,"
                        " ended: v.ended, paused: v.paused, src: v.currentSrc.slice(0, 12)})"
                    )
                    wait_for(
                        page,
                        lambda: video.evaluate("v => v.currentTime > 0 && !v.error"),
                        lambda: f"Clock stuck: {video.evaluate(state)}; recent {seen[-12:]}",
                    )

                page.on("dialog", lambda dialog: dialog.accept())
                with page.expect_response(
                    lambda r: r.request.method == "DELETE" and r.url.endswith(f"/jobs/{asset}")
                ) as removed:
                    page.locator("#job-delete").click()
                assert removed.value.status == 204
                gone = page.evaluate(
                    "async id => (await fetch('/api/media/jobs/' + id)).status", asset
                )
                assert gone in {404, 410}
        finally:
            work.stop()
        assert not work.failures, work.failures
        assert work.encodes >= 1


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


def wait_for(page, condition, message, timeout=45):
    # page.wait_for_timeout keeps Playwright's event loop running, so response callbacks fire.
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if condition():
            return
        page.wait_for_timeout(250)
    raise AssertionError(message() if callable(message) else message)
