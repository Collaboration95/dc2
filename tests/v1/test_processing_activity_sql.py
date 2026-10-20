"""#244 against real PostgreSQL: a direct retry from a quiet gate leaves pending outbox work
that the next repair pass can see. Needs V1_TEST_PROCESSING_DSN (skipped otherwise)."""

import json
import time
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from contracts.gateway import GatewayAdapter
from processing import v1_api
from processing.database import get_v1_session
from processing.messaging import claim, finish, handle_command
from processing.messaging_models import ProcessingOutbox
from runtime_support import activity
from tests.v1.test_activity_gate import QUIET, TOUCHED, Ssm, processing_event
from tests.v1.test_messaging_sql import SETTINGS, factory, state  # noqa: F401

pytestmark = pytest.mark.integration


async def test_a_direct_retry_from_a_quiet_gate_records_activity_and_commits_pending_work(
    monkeypatch,
    factory,  # noqa: F811
):
    from tests.v1.test_delivery import message

    monkeypatch.setattr(activity, "_last_touch", {})
    await handle_command(factory, message())
    job, first = await state(factory)
    work = await claim(factory, job.id, first.id, SETTINGS, task_name="local-" + uuid4().hex)
    await finish(factory, work, error="Processing interrupted")
    async with factory() as session:
        before = await session.scalar(select(func.count()).select_from(ProcessingOutbox))

    ssm = Ssm("0", f"{int(time.time())} 99999999999")  # quiet start
    monkeypatch.setattr(activity, "_ssm_client", lambda: ssm)
    monkeypatch.setenv("PROCESSING_ACTIVITY_TOUCHED_PARAMETER", TOUCHED)
    monkeypatch.setenv("PROCESSING_ACTIVITY_QUIET_PARAMETER", QUIET)

    async def session():
        async with factory() as live:
            yield live

    app = v1_api.create_app()
    app.dependency_overrides[get_v1_session] = session
    response = await GatewayAdapter(app, service="processing").invoke(
        processing_event(
            "POST",
            f"/jobs/{job.id}/retry",
            json.dumps({"retry_request_id": str(uuid4())}),
            owner=job.owner_id,
        )
    )
    assert response["statusCode"] == 202
    assert [name for name, _ in ssm.puts] == [TOUCHED]
    assert not activity.Activity(TOUCHED, QUIET, client=ssm).quiet()  # repair now runs SQL
    async with factory() as live:
        after = await live.scalar(select(func.count()).select_from(ProcessingOutbox))
    assert after > before  # the retry's outbox work is committed and visible to the next pass
