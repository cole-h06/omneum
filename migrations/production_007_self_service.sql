BEGIN;

-- A validated account receives a private workspace; no client-selected binding.
-- Identity is an issuer-scoped subject digest, never an email or JWT.
CREATE TABLE control.contributor_accounts (
    identity_sha256 bytea PRIMARY KEY CHECK (octet_length(identity_sha256)=32),
    workspace_id uuid NOT NULL UNIQUE REFERENCES control.workspaces(id),
    enabled boolean NOT NULL DEFAULT true
);
CREATE TABLE control.account_installations (
    installation_id uuid PRIMARY KEY REFERENCES control.installations(id),
    identity_sha256 bytea NOT NULL REFERENCES control.contributor_accounts(identity_sha256),
    withdrawn_at timestamptz
);
CREATE TABLE control.enrollment_budgets (
    identity_sha256 bytea NOT NULL CHECK (octet_length(identity_sha256)=32),
    window_start timestamptz NOT NULL,
    requests integer NOT NULL CHECK (requests BETWEEN 1 AND 60),
    PRIMARY KEY (identity_sha256, window_start)
);

CREATE FUNCTION control.prevent_account_rebinding() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
BEGIN
    IF NEW.identity_sha256 <> OLD.identity_sha256 OR NEW.workspace_id <> OLD.workspace_id THEN
        RAISE EXCEPTION 'account workspace binding is immutable';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER immutable_account_binding BEFORE UPDATE ON control.contributor_accounts
FOR EACH ROW EXECUTE FUNCTION control.prevent_account_rebinding();
CREATE FUNCTION control.prevent_account_installation_rebinding() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
BEGIN
    IF NEW.installation_id <> OLD.installation_id OR NEW.identity_sha256 <> OLD.identity_sha256 OR
       (OLD.withdrawn_at IS NOT NULL AND NEW.withdrawn_at IS DISTINCT FROM OLD.withdrawn_at) THEN
        RAISE EXCEPTION 'installation account binding and withdrawal are immutable';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER immutable_account_installation BEFORE UPDATE ON control.account_installations
FOR EACH ROW EXECUTE FUNCTION control.prevent_account_installation_rebinding();

CREATE ROLE omneum_enrollment NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE
    NOINHERIT NOREPLICATION NOBYPASSRLS;
GRANT USAGE ON SCHEMA control TO omneum_enrollment;
GRANT SELECT, INSERT ON control.organizations, control.workspaces,
    control.installations, control.ingestion_principals, control.consent_grants,
    control.contributor_accounts, control.account_installations,
    control.ingestion_credentials, control.enrollment_budgets TO omneum_enrollment;
GRANT UPDATE(enabled) ON control.ingestion_principals TO omneum_enrollment;
GRANT UPDATE(revoked_at) ON control.consent_grants, control.ingestion_credentials TO omneum_enrollment;
GRANT UPDATE(withdrawn_at) ON control.account_installations TO omneum_enrollment;
GRANT UPDATE(requests) ON control.enrollment_budgets TO omneum_enrollment;
GRANT SELECT ON control.contributor_accounts, control.account_installations TO omneum_ingestion;
GRANT SELECT, DELETE ON control.enrollment_budgets TO omneum_network_operator;
GRANT SELECT ON control.contributor_accounts, control.account_installations TO omneum_network_operator;
GRANT UPDATE(enabled) ON control.contributor_accounts TO omneum_network_operator;

-- Existing operator enrollments remain compatible. Account suspension must also
-- stop already issued credentials, not merely prevent their renewal.
COMMIT;
