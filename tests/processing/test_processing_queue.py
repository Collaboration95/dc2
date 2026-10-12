from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import fakeredis
from rq import Queue
from rq.registry import StartedJobRegistry

from processing import queue
from processing.config import Settings


def cfg(redis="redis://unused"):
    return Settings(postgres_dsn="postgresql://unused@unused/processing_db", redis_url=redis)


def test_reserved_queue_delivery_and_runnable_membership_offline(monkeypatch):
    redis = fakeredis.FakeRedis()
    # fakeredis without Lua cannot release a Redis distributed lock. Real lock
    # semantics are covered by the gated real Redis suite.
    monkeypatch.setattr(redis, "lock", Mock(return_value=Mock(__enter__=Mock(), __exit__=Mock())))
    target = Queue("unit-processing-" + uuid4().hex, connection=redis)
    job, attempt = uuid4(), uuid4()
    assert queue.enqueue_attempt(job, attempt, queue=target)
    assert not queue.enqueue_attempt(job, attempt, queue=target)
    redis.lrem(target.key, 0, str(attempt))
    assert redis.exists("rq:job:" + str(attempt))
    assert queue.enqueue_attempt(job, attempt, queue=target)
    assert target.get_job_ids() == [str(attempt)]
    task = target.fetch_job(str(attempt))
    assert task.args == (str(job), str(attempt))
    redis.lrem(target.key, 0, str(attempt))
    registry = StartedJobRegistry(target.name, connection=redis)
    redis.zadd(registry.key, {str(attempt) + ":execution": 9999999999})
    assert not queue.enqueue_attempt(job, attempt, queue=target)
    redis.zadd(registry.key, {str(attempt) + ":execution": 1})
    assert queue.enqueue_attempt(job, attempt, queue=target)


def test_queue_explicit_bounded_connection(monkeypatch):
    redis = Mock()
    monkeypatch.setattr("redis.Redis.from_url", Mock(return_value=redis))
    target = queue.get_queue(cfg())
    assert target.connection is redis and target.name == "processing"


async def test_publish_missing_redis_outage_and_nonqueued(monkeypatch):
    job = SimpleNamespace(
        job_id=uuid4(), current_attempt=SimpleNamespace(attempt_id=uuid4()), status="done"
    )
    await queue.publish(job)
    job.status = "queued"
    monkeypatch.setattr(queue, "get_settings", lambda: cfg(""))
    await queue.publish(job)
    monkeypatch.setattr(queue, "get_settings", cfg)
    callback = Mock(side_effect=OSError("secret"))
    monkeypatch.setattr(queue, "enqueue_attempt", callback)
    await queue.publish(job)
    callback.assert_called_once_with(job.job_id, job.current_attempt.attempt_id)
