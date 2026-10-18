"""Let a release steer the always-on launcher (V2-live, AD-27); additive only.

`cap_limit` lowers the encoder cap while a release needs Fargate headroom for its migration and
schema-probe tasks; `worker_definition` points launches at the released worker. Both are NULL
(the stack's own cap and worker) except during and after a release, and an older image ignores
them, so a rollback needs nothing from this revision.
"""

import sqlalchemy as sa
from alembic import op

revision = "processing_0008"
down_revision = "processing_0007"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("launcher_control", sa.Column("cap_limit", sa.Integer()))
    op.add_column("launcher_control", sa.Column("worker_definition", sa.String(512)))


def downgrade():
    op.drop_column("launcher_control", "worker_definition")
    op.drop_column("launcher_control", "cap_limit")
