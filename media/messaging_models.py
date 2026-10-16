"""Media-owned durable message records; no cross-domain database references."""

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import DateTime, Index, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from media.database import Base


class MediaInbox(Base):
    __tablename__ = "message_inbox"
    message_id: Mapped[UUID] = mapped_column(primary_key=True)
    body_hash: Mapped[str] = mapped_column(String(64))
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), server_default=func.now()
    )


class MediaOutbox(Base):
    __tablename__ = "message_outbox"
    __table_args__ = (Index("ix_message_outbox_due", "next_try_at"),)
    message_id: Mapped[UUID] = mapped_column(primary_key=True)
    body_hash: Mapped[str] = mapped_column(String(64))
    queue: Mapped[str] = mapped_column(String(40))
    body: Mapped[dict] = mapped_column(JSONB)
    next_try_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    tries: Mapped[int] = mapped_column(default=0, server_default="0")
    claim_token: Mapped[UUID | None]
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None]
