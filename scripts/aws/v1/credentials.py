"""Which kind of credential a profile holds, without ever returning or printing it.

Why this exists: `FlickPondRequireMFA` denies a call when `aws:MultiFactorAuthPresent` is
`false` (a `Bool`, not a `BoolIfExists`, condition). A direct CLI call made with the long-term
`AKIA` key carries no MFA key at all, so it is *not* denied, which makes the profile look fine.
CloudFormation then makes its own calls on the caller's behalf with the key set to `false`, and
those are denied: that is what stopped `s3:CreateBucket` on 2026-10-15 and rolled the bootstrap
stack back. A pre-flight that only checks "can I call STS" would pass and the deploy would die
twenty minutes in. So the pipeline refuses long-term credentials up front for every step that
drives CloudFormation, and tells the operator how to mint an MFA-backed session instead.

Nothing here reads the secret half of a key. The probe asks the AWS CLI to export the profile's
credentials, keeps the first four characters of the access key id (its type prefix) and whether
a session token exists, and drops the rest.
"""

import configparser
import datetime as dt
import json
import subprocess
from pathlib import Path

from scripts.aws.transport import OperationError

MFA_PROFILE = "dc2-project2-mfa"
BASE_PROFILE = "dc2-project2"
# Non-standard key written by mfa_session: botocore and the CLI ignore keys they do not know,
# and an STS session token carries its expiry nowhere the CLI will export it from a static file.
EXPIRY_KEY = "x_dc2_session_expiration"
FIX = "run `python -m scripts.aws.v1.mfa_session --code NNNNNN` (make aws-mfa-session CODE=...)"
# A deploy takes 50-80 minutes; a session about to lapse is worth a warning, not a refusal,
# because a resumed run only needs a few minutes of it.
WARN_BELOW_SECONDS = 3600


def credentials_file(home=None):
    return Path(home or Path.home()) / ".aws" / "credentials"


def config_file(home=None):
    return Path(home or Path.home()) / ".aws" / "config"


def _parse_time(text):
    try:
        moment = dt.datetime.fromisoformat(str(text).replace("Z", "+00:00"))
    except ValueError:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=dt.UTC)


def stored_expiry(profile, *, home=None):
    """The expiry mfa_session recorded for this profile, or None."""
    parser = configparser.RawConfigParser()
    try:
        parser.read(credentials_file(home))
        return _parse_time(parser.get(profile, EXPIRY_KEY))
    except (configparser.Error, OSError):
        return None


def probe(profile, *, runner=subprocess.run, environ=None, home=None, now=None):
    """Classify the profile's credentials: {"kind", "expires_at", "remaining_seconds"}.

    kind is "long-term" (access key id AKIA...), "session" (ASIA... with a token) or "unknown".
    The CLI call is local: it resolves the profile and makes no network request for a static key.
    """
    from scripts.aws.v1_operator import sanitized_environment

    env = dict(sanitized_environment() if environ is None else environ)
    try:
        done = runner(
            ["aws", "configure", "export-credentials", "--profile", profile, "--format", "process"],
            env=env, capture_output=True, text=True, timeout=30, check=False,
        )
        data = json.loads(done.stdout) if done.returncode == 0 else {}
    except (OSError, ValueError, subprocess.SubprocessError):
        data = {}
    key = data.get("AccessKeyId", "") if isinstance(data, dict) else ""
    kind = "unknown"
    if key.startswith("AKIA"):
        kind = "long-term"
    elif key.startswith("ASIA") and data.get("SessionToken"):
        kind = "session"
    expires = _parse_time(data.get("Expiration")) if isinstance(data, dict) else None
    if kind == "session" and expires is None:
        expires = stored_expiry(profile, home=home)
    del data, key  # nothing secret leaves this function
    remaining = None
    if expires is not None:
        remaining = (expires - (now or dt.datetime.now(dt.UTC))).total_seconds()
    return {
        "kind": kind,
        "expires_at": expires.strftime("%Y-%m-%dT%H:%M:%SZ") if expires else None,
        "remaining_seconds": round(remaining) if remaining is not None else None,
    }


def assess(profile, info):
    """(status, detail) for a probe result: pass | warn | blocker."""
    if info["kind"] == "long-term":
        return "blocker", (
            f"Profile {profile} holds long-term credentials (AKIA...). Calls CloudFormation makes "
            "on your behalf carry aws:MultiFactorAuthPresent=false and FlickPondRequireMFA denies "
            f"them (this killed s3:CreateBucket on 2026-10-15). First {FIX}, then pass "
            f"--profile {MFA_PROFILE}"
        )
    remaining = info["remaining_seconds"]
    if remaining is not None and remaining <= 0:
        return "blocker", f"The MFA session behind {profile} has expired; {FIX}"
    if info["kind"] == "unknown":
        return "warn", (
            f"Cannot classify the credentials behind {profile}; they will be used as-is. "
            "A long-term key would fail at the first CloudFormation-driven step"
        )
    if remaining is not None and remaining < WARN_BELOW_SECONDS:
        return "warn", f"The MFA session behind {profile} expires in {remaining // 60} minutes"
    return "pass", ""


def require_mfa_session(profile, probe_result=None, **kwargs):
    """Raise OperationError unless the profile is an unexpired session (or unclassifiable)."""
    info = probe_result or probe(profile, **kwargs)
    status, detail = assess(profile, info)
    if status == "blocker":
        raise OperationError(detail)
    return info
