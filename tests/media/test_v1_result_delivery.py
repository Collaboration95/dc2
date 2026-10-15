"""Owned inbox/application/commit boundary with explicit SQL and SQS doubles."""

# ruff: noqa: F811 -- imported pytest fixture is intentionally injected by name.

import json
from contextlib import asynccontextmanager
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID

import pytest
from delivery.envelope import fingerprint
from delivery.sql import MessageConflict
from delivery.sqs import consume_batch
from media.messaging import consume_result
from media.messaging_models import MediaInbox

from media import projections

# Reuse wire fixture from the focused projection tests.
from tests.media.test_v1_projection import event  # noqa: F401


async def test_projection_commits_before_successful_batch_ack(
    session,
    asset,
    event,
    monkeypatch,
):
    order = []

    @asynccontextmanager
    async def begin():
        order.append("begin")
        yield
        order.append("commit")

    session.begin.side_effect = begin
    session.scalar.return_value = UUID(event["message_id"])
    monkeypatch.setattr(projections, "get_asset", AsyncMock(return_value=asset))
    monkeypatch.setattr(projections, "source_for_asset", AsyncMock(return_value=event["source"]))

    async def apply(db, body):
        assert order == ["begin"]
        await projections.apply_result(db, body)
        order.append("projection")

    async def handle(body):
        await consume_result(session, body, apply)
        assert order == ["begin", "projection", "commit"]
        order.append("ack-eligible")

    response = await consume_batch(
        {"Records": [{"messageId": "receipt-1", "body": json.dumps(event)}]},
        "media-results",
        handle,
    )
    assert response == {"batchItemFailures": []}
    assert order[-1] == "ack-eligible"


@pytest.mark.parametrize("failure_at", ["apply", "commit"])
async def test_apply_or_commit_failure_never_acknowledges(session, event, failure_at):
    @asynccontextmanager
    async def begin():
        yield
        if failure_at == "commit":
            raise OSError("commit acknowledgement lost")

    session.begin.side_effect = begin
    session.scalar.return_value = UUID(event["message_id"])
    apply = AsyncMock(side_effect=ValueError("rejected result") if failure_at == "apply" else None)

    async def handle(body):
        await consume_result(session, body, apply)

    response = await consume_batch(
        {"Records": [{"messageId": "receipt-failed", "body": json.dumps(event)}]},
        "media-results",
        handle,
    )
    assert response == {"batchItemFailures": [{"itemIdentifier": "receipt-failed"}]}


async def test_inbox_duplicate_and_conflicting_message_id(session, event):
    # INSERT ... ON CONFLICT found the durable inbox record.
    session.scalar.return_value = None
    session.get.return_value = SimpleNamespace(body_hash=fingerprint(event))
    apply = AsyncMock()
    assert not await consume_result(session, event, apply)
    session.get.assert_awaited_once_with(MediaInbox, UUID(event["message_id"]))
    apply.assert_not_awaited()
    changed = deepcopy(event)
    changed["payload"]["error"] = "different immutable message"
    with pytest.raises(MessageConflict, match="different content"):
        await consume_result(session, changed, apply)
    apply.assert_not_awaited()
