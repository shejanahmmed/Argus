-- =============================================================================
-- Argus Production Database DDL Migrations (PostgreSQL 16 & ClickHouse 24)
-- Matches the self-hosted OSS stack defined in docker-compose.yml.
-- =============================================================================

-- -----------------------------------------------------------------------------
-- 1. PostgreSQL 16 Transactional Control Plane Schema
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS argus_sessions (
    session_id UUID PRIMARY KEY,
    tenant_id VARCHAR(128) NOT NULL,
    workspace_id VARCHAR(128) NOT NULL,
    workflow_id VARCHAR(128) NOT NULL,
    agent_name VARCHAR(128) NOT NULL,
    framework VARCHAR(32) NOT NULL,
    status VARCHAR(32) NOT NULL,
    budget_cap_usd DOUBLE PRECISION NOT NULL,
    accumulated_cost_usd DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    latest_checkpoint_id UUID NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_pg_sessions_tenant
    ON argus_sessions (tenant_id, workspace_id, created_at DESC);

CREATE TABLE IF NOT EXISTS argus_checkpoints (
    seq_id BIGSERIAL PRIMARY KEY,
    checkpoint_id UUID NOT NULL UNIQUE,
    parent_checkpoint_id UUID NULL,
    tenant_id VARCHAR(128) NOT NULL,
    workspace_id VARCHAR(128) NOT NULL,
    session_id UUID NOT NULL REFERENCES argus_sessions(session_id) ON DELETE CASCADE,
    node_name VARCHAR(128) NOT NULL,
    step_index INTEGER NOT NULL,
    memory_state JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_pg_checkpoints_session
    ON argus_checkpoints (session_id, seq_id DESC);

CREATE TABLE IF NOT EXISTS argus_audit_ledger (
    seq_id BIGSERIAL PRIMARY KEY,
    audit_id UUID NOT NULL UNIQUE,
    tenant_id VARCHAR(128) NOT NULL,
    workspace_id VARCHAR(128) NOT NULL,
    session_id UUID NOT NULL,
    actor_id VARCHAR(128) NOT NULL,
    actor_role VARCHAR(32) NOT NULL,
    event_type VARCHAR(64) NOT NULL,
    payload JSONB NOT NULL,
    prev_entry_hash CHAR(64) NOT NULL,
    entry_hash CHAR(64) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_pg_audit_session
    ON argus_audit_ledger (tenant_id, workspace_id, session_id, seq_id ASC);

-- -----------------------------------------------------------------------------
-- 2. ClickHouse 24 Columnar Telemetry Schema (Execute on ClickHouse node)
-- -----------------------------------------------------------------------------
-- CREATE TABLE IF NOT EXISTS argus_telemetry.argus_spans (
--     tenant_id LowCardinality(String),
--     workspace_id LowCardinality(String),
--     session_id UUID,
--     trace_id UUID,
--     span_id UUID,
--     parent_span_id Nullable(UUID),
--     dotted_order String,
--     name String,
--     span_kind LowCardinality(String),
--     operation_name LowCardinality(String),
--     framework LowCardinality(String),
--     model_name Nullable(String),
--     provider_name Nullable(String),
--     prompt_tokens UInt32,
--     completion_tokens UInt32,
--     cost_usd Float64,
--     ttft_ms Nullable(Float64),
--     latency_ms Float64,
--     input_payload String,
--     output_payload String,
--     state_diff String,
--     attributes String,
--     redacted UInt8,
--     started_at DateTime64(6, 'UTC'),
--     ended_at Nullable(DateTime64(6, 'UTC'))
-- ) ENGINE = MergeTree()
-- PARTITION BY toYYYYMM(started_at)
-- ORDER BY (tenant_id, workspace_id, session_id, dotted_order);
