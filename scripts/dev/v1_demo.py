"""Interactive local V1: the shipped web UI, the real handlers and a work pump, in the foreground.

Run after `make v1-up` (and `make setup-v1`). It reuses the browser-acceptance harness: the
FrontendGateway serves the allowlisted frontend files beside /api/media and /api/processing over
local HTTPS, Moto stands in for S3/SQS, and the WorkPump delivers outbox/queue messages and runs one
real finite FFmpeg encode per queued job. Not AWS: no IAM, Lambda, Fargate, Aurora or public TLS.
The certificate is generated locally and trusted only by a browser started with its pinned key
(`--open`, or the printed flag); certificate checking is never disabled.

Starting this resets the run's buckets and queues (Moto state is ephemeral anyway). Ctrl-C stops
the web server and pump; PostgreSQL and Moto stay up until `make v1-down`.
"""

import argparse
import json
import sys
import tempfile
import threading
from pathlib import Path

from scripts.dev.v1_acceptance import app_runtime
from scripts.dev.v1_browser import FrontendGateway, WorkPump, allow_origin, chromium, spki_pin


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--open", action="store_true", help="also open a headed Chromium")
    args = parser.parse_args(argv)
    with app_runtime(args.run_id, gateway=FrontendGateway) as runtime:
        allow_origin(runtime, runtime["url"])
        pump = WorkPump(runtime)
        pump.start()
        print(
            json.dumps(
                {
                    "url": runtime["url"],
                    "mode": "emulated: Moto S3/SQS, Gateway bridge, in-process handlers",
                    "certificate": runtime["ca"],
                    "chrome_flag": "--ignore-certificate-errors-spki-list="
                    + spki_pin(runtime["ca"]),
                    "stop": "Ctrl-C",
                },
                indent=2,
            ),
            flush=True,
        )
        try:
            if args.open:
                with tempfile.TemporaryDirectory() as profile:
                    with chromium(runtime["ca"], Path(profile), headless=False) as browser:
                        browser.new_page().goto(runtime["url"])
                        print("Close the browser window or press Ctrl-C to stop.", flush=True)
                        closed = threading.Event()
                        browser.on("close", lambda *_: closed.set())
                        closed.wait()
            else:
                threading.Event().wait()
        except KeyboardInterrupt:
            pass
        finally:
            pump.stop()
            print(f"Stopped. Encodes: {pump.encodes}; errors: {len(pump.errors)}.", file=sys.stderr)
            for error in pump.errors[-3:]:
                print(f"pump error: {error}", file=sys.stderr)


if __name__ == "__main__":
    main()
