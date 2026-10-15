"""Media's owned Processing result projection."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0005_projection"
down_revision = "media_0004"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "processing_projections",
        sa.Column("asset_id", sa.Uuid(), sa.ForeignKey("assets.id"), primary_key=True),
        sa.Column("job_id", sa.Uuid(), nullable=False, unique=True),
        sa.Column("attempt_id", sa.Uuid(), nullable=True),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("state_version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("source", JSONB(), nullable=False),
        sa.Column("outputs", JSONB(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("result_hash", sa.String(64), nullable=False),
        sa.CheckConstraint("state_version >= 0 AND attempt_number >= 0"),
        sa.CheckConstraint("status IN ('queued', 'processing', 'done', 'failed', 'cancelled')"),
    )

    op.create_table(
        "derived_sources",
        sa.Column("asset_id", sa.Uuid(), sa.ForeignKey("assets.id"), primary_key=True),
        sa.Column("descriptor", JSONB(), nullable=False),
    )


def downgrade():
    op.drop_table("derived_sources")
    op.drop_table("processing_projections")
