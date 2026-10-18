"""Media's result consumer and bounded command outbox repair Lambdas."""

import asyncio
import os
import time

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from delivery.runtime import deadline_for, queue_urls
from delivery.sqs import SQS, consume_batch
from media.config import get_settings
from media.messaging import consume_result, publish_commands
from runtime_support import lambda_db
from runtime_support.activity import Activity
from runtime_support.errors import sanitized_entrypoint
from runtime_support.settings import heal_on_rejection


async def consume_results(event, factory, apply=None):
    if apply is None:
        from media.projections import apply_result

        apply = apply_result

    async def handle(body):
        # consume_batch turns every error into a batch failure, so a rejected login
        # must be noticed here or the warm container keeps replaying the old DSN.
        with heal_on_rejection(get_settings):
            async with factory() as session:
                await consume_result(session, body, apply)

    return await consume_batch(event, "media-results", handle)


async def invoke(event, context, mode):
    from media.database import engine_options

    # Always on (AD-27): a scheduled repair with nothing due opens no connection, so Aurora can
    # pause; a result is about to write, so it is recorded first. Absent markers: V1 as before.
    activity = Activity.from_environ("MEDIA")
    if activity and mode == "repair" and await asyncio.to_thread(activity.quiet):
        return {"skipped": "idle"}
    if activity and mode == "result":
        await asyncio.to_thread(activity.touch)
    settings = get_settings()
    engine = await lambda_db.shared_engine(
        "media",
        settings.postgres_dsn,
        lambda: create_async_engine(
            settings.postgres_dsn, **engine_options(settings, invocation=True)
        ),
    )
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
        from media.recovery_v1 import next_due, run_once
        from media.services.storage import Storage

        # The repair pass raises on a refused login, so one guard covers the outbox
        # publish and the cleanup that follows it.
        with heal_on_rejection(get_settings):
            published = await publish_commands(
                factory, transport, limit=25, deadline=min(deadline, time.monotonic() + 5)
            )
            cleanup = await run_once(factory, settings, Storage(settings), deadline=deadline)
            if activity:
                checked = time.time()  # before the snapshot next_due reads
                due = await next_due(factory, settings)
                await asyncio.to_thread(activity.record, checked, due)
        return {"published": published, **cleanup}
    except Exception as error:
        await lambda_db.release_after("media", error)
        raise


@sanitized_entrypoint("media.result")
def result_handler(event, context):
    return lambda_db.run(invoke(event, context, "result"))


@sanitized_entrypoint("media.repair")
def repair_handler(event, context):
    return lambda_db.run(invoke(event, context, "repair"))
