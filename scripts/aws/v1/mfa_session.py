"""Mint an MFA-backed AWS session into the `dc2-project2-mfa` profile.

    python -m scripts.aws.v1.mfa_session --code 123456 [--duration 129600]

Why: the V1 deploy drives CloudFormation, and CloudFormation's own calls are denied by
`FlickPondRequireMFA` unless the caller's credentials carry MFA. Only `sts get-session-token`
with a one-time code produces such credentials; the long-term access key of `dc2-project2`
cannot. This command looks up the MFA device on the base profile, exchanges the code, and writes
the temporary credentials to a second profile so the long-term key is never replaced.

Only the expiry is printed. The keys go to `~/.aws/credentials` (mode 0600) and nowhere else:
not stdout, not a log, not the repository. The aws CLI runs with a sanitized environment, so an
inherited AWS_* variable cannot redirect the exchange to another account.
"""

import argparse
import configparser
import datetime as dt
import io
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from scripts.aws.transport import OperationError
from scripts.aws.v1 import credentials
from scripts.aws.v1.operations import PROFILE_PATTERN
from scripts.aws.v1.transport import REGION

DEFAULT_DURATION = 129600  # 36 hours, the longest an IAM user may ask for
MIN_DURATION = 900
_SERIAL = re.compile(r"arn:aws:iam::[0-9]{12}:mfa/[A-Za-z0-9+=,.@_/-]{1,128}")
_SECTION = re.compile(r"^\s*\[(?P<name>[^\]]+)\]\s*$")


def _aws(runner, profile, args, *, payload=None):
    """One aws CLI call with the explicit profile. The request goes through a private file."""
    from scripts.aws.v1_operator import sanitized_environment

    argv = ["aws", "--profile", profile, "--region", REGION, "--no-cli-pager", "--output", "json",
            "--cli-connect-timeout", "10", "--cli-read-timeout", "30", *args]
    with tempfile.TemporaryDirectory(prefix="dc2-mfa-") as directory:
        Path(directory).chmod(0o700)
        if payload is not None:
            path = Path(directory) / "request.json"
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w") as handle:
                json.dump(payload, handle)
            argv += ["--cli-input-json", f"file://{path}"]
        done = runner(argv, env=sanitized_environment(), capture_output=True, text=True,
                      timeout=60, check=False)
    if done.returncode:
        # stderr can quote request fields; report only that the call failed and which one.
        raise OperationError(f"aws {args[0]} {args[1]} failed (exit {done.returncode})")
    try:
        return json.loads(done.stdout)
    except ValueError:
        raise OperationError(f"aws {args[0]} {args[1]} returned unparseable output") from None


def find_serial(runner, base_profile, override=None):
    """The one MFA device of the base profile's user (never guessed when there are several)."""
    if override:
        if not _SERIAL.fullmatch(override):
            raise OperationError("--serial must be a virtual MFA device ARN")
        return override
    devices = _aws(runner, base_profile, ["iam", "list-mfa-devices"]).get("MFADevices", [])
    if not devices:
        raise OperationError("The base profile's user has no MFA device; enroll one first")
    if len(devices) > 1:
        raise OperationError("More than one MFA device found; pass --serial explicitly")
    serial = devices[0].get("SerialNumber", "")
    if not _SERIAL.fullmatch(serial):
        raise OperationError("The MFA device is not a virtual device ARN; pass --serial")
    return serial


def session_credentials(runner, base_profile, serial, code, duration):
    reply = _aws(runner, base_profile, ["sts", "get-session-token"], payload={
        "SerialNumber": serial, "TokenCode": code, "DurationSeconds": duration})
    found = reply.get("Credentials", {})
    needed = ("AccessKeyId", "SecretAccessKey", "SessionToken", "Expiration")
    if not isinstance(found, dict) or any(not found.get(k) for k in needed):
        raise OperationError("STS returned an incomplete session")
    if not str(found["AccessKeyId"]).startswith("ASIA"):
        raise OperationError("STS did not return temporary credentials")
    return found


def _render(name, values, *, prefix=""):
    """One INI section rendered by configparser, so quoting and escaping match its reader."""
    parser = configparser.RawConfigParser()
    parser.add_section(prefix + name)
    for key, value in values.items():
        parser.set(prefix + name, key, value)
    buffer = io.StringIO()
    parser.write(buffer)
    return buffer.getvalue()


def replace_section(text, header, body):
    """Replace or append one section textually, leaving every other byte of the file alone.

    Re-writing the whole file through configparser would drop the operator's comments and
    reorder their other profiles; that is a worse side effect than this small splitter.
    """
    kept, skipping = [], False
    for line in text.splitlines(keepends=True):
        match = _SECTION.match(line)
        if match:
            skipping = match.group("name") == header
        if not skipping:
            kept.append(line)
    result = "".join(kept)
    if result and not result.endswith("\n"):
        result += "\n"
    if result.strip():
        result += "\n"
    return result + body


def _write_private(path, text):
    """Atomic replace through the real path (a dotfiles symlink must survive), mode 0600."""
    target = Path(os.path.realpath(path))
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, name = tempfile.mkstemp(prefix=".dc2-mfa-", dir=target.parent)
    try:
        with os.fdopen(fd, "w") as handle:
            handle.write(text)
        os.chmod(name, 0o600)
        os.replace(name, target)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def write_profile(profile, found, *, home=None):
    """Store the session under `profile` in the credentials file and set its region."""
    cred_path, conf_path = credentials.credentials_file(home), credentials.config_file(home)
    body = _render(profile, {
        "aws_access_key_id": found["AccessKeyId"],
        "aws_secret_access_key": found["SecretAccessKey"],
        "aws_session_token": found["SessionToken"],
        credentials.EXPIRY_KEY: found["Expiration"],
    })
    existing = cred_path.read_text() if cred_path.exists() else ""
    updated = replace_section(existing, profile, body)
    check = configparser.RawConfigParser()
    check.read_string(updated)  # a malformed neighbour must stop us before anything is written
    _write_private(cred_path, updated)
    # The config file uses "profile <name>"; "default" is the only unprefixed header.
    config_body = _render(profile, {"region": REGION, "output": "json"}, prefix="profile ")
    config_text = conf_path.read_text() if conf_path.exists() else ""
    _write_private(conf_path, replace_section(config_text, f"profile {profile}", config_body))


def _expiry(found):
    when = dt.datetime.fromisoformat(str(found["Expiration"]).replace("Z", "+00:00"))
    return when.astimezone(dt.UTC)


def main(argv=None, *, runner=subprocess.run, home=None, stdout=None, now=None):
    stdout = stdout or sys.stdout
    parser = argparse.ArgumentParser(prog="scripts.aws.v1.mfa_session", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--code", required=True, help="the current 6-digit MFA code")
    parser.add_argument("--duration", type=int, default=DEFAULT_DURATION,
                        help=f"seconds, {MIN_DURATION}..{DEFAULT_DURATION} (default 36 h)")
    parser.add_argument("--base-profile", default=credentials.BASE_PROFILE)
    parser.add_argument("--profile", default=credentials.MFA_PROFILE,
                        help="profile to write (never 'default')")
    parser.add_argument("--serial", help="MFA device ARN when the user has several")
    parser.add_argument("--account", help="12 digits: confirm the new session resolves to it")
    args = parser.parse_args(argv)
    for name in (args.base_profile, args.profile):
        if name == "default" or not PROFILE_PATTERN.fullmatch(name):
            parser.error("Explicit non-default profile names are required")
    if args.base_profile == args.profile:
        parser.error("The session profile must differ from the long-term base profile")
    if not re.fullmatch(r"[0-9]{6}", args.code):
        parser.error("--code must be exactly six digits")
    if not MIN_DURATION <= args.duration <= DEFAULT_DURATION:
        parser.error(f"--duration must be {MIN_DURATION}..{DEFAULT_DURATION}")
    if args.account and not re.fullmatch(r"[0-9]{12}", args.account):
        parser.error("--account must be 12 digits")
    if args.serial and not _SERIAL.fullmatch(args.serial):
        parser.error("--serial must be a virtual MFA device ARN")
    try:
        serial = find_serial(runner, args.base_profile, args.serial)
        found = session_credentials(runner, args.base_profile, serial, args.code, args.duration)
        write_profile(args.profile, found, home=home)
        if args.account:
            who = _aws(runner, args.profile, ["sts", "get-caller-identity"])
            if who.get("Account") != args.account:
                raise OperationError("The new session resolves to a different account")
    except (OperationError, OSError, configparser.Error) as error:
        message = str(error) if isinstance(error, OperationError) else "could not write profile"
        print(f"mfa_session failed: {message}", file=sys.stderr)
        return 1
    expiry = _expiry(found)
    hours = (expiry - (now or dt.datetime.now(dt.UTC))).total_seconds() / 3600
    del found
    print(f"Profile {args.profile} holds an MFA session until "
          f"{expiry.strftime('%Y-%m-%dT%H:%M:%SZ')} ({hours:.1f} h)", file=stdout)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
