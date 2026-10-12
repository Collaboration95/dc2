"""Real browser and independent Publisher acceptance; no service imports."""

import time
from uuid import uuid4

from scripts.dev.browser import trusted_browser
from scripts.dev.runtime import compose
from scripts.dev.scenario import fixture


def browser_workflow(scenario):
    source = scenario.artifacts / "browser.mp4"
    fixture(source, seconds=12, width=1280, height=720)
    email = f"browser-{uuid4().hex}@example.com"
    password = uuid4().hex
    observations = []
    with trusted_browser(scenario.run_id) as browser:
        page = browser.new_page()
        page.set_default_timeout(15000)

        def request_seen(request):
            from urllib.parse import urlparse

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
        page.locator("#auth-toggle").click()
        page.locator("#auth-email").fill(email)
        page.locator("#auth-password").fill(password)
        page.locator("#auth-submit").click()
        page.locator("#app").wait_for(state="visible")
        assert page.evaluate("window.isSecureContext")
        # Log in with a separate cookie jar for bounded state polling. Browser
        # remains the actor for registration, upload, retry, playback and deletion.
        client = scenario.client()
        scenario.request(
            client,
            "POST",
            "auth/login",
            200,
            route="/auth/login",
            json={"email": email, "password": password},
        )
        compose(scenario.state, "stop", "worker", timeout=75, capture_output=True)
        try:
            with page.expect_response(
                lambda response: (
                    response.request.method == "POST" and response.url.endswith("/api/upload")
                )
            ) as accepted:
                page.locator("#file-input").set_input_files(str(source))
            response = accepted.value
            assert response.status == 202
            asset = response.json()["job_id"]
            compose(
                scenario.state, "up", "-d", "--no-deps", "worker", timeout=60, capture_output=True
            )
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
            compose(
                scenario.state, "up", "-d", "--no-deps", "worker", timeout=60, capture_output=True
            )
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
            video = page.locator("#player video")
            video.wait_for(state="visible", timeout=15000)
            scenario.record(
                "browser-before-play",
                media_state=video.evaluate(
                    "v => ({ready:v.readyState,network:v.networkState,"
                    "error:v.error?.code||null,"
                    "duration:Number.isFinite(v.duration)?v.duration:null})"
                ),
            )
            try:
                video.evaluate(
                    "async v => { v.muted=true; await Promise.race([v.play(), "
                    "new Promise((_,reject)=>setTimeout(()=>reject("
                    "new Error('Playback did not start within 15s')),15000))]); }"
                )
            except Exception:
                scenario.record(
                    "browser-play-failure",
                    media_state=video.evaluate(
                        "v => ({ready:v.readyState,network:v.networkState,"
                        "error:v.error?.code||null,"
                        "duration:Number.isFinite(v.duration)?v.duration:null})"
                    ),
                )
                page.screenshot(path=str(scenario.artifacts / "browser-playback-failed.png"))
                raise
            page.wait_for_function(
                "() => { const v=document.querySelector('#player video'); "
                "return v && v.readyState>=2 && v.currentTime>0.2 && !v.error; }",
                timeout=30000,
            )
            page.screenshot(path=str(scenario.artifacts / "browser-playing.png"))
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
                "Real browser registered, uploaded, observed worker "
                "failure, retried without file bytes, played HLS and deleted",
            )
        finally:
            compose(
                scenario.state, "up", "-d", "--no-deps", "worker", timeout=60, capture_output=True
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
    base = [
        str(PYTHON),
        "-m",
        "publisher",
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
