"""Durable direct upload reservations and immutable source version pins."""

import sqlalchemy as sa
from alembic import op

revision = "media_0004"
down_revision = "0002_uncertain_writes"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "asset_source_versions",
        sa.Column("asset_id", sa.Uuid(), sa.ForeignKey("assets.id"), primary_key=True),
        sa.Column("bucket", sa.Text(), nullable=False),
        sa.Column("key", sa.Text(), nullable=False),
        sa.Column("version_id", sa.Text(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("content_type", sa.String(100), nullable=False),
    )
    op.create_table(
        "upload_reservations",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("owner_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("request_id", sa.Uuid(), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("asset_id", sa.Uuid(), nullable=False, unique=True),
        sa.Column("filename", sa.String(100), nullable=False),
        sa.Column("bucket", sa.Text(), nullable=False),
        sa.Column("key", sa.Text(), nullable=False, unique=True),
        sa.Column("content_type", sa.String(100), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("version_id", sa.Text()),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finalized_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("cleanup_checked_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("owner_id", "request_id"),
    )
    op.create_index("ix_upload_reservations_owner_id", "upload_reservations", ["owner_id"])
    op.create_index("ix_upload_reservations_expires_at", "upload_reservations", ["expires_at"])


def downgrade():
    op.drop_table("upload_reservations")
    op.drop_table("asset_source_versions")
