"""Frozen golden fixtures for the V1 wire contracts (#81).

The JSON under tests/v1/fixtures/contracts is the contract as reviewed. Editing
contracts/v1.py or contracts/gateway.py so that any of it changes must fail here, and the
fix is a deliberate fixture edit in the same pull request, never a silent regeneration.
These checks are offline: they say nothing about live Gateway, IAM or SQS behaviour.
"""

import json
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import jwt
import pytest
from fastapi import FastAPI, Request
from sqlalchemy.dialects import postgresql

from contracts import gateway, v1
from contracts.gateway import GatewayAdapter, invoke_asgi
from contracts.v1 import Actor, ContractError, Envelope
from delivery.envelope import document, fingerprint
from media import authorizer
from media.api import deps
from media.config import Settings as MediaSettings
from media.config import get_settings as media_settings
from media.errors import MediaError
from media.main import create_v1_app
from media.models import User
from media.projections import validate_transition
from media.services.security import issue_token
from processing import v1_api
from processing.config import Settings as ProcessingSettings
from processing.config import get_settings as processing_settings
from processing.database import get_v1_session

FIXTURES = Path(__file__).parent / "fixtures" / "contracts"
ROOT = Path(__file__).resolve().parents[2]


def load(name):
    return json.loads((FIXTURES / name).read_text())


VALID = load("envelopes_valid.json")
INVALID = load("envelopes_invalid.json")
SEQUENCES = load("sequences.json")
EVENTS = load("gateway_events.json")
AUTHORIZER = load("authorizer_cases.json")
SURFACE = load("surface.json")


# --- the frozen contract surface ----------------------------------------------------------


def current_surface():
    roles = [r for r in ("publisher", "viewer", "operator", "admin", "user") if accepted(r)]
    candidates = [
        ("GET", "/health"),
        ("POST", "/auth/register"),
        ("POST", "/auth/login"),
        ("POST", "/auth/logout"),
        ("POST", "/auth/me"),
        ("GET", "/auth/me"),
        ("GET", "/ready"),
        ("GET", "/jobs"),
    ]
    return {
        "schema_version": v1.SCHEMA_VERSION,
        "integration_marker": v1.INTEGRATION_MARKER,
        "max_upload_bytes": v1.MAX_UPLOAD_BYTES,
        "cookie_options": v1.COOKIE_OPTIONS,
        "producers": v1.PRODUCERS,
        "envelope_fields": list(Envelope.__dataclass_fields__),
        "source_fields": list(v1.Source.__dataclass_fields__),
        "actor_context_keys": sorted(Actor(str(uuid4()), "viewer").to_context()),
        "actor_roles": roles,
        "service_prefixes": gateway.PREFIXES,
        "public_routes": [
            {"service": service, "method": method, "path": path}
            for service in ("media", "processing")
            for method, path in candidates
            if gateway.is_public_route(service, method, path)
        ],
    }


def accepted(role):
    try:
        Actor.from_context(Actor(str(uuid4()), "viewer").to_context() | {"role": role})
    except ContractError:
        return False
    return True


def test_contract_surface_matches_the_frozen_golden():
    assert current_surface() == SURFACE


def test_readiness_is_never_a_public_route():
    paths = {(r["service"], r["path"]) for r in SURFACE["public_routes"]}
    assert not any(path == "/ready" for _, path in paths)


# --- envelopes ----------------------------------------------------------------------------


@pytest.mark.parametrize("name", sorted(VALID))
def test_valid_envelope_fixture_is_accepted_and_hashes_to_its_golden(name):
    entry = VALID[name]
    parsed = Envelope.from_dict(entry["message"])
    assert fingerprint(document(entry["message"])) == entry["fingerprint"]
    round_tripped = Envelope.from_dict(json.loads(json.dumps(entry["message"])))
    assert parsed.fingerprint() == round_tripped.fingerprint()
    assert parsed.to_dict() == document(entry["message"])


def test_every_message_kind_has_a_valid_fixture():
    assert {e["message"]["kind"] for e in VALID.values()} == set(v1.PRODUCERS)


@pytest.mark.parametrize("name", sorted(INVALID))
def test_invalid_envelope_fixture_is_refused_without_echoing_its_input(name):
    entry = INVALID[name]
    with pytest.raises(ContractError) as refusal:
        Envelope.from_dict(entry["message"])
    # Errors are logged and returned to peers: they must not repeat attacker-controlled text.
    for secret in ("https://", "X-Amz-Signature", "not-a-uuid"):
        assert secret not in str(refusal.value)


def test_fixtures_cover_the_documented_negative_classes():
    wanted = {
        "submit_without_source",
        "source_null_version_id",
        "payload_contains_signed_url",
        "payload_contains_credential_key",
        "cancellation_ack_confirmation_not_true",
        "result_without_job_but_with_source",
        "schema_version_two",
    }
    assert wanted <= set(INVALID)


# --- replay, reorder, cancel-before-submit ------------------------------------------------


def projected(event):
    return SimpleNamespace(
        state_version=event["state_version"],
        attempt_number=event["payload"]["attempt_number"],
        attempt_id=UUID(event["attempt_id"]),
        status=event["payload"]["status"],
        result_hash=fingerprint({k: v for k, v in event.items() if k != "message_id"}),
    )


def step_event(step):
    message = json.loads(json.dumps(VALID[step["use"]]["message"]))
    for field in ("message_id", "state_version", "attempt_id"):
        if field in step:
            message[field] = step[field]
    message["payload"] = {**message["payload"], **step.get("payload", {})}
    return document(message)


@pytest.mark.parametrize("name", sorted(SEQUENCES["sequences"]))
def test_result_sequences_apply_ignore_or_reject_exactly_as_frozen(name):
    sequence = SEQUENCES["sequences"][name]
    current, outcomes = None, []
    for step in sequence["steps"]:
        event = step_event(step)
        try:
            outcome = "applied" if validate_transition(current, event) else "stale"
        except MediaError as error:
            assert error.status_code == 409
            outcome = "conflict"
        if outcome == "applied":
            current = projected(event)
        outcomes.append(outcome)
    assert outcomes == sequence["expect"]


def test_a_stale_or_replayed_result_never_moves_the_projection_backwards():
    sequence = SEQUENCES["sequences"]["reordered_older_state_arrives_late"]
    current = projected(step_event(sequence["steps"][0]))
    late = step_event(sequence["steps"][1])
    before = (current.state_version, current.status)
    assert validate_transition(current, late) is False
    assert (current.state_version, current.status) == before


def test_cancel_before_submit_fixture_is_self_consistent():
    case = SEQUENCES["cancel_before_submit"]
    cancel = VALID[case["command"]]["message"]
    ack = VALID[case["acknowledgement"]]["message"]
    submit = VALID[case["late_submit"]]["message"]
    assert cancel["source"] is None and cancel["job_id"] is None and cancel["attempt_id"] is None
    assert ack["payload"]["command_message_id"] == cancel["message_id"]
    assert ack["owner_id"] == cancel["owner_id"] and ack["asset_id"] == cancel["asset_id"]
    assert submit["asset_id"] == cancel["asset_id"]
    Envelope.from_dict(submit)  # Shape-valid: refusal is Processing's persisted tombstone.


def test_conflicting_replay_changes_the_hash_of_one_message_id():
    case = SEQUENCES["conflicting_replay"]
    original = VALID[case["valid"]]["message"]
    changed = {**original, **case["mutation"]}
    assert changed["message_id"] == original["message_id"]
    assert fingerprint(document(changed)) != fingerprint(document(original))


@pytest.mark.parametrize(
    "case", ["cancel_before_submit", "conflicting_replay"], ids=lambda value: value
)
def test_behavioural_fixtures_name_tests_that_still_exist(case):
    for reference in SEQUENCES[case]["enforced_by"]:
        path, _, function = reference.partition("::")
        assert f"def {function}(" in (ROOT / path).read_text(), reference


# --- gateway events -----------------------------------------------------------------------


def probe_app():
    app = FastAPI()

    @app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE"])
    async def echo(path: str, request: Request):
        actor = getattr(request.state, "actor", None)
        return {
            "app_path": request.url.path,
            "actor": actor.owner_id if actor else None,
            "headers": sorted(request.headers),
            "cookie_header": request.headers.get("cookie"),
            "query": request.url.query,
        }

    return app


@pytest.mark.parametrize("name", sorted(EVENTS))
async def test_gateway_event_fixture_produces_its_frozen_outcome(name):
    case = EVENTS[name]
    result = await invoke_asgi(probe_app(), case["event"], service=case["service"])
    expect = case["expect"]
    assert result["statusCode"] == expect["status"], result
    if result["statusCode"] != 200:
        # Refusals are generic JSON and never reflect request input.
        assert set(json.loads(result["body"])) == {"error"}
        return
    seen = json.loads(result["body"])
    for field, key in (("actor", "actor"), ("app_path", "app_path"), ("query", "query")):
        if field in expect:
            assert seen[key] == expect[field], name
    if "cookie_header" in expect:
        assert seen["cookie_header"] == expect["cookie_header"]
    for header in expect.get("headers_absent", []):
        assert header not in seen["headers"]


def test_gateway_fixture_has_the_documented_negative_classes():
    required = {
        "forged_identity_headers_without_authorizer_context",
        "forged_public_identity_headers_are_stripped_and_ignored",
        "authorizer_context_with_unknown_role",
        "authorizer_context_with_wrong_integration_marker",
        "other_services_prefix_is_not_routed",
        "malformed_base64_body",
    }
    assert required <= set(EVENTS)


# --- authorizer ---------------------------------------------------------------------------

SECRET = "unit-signing-secret-at-least-32-bytes"


@pytest.fixture
def media_config():
    return MediaSettings(
        postgres_dsn="postgresql+asyncpg://unused:unused@invalid/media_db",
        jwt_secret=SECRET,
        runtime_mode="lambda",
    )


def mint(kind, user_id, config):
    now = datetime.now(UTC)
    if kind == "valid":
        return issue_token(user_id, config)
    if kind == "expired":
        claims = {
            "sub": str(user_id),
            "iat": now - timedelta(hours=2),
            "exp": now - timedelta(hours=1),
        }
        return jwt.encode(claims, SECRET, algorithm="HS256")
    if kind == "wrong-secret":
        claims = {"sub": str(user_id), "iat": now, "exp": now + timedelta(hours=1)}
        return jwt.encode(claims, "another-signing-secret-of-32-bytes!!", algorithm="HS256")
    assert kind == "no-exp"
    return jwt.encode({"sub": str(user_id), "iat": now}, SECRET, algorithm="HS256")


def authorizer_event(case, user_id, config):
    cookies = [
        entry["raw"] if "raw" in entry else f"access_token={mint(entry['token'], user_id, config)}"
        for entry in case["cookies"]
    ]
    return {
        "version": case.get("version", "2.0"),
        "cookies": cookies,
        "headers": case.get("headers", {}),
        "requestContext": {"http": {"method": "GET"}},
    }


def install_user(monkeypatch, config, spec, user_id):
    @asynccontextmanager
    async def session(_settings):
        if spec == "database-error":
            raise OSError("connection refused: password=hunter2")
        row = None if spec is None else User(id=user_id, email="u@example.test", password_hash="x")
        if row is not None:
            row.role = spec["role"]
        yield SimpleNamespace(get=AsyncMock(return_value=row))

    monkeypatch.setattr(authorizer, "invocation_session", session)
    monkeypatch.setattr(authorizer, "get_settings", lambda: config)


@pytest.mark.parametrize("name", sorted(AUTHORIZER))
async def test_authorizer_fixture_produces_its_frozen_decision(name, media_config, monkeypatch):
    case = AUTHORIZER[name]
    user_id = uuid4()
    install_user(monkeypatch, media_config, case["user"], user_id)
    result = await authorizer.authorize(authorizer_event(case, user_id, media_config))
    expect = case["expect"]
    assert result["isAuthorized"] is expect["authorized"]
    if not expect["authorized"]:
        assert set(result) == {"isAuthorized"}, "a denial carries no context to forward"
        return
    context = result["context"]
    assert Actor.from_context(context) == Actor(str(user_id), expect["context"]["role"])
    assert context["owner_id"] == str(user_id) != case.get("headers", {}).get("x-owner-id")


# --- authorizer output feeds the adapters -------------------------------------------------


def gateway_request(service, path, authorizer_result, cookie, method="GET", headers=None):
    request = {
        "version": "2.0",
        "rawPath": f"/api/{service}{path}",
        "rawQueryString": "",
        "headers": headers or {},
        "cookies": [cookie],
        "requestContext": {"http": {"method": method}},
    }
    if authorizer_result["isAuthorized"]:
        request["requestContext"]["authorizer"] = {"lambda": authorizer_result["context"]}
    return request


async def test_media_authorizer_context_is_accepted_by_the_media_adapter(
    media_config, monkeypatch
):
    user = User(id=uuid4(), email="a@example.com", password_hash="x", role="operator")
    install_user(monkeypatch, media_config, {"role": "operator"}, user.id)
    token = issue_token(user.id, media_config)
    cookie = f"access_token={token}"

    decision = await authorizer.authorize(
        {"version": "2.0", "cookies": [cookie], "requestContext": {"http": {}}}
    )
    assert decision["isAuthorized"] and decision["context"]["role"] == "publisher"

    app = create_v1_app()
    app.dependency_overrides[media_settings] = lambda: media_config

    async def sessions(request, config):
        yield SimpleNamespace(get=AsyncMock(return_value=user))

    monkeypatch.setattr(deps, "get_session", sessions)
    adapter = GatewayAdapter(app, service="media")
    forged = {"x-owner-id": str(uuid4()), "x-role": "operator"}
    request = gateway_request("media", "/auth/me", decision, cookie, headers=forged)
    ok = await adapter.invoke(request)
    assert ok["statusCode"] == 200
    assert json.loads(ok["body"])["id"] == str(user.id)

    # The context names one owner; a cookie for anyone else is refused by the application.
    other = User(id=uuid4(), email="b@example.com", password_hash="x", role="user")
    swapped = gateway_request(
        "media", "/auth/me", decision, f"access_token={issue_token(other.id, media_config)}"
    )

    async def other_sessions(request, config):
        yield SimpleNamespace(get=AsyncMock(return_value=other))

    monkeypatch.setattr(deps, "get_session", other_sessions)
    assert (await adapter.invoke(swapped))["statusCode"] == 401

    # A denied decision has no context, so the adapter refuses before the app runs.
    monkeypatch.setattr(deps, "get_session", sessions)
    denied = {"isAuthorized": False}
    assert (await adapter.invoke(gateway_request("media", "/auth/me", denied, cookie)))[
        "statusCode"
    ] == 401


class OwnedRows:
    """Evaluates the owner and id predicates the real query carries, from its bound values."""

    def __init__(self, rows):
        self.rows = rows

    async def execute(self, statement):
        bound = set(statement.compile(dialect=postgresql.dialect()).params.values())
        found = [(j, a) for j, a in self.rows if j.owner_id in bound and j.id in bound]

        class Result:
            def one_or_none(self):
                return found[0] if found else None

            def __iter__(self):
                return iter(found)

        return Result()


def job_pair(owner_id):
    now = datetime.now(UTC)
    job = SimpleNamespace(
        id=uuid4(),
        asset_id=uuid4(),
        owner_id=owner_id,
        status="queued",
        outputs=[],
        error=None,
        created_at=now,
        updated_at=now,
    )
    attempt = SimpleNamespace(
        id=uuid4(),
        attempt_number=1,
        state="queued",
        queued_at=now,
        started_at=None,
        finished_at=None,
        error=None,
    )
    return job, attempt


async def test_media_authorizer_context_scopes_the_processing_adapter_by_owner(
    media_config, monkeypatch
):
    owner, intruder = uuid4(), uuid4()
    pair = job_pair(owner)
    app = v1_api.create_app()
    app.dependency_overrides[processing_settings] = lambda: ProcessingSettings(
        postgres_dsn="postgresql://runtime@unused/processing_db", database_tls=False
    )
    app.dependency_overrides[get_v1_session] = lambda: OwnedRows([pair])
    adapter = GatewayAdapter(app, service="processing")

    async def decide(user_id):
        install_user(monkeypatch, media_config, {"role": "user"}, user_id)
        cookie = f"access_token={issue_token(user_id, media_config)}"
        decision = await authorizer.authorize(
            {"version": "2.0", "cookies": [cookie], "requestContext": {"http": {}}}
        )
        return gateway_request("processing", f"/jobs/{pair[0].id}", decision, cookie)

    mine = await adapter.invoke(await decide(owner))
    assert mine["statusCode"] == 200
    assert json.loads(mine["body"])["processing_job_id"] == str(pair[0].id)
    # Same job id, a different authenticated owner: indistinguishable from absent.
    theirs = await adapter.invoke(await decide(intruder))
    assert theirs["statusCode"] == 404
    assert "Job not found" in theirs["body"]
