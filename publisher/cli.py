"""Small Publisher CLI. Exit 0: success, 1: failure/partial/incomplete, 2: usage."""

import argparse
import fcntl
import getpass
import json
import math
import os
from pathlib import Path

from publisher.client import PublicClient, PublisherError, asset_id
from publisher.state import Intents, file_identity


def positive(value):
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise argparse.ArgumentTypeError("Must be a finite positive number.")
    return number


def poll_count(value):
    number = int(value)
    if not 1 <= number <= 10000:
        raise argparse.ArgumentTypeError("Must be between 1 and 10000.")
    return number


def parser():
    root = argparse.ArgumentParser(description=__doc__)
    root.add_argument("--base-url", required=True, help="HTTPS public API, including /api")
    root.add_argument("--ca-file", help="Explicit PEM CA file; otherwise system trust")
    root.add_argument("--cookie-jar", type=Path, default=Path.home() / ".publisher/cookies.txt")
    root.add_argument("--timeout", type=positive, default=20)
    root.add_argument("--json", action="store_true", help="One JSON document on stdout")
    commands = root.add_subparsers(dest="command", required=True)
    for name in ("register", "login"):
        auth = commands.add_parser(name)
        auth.add_argument("email")
        auth.add_argument("--password-stdin", action="store_true", help="Read one line; never echo")
    publish = commands.add_parser("publish")
    publish.add_argument("directory", type=Path, help="Immediate regular files, sorted by name")
    retry = commands.add_parser("retry", help="Retry the stored source; never sends a file")
    retry.add_argument("asset_id", type=asset_id)
    retry.add_argument("--intent-key", type=asset_id, help="Replay a specific retry UUID")
    status = commands.add_parser("status")
    status.add_argument("asset_id", type=asset_id)
    output = commands.add_parser("output", help="Fetch fresh authorised playback links")
    output.add_argument("asset_id", type=asset_id)
    for command in (publish, retry, status):
        command.add_argument("--wait", action="store_true")
        command.add_argument("--max-polls", type=poll_count, default=60)
        command.add_argument("--interval", type=positive, default=2)
    return root


def mutation(client, intents, identity, call, explicit=None):
    key = intents.reserve(identity, explicit)
    try:
        job_id = call(key)
    except PublisherError as exc:
        if not exc.uncertain:
            intents.complete(identity)
        return {"ok": False, "error": str(exc), "intent_key": key}
    intents.complete(identity)
    return {"ok": True, "job_id": job_id, "intent_key": key}


def finish(client, args, outcome):
    if outcome["ok"] and args.wait:
        try:
            data = client.poll(outcome["job_id"], args.max_polls, args.interval)
        except PublisherError as exc:
            return {**outcome, "ok": False, "error": str(exc)}
        outcome["job"] = data
        outcome["ok"] = data["status"] == "done"
    return outcome


def execute(client, args):
    if args.command in {"register", "login"}:
        if args.password_stdin:
            import sys

            password = sys.stdin.readline().rstrip("\r\n")
        else:
            password = getpass.getpass("Password: ")
        return {"ok": True, "user": client.authenticate(args.command, args.email, password)}
    if args.command in {"status", "output"}:
        job = (
            client.poll(args.asset_id, args.max_polls, args.interval)
            if args.command == "status" and args.wait
            else client.status(args.asset_id)
        )
        ok = not job.get("poll_exhausted") and job["status"] != "failed"
        if args.command == "output":
            ok = job["status"] == "done" and bool(job.get("output_url"))
        return {"ok": ok, "job": job}
    owner = client.identity()
    intents = Intents(args.cookie_jar.with_suffix(".intents.json"), [args.base_url, owner])
    if args.command == "retry":
        identity = intents.identity("retry", args.asset_id)
        return finish(
            client,
            args,
            mutation(
                client,
                intents,
                identity,
                lambda key: client.retry(args.asset_id, key),
                args.intent_key,
            ),
        )
    if not args.directory.is_dir():
        raise ValueError("Publish requires a directory.")
    outcomes = []
    for path in sorted(args.directory.iterdir()):
        if not path.is_file() or path.is_symlink():
            continue
        try:
            identity = intents.identity("upload", file_identity(path))
            outcome = mutation(
                client, intents, identity, lambda key, path=path: client.upload(path, key)
            )
            outcome = finish(client, args, outcome)
        except (OSError, PublisherError):
            outcome = {"ok": False, "error": "File or status request failed."}
        outcomes.append({"file": path.name, **outcome})
    return {"ok": bool(outcomes) and all(item["ok"] for item in outcomes), "files": outcomes}


def main(argv=None):
    args = parser().parse_args(argv)
    # Serialise state operations across CLI processes sharing one session, including
    # pending-intent reservation before any request can leave the process.
    client = None
    try:
        args.cookie_jar.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        lock_fd = os.open(args.cookie_jar.with_suffix(".lock"), os.O_CREAT | os.O_RDWR, 0o600)
        with os.fdopen(lock_fd, "w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            try:
                client = PublicClient(args.base_url, args.cookie_jar, args.ca_file, args.timeout)
                result = execute(client, args)
            finally:
                if client:
                    client.close()
    except PublisherError as exc:
        result = {"ok": False, "error": str(exc)}
    except (OSError, ValueError, KeyError):
        result = {"ok": False, "error": "Client state failed; verify configuration/session."}
    print(json.dumps(result) if args.json else human(result))
    return 0 if result["ok"] else 1


def human(result):
    if "files" in result:
        return "\n".join(
            f"{item['file']}: {'accepted' if item['ok'] else 'failed'} "
            f"{item.get('job_id', item.get('error', ''))}"
            for item in result["files"]
        )
    return json.dumps(result, indent=2)
