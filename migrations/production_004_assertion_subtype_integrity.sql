BEGIN;
LOCK TABLE network.observations, network.assertion_observations IN ACCESS EXCLUSIVE MODE;
-- Never fabricate assertion semantics for an existing orphan envelope.
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM network.observations o
               LEFT JOIN network.assertion_observations a ON a.observation_id=o.id
               WHERE o.observation_type='assertion' AND a.observation_id IS NULL) THEN
        RAISE EXCEPTION 'existing assertion observations are missing subtype rows' USING ERRCODE='23514';
    END IF;
END $$;
CREATE OR REPLACE FUNCTION network.require_assertion_subtype() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    -- Query final transaction state, including envelopes deleted before commit.
    IF EXISTS (SELECT 1 FROM network.observations o
               LEFT JOIN network.assertion_observations a ON a.observation_id=o.id
               WHERE o.id=NEW.id AND o.observation_type='assertion'
                 AND a.observation_id IS NULL) THEN
        RAISE EXCEPTION 'assertion observation requires an assertion subtype row' USING ERRCODE='23514';
    END IF;
    RETURN NULL;
END $$;
DROP TRIGGER IF EXISTS observations_require_assertion ON network.observations;
CREATE CONSTRAINT TRIGGER observations_require_assertion
AFTER INSERT ON network.observations DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION network.require_assertion_subtype();
-- TRUNCATE bypasses row DELETE guards; reject truncation that strands envelopes.
CREATE OR REPLACE FUNCTION network.guard_assertion_subtype_truncate() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF EXISTS (SELECT 1 FROM network.observations o
               LEFT JOIN network.assertion_observations a ON a.observation_id=o.id
               WHERE o.observation_type='assertion' AND a.observation_id IS NULL) THEN
        RAISE EXCEPTION 'cannot truncate assertion subtypes while assertion envelopes remain' USING ERRCODE='23514';
    END IF;
    RETURN NULL;
END $$;
DROP TRIGGER IF EXISTS assertion_subtypes_truncate ON network.assertion_observations;
CREATE TRIGGER assertion_subtypes_truncate AFTER TRUNCATE ON network.assertion_observations
FOR EACH STATEMENT EXECUTE FUNCTION network.guard_assertion_subtype_truncate();
LOCK TABLE public.observations, public.assertion_observations IN ACCESS EXCLUSIVE MODE;
-- Never fabricate assertion semantics for an existing orphan envelope.
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM public.observations o
               LEFT JOIN public.assertion_observations a ON a.observation_id=o.id
               WHERE o.observation_type='assertion' AND a.observation_id IS NULL) THEN
        RAISE EXCEPTION 'existing assertion observations are missing subtype rows' USING ERRCODE='23514';
    END IF;
END $$;
CREATE OR REPLACE FUNCTION public.require_assertion_subtype() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    -- Query final transaction state, including envelopes deleted before commit.
    IF EXISTS (SELECT 1 FROM public.observations o
               LEFT JOIN public.assertion_observations a ON a.observation_id=o.id
               WHERE o.id=NEW.id AND o.observation_type='assertion'
                 AND a.observation_id IS NULL) THEN
        RAISE EXCEPTION 'assertion observation requires an assertion subtype row' USING ERRCODE='23514';
    END IF;
    RETURN NULL;
END $$;
DROP TRIGGER IF EXISTS observations_require_assertion ON public.observations;
CREATE CONSTRAINT TRIGGER observations_require_assertion
AFTER INSERT ON public.observations DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION public.require_assertion_subtype();
-- TRUNCATE bypasses row DELETE guards; reject truncation that strands envelopes.
CREATE OR REPLACE FUNCTION public.guard_assertion_subtype_truncate() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF EXISTS (SELECT 1 FROM public.observations o
               LEFT JOIN public.assertion_observations a ON a.observation_id=o.id
               WHERE o.observation_type='assertion' AND a.observation_id IS NULL) THEN
        RAISE EXCEPTION 'cannot truncate assertion subtypes while assertion envelopes remain' USING ERRCODE='23514';
    END IF;
    RETURN NULL;
END $$;
DROP TRIGGER IF EXISTS assertion_subtypes_truncate ON public.assertion_observations;
CREATE TRIGGER assertion_subtypes_truncate AFTER TRUNCATE ON public.assertion_observations
FOR EACH STATEMENT EXECUTE FUNCTION public.guard_assertion_subtype_truncate();
-- The commit-time constraint runs under the ingestion role.
GRANT SELECT (observation_id) ON network.assertion_observations TO omneum_ingestion;
COMMIT;
