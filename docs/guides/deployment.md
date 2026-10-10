
# Network Deployment

The Omneum Network runs an HTTPS ingestion API backed by PostgreSQL and a protected VOPRF evaluator.

Local MCP installations do not require Network infrastructure. Contributors connect through the authenticated ingestion API when Network contribution is explicitly enabled. They never receive PostgreSQL credentials.

For local installation, see [Installation](installation.md). For administrator-managed Linux MCP services, see [`deploy/README.md`](../../deploy/README.md).

## Architecture

```text
Local MCP contributor
        │
        │ HTTPS
        ▼
Network API (UID 10001)
        │
        ├── PostgreSQL
        │
        └── Unix socket
                │
                ▼
          omneumd (UID 10002)
                │
                ▼
          Network VOPRF key
```

`omneum.transport.network.NetworkHTTPApp` implements the HTTP application. `python -m omneum.network_api` starts Uvicorn on port `8443` with forwarded headers disabled.

The API uses `IngestionService` for authenticated ingestion and a long-lived `EvaluationService` for VOPRF requests. Evaluation workers are bounded and drained during ASGI shutdown.

`omneumd` owns the Network private key. The API verifies the daemon's Unix-socket peer UID and pinned public key before accepting evaluations. The private key is never mounted into the API container.

The Network and local-domain public keys must be distinct.

## Docker Compose

`compose.yaml` provides a disposable Network deployment with PostgreSQL, the evaluator, and the HTTPS API.

Run from the repository root:

```bash
docker build -t omneum-network:local .
docker compose up -d --wait
docker compose run --rm smoke
```

Compose binds HTTPS to localhost and does not publish PostgreSQL. The setup service generates test credentials and a Network VOPRF key in named volumes. The TLS certificate is valid for seven days.

`enroll-test` provisions a disposable contributor. Its credential is written to a private client volume that the API cannot access.

The API does not read the repository `.env` or mount operator credentials.

### Restart verification

```bash
docker compose stop
docker compose start --wait
docker compose run --rm smoke

docker compose restart evaluator network-api
docker compose run --rm smoke
```

`deploy/network/smoke.py` exercises HTTPS authentication, VOPRF proof verification, authorized ingestion, and PostgreSQL persistence.

The smoke client reuses its idempotency key after restart. Repeated ingestion must not create duplicate records.

### Cleanup

```bash
docker compose down --volumes
```

This deletes the disposable database, keys, and credentials. Do not use these volumes in production.

Incomplete provisioning fails instead of replacing existing keys. Remove the disposable volumes before retrying a failed test bootstrap.

## PostgreSQL

The Network API connects as `omneum_ingestion`. Database initialization runs separately with administrator privileges.

Apply these migrations in order:

```text
migrations/production_001.sql
migrations/production_002_ingestion.sql
migrations/production_003_dependency_evidence.sql
migrations/production_003_observation_subtypes.sql
migrations/production_004_assertion_subtype_integrity.sql
migrations/production_004_retrieval_signal.sql
migrations/production_005_contribution_reports.sql
migrations/production_006_credentials.sql
```

`production_002_context_graph.sql` belongs to another schema path. Network ingestion does not require Apache AGE.

API startup never applies migrations or grants contributor consent.

### Database transport

Remote PostgreSQL connections require `sslmode=verify-full` with a trusted CA.

A libpq service file must specify `sslmode=verify-full` explicitly. Unix sockets and loopback connections are permitted for local testing.

Startup checks the effective privileges of `omneum_ingestion`, not only its role name. Elevated role memberships or ownership of application tables and schemas cause startup to fail.

The ingestion role cannot issue credentials or modify contributor enrollment.

## Configuration

Required settings can be supplied directly or through corresponding `_FILE` variables. The API rejects configurations that provide both forms.

| Variable | Value |
|---|---|
| `OMNEUM_NETWORK_DEPLOYMENT_ID` | Network identity (`urn:uuid:...`) |
| `OMNEUM_NETWORK_KEY_VERSION` | Positive VOPRF key version |
| `OMNEUM_NETWORK_PUBLIC_KEY` | Pinned unpadded base64url Network public key |
| `OMNEUM_LOCAL_PUBLIC_KEY` | Distinct local-domain public key |
| `OMNEUM_NETWORK_DATABASE_DSN` | PostgreSQL DSN for `omneum_ingestion` |
| `OMNEUM_NETWORK_TLS_CERT` | HTTPS certificate path |
| `OMNEUM_NETWORK_TLS_KEY` | HTTPS private-key path |

Optional settings:

| Variable | Default |
|---|---|
| `OMNEUM_NETWORK_REQUESTS_PER_MINUTE` | `600` |
| `OMNEUM_DAEMON_SOCKET` | `/run/omneum/eval.sock` |
| `OMNEUM_DAEMON_UID` | `10002` |

The public HTTPS endpoint requires a trusted certificate. Configure additional edge/IP admission limits before exposing the service.

Never commit private keys, database credentials, or secret values files.

## Kubernetes

The Helm chart is located at:

```text
deploy/helm/omneum-network
```

It deploys the API and evaluator using the same entrypoints as Compose. PostgreSQL must already exist; the chart does not create databases or apply migrations.

### Secrets

Create these Kubernetes Secrets using your existing secret-management system:

| Secret | Keys |
|---|---|
| `omneum-network-api` | `database-dsn`, `tls.crt`, `tls.key` |
| `omneum-network-evaluator` | `voprf.key` |

`voprf.key` contains the raw 32-byte VOPRF private key.

The chart copies the scalar into a daemon-only memory volume. API TLS volumes contain only the TLS certificate and key.

The API must not receive the VOPRF scalar or operator database identity.

### Install

Create `/path/to/operator-values.yaml` outside source control with the deployment ID, key version, pinned public keys, and image reference.

```bash
helm lint deploy/helm/omneum-network \
  -f /path/to/operator-values.yaml

helm template omneum-network deploy/helm/omneum-network \
  -f /path/to/operator-values.yaml \
  > /tmp/omneum-network.yaml

helm upgrade --install omneum-network \
  deploy/helm/omneum-network \
  -f /path/to/operator-values.yaml
```

Use an immutable image digest for production releases.

The deployment requires production-specific verification of pod isolation and evaluator key permissions. Successful template rendering does not establish runtime isolation.

## Contributor enrollment

Network credentials are issued by an operator. There is no public registration endpoint.

Run `python -m omneum.network_operator` from a trusted host with the Network package and `psycopg` installed.

The operator database identity must not be mounted in API pods.

### Operator role

`production_006_credentials.sql` creates credential storage, shared admission budgets, and the `omneum_network_operator` role.

For an existing administrator-provisioned login named `network_control_plane`:

```bash
export PGSERVICEFILE=/secure/operator/pg_service.conf
export PGSERVICE=network_migrations

psql -X -v ON_ERROR_STOP=1 \
  -f migrations/production_006_credentials.sql

psql -X -v ON_ERROR_STOP=1 \
  -c 'GRANT omneum_network_operator TO network_control_plane;'
```

The operator login must inherit `omneum_network_operator` or select it through libpq `options`.

Do not grant this role to `omneum_ingestion`.

### Operator credentials

Store the operator DSN in a private file with mode `0600`. Remote connections must use `sslmode=verify-full`.

```bash
export OMNEUM_NETWORK_OPERATOR_DSN_FILE=/secure/operator/network-operator.dsn

install -d -m 700 /secure/operator/issued
```

The CLI also accepts `OMNEUM_NETWORK_OPERATOR_DSN`, but not a DSN argument. Use the mounted file for normal administration.

### Create a workspace

```bash
python -m omneum.network_operator create-workspace
```

Copy the returned UUID into `NETWORK_WORKSPACE_ID`.

```bash
export NETWORK_WORKSPACE_ID="<workspace-uuid>"
```

### Enroll

Verify the contributor's consent before issuing a credential.

```bash
python -m omneum.network_operator enroll \
  --workspace-id "$NETWORK_WORKSPACE_ID" \
  --consent-version consent-2026-10 \
  --confirm-consent \
  --expires-days 90 \
  --output /secure/operator/issued/contributor-a.token
```

`enroll` creates a principal-bound installation, records `research_context_graph` consent, and issues a credential. Omitting `--confirm-consent` fails.

The command returns `principal_id`, `installation_id`, `credential_id`, and `expires_at`.

The token is written to the specified file, not stdout. Files are created exclusively with mode `0600`; existing files and symlinks are rejected. The parent directory must be private.

Deliver the token through an approved private channel and delete the operator's delivery copy afterward.

PostgreSQL stores a domain-separated SHA-256 digest rather than the raw credential. Tokens contain a UUID selector and 256 bits of random secret material.

Credential expiry defaults to 90 days and supports 1–365 days.

## Credential management

### Rotate

Issue a new credential for the existing principal:

```bash
export NETWORK_PRINCIPAL_ID="<principal-uuid>"

python -m omneum.network_operator issue \
  --principal-id "$NETWORK_PRINCIPAL_ID" \
  --expires-days 90 \
  --output /secure/operator/issued/contributor-a-rotated.token
```

Deliver the replacement before revoking the old credential.

Rotation preserves the installation binding and its existing ingestion history.

### Revoke

```bash
export NETWORK_CREDENTIAL_ID="<credential-uuid>"

python -m omneum.network_operator revoke-credential \
  --credential-id "$NETWORK_CREDENTIAL_ID"
```

Revocation is effective without restarting the API.

To disable the contributor entirely:

```bash
python -m omneum.network_operator revoke-contributor \
  --principal-id "$NETWORK_PRINCIPAL_ID"
```

This also revokes active consent. Previously accepted reports remain associated with their installation.

Revoked or expired credentials cannot be reactivated.

### Admission history

```bash
python -m omneum.network_operator prune-quotas \
  --retention-days 2
```

Run quota pruning periodically. Current admission windows are retained.

Admission budgets are stored in PostgreSQL and shared across API instances. Rotating credentials does not reset a principal's budget.

### Concurrent operations

Credential revocation and ingestion synchronize on the installation lock.

Ingestion reauthenticates after acquiring that lock. A completed revocation prevents later pending ingestion using the revoked credential from committing.

If credential issuance fails, inspect the reserved output file and database before retrying. A failed command may leave a file whose credential commit outcome is uncertain.

Do not overwrite that file or automatically issue another credential.

Database or admission-store failures deny Network requests. Local MCP evaluation remains available independently.

## Upgrades

Apply required migrations before starting a Network API version that depends on them.

Remove the obsolete singleton-token configuration:

```text
OMNEUM_NETWORK_API_TOKEN
OMNEUM_NETWORK_PRINCIPAL_ID
```

Remove their `_FILE` variants as well. The API does not support static-token fallback.

Use `issue` to provision a credential for an existing enabled contributor with active consent. New contributors use `enroll`.

For disposable Compose installations:

```bash
docker compose down --volumes
docker compose up -d --wait
docker compose run --rm smoke
```

Production PostgreSQL databases must be migrated in place. Never delete production volumes as part of this procedure.

## Verification

Run the repository's Network tests before deploying a modified API:

```bash
uvx --from uv==0.12.10 uv run --locked --python 3.13 \
  pytest -q \
  tests/test_network_bootstrap.py \
  tests/test_network_enrollment.py
```

For the container integration check:

```bash
docker compose up -d --wait
docker compose run --rm smoke
```

For Kubernetes manifests:

```bash
helm lint deploy/helm/omneum-network \
  -f /path/to/operator-values.yaml
```

The local and hosted security audit also exercised the protected evaluator, database privilege checks, Docker Compose startup, and Linux cross-UID isolation.

These checks do not replace production provisioning or runtime verification.

See [Local and Hosted Security Audit](../security-audit-local-hosted.md) for the recorded findings and remaining production requirements.