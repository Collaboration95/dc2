import copy
from uuid import uuid4

import pytest

from contracts.v1 import Actor, ContractError, Envelope, Source


def message(kind="submit"):
    return {
        "schema_version": 1,
        "message_id": str(uuid4()),
        "kind": kind,
        "owner_id": str(uuid4()),
        "asset_id": str(uuid4()),
        "job_id": None,
        "attempt_id": None,
        "state_version": 0,
        "source": {
            "bucket": "sources",
            "key": "owned/source",
            "version_id": "immutable-v1",
            "sha256": "a" * 64,
            "size_bytes": 10,
            "content_type": "video/mp4",
        },
        "payload": {},
    }


@pytest.mark.parametrize(
    "update",
    [
        {"schema_version": True},
        {"schema_version": "1"},
        {"role": "admin"},
        {"owner_id": "forged"},
        {"integration": "other"},
    ],
)
def test_actor_requires_verified_schema(update):
    context = Actor(str(uuid4()), "publisher").to_context()
    with pytest.raises(ContractError):
        Actor.from_context(context | update)


def test_actor_round_trip():
    actor = Actor(str(uuid4()), "viewer")
    assert Actor.from_context(actor.to_context()) == actor


def test_message_replay_hash_and_binding():
    value = message("work")
    value.update(job_id=str(uuid4()), attempt_id=str(uuid4()))
    event = Envelope.from_dict(value)
    assert Envelope.from_dict(copy.deepcopy(value)).fingerprint() == event.fingerprint()
    event.assert_bound(
        owner_id=value["owner_id"],
        asset_id=value["asset_id"],
        source=Source.from_dict(value["source"]),
        job_id=value["job_id"],
        attempt_id=value["attempt_id"],
    )
    with pytest.raises(ContractError):
        event.assert_bound(owner_id=str(uuid4()), asset_id=value["asset_id"], source=event.source)
    value["state_version"] += 1
    assert Envelope.from_dict(value).fingerprint() != event.fingerprint()


@pytest.mark.parametrize(
    "update",
    [
        {"state_version": -1},
        {"state_version": True},
        {"source": None},
        {"kind": "unknown"},
        {"payload": {"source_url": "private"}},
        {"payload": {"nested": ["https://signed.example"]}},
        {"payload": {"secret": "x"}},
        {"payload": {"nan": float("nan")}},
    ],
)
def test_invalid_message(update):
    with pytest.raises(ContractError):
        Envelope.from_dict(message() | update)


def test_cancel_before_submit_needs_no_source_or_job():
    value = message("cancel") | {"source": None}
    assert Envelope.from_dict(value).job_id is None


@pytest.mark.parametrize(
    "update",
    [
        {"version_id": "null"},
        {"size_bytes": True},
        {"size_bytes": 104857601},
        {"sha256": "wrong"},
        {"key": "https://example"},
    ],
)
def test_source_requires_immutable_verified_revision(update):
    with pytest.raises(ContractError):
        Source.from_dict(message()["source"] | update)


def cancellation_ack():
    return message("result") | {
        "source": None,
        "payload": {
            "status": "cancelled",
            "cancellation_confirmed": True,
            "command_message_id": str(uuid4()),
        },
    }


def test_cancel_before_submit_ack_has_no_invented_job_source_or_attempt():
    value = cancellation_ack()
    envelope = Envelope.from_dict(value)
    assert envelope.source is None
    assert envelope.job_id is None and envelope.attempt_id is None
    assert envelope.to_dict() == value
    assert Envelope.from_dict(envelope.to_dict()).fingerprint() == envelope.fingerprint()
    changed = copy.deepcopy(value)
    changed["payload"]["command_message_id"] = str(uuid4())
    assert Envelope.from_dict(changed).fingerprint() != envelope.fingerprint()


@pytest.mark.parametrize(
    "update",
    [
        {"job_id": str(uuid4())},
        {"attempt_id": str(uuid4())},
        {"source": message()["source"]},
        {"kind": "work"},
    ],
)
def test_cancellation_ack_exception_is_result_only_with_both_ids_and_source_null(update):
    with pytest.raises(ContractError):
        Envelope.from_dict(cancellation_ack() | update)


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"status": "cancelled", "command_message_id": str(uuid4())},
        {
            "status": "cancelled",
            "cancellation_confirmed": False,
            "command_message_id": str(uuid4()),
        },
        {"status": "cancelled", "cancellation_confirmed": 1, "command_message_id": str(uuid4())},
        {
            "status": "cancelled",
            "cancellation_confirmed": "true",
            "command_message_id": str(uuid4()),
        },
        {"status": "done", "cancellation_confirmed": True, "command_message_id": str(uuid4())},
        {"status": "cancelled", "cancellation_confirmed": True},
        {"status": "cancelled", "cancellation_confirmed": True, "command_message_id": None},
        {"status": "cancelled", "cancellation_confirmed": True, "command_message_id": "not-a-uuid"},
        {
            "status": "cancelled",
            "cancellation_confirmed": True,
            "command_message_id": str(uuid4()),
            "outputs": [],
        },
    ],
)
def test_cancellation_ack_requires_exact_explicit_confirmation_and_command_uuid(payload):
    with pytest.raises(ContractError):
        Envelope.from_dict(cancellation_ack() | {"payload": payload})


@pytest.mark.parametrize("kind", ["work", "result"])
@pytest.mark.parametrize("missing", ["job_id", "attempt_id", "both"])
def test_normal_job_messages_still_require_job_and_attempt(kind, missing):
    value = message(kind) | {
        "job_id": str(uuid4()),
        "attempt_id": str(uuid4()),
        "payload": {"status": "done"},
    }
    Envelope.from_dict(value)
    if missing in ("job_id", "both"):
        value["job_id"] = None
    if missing in ("attempt_id", "both"):
        value["attempt_id"] = None
    with pytest.raises(ContractError):
        Envelope.from_dict(value)


def test_existing_job_cancellation_result_remains_valid():
    value = message("result") | {
        "job_id": str(uuid4()),
        "attempt_id": str(uuid4()),
        "payload": {"status": "cancelled", "outputs": []},
    }
    assert Envelope.from_dict(value).job_id == value["job_id"]


def test_consumers_accept_this_version_and_the_one_before_it(monkeypatch):
    from contracts import v1

    monkeypatch.setattr(v1, "SCHEMA_VERSION", 2)
    assert v1.accepted_versions() == {1, 2}
    older = message("work") | {"job_id": str(uuid4()), "attempt_id": str(uuid4())}
    assert older["schema_version"] == 1
    assert Envelope.from_dict(older).schema_version == 1
    assert Envelope.from_dict(older | {"schema_version": 2}).schema_version == 2
    context = Actor(str(uuid4()), "viewer").to_context()
    assert context["schema_version"] == 1  # Nothing stamps 2 until EMIT_VERSION is raised.
    assert Actor.from_context(context | {"schema_version": 2}).role == "viewer"
    assert Actor.from_context(context).role == "viewer"


@pytest.mark.parametrize("version", [3, 0, -1, True, "2", 2.0, None])
def test_a_version_beyond_the_next_one_or_not_an_integer_is_refused(monkeypatch, version):
    from contracts import v1

    monkeypatch.setattr(v1, "SCHEMA_VERSION", 2)
    with pytest.raises(ContractError):
        Envelope.from_dict(message() | {"schema_version": version})
    with pytest.raises(ContractError):
        Actor.from_context(Actor(str(uuid4()), "viewer").to_context() | {"schema_version": version})


def test_the_first_version_has_no_predecessor_to_accept():
    from contracts import v1

    assert v1.SCHEMA_VERSION == 1 and v1.accepted_versions() == {1}


def test_an_unknown_envelope_source_and_actor_field_is_ignored_not_carried():
    added = message("work") | {
        "job_id": str(uuid4()),
        "attempt_id": str(uuid4()),
        "priority": "high",
    }
    added["source"] = added["source"] | {"storage_class": "GLACIER"}
    parsed = Envelope.from_dict(added)
    plain = message("work") | {"job_id": added["job_id"], "attempt_id": added["attempt_id"]}
    plain["message_id"], plain["owner_id"], plain["asset_id"] = (
        added["message_id"],
        added["owner_id"],
        added["asset_id"],
    )
    assert parsed.fingerprint() == Envelope.from_dict(plain).fingerprint()
    assert "priority" not in parsed.to_dict() and "storage_class" not in parsed.to_dict()["source"]
    context = Actor(str(uuid4()), "publisher").to_context() | {"tenant": "t-1"}
    assert Actor.from_context(context).role == "publisher"


def test_a_missing_known_field_is_still_refused():
    value = message()
    del value["asset_id"]
    with pytest.raises(ContractError):
        Envelope.from_dict(value)
    broken = message()
    del broken["source"]["sha256"]
    with pytest.raises(ContractError):
        Envelope.from_dict(broken)


def test_producers_never_emit_a_version_the_consumers_would_refuse():
    from contracts import v1

    assert v1.EMIT_VERSION in v1.accepted_versions()
    assert v1.EMIT_VERSION <= v1.SCHEMA_VERSION


def test_a_producer_may_trail_the_readable_version_during_a_rollout(monkeypatch):
    from contracts import v1

    # Release 1 of a bump: every service can read 2, nobody sends it yet.
    monkeypatch.setattr(v1, "SCHEMA_VERSION", 2)
    assert Actor(str(uuid4()), "viewer").to_context()["schema_version"] == 1
    # Release 2: every consumer is deployed with release 1, so producers may stamp 2.
    monkeypatch.setattr(v1, "EMIT_VERSION", 2)
    assert Actor(str(uuid4()), "viewer").to_context()["schema_version"] == 2


def test_no_service_hardcodes_the_schema_version_it_stamps_on_a_message():
    import ast
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    for package in ("media", "processing"):
        for path in (root / package).rglob("*.py"):
            for node in ast.walk(ast.parse(path.read_text())):
                if not isinstance(node, ast.Dict):
                    continue
                for key, value in zip(node.keys, node.values, strict=True):
                    if isinstance(key, ast.Constant) and key.value == "schema_version":
                        # The health endpoint reports the service's own wire version as data.
                        assert not isinstance(value, ast.Constant) or path.name == "v1_api.py", path
