BEGIN;
LOCK TABLE public.observations IN ACCESS EXCLUSIVE MODE;
CREATE TABLE IF NOT EXISTS public.assertion_observations (
    observation_id uuid PRIMARY KEY REFERENCES public.observations(id) ON DELETE CASCADE,
    claim_id uuid NOT NULL REFERENCES public.claims(id)
);
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.columns
               WHERE table_schema='public' AND table_name='observations' AND column_name='claim_id') THEN
        -- Retain IDs, provenance, timestamps and every other envelope field.
        UPDATE public.observations SET observation_type='assertion';
        INSERT INTO public.assertion_observations SELECT id, claim_id FROM public.observations;
        ALTER TABLE public.observations DROP COLUMN claim_id;
    END IF;
END $$;
CREATE INDEX IF NOT EXISTS assertion_observations_claim_idx ON public.assertion_observations(claim_id);
CREATE OR REPLACE FUNCTION public.validate_assertion_observation() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        IF EXISTS (SELECT 1 FROM public.observations WHERE id=OLD.observation_id) THEN
            RAISE EXCEPTION 'assertion observations are immutable' USING ERRCODE='23514';
        END IF;
        RETURN OLD;
    END IF;
    IF TG_OP = 'UPDATE' THEN
        RAISE EXCEPTION 'assertion observations are immutable' USING ERRCODE='23514';
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM public.observations o JOIN public.claims c ON c.id=NEW.claim_id
        WHERE o.id=NEW.observation_id AND o.observation_type='assertion'
          AND o.workspace_id=c.workspace_id
        FOR KEY SHARE OF o, c
    ) THEN
        RAISE EXCEPTION 'assertion subtype requires a valid assertion envelope and claim' USING ERRCODE='23503';
    END IF;
    RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS assertion_observations_valid ON public.assertion_observations;
CREATE TRIGGER assertion_observations_valid BEFORE INSERT OR UPDATE OR DELETE ON public.assertion_observations
FOR EACH ROW EXECUTE FUNCTION public.validate_assertion_observation();
CREATE OR REPLACE FUNCTION public.immutable_observation() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'observations are immutable' USING ERRCODE='23514';
END $$;
DROP TRIGGER IF EXISTS observations_immutable ON public.observations;
CREATE TRIGGER observations_immutable BEFORE UPDATE ON public.observations
FOR EACH ROW EXECUTE FUNCTION public.immutable_observation();
CREATE OR REPLACE VIEW public.assertion_observation_envelopes AS
SELECT o.*, a.claim_id FROM public.observations o
JOIN public.assertion_observations a ON a.observation_id=o.id WHERE o.observation_type='assertion';
CREATE OR REPLACE FUNCTION public.validate_assertion_claim_workspace() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF EXISTS (SELECT 1 FROM public.assertion_observations a
               JOIN public.observations o ON o.id=a.observation_id
               WHERE a.claim_id=OLD.id AND o.workspace_id<>NEW.workspace_id) THEN
        RAISE EXCEPTION 'assertion claim cannot cross workspaces' USING ERRCODE='23503';
    END IF;
    RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS assertion_claim_workspace ON public.claims;
CREATE TRIGGER assertion_claim_workspace BEFORE UPDATE OF workspace_id ON public.claims
FOR EACH ROW EXECUTE FUNCTION public.validate_assertion_claim_workspace();
COMMIT;
