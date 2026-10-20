"""Backoff and retirement for expired direct-upload rescans.

The outcome of a scan (clean or failed) is not recoverable from any earlier column, and
retirement must never follow a failed scan, so the schedule needs its own columns.
"""

import sqlalchemy as sa
from alembic import op

revision = "media_0008"
down_revision = "media_0007"
branch_labels = None
depends_on = None


def upgrade():
    # Existing rows become due immediately: their next clean scan past the horizon retires
    # them, and until then they back off like any other row.
    op.add_column(
        "upload_reservations",
        sa.Column(
            "cleanup_next_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.add_column(
        "upload_reservations",
        sa.Column("cleanup_attempts", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "upload_reservations", sa.Column("cleanup_retired_at", sa.DateTime(timezone=True))
    )
    op.create_index(
        "ix_upload_reservations_cleanup_due",
        "upload_reservations",
        ["cleanup_next_at"],
        postgresql_where=sa.text("cleanup_retired_at IS NULL"),
    )


def downgrade():
    op.drop_index("ix_upload_reservations_cleanup_due", table_name="upload_reservations")
    op.drop_column("upload_reservations", "cleanup_retired_at")
    op.drop_column("upload_reservations", "cleanup_attempts")
    op.drop_column("upload_reservations", "cleanup_next_at")
