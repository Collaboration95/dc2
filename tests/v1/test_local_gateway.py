import base64
import threading
import urllib.request

import pytest

from scripts.dev.v1_gateway import Gateway, server


def test_gateway_builds_context_from_authorizer_preserving_wire_body_query():
    captured = []
    actor = {
        "schema_version": 1,
        "integration": "dc2-gateway-v1",
        "owner_id": "server-user",
        "role": "publisher",
    }
    gateway = Gateway(
        lambda event, _: captured.append(event) or {"statusCode": 200},
        lambda event, _: {"statusCode": 200},
        lambda event, _: {"isAuthorized": True, "context": actor},
    )
    gateway.invoke(
        "POST",
        "/api/media/uploads/reservations?name=a%2Fb&name=c",
        {
            "Cookie": "session=example; preference=demo",
            "X-Owner-Id": "forged",
            "X-Role": "publisher",
        },
        b"\xff\x00",
    )
    event = captured[0]
    assert event["rawPath"] == "/api/media/uploads/reservations"
    assert event["rawQueryString"] == "name=a%2Fb&name=c"
    assert base64.b64decode(event["body"]) == b"\xff\x00"
    assert event["cookies"] == ["session=example", "preference=demo"]
    assert event["requestContext"]["authorizer"]["lambda"] == actor
    assert "x-owner-id" not in event["headers"] and "x-role" not in event["headers"]


def test_anonymous_paths_and_denial_do_not_forge_actor():
    events = []
    gateway = Gateway(
        lambda event, _: events.append(event) or {"statusCode": 200},
        lambda event, _: {"statusCode": 200},
        lambda event, _: {"isAuthorized": False},
    )
    assert gateway.invoke("POST", "/api/media/auth/login", {})["statusCode"] == 200
    assert "authorizer" not in events[0]["requestContext"]
    assert gateway.invoke("GET", "/api/media/jobs", {"X-Owner-Id": "forged"})["statusCode"] == 401
    assert gateway.invoke("POST", "/api/processing/jobs", {})["statusCode"] == 401
    assert gateway.invoke("GET", "/api/media/health", {})["statusCode"] == 200
    assert gateway.invoke("GET", "/unknown", {})["statusCode"] == 404


# Binds a real loopback socket, which the offline-fast tier forbids.
@pytest.mark.integration
def test_real_http_bridge_preserves_multiple_set_cookie_and_binary_response():
    gateway = Gateway(
        lambda event, _: {
            "statusCode": 200,
            "isBase64Encoded": True,
            "body": base64.b64encode(b"\x00\xff").decode(),
            "cookies": ["session=example; HttpOnly", "second=demo"],
        },
        None,
        None,
    )
    http = server(gateway)
    worker = threading.Thread(target=http.serve_forever, daemon=True)
    worker.start()
    try:
        with urllib.request.urlopen(
            f"http://127.0.0.1:{http.server_port}/api/media/health"
        ) as reply:
            assert reply.read() == b"\x00\xff"
            assert len(reply.headers.get_all("Set-Cookie")) == 2
    finally:
        http.shutdown()
        http.server_close()
        worker.join(timeout=2)
