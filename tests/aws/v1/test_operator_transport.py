"""Argument contracts for the operator SDK bridge; fake clients, no AWS calls."""

import io
import json
import time
from types import SimpleNamespace

import pytest

from scripts.aws.transport import OperationError
from scripts.aws.v1.transport import OPERATIONS, OperatorTransport, validate_arguments

ACCOUNT = "123456789012"
UUID = "11111111-2222-3333-4444-555555555555"
INVOKE = {"FunctionName": "f", "Qualifier": "live", "InvocationType": "RequestResponse"}


def client(**methods):
    config = SimpleNamespace(retries={"total_max_attempts": 1}, connect_timeout=2, read_timeout=3)
    meta = SimpleNamespace(region_name="ap-southeast-1", config=config)
    return SimpleNamespace(meta=meta, **methods)


def transport(**clients):
    return OperatorTransport(
        clients, identity={"Account": ACCOUNT}, account=ACCOUNT, region="ap-southeast-1"
    )


def deadline():
    return time.monotonic() + 30


FN = {"FunctionName": "f"}
STAGE = {"ApiId": "abc123def", "StageName": "$default"}
VALID = [
    ("lambda", "put-function-concurrency", {**FN, "ReservedConcurrentExecutions": 0}),
    ("lambda", "delete-function-concurrency", {"FunctionName": "f"}),
    ("lambda", "get-function-concurrency", {"FunctionName": "f"}),
    ("lambda", "get-account-settings", {}),
    ("lambda", "list-event-source-mappings", {"FunctionName": "f"}),
    ("lambda", "update-event-source-mapping", {"UUID": UUID, "Enabled": False}),
    ("events", "enable-rule", {"Name": "rule"}),
    ("events", "disable-rule", {"Name": "rule"}),
    ("events", "describe-rule", {"Name": "rule"}),
    ("ecs", "list-tasks", {"cluster": "c", "desiredStatus": "RUNNING"}),
    ("ecs", "describe-tasks", {"cluster": "c", "tasks": ["arn:aws:ecs:r:1:task/c/abc"]}),
    ("ecs", "stop-task", {"cluster": "c", "task": "abc", "reason": "session close"}),
    (
        "logs",
        "get-log-events",
        {
            "logGroupName": "/dc2/tasks",
            "logStreamName": "Media/m/abc",
            "startFromHead": True,
            "nextToken": "f/1",
        },
    ),
    (
        "apigatewayv2",
        "update-stage",
        {**STAGE, "DefaultRouteSettings": {"ThrottlingBurstLimit": 0, "ThrottlingRateLimit": 0}},
    ),
]


@pytest.mark.parametrize("service,operation,payload", VALID)
def test_every_session_operation_accepts_its_documented_arguments(service, operation, payload):
    validate_arguments(service, operation, payload)


@pytest.mark.parametrize(
    "service,operation,payload",
    [
        ("lambda", "put-function-concurrency", {"FunctionName": "f"}),
        ("lambda", "put-function-concurrency", {**FN, "ReservedConcurrentExecutions": -1}),
        ("lambda", "put-function-concurrency", {**FN, "ReservedConcurrentExecutions": True}),
        ("lambda", "delete-function-concurrency", {"FunctionName": "f", "Qualifier": "live"}),
        ("lambda", "update-event-source-mapping", {"UUID": "not-a-uuid", "Enabled": True}),
        ("lambda", "update-event-source-mapping", {"UUID": UUID, "Enabled": "true"}),
        ("lambda", "update-event-source-mapping", {"UUID": UUID, "Enabled": True, "BatchSize": 1}),
        ("lambda", "invoke", {**FN, "InvocationType": "RequestResponse", "Payload": {}}),
        ("lambda", "invoke", {**INVOKE, "InvocationType": "Event", "Payload": {}}),
        ("events", "enable-rule", {"Name": "../x"}),
        ("events", "put-rule", {"Name": "r"}),
        ("ecs", "list-tasks", {"cluster": "c", "desiredStatus": "PENDING"}),
        ("ecs", "stop-task", {"cluster": "c"}),
        ("logs", "get-log-events", {"logGroupName": "g"}),
        ("logs", "get-log-events", {"logGroupName": "g", "logStreamName": "s", "limit": 0}),
        ("logs", "filter-log-events", {"logGroupName": "g"}),
        ("logs", "delete-log-group", {"logGroupName": "g"}),
        ("ecs", "run-task", {"cluster": "c", "taskDefinition": "d", "launchType": "EC2"}),
        (
            "apigatewayv2",
            "update-stage",
            {**STAGE, "DefaultRouteSettings": {"DetailedMetricsEnabled": True}},
        ),
        ("sqs", "purge-queue", {"QueueUrl": "x"}),
        ("rds", "stop-db-cluster", {}),
    ],
)
def test_malformed_extra_or_unsupported_operations_are_refused(service, operation, payload):
    with pytest.raises(OperationError):
        validate_arguments(service, operation, payload)


def test_destructive_and_database_operations_are_not_in_the_allowlist():
    names = {op for ops in OPERATIONS.values() for op in ops}
    assert not names & {"purge-queue", "stop-db-cluster", "delete-function", "delete-bucket"}
    assert "sqs" not in OPERATIONS and "rds" not in OPERATIONS


def test_invalid_arguments_never_reach_the_sdk():
    calls = []
    sdk = client(put_function_concurrency=lambda **kw: calls.append(kw))
    with pytest.raises(OperationError):
        transport(**{"lambda": sdk}).call(
            "lambda",
            "put-function-concurrency",
            {"FunctionName": "f", "ReservedConcurrentExecutions": 1, "Extra": 1},
            deadline=deadline(),
        )
    assert calls == []


def test_invoke_serializes_payload_and_returns_bounded_parsed_response_without_logs():
    seen = {}

    def invoke(**kwargs):
        seen.update(kwargs)
        return {
            "StatusCode": 200,
            "FunctionError": "Unhandled",
            "LogResult": "private",
            "Payload": io.BytesIO(json.dumps({"statusCode": 200}).encode()),
        }

    result = transport(**{"lambda": client(invoke=invoke)}).call(
        "lambda", "invoke", {**INVOKE, "Payload": {"rawPath": "/health"}}, deadline=deadline()
    )
    assert json.loads(seen["Payload"]) == {"rawPath": "/health"}
    assert result == {"StatusCode": 200, "FunctionError": True, "Payload": {"statusCode": 200}}


def test_oversized_invoke_response_is_rejected():
    big = io.BytesIO(b"x" * 1_000_001)
    sdk = client(invoke=lambda **kw: {"StatusCode": 200, "Payload": big})
    with pytest.raises(OperationError):
        transport(**{"lambda": sdk}).call(
            "lambda", "invoke", {**INVOKE, "Payload": {}}, deadline=deadline()
        )


@pytest.mark.parametrize("account", ["", "866", None, "abcdefghijkl"])
def test_account_must_be_an_explicit_twelve_digit_input(account):
    with pytest.raises(OperationError, match="12-digit"):
        OperatorTransport(
            {}, identity={"Account": account}, account=account, region="ap-southeast-1"
        )


def test_a_copied_task_definition_may_keep_its_task_role_but_gains_no_other_field():
    base = {
        "family": "f",
        "containerDefinitions": [{}],
        "cpu": "256",
        "memory": "512",
        "networkMode": "awsvpc",
        "requiresCompatibilities": ["FARGATE"],
        "executionRoleArn": "arn:aws:iam::123456789012:role/e",
    }
    validate_arguments(
        "ecs",
        "register-task-definition",
        {**base, "taskRoleArn": "arn:aws:iam::123456789012:role/t"},
    )
    with pytest.raises(OperationError):
        validate_arguments("ecs", "register-task-definition", {**base, "volumes": []})
