# Server Deployment

Omneum Network runs as a self-hosted service on Linux. This guide covers the production deployment on Ubuntu 24.04, using DigitalOcean Managed PostgreSQL for persistence. The enrollment and ingestion APIs run behind Nginx; a separate Rust daemon handles protected VOPRF evaluation.

This guide operates an existing, approved deployment; repository commands do not provision cloud resources. **Do not enable contributions until release preflight and both live acceptance paths pass against the installed release.**

## Deployment layout

| Component | Runtime | Boundary |
| --- | --- | --- |
| Public ingress | Nginx, HTTPS | Only the three API routes; no direct backend ports |
| Enrollment API | `omneum-network-enrollment` | OIDC access tokens; enrollment DB role |
| Ingestion API | `omneum-network-ingestion` | Installation credentials; ingestion DB role |
| Protected evaluator | `omneum-network-evaluator` | AF_UNIX IPC; evaluator-owned scalar |
| Database | DigitalOcean PostgreSQL, `omneum_prod` | Separate roles; verified TLS |
| Client | Local MCP server | Local graph remains private; contributions require consent |

## Database layout

`migrations/production_001.sql` establishes the hosted schema boundaries:

| Schema | Contents |
| --- | --- |
| `control` | Accounts, installations, consent, principals, credentials, receipts, quotas |
| `network` | Shared pseudonymous sources, claims, observations, evaluation and dependency reports |
| `public` | Explicitly published semantic information |
| `private` | Reserved for a future hosted Cloud product; currently empty |

Local installations use SQLite or user-managed PostgreSQL. They receive installation API credentials, never `omneum_prod` credentials. Authorized contributions pass through HTTPS ingestion into `network.*`; authorization and receipts live in `control.*`. Reported scores remain contributor reports, not Network-wide scores.

**Apache AGE is not part of this deployment.** DigitalOcean Managed PostgreSQL does not list it among [supported extensions](https://docs.digitalocean.com/products/databases/postgresql/details/supported-extensions/). The hosted graph uses relational tables and SQL joins.

`production_002_context_graph.sql` creates an AGE graph named `omneum_network`; exclude it from hosted migrations. No AGE population, synchronization, or backfill exists. The local `PostgresStorage` adapter targets `public.*` and `omneum_context`; do not apply its unprefixed migrations to `omneum_prod`.

## 1. Infrastructure

Provision the following in DigitalOcean:

| Resource | Configuration |
| --- | --- |
| VM | Ubuntu 24.04, x86_64, 2 GiB RAM |
| PostgreSQL | Managed cluster in the VM's region |
| Database | Dedicated `omneum_prod` |
| DNS | Approved API hostname pointing to the VM |
| TLS | Publicly trusted certificate with automatic renewal |
| Identity | OIDC provider supporting device authorization |

Restrict PostgreSQL trusted sources to the VM and authorized administration addresses. Download the cluster CA; retain the administrative login in a root-owned private file. If the database already contains objects, inspect its schema and migration ledger after backup. Do not recreate it or rerun DDL blindly.

Install host dependencies:

```bash
sudo apt-get update
sudo apt-get install --no-install-recommends \
  python3 python3-venv nginx certbot ca-certificates \
  postgresql-client ufw cron xxd
```

Configure the firewall, substituting the actual administrator CIDR:

```bash
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow from YOUR_ADMIN_CIDR to any port 22 proto tcp
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw enable
```

Keep the current SSH session open until a second connection succeeds. Apply equivalent DigitalOcean cloud firewall rules.

Backend ports `8443` and `8444` must not be public. Both Python APIs bind to `127.0.0.1`; the evaluator uses AF_UNIX inside a private network namespace.

Enable managed database backups. Define retention, recovery point, and recovery time requirements. A single VM has no application failover.

## 2. Account authentication

Register an Auth0 tenant or equivalent OIDC provider.

| Setting | Requirement |
| --- | --- |
| Application type | Public Native Application |
| Grant | Device Authorization |
| API audience | Dedicated enrollment audience |
| Signing algorithm | RS256 |
| Permission | `omneum:enroll` |
| Token lifetime | At most 3,600 seconds |
| API authorization | Enrollment scope authorized for intended users |

Disable unused grants. Configure account recovery, signup abuse controls, and administrator MFA. Database-account login requires a production email provider; Auth0's built-in email delivery is for testing.

Record the issuer with its trailing slash, JWKS URI, client ID, device endpoint, token endpoint, and verification URI. The CLI requests the configured audience and scope; it does not persist account JWTs.

Enrollment validates:

- RS256 signature, issuer, audience, subject, and scope
- Integer `iat` and `exp`; non-future issuance and positive lifetime no longer than one hour
- `nbf` when present; malformed, non-integer, or future values are rejected

An Auth0 audience array is valid when it contains the configured enrollment audience. ID tokens and access tokens for other APIs are not accepted.

Provider compatibility remains unverified until the real device-flow acceptance test succeeds.

References: [Device Authorization](https://auth0.com/docs/get-started/authentication-and-authorization-flow/device-authorization-flow), [Access Tokens](https://auth0.com/docs/secure/tokens/access-tokens/get-access-tokens).

## 3. Build artifacts

Build on trusted Linux x86_64 with the VM's Python minor version (Python 3.12 on Ubuntu 24.04), Rust 1.90.0, and the reviewed repository revision. Production builds must exclude fixture and test-daemon features.

```bash
sh deploy/network/vm/build-artifacts.sh /absolute/new/artifacts
sha256sum /absolute/new/artifacts/SHA256SUMS
```

Transfer the artifact bundle and reviewed repository to root-owned VM directories. Authenticate the release manifest digest through an independent trusted channel; a manifest copied alongside its artifacts does not authenticate the bundle.

Install offline:

```bash
sudo sh /root/repository/deploy/network/vm/install.sh \
  /root/artifacts /root/repository
```

The installer refuses existing installation paths. It creates three disabled-login service identities:

| Identity | Access |
| --- | --- |
| `omneum-network-api` | Ingestion runtime |
| `omneum-enrollment` | Enrollment runtime |
| `omneum-network-crypto` | Protected evaluator and scalar |

Only ingestion and the evaluator share the reserved IPC group. Installation does not start Omneum services; the initial configuration is intentionally invalid. The evaluator scalar is never mounted as a Python API credential.

## 4. Configuration and keys

Edit `/etc/omneum-network/production.json` as root. Start from `deploy/network/vm/production.json`.

The deployment validator rejects missing fields, zero key versions, malformed public keys, reserved DNS names, duplicate secret paths, and insecure transport. Set `database_name` to `omneum_prod` in all production DSNs.

### Private files

| Setting | Path |
| --- | --- |
| Database CA | `/etc/omneum-network/secrets/database-ca.pem` |
| Ingestion DSN | `/etc/omneum-network/secrets/ingestion.dsn` |
| Enrollment DSN | `/etc/omneum-network/secrets/enrollment.dsn` |
| TLS certificate | `/etc/omneum-network/secrets/tls.crt` |
| TLS private key | `/etc/omneum-network/secrets/tls.key` |
| OIDC JWKS | `/etc/omneum-network/secrets/jwks.json` |
| Administrator DSN | `/root/network-admin.dsn` |

All DSN files are root-owned, mode `0600`. Runtime DSNs use distinct random passwords and libpq keyword syntax:

```text
host=ACTUAL_DB_DNS port=ACTUAL_DB_PORT dbname=omneum_prod user=omneum_ingestion password='ACTUAL_SECRET' sslmode=verify-full
host=ACTUAL_DB_DNS port=ACTUAL_DB_PORT dbname=omneum_prod user=omneum_enrollment password='DIFFERENT_SECRET' sslmode=verify-full
```

CA paths come from configuration and systemd credential mounts. Deployment commands reject DSN service files, `hostaddr`, option injection, and TLS overrides. Runtime logins must not own schemas or tables or inherit each other's privileges.

Do not pass passwords through shell arguments, history, or logs.

### Protected evaluator

Provision the Network scalar once, as the evaluator identity:

```bash
sudo runuser -u omneum-network-crypto -- \
  /opt/omneum-network/libexec/omneumd provision \
  --key-dir /var/lib/omneum-network-crypto
```

The command emits the public key as hex. Alternatively, provision and convert that output directly to unpadded base64url:

```bash
sudo runuser -u omneum-network-crypto -- \
  /opt/omneum-network/libexec/omneumd provision \
  --key-dir /var/lib/omneum-network-crypto \
  | xxd -r -p | base64 -w0 | tr '+/' '-_' | tr -d '='
```

**Run one form only.** Provisioning refuses an existing scalar. Copy the public result into `network_public_key`; never read or export the scalar through an API account.

Generate a deployment identifier:

```bash
python3 -c 'import uuid; print("urn:uuid:" + str(uuid.uuid4()))'
```

Set a positive Network key version. `local_public_key` must be the release's distinct local-domain public key; local linkage tokens are not Network credentials. Preserve deployment ID, key version, and public pins across routine restarts and upgrades.

### Consent

Publish `research_context_graph` terms at the configured HTTPS `consent_url`. Cover linkability, retention, withdrawal, and deletion behavior; set the matching consent version.

Research consent does not authorize publication into `public.*`.

### Generate runtime DSNs

After configuring public values and keys, install the verified CA:

```bash
sudo install -m 0600 \
  /root/verified-database-ca.pem \
  /etc/omneum-network/secrets/database-ca.pem

sudo /opt/omneum-network/venv/bin/python -I -B \
  -m omneum.network_deploy generate-dsns
```

The generator writes 256-bit random passwords to exclusive private files and refuses overwrites. Inspect partial output before retrying.

## 5. Database migration

Run migrations with the administrator DSN, never a runtime DSN:

```bash
sudo /opt/omneum-network/venv/bin/python -I -B \
  -m omneum.network_deploy migrate \
  --admin-dsn-file /root/network-admin.dsn \
  --migrations /root/repository/migrations
```

The runner applies the hosted migration sequence through `production_007_self_service.sql`, excluding `production_002_context_graph.sql`.

Migration checksums are recorded transactionally in `omneum_deploy.migrations`. Repeated execution verifies checksums and skips completed migrations. Runtime logins receive salted SCRAM verifiers, not plaintext password SQL.

An existing schema without a compatible migration ledger fails closed. Reconcile it administratively after backup; do not bypass the check.

Restrict database query logging before running role-password DDL.

## 6. TLS and service startup

The installer provides an HTTP-only ACME bootstrap. For a fresh deployment, remove the Ubuntu default Nginx site and request a certificate:

```bash
sudo rm /etc/nginx/sites-enabled/default
sudo nginx -t
sudo systemctl enable --now nginx

sudo certbot certonly --webroot \
  -w /var/lib/omneum-acme \
  -d YOUR_APPROVED_DOMAIN \
  --email YOUR_OPERATOR_EMAIL --agree-tos
```

If Certbot has already issued a valid certificate using the Nginx plugin, **do not repeat initial issuance**. Reconcile the existing Nginx site and Certbot renewal configuration with the installed Omneum configuration before replacing either.

Install certificates and provider keys:

```bash
sudo /opt/omneum-network/venv/bin/python -I -B \
  -m omneum.network_deploy install-certificates

sudo /opt/omneum-network/venv/bin/python -I -B \
  -m omneum.network_deploy refresh-jwks
```

Render the systemd units and Nginx configuration:

```bash
sudo install -d -m 0700 /etc/omneum-network/rendered

sudo /opt/omneum-network/venv/bin/python -I -B \
  -m omneum.network_deploy render \
  --output /etc/omneum-network/rendered

sudo install -m 0600 \
  /etc/omneum-network/rendered/public.env \
  /etc/omneum-network/public.env

sudo install -m 0644 \
  /etc/omneum-network/rendered/omneum-network-*.service \
  /etc/systemd/system/

sudo install -m 0600 \
  /etc/omneum-network/rendered/nginx.conf \
  /etc/nginx/conf.d/omneum-network.conf

sudo rm /etc/nginx/conf.d/omneum-acme.conf
sudo nginx -t
sudo systemctl daemon-reload

sudo systemctl enable --now \
  omneum-network-evaluator \
  omneum-network-ingestion \
  omneum-network-enrollment

sudo systemctl reload nginx
```

Do not install the rendered Nginx configuration while an overlapping `api.omneum.ai` server block remains enabled. Validate the replacement and preserve the active certificate renewal path.

The APIs receive separate database credentials and CA/TLS copies through systemd `LoadCredential`. Enrollment cannot access the evaluator socket or scalar directory.

Nginx verifies the loopback backends' certificate trust and hostname. It clears forwarded headers, disables access logs, limits request size and duration, and applies source-IP request and connection limits. Authorization and quotas remain application responsibilities.

### Certificate renewal and JWKS refresh

```bash
sudo install -m 0755 \
  /opt/omneum-network/libexec/renew-certificates \
  /etc/letsencrypt/renewal-hooks/deploy/omneum-network

sudo systemctl enable --now certbot.timer
sudo certbot renew --dry-run

sudo /opt/omneum-network/libexec/renew-certificates

sudo install -m 0644 \
  /root/repository/deploy/network/vm/jwks.cron \
  /etc/cron.d/omneum-network-jwks
```

The renewal hook validates Certbot archive files, copies the matching certificate and key into private runtime paths, reloads Nginx, and restarts API credential snapshots.

JWKS refresh validates the fixed issuer discovery and signing-key endpoints before replacing keys. Unknown signing keys fail closed until refresh; enrollment restarts only when the key set changes.

Do not log JWTs, request bodies, credentials, or private application data.

## 7. Release pins and preflight

Production clients use release-owned constants:

| Module | Constant |
| --- | --- |
| `omneum/contribution/network.py` | `_PRODUCTION_NETWORK` |
| `omneum/onboarding.py` | `_PRODUCTION_ONBOARDING` |

Populate them from independently verified deployment values. Enrollment pins include the OIDC audience and `omneum:enroll` scope.

All three endpoints use the same HTTPS origin:

| Route | Service |
| --- | --- |
| `POST /v1/voprf` | Protected evaluation |
| `POST /v1/contributions` | Contribution ingestion |
| `POST /v1/enrollment` | Enrollment |

No private keys or DSNs belong in release constants. Contributor environment variables cannot override production endpoints, deployment IDs, or public keys.

Build and install the pinned release on the VM and acceptance client before running preflight:

```bash
sudo /opt/omneum-network/venv/bin/python -I -B \
  -m omneum.network_release --require-provisioned

sudo /opt/omneum-network/venv/bin/python -I -B \
  -m omneum.network_deploy preflight

sudo systemctl status \
  omneum-network-evaluator \
  omneum-network-ingestion \
  omneum-network-enrollment nginx
```

Preflight validates configuration, permissions, certificate pairing, CA trust, database TLS, service identities, migrations, provider discovery, JWKS, public authorization rejection, evaluator IPC/proofs, and release-pin consistency.

It does not establish real account login, peak capacity, or recovery readiness.

### Public authorization check

Unauthenticated requests must return HTTP 401 on all three routes.

```bash
curl --fail-with-body \
  -X POST \
  -H 'Content-Type: application/json' \
  --data '{}' \
  https://YOUR_APPROVED_DOMAIN/v1/voprf
```

Curl exits nonzero on the expected 401. A successful TCP or TLS connection alone does not establish application readiness. Never use `-k` to bypass certificate validation.

## 8. Acceptance

### Hosted acceptance

Use a dedicated provider test account. Each run consumes one of its ten lifetime installation slots and retains a synthetic report.

```bash
sudo /opt/omneum-network/venv/bin/python -I -B \
  -m omneum.network_deploy provider-token

sudo /opt/omneum-network/venv/bin/python -I -B \
  -m omneum.network_acceptance hosted \
  --confirm-live \
  --admin-dsn-file /root/network-admin.dsn
```

The hosted test uses a real provider-issued token. It checks enrollment and consent, VOPRF proofs, domain separation, persistence, idempotency, renewal, rotation, revocation, withdrawal, and rejection after withdrawal.

The administrative DSN is used only for verification. Unit tests with synthetic tokens do not establish Auth0 compatibility.

### Local client acceptance

On a supported macOS/Linux client with the pinned release:

```bash
pip install omneum
omneum install
omneum network enroll
python -m omneum.network_acceptance local-outage
```

The outage test exercises the installed MCP service and a fresh private SQLite test graph during a simulated Network timeout. It does not stop production or export existing local history.

After verification, configure `omneum-contributor` as the MCP command and enable:

```bash
export OMNEUM_NETWORK_CONTRIBUTION=true
```

Only `evaluate_observations` contributes new assertion occurrences. `omneum-server` and `evaluate_context` remain local APIs.

Renew installation credentials with `omneum network renew` before expiration, then restart the MCP connection.

### Disposable regression tests

Use a dedicated test PostgreSQL cluster whose database name contains `test`.

```bash
python -m pytest -q \
  tests/test_network_deploy.py \
  tests/test_network_enrollment.py \
  tests/test_network_bootstrap.py \
  tests/test_contributor.py

cargo test --locked --no-default-features --features daemon
```

For disposable Linux ingress and security acceptance:

```bash
docker build -t omneum-network:vm-audit .

docker build -t omneum-vm-security:local \
  -f tests/security/vm.Dockerfile .

docker run --rm --network none \
  --mount type=bind,src="$PWD",dst=/repo,readonly \
  omneum-vm-security:local
```

This harness uses a mock OIDC provider and three Unix identities. It checks unit syntax, TLS ingress, database boundaries, and lifecycle behavior; it does not verify real Auth0 tokens or live systemd confinement.

The Compose stack is disposable. Never reuse its seven-day certificates, test credentials, keys, or volumes in production.

## 9. Backups

Create `/root/network-backup.pgservice` with mode `0600`:

```ini
[network_backup]
host=ACTUAL_DB_DNS
port=ACTUAL_DB_PORT
dbname=omneum_prod
user=ACTUAL_ADMIN_LOGIN
password=ACTUAL_ADMIN_SECRET
sslmode=verify-full
sslrootcert=/etc/omneum-network/secrets/database-ca.pem
```

Use a private editor; do not put the password in shell history.

```bash
sudo install -d -m 0700 /root/omneum-backups

sudo env \
  PGSERVICEFILE=/root/network-backup.pgservice \
  PGSERVICE=network_backup \
  pg_dump --format=custom \
  --file=/root/omneum-backups/network.dump

sudo chmod 0600 /root/omneum-backups/network.dump
```

Encrypt the dump before transferring it to an authorized off-VM recovery location. This supplements, rather than replaces, managed PostgreSQL backups.

## 10. Upgrade and rollback

Keep the previous authenticated artifact bundle, configuration, rendered units, and database backup. A same-schema upgrade installs into a new offline virtual environment; the initial installer is not an upgrade mechanism.

Verify the new manifest before stopping services. Preserve the evaluator identity, scalar, deployment ID, and public pins.

For a same-schema code upgrade with artifacts staged in `/root/new-artifacts`:

```bash
sudo test ! -e /opt/omneum-network-previous

sudo systemctl stop \
  omneum-network-ingestion \
  omneum-network-enrollment \
  omneum-network-evaluator

sudo mv /opt/omneum-network /opt/omneum-network-previous
sudo install -d -m 0755 \
  /opt/omneum-network \
  /opt/omneum-network/libexec

sudo python3 -m venv /opt/omneum-network/venv

sudo /opt/omneum-network/venv/bin/python -m pip install \
  --no-index --find-links /root/new-artifacts \
  -r /root/repository/deploy/network/requirements.txt \
  /root/new-artifacts/omneum-*.whl

sudo install -m 0755 \
  /root/new-artifacts/omneumd \
  /opt/omneum-network/libexec/omneumd

sudo install -m 0755 \
  /root/repository/deploy/network/vm/renew-certificates.sh \
  /opt/omneum-network/libexec/renew-certificates

sudo /opt/omneum-network/libexec/omneumd capabilities

sudo /opt/omneum-network/venv/bin/python -I -B \
  -m omneum.network_deploy migrate \
  --admin-dsn-file /root/network-admin.dsn \
  --migrations /root/repository/migrations

sudo systemctl start \
  omneum-network-evaluator \
  omneum-network-ingestion \
  omneum-network-enrollment

sudo /opt/omneum-network/venv/bin/python -I -B \
  -m omneum.network_deploy preflight
```

`capabilities` must report `protected-voprf-v1`. If units or configuration changed, render them into a fresh private directory and validate before restart. A failed preflight blocks release promotion.

### Code rollback

Ensure `/opt/omneum-network-failed` does not exist. Restore matching configuration and units if the upgrade changed them.

```bash
sudo systemctl stop \
  omneum-network-ingestion \
  omneum-network-enrollment \
  omneum-network-evaluator

sudo mv /opt/omneum-network /opt/omneum-network-failed
sudo mv /opt/omneum-network-previous /opt/omneum-network

sudo systemctl daemon-reload

sudo systemctl start \
  omneum-network-evaluator \
  omneum-network-ingestion \
  omneum-network-enrollment

sudo /opt/omneum-network/venv/bin/python -I -B \
  -m omneum.network_deploy preflight
```

Do not restore old consent or credential state to roll back application code. If the schema is incompatible with the previous release, use a forward fix.

## 11. Recovery

Restore backups into an isolated cluster first. Validate schemas, grants, receipts, revoked credentials, and consent state before cutover.

For a newly migrated recovery database, configure the private backup service file to point to the recovery cluster and run:

```bash
sudo env \
  PGSERVICEFILE=/root/network-backup.pgservice \
  PGSERVICE=network_backup \
  pg_restore --data-only \
  --exclude-schema=omneum_deploy \
  --no-owner --no-acl \
  --single-transaction --exit-on-error \
  --dbname=service=network_backup \
  /root/omneum-backups/network.dump
```

Never test this restore against production.

### Evaluator key recovery

Maintain an encrypted off-VM copy of the evaluator scalar under a separate authorized recovery identity. The API accounts must not be able to decrypt it.

With an approved offline `age` recipient:

```bash
sudo age -r YOUR_RECOVERY_PUBLIC_KEY \
  -o /root/omneum-backups/voprf.key.age \
  /var/lib/omneum-network-crypto/voprf.key

sudo chmod 0600 /root/omneum-backups/voprf.key.age
```

On a fresh recovery VM, before provisioning any new scalar:

```bash
sudo age --decrypt \
  -i /root/offline-recovery.identity \
  -o /root/omneum-backups/voprf.key \
  /root/omneum-backups/voprf.key.age

sudo test ! -e /var/lib/omneum-network-crypto/voprf.key

sudo install \
  -o omneum-network-crypto \
  -g omneum-network-ipc \
  -m 0600 \
  /root/omneum-backups/voprf.key \
  /var/lib/omneum-network-crypto/voprf.key
```

Verify the recovered public key against the pinned release before reopening traffic. Remove the temporary plaintext copy after successful recovery.

Never generate a replacement scalar under an existing key version. VM snapshots containing plaintext scalar material are not an independent key backup; verify snapshot encryption and access controls.

## Operations

Schedule quota pruning with an authorized operator DSN:

```bash
python -m omneum.network_operator prune-quotas --retention-days 2
```

Monitor TLS expiry, JWKS refresh, database connection limits, disk and memory headroom, quota pruning, backup jobs, and recovery checks. Keep operator credentials out of the ingestion and enrollment services.

## Related documentation

- [Network Contribution](../../docs/network-contribution.md)
- [Storage](../../docs/storage.md)
- [DigitalOcean PostgreSQL Extensions](https://docs.digitalocean.com/products/databases/postgresql/details/supported-extensions/)
- [Auth0 Device Authorization](https://auth0.com/docs/get-started/authentication-and-authorization-flow/device-authorization-flow)