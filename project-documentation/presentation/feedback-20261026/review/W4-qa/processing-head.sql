CREATE TABLE jobs (
    id UUID NOT NULL, 
    asset_id UUID NOT NULL, 
    owner_id UUID NOT NULL, 
    source JSONB NOT NULL, 
    operations JSONB NOT NULL, 
    request_hash VARCHAR(64) NOT NULL, 
    source_url VARCHAR NOT NULL, 
    source_url_expires_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    status VARCHAR(16) NOT NULL, 
    current_attempt_id UUID NOT NULL, 
    error VARCHAR, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    deleted_at TIMESTAMP WITH TIME ZONE, 
    PRIMARY KEY (id), 
    CONSTRAINT ck_jobs_status CHECK (status IN ('queued', 'processing', 'done', 'failed')), 
    UNIQUE (asset_id)
);

CREATE INDEX ix_jobs_owner_id ON jobs (owner_id);

CREATE TABLE attempts (
    id UUID NOT NULL, 
    job_id UUID NOT NULL, 
    attempt_number INTEGER NOT NULL, 
    state VARCHAR(16) NOT NULL, 
    queued_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    started_at TIMESTAMP WITH TIME ZONE, 
    finished_at TIMESTAMP WITH TIME ZONE, 
    error VARCHAR, 
    PRIMARY KEY (id), 
    CONSTRAINT uq_attempts_job_number UNIQUE (job_id, attempt_number), 
    CONSTRAINT ck_attempts_number CHECK (attempt_number >= 1), 
    CONSTRAINT ck_attempts_state CHECK (state IN ('queued', 'processing', 'succeeded', 'failed', 'abandoned', 'cancelled')), 
    FOREIGN KEY(job_id) REFERENCES jobs (id)
);

ALTER TABLE jobs ADD CONSTRAINT fk_jobs_current_attempt FOREIGN KEY(current_attempt_id) REFERENCES attempts (id) DEFERRABLE INITIALLY DEFERRED;

CREATE TABLE submission_guards (
    asset_id UUID NOT NULL, 
    owner_id UUID NOT NULL, 
    job_id UUID, 
    deleted_at TIMESTAMP WITH TIME ZONE, 
    PRIMARY KEY (asset_id), 
    FOREIGN KEY(job_id) REFERENCES jobs (id)
);

ALTER TABLE jobs ADD COLUMN outputs JSONB DEFAULT '[]'::jsonb NOT NULL;

ALTER TABLE attempts ADD COLUMN lease_token UUID;

ALTER TABLE attempts ADD COLUMN heartbeat_at TIMESTAMP WITH TIME ZONE;

ALTER TABLE attempts ADD COLUMN lease_expires_at TIMESTAMP WITH TIME ZONE;

ALTER TABLE attempts ADD COLUMN deadline_at TIMESTAMP WITH TIME ZONE;

ALTER TABLE attempts ADD COLUMN next_dispatch_at TIMESTAMP WITH TIME ZONE;

ALTER TABLE attempts ADD COLUMN dispatch_error VARCHAR;

ALTER TABLE attempts ADD COLUMN dispatch_count INTEGER DEFAULT '0' NOT NULL;

CREATE INDEX ix_attempts_recovery ON attempts (state, next_dispatch_at);

CREATE TABLE retry_requests (
    id UUID NOT NULL, 
    job_id UUID NOT NULL, 
    request_id UUID NOT NULL, 
    attempt_id UUID NOT NULL, 
    PRIMARY KEY (id), 
    UNIQUE (job_id, request_id), 
    FOREIGN KEY(job_id) REFERENCES jobs (id) ON DELETE CASCADE, 
    FOREIGN KEY(attempt_id) REFERENCES attempts (id) ON DELETE CASCADE
);

CREATE TABLE cleanup_intents (
    attempt_id UUID NOT NULL, 
    job_id UUID NOT NULL, 
    next_try_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    tries INTEGER DEFAULT '0' NOT NULL, 
    last_error VARCHAR, 
    PRIMARY KEY (attempt_id), 
    FOREIGN KEY(attempt_id) REFERENCES attempts (id) ON DELETE CASCADE, 
    FOREIGN KEY(job_id) REFERENCES jobs (id) ON DELETE CASCADE
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

CREATE TABLE job_messaging (
    job_id UUID NOT NULL, 
    state_version INTEGER DEFAULT '0' NOT NULL, 
    PRIMARY KEY (job_id), 
    FOREIGN KEY(job_id) REFERENCES jobs (id)
);

CREATE TABLE attempt_tasks (
    attempt_id UUID NOT NULL, 
    task_name VARCHAR(256) NOT NULL, 
    PRIMARY KEY (attempt_id), 
    FOREIGN KEY(attempt_id) REFERENCES attempts (id), 
    UNIQUE (task_name)
);

ALTER TABLE cleanup_intents ADD COLUMN created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL;

ALTER TABLE cleanup_intents ADD COLUMN retired_at TIMESTAMP WITH TIME ZONE;

CREATE INDEX ix_cleanup_intents_due ON cleanup_intents (next_try_at, attempt_id) WHERE retired_at IS NULL;

CREATE TABLE launcher_control (
    id SERIAL NOT NULL, 
    enabled BOOLEAN DEFAULT false NOT NULL, 
    enabled_at TIMESTAMP WITH TIME ZONE, 
    session_end_at TIMESTAMP WITH TIME ZONE, 
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    PRIMARY KEY (id), 
    CONSTRAINT ck_launcher_control_singleton CHECK (id = 1)
);

CREATE TABLE launch_reservations (
    token VARCHAR(64) NOT NULL, 
    started_by VARCHAR(36) NOT NULL, 
    status VARCHAR(16) DEFAULT 'reserved' NOT NULL, 
    payload JSONB NOT NULL, 
    deadline_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    reserved_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    sent_at TIMESTAMP WITH TIME ZONE, 
    launched_at TIMESTAMP WITH TIME ZONE, 
    settled_at TIMESTAMP WITH TIME ZONE, 
    task_arn VARCHAR(512), 
    claimed BOOLEAN, 
    last_error VARCHAR(120), 
    PRIMARY KEY (token), 
    CONSTRAINT ck_launch_reservations_status CHECK (status IN ('reserved', 'launched', 'stopped', 'released')), 
    UNIQUE (started_by)
);

CREATE INDEX ix_launch_reservations_open ON launch_reservations (reserved_at) WHERE status IN ('reserved', 'launched');

