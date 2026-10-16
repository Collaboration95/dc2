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
from urllib.parse import urlsplit

from scripts.dev.v1_gateway import Gateway
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


class WorkPump(threading.Thread):
    """Delivers outbox/SQS batches and runs one finite encoder per queued work message."""

    def __init__(self, runtime, interval=0.5):
        super().__init__(daemon=True)
        self.runtime, self.interval = runtime, interval
        self.stopped = threading.Event()
        self.failures = []
        self.encodes = 0

    def queued_work(self):
        from scripts.dev.v1_verify import sdk

        queue = self.runtime["data"]["resources"]["queues"]["work"]
        attributes = sdk(self.runtime["data"], "sqs").get_queue_attributes(
            QueueUrl=queue, AttributeNames=["ApproximateNumberOfMessages"]
        )["Attributes"]
        return int(attributes["ApproximateNumberOfMessages"])

    def run(self):
        from scripts.dev.v1_acceptance import encode_one, pump

        while not self.stopped.wait(self.interval):
            try:
                pump(self.runtime)
                if self.queued_work():
                    # A visible message means exactly one encode; an empty poll would idle 20s.
                    encode_one(self.runtime)
                    self.encodes += 1
            except Exception as error:
                # Kept for the test to assert on; the bridge must not hide a stuck pipeline.
                self.failures.append(f"{type(error).__name__}: {str(error)[:300]}")

    def stop(self):
        self.stopped.set()
        self.join(timeout=90)


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
