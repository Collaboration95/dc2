"""Run the project-local Firefox browser with explicit local CA trust."""

import argparse
import contextlib
import json
import os
import shutil
import ssl
import subprocess
import tempfile
import threading
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

try:
    from .tls import ROOT, ensure_tls, run_directory
except ImportError:
    from tls import ROOT, ensure_tls, run_directory


@contextlib.contextmanager
def trusted_browser(run_id, headless=True):
    # Repo-owned test harness; interactive inspection uses T3 preview separately.
    os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(ROOT / ".local/playwright")
    from playwright.sync_api import sync_playwright

    tls = ensure_tls(run_id)
    browsers = ROOT / ".local/playwright"
    certutil = shutil.which("certutil")
    if certutil is None:
        raise RuntimeError("Firefox trust tests need NSS certutil (libnss3-tools on Linux).")
    with sync_playwright() as playwright:
        executable = Path(playwright.firefox.executable_path)
        if not executable.is_file() or not executable.is_relative_to(browsers):
            raise RuntimeError("Install project Firefox with make browser-install first")
        with tempfile.TemporaryDirectory(prefix="firefox-", dir=run_directory(run_id)) as profile:
            subprocess.run(
                [certutil, "-N", "-d", "sql:" + profile, "--empty-password"],
                check=True,
                capture_output=True,
            )
            subprocess.run(
                [
                    certutil,
                    "-A",
                    "-d",
                    "sql:" + profile,
                    "-n",
                    "dc2-local-ca",
                    "-t",
                    "C,,",
                    "-i",
                    str(tls / "ca.crt"),
                ],
                check=True,
                capture_output=True,
            )
            context = playwright.firefox.launch_persistent_context(
                profile,
                headless=headless,
                ignore_https_errors=False,
                viewport={"width": 1280, "height": 800},
            )
            try:
                yield context
            finally:
                context.close()


class ProbeHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        body = b"<html><body><h1>dc2 TLS trust works</h1></body></html>"
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, _format, *_args):
        pass


@contextlib.contextmanager
def tls_probe(folder):
    server = ThreadingHTTPServer(("127.0.0.1", 0), ProbeHandler)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(folder / "server.crt", folder / "server.key")
    server.socket = context.wrap_socket(server.socket, server_side=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"https://localhost:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def trust_smoke(run_id, live_url=None):
    from playwright.sync_api import Error

    trusted = ensure_tls(run_id)
    untrusted = ensure_tls(run_id[:50] + "-untrusted")
    artifacts = ROOT / "artifacts" / run_id
    artifacts.mkdir(parents=True, exist_ok=True)
    with tls_probe(trusted) as positive, tls_probe(untrusted) as negative:
        with trusted_browser(run_id) as browser:
            page = browser.new_page()
            response = page.goto(positive, wait_until="domcontentloaded", timeout=15000)
            assert response.status == 200
            assert page.locator("h1").inner_text() == "dc2 TLS trust works"
            assert page.evaluate("window.isSecureContext") is True
            page.screenshot(path=str(artifacts / "browser-trust.png"))
            if live_url:
                live = page.goto(live_url, wait_until="domcontentloaded", timeout=15000)
                assert live.status == 200, "Live infrastructure HTTPS endpoint failed"
                assert page.evaluate("window.isSecureContext") is True
            try:
                page.goto(negative, wait_until="domcontentloaded", timeout=15000)
            except Error as error:
                message = str(error)
                if not any(s in message for s in ("SEC_ERROR_", "MOZILLA_PKIX_ERROR")):
                    raise AssertionError(
                        "Untrusted control failed for a non-certificate reason"
                    ) from error
            else:
                raise AssertionError("Firefox accepted the untrusted control certificate")
            result = {
                "tested_at": datetime.now(UTC).isoformat(),
                "browser": browser.browser.version,
                "trusted_https": "PASS",
                "untrusted_certificate_rejected": "PASS",
                "ignore_https_errors": False,
                "trust_mechanism": "project-profile NSS certutil CA import",
                "ca_file": str(trusted / "ca.crt"),
                "live_infrastructure_url": live_url,
            }
    (artifacts / "browser-trust.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["install", "trust-smoke", "open"])
    parser.add_argument("--run-id", default="dc2")
    parser.add_argument("--url")
    args = parser.parse_args()
    if args.action == "install":
        import sys

        env = {**os.environ, "PLAYWRIGHT_BROWSERS_PATH": str(ROOT / ".local/playwright")}
        subprocess.run(
            [sys.executable, "-m", "playwright", "install", "firefox"], check=True, env=env
        )
    elif args.action == "trust-smoke":
        trust_smoke(args.run_id, args.url)
    else:
        state = json.loads((run_directory(args.run_id) / "state.json").read_text())
        with trusted_browser(args.run_id, headless=False) as browser:
            browser.new_page().goto(args.url or state["public_url"])
            input("Press Enter to close this project browser.\n")


if __name__ == "__main__":
    main()
