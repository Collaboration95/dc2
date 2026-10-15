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
