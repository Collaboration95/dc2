"""Consumer-driven contract between Processing and Media, from Processing's side (#198).

Processing owns tests/contracts/consumers/processing_consumes_media_commands.json: the
commands it consumes and the fields it reads. Media must keep producing messages that satisfy
it (tests/media/test_media_consumer_contract.py checks that); this file proves Processing's real
command consumer still reads every message in it, including what a newer Media may send
without a lockstep release: an additive field and the previous schema version. The reverse
direction is Processing producing the results that
tests/contracts/consumers/media_consumes_processing_results.json declares.
"""

import json
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import UUID

import pytest
from _processing_doubles import NOW, Session

from contracts import v1
from processing import lifecycle, messaging, short_lane
from processing.worker.storage import OutputStore

CONSUMERS = Path(__file__).resolve().parents[1] / "contracts" / "consumers"
COMMANDS = json.loads((CONSUMERS / "processing_consumes_media_commands.json").read_text())
RESULTS = json.loads((CONSUMERS / "media_consumes_processing_results.json").read_text())


def tolerated(message):
    """What a newer producer may add without a version bump: fields nobody here reads yet."""
    extended = deepcopy(message)
    extended["trace_id"] = "0af7651916cd43dd8448eb211c80319c"
    if extended["source"] is not None:
        extended["source"]["storage_class"] = "STANDARD"
    extended["payload"]["priority"] = "high"
    return extended


VARIANTS = {"as_published": lambda message: message, "with_additive_fields": tolerated}


class Consumer:
    """handle_command with the SQL boundary doubled, so only the message reading is real."""

    def __init__(self, monkeypatch):
        self.session = Session()
        self.guard = SimpleNamespace(job_id=None, deleted_at=None, owner_id=None, asset_id=None)
        self.emitted = AsyncMock()
        self.retry = AsyncMock()
        self.cancel = AsyncMock()
        monkeypatch.setattr(messaging, "accept", AsyncMock(return_value=True))
        monkeypatch.setattr(messaging, "_guard", AsyncMock(return_value=self.guard))
        monkeypatch.setattr(messaging, "emit_state", self.emitted)
        monkeypatch.setattr(messaging, "_retry_locked", self.retry)
        monkeypatch.setattr(messaging, "_cancel_locked", self.cancel)
        monkeypatch.setattr(lifecycle, "db_now", AsyncMock(return_value=NOW))

    def existing_job(self, published):
        job = SimpleNamespace(
            id=UUID(published["job_id"]),
            owner_id=UUID(published["owner_id"]),
            asset_id=UUID(published["asset_id"]),
            source=published["source"],
            request_hash="",
        )
        self.guard.job_id = job.id
        self.session.scalar.return_value = job
        self.session.get.return_value = job
        return job

    async def handle(self, message):
        return await messaging.handle_command(lambda: self.session, message)


@pytest.fixture
def consumer(monkeypatch):
    return Consumer(monkeypatch)


@pytest.mark.parametrize("variant", VARIANTS)
@pytest.mark.parametrize("name", ["submit", "submit_with_operations"])
async def test_processing_creates_a_job_from_every_submit_media_promises_to_send(
    consumer, name, variant
):
    published = COMMANDS["messages"][name]
    assert await consumer.handle(VARIANTS[variant](published))
    job = consumer.session.add.call_args_list[0].args[0]
    assert (str(job.owner_id), str(job.asset_id)) == (published["owner_id"], published["asset_id"])
    # The additive source field is not part of the immutable descriptor Processing stores.
    assert job.source == published["source"]
    assert job.operations == published["payload"]["operations"]
    assert job.status == "queued"
    consumer.emitted.assert_awaited_once()


@pytest.mark.parametrize("variant", VARIANTS)
async def test_processing_retries_the_named_job_on_the_retry_media_promises_to_send(
    consumer, variant
):
    published = COMMANDS["messages"]["retry"]
    job = consumer.existing_job(published)
    assert await consumer.handle(VARIANTS[variant](published))
    consumer.retry.assert_awaited_once_with(consumer.session, job, UUID(published["message_id"]))


@pytest.mark.parametrize("variant", VARIANTS)
@pytest.mark.parametrize("name", ["cancel_existing_job", "cancel_before_submit"])
async def test_processing_cancels_on_every_cancel_media_promises_to_send(consumer, name, variant):
    published = COMMANDS["messages"][name]
    if published["job_id"]:
        consumer.existing_job(published)
    assert await consumer.handle(VARIANTS[variant](published))
    consumer.cancel.assert_awaited_once_with(
        consumer.session, consumer.guard, command_message_id=published["message_id"]
    )


@pytest.mark.parametrize("name", sorted(COMMANDS["messages"]))
async def test_processing_still_reads_commands_stamped_with_the_previous_schema_version(
    consumer, monkeypatch, name
):
    published = COMMANDS["messages"][name]
    # A Media that has not been redeployed after Processing moved to the next version.
    monkeypatch.setattr(v1, "SCHEMA_VERSION", published["schema_version"] + 1)
    if published["job_id"] and published["kind"] != "submit":
        consumer.existing_job(published)
    assert await consumer.handle(published)


@pytest.mark.parametrize("name", sorted(COMMANDS["messages"]))
async def test_processing_refuses_a_command_from_a_future_schema_version(consumer, name):
    message = deepcopy(COMMANDS["messages"][name]) | {"schema_version": v1.SCHEMA_VERSION + 1}
    with pytest.raises(v1.ContractError):
        await consumer.handle(message)
    consumer.session.add.assert_not_called()


def test_the_commands_contract_declares_every_kind_it_reads():
    kinds = {m["kind"] for m in COMMANDS["messages"].values()}
    assert kinds == set(COMMANDS["reads"]["kinds"])


# --- Processing as the producer of the results Media consumes -----------------------------


def satisfies(message, reads):
    """The consumer-declared expectations, checked on what the producer really built."""
    assert set(reads["envelope"]) <= set(message)
    assert message["kind"] == "result"
    payload = message["payload"]
    assert set(reads["payload"]["always"]) <= set(payload)
    assert payload["status"] in reads["statuses"]
    assert set(reads["payload"].get(payload["status"], [])) <= set(payload)
    prefix = reads["output_key_prefix"].format(
        job_id=message["job_id"], attempt_id=message["attempt_id"]
    )
    for output in payload.get("outputs", []):
        assert set(reads["output"]) <= set(output)
        assert output["object_key"].startswith(prefix)
    v1.Envelope.from_dict(message)


async def uploaded(job_id, attempt_id, tmp_path):
    """Outputs exactly as the encoder's OutputStore reports them after a PUT."""
    store = OutputStore.__new__(OutputStore)
    store.bucket = "outputs"
    store.client = Mock()

    def put_object(_bucket, _key, reader, size, **_):
        reader.read(size)  # The store verifies it hashed every byte it sent.
        return SimpleNamespace(etag="acknowledged")

    store.client.put_object.side_effect = put_object
    prefix = lifecycle.output_prefix(job_id, attempt_id)
    primary, manifest = tmp_path / "primary.mp4", tmp_path / "master.m3u8"
    primary.write_bytes(b"video"), manifest.write_bytes(b"#EXTM3U")
    return [
        await store.put(prefix + "primary.mp4", primary, "video/mp4", "primary"),
        await store.put(
            prefix + "hls/master.m3u8", manifest, "application/vnd.apple.mpegurl", "hls_manifest"
        ),
    ]


@pytest.mark.parametrize("status", ["queued", "processing", "done", "failed", "cancelled"])
async def test_processing_result_for_every_status_satisfies_what_media_reads(
    monkeypatch, tmp_path, status
):
    sample = RESULTS["messages"]["done"]
    ids = {k: UUID(sample[k]) for k in ("owner_id", "asset_id", "job_id", "attempt_id")}
    outputs = await uploaded(ids["job_id"], ids["attempt_id"], tmp_path) if status == "done" else []
    job = SimpleNamespace(
        id=ids["job_id"],
        owner_id=ids["owner_id"],
        asset_id=ids["asset_id"],
        source=sample["source"],
        operations=[],
        status="queued" if status == "cancelled" else status,
        outputs=outputs,
        error="The source or edit could not be processed" if status == "failed" else None,
        deleted_at=NOW if status == "cancelled" else None,
    )
    attempt = SimpleNamespace(id=ids["attempt_id"], attempt_number=1, state=job.status)
    staged = AsyncMock()
    monkeypatch.setattr(messaging, "stage", staged)
    monkeypatch.setattr(lifecycle, "db_now", AsyncMock(return_value=NOW))
    monkeypatch.setattr(short_lane, "work_lane", AsyncMock(return_value="processing-work"))
    session = Session()
    session.get.return_value = SimpleNamespace(state_version=2)
    await messaging.emit_state(session, job, attempt)
    results = [c for c in staged.await_args_list if c.args[2]["kind"] == "result"]
    assert len(results) == 1
    assert results[0].args[3] == RESULTS["queue"]
    satisfies(results[0].args[2], RESULTS["reads"])
    assert results[0].args[2]["payload"]["status"] == status


async def test_processing_cancel_before_submit_acknowledgement_satisfies_what_media_reads(
    monkeypatch,
):
    sample = RESULTS["messages"]["cancellation_ack"]
    guard = SimpleNamespace(
        job_id=None,
        deleted_at=None,
        owner_id=UUID(sample["owner_id"]),
        asset_id=UUID(sample["asset_id"]),
    )
    staged = AsyncMock()
    monkeypatch.setattr(messaging, "stage", staged)
    monkeypatch.setattr(lifecycle, "db_now", AsyncMock(return_value=NOW))
    command_id = sample["payload"]["command_message_id"]
    await messaging._cancel_locked(Session(), guard, command_message_id=command_id)
    ((_, _, message, queue),) = [c.args for c in staged.await_args_list]
    assert queue == RESULTS["queue"]
    assert set(RESULTS["reads"]["envelope"]) <= set(message)
    assert message["job_id"] is None and message["source"] is None
    assert message["payload"] == sample["payload"]
    v1.Envelope.from_dict(message)


def test_the_results_contract_examples_cover_the_statuses_media_reads():
    statuses = {m["payload"]["status"] for m in RESULTS["messages"].values()}
    assert statuses == set(RESULTS["reads"]["statuses"])
