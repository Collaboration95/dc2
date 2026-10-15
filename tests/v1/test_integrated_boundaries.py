"""Cross-lane seams using real implementations, without external services."""

import time
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory

from media.api import v1_hls, v1_jobs
from media.lambda_handler import handler
from processing import lifecycle
from processing.worker.sqs import execute_message


@pytest.mark.parametrize(
    "path,method,endpoint",
    [
        ("/jobs", "GET", v1_jobs.listing),
        ("/jobs/{job_id}", "GET", v1_jobs.read),
        ("/jobs/{job_id}/retry", "POST", v1_jobs.retry),
        ("/jobs/{job_id}/hls/{path:path}", "GET", v1_hls.part),
    ],
)
def test_deployed_media_app_uses_projection_routes(path, method, endpoint):
    def routes(router):
        for route in router.routes:
            included = getattr(route, "original_router", None)
            if included is not None:
                yield from routes(included)
            else:
                yield route

    matches = [
        route
        for route in routes(handler.app)
        if getattr(route, "path", None) == path and method in getattr(route, "methods", ())
    ]
    assert len(matches) == 1
    assert matches[0].endpoint is endpoint


async def test_worker_passes_task_binding_through_real_durable_claim(monkeypatch):
    # Keep the actual worker -> messaging call; intercept only SQL lifecycle work.
    # AsyncMock at the messaging boundary would hide signature incompatibilities.
    sql_claim = AsyncMock(return_value=None)
    monkeypatch.setattr(lifecycle, "claim", sql_claim)
    from tests.v1.test_delivery import message

    body = message("work")
    body.update(job_id=str(uuid4()), attempt_id=str(uuid4()))
    assert not await execute_message(
        None,
        body,
        SimpleNamespace(),
        renew=AsyncMock(),
        deadline=time.monotonic() + 60,
        task_name="integration-task",
    )
    assert sql_claim.call_args.kwargs["task_name"] == "integration-task"


@pytest.mark.parametrize("owner", ["media", "processing"])
def test_owner_migrations_have_one_resolvable_head(owner):
    config = Config()
    config.set_main_option("script_location", f"{owner}/migrations")
    scripts = ScriptDirectory.from_config(config)
    heads = scripts.get_heads()
    assert len(heads) == 1
    assert list(scripts.walk_revisions())[-1].down_revision is None
