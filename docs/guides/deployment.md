# Hosted Network: single Linux VM

This runbook targets Ubuntu 24.04, one 2 GiB VM, managed PostgreSQL, and an OIDC
provider. It reuses the ingestion/enrollment entrypoints and protected Rust daemon.
No cloud resources are created by the repository commands. Obtain approval before
creating the VM, database, domain, authentication subscription, or email service.
Production readiness requires both acceptance commands below to pass on the actual
released package and provisioned deployment.

## 1. Provision external infrastructure

In DigitalOcean, after approval:

1. Create the VM with an SSH public key; disable password and root SSH login after
   establishing a sudo account. Use a supported Ubuntu 24.04 image and enable
   security updates. Record the static public IPv4 address.
2. Create managed PostgreSQL in the same region. Create a dedicated empty
   `omneum_network` database. Download the cluster CA; record its DNS hostname and
   port. Restrict trusted sources to the VM and the authorized administration IP.
   Retain the administrative login only in a root-owned private file.
3. Create an A record for the approved Network domain pointing to the VM. Do not
   publish an AAAA record without configuring and testing IPv6 ingress.
4. Enable managed database backups and test recovery. Define report retention,
   recovery-time and recovery-point targets. Single-node application hosting has
   planned restart downtime and no redundant application failover.

On the VM, execute as your sudo administrator. Replace the SSH source CIDR first;
keep the existing SSH session open while testing a second session.

```bash
sudo apt-get update
sudo apt-get install --no-install-recommends python3 python3-venv nginx certbot ca-certificates postgresql-client ufw cron xxd
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow from YOUR_ADMIN_CIDR to any port 22 proto tcp
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw enable
```

Apply equivalent DigitalOcean cloud firewall rules. Do not expose 8443, 8444,
PostgreSQL, or the evaluator. Both APIs bind to 127.0.0.1; the evaluator has a
private network namespace and supports only AF_UNIX.

## 2. Configure account authentication

Create an Auth0 tenant or equivalent OIDC account provider. Register a custom API
with a dedicated enrollment audience, RS256 signing, `omneum:enroll` permission,
and an access-token lifetime of at most 3,600 seconds. Register a **public Native
Application**, enable the device authorization grant, and authorize enrollment
scope for the intended account population. Disable unused grant types. Configure
account recovery, signup abuse controls, and administrator MFA at the provider.
If using database-account login, configure a production external email provider;
Auth0's built-in mail delivery is intended for testing.

Record the exact HTTPS issuer (including trailing slash), discovery JWKS URI,
public client ID, device endpoint, token endpoint, and verification URI. The CLI
requests the dedicated **audience** and enrollment scope. It never persists account
JWTs. Auth0 can return an audience array; signature validation checks membership
of the configured enrollment audience.

`nbf` is optional under RFC 7519. Enrollment verifies it when present and rejects
future, malformed, or non-integer values. Issuer, audience, RS256 signature, subject,
scope, integer `iat`/`exp`, non-future issuance, expiration, and a positive lifetime
no longer than one hour remain mandatory. ID tokens and unrelated API tokens
cannot substitute for the enrollment access token. Auth0 compatibility is still
unverified until the real-provider command in step 7 succeeds.

References: [Auth0 device flow](https://auth0.com/docs/get-started/authentication-and-authorization-flow/device-authorization-flow),
[Auth0 access-token profiles](https://auth0.com/docs/secure/tokens/access-tokens/access-token-profiles),
[API audience and lifetime](https://auth0.com/docs/secure/tokens/access-tokens/get-access-tokens),
[restricted custom claims](https://auth0.com/docs/secure/tokens/json-web-tokens/create-custom-claims).

## 3. Build and install authenticated artifacts

Build on a trusted Linux machine with the VM's architecture and Python minor
version (Ubuntu 24.04 supplies Python 3.12), Rust toolchain 1.90.0, and the reviewed
repository. Do not build fixture/test-daemon features for production.

```bash
sh deploy/network/vm/build-artifacts.sh /absolute/new/artifacts
sha256sum /absolute/new/artifacts/SHA256SUMS
```

Transfer the bundle and reviewed repository to root-owned directories on the VM.
Authenticate the manifest digest through an independent trusted release channel;
a manifest transported beside its artifacts alone is not authentication. Verify
that the build revision/source changes match the reviewed release.

```bash
sudo sh /root/repository/deploy/network/vm/install.sh /root/artifacts /root/repository
```

Installation is offline and refuses existing installation paths. It creates
`omneum-network-api`, `omneum-enrollment`, and `omneum-network-crypto` with disabled
login shells. Only ingestion and the evaluator share the reserved IPC group.
It starts no Omneum services and installs an intentionally invalid configuration.
The scalar never becomes a systemd credential available to either Python API.

## 4. Install configuration and keys

Edit `/etc/omneum-network/production.json` as root. Its template is
`deploy/network/vm/production.json`. Every field is mandatory; empty values,
zero versions, malformed public keys, reserved DNS names, duplicate secret paths,
and insecure transport fail validation. Use these private destination paths:

```text
database_ca       /etc/omneum-network/secrets/database-ca.pem
ingestion_dsn_file /etc/omneum-network/secrets/ingestion.dsn
enrollment_dsn_file /etc/omneum-network/secrets/enrollment.dsn
tls_certificate   /etc/omneum-network/secrets/tls.crt
tls_private_key   /etc/omneum-network/secrets/tls.key
oidc_jwks_file    /etc/omneum-network/secrets/jwks.json
```

Install the verified DigitalOcean CA with mode 0600. Generate the separate runtime
DSNs without printing passwords:

The generator writes 256-bit random passwords directly to exclusive private files.
It refuses existing files; inspect partial results rather than overwriting them.
Never put passwords in shell arguments, history, URLs, or logs. All DSN
files are root-owned 0600. Their syntax is libpq keyword syntax:

```text
host=ACTUAL_DB_DNS port=ACTUAL_DB_PORT dbname=omneum_network user=omneum_ingestion password='ACTUAL_SECRET' sslmode=verify-full
host=ACTUAL_DB_DNS port=ACTUAL_DB_PORT dbname=omneum_network user=omneum_enrollment password='DIFFERENT_SECRET' sslmode=verify-full
```

Store the corresponding administrator DSN at `/root/network-admin.dsn`, with the
actual administrator username. CA paths are supplied from the configuration and
systemd credential mounts, not from DSNs. DSN service files, options, hostaddr,
and TLS overrides are rejected by deployment commands. Use distinct randomly
generated runtime passwords and no runtime role memberships. Neither runtime
login owns application schemas or tables.

Provision the Network scalar once, under the evaluator identity:

```bash
sudo runuser -u omneum-network-crypto -- /opt/omneum-network/libexec/omneumd provision --key-dir /var/lib/omneum-network-crypto
```

The command prints the **public** key as hex. To convert it without handling the
scalar, capture the public result directly:

```bash
sudo runuser -u omneum-network-crypto -- /opt/omneum-network/libexec/omneumd provision --key-dir /var/lib/omneum-network-crypto | xxd -r -p | base64 -w0 | tr '+/' '-_' | tr -d '='
```

Run **one** provisioning form, once; the second command is an alternative to the
first. Existing scalar files are never replaced. Copy the output into
`network_public_key`. Generate the deployment UUID when provisioning:

```bash
python3 -c 'import uuid; print("urn:uuid:" + str(uuid.uuid4()))'
```

Never read, print, copy, or convert the scalar through the
API account. Provision a unique Network deployment UUID and positive key version.
`local_public_key` must be the supported release's distinct local-domain public
key. The configured local key does not authorize using local linkage tokens on
the Network. Preserve public pins across routine restarts and upgrades.

Publish consent terms for `research_context_graph` at the configured HTTPS
`consent_url` (through the existing documentation site), including linkability,
retention, withdrawal, and deletion behavior; set the corresponding consent version.
The API domain serves only the three API routes and ACME challenge files.

After completing the public/key configuration above, install the verified CA and
generate the private runtime DSNs. The config must validate before generation:

```bash
sudo install -m 0600 /root/verified-database-ca.pem /etc/omneum-network/secrets/database-ca.pem
sudo /opt/omneum-network/venv/bin/python -I -B -m omneum.network_deploy generate-dsns
```

## 5. Migrate and obtain certificates

Run the migration command only with the administrative file:

```bash
sudo /opt/omneum-network/venv/bin/python -I -B -m omneum.network_deploy migrate --admin-dsn-file /root/network-admin.dsn --migrations /root/repository/migrations
```

The runner applies the existing Network migration sequence through
`production_007_self_service.sql`, records checksums transactionally in an
administrator-only `omneum_deploy.migrations` ledger, and configures the two
runtime logins using salted SCRAM verifiers rather than cleartext SQL passwords. Repeating it checks checksums and skips completed migrations.
It does not apply the unrelated AGE/context-graph schema. Restrict database query
logging so password-setting commands and application request data are not retained.
Existing databases without this ledger fail closed: reconcile their applied
migrations and checksums administratively after backup; never blindly rerun DDL.

For initial ACME issuance, remove the Ubuntu default nginx site, validate the
installed HTTP-only ACME bootstrap, and start nginx:

```bash
sudo rm /etc/nginx/sites-enabled/default
sudo nginx -t
sudo systemctl enable --now nginx
sudo certbot certonly --webroot -w /var/lib/omneum-acme -d YOUR_APPROVED_DOMAIN --email YOUR_OPERATOR_EMAIL --agree-tos
sudo /opt/omneum-network/venv/bin/python -I -B -m omneum.network_deploy install-certificates
sudo /opt/omneum-network/venv/bin/python -I -B -m omneum.network_deploy refresh-jwks
sudo install -d -m 0700 /etc/omneum-network/rendered
sudo /opt/omneum-network/venv/bin/python -I -B -m omneum.network_deploy render --output /etc/omneum-network/rendered
sudo install -m 0600 /etc/omneum-network/rendered/public.env /etc/omneum-network/public.env
sudo install -m 0644 /etc/omneum-network/rendered/omneum-network-*.service /etc/systemd/system/
sudo install -m 0600 /etc/omneum-network/rendered/nginx.conf /etc/nginx/conf.d/omneum-network.conf
sudo rm /etc/nginx/conf.d/omneum-acme.conf
sudo nginx -t
sudo systemctl daemon-reload
sudo systemctl enable --now omneum-network-evaluator omneum-network-ingestion omneum-network-enrollment
sudo systemctl reload nginx
```

APIs receive separate DSNs and copies of CA/TLS files through `LoadCredential`.
The enrollment service cannot access the evaluator key directory or socket.
Nginx verifies backend certificate trust and the public hostname while connecting
to loopback. It clears forwarded headers, disables access logs, logs only critical
errors, enforces body/header/time limits, and applies source-IP request/connection
limits. It does not replace account authorization or installation quotas.

Enable renewal and provider signing-key maintenance:

```bash
sudo install -m 0755 /opt/omneum-network/libexec/renew-certificates /etc/letsencrypt/renewal-hooks/deploy/omneum-network
sudo systemctl enable --now certbot.timer
sudo certbot renew --dry-run
sudo /opt/omneum-network/libexec/renew-certificates
sudo install -m 0644 /root/repository/deploy/network/vm/jwks.cron /etc/cron.d/omneum-network-jwks
```

The deploy hook validates root-controlled certbot archive files, copies the matching
certificate/key into private files, reloads nginx, and restarts API credential
snapshots. JWKS refresh validates the fixed issuer discovery/JWKS HTTPS destinations
and signing keys before replacement; unknown keys fail closed until refresh. It
restarts enrollment only when the signing keys change, to refresh its credential snapshot. Monitor failures;
brief restart downtime is expected. Do not add request bodies, JWTs, or credentials
to proxy, service, APM, or database logs.

## 6. Release pins and preflight

After independently verifying the external deployment, populate the
**release-owned source constants** `_PRODUCTION_NETWORK` in
`omneum/contribution/network.py` and `_PRODUCTION_ONBOARDING` in
`omneum/onboarding.py` with the verified public values. Account pins now include
`audience`. Keep scope `omneum:enroll`. The three API URLs share one HTTPS origin
and use `/v1/voprf`, `/v1/contributions`, and `/v1/enrollment`. No private key or DSN
belongs in these constants. Build and install the reviewed pinned package on both
the VM and acceptance client before testing. Contributor environment variables
cannot select endpoints, deployment IDs, or keys.

```bash
sudo /opt/omneum-network/venv/bin/python -I -B -m omneum.network_release --require-provisioned
sudo /opt/omneum-network/venv/bin/python -I -B -m omneum.network_deploy preflight
sudo systemctl status omneum-network-evaluator omneum-network-ingestion omneum-network-enrollment nginx
```

Preflight checks configuration, root-controlled file paths and permissions,
certificate/key pairing, configured CA, verified TLS database connections,
least-privilege identities, migration-007 tables/triggers, provider discovery/JWKS,
public HTTPS authorization rejection, installed units and process identities,
evaluator socket/identity/public key/proof, and release-pin consistency. It does
not attest provider client configuration, peak capacity, recovery, or account login;
those require acceptance and operational verification. No private exception text
is printed. Inspect sanitized journals for dependency failures.

Unauthenticated health requests must return 401 on all three routes:

```bash
curl --fail-with-body -X POST -H 'Content-Type: application/json' --data '{}' https://YOUR_APPROVED_DOMAIN/v1/voprf
```

The expected HTTP 401 causes curl's failure exit status. A successful TCP connection
alone is not a health or authorization check. Never use `-k` or disable CA checks.

## 7. Acceptance: live versus disposable

On the VM, use a dedicated provider test account. Each hosted acceptance run
consumes one of its ten lifetime installation slots and retains one synthetic
report. It prompts for explicit purpose consent and provider device login. It
never exports existing local history or deletes unrelated server data.

```bash
sudo /opt/omneum-network/venv/bin/python -I -B -m omneum.network_deploy provider-token
sudo /opt/omneum-network/venv/bin/python -I -B -m omneum.network_acceptance hosted --confirm-live --admin-dsn-file /root/network-admin.dsn
```

Hosted acceptance verifies a **real provider-issued** token, enrollment/consent,
VOPRF proofs and domain separation, persistence, idempotency, renewal, rotation,
revocation, withdrawal, and rejection after withdrawal. Synthetic tokens in unit
tests do not establish Auth0 compatibility. The admin DSN is used only for
verification, never supplied to a runtime service.

On a supported macOS/Linux client with the pinned release installed:

```bash
pip install omneum
omneum install
omneum network enroll
python -m omneum.network_acceptance local-outage
```

The client command exercises the installed MCP service and fresh private test
SQLite during a simulated client-side Network timeout; it does not stop production.
It reads only the installation credential and never exports the existing graph.
After verification, use `omneum-contributor` as the MCP command and set
`OMNEUM_NETWORK_CONTRIBUTION=true`. Only `evaluate_observations` contributes new
assertion occurrences. `omneum-server` and `evaluate_context` remain local APIs.
Run `omneum network renew` before credential expiry and restart the MCP connection.

Disposable regression execution uses the existing test suite and a dedicated
local PostgreSQL cluster whose database name contains `test`:

```bash
python -m pytest -q tests/test_network_deploy.py tests/test_network_enrollment.py tests/test_network_bootstrap.py tests/test_contributor.py
cargo test --locked --no-default-features --features daemon
```

The repository Compose stack remains disposable only. Its generated seven-day
certificates, keys, test credentials, and volumes must never be reused in production.
The existing Helm files are not needed for this VM deployment.

For disposable Linux ingress/database/security acceptance:

```bash
docker build -t omneum-network:vm-audit .
docker build -t omneum-vm-security:local -f tests/security/vm.Dockerfile .
docker run --rm --network none --mount type=bind,src="$PWD",dst=/repo,readonly omneum-vm-security:local
```

This harness uses a mock provider and three actual Unix identities, validates unit
syntax, and verifies TLS ingress/database/lifecycle behavior. It explicitly does
not attest systemd runtime confinement or real Auth0 tokens.

## 8. Upgrade, rollback, and recovery

Create `/root/network-backup.pgservice` with the actual administrative connection
and trusted CA, using a private editor, then set root ownership and mode 0600:

```ini
[network_backup]
host=ACTUAL_DB_DNS
port=ACTUAL_DB_PORT
dbname=omneum_network
user=ACTUAL_ADMIN_LOGIN
password=ACTUAL_ADMIN_SECRET
sslmode=verify-full
sslrootcert=/etc/omneum-network/secrets/database-ca.pem
```

The service-file path and service name are the only connection information passed
to the backup process environment; no password appears in arguments:

```bash
sudo install -d -m 0700 /root/omneum-backups
sudo env PGSERVICEFILE=/root/network-backup.pgservice PGSERVICE=network_backup pg_dump --format=custom --file=/root/omneum-backups/network.dump
sudo chmod 0600 /root/omneum-backups/network.dump
```

The parent directory is private throughout creation. Encrypt this dump before
transferring it to the authorized off-VM recovery location. Provider-managed
backups remain enabled; this command supplements them.


Before upgrading, save the authenticated prior artifact bundle, configuration,
rendered units, and database backup. Build/install a new offline venv in a separate
root-owned version directory, verify dependencies and the protected daemon, then
stop both APIs, apply forward migrations, and replace the fixed runtime directory
using root-controlled directories on the same filesystem. Preserve evaluator
identity, scalar, deployment ID, and public pins. Regenerate units in a **new**
private output directory, validate nginx/systemd, restart, run preflight, and repeat
acceptance before promoting the release. Render refuses overwriting existing files.

For a same-schema code upgrade, use authenticated artifacts in `/root/new-artifacts`.
Ensure `/opt/omneum-network-previous` does not exist before starting. The initial
installer is intentionally unsuitable for upgrades because it would overwrite
configuration. Keep configuration and the scalar in their existing paths:

```bash
sudo test ! -e /opt/omneum-network-previous
sudo systemctl stop omneum-network-ingestion omneum-network-enrollment omneum-network-evaluator
sudo mv /opt/omneum-network /opt/omneum-network-previous
sudo install -d -m 0755 /opt/omneum-network /opt/omneum-network/libexec
sudo python3 -m venv /opt/omneum-network/venv
sudo /opt/omneum-network/venv/bin/python -m pip install --no-index --find-links /root/new-artifacts -r /root/repository/deploy/network/requirements.txt /root/new-artifacts/omneum-*.whl
sudo install -m 0755 /root/new-artifacts/omneumd /opt/omneum-network/libexec/omneumd
sudo install -m 0755 /root/repository/deploy/network/vm/renew-certificates.sh /opt/omneum-network/libexec/renew-certificates
sudo /opt/omneum-network/libexec/omneumd capabilities
sudo /opt/omneum-network/venv/bin/python -I -B -m omneum.network_deploy migrate --admin-dsn-file /root/network-admin.dsn --migrations /root/repository/migrations
sudo systemctl start omneum-network-evaluator omneum-network-ingestion omneum-network-enrollment
sudo /opt/omneum-network/venv/bin/python -I -B -m omneum.network_deploy preflight
```

`capabilities` must return `protected-voprf-v1`. Verify the new manifest before
stopping anything; save matching units/configuration privately and regenerate them
if changed, using step 5 and a fresh render directory. Any failure leaves the
services stopped or unhealthy; fix it or roll back before reopening contribution.

For code rollback, ensure `/opt/omneum-network-failed` does not already exist,
restore matching configuration/units if changed, then execute:

```bash
sudo systemctl stop omneum-network-ingestion omneum-network-enrollment omneum-network-evaluator
sudo mv /opt/omneum-network /opt/omneum-network-failed
sudo mv /opt/omneum-network-previous /opt/omneum-network
sudo systemctl daemon-reload
sudo systemctl start omneum-network-evaluator omneum-network-ingestion omneum-network-enrollment
sudo /opt/omneum-network/venv/bin/python -I -B -m omneum.network_deploy preflight
```

Never undo consent
withdrawal or credential revocation by restoring an old database merely to roll
back code. Use forward fixes when schema compatibility prevents code rollback.

Recover database backups into an isolated cluster first. Verify schema/grants,
receipts, revoked credentials, and consent state before redirecting the deployment.
Restrict the new cluster's trusted sources and verify its CA/DNS. Update the
server-only configuration and regenerate credential mounts; API release URLs and
VOPRF pins remain fixed. Re-run preflight and acceptance after any failover.

After creating and testing an isolated recovery cluster, migrate its empty database
with step 5 and point the private backup service file at that new cluster/CA.
Restore data without replacing fresh migration checksums or managed-service roles:

```bash
sudo env PGSERVICEFILE=/root/network-backup.pgservice PGSERVICE=network_backup pg_restore --data-only --exclude-schema=omneum_deploy --no-owner --no-acl --single-transaction --exit-on-error --dbname=service=network_backup /root/omneum-backups/network.dump
```

Verify the restored revocation/consent state before cutover. New cluster creation
requires separate approval; never test this restore against production.

Maintain an encrypted off-VM scalar recovery copy under a separate authorized
operator identity; no API account may decrypt it. Restore it into the evaluator's
0700 directory as a 0600 evaluator-owned file, and verify the recovered public key
matches the release. Never generate a replacement scalar under an existing key
version. For example, with an approved offline `age` recovery identity, install
the `age` command and encrypt directly to a private output file:

```bash
sudo age -r YOUR_RECOVERY_PUBLIC_KEY -o /root/omneum-backups/voprf.key.age /var/lib/omneum-network-crypto/voprf.key
sudo chmod 0600 /root/omneum-backups/voprf.key.age
```

On a fresh recovery VM, before provisioning any scalar:

```bash
sudo age --decrypt -i /root/offline-recovery.identity -o /root/omneum-backups/voprf.key /root/omneum-backups/voprf.key.age
sudo test ! -e /var/lib/omneum-network-crypto/voprf.key
sudo install -o omneum-network-crypto -g omneum-network-ipc -m 0600 /root/omneum-backups/voprf.key /var/lib/omneum-network-crypto/voprf.key
```

Protect the temporary plaintext recovery copy, verify the recovered public key,
and remove that temporary copy after successful recovery. VM snapshots containing an unencrypted scalar are not an acceptable
independent key backup. Verify the provider's snapshot encryption and access
policy, and test recovery before enabling such snapshots.

Schedule `python -m omneum.network_operator prune-quotas --retention-days 2` using
a private operator DSN on an authorized administration host. Monitor resource
peaks, disk usage, TLS expiry, JWKS refresh, DB connection limits, quota pruning,
and recovery jobs. Do not mount operator credentials in either API. Operator
issuance/recovery remains separate from normal self-service onboarding.
