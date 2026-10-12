"""Independent Processing intake tables."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "processing_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "jobs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("asset_id", sa.Uuid(), nullable=False, unique=True),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("source", postgresql.JSONB(), nullable=False),
        sa.Column("operations", postgresql.JSONB(), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("source_url", sa.String(), nullable=False),
        sa.Column("source_url_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("current_attempt_id", sa.Uuid(), nullable=False),
        sa.Column("error", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('queued', 'processing', 'done', 'failed')", name="ck_jobs_status"
        ),
    )
    op.create_index("ix_jobs_owner_id", "jobs", ["owner_id"])
    op.create_table(
        "attempts",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("job_id", sa.Uuid(), sa.ForeignKey("jobs.id"), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("queued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error", sa.String(), nullable=True),
        sa.UniqueConstraint("job_id", "attempt_number", name="uq_attempts_job_number"),
        sa.CheckConstraint("attempt_number >= 1", name="ck_attempts_number"),
        sa.CheckConstraint(
            "state IN ('queued', 'processing', 'succeeded', 'failed', 'abandoned', 'cancelled')",
            name="ck_attempts_state",
        ),
    )
    op.create_foreign_key(
        "fk_jobs_current_attempt",
        "jobs",
        "attempts",
        ["current_attempt_id"],
        ["id"],
        deferrable=True,
        initially="DEFERRED",
    )
    op.create_table(
        "submission_guards",
        sa.Column("asset_id", sa.Uuid(), primary_key=True),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("job_id", sa.Uuid(), sa.ForeignKey("jobs.id"), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("submission_guards")
    op.drop_constraint("fk_jobs_current_attempt", "jobs", type_="foreignkey")
    op.drop_table("attempts")
    op.drop_index("ix_jobs_owner_id", table_name="jobs")
    op.drop_table("jobs")
