"""Harness for driving the real frontend against the local V1 Gateway bridge.

The page, its HTTPS origin and the cookie flow are real. The Gateway is the loopback bridge
in scripts.dev.v1_gateway, S3/SQS are Moto, and a thread plays the part of the SQS event
source mappings and of the one Fargate task per queued message. None of that is AWS.
"""

import base64
import contextlib
import hashlib
import json
import mimetypes
import os
import subprocess
import threading
from pathlib import Path
from urllib.parse import urlsplit

from scripts.dev.v1_gateway import Gateway
from scripts.dev.v1_redact import redact
from scripts.dev.v1_runtime import ROOT

FRONTEND = ROOT / "frontend"
# Only what the page loads. Tests, node_modules and package files are never served.
STATIC_FILES = {"index.html", "app.js", "style.css"}


class FrontendGateway(Gateway):
    """Serves the static frontend beside /api so the page and its API share one origin."""

    def invoke(self, method, target, headers, body=b""):
        path = urlsplit(target).path
        if path.startswith("/api/"):
            return super().invoke(method, target, headers, body)
        if method not in {"GET", "HEAD"}:
            return {"statusCode": 405, "body": ""}
        name = "index.html" if path == "/" else path.lstrip("/")
        served = name in STATIC_FILES or name.startswith("vendor/")
        file = (FRONTEND / name).resolve()
        if not served or not file.is_file() or not file.is_relative_to(FRONTEND):
            return {"statusCode": 404, "body": ""}
        kind = mimetypes.guess_type(file.name)[0] or "application/octet-stream"
        return {
            "statusCode": 200,
            "headers": {"Content-Type": kind},
            "isBase64Encoded": True,
            "body": base64.b64encode(file.read_bytes()).decode(),
        }


def shipped_cors(bucket, origin):
    """The CORS rules the V1 template gives `bucket` ("Source" or "Output"), for `origin`.

    Reading the shipped template keeps the browser test honest: a hand-written permissive
    rule here hid that the output bucket must answer CORS-mode HLS segment reads.
    """
    template = json.loads((ROOT / "deploy/aws/v1/template.json").read_text())
    rules = template["Resources"][f"{bucket}Bucket"]["Properties"]["CorsConfiguration"]
    placeholder = {"Ref": "SourceCorsOrigin"}
    # CloudFormation and the S3 API spell two of the keys differently.
    rename = {"ExposedHeaders": "ExposeHeaders", "MaxAge": "MaxAgeSeconds"}
    return {
        "CORSRules": [
            {
                rename.get(key, key): (
                    [origin if item == placeholder else item for item in value]
                    if key == "AllowedOrigins"
                    else value
                )
                for key, value in rule.items()
            }
            for rule in rules["CorsRules"]
        ]
    }


def allow_origin(runtime, origin):
    """Give the page's exact origin the CORS the shipped buckets give the site.

    Moto answers CORS only for configured buckets. The output bucket matters twice: hls.js
    and the MP4 range read use CORS, and native HLS redirects its segment reads there too.
    """
    from scripts.dev.v1_verify import sdk

    s3 = sdk(runtime["data"], "s3")
    buckets = runtime["data"]["resources"]["buckets"]
    for bucket in ("source", "output"):
        s3.put_bucket_cors(
            Bucket=buckets[bucket], CORSConfiguration=shipped_cors(bucket.title(), origin)
        )


# This many failed iterations in a row (about 3s of retrying at the default interval, plus
# the time each attempt took) is a fault that is not going away, not a slow moment.
STUCK_AFTER = 6


class WorkPump(threading.Thread):
    """Delivers outbox/SQS batches and runs one finite encoder per queued work message.

    One iteration that fails is not a verdict. On a CI runner Moto, PostgreSQL, FFmpeg and
    Chromium share two CPUs, so a loopback call can time out once and then succeed on the
    next pass, and the pipeline has recovered by itself. The pump therefore keeps going and
    judges the pipeline by whether it ended up healthy: a failure streak of `STUCK_AFTER`,
    or an iteration that is still failing when the pump stops, is a real fault. Every error
    is kept (redacted) either way so a recovered blip is still visible in the report.
    """

    def __init__(self, runtime, interval=0.5):
        super().__init__(daemon=True)
        self.runtime, self.interval = runtime, interval
        self.stopped = threading.Event()
        self.errors = []
        self.streak = self.worst_streak = 0
        self.encodes = 0

    def queued_work(self):
        from scripts.dev.v1_verify import sdk

        queue = self.runtime["data"]["resources"]["queues"]["work"]
        attributes = sdk(self.runtime["data"], "sqs").get_queue_attributes(
            QueueUrl=queue, AttributeNames=["ApproximateNumberOfMessages"]
        )["Attributes"]
        return int(attributes["ApproximateNumberOfMessages"])

    def iterate(self):
        from scripts.dev.v1_acceptance import encode_one, pump

        try:
            pump(self.runtime)
            if self.queued_work():
                # A visible message means exactly one encode; an empty poll would idle 20s.
                encode_one(self.runtime)
                self.encodes += 1
        except Exception as error:
            self.streak += 1
            self.worst_streak = max(self.worst_streak, self.streak)
            self.errors.append(redact(f"{type(error).__name__}: {str(error)[:300]}"))
        else:
            self.streak = 0

    def run(self):
        while not self.stopped.wait(self.interval):
            self.iterate()
        if self.streak:
            # The last pass failed and nothing ran after it; one more pass says whether the
            # fault was a blip or is still there.
            self.iterate()

    @property
    def stuck(self):
        return self.worst_streak >= STUCK_AFTER or bool(self.streak and self.stopped.is_set())

    def problem(self):
        """Why the pipeline cannot be trusted, or None when it ended healthy."""
        if not self.stuck:
            return None
        return (
            f"The work pump failed {self.worst_streak} times in a row "
            f"(still failing: {bool(self.streak)}): {self.errors[-5:]}"
        )

    def stop(self):
        self.stopped.set()
        self.join(timeout=90)


def segment_redirect_gap(redirects, reads):
    """What a redirected native segment read still lacks, or None once it has happened.

    Both halves are read where they happen: the Gateway bridge's list of 307 paths, and the
    object store's list of segment GETs. The browser's own request and response events are
    deliberately not used. Under load Playwright can report a redirect hop after the response
    that followed it, attributed to the first request's URL, so they can disagree with what
    actually crossed the wire at the moment a test looks.
    """
    redirected = [p for p in redirects if p.endswith(".ts")]
    gaps = []
    if not redirected:
        gaps.append("the Gateway has not answered a segment request with a 307")
    if not reads:
        gaps.append("the object store has not been asked for a segment")
    return "; ".join(gaps) or None


def spki_pin(certificate):
    """SHA-256 of the leaf public key, so only this process trusts this one certificate."""
    public = subprocess.check_output(
        ["openssl", "x509", "-in", str(certificate), "-pubkey", "-noout"]
    )
    der = subprocess.check_output(["openssl", "pkey", "-pubin", "-outform", "DER"], input=public)
    return base64.b64encode(hashlib.sha256(der).digest()).decode()


@contextlib.contextmanager
def chromium(certificate, profile):
    """Headless Chromium trusting only the generated certificate; errors stay enabled.

    The browser must already be installed (make browser-install, or `playwright install
    chromium`). When V1_BROWSER=1 was requested, a missing browser raises Playwright's own
    install hint; it is never turned into a skip.
    """
    os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(ROOT / ".local/playwright"))
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        # channel="chromium" selects the full browser in new headless mode, which is what
        # `playwright install chromium --no-shell` (make browser-install) provides.
        context = playwright.chromium.launch_persistent_context(
            str(profile),
            channel="chromium",
            headless=True,
            ignore_https_errors=False,
            args=["--ignore-certificate-errors-spki-list=" + spki_pin(certificate)],
            viewport={"width": 1280, "height": 800},
        )
        try:
            yield context
        finally:
            context.close()


def failure_dir(name):
    """Where this test may leave screenshots and state, or None outside a verified run."""
    base = os.environ.get("V1_FAILURE_DIR")
    return Path(base) / name if base else None


def capture_failure(page, directory, **context):
    """Leave a screenshot and a redacted page-state file beside the junit report.

    A Playwright trace is deliberately not used: it embeds every request's headers, cookies
    and presigned URLs, and cannot be scrubbed afterwards. The screenshot shows only what the
    page rendered, and the state file is passed through `redact` as a whole.
    """
    if directory is None:
        return
    directory.mkdir(parents=True, exist_ok=True)
    state = dict(context)
    try:
        page.screenshot(path=str(directory / "page.png"), timeout=10000)
    except Exception as error:
        state["screenshot_error"] = type(error).__name__
    probe = """() => {
      const text = id => document.getElementById(id)?.textContent?.trim() ?? null;
      const shown = id => { const e = document.getElementById(id); return !!e && !e.hidden; };
      const v = document.querySelector('#player video');
      return {
        path: location.pathname,
        status: text('status'), auth_status: text('auth-status'), badge: text('job-badge'),
        auth_visible: shown('auth'), app_visible: shown('app'), player_visible: shown('player'),
        video: v && {t: v.currentTime, ready: v.readyState, paused: v.paused, ended: v.ended,
                     error: v.error && v.error.code, src_kind: v.currentSrc.split(':')[0]},
      };
    }"""
    try:
        state["page"] = page.evaluate(probe)
    except Exception as error:
        state["page_error"] = type(error).__name__
    (directory / "state.json").write_text(redact(json.dumps(state, indent=2, default=str)))
