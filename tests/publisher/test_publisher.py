"""Offline public-contract peers: no live services or service imports."""

import ast
import io
import json
import runpy
from pathlib import Path
from uuid import UUID

import httpx
import pytest

from publisher import cli
from publisher.client import PublicClient, PublisherError, private_write
from publisher.state import Intents

ASSET = "11111111-1111-4111-8111-111111111111"
USER = "22222222-2222-4222-8222-222222222222"
KEY = "33333333-3333-4333-8333-333333333333"
BASE = "https://media.test/api"
EMAIL = f"{USER}@example.com"


def job(status="done", **extra):
    return {"id": ASSET, "filename": "clip.mp4", "status": status, **extra}


@pytest.fixture
def factory(tmp_path):
    clients = []

    def create(handler):
        client = PublicClient(BASE, tmp_path / "cookies", transport=httpx.MockTransport(handler))
        clients.append(client)
        return client

    yield create
    for client in clients:
        client.close()


def test_cookie_survives_process_restart_and_is_secure(tmp_path):
    def register(request):
        assert json.loads(request.content) == {"email": EMAIL, "password": "private"}
        return httpx.Response(
            201,
            json={
                "id": USER,
                "email": EMAIL,
                "role": "user",
                "password": "DO NOT PRINT",
            },
            headers={
                "set-cookie": (
                    "access_token=fixture-only; Path=/api; Secure; HttpOnly; SameSite=Strict"
                )
            },
        )

    first = PublicClient(BASE, tmp_path / "cookies", transport=httpx.MockTransport(register))
    assert "password" not in first.authenticate("register", EMAIL, "private")
    first.close()
    assert (tmp_path / "cookies").stat().st_mode & 0o777 == 0o600

    def me(request):
        assert request.headers["cookie"] == "access_token=fixture-only"
        assert request.url.path == "/api/auth/me"
        return httpx.Response(200, json={"id": USER})

    second = PublicClient(BASE, tmp_path / "cookies", transport=httpx.MockTransport(me))
    assert second.identity() == USER
    second.close()


@pytest.mark.parametrize(
    "url",
    [
        "http://media.test",
        "https://a:b@media.test",
        "https://media.test?q=x",
        "https://media.test#x",
    ],
)
def test_only_trusted_https_origins(tmp_path, url):
    with pytest.raises(ValueError):
        PublicClient(url, tmp_path / "cookies")


@pytest.mark.parametrize("status", [401, 404, 409, 410, 413, 415, 422, 503, 302])
def test_safe_http_errors(factory, status):
    client = factory(lambda req: httpx.Response(status, json={"error": "secret-token"}))
    with pytest.raises(PublisherError) as caught:
        client.status(ASSET)
    assert caught.value.status == status
    assert caught.value.uncertain == (status >= 500)
    assert "secret-token" not in str(caught.value)


@pytest.mark.parametrize("body", [b"bad json", b"[]", b"null"])
def test_invalid_responses(factory, body):
    with pytest.raises(PublisherError, match="Invalid API response"):
        factory(lambda req: httpx.Response(200, content=body)).identity()


@pytest.mark.parametrize("data", [{}, {"job_id": "bad"}, {"job_id": None}])
def test_bad_acceptance_preserves_intent(factory, tmp_path, data):
    client = factory(lambda req: httpx.Response(202, json=data))
    intents = Intents(tmp_path / "intents", [BASE, USER])
    result = cli.mutation(client, intents, "retry", lambda key: client.retry(ASSET, key))
    assert not result["ok"]
    assert intents.data["retry"] == result["intent_key"]


def test_transport_replay_reopens_file_and_restores_key(factory, tmp_path):
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"video-content")
    requests = []

    def peer(req):
        requests.append(req)
        assert b"video-content" in req.content
        if len(requests) == 1:
            raise httpx.ReadTimeout("secret internal URL")
        return httpx.Response(202, json={"job_id": ASSET})

    client = factory(peer)
    intents = Intents(tmp_path / "intents", [BASE, USER])
    identity = intents.identity("upload", ["clip.mp4", 13, "digest"])
    first = cli.mutation(client, intents, identity, lambda key: client.legacy_upload(video, key))
    assert not first["ok"]
    assert "secret" not in first["error"]
    intents = Intents(tmp_path / "intents", [BASE, USER])
    second = cli.mutation(client, intents, identity, lambda key: client.legacy_upload(video, key))
    assert second["ok"]
    assert first["intent_key"] == second["intent_key"]
    assert requests[0].headers["idempotency-key"] == requests[1].headers["idempotency-key"]
    assert intents.data == {}
    third = cli.mutation(client, intents, identity, lambda key: client.legacy_upload(video, key))
    assert third["intent_key"] != second["intent_key"]


def test_retry_bodyless_replay_and_new_user_intent(factory, tmp_path):
    calls = []

    def peer(req):
        calls.append(req)
        assert req.url.path == f"/api/jobs/{ASSET}/retry"
        assert req.content == b""
        return httpx.Response(503 if len(calls) == 1 else 202, json={"job_id": ASSET})

    client = factory(peer)
    intents = Intents(tmp_path / "intents", [BASE, USER])
    one = cli.mutation(client, intents, ASSET, lambda key: client.retry(ASSET, key))
    two = cli.mutation(client, intents, ASSET, lambda key: client.retry(ASSET, key))
    three = cli.mutation(client, intents, ASSET, lambda key: client.retry(ASSET, key))
    assert one["intent_key"] == two["intent_key"] != three["intent_key"]
    assert (
        cli.mutation(client, intents, ASSET, lambda key: client.retry(ASSET, key), KEY)[
            "intent_key"
        ]
        == KEY
    )


def test_definitive_rejection_releases_intent(factory, tmp_path):
    client = factory(lambda req: httpx.Response(409))
    intents = Intents(tmp_path / "intents", USER)
    assert not cli.mutation(client, intents, ASSET, lambda key: client.retry(ASSET, key))["ok"]
    assert intents.data == {}
    assert Intents(tmp_path / "other", "other-owner").identity("retry", ASSET) != intents.identity(
        "retry", ASSET
    )


@pytest.mark.parametrize(
    "statuses,expected,exhausted",
    [
        (["queued", "processing", "done"], "done", False),
        (["queued", "failed"], "failed", False),
        (["queued"] * 3, "queued", True),
        ([503] * 3, "unavailable", True),
        ([503, "done"], "done", False),
    ],
)
def test_bounded_polling(factory, statuses, expected, exhausted):
    statuses = iter(statuses)
    calls = []

    def peer(req):
        calls.append(req)
        status = next(statuses)
        return httpx.Response(503) if status == 503 else httpx.Response(200, json=job(status))

    sleep = []
    result = factory(peer).poll(ASSET, 3, 2, sleep=sleep.append)
    assert result["status"] == expected
    assert result.get("poll_exhausted", False) == exhausted
    assert len(calls) <= 3
    assert len(sleep) == len(calls) - 1


def test_poll_stops_on_auth_or_invalid_status(factory):
    with pytest.raises(PublisherError):
        factory(lambda req: httpx.Response(401)).poll(ASSET, 2, 1)
    with pytest.raises(PublisherError, match="Invalid status"):
        factory(lambda req: httpx.Response(200, json=job("invented"))).status(ASSET)


def args(tmp_path, *command):
    return ["--base-url", BASE, "--cookie-jar", str(tmp_path / "cookies"), "--json", *command]


def install_peer(monkeypatch, handler):
    # These frozen peers exercise the pre-Gateway multipart contract.
    monkeypatch.setattr(PublicClient, "upload", PublicClient.legacy_upload)
    actual = PublicClient
    monkeypatch.setattr(
        cli,
        "PublicClient",
        lambda base, jar, ca, timeout: actual(
            base, jar, ca, timeout, transport=httpx.MockTransport(handler)
        ),
    )


def test_cli_mixed_batch_keeps_every_file_outcome(monkeypatch, tmp_path, capsys):
    directory = tmp_path / "videos"
    directory.mkdir()
    for name in ("a.mp4", "b.txt", "c.mp4"):
        (directory / name).write_bytes(name.encode())
    (directory / "nested").mkdir()
    (directory / "link").symlink_to(directory / "a.mp4")
    uploaded = []

    def peer(req):
        if req.url.path.endswith("auth/me"):
            return httpx.Response(200, json={"id": USER})
        uploaded.append(req)
        UUID(req.headers["idempotency-key"])
        if b'filename="b.txt"' in req.content:
            return httpx.Response(415, json={"error": "password=DO-NOT-PRINT"})
        return httpx.Response(202, json={"job_id": ASSET})

    install_peer(monkeypatch, peer)
    assert cli.main(args(tmp_path, "publish", str(directory))) == 1
    output = capsys.readouterr().out
    results = json.loads(output)["files"]
    assert [item["file"] for item in results] == ["a.mp4", "b.txt", "c.mp4"]
    assert [item["ok"] for item in results] == [True, False, True]
    assert len(uploaded) == 3
    assert "DO-NOT-PRINT" not in output


@pytest.mark.parametrize("command", ["register", "login"])
def test_cli_auth_password_stdin(monkeypatch, tmp_path, capsys, command):
    monkeypatch.setattr("sys.stdin", io.StringIO("private-fixture\n"))
    install_peer(
        monkeypatch,
        lambda req: httpx.Response(
            200,
            json={"id": USER, "email": EMAIL, "role": "user", "token": "do-not-print"},
        ),
    )
    assert cli.main(args(tmp_path, command, EMAIL, "--password-stdin")) == 0
    output = capsys.readouterr().out
    assert "private-fixture" not in output and "do-not-print" not in output
    assert json.loads(output)["user"]["id"] == USER


def test_cli_interactive_password(monkeypatch, tmp_path):
    monkeypatch.setattr(cli.getpass, "getpass", lambda prompt: "fixture")
    install_peer(
        monkeypatch,
        lambda req: httpx.Response(200, json={"id": USER, "email": EMAIL, "role": "user"}),
    )
    assert cli.main(args(tmp_path, "login", EMAIL)) == 0


@pytest.mark.parametrize(
    "command,status,expected",
    [
        ("status", "queued", 0),
        ("status", "failed", 1),
        ("output", "done", 0),
        ("output", "queued", 1),
    ],
)
def test_status_and_authorised_links(monkeypatch, tmp_path, capsys, command, status, expected):
    install_peer(
        monkeypatch,
        lambda req: httpx.Response(
            200,
            json=job(
                status,
                output_url="https://media.test/output/primary",
                hls_url=f"/api/jobs/{ASSET}/hls/a.m3u8",
                error="do-not-print",
            ),
        ),
    )
    assert cli.main(args(tmp_path, command, ASSET)) == expected
    output = capsys.readouterr().out
    assert "do-not-print" not in output
    assert json.loads(output)["job"]["id"] == ASSET


@pytest.mark.parametrize("command", ["status", "retry", "publish"])
def test_wait_commands(monkeypatch, tmp_path, capsys, command):
    (tmp_path / "clip.mp4").write_bytes(b"clip")

    def peer(req):
        if req.url.path.endswith("auth/me"):
            return httpx.Response(200, json={"id": USER})
        if req.method == "POST":
            return httpx.Response(202, json={"job_id": ASSET})
        return httpx.Response(200, json=job("done"))

    install_peer(monkeypatch, peer)
    target = str(tmp_path) if command == "publish" else ASSET
    assert cli.main(args(tmp_path, command, target, "--wait", "--max-polls", "1")) == 0
    assert json.loads(capsys.readouterr().out)["ok"]


def test_safe_errors_empty_directory_and_human_output(monkeypatch, tmp_path, capsys):
    install_peer(monkeypatch, lambda req: httpx.Response(200, json={"id": USER}))
    assert cli.main(args(tmp_path, "publish", str(tmp_path / "missing"))) == 1
    capsys.readouterr()
    empty = tmp_path / "empty"
    empty.mkdir()
    assert cli.main(args(tmp_path, "publish", str(empty))) == 1
    assert json.loads(capsys.readouterr().out)["files"] == []
    assert "failed" in cli.human({"files": [{"file": "bad", "ok": False, "error": "unsupported"}]})
    assert "ok" in cli.human({"ok": True})


@pytest.mark.parametrize(
    "flag,value",
    [("--timeout", "nan"), ("--timeout", "0"), ("--max-polls", "0"), ("--max-polls", "10001")],
)
def test_usage_bounds(tmp_path, flag, value):
    command = (
        ["status", ASSET, flag, value] if flag == "--max-polls" else [flag, value, "status", ASSET]
    )
    with pytest.raises(SystemExit) as caught:
        cli.main(args(tmp_path, *command))
    assert caught.value.code == 2


def test_private_atomic_state_survives_failed_write(tmp_path):
    target = tmp_path / "state"
    target.write_text("old")

    def fail(name):
        Path(name).write_text("new")
        raise OSError("fixture")

    with pytest.raises(OSError):
        private_write(target, fail)
    assert target.read_text() == "old"
    assert list(tmp_path.iterdir()) == [target]


def test_module_entry_and_import_boundary(monkeypatch):
    monkeypatch.setattr(cli, "main", lambda: 0)
    with pytest.raises(SystemExit) as caught:
        runpy.run_module("publisher", run_name="__main__")
    assert caught.value.code == 0
    for path in Path("publisher").glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            names = (
                [node.module]
                if isinstance(node, ast.ImportFrom)
                else [alias.name for alias in node.names]
                if isinstance(node, ast.Import)
                else []
            )
            assert not any(
                name
                and name.split(".")[0] in {"app", "media", "processing", "sqlalchemy", "asyncpg"}
                for name in names
            )


def test_public_schema_conformance_and_explicit_ca(tmp_path, monkeypatch):
    import ssl

    import jsonschema

    contract = json.loads(
        Path("project-roadmap/design/05-contracts/public.openapi.json").read_text()
    )

    def validate(schema, data):
        jsonschema.Draft202012Validator(
            {**schema, "components": contract["components"]},
            format_checker=jsonschema.FormatChecker(),
        ).validate(data)

    actual_context = ssl.create_default_context
    ca = tmp_path / "ca.pem"
    ca.write_text("placeholder")
    trust_calls = []

    def trust(*, cafile):
        trust_calls.append(cafile)
        context = actual_context()
        assert context.verify_mode == ssl.CERT_REQUIRED
        assert context.check_hostname
        return context

    monkeypatch.setattr(ssl, "create_default_context", trust)
    seen = []

    def peer(req):
        path = req.url.path.removeprefix("/api")
        route = (
            "/jobs/{job_id}/retry"
            if path.endswith("/retry")
            else ("/jobs/{job_id}" if path.startswith("/jobs/") else path)
        )
        operation = contract["paths"][route][req.method.lower()]
        if route in {"/auth/register", "/auth/login"}:
            validate(
                operation["requestBody"]["content"]["application/json"]["schema"],
                json.loads(req.content),
            )
            data = {"id": USER, "email": EMAIL, "role": "user"}
            status = 201 if route.endswith("register") else 200
        elif req.method == "POST":
            UUID(req.headers["idempotency-key"])
            if route.endswith("retry"):
                assert req.content == b"" and "requestBody" not in operation
            else:
                assert b'name="file"' in req.content and b"fixture video" in req.content
            data, status = {"job_id": ASSET}, 202
        else:
            data, status = job(output_url="https://media.test/output.mp4"), 200
        validate(operation["responses"][str(status)]["content"]["application/json"]["schema"], data)
        seen.append(route)
        return httpx.Response(status, json=data)

    client = PublicClient(BASE, tmp_path / "cookies", str(ca), transport=httpx.MockTransport(peer))
    try:
        client.authenticate("register", EMAIL, "password-fixture")
        client.authenticate("login", EMAIL, "password-fixture")
        video = tmp_path / "clip.mp4"
        video.write_bytes(b"fixture video")
        assert client.legacy_upload(video, KEY) == ASSET
        assert client.retry(ASSET, KEY) == ASSET
        assert client.status(ASSET)["status"] == "done"
    finally:
        client.close()
    assert trust_calls == [str(ca)]
    assert len(seen) == 5


def test_wait_failure_preserves_accepted_asset(monkeypatch, tmp_path, capsys):
    def peer(req):
        if req.url.path.endswith("auth/me"):
            return httpx.Response(200, json={"id": USER})
        if req.method == "POST":
            return httpx.Response(202, json={"job_id": ASSET})
        return httpx.Response(401)

    install_peer(monkeypatch, peer)
    assert cli.main(args(tmp_path, "retry", ASSET, "--wait")) == 1
    result = json.loads(capsys.readouterr().out)
    assert result["job_id"] == ASSET and not result["ok"]


@pytest.mark.parametrize("operation", ["upload", "retry"])
def test_cli_uncertain_auth_recovery_is_owner_scoped(
    monkeypatch, tmp_path, capsys, operation
):
    directory = tmp_path / "videos"
    directory.mkdir()
    (directory / "clip.mp4").write_bytes(b"original content")
    command = ("publish", str(directory)) if operation == "upload" else ("retry", ASSET)
    owner = USER
    stage = "lost"
    posts = []

    def peer(req):
        if req.url.path.endswith("auth/me"):
            if stage == "expired-identity":
                return httpx.Response(401)
            return httpx.Response(200, json={"id": owner})
        if req.url.path.endswith("auth/login"):
            return httpx.Response(200, json={"id": owner, "email": EMAIL, "role": "user"})
        posts.append(req)
        if operation == "upload":
            assert b"original content" in req.content
        else:
            assert req.content == b""
        if stage == "lost":
            raise httpx.ReadTimeout("lost acknowledgement")
        if stage == "expired":
            return httpx.Response(401)
        return httpx.Response(202, json={"job_id": ASSET})

    def invoke(*commands):
        code = cli.main(args(tmp_path, *commands))
        result = json.loads(capsys.readouterr().out)
        return code, result["files"][0] if operation == "upload" and "files" in result else result

    install_peer(monkeypatch, peer)
    monkeypatch.setattr(cli.getpass, "getpass", lambda prompt: "fixture-password")
    code, lost = invoke(*command)
    assert code == 1
    journal = tmp_path / "cookies.intents.json"
    assert list(json.loads(journal.read_text()).values()) == [lost["intent_key"]]
    stage = "expired"
    code, expired = invoke(*command)
    assert code == 1 and expired["intent_key"] == lost["intent_key"]
    assert list(json.loads(journal.read_text()).values()) == [lost["intent_key"]]
    stage = "expired-identity"
    code, expired_identity = invoke(*command)
    assert code == 1 and "Session expired" in expired_identity["error"]
    assert len(posts) == 2
    assert list(json.loads(journal.read_text()).values()) == [lost["intent_key"]]

    # Another owner's confirmed action cannot consume or replay this pending key.
    stage = "accepted"
    owner = KEY
    assert invoke("login", EMAIL)[0] == 0
    code, other = invoke(*command)
    assert code == 0 and other["intent_key"] != lost["intent_key"]
    assert list(json.loads(journal.read_text()).values()) == [lost["intent_key"]]
    owner = USER
    assert invoke("login", EMAIL)[0] == 0
    code, resumed = invoke(*command)
    assert code == 0 and resumed["job_id"] == ASSET
    assert resumed["intent_key"] == lost["intent_key"]
    assert json.loads(journal.read_text()) == {}
    code, later = invoke(*command)
    assert code == 0 and later["intent_key"] != lost["intent_key"]
    assert [req.headers["idempotency-key"] for req in posts] == [
        lost["intent_key"], lost["intent_key"], other["intent_key"],
        lost["intent_key"], later["intent_key"],
    ]


def test_completion_save_failure_keeps_accepted_ids_and_key_through_later_batch_writes(
    monkeypatch, tmp_path, capsys
):
    directory = tmp_path / "videos"
    directory.mkdir()
    for name in ("a.mp4", "b.txt", "c.mp4"):
        (directory / name).write_bytes(name.encode())
    requests = []

    def peer(req):
        if req.url.path.endswith("auth/me"):
            return httpx.Response(200, json={"id": USER})
        requests.append(req)
        if b'filename="b.txt"' in req.content:
            return httpx.Response(415)
        accepted = ASSET if b'filename="a.mp4"' in req.content else KEY
        return httpx.Response(202, json={"job_id": accepted})

    save = Intents.save
    failed = False

    def fail_first_completion(self):
        nonlocal failed
        if not self.data and not failed:
            failed = True
            raise OSError("secret filesystem detail")
        save(self)

    install_peer(monkeypatch, peer)
    monkeypatch.setattr(Intents, "save", fail_first_completion)
    assert cli.main(args(tmp_path, "publish", str(directory))) == 1
    raw = capsys.readouterr().out
    result = json.loads(raw)
    assert result["state_error"] and "secret" not in raw
    outcomes = result["files"]
    assert [item["file"] for item in outcomes] == ["a.mp4", "b.txt", "c.mp4"]
    assert [item["ok"] for item in outcomes] == [False, False, True]
    assert outcomes[0]["job_id"] == ASSET and outcomes[2]["job_id"] == KEY
    assert all(UUID(item["intent_key"]) for item in outcomes)
    journal = tmp_path / "cookies.intents.json"
    assert list(json.loads(journal.read_text()).values()) == [outcomes[0]["intent_key"]]

    assert cli.main(args(tmp_path, "publish", str(directory))) == 1  # unsupported b remains
    replay = json.loads(capsys.readouterr().out)["files"]
    assert len(replay) == 3 and replay[0]["ok"]
    assert replay[0]["job_id"] == ASSET
    assert replay[0]["intent_key"] == outcomes[0]["intent_key"]
    assert replay[2]["intent_key"] != outcomes[2]["intent_key"]
    assert requests[0].headers["idempotency-key"] == requests[3].headers["idempotency-key"]
    assert json.loads(journal.read_text()) == {}


@pytest.mark.parametrize("mixed", [False, True])
def test_cookie_save_failure_preserves_all_completed_batch_outcomes(
    monkeypatch, tmp_path, capsys, mixed
):
    directory = tmp_path / "videos"
    directory.mkdir()
    for name in ("a.mp4", "b.mp4", "c.mp4"):
        (directory / name).write_bytes(name.encode())
    keys = []

    def peer(req):
        if req.url.path.endswith("auth/me"):
            return httpx.Response(200, json={"id": USER})
        keys.append(req.headers["idempotency-key"])
        if mixed and b'filename="b.mp4"' in req.content:
            return httpx.Response(415)
        accepted = ASSET if b'filename="a.mp4"' in req.content else KEY
        return httpx.Response(202, json={"job_id": accepted})

    def fail_cookie_save(*args, **kwargs):
        raise OSError("secret cookie path")

    install_peer(monkeypatch, peer)
    monkeypatch.setattr("publisher.client.MozillaCookieJar.save", fail_cookie_save)
    assert cli.main(args(tmp_path, "publish", str(directory))) == 1
    raw = capsys.readouterr().out
    result = json.loads(raw)
    assert result["ok"] is False and result["state_error"]
    assert "secret" not in raw
    assert [item["file"] for item in result["files"]] == ["a.mp4", "b.mp4", "c.mp4"]
    assert [item["ok"] for item in result["files"]] == [True, not mixed, True]
    assert [item["intent_key"] for item in result["files"]] == keys
    assert result["files"][0]["job_id"] == ASSET
    assert result["files"][2]["job_id"] == KEY
    assert json.loads((tmp_path / "cookies.intents.json").read_text()) == {}
    assert "Client state failed" in cli.human(result)


@pytest.mark.parametrize("status", [202, 409])
def test_retry_completion_state_failure_retains_key_and_safe_outcome(
    factory, tmp_path, monkeypatch, status
):
    client = factory(lambda req: httpx.Response(status, json={"job_id": ASSET}))
    intents = Intents(tmp_path / "intents", [BASE, USER])
    save = intents.save

    def fail_completion():
        if not intents.data:
            raise OSError("private state detail")
        save()

    monkeypatch.setattr(intents, "save", fail_completion)
    outcome = cli.mutation(client, intents, ASSET, lambda key: client.retry(ASSET, key))
    assert not outcome["ok"] and outcome["state_error"]
    assert intents.data[ASSET] == outcome["intent_key"]
    assert Intents(intents.path, [BASE, USER]).data == intents.data
    if status == 202:
        assert outcome["job_id"] == ASSET
    else:
        assert "conflict" in outcome["error"]


def test_failed_reservation_rolls_back_memory_before_later_save(tmp_path, monkeypatch):
    intents = Intents(tmp_path / "intents", [BASE, USER])
    retained = intents.reserve("retained")
    save = intents.save
    monkeypatch.setattr(intents, "save", lambda: (_ for _ in ()).throw(OSError("fixture")))
    with pytest.raises(OSError):
        intents.reserve("not-submitted")
    assert intents.data == {"retained": retained}
    monkeypatch.setattr(intents, "save", save)
    intents.reserve("later")
    assert set(Intents(intents.path, [BASE, USER]).data) == {"retained", "later"}
