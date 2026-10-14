import asyncio
import json
from datetime import UTC, datetime, timedelta
from io import BytesIO
from unittest.mock import Mock
from urllib.parse import parse_qs, urlsplit

import pytest
from minio.credentials import Credentials
from urllib3 import HTTPResponse

from media import storage_credentials as credentials
from media.errors import MediaError
from media.services.storage import Storage


@pytest.fixture
def container(monkeypatch):
    for key in [
        "AWS_CONTAINER_CREDENTIALS_RELATIVE_URI",
        "AWS_CONTAINER_CREDENTIALS_FULL_URI",
        "AWS_WEB_IDENTITY_TOKEN_FILE",
        "AWS_CONTAINER_AUTHORIZATION_TOKEN_FILE",
        "AWS_CONTAINER_AUTHORIZATION_TOKEN",
    ]:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("AWS_CONTAINER_CREDENTIALS_RELATIVE_URI", "/v2/credentials/test")


def temporary(token, seconds=600):
    return Credentials(
        "dummy-access", "dummy-secret", token, datetime.now(UTC) + timedelta(seconds=seconds)
    )


@pytest.mark.parametrize(
    "full",
    [
        "https://evil.test/path",
        "http://169.254.169.254/path",
        "http://localhost/path?token=private",
    ],
)
def test_container_mode_rejects_fallback_and_bad_endpoints(monkeypatch, full):
    monkeypatch.delenv("AWS_CONTAINER_CREDENTIALS_RELATIVE_URI", raising=False)
    monkeypatch.setenv("AWS_CONTAINER_CREDENTIALS_FULL_URI", full)
    with pytest.raises(ValueError, match="Invalid container"):
        credentials.ContainerProvider()


def test_native_refresh_and_auth_token_file(container, monkeypatch, tmp_path):
    # The native provider rereads its authorization file on refresh; never print its contents.
    token_file = tmp_path / "token"
    token_file.write_text("authorization-A")
    monkeypatch.delenv("AWS_CONTAINER_CREDENTIALS_RELATIVE_URI")
    monkeypatch.setenv("AWS_CONTAINER_CREDENTIALS_FULL_URI", "http://localhost/task")
    monkeypatch.setenv("AWS_CONTAINER_AUTHORIZATION_TOKEN_FILE", str(token_file))
    replies = []
    expirations = [1, 600]

    class Transport:
        def urlopen(self, method, url, **kw):
            replies.append(kw["headers"]["Authorization"])
            token_file.write_text("authorization-B")
            body = json.dumps(
                {
                    "AccessKeyId": "dummy-access",
                    "SecretAccessKey": "dummy-secret",
                    "Token": f"session-{len(replies)}",
                    "Expiration": (
                        datetime.now(UTC) + timedelta(seconds=expirations.pop(0))
                    ).strftime("%Y-%m-%dT%H:%M:%SZ"),
                }
            ).encode()
            return HTTPResponse(status=200, body=body)

    monkeypatch.setattr(credentials, "PoolManager", lambda **kw: Transport())
    provider = credentials.ContainerProvider()
    assert provider.retrieve().session_token == "session-2"
    assert provider.retrieve().session_token == "session-2"
    assert replies == ["authorization-A", "authorization-B"]


def test_missing_endpoint_and_static_override_fail(container, monkeypatch, settings):
    with pytest.raises(ValueError, match="overrides"):
        Storage(
            settings.model_copy(
                update={"storage_credential_mode": "ecs", "minio_access_key": "dummy"}
            )
        )
    monkeypatch.delenv("AWS_CONTAINER_CREDENTIALS_RELATIVE_URI")
    with pytest.raises(ValueError, match="exactly one"):
        Storage(settings.model_copy(update={"storage_credential_mode": "ecs"}))
    with pytest.raises(ValueError, match="complete"):
        Storage(settings.model_copy(update={"minio_access_key": "incomplete"}))


async def test_snapshot_token_ttl_output_and_concurrency(settings):
    store = Storage(settings)
    values = [temporary(f"session-{i}", 80 + i) for i in range(12)]
    store.provider = Mock(retrieve=Mock(side_effect=values))
    signed = await asyncio.gather(*(store.source_grant(f"source-{i}") for i in range(12)))
    for url, expiry in signed:
        query = parse_qs(urlsplit(url).query)
        used = next(c for c in values if c.session_token == query["X-Amz-Security-Token"][0])
        signed_at = datetime.strptime(query["X-Amz-Date"][0], "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC)
        assert expiry == signed_at + timedelta(seconds=int(query["X-Amz-Expires"][0]))
        assert expiry <= used.expiration.replace(tzinfo=UTC) - timedelta(seconds=10)
    store.provider = Mock(retrieve=Mock(return_value=temporary("output-session")))
    output = await store.sign_output("output", inline=True)
    assert parse_qs(urlsplit(output).query)["X-Amz-Security-Token"] == ["output-session"]


@pytest.mark.parametrize("failure", ["expired", "near", "refresh_error"])
async def test_failed_signing_never_publishes_grant(settings, failure):
    store = Storage(settings)
    retrieve = (
        Mock(side_effect=RuntimeError("private-credential"))
        if failure == "refresh_error"
        else Mock(return_value=temporary("private-session", -1 if failure == "expired" else 20))
    )
    store.provider = Mock(retrieve=retrieve)
    with pytest.raises(MediaError) as error:
        await store.source_grant("source")
    assert "private" not in str(error.value)


def test_native_provider_serializes_refresh(container):
    import concurrent.futures

    native = Mock(retrieve=Mock(return_value=temporary("token-B")))
    old = Mock(retrieve=Mock(return_value=temporary("token-A", 1)))
    factory = Mock(side_effect=[old, native])
    provider = credentials.ContainerProvider(factory=factory)
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        assert (
            list(pool.map(lambda _: provider.retrieve().session_token, range(12)))
            == ["token-B"] * 12
        )
    assert factory.call_count == 2


async def test_ordinary_put_rotates_token_without_reconstructing_store(
    settings, container, monkeypatch
):
    seen = []
    native = Mock(retrieve=Mock(side_effect=[temporary("token-A"), temporary("token-B")]))
    monkeypatch.setattr(credentials, "IamAwsProvider", lambda **kw: native)
    store = Storage(settings.model_copy(update={"storage_credential_mode": "ecs"}))

    def request(method, url, **kw):
        seen.append(kw["headers"].get("X-Amz-Security-Token"))
        return HTTPResponse(status=200, headers={"etag": '"ack"'}, body=b"")

    monkeypatch.setattr(store.internal._http, "urlopen", request)
    await store.put_source("key", BytesIO(b"x"), 1, "video/mp4")
    await store.put_source("key", BytesIO(b"x"), 1, "video/mp4")
    assert seen == ["token-A", "token-B"]


def test_clock_controlled_native_refresh_and_no_lost_endpoint_fallback(container, monkeypatch):
    fixed = datetime(2026, 10, 15, tzinfo=UTC)
    old = Mock(
        retrieve=Mock(return_value=Credentials("a", "s", "old", fixed + timedelta(seconds=39)))
    )
    new = Mock(
        retrieve=Mock(return_value=Credentials("b", "s", "new", fixed + timedelta(seconds=600)))
    )
    provider = credentials.ContainerProvider(
        factory=Mock(side_effect=[old, new]), clock=lambda: fixed
    )
    assert provider.retrieve().session_token == "new"
    provider = credentials.ContainerProvider(factory=lambda: old, clock=lambda: fixed)
    monkeypatch.delenv("AWS_CONTAINER_CREDENTIALS_RELATIVE_URI")
    with pytest.raises(ValueError, match="unavailable"):
        provider.retrieve()


async def test_clock_controlled_snapshot_has_exact_expiry_and_static_ttl(settings):
    fixed = datetime(2026, 10, 15, 1, 2, 3, tzinfo=UTC)
    store = Storage(settings, clock=lambda: fixed)
    store.provider = Mock(
        retrieve=Mock(return_value=Credentials("a", "s", "snapshot", fixed + timedelta(seconds=75)))
    )
    url, expiry = await store.source_grant("key")
    assert parse_qs(urlsplit(url).query)["X-Amz-Expires"] == ["65"]
    assert expiry == fixed + timedelta(seconds=65)
    from minio.credentials import StaticProvider

    store.provider = StaticProvider("local-access", "local-secret")
    _, expiry = await store.source_grant("key")
    assert expiry == fixed + timedelta(seconds=settings.signed_url_ttl_seconds)
