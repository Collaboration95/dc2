"""Explicit operator-only SDK bridge. Importing this module performs no AWS calls.

The legacy scripts.aws.transport remains offline-only. Pass already scoped SDK
clients here; there is deliberately no implicit boto3 session/profile discovery.
Every operation has an argument contract: a typo or an unexpected field (a stray
purge, a cross-account ARN, an unbounded read) is refused before an SDK request.
"""

import json
import re
import time

from scripts.aws.transport import OperationError, remaining, safe_record

REGION = "ap-southeast-1"
_ACCOUNT = re.compile(r"[0-9]{12}")
_FUNCTION = re.compile(r"[A-Za-z0-9-_:.]{1,140}")
_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
_STAGE = re.compile(r"[A-Za-z0-9_$-]{1,128}")
_API = re.compile(r"[a-z0-9]{6,20}")
_RULE = re.compile(r"[A-Za-z0-9._-]{1,64}")
_TASK = re.compile(r"[A-Za-z0-9:/_.-]{1,255}")
_LOG_NAME = re.compile(r"[A-Za-z0-9_./#-]{1,512}")
# Bounded replies keep a malformed function from exhausting operator memory.
MAX_INVOKE_PAYLOAD = 1_000_000


def _text(pattern):
    return lambda v: isinstance(v, str) and pattern.fullmatch(v) is not None


def _integer(low, high):
    return lambda v: type(v) is int and low <= v <= high


def _boolean(v):
    return type(v) is bool


def _string_list(low, high, pattern=_TASK):
    return lambda v: (
        isinstance(v, list)
        and low <= len(v) <= high
        and all(isinstance(i, str) and pattern.fullmatch(i) for i in v)
    )


def _any(_):
    return True


def _object(v):
    return isinstance(v, dict)


def _route_settings(v):
    # Only the throttle pair is operator-controlled; everything else stays as deployed.
    return (
        isinstance(v, dict)
        and v.keys() == {"ThrottlingBurstLimit", "ThrottlingRateLimit"}
        and _integer(0, 10_000)(v["ThrottlingBurstLimit"])
        and _integer(0, 10_000)(v["ThrottlingRateLimit"])
    )


def _invoke_type(v):
    # Asynchronous Event invocations would hide failures from readiness/repair.
    return v == "RequestResponse"


FUNCTION = _text(_FUNCTION)
CLUSTER = _text(_TASK)
# name -> (required, optional) field validators
OPERATIONS = {
    "lambda": {
        "get-alias": ({"FunctionName": FUNCTION, "Name": FUNCTION}, {}),
        "update-alias": (
            {"FunctionName": FUNCTION, "Name": FUNCTION, "FunctionVersion": FUNCTION},
            {"RevisionId": _any},
        ),
        "get-function": ({"FunctionName": FUNCTION}, {"Qualifier": FUNCTION}),
        "get-function-configuration": ({"FunctionName": FUNCTION}, {"Qualifier": FUNCTION}),
        "update-function-code": (
            {"FunctionName": FUNCTION, "ImageUri": _any},
            {"RevisionId": _any, "Publish": _boolean},
        ),
        "publish-version": (
            {"FunctionName": FUNCTION},
            {"Description": _any, "RevisionId": _any, "CodeSha256": _any},
        ),
        "list-versions-by-function": (
            {"FunctionName": FUNCTION},
            {"Marker": _any, "MaxItems": _integer(1, 50)},
        ),
        "put-function-concurrency": (
            {"FunctionName": FUNCTION, "ReservedConcurrentExecutions": _integer(0, 1000)},
            {},
        ),
        "get-function-concurrency": ({"FunctionName": FUNCTION}, {}),
        "delete-function-concurrency": ({"FunctionName": FUNCTION}, {}),
        "get-account-settings": ({}, {}),
        "list-event-source-mappings": (
            {},
            {"FunctionName": FUNCTION, "Marker": _any, "MaxItems": _integer(1, 100)},
        ),
        "get-event-source-mapping": ({"UUID": _text(_UUID)}, {}),
        "update-event-source-mapping": ({"UUID": _text(_UUID), "Enabled": _boolean}, {}),
        # Qualifier is mandatory so a probe never reaches an unpublished $LATEST.
        "invoke": (
            {
                "FunctionName": FUNCTION,
                "Qualifier": FUNCTION,
                "InvocationType": _invoke_type,
                "Payload": _object,
            },
            {},
        ),
    },
    "events": {
        "enable-rule": ({"Name": _text(_RULE)}, {}),
        "disable-rule": ({"Name": _text(_RULE)}, {}),
        "describe-rule": ({"Name": _text(_RULE)}, {}),
    },
    "apigatewayv2": {
        "get-stage": ({"ApiId": _text(_API), "StageName": _text(_STAGE)}, {}),
        "update-stage": (
            {
                "ApiId": _text(_API),
                "StageName": _text(_STAGE),
                "DefaultRouteSettings": _route_settings,
            },
            {},
        ),
    },
    "ecs": {
        "describe-task-definition": ({"taskDefinition": CLUSTER}, {}),
        "run-task": (
            {
                "cluster": CLUSTER,
                "taskDefinition": CLUSTER,
                "launchType": lambda v: v == "FARGATE",
                "count": _integer(1, 1),
                "clientToken": _any,
                "startedBy": _any,
                "networkConfiguration": _object,
            },
            {"overrides": _object},
        ),
        "describe-tasks": ({"cluster": CLUSTER, "tasks": _string_list(1, 100)}, {}),
        "list-tasks": (
            {"cluster": CLUSTER},
            {
                "desiredStatus": lambda v: v in {"RUNNING", "STOPPED"},
                "nextToken": _any,
                "maxResults": _integer(1, 100),
            },
        ),
        "stop-task": (
            {"cluster": CLUSTER, "task": CLUSTER},
            {"reason": lambda v: isinstance(v, str) and len(v) <= 255},
        ),
        # The cloud-proof latency generator is a temporary Fargate task definition that is
        # deregistered when its run ends; nothing else may register one.
        "register-task-definition": (
            {
                "family": CLUSTER,
                "containerDefinitions": lambda v: isinstance(v, list) and len(v) == 1,
                "cpu": _text(re.compile(r"[0-9]{3,5}")),
                "memory": _text(re.compile(r"[0-9]{3,6}")),
                "networkMode": lambda v: v == "awsvpc",
                "requiresCompatibilities": lambda v: v == ["FARGATE"],
                "executionRoleArn": CLUSTER,
            },
            # taskRoleArn: a release-plan copy of a migration definition keeps its owner role.
            {"runtimePlatform": _object, "tags": _any, "taskRoleArn": CLUSTER},
        ),
        "deregister-task-definition": ({"taskDefinition": CLUSTER}, {}),
    },
    # Read-only: the in-VPC reader parses the result line its own finite task printed.
    "logs": {
        "get-log-events": (
            {"logGroupName": _text(_LOG_NAME), "logStreamName": _text(_LOG_NAME)},
            {"startFromHead": _boolean, "nextToken": _any, "limit": _integer(1, 100)},
        )
    },
}


def validate_arguments(service, operation, payload):
    """Refuse unknown operations and malformed/extra fields before any request."""
    spec = OPERATIONS.get(service, {}).get(operation)
    if spec is None or not isinstance(payload, dict):
        raise OperationError("Unsupported V1 operator operation")
    required, optional = spec
    if required.keys() - payload.keys() or payload.keys() - required.keys() - optional.keys():
        raise OperationError("Operation arguments do not match the V1 contract")
    for key, value in payload.items():
        if not (required.get(key) or optional[key])(value):
            raise OperationError("Operation argument violates the V1 contract")


class OperatorTransport:
    def __init__(self, clients, *, identity, account, region, clock=time.monotonic, budgets=None):
        """budgets maps a service to a larger network allowance (seconds, at most 70).

        A synchronous Lambda invocation can legitimately run for the function timeout
        (60 s) while Aurora resumes; other services keep the strict fifteen seconds.
        """
        # The account is operator input, never source code: a stale constant could point
        # a mutation at the wrong account. It must match a freshly verified STS identity.
        if not isinstance(account, str) or not _ACCOUNT.fullmatch(account) or region != REGION:
            raise OperationError("Explicit 12-digit account and V1 region required")
        if identity.get("Account") != account:
            raise OperationError("Operator must supply freshly verified STS identity")
        if not clients or any(c.meta.region_name != region for c in clients.values()):
            raise OperationError("Explicit regional clients required")
        budgets = budgets or {}
        if any(type(v) not in {int, float} or not 15 < v <= 70 for v in budgets.values()):
            raise OperationError("Extended network budgets must exceed 15 and not exceed 70")
        for service, client in clients.items():
            config = client.meta.config
            if (config.retries or {}).get("total_max_attempts") != 1:
                raise OperationError("SDK retries must be disabled; reconcile writes explicitly")
            if config.connect_timeout + config.read_timeout > budgets.get(service, 15):
                raise OperationError("SDK network timeouts exceed the service budget")
        self.clients, self.clock = clients, clock

    def call(self, service, operation, payload, *, deadline):
        if service not in self.clients:
            raise OperationError("Unsupported V1 release operation")
        validate_arguments(service, operation, payload)
        safe_record(payload)
        # Reserve a full bounded SDK request. No request begins with insufficient budget.
        config = self.clients[service].meta.config
        if remaining(deadline, self.clock) < config.connect_timeout + config.read_timeout:
            raise OperationError("Insufficient request deadline")
        arguments = dict(payload)
        if (service, operation) == ("lambda", "invoke"):
            arguments["Payload"] = json.dumps(arguments["Payload"]).encode()
        try:
            result = getattr(self.clients[service], operation.replace("-", "_"))(**arguments)
            if (service, operation) == ("lambda", "invoke"):
                result = self._invoke_result(result)
            return result
        except Exception:
            # SDK messages can contain private request/response values.
            raise OperationError("V1 operator request failed; reconcile persisted intent") from None

    @staticmethod
    def _invoke_result(result):
        body = result["Payload"].read(MAX_INVOKE_PAYLOAD + 1)
        if len(body) > MAX_INVOKE_PAYLOAD:
            raise OperationError("Invocation response exceeds the bounded size")
        return {
            "StatusCode": result.get("StatusCode"),
            # Presence only: FunctionError detail and logs can carry private values.
            "FunctionError": bool(result.get("FunctionError")),
            "Payload": json.loads(body) if body else None,
        }
