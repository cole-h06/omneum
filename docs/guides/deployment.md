# Omneum-hosted Network deployment

This infrastructure runs the Network API for Omneum operators. Standalone local
MCP installation remains `omneum install` and `omneum-server`; contributors do
not install Docker, Kubernetes, Helm or PostgreSQL and receive no database
credentials. The local Context Graph operates independently of the Network.
See [MCP contribution setup](configuration.md#enable-network-contribution-mcp) for the optional local adapter
and production provisioning requirements.

The ASGI application is `omneum.transport.network.NetworkHTTPApp`. The minimal
entrypoint `python -m omneum.network_api` constructs that application and the
existing `IngestionService`, then serves HTTPS on port 8443 with Uvicorn.
Forwarded headers are disabled. There is no second HTTP implementation.

The protected Rust `omneumd` owns the Network private key under UID 10002. The
API runs as UID 10001, verifies daemon UID and the configured public-key pin on
Unix-socket connections, and never mounts the private key. The local-domain
public key must be valid and distinct from the Network key. One long-lived
`EvaluationService` owns a bounded worker pool; ASGI shutdown drains it. The
daemon handles SIGTERM and preserves its provisioned key across restarts.

The image builds the native RFC 9497 extension and production daemon from
`Cargo.lock`. Python runtime requirements are pinned in
`deploy/network/requirements.txt`, exported from the existing `uv.lock` plus
Network-only psycopg 3.3.6. MCP dependencies remain unchanged. Refresh that file
when updating the Python lock; do not include benchmark dependency groups.
Base images use version tags; immutable registry digests should be recorded by
the operator for released images. This checkout has not yet had a container build
verified (see validation status below).

## Disposable local integration

Run from the repository root on a Docker host with Compose v2:

```sh
env -u OMNEUM_TEST_POSTGRES_DSN -u OMNEUM_INGESTION_TEST_ADMIN_DSN .venv/bin/python -m pytest tests -q
docker build -t omneum-network:local .
docker compose up -d --wait
docker compose run --rm smoke
docker compose stop
docker compose start --wait
docker compose run --rm smoke
docker compose restart evaluator network-api
docker compose run --rm smoke
# Remove only this stack's disposable database, keys and credentials:
docker compose down --volumes
```

Compose binds HTTPS only to localhost, publishes no PostgreSQL port, and uses
`omneum_network_test`. The setup service generates random database passwords,
independent Network key and a seven-day test TLS certificate in named volumes.
A separate operator-only `enroll-test` service enrolls a disposable consenting
contributor and issues its credential into the private client volume. The API
never mounts that volume or the administrator/operator credentials. It never reads the repository `.env`. Incomplete
provisioning fails rather than silently rotating keys; remove these disposable
volumes and retry. Do not reuse these test credentials or database in production.
The smoke check verifies HTTPS startup, rejected authentication, real VOPRF proof
verification, authorized ingestion, idempotent replay and persisted rows. Reusing
its fixed idempotency key after restarting verifies persistence and key stability.

PostgreSQL initializes the following existing migrations, in this exact order:

1. `production_001.sql`
2. `production_002_ingestion.sql`
3. `production_003_dependency_evidence.sql`
4. `production_003_observation_subtypes.sql`
5. `production_004_assertion_subtype_integrity.sql`
6. `production_004_retrieval_signal.sql`
7. `production_005_contribution_reports.sql`
8. `production_006_credentials.sql`

`production_002_context_graph.sql` belongs to another schema path and is not
required by ingestion. Network ingestion does not require Apache AGE. Database
initialization uses a disposable administrator; request processing connects
as the restricted `omneum_ingestion` role. Production migrations and control
plane enrollment (principal, installation, workspace, consent) must be performed
separately by an operator. API startup never applies migrations or grants consent.

## Production configuration and Helm

There was no existing Helm chart in this checkout. The chart at
`deploy/helm/omneum-network` uses the same image, API entrypoint and evaluator
command as Compose. PostgreSQL is externally managed; the chart does not create
or migrate a production database. The API uses one database-backed credential
authority shared by HTTP admission and ingestion. Each credential maps to an
independently enrolled immutable principal/installation, with enabled enrollment,
active consent, expiry and revocation checked on every authentication. No raw
bearer tokens or principal IDs are configured in the API environment or Helm
values. PostgreSQL admission counters enforce per-principal budgets across API
instances, restarts and overlapping/rotated credentials. Daily ingestion quotas
remain tied to the permanent installation binding.

The API accepts each required setting as an environment variable or a `_FILE`
path, but rejects configuring both:

| Setting | Value |
| --- | --- |
| `OMNEUM_NETWORK_DEPLOYMENT_ID` | `urn:uuid:...` Network deployment identity |
| `OMNEUM_NETWORK_KEY_VERSION` | Active positive key version |
| `OMNEUM_NETWORK_PUBLIC_KEY` | Pinned unpadded base64url Network public key |
| `OMNEUM_LOCAL_PUBLIC_KEY` | Distinct unpadded base64url local-domain public key |
| `OMNEUM_NETWORK_DATABASE_DSN` | PostgreSQL DSN for `omneum_ingestion` |
| `OMNEUM_NETWORK_TLS_CERT` / `OMNEUM_NETWORK_TLS_KEY` | TLS file paths |

Optional settings: `OMNEUM_NETWORK_REQUESTS_PER_MINUTE` (600),
`OMNEUM_DAEMON_SOCKET` (`/run/omneum/eval.sock`) and `OMNEUM_DAEMON_UID` (10002).
Use PostgreSQL TLS and a trusted HTTPS certificate in production. The local HTTPS
probe trusts the mounted certificate for the container's loopback listener;
contributors still verify the public HTTPS endpoint's certificate and hostname. Add edge/IP admission
limits at the deployment boundary. Never commit credentials, scalar keys or secret
values files.

Create Kubernetes Secrets through your existing secret-management system:
`omneum-network-api` with `database-dsn`, `tls.crt`, `tls.key`, and
`omneum-network-evaluator` with raw 32-byte `voprf.key`. The chart copies the
scalar into a daemon-only memory volume with the ownership and permissions
required by the protected daemon. API TLS volumes contain only TLS entries.

Create a public operator values file outside source control with `deploymentId`,
`keyVersion`, `networkPublicKey`, `localPublicKey`, and the image
repository and immutable release tag. Then:

```sh
helm lint deploy/helm/omneum-network -f /path/to/operator-values.yaml
helm template omneum-network deploy/helm/omneum-network -f /path/to/operator-values.yaml > /tmp/omneum-network.yaml
helm upgrade --install omneum-network deploy/helm/omneum-network -f /path/to/operator-values.yaml
```

Do not connect these validation commands to `omneum_prod`.

## Operator-controlled contributor enrollment

There is no public self-registration or management HTTP endpoint. Run the
operator CLI from a trusted host with the Network package and its psycopg driver.
Only this host receives an operator database identity; contributors receive only
their API credential and enable it through ordinary MCP configuration.

Apply `production_006_credentials.sql` after the existing Network migrations.
Use an administrator's private PostgreSQL service file, keeping passwords out of
arguments and shell history. For an existing administrator-provisioned login
`network_control_plane`, the exact migration/role commands are:

```sh
export PGSERVICEFILE=/secure/operator/pg_service.conf
export PGSERVICE=network_migrations
psql -X -v ON_ERROR_STOP=1 -f migrations/production_006_credentials.sql
psql -X -v ON_ERROR_STOP=1 -c 'GRANT omneum_network_operator TO network_control_plane;'
```

Provision this login through your normal PostgreSQL identity/TLS system; it must
inherit the operator role or explicitly select it via libpq `options`. The API's
`omneum_ingestion` login must never receive that membership. Migration 006 creates
hash-only credential storage, immutable credential bindings, shared admission
budgets and the least privileged `omneum_network_operator` role. The ingestion
role can read credentials and consume admission budgets, but cannot enroll,
issue, rebind, revoke, or grant consent. Existing migrations are not reapplied.

Store an operator DSN in a private mounted secret file (0600); use PostgreSQL
`sslmode=verify-full` for remote access. The operator CLI accepts
`OMNEUM_NETWORK_OPERATOR_DSN` or `OMNEUM_NETWORK_OPERATOR_DSN_FILE`, never a DSN
argument. Do not mount this identity in API pods. Prepare a private issuance
directory and create a workspace if you do not already have one:

```sh
export OMNEUM_NETWORK_OPERATOR_DSN_FILE=/secure/operator/network-operator.dsn
install -d -m 700 /secure/operator/issued
python -m omneum.network_operator create-workspace
```

Copy the returned non-secret workspace UUID into `NETWORK_WORKSPACE_ID`. After
verifying the contributor's explicit consent, enroll them with the applicable
consent-policy version:

```sh
python -m omneum.network_operator enroll \
  --workspace-id "$NETWORK_WORKSPACE_ID" \
  --consent-version consent-2026-10 --confirm-consent \
  --expires-days 90 --output /secure/operator/issued/contributor-a.token
```

The command returns only `principal_id`, `installation_id`, `credential_id` and
`expires_at`. Keep those identifiers for administration. It creates a new
installation, permanently binds it to its independently identified principal and
workspace, records an active `research_context_graph` consent grant, and issues
one random credential. Omitting `--confirm-consent` is an error. Repeat with a
new output filename for each independently consenting contributor.

The raw token is issued once into the operator-owned 0600 file in a private 0700
directory; it never appears in stdout, stderr, arguments, database rows or API
configuration. Transfer that file's contents through your approved private
credential-delivery channel, then delete the operator's delivery copy. The
recipient keeps their credential in private MCP settings/secret storage. This
issuance artifact is the only operator-side plaintext copy; there is no token
retrieval endpoint or command. Tokens contain a public UUID selector and 256 bits
of random secret material. The database stores a domain-separated SHA-256 digest,
verified using constant-time comparison. This is hashing for random API tokens,
not a password-hashing scheme. Leaked database hashes do not supply usable bearer
credentials. Credential lifetimes default to 90 days and must be 1–365 days.

Rotation preserves the principal, installation, consent and quota history. Copy
the public identifiers from the prior JSON into `NETWORK_PRINCIPAL_ID` and
`NETWORK_CREDENTIAL_ID`; then:

```sh
python -m omneum.network_operator issue \
  --principal-id "$NETWORK_PRINCIPAL_ID" \
  --expires-days 90 --output /secure/operator/issued/contributor-a-rotated.token
# Deliver the new credential before revoking the old credential ID:
python -m omneum.network_operator revoke-credential \
  --credential-id "$NETWORK_CREDENTIAL_ID"
# Disable the entire contributor, revoke all their credentials and active consent:
python -m omneum.network_operator revoke-contributor \
  --principal-id "$NETWORK_PRINCIPAL_ID"
# Schedule daily; current admission windows are never removed:
python -m omneum.network_operator prune-quotas --retention-days 2
```

Revocation is idempotent and does not require restarting the API. Both HTTP routes
honor it. Operator issuance/revocation and ingestion share the installation lock;
ingestion reauthenticates after taking that lock, before replay or writes. A
successful revocation waits for earlier locked ingestion to finish and prevents
subsequent pending ingestion with the revoked credential from committing.
Revoked/expired credentials cannot be reactivated or rebound; issue a new
credential. Disabling a contributor also revokes their consent, so issuance then
fails. Previously accepted reports remain in their original installation history.

All output files are created exclusively; existing files and symlinks are rejected.
If issuance or commit fails, inspect any reserved private file and the database
before retrying: the file may be empty, or may hold a credential whose commit
outcome is uncertain. Never overwrite it or automatically issue a replacement.
Commands exit nonzero on failure and sanitize error messages. Authentication,
admission-store or database outages deny Network requests; local MCP evaluation
continues under the existing failure behavior.

For upgrades, remove obsolete singleton `OMNEUM_NETWORK_API_TOKEN` and
`OMNEUM_NETWORK_PRINCIPAL_ID` settings (including `_FILE` variants). No static-token
fallback exists. Apply migration 006 and use `issue` for an existing enabled,
consenting principal to preserve its history. New contributors use `enroll`.
Recreate old disposable Compose volumes with `docker compose down --volumes`
before testing this changed bootstrap; production databases are migrated in place.

The CLI command forms above are exercised with a disposable database and the
least privileged operator role. Production migration/grant commands are supplied
for administrators and have not been run against production.

## Validation status

Multi-contributor enrollment validation passed **272 tests, 1 skipped** against a
new disposable cluster on port 55443. This includes independently enrolled
principals, hash-only storage, least privileged operator CLI commands, consent,
expiry, credential rotation, cross-principal isolation, revocation during pending
ingestion, concurrent shared admission budgets, both HTTP routes, native HTTPS
startup/restart, and local MCP fallback. The skipped legacy local-storage test
requires the separate `OMNEUM_TEST_POSTGRES_DSN`, which was left unset. Network
persistence was tested against the disposable ingestion database. The exact
focused command was:

```sh
OMNEUM_INGESTION_TEST_ADMIN_DSN='host=/private/tmp/omneum-enrollment-pg/socket port=55443 dbname=omneum_enrollment_test user=network_test_admin' .venv/bin/python -m pytest tests/test_network_enrollment.py tests/test_network_bootstrap.py tests/test_ingestion.py tests/test_network_trust.py tests/test_network_http.py tests/test_contributor.py tests/test_contribution_security.py tests/test_voprf_boundary.py tests/test_client_contribution.py -q
```

The cluster was initialized with the following commands, stopped after testing,
and its data directory removed. Trust authentication was restricted to this
temporary test cluster; it is not production configuration.

```sh
initdb -D /private/tmp/omneum-enrollment-pg/data --auth=trust -U network_test_admin
pg_ctl -D /private/tmp/omneum-enrollment-pg/data -l /private/tmp/omneum-enrollment-pg/server.log -o '-k /private/tmp/omneum-enrollment-pg/socket -h 127.0.0.1 -p 55443' start
createdb -h /private/tmp/omneum-enrollment-pg/socket -p 55443 -U network_test_admin omneum_enrollment_test
pg_ctl -D /private/tmp/omneum-enrollment-pg/data stop -m fast
.venv/bin/python -m compileall -q omneum/ingestion/credentials.py omneum/network_operator.py omneum/network_api.py deploy/network tests/test_network_enrollment.py tests/test_network_bootstrap.py
sh -n deploy/network/init-postgres.sh
git diff --check
.venv/bin/python -m omneum.network_operator --help
env -u OMNEUM_TEST_POSTGRES_DSN -u OMNEUM_INGESTION_TEST_ADMIN_DSN .venv/bin/python -m pytest tests/test_client_contribution.py::test_both_with_real_storage -q -rs
```

The last command confirms the skipped-test reason. Its first sandboxed attempt
failed to start the Unix-socket fixture daemon; rerunning outside the sandbox
confirmed the database configuration skip. Compose, Chart.yaml and values.yaml
also passed PyYAML parsing; Docker and Helm are still unavailable, so this does
not verify container execution or template rendering.

The following counts describe the earlier container/bootstrap and contributor
work, before the multi-contributor changes:

On this workstation the baseline free regression suite passed: **1,091 passed,
82 skipped**. The final free suite passed: **1,107 passed, 83 skipped**.
The existing release contract checks passed: **31 tests**.
An additional native Network integration run passed **186 tests** against a
fresh PostgreSQL cluster under `/private/tmp`, using only disposable fixture
keys and identities. It exercised the shipped HTTPS entrypoint, authentication
rejection, VOPRF evaluation, authorized ingestion, PostgreSQL persistence,
ASGI shutdown and restart, and real MCP stdio local-only and outage paths. Unix-socket fixture tests require execution outside the filesystem
sandbox. PostgreSQL tests in the free-suite runs were skipped with both database test
DSNs unset. The separate integration run used this command:

```sh
OMNEUM_INGESTION_TEST_ADMIN_DSN='host=/private/tmp/omneum-network-pg/socket port=55439 dbname=omneum_network_test user=network_test_admin' .venv/bin/python -m pytest tests/test_ingestion.py tests/test_network_trust.py tests/test_network_http.py tests/test_network_bootstrap.py tests/test_contributor.py -q
```

The temporary cluster was created with `initdb --auth=trust`, explicitly bound
to a temporary Unix socket and port 55439, then stopped with `pg_ctl`. It was
never an existing or production cluster. Its data directory was removed after
tests completed. These native tests use the repository
fixture daemon and do not establish container/Linux isolation guarantees.
Docker and Helm are absent from PATH, so image build, Compose integration,
container restart and Helm rendering commands above are supplied for execution,
not claimed as tested. No production database or paid API was used.


Additional commands executed during validation:

```sh
initdb -D /private/tmp/omneum-network-pg/data --auth=trust -U network_test_admin
pg_ctl -D /private/tmp/omneum-network-pg/data -l /private/tmp/omneum-network-pg/server.log -o '-k /private/tmp/omneum-network-pg/socket -h 127.0.0.1 -p 55439' start
createdb -h /private/tmp/omneum-network-pg/socket -p 55439 -U network_test_admin omneum_network_test
pg_ctl -D /private/tmp/omneum-network-pg/data stop -m fast
UV_CACHE_DIR=/private/tmp/omneum-container-uv uv --no-config export --frozen --no-dev --no-emit-project --no-hashes --no-annotate --format requirements-txt --output-file deploy/network/requirements.txt
.venv/bin/python -m pytest tests/test_network_http.py -xq
.venv/bin/python -m pytest tests/test_network_bootstrap.py tests/test_contributor.py -q
.venv/bin/python -m pytest tests/test_contributor.py -q
.venv/bin/python -m unittest discover -s tools -p 'test_release_*.py' -q
sh -n deploy/network/init-postgres.sh
.venv/bin/python -m compileall -q omneum/contributor.py omneum/network_api.py deploy/network
git diff --check
```

Plain Compose, chart metadata and values YAML were parsed with PyYAML. This is
not a substitute for Compose validation or Helm template rendering. The local
uv executable was 0.12.12 rather than the project's required 0.12.10, so export
used `--no-config --frozen` solely to read the existing lock without changing it.
The generated requirements file includes explicit Network-only driver pins.
Initial sandbox fixture failures were resolved by allowing disposable socket
and PostgreSQL shared-memory operations outside the sandbox.
