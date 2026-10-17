"""Real browser and independent Publisher acceptance of the frozen inherited stack.

The V1 equivalents (reserved direct upload against the Gateway bridge) live in
tests/v1/test_workflow_acceptance.py and tests/v1/test_browser_acceptance.py.
"""

import time
from urllib.parse import urljoin, urlparse
from uuid import uuid4

from scripts.dev.browser import trusted_browser
from scripts.dev.runtime import compose
from scripts.dev.scenario import fixture


def browser_login(page, scenario, email, password):
    """Register, log out, then exercise existing credentials through the real UI."""
    page.locator("#auth-toggle").click()
    page.locator("#auth-email").fill(email)
    page.locator("#auth-password").fill(password)
    with page.expect_response(
        lambda r: r.request.method == "POST" and urlparse(r.url).path == "/api/auth/register"
    ) as registered:
        page.locator("#auth-submit").click()
    assert registered.value.status == 201
    owner = registered.value.json()["id"]
    page.locator("#app").wait_for(state="visible")
    with page.expect_response(
        lambda r: r.request.method == "POST" and urlparse(r.url).path == "/api/auth/logout"
    ) as logout:
        page.locator("#logout").click()
    assert logout.value.status == 204
    page.locator("#app").wait_for(state="hidden")
    page.locator("#auth").wait_for(state="visible")
    # Registration mode survives logout in the current frontend.
    page.locator("#auth-toggle").click()
    page.locator("#auth-email").fill(email)
    page.locator("#auth-password").fill(password)
    with page.expect_response(
        lambda r: r.request.method == "POST" and urlparse(r.url).path == "/api/auth/login"
    ) as login:
        page.locator("#auth-submit").click()
    assert login.value.status == 200
    assert login.value.json()["id"] == owner
    page.locator("#app").wait_for(state="visible")
    scenario.record("browser-ui-login", register_status=201, logout_status=204, login_status=200)


class BrowserMediaRequests:
    """In-memory HLS response graph. Only aggregate counts enter evidence."""

    def __init__(self):
        self.playlists = {}
        self.segments = set()
        self.failures = []

    def seen(self, response):
        path = urlparse(response.url).path
        if response.status not in (200, 206) or not path.endswith((".m3u8", ".ts")):
            return
        try:
            if path.endswith(".m3u8"):
                text = response.text()
                assert text.startswith("#EXTM3U")
                self.playlists[response.url] = [
                    urljoin(response.url, line.strip())
                    for line in text.splitlines()
                    if line.strip() and not line.startswith("#")
                ]
            else:
                assert response.body(), "Browser HLS segment response was empty"
                # A facade segment can redirect to signed storage. Match the
                # playlist link through its redirect chain without persisting it.
                request = response.request
                while request is not None:
                    self.segments.add(request.url)
                    request = request.redirected_from
        except Exception as error:
            self.failures.append(type(error).__name__)

    def counts(self, manifest):
        assert not self.failures, "Browser HLS response observation failed"
        assert manifest in self.playlists, "Browser did not fetch the expected HLS manifest"
        pending, playlists, segments = [manifest], set(), set()
        while pending:
            url = pending.pop()
            if url in playlists:
                continue
            assert len(playlists) < 10, "Browser HLS ladder exceeded the bounded traversal"
            playlists.add(url)
            for target in self.playlists[url]:
                if target in self.playlists:
                    pending.append(target)
                elif target in self.segments:
                    segments.add(target)
        assert segments, "Browser did not fetch a nonempty segment from the expected HLS ladder"
        return {"playlists": len(playlists), "segments": len(segments)}


MEDIA_SAMPLE = """(v, expected) => {
    const hls = new URL(expected.hls, location.href).href;
    const mp4 = new URL(expected.mp4, location.href).href;
    const blob = v.currentSrc.startsWith('blob:') && !!window.Hls?.isSupported();
    const native = !!v.canPlayType('application/vnd.apple.mpegurl') && v.currentSrc === hls;
    return {ready:v.readyState, error:v.error?.code || null, current_time:v.currentTime,
        decoded_frames:v.getVideoPlaybackQuality?.().totalVideoFrames
            ?? v.webkitDecodedFrameCount ?? 0,
        selected_hls:blob || native, selected_mp4:v.currentSrc === mp4,
        source_kind:blob ? 'blob' : native ? 'native-hls' : v.currentSrc === mp4 ? 'mp4' : 'other'};
}"""


def assert_video_progress(before, after, transport):
    assert after[f"selected_{transport}"], f"Browser selected a different source from {transport}"
    assert after["ready"] >= 2 and not after["error"], "Browser video is not decodable"
    assert after["current_time"] > before["current_time"] + 0.2, "Video clock did not advance"
    assert after["decoded_frames"] > before["decoded_frames"], "Decoded video did not advance"


def decoded_playback(page, video, expected, transport):
    before = video.evaluate(MEDIA_SAMPLE, expected)
    video.evaluate(
        "async v => { v.muted=true; await Promise.race([v.play(), "
        "new Promise((_,reject)=>setTimeout(()=>reject("
        "new Error('Playback did not start within 15s')),15000))]); }"
    )
    page.wait_for_function(
        "([selector,before,expected,transport]) => {"
        "const v=document.querySelector(selector); if(!v) return false;"
        f"const after=({MEDIA_SAMPLE})(v,expected);"
        "return after['selected_'+transport] && after.ready>=2 && !after.error && "
        "after.current_time>before.current_time+0.2 && "
        "after.decoded_frames>before.decoded_frames; }",
        arg=[
            "#player video" if transport == "hls" else "#acceptance-mp4",
            before,
            expected,
            transport,
        ],
        timeout=30000,
    )
    after = video.evaluate(MEDIA_SAMPLE, expected)
    assert_video_progress(before, after, transport)
    return {"before": before, "after": after}


def browser_playback(page, scenario, result, media):
    assert result.get("hls_url"), "Browser acceptance requires an HLS ladder"
    expected = {"hls": result["hls_url"], "mp4": result["output_url"]}
    video = page.locator("#player video")
    video.wait_for(state="visible", timeout=15000)
    hls = decoded_playback(page, video, expected, "hls")
    counts = media.counts(urljoin(scenario.state["public_url"], result["hls_url"]))
    scenario.record("browser-hls-decoded", **counts, **hls)
    page.screenshot(path=str(scenario.artifacts / "browser-playing.png"))
    video.evaluate("v => v.pause()")
    # Small explicit MP4 probe in the same trusted browser/session. The app's
    # own HLS selection above remains the acceptance gate for its player.
    page.evaluate(
        "src => { const v=document.createElement('video'); v.id='acceptance-mp4'; "
        "v.controls=true; v.muted=true; v.src=src; document.body.append(v); }",
        result["output_url"],
    )
    try:
        mp4 = decoded_playback(page, page.locator("#acceptance-mp4"), expected, "mp4")
        scenario.record("browser-mp4-decoded", **mp4)
    finally:
        page.evaluate(
            "() => { const v=document.querySelector('#acceptance-mp4'); if(v) {"
            "v.pause(); v.removeAttribute('src'); v.load(); v.remove(); } }"
        )


def browser_workflow(scenario):
    source = scenario.artifacts / "browser.mp4"
    fixture(source, seconds=12, width=1280, height=720)
    email = f"browser-{uuid4().hex}@example.com"
    password = uuid4().hex
    observations = []
    with trusted_browser(scenario.run_id) as browser:
        page = browser.new_page()
        page.set_default_timeout(15000)
        # This harness drives the frozen inherited stack, which has no /api/media prefix and
        # no reservation routes. The V1 frontend keeps its legacy mode for exactly this.
        page.add_init_script("window.FLICKPOND_LEGACY_API = true;")
        media = BrowserMediaRequests()
        # Native HLS can announce a response before Chromium exposes its body.
        # Only completed requests can supply the playlist/segment graph.
        page.on("requestfinished", lambda request: media.seen(request.response()))

        def request_seen(request):
            path = urlparse(request.url).path
            if request.method == "POST" and (path == "/api/upload" or path.endswith("/retry")):
                observations.append(
                    {
                        "path": path,
                        "key": request.headers.get("idempotency-key"),
                        "bytes": len(request.post_data_buffer or b""),
                    }
                )

        page.on("request", request_seen)
        page.goto(scenario.state["public_url"], wait_until="domcontentloaded")
        browser_login(page, scenario, email, password)
        assert page.evaluate("window.isSecureContext")
        # Log in with a separate cookie jar for bounded state polling. Browser
        # remains the actor for registration/login, upload, retry, playback and deletion.
        client = scenario.client()
        scenario.request(
            client,
            "POST",
            "auth/login",
            200,
            route="/auth/login",
            json={"email": email, "password": password},
        )
        with scenario.restore_services("worker") as guard:
            compose(scenario.state, "stop", "worker", timeout=75, capture_output=True)
            with page.expect_response(
                lambda response: (
                    response.request.method == "POST" and response.url.endswith("/api/upload")
                )
            ) as accepted:
                page.locator("#file-input").set_input_files(str(source))
            response = accepted.value
            assert response.status == 202
            asset = response.json()["job_id"]
            guard.start("worker")
            scenario.wait(client, asset, states=("processing",), timeout=30)
            killed = time.monotonic()
            compose(
                scenario.state, "kill", "-s", "SIGKILL", "worker", timeout=15, capture_output=True
            )
            scenario.wait(client, asset, states=("failed",), timeout=300)
            failure_seconds = time.monotonic() - killed
            assert failure_seconds <= 300
            page.locator("#job-retry").wait_for(state="visible", timeout=15000)
            page.screenshot(path=str(scenario.artifacts / "browser-failed-attempt.png"))
            before_uploads = sum(item["path"] == "/api/upload" for item in observations)
            guard.start("worker")
            with page.expect_response(
                lambda response: (
                    response.request.method == "POST" and response.url.endswith("/retry")
                )
            ) as retry:
                page.locator("#job-retry").click()
            assert retry.value.status == 202
            assert retry.value.json()["job_id"] == asset
            result = scenario.wait(client, asset)
            assert result["output_url"]
            assert before_uploads == sum(item["path"] == "/api/upload" for item in observations)
            retries = [item for item in observations if item["path"].endswith("/retry")]
            assert len(retries) == 1 and retries[0]["bytes"] == 0 and retries[0]["key"]
            try:
                browser_playback(page, scenario, result, media)
            except Exception:
                scenario.record("browser-play-failure")
                page.screenshot(path=str(scenario.artifacts / "browser-playback-failed.png"))
                raise
            scenario.record(
                "browser-playback-retry",
                asset_id=asset,
                failure_seconds=round(failure_seconds, 3),
                retry_body_bytes=retries[0]["bytes"],
                uploads=before_uploads,
            )
            page.on("dialog", lambda dialog: dialog.accept())
            with page.expect_response(
                lambda response: (
                    response.request.method == "DELETE" and response.url.endswith(f"/jobs/{asset}")
                )
            ) as deletion:
                page.locator("#job-delete").click()
            assert deletion.value.status == 204
            scenario.request(client, "GET", f"jobs/{asset}", 404, route="/jobs/{job_id}")
            scenario.passed(
                "CT-18-browser",
                "Real browser registered/logged out/logged in, uploaded, observed worker "
                "failure, retried without file bytes, decoded selected HLS and explicit MP4, "
                "deleted",
            )


def cli_workflow(scenario):
    import json
    import shutil
    import subprocess
    from pathlib import Path

    from scripts.dev.common import PYTHON, ROOT

    folder = scenario.artifacts / "publisher-inputs"
    folder.mkdir(exist_ok=True)
    source = scenario.artifacts / "publisher-source.mp4"
    fixture(source)
    for number in range(30):
        shutil.copyfile(source, folder / f"lesson-{number:02}.mp4")
    (folder / "unsupported.txt").write_text("Expected per-file 415; valid files must continue.")
    cookie = ROOT / ".local/runs" / scenario.run_id / "publisher-e2e/cookies.txt"
    # The shipped CLI is V1-only (reserve, direct S3 POST, finalize). The inherited stack
    # under test accepts only multipart /upload, so swap just that one client method.
    legacy_cli = (
        "import sys; from publisher.client import PublicClient as C; "
        "C.upload = C.legacy_upload; from publisher.cli import main; sys.exit(main())"
    )
    base = [
        str(PYTHON),
        "-c",
        legacy_cli,
        "--base-url",
        scenario.state["public_url"] + "/api",
        "--ca-file",
        scenario.state["ca_file"],
        "--cookie-jar",
        str(cookie),
        "--json",
    ]

    def invoke(*args, expected=0, password=None, timeout=300):
        result = subprocess.run(
            base + list(args),
            input=None if password is None else password + "\n",
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=ROOT,
        )
        assert result.returncode == expected, f"Publisher {args[0]} exit {result.returncode}"
        # Do not persist stdout: authorised playback links are expiring capabilities.
        data = json.loads(result.stdout)
        scenario.record("publisher-command", command=args[0], exit_code=result.returncode)
        return data

    email, password = f"publisher-{uuid4().hex}@example.com", uuid4().hex
    account = invoke("register", email, "--password-stdin", password=password)
    user = account["user"]
    assert invoke("login", email, "--password-stdin", password=password)["user"]["id"] == user["id"]
    assert cookie.stat().st_mode & 0o777 == 0o600
    batch = invoke(
        "publish",
        str(folder),
        "--wait",
        "--max-polls",
        "300",
        "--interval",
        ".2",
        expected=1,
        timeout=600,
    )
    files = batch["files"]
    assert len(files) == 31
    good = [item for item in files if item["ok"]]
    bad = [item for item in files if not item["ok"]]
    assert len(good) == 30 and len(bad) == 1 and bad[0]["file"] == "unsupported.txt"
    selected = good[0]["job_id"]
    assert invoke("status", selected)["job"]["status"] == "done"
    output = invoke("output", selected)["job"]
    client = scenario.client()
    scenario.request(
        client,
        "POST",
        "auth/login",
        200,
        route="/auth/login",
        json={"email": email, "password": password},
    )
    accessed = client.get(output["output_url"])
    assert accessed.status_code == 200 and len(accessed.content) > 0
    scenario.record(
        "publisher-batch",
        accepted=30,
        rejected=1,
        files=31,
        first_asset_id=selected,
        output_bytes=len(accessed.content),
    )
    # Recognised MP4 header but deliberately truncated body produces an owned
    # failed attempt. Retry proves stored-source transport even after deleting
    # the local input. Its unchanged invalid source is expected to fail again;
    # the real browser separately proves recovery to success after a worker kill.
    corrupt = scenario.artifacts / "publisher-failure"
    corrupt.mkdir(exist_ok=True)
    damaged = corrupt / "truncated.mp4"
    damaged.write_bytes(source.read_bytes()[:32])
    failed = invoke(
        "publish", str(corrupt), "--wait", "--max-polls", "100", "--interval", ".2", expected=1
    )["files"][0]
    asset = failed["job_id"]
    before = scenario.processing_job(user["id"], asset)
    assert before["status"] == "failed"
    damaged.unlink()
    retried = invoke("retry", asset, "--wait", "--max-polls", "100", "--interval", ".2", expected=1)
    assert retried["job_id"] == asset and retried["job"]["status"] == "failed"
    after = scenario.processing_job(user["id"], asset)
    assert after["current_attempt"]["number"] == 2
    assert after["current_attempt"]["attempt_id"] != before["current_attempt"]["attempt_id"]
    scenario.record(
        "publisher-stored-retry",
        asset_id=asset,
        attempt_number=after["current_attempt"]["number"],
        local_input_exists=Path(damaged).exists(),
        expected_source_failure=True,
    )
    for asset_id in [item["job_id"] for item in good] + [asset]:
        scenario.request(client, "DELETE", f"jobs/{asset_id}", 204, route="/jobs/{job_id}")
    scenario.passed(
        "CT-18-cli",
        "Independent CLI registers/logs in, reports 30 successes+1 "
        "rejection, polls and accesses output; retry creates Attempt2 without local source",
    )
