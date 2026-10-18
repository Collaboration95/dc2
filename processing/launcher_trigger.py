"""Wake the encoder launcher the moment Processing puts work on its queue (V2-live, #237).

The launcher's one-minute schedule alone made a single job wait 110 s in the median (r1018b).
A work publisher therefore also invokes the launcher asynchronously after its send. That wake
is only a hint: the launcher still decides from SQL and the queue depth, its reservations hold
the cap under any number of concurrent wakes, and the schedule picks up a wake that was lost.
"""

import asyncio
import json
import logging
import os

WORK_QUEUE = "processing-work"
WAKE = {"dc2_operation": "launcher", "action": "wake"}
logger = logging.getLogger(__name__)


def invoke_async(function):
    import boto3
    from botocore.config import Config

    # One short attempt: a slow or failed wake must not hold up the publisher's own work.
    client = boto3.client(
        "lambda",
        region_name=os.environ.get("AWS_REGION"),
        config=Config(connect_timeout=2, read_timeout=5, retries={"total_max_attempts": 1}),
    )
    client.invoke(
        FunctionName=function, InvocationType="Event", Payload=json.dumps(WAKE).encode()
    )


class WakeOnWork:
    """The publisher's transport, plus one launcher wake per invocation after a work send."""

    def __init__(self, transport, function, *, invoke=invoke_async):
        self.transport, self.function, self.invoke = transport, function, invoke
        self.woken = False

    async def send(self, queue, envelope):
        result = await self.transport.send(queue, envelope)
        if queue == WORK_QUEUE and not self.woken:
            # Once is enough: one tick reserves for the whole backlog it can see.
            self.woken = True
            try:
                await asyncio.to_thread(self.invoke, self.function)
            except Exception as error:
                # Only the type: the schedule recovers the wake, and the text could carry
                # request details.
                logger.warning("launcher wake failed: %s", type(error).__name__)
        return result

    def __getattr__(self, name):
        return getattr(self.transport, name)


def wrap(transport, environ=None):
    """Wrap only where the stack deployed the launcher; elsewhere the transport is unchanged."""
    environ = os.environ if environ is None else environ
    function = environ.get("PROCESSING_LAUNCHER_FUNCTION", "")
    return WakeOnWork(transport, function) if function else transport
