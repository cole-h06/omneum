BEGIN;

CREATE TABLE control.ingestion_credentials (
    id uuid PRIMARY KEY,
    principal_id uuid NOT NULL REFERENCES control.ingestion_principals(principal_id),
    token_sha256 bytea NOT NULL UNIQUE CHECK (octet_length(token_sha256) = 32),
    issued_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    expires_at timestamptz NOT NULL,
    revoked_at timestamptz,
    CHECK (expires_at > issued_at),
    CHECK (revoked_at IS NULL OR revoked_at >= issued_at)
);
CREATE INDEX ingestion_credentials_principal_idx ON control.ingestion_credentials(principal_id);

CREATE FUNCTION control.prevent_credential_rebinding() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog AS $$
BEGIN
    IF NEW.id <> OLD.id OR NEW.principal_id <> OLD.principal_id OR
       NEW.token_sha256 <> OLD.token_sha256 OR NEW.issued_at <> OLD.issued_at OR
       NEW.expires_at <> OLD.expires_at OR
       (OLD.revoked_at IS NOT NULL AND NEW.revoked_at IS DISTINCT FROM OLD.revoked_at) THEN
        RAISE EXCEPTION 'issued credentials are immutable except initial revocation';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER immutable_credential BEFORE UPDATE ON control.ingestion_credentials
FOR EACH ROW EXECUTE FUNCTION control.prevent_credential_rebinding();

-- Shared across API workers, replicas, restarts and credential rotations.
CREATE TABLE control.network_admission_budgets (
    principal_id uuid NOT NULL REFERENCES control.ingestion_principals(principal_id),
    window_start timestamptz NOT NULL,
    requests integer NOT NULL CHECK (requests BETWEEN 1 AND 100000),
    PRIMARY KEY (principal_id, window_start)
);
GRANT SELECT ON control.ingestion_credentials TO omneum_ingestion;
GRANT SELECT, INSERT ON control.network_admission_budgets TO omneum_ingestion;
GRANT UPDATE (requests) ON control.network_admission_budgets TO omneum_ingestion;

-- Operators authenticate through PostgreSQL; there is no public registration API.
CREATE ROLE omneum_network_operator NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE
    NOINHERIT NOREPLICATION NOBYPASSRLS;
GRANT USAGE ON SCHEMA control TO omneum_network_operator;
GRANT SELECT, INSERT ON control.organizations, control.workspaces,
    control.installations, control.ingestion_principals, control.consent_grants
    TO omneum_network_operator;
GRANT UPDATE (enabled) ON control.ingestion_principals TO omneum_network_operator;
GRANT UPDATE (revoked_at) ON control.consent_grants TO omneum_network_operator;
GRANT SELECT ON control.ingestion_credentials TO omneum_network_operator;
GRANT INSERT (id, principal_id, token_sha256, expires_at) ON control.ingestion_credentials
    TO omneum_network_operator;
GRANT UPDATE (revoked_at) ON control.ingestion_credentials TO omneum_network_operator;
GRANT SELECT, DELETE ON control.network_admission_budgets TO omneum_network_operator;
COMMIT;
