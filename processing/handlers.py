"""V1 Lambda control entrypoints. No public raw-source job creation endpoint."""

import asyncio
import os

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from delivery.runtime import deadline_for, queue_urls
from delivery.sqs import SQS
from processing.config import get_settings
from processing.messaging import consume_commands, publish_outbox
from processing.recovery_v1 import run_once, terminal_event


async def invoke(event, context, mode):
    settings = get_settings()
    engine = create_async_engine(settings.postgres_dsn, pool_pre_ping=True)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    transport = SQS(
        queue_urls(),
        producer="processing",
        region=os.environ.get("AWS_REGION"),
        endpoint_url=os.environ.get("SQS_ENDPOINT_URL"),
    )
    deadline = deadline_for(context)
    try:
        if mode == "command":
            result = await consume_commands(event, factory)
            # ACK follows committed domain/inbox/outbox, not network availability.
            try:
                await publish_outbox(factory, transport, deadline=deadline, limit=25)
            except Exception:
                pass  # Durable outbox is repaired by the session-scoped tick.
            return result
        if mode == "ecs":
            await terminal_event(factory, event)
        # S3 notifications are also hints. Repeated retained cleanup intents, not
        # a supplied bucket/key, determine what can safely be deleted.
        return await run_once(factory, settings, transport, deadline=deadline)
    finally:
        await engine.dispose()


def command_handler(event, context):
    return asyncio.run(invoke(event, context, "command"))


def repair_handler(event, context):
    return asyncio.run(invoke(event, context, "repair"))


def ecs_handler(event, context):
    return asyncio.run(invoke(event, context, "ecs"))


def s3_handler(event, context):
    return asyncio.run(invoke(event, context, "s3"))
