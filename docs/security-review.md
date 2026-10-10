
# Security Audit

**2026-10-10 · Local MCP, Context Graph, evaluator, and hosted Network**

Implementation review covering the local SQLite Context Graph, MCP transport, Rust VOPRF evaluator, Network contribution path, and hosted ingestion service.

Six defects were identified and fixed. Regression tests, native filesystem checks, disposable PostgreSQL instances, and container isolation tests were used to verify the changes.

**Status:** Local security regressions passed. Hosted Network deployment was validated with Docker Compose, but production Network provisioning and live Kubernetes isolation remain unverified. This audit is not production deployment approval.

## Findings

| Component | Finding | Resolution |
| --- | --- | --- |
| SQLite filesystem | Darwin ACL grants bypassed POSIX mode checks | Descriptor-based ACL validation for graph directories, database files, and SQLite sidecars |
| Operator credentials | Inherited ACLs could expose generated API credentials | Validate the opened output directory before reserving credential files |
| SQLite migrations | Migration checksums did not detect modifications to the live schema | Validate schema objects against bundled migration snapshots before trusting the migration ledger |
| PostgreSQL transport | Remote connections could use unverified TLS | Require `sslmode=verify-full` for remote database endpoints |
| PostgreSQL privileges | Startup checked the ingestion role name without checking effective privilege boundaries | Reject elevated role attributes, memberships, and application object ownership |
| Operator CLI | Mounted DSN files were documented but unsupported | Add file-based DSN loading with ambiguity rejection |

### Filesystem ACLs

`0700` directories and `0600` files do not override an existing Darwin ACL.

A native reproduction confirmed that `chmod(0600)` preserved an `everyone allow read` ACL. The previous mode-only checks could therefore accept graph files accessible to another local user.

The fix adds descriptor-based ACL inspection in `omneum/storage/filesystem.py`. SQLite validates the private directory, ancestor mutation permissions, and database sidecars before opening storage.

Operator credential output uses the same protection. An unsafe directory is rejected before a credential file is created.

**Regression coverage:** `tests/test_local_security.py`

Includes inherited grants, writable ancestors, private graph objects, operator output, and compatibility with restrictive deny ACLs.

### SQLite schema integrity

Migration checksums protect migration files, not the live database schema.

An attacker able to modify the database could introduce triggers, replace views, or remove indexes without changing the recorded migration checksums. A substituted migration-ledger view could also execute SQL during ledger inspection.

`omneum/storage/sqlite.py` now derives expected schema snapshots from bundled migrations and validates live objects before reading migration history.

SQLite connections also disable extension loading, distrust schema SQL, and enable defensive mode where supported.

Tests cover:

- Injected triggers and modified tables
- Removed indexes and views
- Replaced migration ledgers
- Misleading `sqliteX` object names
- Legacy migration compatibility

These checks detect schema modification. They do not authenticate stored rows or protect against rollback to an older database snapshot.

### PostgreSQL transport and privileges

Remote PostgreSQL connections now require verified server identity.

`omneum/network_api.py` enforces `sslmode=verify-full` for remote hosts and addresses, including configurations involving libpq environment variables, service files, and multiple hosts. Unix sockets and loopback test connections retain their supported local behavior.

The ingestion role is checked before the API begins serving requests.

Rejected configurations include superuser privileges, role/database creation, replication, RLS bypass, additional role memberships, and ownership of application schema objects.

The Compose deployment uses verified PostgreSQL TLS with a database-only key volume.

**Tests:** `tests/test_network_bootstrap.py`

Real PostgreSQL instances were used to exercise privilege escalation, indirect memberships, schema ownership, and transport configuration.

### Operator credential loading

`omneum/network_operator.py` now accepts a DSN from an environment value or mounted file.

Providing both is rejected. The operator regression tests cover the CLI path, not only the configuration parser.

The Compose smoke fixture was also updated to include the collections required by the frozen ingestion wire contract.

## Security boundaries

### Local Context Graph

| Layer | Implementation | Enforcement |
| --- | --- | --- |
| SDK | `omneum/client.py`, `omneum/local_persistence.py` | Lazy local SQLite initialization |
| Paths | `omneum/paths.py` | Native user-data directory selection |
| Filesystem | `omneum/storage/filesystem.py` | Ownership, ACL, ancestor, and mount checks |
| Database | `omneum/storage/sqlite.py` | Private files, schema validation, parameterized SQL |
| Transactions | `omneum/storage/sqlite.py` | WAL, `BEGIN IMMEDIATE`, nested savepoints |

The graph directory is `0700`; database files and SQLite sidecars are `0600`.

Storage rejects unsafe ownership, symlinks, unexpected hardlinks, nonregular files, and known remote mounts. These checks run before SQLite opens the database.

SQL values use bound parameters. Interpolated identifiers are adapter-owned constants; savepoint names are generated internally. User metadata is serialized as JSON.

Concurrent writers are serialized through SQLite transactions. Nested operations use savepoints, and failed evaluations roll back their data writes.

The protected MCP process does not open the caller's Context Graph.

**Tests:** `tests/test_sqlite_storage.py`, `tests/test_observation_subtypes.py`, `tests/test_local_security.py`

### MCP transport

`omneum/transport/mcp.py` exposes three operations:

| Tool | Boundary |
| --- | --- |
| `ping` | Health and protocol response |
| `evaluate_voprf` | Blinded VOPRF evaluation |
| `evaluate_assertion` | Opaque context evaluation |

Request metadata must match server configuration. Invalid types and unexpected fields are rejected.

`omneum/transport/stdio.py` bounds incoming frames before parsing.

On managed Linux installations, `deploy/systemd/omneum-server.socket` uses a root-owned `0660` socket. Sessions run under separate dynamic UIDs with a reserved primary GID.

The managed-session isolation behavior was tested independently of ordinary same-UID development fixtures.

### Rust evaluator

| Boundary | Implementation | Protection |
| --- | --- | --- |
| Python → daemon | `omneum/daemon.py` | Peer UID and pinned public-key checks |
| IPC authorization | `src/daemon/mod.rs` | Configured UID or managed-session primary GID |
| Socket lifecycle | `src/daemon/os.rs`, `src/daemon/mod.rs` | Safe path traversal, ownership, lock, and inode checks |
| Private scalar | `src/daemon/mod.rs`, `src/daemon/os.rs` | Separate service UID, exclusive provisioning, restricted filesystem access |
| Cryptography | `src/voprf_core.rs` | RFC 9497 Ristretto255-SHA512 verification and evaluation |

Supplementary group membership does not authorize evaluator access.

IPC uses fixed opcodes and frame lengths, with bounded connections, deadlines, and rate limits.

Socket startup refuses active collisions. Cleanup removes only the daemon's own socket inode. The lock file is validated before use.

The scalar is provisioned exclusively under a private directory and is opened by the evaluator identity, not the Python serving process.

Linux hardening disables dumpability and privilege gain and rejects capabilities. Core dumps are disabled.

Malformed or identity Ristretto elements are rejected. The daemon exposes no signing operation, private-key export, caller-selected scalar, or plaintext evaluation input.

**Evidence:** `tests/test_daemon.py`, `tests/test_voprf_boundary.py`, Rust unit/property tests, and the production Linux isolation harness.

### Local → Network

Network contribution is opt-in. Local persistence runs independently of the Network path.

```text
SDK / MCP client
       |
       v
Local Context Graph
       |
       | explicit contribution configuration
       v
Contribution builder
       |
       | allowlisted projection
       v
HTTPS Network client
       |
       v
Hosted ingestion API
```

| Component | Contract |
| --- | --- |
| `omneum/client.py` | Local persistence precedes optional contribution |
| `omneum/contributor.py` | Explicit opt-in and API credential |
| `omneum/contribution/builder.py` | Allowlisted projection using an independent Network key |
| `omneum/contribution/config.py` | HTTPS client configuration |
| `omneum/contribution/network.py` | Response verification, VOPRF proof verification, redirect/proxy rejection |

The builder does not serialize the stored graph.

Environment values in the ordinary SDK do not silently enable contribution. A configured contributor session can submit new observations, subject to its authorization.

**Tests:** `tests/test_contribution_security.py`, `tests/test_sqlite_storage.py`

### Hosted ingestion

`omneum/transport/network.py` applies HTTP admission checks before persistence: TLS requirements, route and media-type validation, authorization-header constraints, bounded requests, deadlines, capacity limits, and principal quotas.

Credentials are hashed and scoped to enabled principals with active consent. Expiration and revocation are enforced by `omneum/ingestion/credentials.py`.

`omneum/ingestion/postgres.py` owns principal/workspace binding. Authorization is checked again after acquiring the installation lock, before the atomic ingestion transaction.

Persistence supports idempotency and quotas.

The Compose and Helm deployments separate API and evaluator identities and mounts. Capabilities are dropped in the supplied deployment configurations.

**Tests:** `tests/test_ingestion.py`, `tests/test_network_http.py`, `tests/test_network_bootstrap.py`, `tests/test_network_enrollment.py`

## Deployment limitations

### Hosted Network

Production endpoint and public-key pins are not provisioned in `omneum/contribution/network.py`.

Before enabling public Network contribution, provision and independently verify:

- Production domain and TLS configuration
- Independent Network scalar and public pin/version
- Credential issuance and consent authority

The Docker Compose deployment passed its smoke test. That does not establish readiness of a separately deployed Kubernetes cluster.

The Helm chart does not currently provide a NetworkPolicy or edge/IP rate limits.

Authentication occurs before principal quotas. Unauthenticated requests can consume the bounded 64-request capacity. Edge admission controls and evaluator egress restrictions must be verified on the deployment platform.

### VOPRF and pseudonymous metadata

The evaluator cannot determine the plaintext or purpose of a blinded input.

An authorized malicious client can submit guessed inputs and consume the shared evaluation budget. Repeated evaluations may permit dictionary or linkage analysis.

The VOPRF scalar must not be reused for signing or unrelated protocols.

Ingestion validates token structure; it does not establish the truth of submitted reports or cryptographically prove that every token was issued by the evaluator.

Network contributions also expose structural metadata. Source kinds, scores, parent counts, ownership relationships, and time deltas can carry sensitive information even without plaintext assertions.

The hosted service can observe account and network attribution. Pseudonymity is not anonymity.

### Local storage

SQLite stores claims, identifiers, retrieval fields, and metadata in plaintext.

Filesystem isolation assumes the owning UID is trusted. Processes running under that UID, and root, can bypass application-level checks.

| Limitation | Responsibility |
| --- | --- |
| Disk encryption | Operating system / operator |
| Backup protection | Operator |
| Cloud-synchronized directories | Operator |
| Same-UID database modification | Outside the filesystem trust boundary |
| Database snapshot rollback | Not prevented by schema validation |
| Disk and history growth | No enforced storage/history quota |
| Windows DACL isolation | Not implemented |

Same-UID pathname replacement between validation and SQLite open is not fully excluded.

Known remote mounts are rejected, but unavailable Linux mount metadata or unknown filesystem types cannot establish locality. A local directory synchronized by another application is still considered a local filesystem.

Caller-selected PostgreSQL storage, evaluator integrations, and metrics recorders are outside the default SQLite privacy boundary.

Protected evaluator serving supports Linux and macOS. Windows storage does not currently enforce equivalent owner/DACL checks.

### Key lifecycle and database operations

Scalar provisioning refuses overwrite. A running daemon holds one scalar for its lifetime.

Rotation requires a new scalar, matching public pin, version coordination, and a plan for previously generated graph identities. Changing the version label alone is not rotation.

Admission budgets accumulate until operator pruning.

PostgreSQL startup privilege checks reject known elevated configurations, but are not a complete allowlist of every direct `GRANT`. Production migrations and effective database permissions still require operator review.

## Verification

| Target | Result | Coverage |
| --- | --- | --- |
| Local boundary suite | **290 passed, 3 skipped** | SQLite, daemon IPC, MCP, contribution, hosted ASGI boundaries |
| SQLite security suite | **76 passed** | Schema, ACLs, migrations, concurrency |
| Native ACL/schema/subtype subset | **28 passed** | Targeted regression checks |
| PostgreSQL/bootstrap/operator | **113 passed** | Real disposable database, HTTPS, credentials, privileges |
| Rust production-feature tests | **15 passed** | Cryptography, peer authorization, rate controls |
| Docker Compose smoke | **Passed** | HTTPS, VOPRF proof, verified database TLS, ingestion, idempotent retry |
| Linux isolation harness | **Passed** | Distinct UIDs, key access, process memory, IPC, restart, path traversal |
| Helm lint/render | **Passed** | Chart syntax and template rendering |
| Compose validation | **Passed** | Deployment configuration |

Test counts overlap. They are not an aggregate test total.

The Compose smoke used a fresh isolated build and disposable PostgreSQL storage. The cross-UID probe denied private-key reads, `/proc/1/mem` access, and unauthorized evaluator IPC.

The Linux production-binary harness also exercised malformed ownership/modes, restart cleanup, and the `openat2` `ENOSYS` fallback.

Native macOS ACL and peer-credential behavior was exercised on the audit workstation.

**Not exercised:** live Kubernetes admission/network policy, production credentials, production database, and installed macOS launchd service isolation.

## References

- [SQLite security guidance](https://www.sqlite.org/security.html)
- [SQLite trusted_schema](https://www.sqlite.org/pragma.html#pragma_trusted_schema)
- `deploy/README.md` — managed local evaluator deployment
- `docs/guides/deployment.md` — hosted Network deployment
- `tests/security/` — Linux isolation harnesses