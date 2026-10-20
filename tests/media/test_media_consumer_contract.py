"""Consumer-driven contract between Media and Processing, from Media's side (#198).

Media owns tests/contracts/consumers/media_consumes_processing_results.json: the result
messages it consumes and the fields it reads. Processing must keep producing messages that
satisfy it (tests/processing/test_processing_consumer_contract.py checks that), and this file proves
Media's real consumer still reads every message in it, including the changes a newer
Processing is allowed to make without a lockstep release: an additive field and the
previous schema version. The reverse direction is Media producing the commands that
tests/contracts/consumers/processing_consumes_media_commands.json declares.
"""

import json
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest

from contracts import v1
from media import projections
from media.messaging import consume_result
from media.messaging_models import MediaOutbox
from media.models import CleanupIntent, now
from media.projection_models import ProcessingProjection
from media.services import v1_lifecycle

CONSUMERS = Path(__file__).resolve().parents[1] / "contracts" / "consumers"
RESULTS = json.loads((CONSUMERS / "media_consumes_processing_results.json").read_text())
COMMANDS = json.loads((CONSUMERS / "processing_consumes_media_commands.json").read_text())


def tolerated(message):
    """What a newer producer may add without a version bump: fields nobody here reads yet."""
    extended = deepcopy(message)
    extended["trace_id"] = "0af7651916cd43dd8448eb211c80319c"
    if extended["source"] is not None:
        extended["source"]["storage_class"] = "STANDARD"
    # The cancellation acknowledgement's payload is a closed object by contract; every other
    # payload is an open map of which Media reads only the keys it names.
    if "cancellation_confirmed" not in extended["payload"]:
        extended["payload"]["encoder"] = {"name": "x264"}
    for output in extended["payload"].get("outputs", []):
        output["duration_ms"] = 1000
    return extended


VARIANTS = {"as_published": lambda message: message, "with_additive_fields": tolerated}


def prepare(session, asset, message, monkeypatch, accepted_source):
    """Put Media in the state in which this result is expected to arrive."""
    ack = message["job_id"] is None
    asset.id, asset.owner_id = UUID(message["asset_id"]), UUID(message["owner_id"])
    asset.processing_job_id = None if ack else UUID(message["job_id"])
    asset.deleted_at = now() if message["payload"]["status"] == "cancelled" else None
    intent = CleanupIntent(asset_id=asset.id)
    command = SimpleNamespace(
        queue="processing-commands",
        body={
            "kind": "cancel",
            "owner_id": message["owner_id"],
            "asset_id": message["asset_id"],
            "job_id": None,
        },
    )

    async def get(model, key, **_):
        return {CleanupIntent: intent, MediaOutbox: command}.get(model)

    session.get.side_effect = get
    session.scalar.return_value = UUID(message["message_id"])
    monkeypatch.setattr(projections, "get_asset", AsyncMock(return_value=asset))
    monkeypatch.setattr(projections, "source_for_asset", AsyncMock(return_value=accepted_source))
    return intent


@pytest.mark.parametrize("variant", VARIANTS)
@pytest.mark.parametrize("name", sorted(RESULTS["messages"]))
async def test_media_consumes_every_result_processing_promises_to_send(
    session, asset, monkeypatch, name, variant
):
    published = RESULTS["messages"][name]
    message = VARIANTS[variant](published)
    intent = prepare(session, asset, message, monkeypatch, published["source"])
    assert await consume_result(session, message, projections.apply_result)
    status = message["payload"]["status"]
    if name == "cancellation_ack":
        assert intent.processing_deleted_at is not None
        return
    if name == "cancelled":
        assert intent.processing_deleted_at is not None
        return
    saved = session.add.call_args.args[0]
    assert isinstance(saved, ProcessingProjection)
    assert saved.status == status
    assert saved.state_version == message["state_version"]
    assert saved.attempt_number == message["payload"]["attempt_number"]
    assert saved.error == message["payload"]["error"]
    assert [o["kind"] for o in saved.outputs] == [o["kind"] for o in message["payload"]["outputs"]]
    # The unknown fields were dropped on the way in: nothing of them is stored or hashed.
    assert "duration_ms" not in json.dumps(saved.outputs)
    stored = v1.Envelope.from_dict(message).to_dict()
    assert saved.result_hash == projections.fingerprint(
        {k: v for k, v in stored.items() if k != "message_id"}
    )
    assert "trace_id" not in stored and "storage_class" not in json.dumps(stored["source"])


@pytest.mark.parametrize("name", sorted(RESULTS["messages"]))
async def test_media_still_reads_results_stamped_with_the_previous_schema_version(
    session, asset, monkeypatch, name
):
    # A Processing that has not been redeployed after Media moved to the next version.
    monkeypatch.setattr(v1, "SCHEMA_VERSION", RESULTS["messages"][name]["schema_version"] + 1)
    assert v1.accepts_version(RESULTS["messages"][name]["schema_version"])
    message = RESULTS["messages"][name]
    prepare(session, asset, message, monkeypatch, message["source"])
    assert await consume_result(session, message, projections.apply_result)


@pytest.mark.parametrize("name", sorted(RESULTS["messages"]))
async def test_media_refuses_a_result_from_a_future_schema_version(
    session, asset, monkeypatch, name
):
    message = deepcopy(RESULTS["messages"][name])
    message["schema_version"] = v1.SCHEMA_VERSION + 1
    prepare(session, asset, message, monkeypatch, message["source"])
    with pytest.raises(v1.ContractError):
        await consume_result(session, message, projections.apply_result)
    session.add.assert_not_called()


def test_the_results_contract_declares_what_media_reads_and_every_status_is_exemplified():
    reads = RESULTS["reads"]
    statuses = {m["payload"]["status"] for m in RESULTS["messages"].values()}
    assert statuses == set(reads["statuses"])
    for message in RESULTS["messages"].values():
        assert set(reads["envelope"]) <= set(message)
        status = message["payload"]["status"]
        if message["job_id"] is None:
            continue
        assert set(reads["payload"]["always"]) <= set(message["payload"])
        assert set(reads["payload"].get(status, [])) <= set(message["payload"])


# --- Media as the producer of the commands Processing consumes ----------------------------


class Recorded:
    def __init__(self):
        self.sent = []

    async def __call__(self, session, envelope):
        self.sent.append(envelope)


@pytest.fixture
def recorded(monkeypatch):
    recorder = Recorded()
    monkeypatch.setattr("media.messaging.stage_command", recorder)
    return recorder


def satisfies(message, reads):
    """The consumer-declared expectations, checked on what the producer really built."""
    kind = message["kind"]
    assert kind in reads["kinds"]
    assert set(reads["envelope"]) <= set(message)
    assert set(reads["payload"][kind]) <= set(message["payload"])
    if kind in reads["source_required_for"]:
        assert message["source"] is not None
    if message["source"] is not None:
        assert set(reads["source"]) <= set(message["source"])
        prefixes = [p.format(owner_id=message["owner_id"]) for p in reads["source_key_prefixes"]]
        assert message["source"]["key"].startswith(tuple(prefixes))
    v1.Envelope.from_dict(message)


@pytest.fixture
def staged_source(asset):
    return {
        "bucket": "dc2-source",
        "key": f"staging/{asset.owner_id}/{uuid4()}/source",
        "version_id": "3sL4kqtJlcpXroDTDmJ",
        "sha256": "a" * 64,
        "size_bytes": 1024,
        "content_type": "video/mp4",
    }


async def test_media_submit_command_satisfies_what_processing_reads(
    session, asset, recorded, staged_source
):
    asset.processing_job_id = None
    asset.operations = [{"operation": "clip", "params": {"start": 0, "end": 3}}]
    await v1_lifecycle.stage_submit(session, asset, staged_source)
    (message,) = recorded.sent
    satisfies(message, COMMANDS["reads"])
    assert message["kind"] == "submit"
    assert message["payload"]["operations"] == asset.operations


async def test_media_retry_command_satisfies_what_processing_reads(
    session, asset, recorded, staged_source
):
    await v1_lifecycle.command(session, asset, "retry", source=staged_source)
    (message,) = recorded.sent
    satisfies(message, COMMANDS["reads"])
    assert message["job_id"] == str(asset.processing_job_id)


@pytest.mark.parametrize("submitted", [True, False])
async def test_media_cancel_command_satisfies_what_processing_reads(
    session, asset, recorded, submitted
):
    if not submitted:
        asset.processing_job_id = None
    await v1_lifecycle.command(session, asset, "cancel")
    (message,) = recorded.sent
    satisfies(message, COMMANDS["reads"])
    assert (message["job_id"] is not None) is submitted


def test_the_commands_contract_examples_satisfy_their_own_declared_reads():
    for message in COMMANDS["messages"].values():
        satisfies(message, COMMANDS["reads"])
