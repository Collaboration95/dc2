"""Retain cleanup authority until source writer completion is known."""

import sqlalchemy as sa
from alembic import op

revision = "0002_uncertain_writes"
down_revision = "0001_media"
branch_labels = None
depends_on = None


def upgrade():
    # Existing reservations have no durable proof of writer completion.
    op.add_column(
        "staged_objects",
        sa.Column("write_uncertain", sa.Boolean(), nullable=False, server_default=sa.true()),
    )


def downgrade():
    op.drop_column("staged_objects", "write_uncertain")
