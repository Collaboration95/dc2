"""Bound late-output rescans with a retirement horizon (0004 was never issued).

Alembic orders by revision ID, not file number; 0005 depends on 0003 directly.
"""

import sqlalchemy as sa
from alembic import op

revision = "processing_0006"
down_revision = "processing_0005"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "cleanup_intents",
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.add_column("cleanup_intents", sa.Column("retired_at", sa.DateTime(timezone=True)))
    op.create_index(
        "ix_cleanup_intents_due",
        "cleanup_intents",
        ["next_try_at", "attempt_id"],
        postgresql_where=sa.text("retired_at IS NULL"),
    )


def downgrade():
    op.drop_index("ix_cleanup_intents_due", table_name="cleanup_intents")
    op.drop_column("cleanup_intents", "retired_at")
    op.drop_column("cleanup_intents", "created_at")
