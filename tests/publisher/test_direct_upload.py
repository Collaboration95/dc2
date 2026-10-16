"""Independent public HTTP workflow, no Media/Processing imports."""

import hashlib
import json
from uuid import uuid4

import httpx
import pytest

from publisher.client import PublicClient, PublisherError


@pytest.mark.parametrize("replay", [False, True])
def test_direct_upload_no_api_cookies_and_finalize_retry(tmp_path, replay):
    key, reservation, asset = map(str, (uuid4(), uuid4(), uuid4()))
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"fixture-video")
    calls = []

    def peer(req):
        calls.append(req)
        if req.url.path.endswith("/reservations"):
            body = json.loads(req.content)
            assert body["request_id"] == key
            assert body["sha256"] == hashlib.sha256(video.read_bytes()).hexdigest()
            assert b"fixture-video" not in req.content
            return httpx.Response(
                201,
                json={
                    "reservation_id": reservation,
                    "asset_id": asset,
                    "upload": None
                    if replay
                    else {
                        "url": "https://media.test/source",
                        "fields": {"key": "server-owned", "Content-Type": "video/mp4"},
                    },
                },
            )
        if req.url.path == "/source":
            assert "cookie" not in req.headers and "authorization" not in req.headers
            assert b"fixture-video" in req.content
            return httpx.Response(204)
        assert req.url.path.endswith(f"/{reservation}/finalize")
        assert json.loads(req.content) == {"request_id": key}
        return httpx.Response(202, json={"job_id": asset})

    client = PublicClient(
        "https://media.test/api/media", tmp_path / "cookies", transport=httpx.MockTransport(peer)
    )
    client.http.cookies.set("api-secret", "private", domain="media.test", path="/")
    try:
        assert client.upload(video, key) == asset
        assert len(calls) == (2 if replay else 3)
        assert "cookie" in calls[0].headers
    finally:
        client.close()


def test_edit_and_delete_public_surface(tmp_path):
    asset = str(uuid4())
    seen = []

    def peer(req):
        seen.append(req)
        return (
            httpx.Response(204)
            if req.method == "DELETE"
            else httpx.Response(202, json={"job_id": asset})
        )

    client = PublicClient(
        "https://media.test/api/media", tmp_path / "cookies", transport=httpx.MockTransport(peer)
    )
    try:
        operations = [{"operation": "clip", "params": {"start": 0, "end": 1}}]
        assert client.edit(asset, operations, str(uuid4())) == asset
        assert client.delete(asset) == asset
        assert json.loads(seen[0].content) == {"operations": operations}
        assert seen[1].method == "DELETE"
    finally:
        client.close()


def test_uncertain_s3_response_retains_intent(tmp_path):
    path = tmp_path / "clip.mp4"
    path.write_bytes(b"video")

    def peer(req):
        if req.url.path == "/source":
            raise httpx.ReadTimeout("secret")
        return httpx.Response(
            201,
            json={
                "reservation_id": str(uuid4()),
                "upload": {"url": "https://storage.test/source", "fields": {}},
            },
        )

    client = PublicClient(
        "https://media.test/api/media", tmp_path / "cookies", transport=httpx.MockTransport(peer)
    )
    try:
        with pytest.raises(PublisherError) as error:
            client.upload(path, str(uuid4()))
        assert error.value.uncertain and "secret" not in str(error.value)
    finally:
        client.close()


def test_cli_edit_retains_identity_and_delete_handles_empty_response(monkeypatch, tmp_path, capsys):
    from publisher import cli

    asset = str(uuid4())
    seen = []

    def peer(req):
        seen.append(req)
        if req.url.path.endswith("auth/me"):
            return httpx.Response(200, json={"id": str(uuid4())})
        if req.method == "DELETE":
            return httpx.Response(204)
        assert json.loads(req.content)["operations"][0]["operation"] == "clip"
        return httpx.Response(202, json={"job_id": asset})

    monkeypatch.setattr(
        cli,
        "PublicClient",
        lambda base, jar, ca, timeout: PublicClient(
            base, jar, ca, timeout, transport=httpx.MockTransport(peer)
        ),
    )
    base = [
        "--base-url",
        "https://media.test/api/media",
        "--cookie-jar",
        str(tmp_path / "cookies"),
        "--json",
    ]
    assert (
        cli.main(
            base
            + [
                "edit",
                asset,
                "--operations",
                json.dumps([{"operation": "clip", "params": {"start": 0, "end": 1}}]),
            ]
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out)["job_id"] == asset
    assert cli.main(base + ["delete", asset]) == 0
    assert json.loads(capsys.readouterr().out) == {"ok": True, "job_id": asset}
    assert seen[-1].method == "DELETE"
