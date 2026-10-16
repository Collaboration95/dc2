"""Durable direct-upload grants and immutable adopted source revisions."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from media.database import Base
from media.models import now


class UploadReservation(Base):
    __tablename__ = "upload_reservations"
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    owner_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    request_id: Mapped[UUID] = mapped_column(Uuid)
    request_hash: Mapped[str] = mapped_column(String(64))
    asset_id: Mapped[UUID] = mapped_column(Uuid, unique=True)
    filename: Mapped[str] = mapped_column(String(100))
    bucket: Mapped[str] = mapped_column(Text)
    key: Mapped[str] = mapped_column(Text, unique=True)
    content_type: Mapped[str] = mapped_column(String(100))
    size_bytes: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64))
    version_id: Mapped[str | None] = mapped_column(Text)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    finalized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cleanup_checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    # Rescan schedule: attempts drive the backoff, next_at orders the batch, and retired_at
    # (a clean scan past the horizon) ends it. Failed scans never retire a row.
    cleanup_next_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=now, server_default=func.now()
    )
    cleanup_attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    cleanup_retired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    __table_args__ = (
        UniqueConstraint("owner_id", "request_id"),
        Index(
            "ix_upload_reservations_cleanup_due",
            "cleanup_next_at",
            postgresql_where=text("cleanup_retired_at IS NULL"),
        ),
        CheckConstraint(
            "finalized_at IS NULL OR (version_id IS NOT NULL AND version_id NOT IN ('', 'null'))",
            name="ck_upload_reservations_finalized_has_pin",
        ),
    )


class SourceVersion(Base):
    """Version pins for derived assets copied from validated Processing outputs."""

    __tablename__ = "asset_source_versions"
    asset_id: Mapped[UUID] = mapped_column(ForeignKey("assets.id"), primary_key=True)
    bucket: Mapped[str] = mapped_column(Text)
    key: Mapped[str] = mapped_column(Text)
    version_id: Mapped[str] = mapped_column(Text)
    sha256: Mapped[str] = mapped_column(String(64))
    size_bytes: Mapped[int] = mapped_column(Integer)
    content_type: Mapped[str] = mapped_column(String(100))
