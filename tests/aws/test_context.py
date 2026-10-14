import httpx
import pytest

from scripts.aws.context import Client, Context, ContextError


def context(**kw):
    return Context("https://demo.cloudfront.net", "ap-southeast-1", ("sources", "outputs"), **kw)


@pytest.mark.parametrize(
    "url",
    [
        "http://demo.cloudfront.net",
        "https://evil.test",
        "https://user:pass@demo.cloudfront.net",
        "https://demo.cloudfront.net/?token=private",
    ],
)
def test_production_context_rejects_invalid_api_origin(url):
    with pytest.raises(ContextError):
        Context(url, "ap-southeast-1", ("sources",))


def test_local_fixtures_explicit_and_production_no_custom_ca():
    with pytest.raises(ContextError):
        Context("https://localhost:54440", "ap-southeast-1", ("sources",))
    local = Context("https://localhost:54440", "ap-southeast-1", ("sources",), mode="local-fixture")
    assert local.mode == "local-fixture"
    with pytest.raises(ContextError, match="normal system trust"):
        Client(context(), ca_file="must-not-be-read")


def test_cookie_token_isolation_and_query_bytes_preserved():
    requests = []

    def api(req):
        return httpx.Response(200, json={}, headers={"set-cookie": "private=api-cookie; Path=/"})

    def objects(req):
        requests.append(req)
        return httpx.Response(
            200, content=b"object", headers={"set-cookie": "private=object-cookie"}
        )

    capability = (
        "https://outputs.s3.ap-southeast-1.amazonaws.com/x?X-Amz-Signature=ab%2fCD&part=a+b&z=%20"
    )
    with Client(
        context(),
        api_transport=httpx.MockTransport(api),
        object_transport=httpx.MockTransport(objects),
    ) as client:
        client.request("POST", "/api/auth/login", headers={"Authorization": "Bearer api-token"})
        client.api.headers["Authorization"] = "Bearer persistent-api-token"
        client.download(capability)
        client.download(capability)
        for req in requests:
            assert "cookie" not in req.headers and "authorization" not in req.headers
            assert req.url.raw_path == capability.split("amazonaws.com", 1)[1].encode()


@pytest.mark.parametrize(
    "url",
    [
        "https://sources.s3.us-east-1.amazonaws.com/x?a=b",
        "https://evil.test/x",
        "http://sources.s3.ap-southeast-1.amazonaws.com/x",
        "https://sources.s3.ap-southeast-1.amazonaws.com.evil.test/x",
    ],
)
def test_capability_strict_allowlist(url):
    with Client(context()) as client, pytest.raises(ContextError):
        client.download(url)


def test_redirect_and_body_bounds_and_relative_api_only():
    transport = httpx.MockTransport(
        lambda req: httpx.Response(307, headers={"location": "https://evil.test"})
    )
    with Client(context(), object_transport=transport) as client:
        with pytest.raises(ContextError, match="redirect"):
            client.download("https://sources.s3.ap-southeast-1.amazonaws.com/x")
        with pytest.raises(ContextError, match="configured origin"):
            client.request("GET", "//evil.test/path")
    transport = httpx.MockTransport(lambda req: httpx.Response(200, content=b"12345"))
    with Client(context(capability_limit_bytes=4), object_transport=transport) as client:
        with pytest.raises(ContextError, match="body limit"):
            client.download("https://sources.s3.ap-southeast-1.amazonaws.com/x")


def test_malformed_port_failure_does_not_echo_private_url():
    private = "https://sources.s3.ap-southeast-1.amazonaws.com:private-sentinel/object"
    with Client(context()) as client, pytest.raises(ContextError, match="^Invalid HTTP URL$"):
        client.download(private)
