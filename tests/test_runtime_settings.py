from unittest.mock import Mock, patch

import pytest

from runtime_support.settings import RuntimeConfigurationError, runtime_values

ARN = "arn:aws:ssm:ap-southeast-1:111122223333:parameter/dc2/media/postgres"


def test_local_settings_never_discover_aws_credentials():
    with patch("runtime_support.settings._native_client") as discover:
        assert runtime_values("MEDIA", environ={"AWS_PROFILE": "other-project"}) == {}
    discover.assert_not_called()


def test_only_owner_references_are_decrypted_and_environment_is_unchanged():
    env = {
        "MEDIA_POSTGRES_DSN_PARAMETER_ARN": ARN,
        "PROCESSING_POSTGRES_DSN_PARAMETER_ARN": "unrelated",
    }
    original = dict(env)
    client = Mock()
    client.get_parameter.return_value = {
        "Parameter": {"ARN": ARN, "Type": "SecureString", "Value": "private-dsn"}
    }
    assert runtime_values("MEDIA", environ=env, ssm_client=client) == {
        "postgres_dsn": "private-dsn"
    }
    client.get_parameter.assert_called_once_with(Name=ARN, WithDecryption=True)
    client.close.assert_not_called()
    assert env == original


def test_profile_credentials_cannot_resolve_production_secrets():
    with pytest.raises(RuntimeConfigurationError, match="native Lambda"):
        runtime_values(
            "MEDIA", environ={"MEDIA_POSTGRES_DSN_PARAMETER_ARN": ARN, "AWS_PROFILE": "default"}
        )


@pytest.mark.parametrize(
    "response",
    [
        {"Parameter": {"ARN": ARN, "Type": "String", "Value": "secret"}},
        {"Parameter": {"ARN": ARN + "-other", "Type": "SecureString", "Value": "secret"}},
        {"Parameter": {"ARN": ARN, "Type": "SecureString", "Value": ""}},
    ],
)
def test_unexpected_parameter_response_is_rejected_without_value_disclosure(response):
    client = Mock()
    client.get_parameter.return_value = response
    with pytest.raises(RuntimeConfigurationError) as error:
        runtime_values(
            "MEDIA", environ={"MEDIA_POSTGRES_DSN_PARAMETER_ARN": ARN}, ssm_client=client
        )
    assert "secret" not in str(error.value)
    assert error.value.__suppress_context__


def test_sdk_failure_does_not_expose_response_data():
    client = Mock()
    client.get_parameter.side_effect = RuntimeError("password=do-not-log")
    with pytest.raises(RuntimeConfigurationError) as error:
        runtime_values(
            "MEDIA", environ={"MEDIA_POSTGRES_DSN_PARAMETER_ARN": ARN}, ssm_client=client
        )
    assert "do-not-log" not in str(error.value)
    assert error.value.__suppress_context__


def test_cross_account_parameter_set_fails_before_network():
    env = {
        "MEDIA_POSTGRES_DSN_PARAMETER_ARN": ARN,
        "MEDIA_JWT_SECRET_PARAMETER_ARN": ARN.replace("111122223333", "444455556666"),
    }
    client = Mock()
    with pytest.raises(RuntimeConfigurationError, match="one account"):
        runtime_values("MEDIA", environ=env, ssm_client=client)
    client.get_parameter.assert_not_called()
