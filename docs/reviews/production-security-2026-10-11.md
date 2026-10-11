# Production deployment and security review — 2026-10-11

## Launch assessment

**NO-GO for public contributions and fresh-user onboarding.** This is an
implementation review with isolated adversarial tests and bounded production
probes, not a completed production security certification. No confirmed Critical
Omneum authentication or key-extraction vulnerability was demonstrated. Several
confirmed readiness blockers and a vulnerable dependency inventory remain on
the VM. Passing tests does not establish production confinement, provider policy,
capacity, recovery readiness, or resistance to determined collusion.

Public contributions have not been enabled by this work. No runtime rebuild,
reinstallation, database mutation, credential rotation, Network scalar
provisioning, SSH change, or Nginx change was performed on production.

## Evidence and boundaries

- Reviewed source: `4f17cb85b747d00e81d68d03d59c9bfa3da3bc50`.
- Installed Omneum: `1.0.3`; installed PyJWT: `2.13.0`.
- Four installed Python modules matched reviewed-source SHA-256 values before
  local changes: deployment tooling, release validation, Network pins, onboarding.
  This is not proof that every installed file matches the artifact bundle.
- Installed evaluator capability: `protected-voprf-v1`.
- Three non-login service identities exist; ingestion and evaluator share their
  reserved primary IPC group, enrollment has a separate group.
- Nginx is active. Omneum units are not installed, and no application TCP
  listeners were observed. Public listeners were SSH, HTTP, HTTPS, and loopback DNS.
- The supplied SSH key now authenticates. Noninteractive sudo is unavailable.
  Root-only configuration, artifact manifest, database state and scalar-file
  metadata still require the operator's interactive read-only audit.
- Twelve sequential production requests, separated by one second, used missing
  or invalid authorization, GET, and a query string across the three routes.
  **Every response was 503.** These results do not verify application rejection.
  No valid credentials, oversized requests, concurrency bursts or destructive
  payloads were used against production.
- Auth0 discovery advertised the expected issuer, signing-key endpoint, token
  endpoint, RS256, and device grant. Application registration, audience access,
  scope grants, token lifetime and signup policy remain unverified.

## Verification results

| Check | Result | Limits |
| --- | --- | --- |
| Final affected Python security suite | 469 passed, 1 skipped | Local disposable PostgreSQL 15; real production PostgreSQL 18.6 not tested |
| Skipped test | Alternate local PostgreSQL persistence | Requires `OMNEUM_TEST_POSTGRES_DSN`; hosted Network database tests were executed |
| Rust production-feature suite | 15 passed | Includes RFC 9497 vector, malformed transcripts, peer authorization and rate controls; bounded property testing |
| Isolated Linux deployment harness | Passed | Real TLS Nginx/backend/DB, role grants, three Unix identities, migration ledger, synthetic identity provider, lifecycle and persistence |
| Isolated protected-evaluator harness | Passed | Cross-UID key/config/memory/ptrace denial, unauthorized IPC, symlinks, descriptor cleanup and fallback, restart/shutdown |
| RustSec audit | 0 advisories across 85 locked dependencies | Advisory DB commit `7eebec69c352c7191b1f13eb95dd510eeca5d1de`, updated 2026-10-09 |
| Original Python pinned-dependency audit | 14 advisories in PyJWT 2.13.0 | Inventory finding; applicability reviewed below |
| Prepared Python dependency audit | 0 advisories across 42 evaluated packages | PyJWT 2.15.0; not applied to VM; scanner uses current local platform markers |
| Fresh public pip installation | Failed | `No matching distribution found for omneum`; public PyPI JSON returned 404 |
| Exact-version public daemon release | Unavailable to unauthenticated fetch | GitHub API for `cole-h06/omneum` tag `v1.0.3` returned 404; may be unpublished or private |
| Production authorization, persistence, confinement | Pending | Maintenance ingress returns 503; root audit and real provider login required |

The first suite run had four failures in a documentation example test, caused by
its obsolete section names and assumption that the edited configuration guide
contained two JSON examples. The test now executes the actual documented
credential-store-based configuration and its opt-out/error variants. Existing
user documentation edits were preserved. The final suite includes five new
adversarial account-token regression cases.

## Findings

### F-01 — High — fresh-user release path unavailable (confirmed readiness blocker)

**Locations:** `pyproject.toml`, `docs/guides/installation.md:18`,
`omneum/installation.py:50`, `omneum/installation.py:237`.

**Reproduction:** In a new local virtual environment run `python -m pip install
omneum`. It fails before onboarding. Read-only requests to
`https://pypi.org/pypi/omneum/json` and
`https://api.github.com/repos/cole-h06/omneum/releases/tags/v1.0.3` return 404.

**Impact:** A new public user cannot reach protected local installation, opt-in,
account login or contribution using the documented flow. This is not an
authentication bypass.

**Fix:** Prepare and review a publicly available, pinned package and matching
exact-version daemon assets for each supported platform, with verified release
provenance. Publication is a separate operator-authorized action. Retest in a
clean supported client environment without modifying an existing local daemon.
The current VM runtime is not to be rebuilt or reinstalled for this task.

### F-02 — High — production pins and application services absent (confirmed readiness blocker)

**Locations:** `omneum/contribution/network.py:83`, `omneum/onboarding.py:44`,
`omneum/network_release.py:6`, `omneum/network_deploy.py:pins_match`.

**Reproduction:** Installed `python -I -B -m omneum.network_release
--require-provisioned` fails. Both installed pin constants are `None`.
`systemctl is-enabled` reports the three Omneum units as not found. Empty public
API requests return maintenance 503 rather than authenticated application 401.

**Impact:** No real hosted acceptance is possible. The fail-closed release guard
is functioning; it must not be bypassed with contributor environment overrides.

**Fix:** Verify existing key state first. After approval, provision the Network
scalar only if absent, retain its public output, set stable deployment ID and
positive key version, and record Auth0 Native Application client ID and published
consent URL/version. Build literal `_ProductionNetwork` and `OnboardingPins`
values using those independently verified public values. The installed Python
files can receive a reviewed, backed-up source-only patch; native runtime
artifacts remain installed. Record before/after file digests and patch provenance.
Apply equivalent public pins to the acceptance client and eventual public release.
Run release validation and `pins_match`; do not substitute runtime configuration
loading for release-owned constants.

`local_public_key` in server configuration must be a valid, distinct public key
from an approved local domain. The client also compares the actual local key
against the Network key. No production scalar or DSN belongs in a release pin.

### F-03 — Medium — preflight incompatible with existing Certbot site (confirmed deployment defect; fix prepared)

**Locations:** `omneum/network_deploy.py:nginx_config`, `service_checks`,
new `nginx_certbot_site` and `check_nginx`; `tests/test_network_deploy.py`.

**Reproduction:** Original preflight requires byte equality with the generated
standalone `/etc/nginx/conf.d/omneum-network.conf`. The active VM uses
`sites-enabled/omneum-network`, with Certbot-managed certificate paths, SSL
options and HTTP redirect. Installing both would overlap API server blocks.

**Impact:** Operators could be encouraged to replace or conflict with a working
HTTPS/renewal configuration. The mismatch itself is not a demonstrated exploit.

**Prepared fix:** `render --nginx-layout certbot` emits application integration
inside the existing Certbot site layout and separate HTTP-scope rate-limit zones.
It preserves Certbot lineage paths, SSL-options include, DH parameters, IPv4/IPv6
listeners and the original redirect. Preflight validates exact application
directives, ownership, active include paths, duplicate API server names, and the
TLS protocol floor. Backend certificate/hostname verification, header clearing,
request-size controls and logging restrictions remain present. Standalone
deployment remains supported. No alternate ACME bootstrap is installed.

**Status:** Local rendering/tamper regressions, actual isolated Nginx syntax and
reload, and synthetic hosted lifecycle/proof acceptance through the Certbot
layout passed. The production site still requires the operator's actual
`nginx -t`, diff review, renewal validation, and real-provider acceptance. The
staged patch has not been applied to the runtime.

### F-04 — Medium — known-vulnerable PyJWT inventory (confirmed dependency finding; exploit not demonstrated)

**Locations:** `deploy/network/requirements.txt:29`, `uv.lock` PyJWT entry,
`omneum/enrollment.py:50`, installed VM package `PyJWT==2.13.0`.

**Reproduction:** `pip-audit --disable-pip --no-deps -r
deploy/network/requirements.txt -f json` reports 14 advisories on the original
pin, including conditional algorithm confusion, JWKS-client behavior,
options-dict reuse, parsing and OKP private-JWK issues.

**Applicability:** Omneum uses only RS256, constructs an RSA key object from
mounted public JWKS, rejects attacker-directed `jku`/`x5u` and critical
extensions, does not use `PyJWKClient`, caps tokens at 8192 bytes, catches all
validation exceptions, and creates fresh options for each verification. It does
not accept JWT-based raw-token revocation or OKP private proof keys. The tested
preconditions for the reported forgery/bypass paths are absent. A Critical
library advisory is not evidence of a Critical Omneum vulnerability.

**Fix prepared:** Update only PyJWT to 2.15.0 in the lockfile and deployment
requirements. The exact required uv version 0.12.10 produced the lockfile update.
Repeated advisory scan: zero known advisories. Repeated authentication, consent,
cross-account, ingestion and local-privacy regressions passed using an isolated
2.15.0 package. The VM remains on 2.13.0; prepare a hash-verified offline package
update and rollback for operator review before changing production dependencies.

**Sources:** [maintainer options-dict advisory](https://github.com/jpadilla/pyjwt/security/advisories/GHSA-gvp8-978c-rx2q),
[maintainer algorithm-confusion advisory](https://github.com/jpadilla/pyjwt/security/advisories/GHSA-ffc3-869f-jxw9),
[maintainer OKP advisory](https://github.com/jpadilla/pyjwt/security/advisories/GHSA-x33g-cr3x-6449).

### F-05 — Medium — token/source/evidence fabrication and Sybil limits (confirmed design limits; no authoritative-score exploit)

**Locations:** `omneum/ingestion/validation.py:decode`,
`omneum/ingestion/postgres.py:_write_run`, `omneum/enrollment.py:EnrollmentService.handle`,
`tests/test_network_trust.py:88`.

**Reproduction:** Isolated `test_fabricated_sources_do_not_make_authenticated_consensus`
submits 30 randomly formed 64-byte source tokens and inflated client reports.
The report is accepted. Source classifications and structural evidence are
also contributor-supplied. Separate accounts can obtain separate installations;
ten lifetime slots per identity does not prove ten independent people.

**Impact:** Contributors can lie or coordinate within finite budgets. VOPRF
proof verification by the honest client does not prove issuance of arbitrary
finalized tokens received by ingestion, nor truth/ownership/independence of
reports. A malicious client could intentionally encode information in allowed
fields. No server-side reliability consensus, public publication, or cross-report
overwrite was demonstrated: records remain installation-attributed reports,
with immutable report relationships, replay deduplication and budgets.

**Fix/recommendation:** Keep intake explicitly untrusted. Verify Auth0 signup
abuse controls before public admission. Do not interpret reported scores,
ownership flags or source counts as authoritative Network reliability. Any future
aggregation requires a reviewed Sybil/poisoning threat model and contributor
weighting/admission policy. Cryptographic issuance evidence would require a
separate protocol design; do not invent a server-side check of opaque VOPRF output.
If launch requires manipulation-resistant global reliability, this is a blocking
product/security requirement beyond the current implementation.

### F-06 — Medium — linkability, inference and retained reports (confirmed privacy properties; policy verification pending)

**Locations:** `omneum/contribution/builder.py`, `omneum/contribution/linkage.py`,
`omneum/onboarding.py:220`, `omneum/enrollment.py:handle`,
`docs/security-review.md` VOPRF/privacy limitations.

**Reproduction:** Honest-client wire tests show stable Network source/claim
tokens and allowed relationship/evidence fields; hosted lifecycle tests retain
accepted reports after withdrawal. An authorized user can request evaluations
of guessed low-entropy inputs within their quota.

**Impact:** Blinding conceals raw input from the evaluator; pseudonymous reports
are linkable and are not anonymous or immune to inference. Consent withdrawal
blocks future contributions and renewal, but does not erase accepted history.
Infrastructure can observe source IP and request timing. These properties must
be disclosed in the published versioned consent terms before admission.

**Fix/recommendation:** Verify terms covering linkability, metadata, retention,
withdrawal and deletion policy. Preserve distinct local/Network keys and bounded
evaluation quotas. Confirm no sensitive access/body/header logging in production.
Do not promise automatic deletion or arbitrary malicious-client exfiltration
prevention. Local honest-client tests found no automatic raw-context/history export.

### F-07 — Medium — release trust concentrated in one delivery origin (confirmed design limit)

**Locations:** `omneum/installation.py:download`, `verify_checksum`,
`deploy/network/vm/build-artifacts.sh`, `deploy/network/vm/install.sh`.

**Reproduction:** Public installer obtains an archive and its checksum manifest
from the same exact-version GitHub release. An origin/release-account attacker
able to replace both can provide a matching malicious archive. No compromise was
observed. The VM deployment uses a separately supplied trusted manifest digest;
that root-only verification is still pending.

**Impact:** SHA-256 detects mismatches and corrupted assets but does not provide
independent publisher identity if the delivery origin is compromised. Broad
public-package dependency ranges also resolve differently over time, unlike the
locked server environment. Initial-install and same-schema upgrade paths assume
a trusted operator and authenticated artifacts; there is no automatic universal
rollback mechanism for database/key changes.

**Recommendation:** Retain authenticated manifest digests and source-tree
mapping, review release account protection, and consider signed/attested assets
with an independently distributed trust root. Audit resolved public-client
dependencies as well as the locked server. Do not label a reconstructed Git
revision alone as independent source provenance. Do not reuse the initial
installer as an upgrade command. This is not a confirmed distribution compromise.

### F-08 — Low — onboarding diagnosis and manual MCP opt-in (confirmed usability limits)

**Locations:** `omneum/cli.py:_network_manage`, `omneum/onboarding.py:_manage`,
`omneum/contributor.py:network_configuration`, `docs/guides/configuration.md:118`.

**Reproduction:** Even after package/local-daemon installation, the user must
run `omneum network enroll`, approve research consent, complete the Auth0 device
flow, choose `omneum-contributor`, set the explicit opt-in flag, and reconnect
MCP. CLI failure messages combine provisioning, login, consent and storage
causes; an environment API-key override can silently take precedence over a
renewed private-store credential. The source's precise unprovisioned-release
exception is hidden by the CLI's generic message.

**Impact:** Users may repeatedly retry login for a release-configuration problem,
forget the contributor command or restart, or retain a stale override. The
additional consent/opt-in choices are intentional privacy protections, not steps
to remove without redesign.

**Recommendation:** Publish one tested fresh-user sequence, show public-only
diagnostic categories, explain the contributor command and credential-store
precedence, and provide an explicit opt-in configuration helper if desired.
Users must never manually configure production endpoints, keys, audiences or
database credentials. Operator provisioning of release constants is the required
fix for those values. Generic exceptions should continue to suppress secrets.

## Security acceptance matrix

| Area | Inspected/tested | Remaining production gate |
| --- | --- | --- |
| Fresh-user onboarding | Installer exact-version checks, extraction safety, device polling and pinned destination, private credential store, consent denial, MCP JSON entrypoint | Public package/assets, clean supported-client install, real device login, successful ingestion |
| Authentication/authorization | Expired/forged/wrong issuer/audience, missing scope, `none`/HS confusion, optional `nbf`, unknown/ambiguous keys, hostile key URLs, cross-account lifecycle, installation/workspace binding, concurrent revocation, replay, privilege grants | Real Auth0 tokens and two dedicated test identities on deployed services |
| Privacy/consent | Default opt-out, no call on consent denial, raw-field allowlist, only new occurrences, no credential forwarding to protected local service, secret-safe tool/HTTP errors, withdrawal/revocation, local persistence during outage | Versioned published terms, mounted credential isolation, restricted production logs and real withdrawal |
| VOPRF | RFC 9497 vector, element/proof lengths and malformed transcripts, key/public pin mismatch, domain separation, protected Linux peer/key boundaries, restart persistence | Existing scalar metadata, approved one-time provisioning if absent, live proof verification as ingestion UID, enrollment denial |
| Ingestion | Invalid JSON, duplicate JSON keys, collections/body bounds, invalid endpoints/evidence, schema extras, arbitrary/copy tokens as untrusted reports, idempotency conflicts, quotas/concurrency, cross-run foreign keys and immutable previous reports | Bounded authenticated synthetic contributions and administrative persistence verification |
| Infrastructure | Generated unit syntax, loopback TLS and Nginx controls, DB role tests, IPC identity/group checks, isolated admission/resource tests | Actual systemd namespace/UID/credential mounts, firewall/cloud DB trusted sources, TLS renewal, logging, backup/recovery, resource headroom |
| Supply chain | Lockfile advisory scans, exact-version public release lookup, archive-layout checks, four module hashes, installed evaluator capabilities | Root manifest authentication and all artifact checksums, build snapshot mapping, complete installed inventory, patched dependency installation |
| Adversarial production | Twelve bounded unauthenticated requests | Repeat after services start; bounded authenticated negative matrix only after test account/consent approval |

VOPRF output is intentionally deterministic for a fixed key/input. Re-evaluating
a blinded input is not itself an authentication replay vulnerability. Admission
still requires valid installation authorization; repeated evaluation is subject
to quotas. Contribution replay is installation-scoped and content-fingerprinted,
and credential renewal/rotation does not reset that identity or its budgets.
Account JWTs are bearer tokens reusable during their valid lifetime; provider
revocation is not an immediate online introspection mechanism.

## Operator execution sequence

Proceed in small reviewed batches, collecting public-only results between them:

1. Interactive read-only root audit: authenticate artifact manifest, checksums,
   build metadata, source/runtime hashes, owners/modes, public configuration,
   presence of administrator DSN/CA/scalar, and current Nginx syntax.
2. Read-only database inspection with the existing private administrative DSN:
   verified TLS, schema/ledger checksums, role attributes/grants, logging policy,
   backup readiness. Do not rerun DDL or alter passwords during inspection.
3. Review configuration candidates and public pins. Request separate approval
   for one-time Network key provisioning if no scalar exists. Never provision
   over an existing or partially written key; do not read/export it as root/API.
4. After backup and explicit migration/role-password approval, use repository
   `generate-dsns` as appropriate and the supported `migrate` command. The runner
   excludes AGE and reapplies role password verifiers even when migration files
   are already recorded; **rerunning it is a credential operation**.
5. Apply reviewed Python-only deployment/pin patches and approved offline PyJWT
   update with backups and recorded digests. Do not rebuild/reinstall the runtime.
6. Install CA/TLS credential copies, validated JWKS, public environment, units,
   and the reviewed integration into the existing Certbot site. Preserve its
   certificate/renewal path. No overlapping site or ACME bootstrap.
7. Start privately confined services, run installed-release and production
   preflight, inspect actual systemd/IPC/network controls, test certificate
   renewal, and run safe rejection checks. Do not enable broad contributions.
8. Obtain approval for retained synthetic installation/report, credential
   lifecycle operations, and dedicated real-provider test accounts. Run hosted
   acceptance and the expanded bounded authenticated negative tests.
9. Run clean pinned-client onboarding and local-outage acceptance. Obtain explicit
   launch approval only after all security gates pass and remaining design risks
   are understood. If any required check is unavailable, retain NO-GO.

Database credentials remain exclusively in root-private server files and systemd
credential mounts. Local MCP clients use only authenticated HTTPS installation
credentials, never production database credentials.
