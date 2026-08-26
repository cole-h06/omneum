CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TYPE visibility_scope AS ENUM (
    'private',
    'organization',
    'public'
);

CREATE TYPE evaluation_status AS ENUM (
    'pending',
    'running',
    'completed',
    'failed'
);


CREATE TABLE organizations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);


CREATE TABLE workspaces (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL
        REFERENCES organizations(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    UNIQUE (organization_id, name)
);


CREATE TABLE agents (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id UUID NOT NULL
        REFERENCES workspaces(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    external_id TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    UNIQUE (workspace_id, external_id)
);


CREATE TABLE api_keys (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id UUID NOT NULL
        REFERENCES workspaces(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    key_prefix TEXT NOT NULL,
    key_hash TEXT NOT NULL UNIQUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at TIMESTAMPTZ,
    revoked_at TIMESTAMPTZ
);


CREATE TABLE sources (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id UUID NOT NULL
        REFERENCES workspaces(id) ON DELETE CASCADE,
    source_token BYTEA NOT NULL,
    source_kind TEXT,
    public_identifier TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    UNIQUE (workspace_id, source_token)
);


CREATE TABLE claims (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id UUID NOT NULL
        REFERENCES workspaces(id) ON DELETE CASCADE,

    claim_token BYTEA NOT NULL,
    entity_token BYTEA NOT NULL,
    attribute_token BYTEA NOT NULL,
    value_token BYTEA NOT NULL,

    public_claim JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    UNIQUE (workspace_id, claim_token)
);


CREATE TABLE observations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id UUID NOT NULL
        REFERENCES workspaces(id) ON DELETE CASCADE,
    agent_id UUID
        REFERENCES agents(id) ON DELETE SET NULL,
    source_id UUID NOT NULL
        REFERENCES sources(id),
    claim_id UUID NOT NULL
        REFERENCES claims(id),

    observation_type TEXT NOT NULL DEFAULT 'assertion',
    visibility visibility_scope NOT NULL DEFAULT 'private',

    observed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    source_modified_at TIMESTAMPTZ,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);


CREATE TABLE evaluation_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id UUID NOT NULL
        REFERENCES workspaces(id) ON DELETE CASCADE,

    algorithm TEXT NOT NULL DEFAULT 'BRAID',
    algorithm_version TEXT NOT NULL,
    status evaluation_status NOT NULL DEFAULT 'pending',
    parameters JSONB NOT NULL DEFAULT '{}'::jsonb,

    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);


CREATE TABLE source_dependencies (
    evaluation_run_id UUID NOT NULL
        REFERENCES evaluation_runs(id) ON DELETE CASCADE,
    source_a_id UUID NOT NULL
        REFERENCES sources(id),
    source_b_id UUID NOT NULL
        REFERENCES sources(id),

    dependency_score DOUBLE PRECISION NOT NULL
        CHECK (dependency_score BETWEEN 0 AND 1),
    signal_coverage DOUBLE PRECISION
        CHECK (signal_coverage BETWEEN 0 AND 1),
    components JSONB NOT NULL DEFAULT '{}'::jsonb,

    PRIMARY KEY (evaluation_run_id, source_a_id, source_b_id),
    CHECK (source_a_id <> source_b_id)
);


CREATE TABLE source_scores (
    evaluation_run_id UUID NOT NULL
        REFERENCES evaluation_runs(id) ON DELETE CASCADE,
    source_id UUID NOT NULL
        REFERENCES sources(id),
    reliability_score DOUBLE PRECISION NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    PRIMARY KEY (evaluation_run_id, source_id)
);


CREATE TABLE claim_scores (
    evaluation_run_id UUID NOT NULL
        REFERENCES evaluation_runs(id) ON DELETE CASCADE,
    claim_id UUID NOT NULL
        REFERENCES claims(id),
    support_score DOUBLE PRECISION NOT NULL,
    effective_independent_support DOUBLE PRECISION,
    dependency_cluster_count INTEGER,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    PRIMARY KEY (evaluation_run_id, claim_id)
);


CREATE TABLE snapshots (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id UUID NOT NULL
        REFERENCES workspaces(id) ON DELETE CASCADE,
    evaluation_run_id UUID
        REFERENCES evaluation_runs(id) ON DELETE SET NULL,

    name TEXT,
    observation_cutoff TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);


CREATE INDEX observations_workspace_time_idx
    ON observations (workspace_id, observed_at DESC);

CREATE INDEX observations_source_idx
    ON observations (source_id);

CREATE INDEX observations_claim_idx
    ON observations (claim_id);

CREATE INDEX claims_entity_attribute_idx
    ON claims (
        workspace_id,
        entity_token,
        attribute_token
    );

CREATE INDEX evaluation_runs_workspace_time_idx
    ON evaluation_runs (workspace_id, created_at DESC);