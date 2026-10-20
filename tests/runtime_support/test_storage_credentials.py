from types import SimpleNamespace

import pytest
from minio.credentials import StaticProvider

from media import storage_credentials as media_credentials
from processing import storage_credentials as processing_credentials

FACADES = (media_credentials, processing_credentials)


def settings(mode="static", access="", secret=""):
    return SimpleNamespace(
        storage_credential_mode=mode, minio_access_key=access, minio_secret_key=secret
    )


@pytest.mark.parametrize("facade", FACADES, ids=("media", "processing"))
def test_owner_facades_create_the_same_native_ecs_provider(monkeypatch, facade):
    monkeypatch.setenv("AWS_CONTAINER_CREDENTIALS_RELATIVE_URI", "/v2/credentials/test")
    monkeypatch.delenv("AWS_CONTAINER_CREDENTIALS_FULL_URI", raising=False)
    monkeypatch.delenv("AWS_WEB_IDENTITY_TOKEN_FILE", raising=False)
    provider = facade.credential_provider(settings("ecs"))
    assert isinstance(provider, facade.ContainerProvider)


@pytest.mark.parametrize("facade", FACADES, ids=("media", "processing"))
@pytest.mark.parametrize(
    ("mode", "access", "secret", "error"),
    [
        ("static", "", "", None),
        ("static", "access", "secret", None),
        ("static", "access", "", "Static storage requires a complete credential pair"),
        ("ecs", "access", "secret", "ECS storage rejects static credential overrides"),
        ("lambda", "", "secret", "Lambda storage rejects static credential overrides"),
        ("profile", "", "", "Invalid storage credential mode"),
    ],
)
def test_owner_facades_keep_the_same_static_and_native_mode_policy(
    facade, mode, access, secret, error
):
    config = settings(mode, access, secret)
    if error:
        with pytest.raises(ValueError, match=f"^{error}$"):
            facade.credential_provider(config)
        return

    provider = facade.credential_provider(config)
    if access:
        assert isinstance(provider, StaticProvider)
    else:
        assert provider is None


@pytest.mark.parametrize("facade", FACADES, ids=("media", "processing"))
def test_lambda_provider_reads_each_rotated_tuple(monkeypatch, facade):
    monkeypatch.setenv("AWS_LAMBDA_FUNCTION_NAME", "flickpond-test")
    monkeypatch.delenv("AWS_CREDENTIAL_EXPIRATION", raising=False)
    provider = facade.credential_provider(settings("lambda"))
    observed = []
    tuples = (("access-A", "secret-A", "token-A"), ("access-B", "secret-B", "token-B"))
    for access, secret, token in tuples:
        monkeypatch.setenv("AWS_ACCESS_KEY_ID", access)
        monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", secret)
        monkeypatch.setenv("AWS_SESSION_TOKEN", token)
        observed.append(provider.retrieve())

    assert [(item.access_key, item.secret_key, item.session_token) for item in observed] == [
        ("access-A", "secret-A", "token-A"),
        ("access-B", "secret-B", "token-B"),
    ]
