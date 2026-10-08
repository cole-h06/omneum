"""Bundled SQLite migrations: versioned, transactional, never rewritten after release."""

APPLICATION_ID = 0x4F4D4E45  # OMNE, local Context Graph (not a production replica).

MIGRATIONS = ((1, """
CREATE TABLE sources (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    deployment_id TEXT NOT NULL,
    key_version INTEGER NOT NULL CHECK (key_version > 0),
    source_token BLOB NOT NULL CHECK (length(source_token) = 64),
    source_kind TEXT NOT NULL,
    identifier TEXT NOT NULL,
    UNIQUE (workspace_id, deployment_id, key_version, source_token),
    UNIQUE (workspace_id, id)
);
CREATE TABLE claims (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    deployment_id TEXT NOT NULL,
    key_version INTEGER NOT NULL CHECK (key_version > 0),
    claim_token BLOB NOT NULL CHECK (length(claim_token) = 64),
    entity_namespace TEXT NOT NULL,
    entity TEXT NOT NULL,
    attribute TEXT NOT NULL,
    value TEXT NOT NULL,
    UNIQUE (workspace_id, deployment_id, key_version, claim_token),
    UNIQUE (workspace_id, id)
);
CREATE TABLE evaluation_runs (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    algorithm TEXT NOT NULL,
    algorithm_version TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status = 'completed'),
    parameters TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (workspace_id, id)
);
CREATE TABLE observations (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    evaluation_run_id TEXT,
    local_observation_id TEXT NOT NULL,
    source_id TEXT NOT NULL,
    claim_id TEXT NOT NULL,
    source_owner_id TEXT,
    observed_at TEXT NOT NULL,
    source_modified_at TEXT,
    upstream_known INTEGER NOT NULL CHECK (upstream_known IN (0, 1)),
    citations_known INTEGER NOT NULL CHECK (citations_known IN (0, 1)),
    parents_known INTEGER NOT NULL CHECK (parents_known IN (0, 1)),
    retrievals_known INTEGER NOT NULL CHECK (retrievals_known IN (0, 1)),
    metadata TEXT NOT NULL,
    dependency_signals TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (workspace_id, id),
    UNIQUE (evaluation_run_id, local_observation_id),
    FOREIGN KEY (workspace_id, source_id) REFERENCES sources (workspace_id, id),
    FOREIGN KEY (workspace_id, claim_id) REFERENCES claims (workspace_id, id),
    FOREIGN KEY (workspace_id, evaluation_run_id) REFERENCES evaluation_runs (workspace_id, id)
);
CREATE TABLE observation_source_references (
    observation_id TEXT NOT NULL REFERENCES observations (id),
    relationship TEXT NOT NULL CHECK (relationship IN ('upstream', 'citation')),
    position INTEGER NOT NULL CHECK (position >= 0),
    source_kind TEXT NOT NULL,
    identifier TEXT NOT NULL,
    PRIMARY KEY (observation_id, relationship, position)
);
CREATE TABLE observation_parents (
    workspace_id TEXT NOT NULL,
    observation_id TEXT NOT NULL,
    position INTEGER NOT NULL CHECK (position >= 0),
    local_parent_id TEXT NOT NULL,
    parent_observation_id TEXT,
    PRIMARY KEY (observation_id, position),
    FOREIGN KEY (workspace_id, observation_id) REFERENCES observations (workspace_id, id),
    FOREIGN KEY (workspace_id, parent_observation_id) REFERENCES observations (workspace_id, id)
);
CREATE TABLE observation_retrievals (
    observation_id TEXT NOT NULL REFERENCES observations (id),
    position INTEGER NOT NULL CHECK (position >= 0),
    local_retrieval_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    resource_id TEXT NOT NULL,
    retrieved_at TEXT NOT NULL,
    fields TEXT NOT NULL,
    PRIMARY KEY (observation_id, position)
);
CREATE TABLE source_scores (
    workspace_id TEXT NOT NULL,
    evaluation_run_id TEXT NOT NULL,
    source_id TEXT NOT NULL,
    reliability_score REAL NOT NULL CHECK (reliability_score BETWEEN 0 AND 1),
    PRIMARY KEY (evaluation_run_id, source_id),
    FOREIGN KEY (workspace_id, evaluation_run_id) REFERENCES evaluation_runs (workspace_id, id),
    FOREIGN KEY (workspace_id, source_id) REFERENCES sources (workspace_id, id)
);
CREATE TABLE claim_scores (
    workspace_id TEXT NOT NULL,
    evaluation_run_id TEXT NOT NULL,
    claim_id TEXT NOT NULL,
    support_score REAL NOT NULL CHECK (support_score >= 0),
    agreement_weight REAL NOT NULL CHECK (agreement_weight BETWEEN 0 AND 1),
    is_attribute_max_support INTEGER NOT NULL CHECK (is_attribute_max_support IN (0, 1)),
    supporting_source_count INTEGER NOT NULL CHECK (supporting_source_count >= 1),
    effective_independent_support REAL NOT NULL CHECK (effective_independent_support >= 1),
    dependency_cluster_count INTEGER,
    dependency_signal_coverage REAL CHECK (dependency_signal_coverage BETWEEN 0 AND 1),
    PRIMARY KEY (evaluation_run_id, claim_id),
    FOREIGN KEY (workspace_id, evaluation_run_id) REFERENCES evaluation_runs (workspace_id, id),
    FOREIGN KEY (workspace_id, claim_id) REFERENCES claims (workspace_id, id)
);
CREATE TABLE claim_support_sources (
    workspace_id TEXT NOT NULL,
    evaluation_run_id TEXT NOT NULL,
    claim_id TEXT NOT NULL,
    source_id TEXT NOT NULL,
    independence REAL NOT NULL CHECK (independence BETWEEN 0 AND 1),
    contribution REAL NOT NULL CHECK (contribution >= 0),
    PRIMARY KEY (evaluation_run_id, claim_id, source_id),
    FOREIGN KEY (evaluation_run_id, claim_id) REFERENCES claim_scores (evaluation_run_id, claim_id),
    FOREIGN KEY (workspace_id, evaluation_run_id) REFERENCES evaluation_runs (workspace_id, id),
    FOREIGN KEY (workspace_id, claim_id) REFERENCES claims (workspace_id, id),
    FOREIGN KEY (workspace_id, source_id) REFERENCES sources (workspace_id, id)
);
CREATE TABLE claim_conflicts (
    workspace_id TEXT NOT NULL,
    evaluation_run_id TEXT NOT NULL,
    claim_id TEXT NOT NULL,
    conflicting_claim_id TEXT NOT NULL,
    support REAL NOT NULL CHECK (support >= 0),
    PRIMARY KEY (evaluation_run_id, claim_id, conflicting_claim_id),
    FOREIGN KEY (evaluation_run_id, claim_id) REFERENCES claim_scores (evaluation_run_id, claim_id),
    FOREIGN KEY (workspace_id, evaluation_run_id) REFERENCES evaluation_runs (workspace_id, id),
    FOREIGN KEY (workspace_id, claim_id) REFERENCES claims (workspace_id, id),
    FOREIGN KEY (workspace_id, conflicting_claim_id) REFERENCES claims (workspace_id, id)
);
CREATE TABLE source_dependencies (
    workspace_id TEXT NOT NULL,
    evaluation_run_id TEXT NOT NULL,
    source_a_id TEXT NOT NULL,
    source_b_id TEXT NOT NULL,
    dependency_score REAL NOT NULL CHECK (dependency_score BETWEEN 0 AND 1),
    signal_coverage REAL NOT NULL CHECK (signal_coverage BETWEEN 0 AND 1),
    components TEXT NOT NULL,
    CHECK (source_a_id < source_b_id),
    PRIMARY KEY (evaluation_run_id, source_a_id, source_b_id),
    FOREIGN KEY (workspace_id, evaluation_run_id) REFERENCES evaluation_runs (workspace_id, id),
    FOREIGN KEY (workspace_id, source_a_id) REFERENCES sources (workspace_id, id),
    FOREIGN KEY (workspace_id, source_b_id) REFERENCES sources (workspace_id, id)
);
CREATE INDEX observations_source ON observations (workspace_id, source_id);
CREATE INDEX observations_claim ON observations (workspace_id, claim_id);
CREATE INDEX observations_run ON observations (evaluation_run_id);
CREATE INDEX observation_parents_parent ON observation_parents (parent_observation_id);
CREATE INDEX source_dependencies_b ON source_dependencies (evaluation_run_id, source_b_id);
"""), (2, """
CREATE TABLE observations_new (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    evaluation_run_id TEXT,
    local_observation_id TEXT,
    source_id TEXT NOT NULL,
    observation_type TEXT NOT NULL DEFAULT 'assertion',
    visibility TEXT NOT NULL DEFAULT 'private',
    source_owner_id TEXT,
    observed_at TEXT NOT NULL,
    source_modified_at TEXT,
    upstream_known INTEGER NOT NULL DEFAULT 0 CHECK (upstream_known IN (0, 1)),
    citations_known INTEGER NOT NULL DEFAULT 0 CHECK (citations_known IN (0, 1)),
    parents_known INTEGER NOT NULL DEFAULT 0 CHECK (parents_known IN (0, 1)),
    retrievals_known INTEGER NOT NULL DEFAULT 0 CHECK (retrievals_known IN (0, 1)),
    metadata TEXT NOT NULL DEFAULT '{}',
    dependency_signals TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (workspace_id, id),
    UNIQUE (evaluation_run_id, local_observation_id),
    FOREIGN KEY (workspace_id, source_id) REFERENCES sources (workspace_id, id),
    FOREIGN KEY (workspace_id, evaluation_run_id) REFERENCES evaluation_runs (workspace_id, id)
);
INSERT INTO observations_new (id, workspace_id, evaluation_run_id, local_observation_id, source_id, source_owner_id, observed_at, source_modified_at, upstream_known, citations_known, parents_known, retrievals_known, metadata, dependency_signals, created_at)
SELECT id, workspace_id, evaluation_run_id, local_observation_id, source_id, source_owner_id, observed_at, source_modified_at, upstream_known, citations_known, parents_known, retrievals_known, metadata, dependency_signals, created_at FROM observations;
CREATE TABLE assertion_observations (
    observation_id TEXT PRIMARY KEY REFERENCES observations (id) ON DELETE CASCADE,
    claim_id TEXT NOT NULL REFERENCES claims (id)
);
INSERT INTO assertion_observations SELECT id, claim_id FROM observations;
DROP TABLE observations;
ALTER TABLE observations_new RENAME TO observations;
CREATE INDEX observations_source ON observations (workspace_id, source_id);
CREATE INDEX observations_run ON observations (evaluation_run_id);
CREATE INDEX assertion_observations_claim ON assertion_observations (claim_id);
CREATE TRIGGER assertion_observations_valid BEFORE INSERT ON assertion_observations
WHEN NOT EXISTS (
    SELECT 1 FROM observations o JOIN claims c ON c.id=NEW.claim_id
    WHERE o.id=NEW.observation_id AND o.observation_type='assertion'
      AND o.workspace_id=c.workspace_id
)
BEGIN SELECT RAISE(ABORT, 'assertion subtype requires an assertion envelope and same-workspace claim'); END;
CREATE TRIGGER assertion_observations_immutable BEFORE UPDATE ON assertion_observations
BEGIN SELECT RAISE(ABORT, 'assertion observations are immutable'); END;
CREATE TRIGGER assertion_observations_no_delete BEFORE DELETE ON assertion_observations
WHEN EXISTS (SELECT 1 FROM observations WHERE id=OLD.observation_id)
BEGIN SELECT RAISE(ABORT, 'assertion observations are immutable'); END;
CREATE TRIGGER observations_immutable BEFORE UPDATE OF
    id, workspace_id, source_id, observation_type, visibility, observed_at, metadata,
    local_observation_id, source_owner_id, source_modified_at, upstream_known,
    citations_known, parents_known, retrievals_known, dependency_signals, created_at
ON observations
BEGIN SELECT RAISE(ABORT, 'observations are immutable'); END;
CREATE TRIGGER assertion_claim_workspace BEFORE UPDATE OF workspace_id ON claims
WHEN EXISTS (
    SELECT 1 FROM assertion_observations a JOIN observations o ON o.id=a.observation_id
    WHERE a.claim_id=OLD.id AND o.workspace_id<>NEW.workspace_id
)
BEGIN SELECT RAISE(ABORT, 'assertion claim cannot cross workspaces'); END;
CREATE VIEW assertion_observation_envelopes AS
SELECT o.*, a.claim_id FROM observations o
JOIN assertion_observations a ON a.observation_id=o.id
WHERE o.observation_type='assertion';
"""), (3, """
-- SQLite cannot defer custom triggers. Each assertion creates a protected
-- requirement whose FK is checked only when the enclosing transaction commits.
CREATE TABLE assertion_observation_requirements (
    observation_id TEXT NOT NULL PRIMARY KEY
        REFERENCES observations(id) ON DELETE CASCADE,
    FOREIGN KEY (observation_id) REFERENCES assertion_observations(observation_id)
        DEFERRABLE INITIALLY DEFERRED
);
CREATE TRIGGER assertion_requirement_valid BEFORE INSERT ON assertion_observation_requirements
WHEN NOT EXISTS (SELECT 1 FROM observations
                 WHERE id=NEW.observation_id AND observation_type='assertion')
BEGIN SELECT RAISE(ABORT, 'assertion requirement needs an assertion envelope'); END;
CREATE TRIGGER assertion_requirement_immutable BEFORE UPDATE ON assertion_observation_requirements
BEGIN SELECT RAISE(ABORT, 'assertion requirements are immutable'); END;
CREATE TRIGGER assertion_requirement_no_delete BEFORE DELETE ON assertion_observation_requirements
WHEN EXISTS (SELECT 1 FROM observations WHERE id=OLD.observation_id)
BEGIN SELECT RAISE(ABORT, 'assertion requirements cannot be removed independently'); END;
CREATE TRIGGER observations_require_assertion AFTER INSERT ON observations
WHEN NEW.observation_type='assertion'
BEGIN
    INSERT INTO assertion_observation_requirements(observation_id) VALUES (NEW.id);
END;
-- FK validation in the migration runner rejects existing orphan assertions.
INSERT INTO assertion_observation_requirements(observation_id)
SELECT id FROM observations WHERE observation_type='assertion';
"""))
