"""Persist one-attempt-per-finite-task ownership without rewriting applied 0003."""

import sqlalchemy as sa
from alembic import op

revision = "processing_0005"
down_revision = "processing_0003"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "attempt_tasks",
        sa.Column("attempt_id", sa.Uuid(), sa.ForeignKey("attempts.id"), primary_key=True),
        sa.Column("task_name", sa.String(256), nullable=False, unique=True),
    )


def downgrade():
    op.drop_table("attempt_tasks")
