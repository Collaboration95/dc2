"""Bounded readiness polling; never rerun failing acceptance tests."""

import argparse
import threading
import time
import urllib.error
import urllib.request


def wait(url: str, timeout: float) -> None:
    deadline = time.monotonic() + timeout
    event = threading.Event()
    while (remaining := deadline - time.monotonic()) > 0:
        try:
            with urllib.request.urlopen(url, timeout=min(2, remaining)) as response:
                if response.status == 200:
                    return
        except (OSError, urllib.error.URLError):
            pass
        event.wait(min(0.2, max(0, deadline - time.monotonic())))
    raise SystemExit(f"Readiness unavailable after {timeout}s: {url}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url")
    parser.add_argument("--timeout", type=float, default=60)
    args = parser.parse_args()
    wait(args.url, args.timeout)
