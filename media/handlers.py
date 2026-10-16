"""Media's result consumer and bounded command outbox repair Lambdas."""

import asyncio
import os
import time

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from delivery.runtime import deadline_for, queue_urls
from delivery.sqs import SQS, consume_batch
from media.config import get_settings
from media.messaging import consume_result, publish_commands


async def consume_results(event, factory, apply=None):
    if apply is None:
        from media.projections import apply_result

        apply = apply_result

    async def handle(body):
        async with factory() as session:
            await consume_result(session, body, apply)

    return await consume_batch(event, "media-results", handle)


async def invoke(event, context, mode):
    from media.database import engine_options

    settings = get_settings()
    engine = create_async_engine(settings.postgres_dsn, **engine_options(settings, invocation=True))
    factory = async_sessionmaker(engine, expire_on_commit=False)
    deadline = deadline_for(context)
    try:
        if mode == "result":
            return await consume_results(event, factory)
        transport = SQS(
            queue_urls(),
            producer="media",
            region=os.environ.get("AWS_REGION"),
            endpoint_url=os.environ.get("SQS_ENDPOINT_URL"),
        )
        published = await publish_commands(
            factory, transport, limit=25, deadline=min(deadline, time.monotonic() + 5)
        )
        from media.recovery_v1 import run_once
        from media.services.storage import Storage

        cleanup = await run_once(factory, settings, Storage(settings), deadline=deadline)
        return {"published": published, **cleanup}
    finally:
        await engine.dispose()


def result_handler(event, context):
    return asyncio.run(invoke(event, context, "result"))


def repair_handler(event, context):
    return asyncio.run(invoke(event, context, "repair"))
