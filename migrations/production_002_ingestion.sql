BEGIN;

-- Provisioned by the control plane, never by the ingestion role or payload.
CREATE TABLE control.organizations (id uuid PRIMARY KEY DEFAULT gen_random_uuid());
CREATE TABLE control.workspaces (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id uuid NOT NULL REFERENCES control.organizations(id)
);
CREATE TABLE control.ingestion_principals (
    principal_id uuid PRIMARY KEY,
    installation_id uuid NOT NULL UNIQUE REFERENCES control.installations(id),
    workspace_id uuid NOT NULL REFERENCES control.workspaces(id),
    enabled boolean NOT NULL DEFAULT true
);
-- Bindings are permanent. Disable a principal rather than reassign its history.
CREATE FUNCTION control.prevent_ingestion_rebinding() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog AS $$
BEGIN
    IF NEW.principal_id <> OLD.principal_id OR
       NEW.installation_id <> OLD.installation_id OR
       NEW.workspace_id <> OLD.workspace_id THEN
        RAISE EXCEPTION 'ingestion identity binding is immutable';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER immutable_ingestion_binding BEFORE UPDATE
ON control.ingestion_principals FOR EACH ROW
EXECUTE FUNCTION control.prevent_ingestion_rebinding();
ALTER TABLE network.evaluation_runs ADD CONSTRAINT evaluation_run_installation_id
    UNIQUE (installation_id, id);
ALTER TABLE control.ingestion_receipts
    ADD COLUMN payload_sha256 bytea CHECK (octet_length(payload_sha256) = 32),
    ADD COLUMN evaluation_run_id uuid,
    ADD CONSTRAINT receipt_run_installation FOREIGN KEY (installation_id, evaluation_run_id)
        REFERENCES network.evaluation_runs(installation_id, id),
    ADD CONSTRAINT receipt_result_pair CHECK
        ((payload_sha256 IS NULL) = (evaluation_run_id IS NULL));
-- Legacy receipts remain recognizable and fail closed; they cannot be retried
-- without a verifiable fingerprint. New receipts are inserted with both fields.
ALTER TABLE control.ingestion_receipts ADD CONSTRAINT receipt_principal
    FOREIGN KEY (installation_id) REFERENCES control.ingestion_principals(installation_id) NOT VALID;
-- Enforce new receipts immediately; provision legacy bindings then VALIDATE
-- CONSTRAINT receipt_principal separately if upgrading populated research data.

CREATE ROLE omneum_ingestion NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE
    NOINHERIT NOREPLICATION NOBYPASSRLS;
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA control, network TO omneum_ingestion;
GRANT SELECT ON control.ingestion_principals, control.workspaces,
    control.consent_grants TO omneum_ingestion;
GRANT SELECT, INSERT ON control.ingestion_receipts TO omneum_ingestion;
GRANT SELECT, INSERT ON network.sources, network.claims TO omneum_ingestion;
GRANT UPDATE (last_seen_at) ON network.sources, network.claims TO omneum_ingestion;
GRANT INSERT ON network.evaluation_runs, network.observations,
    network.source_scores, network.claim_scores, network.source_dependencies TO omneum_ingestion;
GRANT SELECT (id) ON network.evaluation_runs TO omneum_ingestion;
COMMIT;
