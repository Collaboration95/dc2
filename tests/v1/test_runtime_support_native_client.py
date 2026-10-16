"""The Lambda-only SSM client path, exercised without any network or credentials."""

from unittest.mock import Mock, patch

import pytest

from runtime_support.settings import RuntimeConfigurationError, runtime_values

ARN = "arn:aws:ssm:ap-southeast-1:111122223333:parameter/dc2/media/postgres"
LAMBDA_ENV = {
    "MEDIA_POSTGRES_DSN_PARAMETER_ARN": ARN,
    "AWS_LAMBDA_FUNCTION_NAME": "media",
    "AWS_ACCESS_KEY_ID": "id",
    "AWS_SECRET_ACCESS_KEY": "key",
    "AWS_SESSION_TOKEN": "token",
}


def test_region_that_differs_from_the_secret_reference_is_refused_before_any_client():
    with patch("boto3.Session") as session:
        with pytest.raises(RuntimeConfigurationError, match="region"):
            runtime_values("MEDIA", environ={**LAMBDA_ENV, "AWS_REGION": "us-east-1"})
    session.assert_not_called()


def test_native_client_uses_only_the_execution_role_set_and_is_closed_after_use():
    client = Mock()
    client.get_parameter.return_value = {
        "Parameter": {"ARN": ARN, "Type": "SecureString", "Value": "private-dsn"}
    }
    with patch("boto3.Session") as session:
        session.return_value.client.return_value = client
        values = runtime_values("MEDIA", environ={**LAMBDA_ENV, "AWS_REGION": "ap-southeast-1"})
    assert values == {"postgres_dsn": "private-dsn"}
    # No profile name is passed, so a developer profile cannot be discovered.
    assert session.call_args.kwargs == {
        "aws_access_key_id": "id",
        "aws_secret_access_key": "key",
        "aws_session_token": "token",
        "region_name": "ap-southeast-1",
    }
    config = session.return_value.client.call_args.kwargs["config"]
    assert config.use_dualstack_endpoint is True
    client.close.assert_called_once_with()


def test_failed_lookup_still_closes_the_native_client_and_hides_the_sdk_error():
    client = Mock()
    client.get_parameter.side_effect = RuntimeError("https://ssm.example/secret-bearing-url")
    with patch("boto3.Session") as session:
        session.return_value.client.return_value = client
        with pytest.raises(RuntimeConfigurationError) as raised:
            runtime_values("MEDIA", environ=LAMBDA_ENV)
    assert "secret-bearing-url" not in str(raised.value)
    assert raised.value.__cause__ is None
    client.close.assert_called_once_with()
