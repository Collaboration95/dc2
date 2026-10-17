"""Processing-owned state for the opt-in unattended launcher (V2 experiment, #68)."""

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Index, String, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from processing.database import Base

# reserved: the slot is taken and RunTask may or may not have landed (the ambiguous state).
# launched: ECS acknowledged or a startedBy lookup found the task.
# stopped:  the task was observed STOPPED. released: it was proven never to have started.
OPEN_STATES = ("reserved", "launched")
STATES = (*OPEN_STATES, "stopped", "released")


class LauncherControl(Base):
    """One row. Taking it FOR UPDATE serializes reservations; FOR SHARE gates every send."""

    __tablename__ = "launcher_control"
    __table_args__ = (CheckConstraint("id = 1", name="ck_launcher_control_singleton"),)
    id: Mapped[int] = mapped_column(primary_key=True, default=1)
    enabled: Mapped[bool] = mapped_column(default=False, server_default=text("false"))
    enabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # A launch without a session end would be unbounded, so enabling always sets one.
    session_end_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class LaunchReservation(Base):
    __tablename__ = "launch_reservations"
    __table_args__ = (
        CheckConstraint(
            "status IN ('reserved', 'launched', 'stopped', 'released')",
            name="ck_launch_reservations_status",
        ),
        Index(
            "ix_launch_reservations_open",
            "reserved_at",
            postgresql_where=text("status IN ('reserved', 'launched')"),
        ),
    )
    # The ECS clientToken. Persisted before RunTask so a replay is byte-identical.
    token: Mapped[str] = mapped_column(String(64), primary_key=True)
    # ECS startedBy (36 characters at most), also the worker's attempt-binding name.
    started_by: Mapped[str] = mapped_column(String(36), unique=True)
    status: Mapped[str] = mapped_column(String(16), default="reserved", server_default="reserved")
    payload: Mapped[dict] = mapped_column(JSONB)
    deadline_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    reserved_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    launched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    settled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    task_arn: Mapped[str | None] = mapped_column(String(512))
    # Whether the task ever claimed an attempt; False feeds the idle-respawn breaker.
    claimed: Mapped[bool | None]
    last_error: Mapped[str | None] = mapped_column(String(120))
