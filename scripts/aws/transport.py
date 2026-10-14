"""Offline AWS CLI plans and explicitly isolated emulator subprocess transport.

There is deliberately no production execution path in this module. Deadlines use
monotonic seconds, not subprocess-relative timeouts renewed on each request.
"""

import json
import math
import re
import subprocess
import time
from urllib.parse import urlsplit

OPERATIONS = {
    "ecs": {
        "list-tasks",
        "describe-tasks",
        "run-task",
        "stop-task",
        "describe-services",
        "update-service",
        "describe-task-definition",
    },
    "ec2": {
        "start-instances",
        "stop-instances",
        "describe-instances",
        "terminate-instances",
        "describe-volumes",
        "delete-volume",
        "describe-addresses",
    },
    "cloudfront": {"get-distribution-config", "update-distribution", "get-distribution"},
    "ecr": {"describe-images", "batch-get-image"},
}
SECRET_KEY = re.compile(
    r"(password|secret|cookie|authorization|dsn|access.?key|session.?token)", re.I
)


class OperationError(RuntimeError):
    """Safe failure: never includes a response, payload or subprocess stderr."""


def config_value(config, key, default=None):
    return config.get(key, default) if isinstance(config, dict) else getattr(config, key, default)


def safe_record(value):
    """Reject secret-bearing data before private persistence or command rendering."""
    if isinstance(value, dict):
        if (
            SECRET_KEY.search(str(value.get("name", "")))
            or "HeaderValue" in value
            or "CustomHeaders" in value
            and value["CustomHeaders"].get("Quantity", 0)
        ):
            raise OperationError("Private header or credential override refused")
        for key, item in value.items():
            if SECRET_KEY.search(str(key)):
                raise OperationError("Secret-bearing field refused")
            safe_record(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            safe_record(item)
    elif isinstance(value, str):
        lowered = value.lower()
        if any(
            s in lowered
            for s in (
                "x-amz-signature",
                "x-amz-credential",
                "postgres://",
                "postgresql://",
                "redis://",
                "bearer ",
                "access_token=",
            )
        ):
            raise OperationError("Secret-bearing value refused")
        if SECRET_KEY.search(value) and ("=" in value or value.startswith("AWS_")):
            raise OperationError("Credential override refused")
    elif isinstance(value, float) and not math.isfinite(value):
        raise OperationError("Nonfinite record refused")
    elif value is not None and not isinstance(value, (int, float, bool)):
        raise OperationError("Non-JSON record refused")


def remaining(deadline, clock=time.monotonic):
    if deadline is None or not math.isfinite(deadline) or deadline <= clock():
        raise OperationError("A live finite deadline is required")
    return deadline - clock()


def command_plan(service, operation, payload, *, region):
    """Frozen AWS CLI JSON boundary; plans are argv arrays, never shell strings."""
    if service not in OPERATIONS or operation not in OPERATIONS[service]:
        raise OperationError("Unsupported control-plane operation")
    if not re.fullmatch(r"[a-z]{2}-[a-z]+-\d", region):
        raise OperationError("Invalid region")
    safe_record(payload)
    return [
        "aws",
        service,
        operation,
        "--region",
        region,
        "--no-cli-pager",
        "--output",
        "json",
        "--cli-input-json",
        json.dumps(payload, sort_keys=True, separators=(",", ":")),
    ]


class CLITransport:
    def __init__(self, config, *, runner=subprocess.run, clock=time.monotonic):
        self.config, self.runner, self.clock = config, runner, clock

    def plan(self, service, operation, payload):
        return command_plan(
            service,
            operation,
            payload,
            region=config_value(self.config, "region", "ap-southeast-1"),
        )

    def call(self, service, operation, payload, *, deadline=None):
        argv = self.plan(service, operation, payload)
        if config_value(self.config, "mode", "plan") != "emulator":
            raise OperationError("Production execution disabled; plan only")
        endpoint = config_value(self.config, "endpoint_url", "")
        parts = urlsplit(endpoint)
        if (
            parts.scheme != "http"
            or parts.hostname not in {"127.0.0.1", "::1"}
            or not parts.port
            or parts.username
            or parts.password
            or parts.query
            or parts.fragment
            or parts.path not in {"", "/"}
        ):
            raise OperationError("Explicit numeric loopback emulator endpoint required")
        # Replace the entire environment: no inherited profiles, keys or metadata.
        env = {
            "PATH": "/usr/local/bin:/usr/bin:/bin",
            "AWS_ACCESS_KEY_ID": "testing",
            "AWS_SECRET_ACCESS_KEY": "testing",
            "AWS_SESSION_TOKEN": "testing",
            "AWS_EC2_METADATA_DISABLED": "true",
            "AWS_CONFIG_FILE": "/dev/null",
            "AWS_SHARED_CREDENTIALS_FILE": "/dev/null",
            "AWS_CLI_AUTO_PROMPT": "off",
            "AWS_MAX_ATTEMPTS": "1",
            "AWS_DEFAULT_REGION": config_value(self.config, "region"),
        }
        try:
            result = self.runner(
                argv + ["--endpoint-url", endpoint],
                env=env,
                capture_output=True,
                text=True,
                check=False,
                timeout=remaining(deadline, self.clock),
            )
            if result.returncode:
                raise OperationError("Emulator command failed")
            response = json.loads(result.stdout)
            if not isinstance(response, dict):
                raise OperationError("Invalid transport response")
            return response
        except (subprocess.SubprocessError, OSError, ValueError):
            raise OperationError("Emulator transport failed or timed out") from None


def main():
    import argparse
    from pathlib import Path

    parser = argparse.ArgumentParser(description="Render a future AWS CLI plan; never executes")
    parser.add_argument("service", choices=tuple(OPERATIONS))
    parser.add_argument("operation")
    parser.add_argument("--payload", type=Path, required=True)
    parser.add_argument("--region", required=True)
    args = parser.parse_args()
    print(
        json.dumps(
            command_plan(
                args.service,
                args.operation,
                json.loads(args.payload.read_text()),
                region=args.region,
            )
        )
    )


if __name__ == "__main__":
    main()
