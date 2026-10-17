"""Media's owned command outbox and result inbox boundary."""

from contracts.v1 import EMIT_VERSION
from delivery.envelope import document
from delivery.sql import accept, publish_due, stage
from media.messaging_models import MediaInbox, MediaOutbox


async def stage_command(session, envelope):
    body = document(envelope)
    if body["kind"] not in {"submit", "retry", "cancel"}:
        raise ValueError("Media produces commands only")
    return await stage(session, MediaOutbox, body, "processing-commands")


async def consume_result(session, envelope, apply):
    body = document(envelope)
    if body["kind"] != "result":
        raise ValueError("Media consumes results only")
    async with session.begin():
        if not await accept(session, MediaInbox, body):
            return False
        await apply(session, body)
    return True


async def publish_commands(factory, transport, **kwargs):
    return await publish_due(factory, MediaOutbox, transport, **kwargs)


async def enqueue_submit(session, asset, source):
    """Finalize helper: caller owns adoption transaction and immutable descriptor."""
    from uuid import uuid4

    return await stage_command(
        session,
        {
            "schema_version": EMIT_VERSION,
            "message_id": str(uuid4()),
            "kind": "submit",
            "owner_id": str(asset.owner_id),
            "asset_id": str(asset.id),
            "job_id": str(asset.processing_job_id) if asset.processing_job_id else None,
            "attempt_id": None,
            "state_version": 0,
            "source": source,
            "payload": {"operations": asset.operations or []},
        },
    )
