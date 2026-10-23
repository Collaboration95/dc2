"""Wake both auto-paused Aurora clusters before a take, through the real public endpoints.

    DEMO_EMAIL=owner-a@example.com python3 -m scripts.demo.warmup --base-url https://SITE

Runs the release smoke's read-only checks (scripts/aws/v1/public_smoke.PublicSmoke without the
upload reservation): both health routes, anonymous denial, login (Media database), the job list
(Media) and a Processing job batch (Processing database). Login and the Processing batch are
retried while they answer 502/503/504, which is how a resuming cluster looks; the whole round is
repeated until every check passes or the attempts run out. Nothing is written.

The email comes from DEMO_EMAIL or a prompt; the password from DEMO_PASSWORD or a hidden prompt.
Neither is ever an argument, a file or printed. Only check names and status codes are printed.
"""

import argparse
import getpass
import os
import sys
import time

from scripts.aws.transport import OperationError
from scripts.aws.v1.public_smoke import PublicSmoke, urllib_http

# Aurora Serverless v2 resumes in about 15 s, sometimes longer; ~80 s of pauses per round.
WAKE_BACKOFF = (5, 10, 15, 20, 30)
ROUND_SECONDS = 240
ROUND_PAUSE = 15


def credentials(environ=os.environ, ask=input, secret=getpass.getpass):
    email = environ.get("DEMO_EMAIL") or ask("Owner email: ").strip()
    password = environ.get("DEMO_PASSWORD") or secret("Password (hidden): ")
    if not email or not password:
        raise OperationError("An email and a password are required")
    return {"email": email, "password": password}


def warm(
    base_url,
    creds,
    *,
    attempts=3,
    http=urllib_http,
    clock=time.monotonic,
    sleep=time.sleep,
    out=None,
):
    out = out or sys.stdout
    smoke = PublicSmoke(
        base_url,
        creds,
        http=http,
        clock=clock,
        sleep=sleep,
        reserve=False,
        wake_backoff=WAKE_BACKOFF,
    )
    for attempt in range(1, attempts + 1):
        started = clock()
        ok = smoke("warmup", {}, None, deadline=started + ROUND_SECONDS)
        receipt = smoke.receipt
        print(
            f"round {attempt}: {'all answered' if ok else 'not yet'} in {clock() - started:.0f} s; "
            f"login {receipt['login_attempts']}, processing {receipt['processing_attempts']}, "
            + ", ".join(f"{k} {v}" for k, v in receipt["checks"].items()),
            file=out,
            flush=True,
        )
        if ok:
            print("Both databases answered. Record within about ten minutes.", file=out)
            return True
        if attempt < attempts:
            sleep(ROUND_PAUSE)
    return False


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--base-url",
        default=os.environ.get("DEMO_BASE_URL"),
        help="public origin (CloudFront site or API Gateway), no path; or DEMO_BASE_URL",
    )
    parser.add_argument("--attempts", type=int, default=3)
    args = parser.parse_args(argv)
    if not args.base_url:
        parser.error("--base-url or DEMO_BASE_URL is required")
    try:
        ok = warm(args.base_url, credentials(), attempts=max(1, args.attempts))
    except OperationError as error:
        print(f"warmup: {error}", file=sys.stderr)
        return 2
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
