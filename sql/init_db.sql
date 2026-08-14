-- Xevyte Connect HRMS Agent — Postgres schema
-- Applied automatically on startup via SQLAlchemy's create_all(), but kept
-- here too as an explicit, reviewable DDL for DBA sign-off / manual setup:
--   psql "$DATABASE_URL" -f sql/init_db.sql

CREATE TABLE IF NOT EXISTS agent_sessions (
    id              VARCHAR(36) PRIMARY KEY,
    encrypted_token TEXT NOT NULL,
    employee_id     VARCHAR(128),
    employee_name   VARCHAR(256),
    role            VARCHAR(64),
    tenant_id       VARCHAR(64),
    tenant_name     VARCHAR(256),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at      TIMESTAMPTZ NOT NULL,
    revoked         BOOLEAN NOT NULL DEFAULT FALSE
);

CREATE TABLE IF NOT EXISTS conversations (
    id          VARCHAR(36) PRIMARY KEY,
    session_id  VARCHAR(36) NOT NULL REFERENCES agent_sessions(id) ON DELETE CASCADE,
    title       VARCHAR(256) NOT NULL DEFAULT 'New conversation',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_conversations_session_id ON conversations(session_id);

CREATE TABLE IF NOT EXISTS messages (
    id              VARCHAR(36) PRIMARY KEY,
    conversation_id VARCHAR(36) NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    role            VARCHAR(16) NOT NULL,
    content         TEXT NOT NULL,
    trace           JSONB,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_messages_conversation_id ON messages(conversation_id);
CREATE INDEX IF NOT EXISTS ix_messages_created_at ON messages(created_at);

CREATE TABLE IF NOT EXISTS approval_requests (
    id                    VARCHAR(36) PRIMARY KEY,
    session_id            VARCHAR(36) NOT NULL REFERENCES agent_sessions(id) ON DELETE CASCADE,
    conversation_id       VARCHAR(36) NOT NULL,
    tool_id               VARCHAR(160) NOT NULL,
    action_hash           VARCHAR(64) NOT NULL,
    risk_tier             VARCHAR(24) NOT NULL,
    encrypted_arguments   TEXT,
    arguments_summary     JSONB,
    policy_snapshot       JSONB,
    status                VARCHAR(16) NOT NULL DEFAULT 'PENDING',
    requested_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    decided_at            TIMESTAMPTZ,
    requester_employee_id VARCHAR(128),
    approver_employee_id  VARCHAR(128),
    decision_note         TEXT
);
CREATE INDEX IF NOT EXISTS ix_approval_requests_session_id ON approval_requests(session_id);
CREATE INDEX IF NOT EXISTS ix_approval_requests_status ON approval_requests(status);

CREATE TABLE IF NOT EXISTS param_provenance_log (
    id              VARCHAR(36) PRIMARY KEY,
    conversation_id VARCHAR(36) NOT NULL,
    tool_id         VARCHAR(160) NOT NULL,
    param_name      VARCHAR(128) NOT NULL,
    source          VARCHAR(16) NOT NULL,
    trusted         BOOLEAN NOT NULL,
    note            TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS event_log (
    id          VARCHAR(36) PRIMARY KEY,
    event_type  VARCHAR(64) NOT NULL,
    tenant_id   VARCHAR(64),
    payload     JSONB,
    processed   BOOLEAN NOT NULL DEFAULT FALSE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS prompt_versions (
    id               VARCHAR(36) PRIMARY KEY,
    prompt_id        VARCHAR(128) NOT NULL,
    version          INTEGER NOT NULL,
    environment      VARCHAR(32) DEFAULT 'production',
    model            VARCHAR(64),
    content          TEXT NOT NULL,
    evaluation_score DOUBLE PRECISION,
    status           VARCHAR(16) DEFAULT 'ACTIVE',
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS model_gateway_calls (
    id              VARCHAR(36) PRIMARY KEY,
    conversation_id VARCHAR(36),
    role            VARCHAR(32) NOT NULL,
    model           VARCHAR(64) NOT NULL,
    input_tokens    INTEGER,
    output_tokens   INTEGER,
    latency_ms      INTEGER,
    success         BOOLEAN DEFAULT TRUE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS circuit_breaker_state (
    tool_group    VARCHAR(160) PRIMARY KEY,
    state         VARCHAR(16) DEFAULT 'CLOSED',
    failure_count INTEGER DEFAULT 0,
    opened_at     TIMESTAMPTZ,
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS idempotency_keys (
    key               VARCHAR(128) PRIMARY KEY,
    tool_id           VARCHAR(160) NOT NULL,
    response_snapshot JSONB,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS workflow_runs (
    id             VARCHAR(36) PRIMARY KEY,
    conversation_id VARCHAR(36) NOT NULL,
    session_id     VARCHAR(36) NOT NULL,
    employee_id    VARCHAR(128),
    user_message   TEXT NOT NULL,
    intent         VARCHAR(64),
    domain         VARCHAR(64),
    tool_id        VARCHAR(160),
    state          VARCHAR(32) DEFAULT 'RECEIVED',
    retry_count    INTEGER DEFAULT 0,
    error_category VARCHAR(32),
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_workflow_runs_conversation_id ON workflow_runs(conversation_id);
CREATE INDEX IF NOT EXISTS ix_workflow_runs_state ON workflow_runs(state);

CREATE TABLE IF NOT EXISTS audit_log (
    id                VARCHAR(36) PRIMARY KEY,
    session_id        VARCHAR(36) REFERENCES agent_sessions(id) ON DELETE SET NULL,
    conversation_id   VARCHAR(36),
    employee_id       VARCHAR(128),
    endpoint_id       VARCHAR(160) NOT NULL,
    http_method       VARCHAR(8) NOT NULL,
    path              VARCHAR(512) NOT NULL,
    risk_tier         VARCHAR(16) NOT NULL,
    user_confirmed    BOOLEAN NOT NULL DEFAULT FALSE,
    request_summary   JSONB,
    response_status   INTEGER,
    response_summary  JSONB,
    success           BOOLEAN NOT NULL DEFAULT FALSE,
    error_message     TEXT,
    latency_ms        INTEGER,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_audit_log_employee_id ON audit_log(employee_id);
CREATE INDEX IF NOT EXISTS ix_audit_log_created_at ON audit_log(created_at);
CREATE INDEX IF NOT EXISTS ix_audit_log_risk_tier ON audit_log(risk_tier);

