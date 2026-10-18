from dataclasses import replace
from datetime import timedelta
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from _processing_doubles import NOW, Rows, Session, pair

from legacy.processing_rq import service
from legacy.processing_rq.schemas import SubmitJob
from processing import lifecycle
from processing.config import Settings
from processing.errors import ProcessingError
from processing.models import Attempt, Job, RetryRequest, SubmissionGuard, utcnow


def cfg():
    return Settings(postgres_dsn="postgresql://unused@unused/processing_db")


async def test_claim_heartbeat_finish_decisions_offline(monkeypatch):
    job, attempt, _, _ = pair("queued")
    session = Session()
    monkeypatch.setattr(lifecycle, "lock_pair", AsyncMock(return_value=(job, attempt)))
    monkeypatch.setattr(lifecycle, "db_now", AsyncMock(return_value=NOW))
    work = await lifecycle.claim(lambda: session, job.id, attempt.id, cfg())
    assert work.job_id == job.id and work.attempt_id == attempt.id
    assert attempt.state == "processing" and job.status == "processing"
    assert await lifecycle.heartbeat(lambda: session, work, cfg())
    assert not await lifecycle.finish(
        lambda: session, replace(work, lease_token=uuid4()), error="stale writer"
    )
    outputs = [
        {
            "kind": "primary",
            "object_key": lifecycle.output_prefix(job.id, attempt.id) + "out",
            "media_type": "video/mp4",
            "size_bytes": 10,
            "sha256": "b" * 64,
        }
    ]
    assert await lifecycle.finish(lambda: session, work, outputs=outputs)
    assert job.status == "done" and attempt.state == "succeeded" and job.outputs == outputs
    assert not await lifecycle.heartbeat(lambda: session, work, cfg())
    assert not await lifecycle.claim(lambda: session, job.id, attempt.id, cfg())


async def test_claim_unknown_and_failure_intent(monkeypatch):
    session = Session()
    monkeypatch.setattr(lifecycle, "db_now", AsyncMock(return_value=NOW))
    monkeypatch.setattr(lifecycle, "lock_pair", AsyncMock(return_value=None))
    assert await lifecycle.claim(lambda: session, uuid4(), uuid4(), cfg()) is None
    job, attempt, _, work = pair()
    monkeypatch.setattr(lifecycle, "lock_pair", AsyncMock(return_value=(job, attempt)))
    assert await lifecycle.finish(lambda: session, work, error="Curated failure")
    assert job.status == "failed" and attempt.error == "Curated failure"
    session.execute.assert_awaited_once()


@pytest.mark.parametrize("condition", ["missing", "deleted", "stale", "missing-attempt", "foreign"])
async def test_lock_pair_rejects_unowned_transition(condition):
    job, attempt, _, _ = pair()
    session = Session()
    if condition == "deleted":
        job.deleted_at = NOW
    elif condition == "stale":
        job.current_attempt_id = uuid4()
    elif condition == "foreign":
        attempt.job_id = uuid4()
    session.scalar.return_value = None if condition == "missing" else job
    session.get.return_value = None if condition == "missing-attempt" else attempt
    assert await lifecycle.lock_pair(session, job.id, attempt.id) is None


async def test_live_requires_unexpired_deadline_and_lease():
    job, attempt, _, work = pair()
    assert lifecycle.live((job, attempt), work.lease_token, NOW)
    attempt.deadline_at = NOW - timedelta(seconds=1)
    assert not lifecycle.live((job, attempt), work.lease_token, NOW)
    assert not lifecycle.live(None, work.lease_token, NOW)


async def test_retry_creation_and_replay_offline(monkeypatch):
    job, attempt, _, _ = pair("failed")
    session = Session()
    monkeypatch.setattr(lifecycle, "db_now", AsyncMock(return_value=NOW))
    session.scalar.side_effect = [job, None]
    session.get.return_value = attempt
    response = await lifecycle.retry_job(session, job.owner_id, job.id, uuid4())
    assert response.status == "queued" and response.current_attempt.number == 2
    assert sum(isinstance(call.args[0], RetryRequest) for call in session.add.call_args_list) == 1
    new = next(
        call.args[0] for call in session.add.call_args_list if isinstance(call.args[0], Attempt)
    )
    job.status = "done"
    new.state = "succeeded"
    session.scalar.side_effect = [job, object()]
    session.get.return_value = new
    replay = await lifecycle.retry_job(session, job.owner_id, job.id, uuid4())
    assert replay.status == "done" and replay.current_attempt.attempt_id == new.id


@pytest.mark.parametrize(
    "condition,code", [("absent", 404), ("owner", 404), ("deleted", 410), ("live", 409)]
)
async def test_retry_owner_deleted_state_errors(condition, code):
    job, attempt, _, _ = pair()
    session = Session()
    if condition == "deleted":
        job.deleted_at = NOW
    session.scalar.side_effect = [None if condition == "absent" else job, None]
    session.get.return_value = attempt
    with pytest.raises(ProcessingError) as exc:
        await lifecycle.retry_job(
            session, uuid4() if condition == "owner" else job.owner_id, job.id, uuid4()
        )
    assert exc.value.status_code == code


async def test_cancel_before_submit_and_existing_job_offline(monkeypatch):
    job, attempt, guard, _ = pair()
    session = Session()
    monkeypatch.setattr(lifecycle, "db_now", AsyncMock(return_value=NOW))
    guard.job_id = None
    session.scalar.return_value = guard
    await lifecycle.cancel_asset(session, guard.owner_id, guard.asset_id)
    assert guard.deleted_at == NOW
    guard.job_id = job.id
    session.scalar.side_effect = [guard, job]
    session.scalars = AsyncMock(return_value=Rows([attempt]))
    await lifecycle.cancel_asset(session, guard.owner_id, guard.asset_id)
    assert attempt.state == "cancelled" and job.deleted_at == NOW
    assert job.outputs == []
    session.scalar.side_effect = None
    session.scalar.return_value = guard
    with pytest.raises(ProcessingError) as exc:
        await lifecycle.cancel_asset(session, uuid4(), guard.asset_id)
    assert exc.value.status_code == 404


async def test_submit_fingerprint_and_durable_response_offline(submission):
    request = SubmitJob.model_validate(submission)
    guard = SubmissionGuard(asset_id=request.asset_id, owner_id=request.owner_id)
    session = Session()
    session.execute.side_effect = [Rows(), Rows([guard])]
    result, created = await service.submit_job(session, request.owner_id, request)
    assert created and result.current_attempt.number == 1 and result.outputs == []
    assert result.created_at == NOW and guard.job_id == result.job_id
    job = next(call.args[0] for call in session.add.call_args_list if isinstance(call.args[0], Job))
    attempt = next(
        call.args[0] for call in session.add.call_args_list if isinstance(call.args[0], Attempt)
    )
    session.execute.side_effect = [Rows(), Rows([guard])]
    session.scalar.return_value = job
    session.get.return_value = attempt
    replay, created = await service.submit_job(session, request.owner_id, request)
    assert not created and replay == result
    session.execute.side_effect = None
    session.execute.return_value = Rows([(job, attempt)])
    session.get.side_effect = None
    assert await service.get_job(session, request.owner_id, job.id) == result
    assert await service.list_jobs(session, request.owner_id, [request.asset_id]) == [result]
    assert utcnow().tzinfo is not None


@pytest.mark.parametrize(
    "condition,code",
    [
        ("header", 404),
        ("guard-owner", 404),
        ("guard-deleted", 410),
        ("job-missing", 503),
        ("job-owner", 503),
        ("job-deleted", 410),
        ("hash", 409),
        ("attempt", 503),
    ],
)
async def test_submit_replay_errors_do_not_mutate(submission, condition, code):
    request = SubmitJob.model_validate(submission)
    job, attempt, guard, _ = pair("queued")
    job.owner_id = guard.owner_id = request.owner_id
    job.request_hash = service.request_fingerprint(request)
    if condition == "guard-owner":
        guard.owner_id = uuid4()
    if condition == "guard-deleted":
        guard.deleted_at = NOW
    if condition == "job-owner":
        job.owner_id = uuid4()
    if condition == "job-deleted":
        job.deleted_at = NOW
    if condition == "hash":
        job.request_hash = "different"
    if condition == "attempt":
        attempt.job_id = uuid4()
    session = Session()
    session.execute.side_effect = [Rows(), Rows([guard])]
    session.scalar.return_value = None if condition == "job-missing" else job
    session.get.return_value = attempt
    with pytest.raises(ProcessingError) as exc:
        await service.submit_job(
            session, uuid4() if condition == "header" else request.owner_id, request
        )
    assert exc.value.status_code == code
    session.add.assert_not_called()


async def test_get_missing_owner_filtered():
    session = Session()
    session.execute.return_value = Rows()
    with pytest.raises(ProcessingError) as exc:
        await service.get_job(session, uuid4(), uuid4())
    assert exc.value.status_code == 404
    assert await service.list_jobs(session, uuid4(), [UUID(int=1)]) == []
