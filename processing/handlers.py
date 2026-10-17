"""V1 Lambda control entrypoints. No public raw-source job creation endpoint."""

import os

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from delivery.runtime import deadline_for, queue_urls
from delivery.sqs import SQS
from processing.config import get_settings
from processing.messaging import consume_commands, publish_outbox
from processing.recovery_v1 import run_once, terminal_event
from runtime_support import lambda_db
from runtime_support.errors import sanitized_entrypoint
from runtime_support.settings import credentials_rejected, heal_on_rejection


def _heal():
    return heal_on_rejection(get_settings)


async def invoke(event, context, mode):
    from processing.database import v1_engine_options

    settings = get_settings()
    engine = await lambda_db.shared_engine(
        "processing",
        settings.postgres_dsn,
        lambda: create_async_engine(settings.postgres_dsn, **v1_engine_options(settings)),
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
    except Exception as error:
        await lambda_db.release_after("processing", error)
        raise


@sanitized_entrypoint("processing.command")
def command_handler(event, context):
    return lambda_db.run(invoke(event, context, "command"))


@sanitized_entrypoint("processing.repair")
def repair_handler(event, context):
    return lambda_db.run(invoke(event, context, "repair"))


@sanitized_entrypoint("processing.ecs")
def ecs_handler(event, context):
    return lambda_db.run(invoke(event, context, "ecs"))


@sanitized_entrypoint("processing.s3")
def s3_handler(event, context):
    return lambda_db.run(invoke(event, context, "s3"))


@sanitized_entrypoint("processing.launcher")
def launcher_handler(event, context):
    # Opt-in V2 experiment (#68): the function exists only when the stack sets
    # UnattendedLaunch=true, and the import keeps V1 cold starts free of boto3 ECS clients.
    from processing.launcher_aws import run

    return lambda_db.run(run(event, context))


@sanitized_entrypoint("processing.short_encoder")
def short_encoder_handler(event, context):
    # Opt-in V2 experiment (#93): the function exists only when the stack sets
    # LambdaShortEncodes=true. The import keeps every other Processing cold start free of it.
    from processing.short_encoder import invoke

    return lambda_db.run(invoke(event, context))
