
# Security Audit

**2026-10-10 · Local MCP, Context Graph, evaluator, and hosted Network**

Implementation review covering the local SQLite Context Graph, MCP transport, Rust VOPRF evaluator, Network contribution path, hosted ingestion service, and account-authenticated enrollment.

The initial audit identified and resolved six defects in filesystem permissions, schema validation, PostgreSQL transport, role privileges, and operator credential handling. Subsequent hardening added descriptor-based path validation, inherited-descriptor cleanup, self-service enrollment, installation-scoped authorization, consent enforcement, and credential lifecycle controls.

**Status:** Local security regressions, disposable PostgreSQL integration, production-feature Rust tests, and Linux evaluator isolation checks passed. Hosted Network enrollment and contribution passed disposable HTTPS integration tests. Production endpoints, identity provider, database, and live deployment isolation remain unverified.

## Findings

| Component | Finding | Resolution |
| --- | --- | --- |
| SQLite filesystem | Darwin ACL grants bypassed POSIX mode checks | Descriptor-based ACL validation for graph directories, database files, and SQLite sidecars |
| Operator credentials | Inherited ACLs could expose generated API credentials | Validate directory ownership, ACLs, and ancestors before creating credential files |
| SQLite migrations | Migration checksums did not detect modifications to the live schema | Validate schema objects against bundled migration snapshots before reading the migration ledger |
| PostgreSQL transport | Remote connections could use unverified TLS | Require `sslmode=verify-full` for remote database endpoints |
| PostgreSQL privileges | Startup checked the ingestion role name without validating effective privilege boundaries | Reject elevated role attributes, memberships, and application object ownership |
| Operator CLI | Mounted DSN files were documented but unsupported | Add file-based DSN loading with ambiguity rejection |
| Evaluator descriptors | Inherited descriptors above a reduced open-file limit could remain accessible | Close inherited descriptors independently of the current descriptor limit |
| Network enrollment | Installation credentials required operator provisioning | Add authenticated OIDC enrollment with account-owned installations and explicit consent |
| Credential lifecycle | Installation authorization lacked self-service renewal, rotation, and withdrawal | Add serialized lifecycle operations with transactional credential invalidation |
| Network authorization | Credential validity alone did not establish current account authorization | Enforce account suspension, installation ownership, active consent, and transactional authorization checks |

### Filesystem ACLs

`0700` directories and `0600` files do not override existing Darwin ACL grants.

A native reproduction confirmed that `chmod(0600)` preserved an `everyone allow read` ACL. Mode-only checks could therefore accept graph files accessible to another local user.

`omneum/storage/filesystem.py` validates directory descriptors using `O_DIRECTORY`, `O_NOFOLLOW`, and `O_CLOEXEC`. Each existing ancestor is checked before creating descendants. Caller-supplied `..` traversal and ancestor symlinks are rejected. Only the root-level macOS aliases `/tmp`, `/var`, and `/etc` are resolved.

Private directories require the current UID and mode `0700`. Ancestor ownership, mutation permissions, and Darwin ACL grants are checked before filesystem changes. Unsafe permissions are rejected rather than widened.

SQLite accepts regular, singly linked files owned by the current UID. Existing owned files are restricted to `0600` after ACL validation. Database, WAL, SHM, and journal files receive equivalent checks.

Operator credential output and the private enrollment credential store use the same validated directory traversal. Credential files are created atomically with mode `0600`.

**Tests:** `tests/test_local_security.py`, `tests/test_sqlite_filesystem.py`, `tests/test_sqlite_storage.py`

Coverage includes inherited ACL grants, writable ancestors, symlinks, hardlinks, unsafe ownership, credential output, SQLite sidecars, and restrictive deny ACL compatibility.

### SQLite schema integrity

Migration checksums protect bundled migration files, not the live database schema.

A writable database could contain injected triggers, modified views, removed indexes, or a substituted migration-ledger object without changing recorded migration checksums.

`omneum/storage/sqlite.py` derives expected schema snapshots from bundled migrations and validates live schema objects before reading migration history.

Persistent migrations execute fixed statements inside transactions. `executescript` is restricted to constructing the in-memory expected schema from release-owned migration constants.

SQLite connections disable extension loading, set `trusted_schema=OFF`, and enable defensive mode where supported.

Observation strings, claim values, references, retrieval fields, metadata, dependency data, and workspace identifiers use bound SQL parameters. Dynamic table and column names in `_identity` are restricted to an internal allowlist. Other dynamic SQL is limited to generated savepoint identifiers, a bounded integer busy timeout, fixed application identifiers, and internal source/claim table selection.

Tests cover injected triggers, modified tables, removed indexes, replaced migration ledgers, misleading `sqliteX` object names, adversarial values, and legacy migration compatibility.

Schema validation detects structural modification. It does not authenticate stored rows or prevent database snapshot rollback.

### PostgreSQL transport and privileges

Remote PostgreSQL connections require verified server identity.

`omneum/network_api.py` enforces `sslmode=verify-full` for remote hosts and addresses, including libpq environment variables, service files, and multiple-host configurations. `omneum/network_operator.py` applies the same requirement to remote operator connections.

Unix sockets and loopback test connections retain their supported local behavior.

The ingestion role is validated before the API begins serving requests. Rejected configurations include superuser privileges, role/database creation, replication, RLS bypass, additional memberships, and ownership of application schema objects.

The enrollment service uses a separate `omneum_enrollment` database role. Its privileges exclude Network report writes, principal rebinding, and account reactivation.

The ingestion role cannot provision accounts, installations, or consent grants. Enrollment cannot issue evaluator keys or modify accepted Network reports.

The Compose deployment uses verified PostgreSQL TLS with a database-only key volume.

**Tests:** `tests/test_network_bootstrap.py`, `tests/test_network_enrollment.py`

Disposable PostgreSQL instances exercised role privilege boundaries, indirect memberships, schema ownership, transport configuration, enrollment authorization, and ingestion persistence.

### Operator credential loading

`omneum/network_operator.py` accepts a PostgreSQL DSN from an environment value or mounted file. Providing both is rejected.

Operator credential output uses validated descriptor traversal and refuses unsafe ownership, ancestors, ACLs, or destination paths.

Operator-issued credentials remain supported for recovery and administration. Existing operator installations cannot be claimed through self-service enrollment.

The Compose smoke fixture includes the collections required by the frozen ingestion wire contract.

### Evaluator descriptor isolation

The previous inherited-descriptor cleanup relied on a descriptor limit that could be reduced by the launcher. Descriptors above that limit could remain open when the evaluator accessed its private scalar.

`src/daemon/os.rs` and `src/daemon/mod.rs` close inherited descriptors independently of the current open-file limit.

Linux uses `close_range` with a descriptor-directory fallback. macOS enumerates `/dev/fd`. Missing fallback metadata fails closed.

The production Linux isolation harness exercised high-numbered inherited descriptors and the `close_range` fallback against a freshly built evaluator binary.

## Security boundaries

### Local Context Graph

| Layer | Implementation | Enforcement |
| --- | --- | --- |
| SDK | `omneum/client.py`, `omneum/local_persistence.py` | Lazy local SQLite initialization |
| Paths | `omneum/paths.py` | Native user-data directory selection |
| Filesystem | `omneum/storage/filesystem.py` | Descriptor-based ownership, ACL, ancestor, and mount checks |
| Database | `omneum/storage/sqlite.py` | Private files, schema validation, parameterized SQL |
| Transactions | `omneum/storage/sqlite.py` | WAL, `BEGIN IMMEDIATE`, nested savepoints |

Graph directories use mode `0700`. Database files and SQLite sidecars use mode `0600`.

Storage rejects unsafe ownership, symlinks, unexpected hardlinks, nonregular files, and known remote mounts before SQLite opens the database.

SQL values use bound parameters. Dynamic identifiers are restricted to adapter-owned constants. User metadata is serialized as JSON.

Concurrent writers are serialized through SQLite transactions. Nested operations use savepoints. Failed evaluations roll back their data writes.

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

Managed-session isolation was tested independently of ordinary same-UID development fixtures.

### Rust evaluator

| Boundary | Implementation | Protection |
| --- | --- | --- |
| Python → daemon | `omneum/daemon.py` | Peer UID and pinned public-key checks |
| IPC authorization | `src/daemon/mod.rs` | Configured UID or managed-session primary GID |
| Socket lifecycle | `src/daemon/os.rs`, `src/daemon/mod.rs` | Validated paths, ownership, lock, and inode checks |
| Private scalar | `src/daemon/mod.rs`, `src/daemon/os.rs` | Separate service UID, exclusive provisioning, restricted filesystem access |
| Descriptor isolation | `src/daemon/os.rs` | Inherited-descriptor closure before key access |
| Cryptography | `src/voprf_core.rs` | RFC 9497 Ristretto255-SHA512 evaluation and verification |

The daemon exposes an AF_UNIX listener with two bounded operations: public-key retrieval and blinded evaluation.

It exposes no TCP listener, SQL interface, plaintext assertion processing, private-key retrieval, caller-selected scalar, or signing operation.

Server-side peer credentials authorize an explicitly configured UID or the reserved managed-session primary GID on Linux. Supplementary group membership alone does not authorize access.

Python verifies the connected peer UID and pinned public key on every exchange.

IPC uses fixed opcodes and frame lengths, bounded connections, deadlines, and rate limits. Endpoint validation rejects traversal, NUL bytes, boolean deadlines, and nonfinite deadlines.

Socket startup refuses active collisions. A daemon lock prevents concurrent ownership. Cleanup removes only the daemon's own socket inode.

The scalar requires a service-owned `0700` directory and singly linked `0600` file. Production serving rejects root and identical evaluator/client UIDs.

Linux hardening disables dumpability and privilege gain, rejects capabilities, and restricts systemd evaluator networking to AF_UNIX. Core dumps are disabled. Private scalar material is zeroized.

Malformed and identity Ristretto elements are rejected.

**Evidence:** `tests/test_daemon.py`, `tests/test_voprf_boundary.py`, Rust unit/property tests, and `tests/security/linux_isolation.py`.

The Linux production-binary harness verified cross-UID key isolation, peer denial, descriptor cleanup, and fallback behavior. Installed macOS launchd isolation remains unverified.

### Local → Network

Network contribution requires explicit opt-in. Local persistence completes independently of Network availability.

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
       | allowlisted structural projection
       v
HTTPS Network client
       |
       | verified Network VOPRF tokens
       v
Hosted ingestion API
```

| Component | Contract |
| --- | --- |
| `omneum/client.py` | Local persistence precedes optional contribution |
| `omneum/contributor.py` | Explicit opt-in and installation credential |
| `omneum/contribution/builder.py` | Allowlisted projection using an independent Network key |
| `omneum/contribution/config.py` | HTTPS client configuration |
| `omneum/contribution/network.py` | Response validation, VOPRF proof verification, redirect/proxy rejection |
| `omneum/network_release.py` | Release-owned endpoint, key, deployment, and consent pin validation |

The contribution builder excludes raw source identifiers, claim values, retrieved text, arbitrary metadata, local graph paths, and stored history.

The client sends blinded VOPRF elements and an allowlisted structural contribution containing finalized Network tokens. Source and claim inputs use separate cryptographic domains.

Network tokens are finalized only after proof verification against the pinned Network public key. The client rejects a Network key matching its local evaluator key.

HTTPS transports verify certificates, reject redirects, disable environment proxies, and validate bounded responses.

Ordinary SDK environment variables do not enable contribution. SDK callers explicitly supply a contribution configuration.

MCP contribution uses `omneum-contributor` with `OMNEUM_NETWORK_CONTRIBUTION=true`. After enrollment, the contributor can load an installation credential from the private CLI store. An explicitly configured `OMNEUM_API_KEY` takes precedence.

Only new occurrences supplied to contribution-enabled evaluations are projected. Stored history is not exported or automatically retried.

Network failures preserve successful local evaluation and persistence results.

**Tests:** `tests/test_contribution_security.py`, `tests/test_contributor.py`, `tests/test_sqlite_storage.py`

### Account enrollment

| Component | Responsibility |
| --- | --- |
| `omneum/enrollment.py` | Account authentication, installation ownership, consent, credential lifecycle |
| `omneum/enrollment_api.py` | Bounded HTTPS enrollment control plane |
| `omneum/onboarding.py` | OAuth device authorization, private credential storage, lifecycle requests |
| `omneum/cli.py` | `network enroll`, `renew`, `rotate`, `revoke`, `withdraw`, `status` |
| `migrations/production_007_self_service.sql` | Account bindings, installation ownership, consent, budgets, enrollment role |

`OIDCAuthenticator.authenticate` validates RS256 account access tokens against mounted public JWKS.

Validation requires the configured HTTPS issuer, dedicated audience, token expiry, issued-at and not-before claims, a maximum one-hour token lifetime, and the `omneum:enroll` scope.

The authenticator does not follow JWT-supplied key URLs. Public JWKS changes are loaded per request.

Account identity uses an issuer-scoped subject digest. Raw subject values, email addresses, account JWTs, and device authorization tokens are not persisted by the enrollment service.

Each account receives a private workspace. Enrollment requests cannot select an organization, workspace, or ingestion principal.

Installation ownership is immutable. Account and installation advisory locks serialize enrollment and credential lifecycle operations.

Duplicate enrollment is rejected. Existing operator-provisioned installations cannot be claimed by another account.

Enrollment permits ten installation slots per account and applies a ten-request-per-minute control-plane budget.

Explicit enrollment creates an affirmative `research_context_graph` consent grant bound to the current server consent version.

Renewal and rotation require authenticated account ownership, an enabled installation, and active consent. Both invalidate prior installation credentials in the same transaction.

Expired contribution credentials can be recovered through account authentication.

Withdrawal revokes installation consent and credentials and disables the installation. Revocation and withdrawal serialize against ingestion through the installation lock.

The CLI uses OAuth device authorization with release-owned endpoints and verification URI. It requires no local callback listener, account-token file, token-bearing URL, CLI token argument, or secret-bearing terminal output.

Installation credentials are stored atomically in a private `0600` file. Lifecycle operations use a local lock.

**Tests:** `tests/test_network_enrollment.py`, `tests/test_network_bootstrap.py`, `tests/test_contributor.py`

### Hosted ingestion

`omneum.transport.network.NetworkHTTPApp` exposes:

| Route | Operation |
| --- | --- |
| `POST /v1/voprf` | Blinded Network VOPRF evaluation |
| `POST /v1/contributions` | Authenticated structural report ingestion |

The ASGI adapter enforces TLS requirements, exact routes, media types, duplicate Authorization-header rejection, bounded headers and streamed bodies, receive deadlines, active-request capacity, and authenticated admission.

The application uses an `Authenticator`, `EvaluationService`, and `IngestionService`. The same credential authority must be used by the HTTP adapter and ingestion core.

A configured rate limiter admits requests only when `rate_limiter(principal_uuid, route)` returns exactly `True`.

Authentication and admission callbacks execute in worker threads. Request cancellation retains its capacity slot until blocking work completes.

Credentials are hashed and scoped to enabled principals with active consent. `omneum/ingestion/credentials.py` checks expiry, revocation, and account suspension.

`omneum/ingestion/postgres.py` owns installation/principal/workspace binding. Authorization is rechecked after acquiring the installation lock and before committing the ingestion transaction.

Ingestion enforces installation-scoped idempotency fingerprints and daily budgets. Credential rotation does not reset those budgets.

Replay conflicts are rejected. Uncertain acceptance is not treated as authorization for automatic retry.

Ingestion validates report structure and authorization. It does not cryptographically attest factual correctness, reported scores, source independence, or prior VOPRF token issuance.

Reports remain attributed, untrusted records. Network-derived signals are not introduced into local evaluation.

The Compose and Helm configurations separate API, enrollment, and evaluator identities and secrets. The optional Helm NetworkPolicy restricts configured ingress and egress when supported by an enforcing CNI.

**Tests:** `tests/test_ingestion.py`, `tests/test_network_http.py`, `tests/test_network_bootstrap.py`, `tests/test_network_enrollment.py`

## Deployment limitations

### Hosted Network

`_PRODUCTION_NETWORK` and `_PRODUCTION_ONBOARDING` remain unprovisioned. No production endpoint, deployment identity, Network public key, account provider, or release pin has been installed.

Public Network contribution requires:

- Production DNS, HTTPS routing, and trusted TLS termination
- Separate Network VOPRF scalar, public key, key version, and deployment identity
- PostgreSQL roles, migrations through `production_007_self_service.sql`, and isolated service credentials
- OIDC device-client registration, trusted issuer, audience, public JWKS, and enrollment scope
- Published consent terms and server consent version
- Release-owned endpoint, deployment, key, and onboarding pins
- Edge/IP admission controls, connection limits, and credential/body logging restrictions
- Live enrollment, VOPRF proof, ingestion, persistence, rotation, and withdrawal verification

Migration 007 must precede deployment of the new authentication, ingestion, and enrollment code.

`python -m omneum.network_release --require-provisioned` fails while production pins are absent.

The Docker Compose smoke test and disposable HTTPS enrollment integration passed. Neither establishes production Kubernetes isolation, live OIDC device authorization, or externally reachable Network availability.

The Helm chart includes an optional NetworkPolicy. Its enforcement depends on the deployed CNI, namespace configuration, database CIDR, and ingress controller.

Unauthenticated requests can consume bounded HTTP admission capacity before principal-level quotas apply. Edge admission controls must enforce additional source-level limits.

Installed macOS launchd service isolation and live Kubernetes/CNI isolation remain unverified.

### VOPRF and pseudonymous metadata

The evaluator cannot determine the plaintext or intended purpose of a blinded input.

An authorized malicious client can submit guessed inputs and consume its permitted evaluation budget. Repeated evaluations may enable dictionary or linkage analysis.

The Network scalar must remain separate from local evaluator keys and must not be reused for signing or unrelated protocols.

Ingestion validates token structure but does not establish that every submitted token was previously issued by the evaluator.

Pseudonymous source and claim tokens are stable and linkable. Source kinds, graph relationships, ownership equality, counts, reported scores, and qualifying time deltas remain potential reidentification signals.

Ingestion retains installation-linked receipts, server acceptance times, report history, and account bindings. Edge infrastructure can observe IP attribution.

Withdrawal revokes consent and credentials. It does not erase previously accepted reports.

The contribution allowlist constrains the honest client's serialized output. A malicious contributor can encode information in permitted numeric or token fields.

### Local storage

SQLite stores claims, identifiers, retrieval fields, and metadata in plaintext.

Filesystem isolation assumes the owning UID is trusted. Processes running under that UID, root, and the filesystem administrator can bypass application-level checks.

| Limitation | Responsibility |
| --- | --- |
| Disk encryption | Operating system / operator |
| Backup protection | Operator |
| Cloud-synchronized directories | Operator |
| Same-UID database modification | Outside the filesystem trust boundary |
| Database snapshot rollback | Not prevented by schema validation |
| Disk and history growth | No enforced storage/history quota |
| Windows DACL isolation | Not implemented |

Python's SQLite VFS opens pathnames rather than caller-owned descriptors. Same-UID pathname replacement between validation and SQLite open is not fully excluded.

Known remote mounts are rejected. Unknown filesystem types or unavailable mount metadata do not establish WAL-safe local locking.

Caller-selected PostgreSQL storage, evaluator integrations, and metrics recorders are outside the default SQLite privacy boundary.

Protected evaluator serving supports Linux and macOS. Windows storage does not enforce equivalent owner/DACL checks.

### Authentication and credential lifecycle

Offline JWT validation observes issuer-side revocation through token expiry unless an independent control-plane suspension applies. Accepted account access tokens have a maximum one-hour lifetime.

Administrative account suspension is checked during credential resolution and ingestion. Immediate serialization against in-flight writes requires acquiring the relevant installation locks.

An explicit `OMNEUM_API_KEY` overrides the private CLI credential store. A stale environment credential must be removed before a renewed CLI credential is used.

Credential renewal, rotation, revocation, and withdrawal require account authorization. Running MCP sessions must be restarted after credential changes.

The account provider controls signup, MFA, abuse prevention, and issuance of the enrollment scope.

### Key lifecycle and database operations

Scalar provisioning refuses overwrite. A running daemon holds one scalar for its lifetime.

Rotation requires a new scalar, matching public pin, key-version coordination, and a plan for previously generated graph identities. Changing the version label alone is not rotation.

Network key rotation must coordinate release-owned pins with ingestion's allowed key versions.

Admission budgets accumulate until operator pruning.

PostgreSQL startup privilege checks reject known elevated configurations but do not constitute a complete allowlist of every direct `GRANT`. Effective production permissions require review after migrations.

The operator owns database backups, retention and deletion policy, TLS, key rotation, quotas, ledger pruning, and production monitoring.

## Verification

| Target | Result | Coverage |
| --- | --- | --- |
| Full Python suite | **1,365 passed, 38 skipped** | Full suite before final operator and descriptor adjustments |
| Final affected security suite | **227 passed** | Enrollment, bootstrap, filesystem, SQLite, contributor, daemon |
| OAuth polling and CLI lifecycle regressions | **2 passed** | Device authorization timing and credential lifecycle |
| Rust production-feature tests | **15 passed** | Cryptography, peer authorization, rate controls |
| Docker Compose smoke | **Passed** | HTTPS, VOPRF proof, verified database TLS, ingestion, idempotency |
| Disposable HTTPS enrollment integration | **Passed** | Signed account tokens, consent, credential storage, VOPRF, persistence, rotation, withdrawal |
| Linux production-binary isolation harness | **Passed** | Cross-UID isolation, `openat2` fallback, inherited-descriptor closure |
| Helm lint/render | **Passed** | Enrollment deployment, Secrets, Services, optional NetworkPolicy |
| Docker image build | **Passed** | Fresh Linux production image |
| `cargo fmt --check` | **Passed** | Rust formatting |
| `git diff --check` | **Passed** | Patch whitespace |
| Python compilation | **Passed** | Changed Python modules |
| Production release-pin validation | **Expected failure** | Required production values absent |

The full Python suite ran against a newly initialized disposable PostgreSQL cluster. The cluster, generated databases, and roles were removed after testing.

The final affected suite ran after the operator compatibility and inherited-descriptor adjustments. The full 1,365-test suite was not repeated after those final changes.

The disposable HTTPS integration used signed RSA account tokens, actual control-plane and ingestion PostgreSQL roles, TLS, private CLI credential storage, independently keyed evaluators, verified VOPRF proofs, accepted report persistence, rotation, and withdrawal.

After withdrawal, a client holding a revoked credential retained successful local evaluation and persistence without another accepted Network report.

The Linux production-binary harness verified cross-UID key isolation, unauthorized peer denial, `openat2` fallback, and high-numbered inherited-descriptor closure, including the `close_range` fallback.

Native macOS ACL and peer-credential behavior was exercised on the audit workstation.

The separate public PostgreSQL/AGE storage integration paths were skipped without an isolated storage DSN.

**Not exercised:** live production OIDC login, production DNS/TLS routing, provisioned Network keys and pins, production PostgreSQL, Kubernetes/CNI enforcement, installed macOS launchd isolation, and measured two-minute onboarding.

## References

- [SQLite security guidance](https://www.sqlite.org/security.html)
- [SQLite trusted_schema](https://www.sqlite.org/pragma.html#pragma_trusted_schema)
- `deploy/README.md` — managed local evaluator deployment
- `docs/guides/deployment.md` — hosted Network deployment
- `docs/network-contribution.md` — contribution protocol and trust boundary
- `docs/storage.md` — local persistence and filesystem behavior
- `tests/security/` — Linux isolation harnesses
- `tests/test_network_enrollment.py` — account authorization and credential lifecycle
- `tests/test_network_bootstrap.py` — hosted service and PostgreSQL boundaries