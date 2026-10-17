"""Add the opt-in launcher's control row and launch reservations (additive only).

Nothing reads these tables unless the stack was deployed with UnattendedLaunch=true, so
rolling the image back leaves V1 behaviour untouched and the tables simply idle.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "processing_0007"
down_revision = "processing_0006"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "launcher_control",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("enabled_at", sa.DateTime(timezone=True)),
        sa.Column("session_end_at", sa.DateTime(timezone=True)),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint("id = 1", name="ck_launcher_control_singleton"),
    )
    op.create_table(
        "launch_reservations",
        sa.Column("token", sa.String(64), primary_key=True),
        sa.Column("started_by", sa.String(36), nullable=False, unique=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="reserved"),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("deadline_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "reserved_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("sent_at", sa.DateTime(timezone=True)),
        sa.Column("launched_at", sa.DateTime(timezone=True)),
        sa.Column("settled_at", sa.DateTime(timezone=True)),
        sa.Column("task_arn", sa.String(512)),
        sa.Column("claimed", sa.Boolean()),
        sa.Column("last_error", sa.String(120)),
        sa.CheckConstraint(
            "status IN ('reserved', 'launched', 'stopped', 'released')",
            name="ck_launch_reservations_status",
        ),
    )
    op.create_index(
        "ix_launch_reservations_open",
        "launch_reservations",
        ["reserved_at"],
        postgresql_where=sa.text("status IN ('reserved', 'launched')"),
    )


def downgrade():
    op.drop_index("ix_launch_reservations_open", table_name="launch_reservations")
    op.drop_table("launch_reservations")
    op.drop_table("launcher_control")
