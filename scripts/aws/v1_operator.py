"""Scoped, read-only V1 account preflight. Never loads the default AWS profile.

Run from the intended checkout: python -m scripts.aws.v1_operator --profile <name>
--account <12 digits> --operator-arn <IAM ARN> --output-dir <ignored private directory>.
The same values may come from DC2_AWS_PROFILE, DC2_AWS_ACCOUNT and DC2_AWS_OPERATOR_ARN.
They are operator input, not source: a hard-coded account would let a stale checkout
verify (and then mutate) the wrong identity. Receipts contain account/resource
metadata, not secrets.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any

REGION = "ap-southeast-1"
NAMESPACE = os.environ.get("DC2_V1_NAMESPACE", "dc2-v1-20261015t1146")
# Empty until configure()/environment supplies them; every AWS call refuses to run unscoped.
PROFILE = os.environ.get("DC2_AWS_PROFILE", "")
ACCOUNT = os.environ.get("DC2_AWS_ACCOUNT", "")
OPERATOR = os.environ.get("DC2_AWS_OPERATOR_ARN", "")


def configure(profile: str, account: str, operator_arn: str) -> None:
    """Bind the explicit operator scope. Rejects defaults and mismatched identities."""
    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", profile or "") or profile == "default":
        raise ValueError("An explicit non-default AWS profile is required")
    if not re.fullmatch(r"[0-9]{12}", account or ""):
        raise ValueError("An explicit 12-digit account is required")
    user = rf"arn:aws:iam::{account}:user/[A-Za-z0-9+=,.@_/-]{{1,64}}"
    if not re.fullmatch(user, operator_arn or ""):
        raise ValueError("Operator ARN must be an IAM user in the explicit account")
    global PROFILE, ACCOUNT, OPERATOR
    PROFILE, ACCOUNT, OPERATOR = profile, account, operator_arn


def add_scope_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--profile", default=os.environ.get("DC2_AWS_PROFILE"))
    parser.add_argument("--account", default=os.environ.get("DC2_AWS_ACCOUNT"))
    parser.add_argument("--operator-arn", default=os.environ.get("DC2_AWS_OPERATOR_ARN"))


def apply_scope(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    try:
        configure(args.profile, args.account, args.operator_arn)
    except ValueError as error:
        parser.error(str(error))


def sanitized_environment() -> dict[str, str]:
    """Exclude inherited credentials, endpoint overrides, and alternate profiles."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("AWS_")}
    env.update(
        AWS_EC2_METADATA_DISABLED="true",
        AWS_PAGER="",
        AWS_RETRY_MODE="standard",
        AWS_MAX_ATTEMPTS="2",
        AWS_IGNORE_CONFIGURED_ENDPOINT_URLS="true",
    )
    return env


def aws(args: list[str]) -> dict[str, Any]:
    if not PROFILE or not ACCOUNT:
        raise RuntimeError("Explicit profile and account are required; no default profile")
    command = [
        "aws",
        "--profile",
        PROFILE,
        "--region",
        REGION,
        "--no-cli-pager",
        "--output",
        "json",
        "--cli-connect-timeout",
        "10",
        "--cli-read-timeout",
        "20",
        *args,
    ]
    observed = dt.datetime.now(dt.UTC).isoformat()
    try:
        result = subprocess.run(
            command,
            env=sanitized_environment(),
            capture_output=True,
            text=True,
            timeout=55,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return {
            "observed_at": observed,
            "command": command,
            "returncode": 124,
            "data": None,
            "error": "bounded AWS command timeout",
        }
    return {
        "observed_at": observed,
        "command": command,
        "returncode": result.returncode,
        "data": json.loads(result.stdout or "{}") if result.returncode == 0 else None,
        "error": result.stderr.strip() if result.returncode else None,
    }


def verify_identity() -> dict[str, Any]:
    receipt = aws(["sts", "get-caller-identity"])
    identity = receipt.get("data") or {}
    if (
        receipt["returncode"] != 0
        or identity.get("Account") != ACCOUNT
        or identity.get("Arn") != OPERATOR
    ):
        raise RuntimeError("DC2 scoped AWS identity verification failed; no further calls")
    return receipt


def private_receipt(directory: Path, name: str, receipt: dict[str, Any]) -> None:
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = directory / f"aws-{name}.json"
    # Set restrictive permissions before writing, including when replacing old receipts.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as stream:
        os.fchmod(stream.fileno(), 0o600)
        json.dump(receipt, stream, indent=2)
        stream.write("\n")


def queries() -> dict[str, list[str]]:
    today = dt.datetime.now(dt.UTC).date()
    return {
        "engines": [
            "rds",
            "describe-db-engine-versions",
            "--engine",
            "aurora-postgresql",
            "--query",
            "DBEngineVersions[].{Version:EngineVersion,"
            "Modes:SupportedEngineModes,Serverless:ServerlessV2FeaturesSupport}",
        ],
        "serverless-orderable": [
            "rds",
            "describe-orderable-db-instance-options",
            "--engine",
            "aurora-postgresql",
            "--engine-version",
            "16.8",
            "--db-instance-class",
            "db.serverless",
        ],
        "fargate-quota": [
            "service-quotas",
            "get-service-quota",
            "--service-code",
            "fargate",
            "--quota-code",
            "L-3032A538",
        ],
        "lambda-quota": ["lambda", "get-account-settings"],
        "inventory": [
            "resourcegroupstaggingapi",
            "get-resources",
            "--tag-filters",
            f"Key=Project,Values={NAMESPACE}",
        ],
        "environment-inventory": [
            "resourcegroupstaggingapi",
            "get-resources",
            "--tag-filters",
            "Key=Project,Values=dc2",
            f"Key=Environment,Values={NAMESPACE}",
        ],
        "stacks": [
            "cloudformation",
            "list-stacks",
            "--query",
            f"StackSummaries[?starts_with(StackName, `{NAMESPACE}`)]",
        ],
        "billing": [
            "ce",
            "get-cost-and-usage",
            "--time-period",
            f"Start={today - dt.timedelta(days=1)},End={today}",
            "--granularity",
            "DAILY",
            "--metrics",
            "UnblendedCost",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    add_scope_arguments(parser)
    args = parser.parse_args()
    apply_scope(parser, args)
    private_receipt(args.output_dir, "identity", verify_identity())
    failures = []
    for name, command in queries().items():
        receipt = aws(command)
        private_receipt(args.output_dir, name, receipt)
        print(f"{name}: {'OBSERVED' if receipt['returncode'] == 0 else 'UNAVAILABLE'}")
        if receipt["returncode"]:
            failures.append(name)
    private_receipt(
        args.output_dir,
        "preflight-summary",
        {
            "account": ACCOUNT,
            "region": REGION,
            "profile": PROFILE,
            "namespace": NAMESPACE,
            "unavailable": failures,
            "mutations": [],
            "cloud_acceptance": "NOT_RUN",
        },
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
