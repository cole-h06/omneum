# Omneum Network contribution

Local Context Graph persistence and Network contribution have separate
configurations. No environment variable enables contribution. Explicit opt-in:

```python
import os
from omneum import OmneumNetwork

network_contribution = OmneumNetwork.pseudonymous(
    api_key=os.environ["OMNEUM_API_KEY"],
)
# Pass explicitly to OmneumClient or open_stdio_client.
```

The factory currently fails closed because production infrastructure is not
provisioned. Before release, populate the release-owned `_PRODUCTION_NETWORK`
pins in `omneum/contribution/network.py` with verified HTTPS endpoints, deployment
UUID, independent Network VOPRF public key and version. No caller or environment
endpoint/key overrides are accepted. Coordinate key rotation with ingestion's
allowed versions and distribute authentic pins. The low-level
`NetworkContributionConfig`, `NetworkLinkageConfig`, `HTTPSNetworkEvaluator` and
`HTTPSContributionTransport` remain available for tests and custom deployments.

The SDK sends blinded VOPRF elements and an allowlisted structural contribution
with finalized Network tokens. Source identifiers, claim values, retrieved text,
arbitrary metadata and local graph contents are excluded. Proof verification
remains in linkage finalization. The client rejects a Network key matching its
local key. HTTPS transports disable redirects and environment proxies, and
bound and validate responses.

## Server integration

`omneum.transport.network.NetworkHTTPApp` is a standalone ASGI callable exposing
only `POST /v1/voprf` and `POST /v1/contributions`. Construct it in a server-owned
bootstrap with a separately provisioned Network `DeploymentState`, a local
public key for the separation check, an `Authenticator`, the existing
`IngestionService`, and a synchronous `rate_limiter(principal_uuid, route)`.
The limiter must return exactly `True` to admit a request. Implement persistent
or distributed quotas as appropriate. Use the same credential authority for
both authentication boundaries: ingestion also authenticates inside its core.
Authenticators own secret storage, scope, expiry, revocation and stable bindings.
Authentication and admission callbacks run in worker threads and must be thread
safe. Request cancellation retains its capacity slot until blocking work ends.

The app checks TLS, exact routes, media types, duplicate Authorization headers,
bounded headers and streamed bodies, a receive deadline, active-request capacity
and authenticated admission. It delegates cryptography to `EvaluationService`
and persistence to `IngestionService.handle()` / `persist()`. Its ASGI lifespan
shutdown closes the evaluation service. It exposes no MCP tools.

Run with TLS in the ASGI server or behind a trusted TLS terminator that securely
establishes `scheme=https`. This adapter does not parse forwarded headers.
Configure the server to trust only the terminator, reject spoofed forwarding,
and enforce connection/header limits before creating ASGI scopes. Add edge/IP
rate limits and disable credential/body logging throughout the deployment.
Provision server credentials, API key lifecycle, key isolation and operational
monitoring separately. Local installations receive API keys, never production
DB credentials.

## Database and trust boundary

Apply all relational production migrations in filename order through
`production_005_contribution_reports.sql`, including both 003 and 004 migrations.
The AGE migration provides a separate graph projection; ingestion only writes
relational tables. Later migrations already grant subtype INSERT/RETURNING
validation, deferred subtype checks, report validation and quota SELECT columns.
No extra grant is required. Permission tests exercise real role writes, replay,
token upserts and deferred triggers at commit.

Provision installations, workspaces, stable ingestion principals and active
explicit `research_context_graph` consent grants in the control plane. The
ingestion role cannot provision these or write published semantic information.

Contributions remain attributed reports. Ingestion does not prove VOPRF token
issuance and stores reported scores without attestation or recomputation.
Authentication and validation do not establish truth or source independence.
Network aggregation must preserve this distinction. Pseudonyms and structural
evidence remain linkable; this path does not claim anonymity.
