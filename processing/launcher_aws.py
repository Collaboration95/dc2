"""Thin boto3 ports and the Lambda entrypoint body for the opt-in launcher.

The decision logic lives in ``processing.launcher`` and sees only these ports, so tests
substitute fakes and never reach a network. Nothing here runs at import time.
"""

import asyncio
import os
import time

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from delivery.runtime import deadline_for
from processing import launcher
from processing.config import get_settings
from processing.launcher import LauncherConfig, RunTaskRefused
from runtime_support.activity import Activity
from runtime_support.settings import heal_on_rejection

SERVICE = "processing-launcher"
OPERATION = "launcher"
LIST_PAGE_SIZE = 100


def _client(name):
    import boto3
    from botocore.config import Config

    # One attempt and short timeouts: a retry would hide an ambiguous RunTask, and the
    # reconcile pass resolves ambiguity by token anyway. Bounded well below the 30 s timeout.
    return boto3.client(
        name,
        region_name=os.environ.get("AWS_REGION"),
        config=Config(connect_timeout=2, read_timeout=5, retries={"total_max_attempts": 1}),
    )


class _Lazy:
    """Build the boto3 client on first use: an idle tick reads only SQL and needs none."""

    service = ""

    def __init__(self, client=None):
        self._client_instance = client

    @property
    def client(self):
        if self._client_instance is None:
            self._client_instance = _client(self.service)
        return self._client_instance


class EcsPort(_Lazy):
    service = "ecs"

    def __init__(self, cluster, client=None):
        super().__init__(client)
        self.cluster = cluster

    async def list_tasks(self, desired_status):
        arns, token = [], None
        for _ in range(launcher.LIST_PAGES):
            request = {
                "cluster": self.cluster,
                "desiredStatus": desired_status,
                "maxResults": LIST_PAGE_SIZE,
            }
            if token:
                request["nextToken"] = token
            reply = await asyncio.to_thread(self.client.list_tasks, **request)
            arns += reply.get("taskArns", [])
            token = reply.get("nextToken")
            if not token:
                return arns
        raise RuntimeError("Task listing did not terminate")

    async def describe_tasks(self, arns):
        return await asyncio.to_thread(self.client.describe_tasks, cluster=self.cluster, tasks=arns)

    async def run_task(self, payload):
        try:
            return await asyncio.to_thread(self.client.run_task, **payload)
        except Exception as error:
            response = getattr(error, "response", None)
            if isinstance(response, dict):
                status = response.get("ResponseMetadata", {}).get("HTTPStatusCode", 500)
                code = response.get("Error", {}).get("Code", "")
                # A 4xx is ECS rejecting the request, so nothing started. A conflict means
                # a request with this token is still in progress, which is the opposite.
                if 400 <= status < 500 and code != "ConflictException":
                    raise RunTaskRefused(code[:80] or "ClientError") from None
            raise


class QueueDepth(_Lazy):
    service = "sqs"

    def __init__(self, url, client=None):
        super().__init__(client)
        self.url = url

    async def visible(self):
        reply = await asyncio.to_thread(
            self.client.get_queue_attributes,
            QueueUrl=self.url,
            AttributeNames=["ApproximateNumberOfMessages"],
        )
        return int(reply["Attributes"]["ApproximateNumberOfMessages"])


class SettledDepth:
    """SQS's visible count trails a send by a moment, and a wake arrives right after one.

    Asked again a few times, briefly, before an empty answer is believed; a scheduled tick
    keeps the plain single read.
    """

    def __init__(self, queue, *, attempts=5, interval=1.0):
        self.queue, self.attempts, self.interval = queue, attempts, interval

    async def visible(self):
        for attempt in range(self.attempts):
            count = await self.queue.visible()
            if count or attempt == self.attempts - 1:
                return count
            await asyncio.sleep(self.interval)


def config_from_environ(environ=None):
    environ = os.environ if environ is None else environ
    prefix = "PROCESSING_LAUNCHER_"
    return LauncherConfig(
        cluster=environ[prefix + "CLUSTER"],
        task_definition=environ[prefix + "TASK_DEFINITION"],
        subnets=tuple(environ[prefix + "SUBNETS"].split(",")),
        security_groups=tuple(environ[prefix + "SECURITY_GROUPS"].split(",")),
        lifetime_seconds=int(environ[prefix + "LIFETIME_SECONDS"]),
        cap=int(environ.get(prefix + "CAP", launcher.HARD_CAP)),
        always_on=environ.get(prefix + "ALWAYS_ON") == "true",
    )


async def run(event, context, *, ecs=None, queue=None, config=None, factory=None, activity=None):
    """Dispatch a scheduled tick or an operator control event; returns counts only."""
    scheduled = not (isinstance(event, dict) and event.get("dc2_operation") == OPERATION)
    activity = activity or Activity.from_environ("PROCESSING")
    if scheduled and activity and await asyncio.to_thread(activity.quiet):
        # Nothing queued, running or reserved (AD-27): no connection, so Aurora can pause. A
        # wake after a work send and every control event still reach SQL.
        return {"service": SERVICE, "action": "tick", "outcome": "idle", "skipped": "quiet"}
    config = config or config_from_environ()
    engine = None
    if factory is None:
        from processing.database import v1_connect_args

        settings = get_settings()
        engine = create_async_engine(
            settings.postgres_dsn, poolclass=NullPool, connect_args=v1_connect_args(settings)
        )
        factory = async_sessionmaker(engine, expire_on_commit=False)
    ecs = ecs or EcsPort(config.cluster)
    deadline = deadline_for(context, maximum=25)
    try:
        with heal_on_rejection(get_settings):
            async with asyncio.timeout(max(0.5, deadline - time.monotonic())):
                return await _dispatch(event, factory, ecs, queue, config)
    finally:
        if engine is not None:
            await engine.dispose()


async def _dispatch(event, factory, ecs, queue, config):
    if isinstance(event, dict) and event.get("dc2_operation") == OPERATION:
        action = event.get("action")
        if action == "enable":
            result = await launcher.set_enabled(
                factory, True, session_end_epoch=event.get("session_end_epoch")
            )
        elif action == "disable":
            result = await launcher.set_enabled(factory, False)
        elif action == "settle":
            result = await launcher.settle(factory, ecs, config)
        elif action == "status":
            result = await launcher.status(factory)
        elif action == "wake":
            # Sent by a work publisher the moment it enqueued (#237): a tick, without waiting
            # for the minute schedule.
            depth = SettledDepth(queue or QueueDepth(os.environ["PROCESSING_WORK_QUEUE_URL"]))
            result = await launcher.tick(factory, ecs, depth, config)
        else:
            raise ValueError("Unknown launcher action")
        return {"service": SERVICE, "action": action, **result}
    queue = queue or QueueDepth(os.environ["PROCESSING_WORK_QUEUE_URL"])
    result = await launcher.tick(factory, ecs, queue, config)
    return {"service": SERVICE, "action": "tick", **result}
