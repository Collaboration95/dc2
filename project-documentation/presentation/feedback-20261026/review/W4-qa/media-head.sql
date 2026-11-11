CREATE TABLE staged_objects (
    key TEXT NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    PRIMARY KEY (key)
);

CREATE TABLE users (
    id UUID NOT NULL, 
    email VARCHAR(320) NOT NULL, 
    password_hash TEXT NOT NULL, 
    role VARCHAR(20) NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    PRIMARY KEY (id), 
    CHECK (role IN ('user', 'operator')), 
    UNIQUE (email)
);

CREATE TABLE assets (
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
);

CREATE INDEX ix_assets_owner_id ON assets (owner_id);

CREATE INDEX assets_pending_due ON assets (submission_state, next_submit_at);

CREATE TABLE cleanup_intents (
    asset_id UUID NOT NULL, 
    processing_deleted_at TIMESTAMP WITH TIME ZONE, 
    source_deleted_at TIMESTAMP WITH TIME ZONE, 
    next_try_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    attempts INTEGER NOT NULL, 
    last_error TEXT, 
    PRIMARY KEY (asset_id), 
    FOREIGN KEY(asset_id) REFERENCES assets (id)
);

CREATE TABLE request_keys (
    owner_id UUID NOT NULL, 
    operation VARCHAR(20) NOT NULL, 
    request_key UUID NOT NULL, 
    request_hash VARCHAR(64) NOT NULL, 
    asset_id UUID NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    PRIMARY KEY (owner_id, operation, request_key), 
    FOREIGN KEY(owner_id) REFERENCES users (id), 
    FOREIGN KEY(asset_id) REFERENCES assets (id)
);

CREATE TABLE retry_intents (
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
);

CREATE INDEX ix_retry_intents_asset_id ON retry_intents (asset_id);

ALTER TABLE staged_objects ADD COLUMN write_uncertain BOOLEAN DEFAULT true NOT NULL;

CREATE TABLE asset_source_versions (
    asset_id UUID NOT NULL, 
    bucket TEXT NOT NULL, 
    key TEXT NOT NULL, 
    version_id TEXT NOT NULL, 
    sha256 VARCHAR(64) NOT NULL, 
    size_bytes INTEGER NOT NULL, 
    content_type VARCHAR(100) NOT NULL, 
    PRIMARY KEY (asset_id), 
    FOREIGN KEY(asset_id) REFERENCES assets (id)
);

CREATE TABLE upload_reservations (
    id UUID NOT NULL, 
    owner_id UUID NOT NULL, 
    request_id UUID NOT NULL, 
    request_hash VARCHAR(64) NOT NULL, 
    asset_id UUID NOT NULL, 
    filename VARCHAR(100) NOT NULL, 
    bucket TEXT NOT NULL, 
    key TEXT NOT NULL, 
    content_type VARCHAR(100) NOT NULL, 
    size_bytes INTEGER NOT NULL, 
    sha256 VARCHAR(64) NOT NULL, 
    version_id TEXT, 
    expires_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    finalized_at TIMESTAMP WITH TIME ZONE, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    cleanup_checked_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    PRIMARY KEY (id), 
    UNIQUE (owner_id, request_id), 
    FOREIGN KEY(owner_id) REFERENCES users (id), 
    UNIQUE (asset_id), 
    UNIQUE (key)
);

CREATE INDEX ix_upload_reservations_owner_id ON upload_reservations (owner_id);

CREATE INDEX ix_upload_reservations_expires_at ON upload_reservations (expires_at);

CREATE TABLE processing_projections (
    asset_id UUID NOT NULL, 
    job_id UUID NOT NULL, 
    attempt_id UUID, 
    attempt_number INTEGER NOT NULL, 
    state_version INTEGER NOT NULL, 
    status VARCHAR(20) NOT NULL, 
    source JSONB NOT NULL, 
    outputs JSONB NOT NULL, 
    error TEXT, 
    result_hash VARCHAR(64) NOT NULL, 
    PRIMARY KEY (asset_id), 
    CHECK (state_version >= 0 AND attempt_number >= 0), 
    CHECK (status IN ('queued', 'processing', 'done', 'failed', 'cancelled')), 
    FOREIGN KEY(asset_id) REFERENCES assets (id), 
    UNIQUE (job_id)
);

CREATE TABLE message_inbox (
    message_id UUID NOT NULL, 
    body_hash VARCHAR(64) NOT NULL, 
    received_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    PRIMARY KEY (message_id)
);

CREATE TABLE message_outbox (
    message_id UUID NOT NULL, 
    body_hash VARCHAR(64) NOT NULL, 
    queue VARCHAR(40) NOT NULL, 
    body JSONB NOT NULL, 
    next_try_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    tries INTEGER DEFAULT '0' NOT NULL, 
    claim_token UUID, 
    sent_at TIMESTAMP WITH TIME ZONE, 
    last_error VARCHAR, 
    PRIMARY KEY (message_id)
);

CREATE INDEX ix_message_outbox_due ON message_outbox (next_try_at);

ALTER TABLE upload_reservations ADD CONSTRAINT ck_upload_reservations_finalized_has_pin CHECK (finalized_at IS NULL OR (version_id IS NOT NULL AND version_id NOT IN ('', 'null')));

ALTER TABLE upload_reservations ADD COLUMN cleanup_next_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL;

ALTER TABLE upload_reservations ADD COLUMN cleanup_attempts INTEGER DEFAULT '0' NOT NULL;

ALTER TABLE upload_reservations ADD COLUMN cleanup_retired_at TIMESTAMP WITH TIME ZONE;

CREATE INDEX ix_upload_reservations_cleanup_due ON upload_reservations (cleanup_next_at) WHERE cleanup_retired_at IS NULL;

