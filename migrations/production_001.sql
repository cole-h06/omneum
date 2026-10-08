BEGIN;

CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE SCHEMA control;
CREATE SCHEMA network;
CREATE SCHEMA private;

-- PostgreSQL creates "public" by default. For omneum_prod, this schema is
-- intentionally reserved for explicitly published semantic information.

CREATE TYPE network.evaluation_status AS ENUM (
    'pending',
    'running',
    'completed',
    'failed'
);

-- Anonymous installation identity. This is not a user, organization,
-- workspace, or local context-graph identity.
CREATE TABLE control.installations (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    created_at timestamptz NOT NULL DEFAULT now(),
    last_seen_at timestamptz
);

-- Authorization for pseudonymous structural contribution.
CREATE TABLE control.consent_grants (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    installation_id uuid NOT NULL
        REFERENCES control.installations(id) ON DELETE CASCADE,
    scope text NOT NULL,
    consent_version text NOT NULL,
    granted_at timestamptz NOT NULL DEFAULT now(),
    revoked_at timestamptz,
    CHECK (scope = 'research_context_graph'),
    CHECK (revoked_at IS NULL OR revoked_at >= granted_at)
);

CREATE INDEX consent_grants_installation_idx
    ON control.consent_grants (installation_id, granted_at DESC);

-- One receipt per accepted ingestion request. The ingestion API, not local
-- installations, owns writes to these schemas.
CREATE TABLE control.ingestion_receipts (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    installation_id uuid NOT NULL
        REFERENCES control.installations(id),
    idempotency_key text NOT NULL,
    received_at timestamptz NOT NULL DEFAULT now(),
    accepted_at timestamptz,
    UNIQUE (installation_id, idempotency_key)
);

-- Pseudonymous network identities. Tokens must be issued in the network
-- linkage domain; local linkage identities are not copied here.
CREATE TABLE network.sources (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    source_token bytea NOT NULL,
    source_kind text NOT NULL,
    key_version text NOT NULL,
    first_seen_at timestamptz NOT NULL DEFAULT now(),
    last_seen_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (source_token, key_version)
);

CREATE TABLE network.claims (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    claim_token bytea NOT NULL,
    key_version text NOT NULL,
    first_seen_at timestamptz NOT NULL DEFAULT now(),
    last_seen_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (claim_token, key_version)
);

CREATE TABLE network.evaluation_runs (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    installation_id uuid NOT NULL
        REFERENCES control.installations(id),
    evaluator_version text NOT NULL,
    estimator_version text NOT NULL,
    status network.evaluation_status NOT NULL,
    occurred_bucket timestamptz,
    source_count integer NOT NULL CHECK (source_count >= 0),
    claim_count integer NOT NULL CHECK (claim_count >= 0),
    observation_count integer NOT NULL CHECK (observation_count >= 0),
    completed_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX evaluation_runs_installation_time_idx
    ON network.evaluation_runs (installation_id, created_at DESC);

CREATE TABLE network.observations (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    evaluation_run_id uuid NOT NULL
        REFERENCES network.evaluation_runs(id) ON DELETE CASCADE,
    source_id uuid NOT NULL
        REFERENCES network.sources(id),
    claim_id uuid NOT NULL
        REFERENCES network.claims(id),
    observation_type text NOT NULL DEFAULT 'assertion',
    observed_bucket timestamptz,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX observations_source_idx
    ON network.observations (source_id);

CREATE INDEX observations_claim_idx
    ON network.observations (claim_id);

CREATE INDEX observations_run_idx
    ON network.observations (evaluation_run_id);

CREATE TABLE network.source_scores (
    evaluation_run_id uuid NOT NULL
        REFERENCES network.evaluation_runs(id) ON DELETE CASCADE,
    source_id uuid NOT NULL
        REFERENCES network.sources(id),
    reliability_score double precision NOT NULL CHECK (reliability_score >= 0),
    contribution_score double precision,
    PRIMARY KEY (evaluation_run_id, source_id)
);

CREATE TABLE network.claim_scores (
    evaluation_run_id uuid NOT NULL
        REFERENCES network.evaluation_runs(id) ON DELETE CASCADE,
    claim_id uuid NOT NULL
        REFERENCES network.claims(id),
    support_score double precision NOT NULL CHECK (support_score >= 0),
    supporting_source_count integer NOT NULL CHECK (supporting_source_count >= 1),
    estimated_independent_support_count double precision NOT NULL
        CHECK (estimated_independent_support_count >= 1),
    dependency_cluster_count integer
        CHECK (dependency_cluster_count IS NULL OR dependency_cluster_count >= 0),
    dependency_signal_coverage double precision
        CHECK (
            dependency_signal_coverage IS NULL OR
            dependency_signal_coverage BETWEEN 0 AND 1
        ),
    PRIMARY KEY (evaluation_run_id, claim_id)
);

CREATE TABLE network.source_dependencies (
    evaluation_run_id uuid NOT NULL
        REFERENCES network.evaluation_runs(id) ON DELETE CASCADE,
    source_low_id uuid NOT NULL
        REFERENCES network.sources(id),
    source_high_id uuid NOT NULL
        REFERENCES network.sources(id),
    dependency_score double precision NOT NULL
        CHECK (dependency_score BETWEEN 0 AND 1),
    upstream_signal double precision,
    citation_signal double precision,
    assertion_lineage_signal double precision,
    ownership_signal double precision,
    temporal_signal double precision,
    graph_signal double precision,
    signal_coverage double precision
        CHECK (signal_coverage IS NULL OR signal_coverage BETWEEN 0 AND 1),
    estimator_version text NOT NULL,
    CHECK (source_low_id < source_high_id),
    PRIMARY KEY (
        evaluation_run_id,
        source_low_id,
        source_high_id
    )
);

-- Explicitly published semantic information. Rows enter these tables only
-- through a future publication authorization boundary. Evaluation and
-- research contribution never imply publication.
CREATE TABLE public.sources (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    network_source_id uuid
        REFERENCES network.sources(id),
    source_kind text NOT NULL,
    identifier text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE public.claims (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    network_claim_id uuid
        REFERENCES network.claims(id),
    entity_namespace text NOT NULL,
    entity text NOT NULL,
    attribute text NOT NULL,
    value jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);

-- Observation is the atomic publication unit.
CREATE TABLE public.observations (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    source_id uuid NOT NULL
        REFERENCES public.sources(id),
    claim_id uuid NOT NULL
        REFERENCES public.claims(id),
    observation_type text NOT NULL DEFAULT 'assertion',
    published_at timestamptz NOT NULL DEFAULT now()
);

-- No tables are created in private yet. It is reserved exclusively for a
-- future explicitly hosted Omneum Cloud product.

COMMIT;
