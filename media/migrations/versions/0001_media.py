"""Independent Media users, immutable intake, request and cleanup intents."""

from alembic import op

revision = "0001_media"
down_revision = None
branch_labels = None
depends_on = None

STATEMENTS = [
    """CREATE TABLE staged_objects (
	key TEXT NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (key)
)""",
    """CREATE TABLE users (
	id UUID NOT NULL, 
	email VARCHAR(320) NOT NULL, 
	password_hash TEXT NOT NULL, 
	role VARCHAR(20) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	CHECK (role IN ('user', 'operator')), 
	UNIQUE (email)
)""",
    """CREATE TABLE assets (
	id UUID NOT NULL, 
	owner_id UUID NOT NULL, 
	filename VARCHAR(100) NOT NULL, 
	source_key TEXT NOT NULL, 
	source_revision INTEGER NOT NULL, 
	source_sha256 VARCHAR(64) NOT NULL, 
	source_size_bytes INTEGER NOT NULL, 
	source_media_type VARCHAR(100) NOT NULL, 
	source_asset_id UUID, 
	operations JSONB NOT NULL, 
	submission_state VARCHAR(20) NOT NULL, 
	processing_job_id UUID, 
	submitted_at TIMESTAMP WITH TIME ZONE, 
	last_submit_error TEXT, 
	submit_attempts INTEGER NOT NULL, 
	next_submit_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	deleted_at TIMESTAMP WITH TIME ZONE, 
	PRIMARY KEY (id), 
	CHECK (source_revision >= 1 AND source_size_bytes > 0), 
	CHECK (submission_state IN ('pending', 'submitted', 'error')), 
	FOREIGN KEY(owner_id) REFERENCES users (id), 
	UNIQUE (source_key)
)""",
    """CREATE INDEX ix_assets_owner_id ON assets (owner_id)""",
    """CREATE INDEX assets_pending_due ON assets (submission_state, next_submit_at)""",
    """CREATE TABLE cleanup_intents (
	asset_id UUID NOT NULL, 
	processing_deleted_at TIMESTAMP WITH TIME ZONE, 
	source_deleted_at TIMESTAMP WITH TIME ZONE, 
	next_try_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	attempts INTEGER NOT NULL, 
	last_error TEXT, 
	PRIMARY KEY (asset_id), 
	FOREIGN KEY(asset_id) REFERENCES assets (id)
)""",
    """CREATE TABLE request_keys (
	owner_id UUID NOT NULL, 
	operation VARCHAR(20) NOT NULL, 
	request_key UUID NOT NULL, 
	request_hash VARCHAR(64) NOT NULL, 
	asset_id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (owner_id, operation, request_key), 
	FOREIGN KEY(owner_id) REFERENCES users (id), 
	FOREIGN KEY(asset_id) REFERENCES assets (id)
)""",
    """CREATE TABLE retry_intents (
	id UUID NOT NULL, 
	asset_id UUID NOT NULL, 
	confirmed_at TIMESTAMP WITH TIME ZONE, 
	rejected_at TIMESTAMP WITH TIME ZONE, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	next_try_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	attempts INTEGER NOT NULL, 
	last_error TEXT, 
	PRIMARY KEY (id), 
	FOREIGN KEY(asset_id) REFERENCES assets (id)
)""",
    """CREATE INDEX ix_retry_intents_asset_id ON retry_intents (asset_id)""",
]


def upgrade():
    for statement in STATEMENTS:
        op.execute(statement)


def downgrade():
    for name in [
        "retry_intents",
        "request_keys",
        "cleanup_intents",
        "assets",
        "users",
        "staged_objects",
    ]:
        op.drop_table(name)
