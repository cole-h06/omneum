# Omneum Network Contribution

Omneum Network accepts pseudonymous Context Graph contributions from explicitly enrolled installations. Hosted enrollment is currently restricted to approved closed-beta participants. Local persistence remains independent of Network submission. Contributions pass through the HTTPS ingestion API; local MCP installations never connect directly to `omneum_prod`.

## Client Configuration

| Interface | Configuration | Default |
|---|---|---|
| Python SDK | `network_contribution` | `None` |
| MCP | `omneum-contributor` | Local-only |
| Enrollment | `omneum network enroll` | Not enrolled |
| Credential | `network/credential.json` or `OMNEUM_API_KEY` | None |

### Python SDK

```python
import os
from omneum import OmneumNetwork

network_contribution = OmneumNetwork.pseudonymous(
    api_key=os.environ["OMNEUM_API_KEY"],
)
```

Pass `network_contribution` explicitly to `OmneumClient` or `open_stdio_client`. SDK environment variables do not enable submission.

`OmneumNetwork.pseudonymous()` reads release-owned parameters from `omneum/contribution/network.py`. `_PRODUCTION_NETWORK` must contain verified values before the production factory can be used.

| Parameter | Requirement |
|---|---|
| Ingestion endpoint | HTTPS |
| VOPRF endpoint | HTTPS |
| Deployment ID | Network deployment UUID |
| Public key | Independent Network VOPRF key |
| Key version | Accepted by the ingestion service |

The factory rejects caller-supplied endpoint and key overrides. An unprovisioned configuration fails closed.

Custom deployments can construct `NetworkContributionConfig` using `NetworkLinkageConfig`, `HTTPSNetworkEvaluator`, and `HTTPSContributionTransport`.

### MCP

Approved beta participants can install Omneum and enroll their local installation:

```bash
omneum network enroll
```

Enrollment uses account authentication and an explicit `research_context_graph` consent grant. The CLI stores the installation credential under the native Omneum configuration directory:

```text
network/credential.json
```

Enable contribution in the MCP host:

```json
{
  "mcpServers": {
    "omneum": {
      "command": "omneum-contributor",
      "env": {
        "OMNEUM_NETWORK_CONTRIBUTION": "true"
      }
    }
  }
}
```

Restart the MCP connection after updating its configuration.

`omneum-contributor` exposes `evaluate_observations`. Only observations supplied in the current tool call are eligible for submission. It does not export existing Context Graph history or forward the local `omneum-server` tools.

An explicit `OMNEUM_API_KEY` overrides the stored credential. The contribution flag must still be `true`; credentials alone do not enable submission.

See [Configuration](guides/configuration.md#network-contribution) for local MCP and SDK settings.

## Contribution Protocol

The client blinds identifiers before requesting Network VOPRF evaluation. `HTTPSNetworkEvaluator` sends blinded group elements to the Network evaluator. The client verifies the returned proof and finalizes Network linkage tokens locally.

The contribution transport submits the allowlisted structural payload using those tokens.

| Data | Network submission |
|---|---|
| Pseudonymous source and claim tokens | Included |
| Approved assertion observations | Included |
| Approved dependency and evaluation reports | Included |
| Raw source identifiers | Excluded |
| Claim values | Excluded |
| Retrieved text and documents | Excluded |
| Arbitrary metadata | Excluded |
| Local Context Graph history | Excluded |

The client rejects a Network public key matching its local evaluator key. Local and Network VOPRF deployments must use separate private keys.

HTTPS transports enforce endpoint validation, bounded responses, and response-schema checks. Redirects and environment proxy routing are disabled.

Network VOPRF key rotation changes derived tokens. Update the release-owned public parameters and ingestion's accepted key versions together.

## Server Integration

`omneum.transport.network.NetworkHTTPApp` is a standalone ASGI application. It exposes no MCP transport or tools.

| Method | Route | Handler |
|---|---|---|
| `POST` | `/v1/voprf` | `EvaluationService` |
| `POST` | `/v1/contributions` | `IngestionService.handle()` / `persist()` |

Construct `NetworkHTTPApp` in a server-owned bootstrap with:

| Dependency | Requirement |
|---|---|
| `DeploymentState` | Separately provisioned Network VOPRF deployment |
| Local public key | Used to reject Network/local key reuse |
| `Authenticator` | Shared credential authority for both routes |
| `IngestionService` | Contribution validation and persistence |
| `rate_limiter(principal_uuid, route)` | Synchronous authenticated admission callback |

Use `ingestion.authenticator` as the HTTP application's authenticator. Construction rejects a different credential authority or a VOPRF key version absent from `ingestion.allowed_key_versions`.

The rate limiter must return exactly `True` to admit a request. Implement persistent or distributed quotas at the deployment boundary. Authentication and admission callbacks execute in worker threads and must be thread-safe. Cancellation retains the active-request capacity slot until blocking work completes.

### Request Handling

`NetworkHTTPApp` enforces:

| Boundary | Validation |
|---|---|
| Transport | HTTPS ASGI scheme |
| Routing | Exact method and path |
| Authorization | Bearer credentials; duplicate header rejection |
| Headers | Size limits and supported media types |
| Body | Streamed size limits and receive deadline |
| Concurrency | Active-request capacity |
| Admission | Authenticated principal and rate limiter |

Cryptographic operations are delegated to `EvaluationService`. Contribution validation and database writes remain in `IngestionService`.

ASGI lifespan shutdown closes the evaluation service.

### TLS and Reverse Proxy

Run the application behind a trusted TLS terminator or an ASGI server with native TLS.

`NetworkHTTPApp` checks the ASGI `scheme` and does not parse forwarded headers. The reverse proxy must establish `scheme=https` without accepting spoofed client forwarding headers.

Enforce connection and header limits at the edge. Disable credential and request-body logging. Apply IP-level rate limits independently of the application's authenticated admission limits.

Local installations receive scoped API credentials, never PostgreSQL connection strings or production database credentials.

## Production Database

The hosted database is `omneum_prod`. Apply the relational migration sequence declared in `omneum.network_deploy.MIGRATIONS` through `production_007_self_service.sql`.

| Schema | Contents |
|---|---|
| `control` | Accounts, installations, workspaces, consent, credentials, ingestion authorization |
| `network` | Shared pseudonymous sources, claims, observations, evaluation reports, dependency reports |
| `public` | Separately authorized semantic publication |
| `private` | Reserved for future hosted Cloud storage |

`network` is the authoritative hosted relational Context Graph. User-controlled private Context Graphs remain in local SQLite or application-managed PostgreSQL.

### Migrations

The production sequence includes both the 003 and 004 migrations and continues through `production_007_self_service.sql`.

Do not apply `production_002_context_graph.sql` to DigitalOcean Managed PostgreSQL. It requires Apache AGE, which is not supported by the managed database configuration.

The AGE migration defines graph labels, not the authoritative relational storage. Production AGE synchronization, population, and rebuild paths are not implemented. No copy into the local `public.*` Context Graph schema is required.

Later relational migrations include subtype INSERT/RETURNING permissions, deferred subtype validation, report constraints, and quota-related SELECT privileges. The migration sequence supplies the required grants.

Database permission tests cover role-scoped writes, replay handling, token upserts, and deferred validation at transaction commit.

See [Server Deployment](guides/deployment.md#database-layout) for migration execution and the managed PostgreSQL deployment.

### Database Roles

| Role | Responsibility |
|---|---|
| `omneum_enrollment` | Account-authenticated installation enrollment and credential lifecycle |
| `omneum_ingestion` | Authorized contribution persistence |
| Migration administrator | Schema migrations and database provisioning |

The ingestion role cannot create installations, grant consent, or publish semantic information.

Provision stable ingestion principals and installation-to-workspace bindings through the control plane. Contribution requires an active `research_context_graph` consent grant.

Self-service enrollment uses `omneum_enrollment`. Operator provisioning remains available for administration and recovery.

Apply migration 007 before deploying the updated enrollment or ingestion services. Existing operator-issued credentials remain supported.

## Ingestion and Authorization

`IngestionService` authenticates each contribution, validates its schema, checks installation authorization, and writes accepted reports to `network.*`.

| Control | Enforcement |
|---|---|
| Authentication | Credential resolves to a stable principal |
| Installation binding | Principal is authorized for the installation and workspace |
| Consent | Active `research_context_graph` grant |
| VOPRF version | Configured `allowed_key_versions` |
| Payload | Explicit structural field allowlist |
| Replay | Canonical contribution idempotency |
| Quota | Per-installation admission budgets |

Installation-level advisory transaction locks serialize concurrent contributions from the same installation.

Authorization and budget checks run again inside the ingestion transaction before persistence. Successful ingestion returns an acceptance receipt.

Credential lifecycle, consent, and admission limits are server-owned. The local MCP opt-in flag does not create authorization or consent.

## Trust Boundary

The Network stores attributed contributor reports, not verified facts.

`NetworkHTTPApp` authenticates callers and enforces request boundaries. `IngestionService` validates accepted payloads and persists their reported values. Neither component independently attests that submitted VOPRF tokens were issued by the Network evaluator.

Reported reliability scores are stored without server-side recomputation or attestation. Authentication does not establish assertion accuracy or source independence.

Network-wide aggregation must retain contributor attribution and distinguish reported evidence from independently verified results.

Pseudonymous identifiers and structural observations remain linkable across authorized contributions. Network contribution is privacy-preserving linkage, not anonymity.
