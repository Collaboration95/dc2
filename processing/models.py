from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from processing.database import Base


def utcnow() -> datetime:
    return datetime.now(UTC)


class Job(Base):
    __tablename__ = "jobs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('queued', 'processing', 'done', 'failed')", name="ck_jobs_status"
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    asset_id: Mapped[UUID] = mapped_column(unique=True)
    owner_id: Mapped[UUID] = mapped_column(index=True)
    source: Mapped[dict] = mapped_column(JSONB)
    operations: Mapped[list] = mapped_column(JSONB, default=list)
    request_hash: Mapped[str] = mapped_column(String(64))
    source_url: Mapped[str]
    source_url_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(16), default="queued")
    current_attempt_id: Mapped[UUID] = mapped_column(
        ForeignKey(
            "attempts.id",
            name="fk_jobs_current_attempt",
            use_alter=True,
            deferrable=True,
            initially="DEFERRED",
        )
    )
    outputs: Mapped[list] = mapped_column(JSONB, default=list, server_default=text("'[]'::jsonb"))
    error: Mapped[str | None]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Attempt(Base):
    __tablename__ = "attempts"
    __table_args__ = (
        UniqueConstraint("job_id", "attempt_number", name="uq_attempts_job_number"),
        CheckConstraint("attempt_number >= 1", name="ck_attempts_number"),
        CheckConstraint(
            "state IN ('queued', 'processing', 'succeeded', 'failed', 'abandoned', 'cancelled')",
            name="ck_attempts_state",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    job_id: Mapped[UUID] = mapped_column(ForeignKey("jobs.id"))
    attempt_number: Mapped[int]
    state: Mapped[str] = mapped_column(String(16), default="queued")
    queued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error: Mapped[str | None]

    lease_token: Mapped[UUID | None]
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deadline_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    dispatch_count: Mapped[int] = mapped_column(default=0, server_default="0")
    next_dispatch_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    dispatch_error: Mapped[str | None]


class RetryRequest(Base):
    __tablename__ = "retry_requests"
    __table_args__ = (UniqueConstraint("job_id", "request_id"),)
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    job_id: Mapped[UUID] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"))
    request_id: Mapped[UUID]
    attempt_id: Mapped[UUID] = mapped_column(ForeignKey("attempts.id", ondelete="CASCADE"))


class CleanupIntent(Base):
    __tablename__ = "cleanup_intents"
    attempt_id: Mapped[UUID] = mapped_column(
        ForeignKey("attempts.id", ondelete="CASCADE"), primary_key=True
    )
    job_id: Mapped[UUID] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"))
    next_try_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    tries: Mapped[int] = mapped_column(default=0, server_default="0")
    last_error: Mapped[str | None]
    # Retirement horizon: a late write cannot outlive the attempt deadline by days,
    # so a successful scan past this age ends the rescans (the row is kept as audit).
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    retired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SubmissionGuard(Base):
    __tablename__ = "submission_guards"

    asset_id: Mapped[UUID] = mapped_column(primary_key=True)
    owner_id: Mapped[UUID]
    job_id: Mapped[UUID | None] = mapped_column(ForeignKey("jobs.id"))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
