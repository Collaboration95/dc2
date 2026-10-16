"""V1 Lambda control entrypoints. No public raw-source job creation endpoint."""

import asyncio
import os

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from delivery.runtime import deadline_for, queue_urls
from delivery.sqs import SQS
from processing.config import get_settings
from processing.messaging import consume_commands, publish_outbox
from processing.recovery_v1 import run_once, terminal_event
from runtime_support.settings import credentials_rejected, heal_on_rejection


def _heal():
    return heal_on_rejection(get_settings)


async def invoke(event, context, mode):
    from processing.database import v1_connect_args

    settings = get_settings()
    engine = create_async_engine(
        settings.postgres_dsn, poolclass=NullPool, connect_args=v1_connect_args(settings)
    )
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
            # consume_batch reports errors as batch failures instead of raising, so
            # the self-heal guard has to wrap each message, not just this call.
            result = await consume_commands(event, factory, guard=_heal)
            # ACK follows committed domain/inbox/outbox, not network availability.
            try:
                await publish_outbox(factory, transport, deadline=deadline, limit=25)
            except Exception as error:
                # Durable outbox is repaired by the session-scoped tick.
                if credentials_rejected(error):
                    get_settings.cache_clear()
            return result
        with _heal():
            stopped = await terminal_event(factory, event) if mode == "ecs" else None
            # S3 notifications are also hints. Repeated retained cleanup intents, not
            # a supplied bucket/key, determine what can safely be deleted.
            result = await run_once(factory, settings, transport, deadline=deadline)
        return result if stopped is None else {**result, "stopped": stopped}
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
