"""Add durable attempt leases, replay identities and repeatable cleanup."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "processing_0002"
down_revision = "processing_0001"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "jobs",
        sa.Column(
            "outputs", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")
        ),
    )
    for name, kind in (
        ("lease_token", sa.Uuid()),
        ("heartbeat_at", sa.DateTime(timezone=True)),
        ("lease_expires_at", sa.DateTime(timezone=True)),
        ("deadline_at", sa.DateTime(timezone=True)),
        ("next_dispatch_at", sa.DateTime(timezone=True)),
        ("dispatch_error", sa.String()),
    ):
        op.add_column("attempts", sa.Column(name, kind, nullable=True))
    op.add_column(
        "attempts", sa.Column("dispatch_count", sa.Integer(), nullable=False, server_default="0")
    )
    op.create_index("ix_attempts_recovery", "attempts", ["state", "next_dispatch_at"])
    op.create_table(
        "retry_requests",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "job_id", sa.Uuid(), sa.ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("request_id", sa.Uuid(), nullable=False),
        sa.Column(
            "attempt_id",
            sa.Uuid(),
            sa.ForeignKey("attempts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.UniqueConstraint("job_id", "request_id"),
    )
    op.create_table(
        "cleanup_intents",
        sa.Column(
            "attempt_id",
            sa.Uuid(),
            sa.ForeignKey("attempts.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "job_id", sa.Uuid(), sa.ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("next_try_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("tries", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.String(), nullable=True),
    )


def downgrade():
    op.drop_table("cleanup_intents")
    op.drop_table("retry_requests")
    op.drop_index("ix_attempts_recovery", table_name="attempts")
    for name in (
        "dispatch_count",
        "dispatch_error",
        "next_dispatch_at",
        "deadline_at",
        "lease_expires_at",
        "heartbeat_at",
        "lease_token",
    ):
        op.drop_column("attempts", name)
    op.drop_column("jobs", "outputs")
