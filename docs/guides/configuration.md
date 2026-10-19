
# Configuration

Omneum uses SQLite for local Context Graph persistence by default. The MCP server connects to a protected VOPRF evaluator. Network contribution is disabled unless explicitly configured.

| Component | Default |
|---|---|
| MCP command | `omneum-server` |
| MCP transport | stdio |
| VOPRF evaluator | Managed local daemon |
| Context Graph storage | SQLite |
| Network contribution | Disabled |

## MCP Server

The local MCP server exposes three tools over stdio.

| Tool | Description |
|---|---|
| `ping` | Check server availability |
| `evaluate_context` | Evaluate opaque source–claim relationships |
| `evaluate_voprf` | Evaluate blinded VOPRF elements |

After installation, configure the MCP host to launch `omneum-server`:

```json
{
  "mcpServers": {
    "omneum": {
      "command": "omneum-server"
    }
  }
}
```

The server uses the installed evaluator daemon for VOPRF operations. The daemon holds the private key; MCP clients do not receive it.

### VOPRF Evaluator

Omneum implements RFC 9497 using the Ristretto255-SHA512 ciphersuite.

| Parameter | Type | Description |
|---|---|---|
| `key_version` | `int` | Evaluator key version |
| `blinded_element` | `bytes` | 32-byte blinded group element |
| `public_key` | `bytes` | 32-byte evaluator public key |
| `ciphersuite` | `str` | Ristretto255-SHA512 |
| `mode` | `str` | Verifiable OPRF |

The evaluator rejects invalid group elements, unsupported ciphersuites, and mismatched key versions.

Local and Network VOPRF deployments use separate keys. A Network public key matching the local evaluator key is rejected.

For managed service installation and daemon administration, see [Installation](installation.md) and [`deploy/README.md`](../../deploy/README.md).

## Local Context Graph

`LocalPersistenceConfig` configures local observation storage. SQLite is the default backend.

### Storage Backends

| Backend | Implementation | Description |
|---|---|---|
| SQLite | `SQLiteStorage` | Local file-backed database |
| PostgreSQL | `PostgresStorage` | Application-managed PostgreSQL database |
| Disabled | `local_persistence=None` | Evaluation without stored observations |

Network contribution does not change the selected local storage backend.

### SQLite

Create a persistence configuration using the default SQLite backend:

```python
from omneum.local_persistence import LocalPersistenceConfig

persistence = LocalPersistenceConfig()
```

SQLite creates the database on first use.

| Platform | Default database path |
|---|---|
| macOS | `~/Library/Application Support/Omneum/context.db` |
| Linux | `~/.local/share/omneum/context.db` |

For a new default graph with unsafe data-directory ancestors, Omneum uses
`~/.omneum/data/context.db`. Existing graphs and explicit paths are never
silently relocated; shared directory permissions are preserved.

To use another database path, construct a `SQLiteStorage` adapter with the desired location and pass it to `LocalPersistenceConfig`.

The Omneum process requires write access to the database directory.

### PostgreSQL

`PostgresStorage` provides local observation persistence using PostgreSQL.

Create the database and apply the required schema migrations before enabling the adapter. Switching from SQLite does not migrate existing observations.

Local PostgreSQL databases are managed by the application operator. They do not connect directly to the hosted `omneum_prod` database or receive production credentials.

### Disable Persistence

Set `local_persistence=None` when constructing the client to evaluate without retaining observations.

Disabling local persistence does not implicitly enable or disable Network contribution. The two settings are independent.

## Network Contribution

Network contribution is disabled by default. Hosted Network enrollment is currently limited to approved closed-beta participants. The standard `omneum-server` remains local-only and does not upload Context Graph history.

The optional `omneum-contributor` MCP adapter exposes `evaluate_observations`. It accepts new assertion occurrences, performs local evaluation, and can submit an allowlisted structural contribution when explicitly enabled.

| MCP command | Tools | Network behavior |
|---|---|---|
| `omneum-server` | `ping`, `evaluate_context`, `evaluate_voprf` | Local-only |
| `omneum-contributor` | `evaluate_observations` | Optional contribution of new observations |

The contributor adapter does not forward the standard MCP server's tools. Existing local observations are not exported.

### MCP Configuration

For approved beta participants, install Omneum normally, then enroll the installation:

```bash
omneum network enroll
```

Enrollment requires account authentication and an explicit consent grant. The CLI stores the installation credential in an owner-only `network/credential.json` file under the Omneum configuration directory.

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

Restart the MCP connection after changing the configuration.

| Setting | Behavior |
|---|---|
| Flag absent or `false` | Local evaluation only; no Network submission |
| `OMNEUM_NETWORK_CONTRIBUTION=true` | Enable contribution using an enrolled credential |
| `OMNEUM_API_KEY` | Explicit credential override; takes precedence over the private store |

An API key alone does not enable contribution. The adapter requires the explicit opt-in flag.

Credentials should remain in the private configuration directory or the MCP host's supported secret store, outside source control.

Only new `evaluate_observations` calls are eligible for contribution. The adapter does not read or upload existing Context Graph history.

### Python SDK

Python clients configure Network contribution through the `network_contribution` argument on `OmneumClient` or `open_stdio_client`.

| Parameter | Type | Default |
|---|---|---|
| `network_contribution` | `NetworkContributionConfig \| None` | `None` |

For approved beta participants using a provisioned Network, the high-level factory constructs the release-pinned contribution configuration:

```python
import os
from omneum import OmneumNetwork

network = OmneumNetwork.pseudonymous(
    api_key=os.environ["OMNEUM_API_KEY"],
)
```

Pass `network` as the client's `network_contribution` argument.

The factory uses release-owned HTTPS endpoints and Network VOPRF public parameters. It does not accept caller-supplied endpoint or key overrides.

MCP environment variables do not automatically enable contribution for Python SDK clients.

### Contribution Status

The contributor adapter reports Network submission separately from local evaluation.

| Status | Meaning |
|---|---|
| `disabled` | Contribution is not enabled |
| `configuration_unavailable` | Required credentials or verified Network parameters are unavailable |
| `failed_or_uncertain` | Submission failed or its outcome could not be established |
| `submitted` | Ingestion returned a validated acceptance receipt |

Local evaluation can succeed even when contribution fails. Failed or uncertain submissions are not automatically retried.

Contribution requires a provisioned Network deployment, compatible release-owned public parameters, an authorized installation, and active consent.

For enrollment, credential lifecycle, contribution payloads, and custom Network configuration, see [Network Contribution](../network-contribution.md).

## Troubleshooting

| Error | Check |
|---|---|
| MCP server fails to start | Installed Python environment and `omneum-server` entry point |
| VOPRF evaluation fails | Evaluator service, public-key pin, key version, and ciphersuite |
| SQLite initialization fails | Database path and directory permissions |
| PostgreSQL persistence fails | Database connection, schema migrations, and role privileges |
| No local observations | `LocalPersistenceConfig` and selected storage backend |
| Network contribution disabled | `OMNEUM_NETWORK_CONTRIBUTION` setting |
| Network configuration unavailable | Enrolled credential and release-provisioned Network parameters |
| Network submission fails | Network availability, credential authorization, and consent status |

For managed daemon installation, see [Installation](installation.md). For production infrastructure and ingestion-service administration, see [Server Deployment](deployment.md).