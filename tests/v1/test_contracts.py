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
