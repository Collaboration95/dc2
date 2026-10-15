"""Media-owned read model; never query Processing's database."""

from uuid import UUID

from sqlalchemy import CheckConstraint, ForeignKey, Integer, String, Text, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from media.database import Base


class ProcessingProjection(Base):
    __tablename__ = "processing_projections"

    asset_id: Mapped[UUID] = mapped_column(ForeignKey("assets.id"), primary_key=True)
    job_id: Mapped[UUID] = mapped_column(Uuid, unique=True)
    attempt_id: Mapped[UUID | None] = mapped_column(Uuid)
    attempt_number: Mapped[int] = mapped_column(Integer)
    state_version: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20))
    source: Mapped[dict] = mapped_column(JSONB)
    outputs: Mapped[list] = mapped_column(JSONB, default=list)
    error: Mapped[str | None] = mapped_column(Text)
    result_hash: Mapped[str] = mapped_column(String(64))

    __table_args__ = (
        CheckConstraint("state_version >= 0 AND attempt_number >= 0"),
        CheckConstraint("status IN ('queued', 'processing', 'done', 'failed', 'cancelled')"),
    )


class DerivedSource(Base):
    """Accepted, immutable source copied from an owned completed output."""

    __tablename__ = "derived_sources"
    asset_id: Mapped[UUID] = mapped_column(ForeignKey("assets.id"), primary_key=True)
    descriptor: Mapped[dict] = mapped_column(JSONB)
