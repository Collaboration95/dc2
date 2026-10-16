"""A finalized upload reservation can never exist without its pinned S3 VersionId."""

import sqlalchemy as sa
from alembic import op

revision = "media_0007"
down_revision = "media_0006"
branch_labels = None
depends_on = None

# The pin lives on the reservation (direct uploads) or asset_source_versions (derived
# sources). Without this constraint a bug or manual repair could leave an adopted asset
# whose staging key is only addressable unversioned, which a replayed grant can overwrite.
CONSTRAINT = "ck_upload_reservations_finalized_has_pin"
PREDICATE = "finalized_at IS NULL OR (version_id IS NOT NULL AND version_id NOT IN ('', 'null'))"


def upgrade():
    op.create_check_constraint(CONSTRAINT, "upload_reservations", sa.text(PREDICATE))


def downgrade():
    op.drop_constraint(CONSTRAINT, "upload_reservations", type_="check")
