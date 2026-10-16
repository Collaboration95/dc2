"""No AWS calls: verify the operator's account and credential isolation boundary."""
import json
import os

import pytest

from scripts.aws import v1_operator as operator

DUMMY_ACCOUNT = "123456789012"
DUMMY_OPERATOR = f"arn:aws:iam::{DUMMY_ACCOUNT}:user/operator"


@pytest.fixture(autouse=True)
def scope(monkeypatch):
    # Identity is operator input; the checkout contains no real account to fall back on.
    monkeypatch.setattr(operator, "PROFILE", "test-profile")
    monkeypatch.setattr(operator, "ACCOUNT", DUMMY_ACCOUNT)
    monkeypatch.setattr(operator, "OPERATOR", DUMMY_OPERATOR)


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
    (operator.ACCOUNT, f"arn:aws:iam::{DUMMY_ACCOUNT}:user/other"),
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


def test_empty_successful_mutation_response_is_valid(monkeypatch):
    monkeypatch.setattr(operator.subprocess, "run", lambda *a, **k: type(
        "Result", (), {"returncode": 0, "stdout": "", "stderr": ""})())
    assert operator.aws(["cloudformation", "execute-change-set"])["data"] == {}


def test_unscoped_calls_are_refused_without_running_the_cli(monkeypatch):
    monkeypatch.setattr(operator, "PROFILE", "")
    monkeypatch.setattr(operator.subprocess, "run", lambda *a, **k: pytest.fail("ran aws"))
    with pytest.raises(RuntimeError, match="no default profile"):
        operator.aws(["sts", "get-caller-identity"])


@pytest.mark.parametrize("profile,account,arn", [
    ("default", DUMMY_ACCOUNT, DUMMY_OPERATOR),
    ("", DUMMY_ACCOUNT, DUMMY_OPERATOR),
    ("p", "123", DUMMY_OPERATOR),
    ("p", DUMMY_ACCOUNT, "arn:aws:iam::999999999999:user/operator"),
    ("p", DUMMY_ACCOUNT, f"arn:aws:iam::{DUMMY_ACCOUNT}:role/operator"),
])
def test_configure_rejects_default_profile_and_identity_outside_the_account(
    profile, account, arn
):
    with pytest.raises(ValueError):
        operator.configure(profile, account, arn)


def test_source_contains_no_concrete_account_or_operator_arn():
    from pathlib import Path

    for name in ("v1_operator.py", "v1_foundation.py", "v1/transport.py"):
        text = (Path(operator.__file__).parent / name).read_text()
        assert not any(ch * 12 in text for ch in "0123456789")
        assert "arn:aws:iam::8" not in text and "dc2-project2" not in text
