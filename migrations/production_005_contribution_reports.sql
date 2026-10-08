BEGIN;
LOCK TABLE network.evaluation_runs, network.sources, network.claims,
    network.observations, network.assertion_observations, network.source_scores,
    network.claim_scores, network.source_dependencies IN ACCESS EXCLUSIVE MODE;

-- Membership and source classification are contributor reports. Shared token
-- rows identify pseudonyms; their legacy source_kind is only a first-report hint.
CREATE TABLE network.reported_sources (
    evaluation_run_id uuid NOT NULL REFERENCES network.evaluation_runs(id) ON DELETE CASCADE,
    source_id uuid NOT NULL REFERENCES network.sources(id),
    source_kind text NOT NULL,
    PRIMARY KEY (evaluation_run_id, source_id)
);
CREATE TABLE network.reported_claims (
    evaluation_run_id uuid NOT NULL REFERENCES network.evaluation_runs(id) ON DELETE CASCADE,
    claim_id uuid NOT NULL REFERENCES network.claims(id),
    PRIMARY KEY (evaluation_run_id, claim_id)
);
-- Recover all historical membership retained by the old schema. Unreferenced
-- historical identities remain intact; their lost run membership is unknowable.
INSERT INTO network.reported_sources
SELECT refs.evaluation_run_id, refs.source_id, s.source_kind
FROM (
    SELECT evaluation_run_id, source_id FROM network.observations
    UNION SELECT evaluation_run_id, source_id FROM network.source_scores
    UNION SELECT evaluation_run_id, source_low_id FROM network.source_dependencies
    UNION SELECT evaluation_run_id, source_high_id FROM network.source_dependencies
) refs JOIN network.sources s ON s.id=refs.source_id;
INSERT INTO network.reported_claims
SELECT o.evaluation_run_id, a.claim_id FROM network.observations o
JOIN network.assertion_observations a ON a.observation_id=o.id
UNION SELECT evaluation_run_id, claim_id FROM network.claim_scores;

ALTER TABLE network.observations ADD CONSTRAINT observation_reported_source
    FOREIGN KEY (evaluation_run_id, source_id)
    REFERENCES network.reported_sources(evaluation_run_id, source_id);
ALTER TABLE network.source_scores ADD CONSTRAINT score_reported_source
    FOREIGN KEY (evaluation_run_id, source_id)
    REFERENCES network.reported_sources(evaluation_run_id, source_id);
ALTER TABLE network.claim_scores ADD CONSTRAINT score_reported_claim
    FOREIGN KEY (evaluation_run_id, claim_id)
    REFERENCES network.reported_claims(evaluation_run_id, claim_id);
ALTER TABLE network.source_dependencies ADD CONSTRAINT dependency_reported_low
    FOREIGN KEY (evaluation_run_id, source_low_id)
    REFERENCES network.reported_sources(evaluation_run_id, source_id);
ALTER TABLE network.source_dependencies ADD CONSTRAINT dependency_reported_high
    FOREIGN KEY (evaluation_run_id, source_high_id)
    REFERENCES network.reported_sources(evaluation_run_id, source_id);

CREATE OR REPLACE FUNCTION network.validate_assertion_observation() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        IF EXISTS (SELECT 1 FROM network.observations WHERE id=OLD.observation_id) THEN
            RAISE EXCEPTION 'assertion observations are immutable' USING ERRCODE='23514';
        END IF;
        RETURN OLD;
    END IF;
    IF TG_OP = 'UPDATE' THEN
        RAISE EXCEPTION 'assertion observations are immutable' USING ERRCODE='23514';
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM network.observations o
        JOIN network.reported_claims c ON c.evaluation_run_id=o.evaluation_run_id
            AND c.claim_id=NEW.claim_id
        WHERE o.id=NEW.observation_id AND o.observation_type='assertion'
    ) THEN
        RAISE EXCEPTION 'assertion subtype requires reported claim and assertion envelope'
            USING ERRCODE='23503';
    END IF;
    RETURN NEW;
END $$;

ALTER TABLE network.evaluation_runs ADD COLUMN dependency_count integer NOT NULL DEFAULT 0
    CHECK (dependency_count >= 0);
UPDATE network.evaluation_runs r SET dependency_count=d.count
FROM (SELECT evaluation_run_id, count(*)::integer AS count
      FROM network.source_dependencies GROUP BY evaluation_run_id) d
WHERE d.evaluation_run_id=r.id;

-- Preserve the approved evidence previously accepted but discarded. Empty
-- historical evidence means unavailable, rather than inventing provenance.
ALTER TABLE network.source_dependencies ADD COLUMN IF NOT EXISTS retrieval_signal double precision;
ALTER TABLE network.source_dependencies ADD COLUMN reported_evidence jsonb NOT NULL DEFAULT '{}'
    CHECK (jsonb_typeof(reported_evidence) = 'object');

GRANT INSERT ON network.reported_sources, network.reported_claims TO omneum_ingestion;
GRANT SELECT (evaluation_run_id, claim_id) ON network.reported_claims TO omneum_ingestion;
GRANT SELECT (evaluation_run_id) ON network.observations TO omneum_ingestion;
GRANT SELECT (installation_id, created_at, source_count, claim_count,
              observation_count, dependency_count) ON network.evaluation_runs TO omneum_ingestion;
COMMIT;
