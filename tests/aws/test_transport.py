import json
import subprocess
from types import SimpleNamespace

import pytest
from test_transport_fixtures import clock as clock
from test_transport_fixtures import config as config
from test_transport_fixtures import fake as fake
from test_transport_fixtures import journal as journal

from scripts.aws.transport import CLITransport, OperationError, command_plan, safe_record


def test_production_is_inert(config):
    def forbidden(*a, **k):
        pytest.fail("real command execution attempted")

    for mode in ("plan", "real", "aws", None):
        config["mode"] = mode
        with pytest.raises(OperationError, match="disabled"):
            CLITransport(config, runner=forbidden).call("ecs", "list-tasks", {}, deadline=200)


@pytest.mark.parametrize(
    "endpoint",
    [
        "https://example.com",
        "http://localhost:5000",
        "http://169.254.169.254:80",
        "http://127.0.0.1",
        "http://user:pass@127.0.0.1:5000",
        "http://127.0.0.1:5000/path",
        "http://127.0.0.1:5000?token=x",
    ],
)
def test_emulator_requires_strict_loopback(config, endpoint):
    config.update(mode="emulator", endpoint_url=endpoint)
    with pytest.raises(OperationError, match="loopback"):
        CLITransport(config).call("ecs", "list-tasks", {}, deadline=200)


def test_emulator_replaces_credentials_environment(config, monkeypatch):
    monkeypatch.setenv("AWS_PROFILE", "REAL")
    monkeypatch.setenv("AWS_CONTAINER_CREDENTIALS_RELATIVE_URI", "/REAL")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "PRIVATE-DUMMY")
    config.update(mode="emulator", endpoint_url="http://127.0.0.1:5000")

    def runner(argv, **kw):
        assert kw["timeout"] == 10
        assert kw["env"]["AWS_SECRET_ACCESS_KEY"] == "testing"
        assert kw["env"]["AWS_EC2_METADATA_DISABLED"] == "true"
        assert kw["env"]["AWS_CONFIG_FILE"] == "/dev/null"
        assert kw["env"]["AWS_SHARED_CREDENTIALS_FILE"] == "/dev/null"
        assert "AWS_PROFILE" not in kw["env"]
        assert "AWS_CONTAINER_CREDENTIALS_RELATIVE_URI" not in kw["env"]
        assert "--profile" not in argv
        return SimpleNamespace(returncode=0, stdout=json.dumps({"taskArns": []}))

    assert CLITransport(config, runner=runner, clock=lambda: 100).call(
        "ecs", "list-tasks", {}, deadline=110
    ) == {"taskArns": []}


@pytest.mark.parametrize("failure", ["exit", "json", "timeout"])
def test_redacted_subprocess_failures(config, failure):
    config.update(mode="emulator", endpoint_url="http://127.0.0.1:5000")

    def runner(*a, **k):
        if failure == "timeout":
            raise subprocess.TimeoutExpired("PRIVATE-DUMMY", 10)
        return SimpleNamespace(returncode=1 if failure == "exit" else 0, stdout="PRIVATE-DUMMY")

    with pytest.raises(OperationError) as err:
        CLITransport(config, runner=runner, clock=lambda: 100).call(
            "ecs", "list-tasks", {}, deadline=110
        )
    assert "PRIVATE-DUMMY" not in str(err.value)


@pytest.mark.parametrize(
    "payload",
    [
        {"password": "x"},
        {"value": "postgresql://user:pass@host"},
        {"value": "https://x/?X-Amz-Signature=x"},
    ],
)
def test_private_payload_rejected(payload):
    with pytest.raises(OperationError):
        safe_record(payload)


def test_frozen_cli_mapping_and_finite_deadline(config):
    argv = command_plan("ecs", "run-task", {"count": 1}, region=config["region"])
    assert argv[:3] == ["aws", "ecs", "run-task"]
    assert json.loads(argv[-1]) == {"count": 1}
    with pytest.raises(OperationError):
        command_plan("ssm", "get-parameter", {}, region=config["region"])
    config.update(mode="emulator", endpoint_url="http://127.0.0.1:5000")
    with pytest.raises(OperationError, match="deadline"):
        CLITransport(config, clock=lambda: 100).call("ecs", "list-tasks", {}, deadline=100)
