# Configuration

Configuration reference for the Omneum MCP server, local Context Graph, VOPRF evaluator, and Omneum Network.

| Component | Configuration | Default |
|---|---|---|
| MCP server | `omneum-server` | local stdio |
| VOPRF evaluator | Local evaluator daemon | Local deployment |
| Context Graph | `LocalPersistenceConfig` | SQLite |
| Storage backend | `SQLiteStorage`, `PostgresStorage` | SQLite |
| Network contribution | `network_contribution` | `None` |
| Network authentication | API key | Required for contribution |

## MCP Server

The MCP server exposes three tools over stdio.

| Tool | Description |
|---|---|
| `ping` | Check server availability |
| `evaluate_context` | Evaluate opaque assertions using BRAID |
| `evaluate_voprf` | Evaluate blinded VOPRF elements |

After `omneum install`, configure your MCP host to launch `omneum-server`.
The optional `omneum-contributor` adapter is described below.

The MCP server uses a local evaluator daemon for VOPRF operations. The evaluator process holds the private key.

### VOPRF Evaluator

Omneum implements RFC 9497 with the Ristretto255-SHA512 ciphersuite.

| Parameter | Type | Description |
|---|---|---|
| `key_version` | `int` | Evaluator key version |
| `blinded_element` | `bytes` | 32-byte blinded group element |
| `public_key` | `bytes` | 32-byte evaluator public key |
| `ciphersuite` | `str` | Ristretto255-SHA512 |
| `mode` | `str` | Verifiable OPRF |

The evaluator rejects invalid group elements, unsupported ciphersuites, and mismatched key versions.

Local and Network VOPRF deployments use separate keys. The client rejects a Network public key matching its local evaluator key.

## Local Context Graph

`LocalPersistenceConfig` configures local observation storage. SQLite is the default backend.

### Storage Backends

| Backend | Implementation | Description |
|---|---|---|
| SQLite | `SQLiteStorage` | Local file-backed database |
| PostgreSQL | `PostgresStorage` | External PostgreSQL database |
| Disabled | `local_persistence=None` | Evaluation without stored observations |

### SQLite

Create a persistence configuration:

```python
from omneum.local_persistence import LocalPersistenceConfig

persistence = LocalPersistenceConfig()
```

SQLite creates the database on first use.

Default database paths:

| Platform | Path |
|---|---|
| macOS | `~/Library/Application Support/Omneum/context.db` |
| Linux | `~/.local/share/omneum/context.db` |

To use another path, construct a `SQLiteStorage` adapter with the database location and pass it to `LocalPersistenceConfig`.

The Omneum process needs write access to the database directory.

### PostgreSQL

`PostgresStorage` implements local observation storage using PostgreSQL.

Create the database and apply the required migrations before enabling persistence. The adapter does not migrate observations from an existing SQLite database.

Local PostgreSQL installations use application-managed databases. They do not receive credentials for `omneum_prod`.

### Persistence Behavior

| Configuration | Behavior |
|---|---|
| SQLite | Store observations in a local database file |
| PostgreSQL | Store observations in an application-managed database |
| No persistence | Evaluate without retaining observations |
| Network contribution enabled | Keep the configured local persistence behavior |

Changing storage backends does not transfer existing observations.

## Omneum Network

### Enable Network contribution (MCP)

Install Omneum normally with `omneum install`, using a package that includes the
`omneum-contributor` command. Local users need no Docker, Kubernetes, Helm,
PostgreSQL or Network database credentials. The normal `omneum-server` command
and its opaque-token tools remain local-only.

For MCP hosts that want to evaluate new observations and optionally contribute,
configure the local adapter directly in the host's MCP settings. No Python
programming is required. This exact local-only JSON configuration is covered by
an entrypoint/stdio regression test:

```json
{
  "mcpServers": {
    "omneum": {
      "command": "omneum-contributor",
      "env": {
        "OMNEUM_NETWORK_CONTRIBUTION": "false"
      }
    }
  }
}
```

Use the executable's absolute path if it is not on your host's PATH. The adapter
locates its sibling `omneum-server` executable when available and preserves the
protected local evaluator's process and Unix-socket isolation. It retains default
SQLite Context Graph persistence independently of contribution.

Once verified production Network parameters ship in a release, opt in with only
an explicit flag and an enrolled API credential:

```json
{
  "mcpServers": {
    "omneum": {
      "command": "omneum-contributor",
      "env": {
        "OMNEUM_NETWORK_CONTRIBUTION": "true",
        "OMNEUM_API_KEY": "YOUR_NETWORK_API_CREDENTIAL"
      }
    }
  }
}
```

The exact JSON above is also tested through stdio, using its placeholder
credential to verify safe behavior while production parameters are unprovisioned.
Replace the placeholder with your enrolled credential for actual contribution.
Keep credentials in private MCP configuration or your host's supported secret
store, outside source control; never put them in command arguments. Restart the
MCP connection after changing settings. The credential is not forwarded to the
protected local MCP child or evaluator daemon.

Contribution is disabled when the flag is absent or `false`; an API key alone
has no effect. Only `true` enables it. The adapter calls the existing
`OmneumNetwork.pseudonymous()` factory. It accepts no contributor-controlled
Network URL, key, deployment ID or database DSN. Python SDK defaults remain
unchanged: SDK users still pass `network_contribution` explicitly.

The adapter exposes `evaluate_observations`, accepting new assertion occurrences
and the existing dependency-estimator settings through its MCP input schema.
Observation fields are `observation_id`, `source_kind`, `source_identifier`,
`entity_namespace`, `entity`, `attribute`, `value` and timezone-aware
`observed_at`. Arbitrary metadata, retrieved text, history-export flags and
other additional fields are rejected. Advanced provenance and retrieval inputs
remain available through the SDK. The original opaque-token `evaluate_context`
tool does not submit contributions.

Local evaluation results are returned to the local MCP host. Only the existing
allowlisted structural contribution is sent to the Network, using independent
VOPRF tokens with verified proofs. Raw identifiers, claim values, retrieved text,
metadata and local linkage tokens are not uploaded. Only occurrences in the new
tool call are eligible; the adapter never reads or exports existing Context Graph
history. Failed or uncertain submissions are not retried automatically.

| `network_contribution` result | Meaning |
| --- | --- |
| `disabled` | Explicit opt-out or default local-only operation |
| `configuration_unavailable` | Invalid opt-in flag, missing/malformed credential, unprovisioned parameters or incompatible Network pin; local evaluation continues and no Network request is made |
| `failed_or_uncertain` | Network rejection/outage, invalid proof or uncertain ingestion; local evaluation and persistence completed |
| `submitted` | Ingestion returned a validated acceptance receipt |

Local service or local storage failures remain evaluation errors; a successful
local result does not imply successful contribution. Network authentication,
enabled principal enrollment, active consent, payload validation and admission
budgets remain server-owned. Explicit MCP opt-in does not create a consent grant.

**Launch blocker:** `_PRODUCTION_NETWORK` is currently `None`. Operators must
provision the HTTPS endpoints, independent Network key, deployment identity and
key version, ship verified release-owned pins, and enroll credentials with an
active consent grant before production contribution works. Until then, local
use continues with `configuration_unavailable` when opt-in is requested.

Network ingestion stores untrusted contributor reports. The adapter verifies
VOPRF responses, but ingestion does not independently attest token issuance or
reported scores; these reports must not be presented as verified consensus.

### Enable Network contribution (Python SDK)

Network contribution is configured through the `network_contribution` argument on `OmneumClient` or `open_stdio_client`.

| Parameter | Type | Default | Description |
|---|---|---|---|
| `network_contribution` | `NetworkContributionConfig \| None` | `None` | Enables contribution when supplied with a valid configuration |

SDK contribution requires explicit configuration. Environment variables do not
enable SDK submission automatically; the MCP adapter settings above apply only
to `omneum-contributor`.

### API Key

Set the Network API key:

```bash
export OMNEUM_API_KEY="your-api-key"
```

Create the Network configuration:

```python
import os
from omneum import OmneumNetwork

network = OmneumNetwork.pseudonymous(
    api_key=os.environ["OMNEUM_API_KEY"],
)
```

Pass the configuration to the client:

```python
client = OmneumClient(
    config,
    evaluator,
    network_contribution=network,
)
```

`OmneumNetwork.pseudonymous()` uses release-provisioned Network parameters. These include the HTTPS ingestion endpoint, VOPRF endpoint, deployment identifier, public key, and key version.

The factory currently fails closed until the production Network infrastructure and release-owned parameters are provisioned.

Setting `OMNEUM_API_KEY` alone has no effect on contribution behavior.

### Advanced Configuration

`NetworkContributionConfig` supports custom Network deployments.

| Parameter | Type | Description |
|---|---|---|
| `linkage` | `NetworkLinkageConfig` | Network VOPRF public parameters |
| `evaluator` | `NetworkEvaluator` | Evaluates blinded VOPRF elements |
| `transport` | `HTTPSContributionTransport` | Sends authenticated contributions |

Example HTTPS transport:

```python
from omneum.contribution.config import (
    NetworkContributionConfig,
    HTTPSContributionTransport,
)

transport = HTTPSContributionTransport(
    endpoint="https://network.example.com/ingest",
    bearer_token="your-api-key",
    timeout_seconds=10.0,
)

config = NetworkContributionConfig(
    linkage=network_linkage,
    evaluator=network_evaluator,
    transport=transport,
)
```

`network_linkage` and `network_evaluator` must use the same Network VOPRF deployment.

The example endpoint is a placeholder for a custom deployment. The high-level factory does not accept caller-supplied endpoint or key overrides.

### HTTPS Transport

| Parameter | Type | Default | Description |
|---|---|---|---|
| `endpoint` | `str` | Required | HTTPS ingestion URL |
| `bearer_token` | `str` | Required | Authentication credential |
| `timeout_seconds` | `float` | `10.0` | HTTP request timeout in seconds |

`HTTPSContributionTransport` validates the endpoint during construction.

The transport rejects non-HTTPS URLs, embedded credentials, query strings, and URL fragments. Redirects and environment proxy routing are disabled.

Responses are checked for valid status codes and receipt structure. Bearer credentials are excluded from object representations.

### Network VOPRF

`NetworkLinkageConfig` defines the public parameters for pseudonymous linkage.

| Parameter | Type | Description |
|---|---|---|
| `key_version` | `int` | Network VOPRF key version |
| `public_key` | `bytes` | 32-byte Network VOPRF public key |

The client blinds source and claim identifiers before calling the Network evaluator.

The evaluator processes the blinded elements. The client verifies the returned proof and finalizes the Network tokens locally.

Network tokens depend on the Network VOPRF key. Key rotation changes the resulting identifiers.

The client, evaluator, and ingestion service must use compatible key versions.

### Contribution Payload

Network contributions use an explicit field allowlist.

| Data | Contribution |
|---|---|
| Pseudonymous source identifiers | Included |
| Pseudonymous claim identifiers | Included |
| Approved structural observations | Included |
| Approved dependency reports | Included |
| Raw source identifiers | Excluded |
| Raw claim values | Excluded |
| Retrieved documents or text | Excluded |
| Arbitrary metadata | Excluded |
| Local database contents | Excluded |

The contribution validator rejects fields outside the allowlist.

### Contribution Modes

| Local persistence | Network contribution | Behavior |
|---|---|---|
| Disabled | Disabled | Evaluate without persistence or submission |
| Enabled | Disabled | Store observations locally |
| Disabled | Enabled | Submit eligible Network contributions |
| Enabled | Enabled | Store locally and submit eligible contributions |

Pass `network_contribution` when constructing the client. Eligible `evaluate_context()` calls then submit contributions.

## Network Ingestion

The Network ingestion service authenticates contributions and writes accepted reports to the production Network schema.

| Component | Implementation | Description |
|---|---|---|
| Authentication | `Authenticator` | Resolve credentials to principals |
| Validation | `IngestionService` | Validate contribution schema and authorization |
| Persistence | `omneum.ingestion.postgres` | Store accepted Network contributions |
| Control plane | `control` schema | Installation and workspace authorization |
| Context Graph | `network` schema | Pseudonymous observations and reports |

### Authentication

`Authenticator` implements credential resolution:

```python
class Authenticator(Protocol):
    def authenticate(self, credential: str, /) -> UUID | None:
        ...
```

Each request requires a valid bearer credential.

The ingestion service resolves the credential to a principal and checks its installation and workspace authorization.

Network contribution also requires an active consent grant for the `research_context_graph` purpose.

### PostgreSQL Permissions

Production ingestion uses the `omneum_ingestion` database role.

The role has access to the Network tables required for contribution persistence. Local MCP installations submit through the authenticated ingestion API.

Installation-level advisory transaction locks serialize concurrent contributions from the same installation.

The ingestion transaction rechecks authorization and contribution budgets before writing.

### Ingestion Validation

| Control | Description |
|---|---|
| Authentication | Require an authorized principal |
| Installation binding | Verify the principal's installation |
| Consent | Require an active contribution grant |
| Key version | Accept configured Network VOPRF versions |
| Payload size | Reject oversized requests |
| Schema | Reject unsupported contribution fields |
| Idempotency | Detect repeated canonical contributions |
| Daily budget | Enforce per-installation submission limits |

Successful ingestion returns a receipt.

Scores are stored as contributor-reported values. Ingestion does not recompute evaluations or attest the underlying assertions.

Authentication establishes contributor authorization. It does not establish the reliability of submitted evidence.

## Configuration Scope

| Configuration | Scope | Description |
|---|---|---|
| MCP transport | Server process | MCP communication transport |
| Local VOPRF key | Evaluator deployment | Local identifier derivation |
| Local persistence | Client | Observation storage |
| Storage adapter | Client | SQLite or PostgreSQL backend |
| Network contribution | Client | Contribution submission |
| API key | Application | Network authentication |
| Network VOPRF key | Network deployment | Shared pseudonymous linkage |
| Ingestion authorization | Production control plane | Contributor permissions |

Storage backend changes require a separate data migration when existing observations must be retained.

Network VOPRF key rotation requires updated public parameters and compatible ingestion key-version settings.

## Troubleshooting

| Error | Check |
|---|---|
| MCP server fails to start | Python environment and server entry point |
| VOPRF evaluation fails | Evaluator daemon, key version, ciphersuite |
| SQLite initialization fails | Database path and directory permissions |
| PostgreSQL persistence fails | Connection, schema migrations, role privileges |
| No local observations | `LocalPersistenceConfig` |
| No Network contributions | `network_contribution` configuration and production Network provisioning |
| HTTP 401 | API credential and principal authorization |
| HTTP 400 | Contribution schema and key version |
| HTTP 413 | Contribution payload size |
| HTTP 503 | Ingestion service or database availability |
| Network linkage fails | Evaluator public key and key version |
| Contribution rejected after authentication | Installation binding, consent, daily budget |