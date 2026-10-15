"""No AWS calls: verify the operator's account and credential isolation boundary."""
import json
import os

import pytest

from scripts.aws import v1_operator as operator


def test_inherited_aws_credentials_and_endpoints_are_removed(monkeypatch):
    for key in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN",
                "AWS_PROFILE", "AWS_CONFIG_FILE", "AWS_ENDPOINT_URL",
                "AWS_WEB_IDENTITY_TOKEN_FILE"):
        monkeypatch.setenv(key, "wrong-account-input")
    env = operator.sanitized_environment()
    assert "wrong-account-input" not in env.values()
    assert env["AWS_EC2_METADATA_DISABLED"] == "true"
    assert env["AWS_IGNORE_CONFIGURED_ENDPOINT_URLS"] == "true"


@pytest.mark.parametrize("account,arn", [
    ("330599756236", operator.OPERATOR),
    (operator.ACCOUNT, "arn:aws:iam::866865534361:user/other"),
])
def test_wrong_identity_stops_preflight(monkeypatch, account, arn):
    monkeypatch.setattr(operator, "aws", lambda args: {
        "returncode": 0, "data": {"Account": account, "Arn": arn}})
    with pytest.raises(RuntimeError, match="identity verification failed"):
        operator.verify_identity()


def test_receipt_is_private_even_when_existing_file_is_public(tmp_path):
    path = tmp_path / "aws-test.json"
    path.write_text("old")
    path.chmod(0o644)
    operator.private_receipt(tmp_path, "test", {"cloud_acceptance": "NOT_RUN"})
    assert os.stat(path).st_mode & 0o777 == 0o600
    assert json.loads(path.read_text()) == {"cloud_acceptance": "NOT_RUN"}


def test_cli_always_sets_profile_region_and_bounded_timeouts(monkeypatch):
    def run(command, **kwargs):
        assert command[command.index("--profile") + 1] == operator.PROFILE
        assert command[command.index("--region") + 1] == operator.REGION
        assert kwargs["timeout"] == 55
        assert kwargs["env"]["AWS_EC2_METADATA_DISABLED"] == "true"
        return type("Result", (), {"returncode": 0, "stdout": "{}", "stderr": ""})()
    monkeypatch.setattr(operator.subprocess, "run", run)
    assert operator.aws(["sts", "get-caller-identity"])["returncode"] == 0
