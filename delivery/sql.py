"""SQL-authoritative at-least-once delivery. Network I/O never spans SQL locks."""

import asyncio
import time
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from delivery.envelope import document, fingerprint


class MessageConflict(ValueError):
    pass


async def accept(session, model, envelope):
    """Call inside the domain mutation transaction; a rollback rolls back dedupe."""
    body = document(envelope)
    identity, digest = UUID(body["message_id"]), fingerprint(body)
    inserted = await session.scalar(
        insert(model)
        .values(message_id=identity, body_hash=digest)
        .on_conflict_do_nothing(index_elements=[model.message_id])
        .returning(model.message_id)
    )
    if inserted is not None:
        return True
    saved = await session.get(model, identity)
    if saved.body_hash != digest:
        raise MessageConflict("Message ID reused with different content")
    return False


async def stage(session, model, envelope, queue):
    """No implicit commit: owned state and message must commit together."""
    body = document(envelope)
    identity, digest = UUID(body["message_id"]), fingerprint(body)
    await session.execute(
        insert(model)
        .values(
            message_id=identity,
            body_hash=digest,
            body=body,
            queue=queue,
            next_try_at=datetime.now(UTC),
            tries=0,
        )
        .on_conflict_do_nothing(index_elements=[model.message_id])
    )
    saved = await session.get(model, identity)
    if saved.body_hash != digest or saved.queue != queue:
        raise MessageConflict("Outbox ID reused with different content")
    return identity


async def publish_due(
    factory,
    model,
    transport,
    *,
    limit=100,
    deadline=None,
    replay_seconds=518400,
    reservation_seconds=30,
):
    """Reserve, commit, send, then fence acknowledgement. Lost replies replay safely.

    Retain sent rows: replay before source-queue retention expires. Work should use
    a <=120s replay interval or the domain's SQL queued-work repair.
    """
    from sqlalchemy import func

    count = 0
    for _ in range(limit):
        if deadline is not None and time.monotonic() >= deadline:
            break
        async with factory() as session, session.begin():
            now = await session.scalar(select(func.clock_timestamp()))
            row = await session.scalar(
                select(model)
                .where(model.next_try_at <= now)
                .order_by(model.next_try_at, model.message_id)
                .with_for_update(skip_locked=True)
                .limit(1)
            )
            if row is None:
                break
            token = uuid4()
            row.claim_token = token
            row.tries += 1
            row.next_try_at = now + timedelta(seconds=reservation_seconds)
            identity, queue, body = row.message_id, row.queue, row.body
        error = None
        try:
            # Clients have bounded SDK connect/read/retry settings; caller also
            # supplies a monotonic invocation deadline to avoid unbounded passes.
            if deadline is None:
                await transport.send(queue, body)
            else:
                async with asyncio.timeout(max(0.001, deadline - time.monotonic())):
                    await transport.send(queue, body)
        except Exception:
            error = "Queue publication unavailable"
        async with factory() as session, session.begin():
            row = await session.get(model, identity, with_for_update=True)
            if row is None or row.claim_token != token:
                continue
            now = await session.scalar(select(func.clock_timestamp()))
            row.claim_token = None
            row.last_error = error
            row.next_try_at = now + timedelta(
                seconds=min(60, 2 ** min(row.tries, 6)) if error else replay_seconds
            )
            if error is None:
                row.sent_at = now
                count += 1
    return count
