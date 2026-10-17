"""Add owned V1 inbox/outbox and replay bookkeeping."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "processing_0003"
down_revision = "processing_0002"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "message_inbox",
        sa.Column("message_id", sa.Uuid(), primary_key=True),
        sa.Column("body_hash", sa.String(64), nullable=False),
        sa.Column(
            "received_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_table(
        "message_outbox",
        sa.Column("message_id", sa.Uuid(), primary_key=True),
        sa.Column("body_hash", sa.String(64), nullable=False),
        sa.Column("queue", sa.String(40), nullable=False),
        sa.Column("body", postgresql.JSONB(), nullable=False),
        sa.Column("next_try_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("tries", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("claim_token", sa.Uuid(), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.String(), nullable=True),
    )
    op.create_index("ix_message_outbox_due", "message_outbox", ["next_try_at"])
    op.create_table(
        "job_messaging",
        sa.Column("job_id", sa.Uuid(), sa.ForeignKey("jobs.id"), primary_key=True),
        sa.Column("state_version", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade():
    op.drop_table("job_messaging")
    op.drop_index("ix_message_outbox_due", table_name="message_outbox")
    op.drop_table("message_outbox")
    op.drop_table("message_inbox")
