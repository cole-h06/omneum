# Ping

`ping` returns the MCP server's active deployment metadata and protocol configuration.

## Check Server Status

Call `ping` with an empty argument object. The tool is registered in `omneum/transport/mcp.py` and requires no input fields.

```python
import asyncio

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

async def main():
    server = StdioServerParameters(command="omneum-server")

    async with stdio_client(server) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            result = await session.call_tool("ping", {})
            if result.isError:
                raise RuntimeError(result.content)

            print(result.structuredContent)

asyncio.run(main())
```

`omneum-server` must be installed and configured. See [Installation](../guides/installation.md).

## Response

`omneum/tools/ping.py` returns the deployment metadata from `DeploymentState` and the protocol constants.

```json
{
  "status": "ok",
  "protocol_version": "v1",
  "algorithm_version": "omneum-v2",
  "deployment_id": "urn:uuid:01234567-89ab-cdef-0123-456789abcdef",
  "voprf_key_version": 1,
  "voprf_mode": "voprf",
  "voprf_ciphersuite": "ristretto255-SHA512",
  "linkage_encoding_version": 1,
  "configuration_fingerprint": "<deployment configuration fingerprint>"
}
```

The deployment ID, key version, and fingerprint above are examples. Read the installed server's values rather than hardcoding them.

| Field | Type | Source |
| --- | --- | --- |
| `status` | `str` | `"ok"` |
| `protocol_version` | `str` | `config.PROTOCOL_VERSION` |
| `algorithm_version` | `str` | `config.ALGORITHM_VERSION` |
| `deployment_id` | `str` | `DeploymentState.deployment_id` |
| `voprf_key_version` | `int` | `DeploymentState.voprf_key_version` |
| `voprf_mode` | `str` | `config.VOPRF_MODE` |
| `voprf_ciphersuite` | `str` | `oprf.CIPHERSUITE` |
| `linkage_encoding_version` | `int` | `linkage.ENCODING_VERSION` |
| `configuration_fingerprint` | `str` | `DeploymentState.configuration_fingerprint` |

`PingResponse` is defined in `omneum/models.py`. The MCP handler returns a dictionary directly.

## Deployment Configuration

Direct `evaluate_voprf` and `evaluate_context` requests must use the active deployment parameters returned by `ping`.

```python
config = result.structuredContent

request_metadata = {
    "protocol_version": config["protocol_version"],
    "deployment_id": config["deployment_id"],
    "voprf_key_version": config["voprf_key_version"],
    "voprf_mode": config["voprf_mode"],
    "voprf_ciphersuite": config["voprf_ciphersuite"],
    "linkage_encoding_version": config["linkage_encoding_version"],
}
```

`configuration_fingerprint` identifies the deployment's public configuration. Clients can compare it against a previously trusted fingerprint to detect configuration changes.

`ping` does not return the VOPRF private scalar or establish that the evaluator can successfully process a blinded element.

## Implementation

```text
omneum/
├── config.py                 # Protocol constants, DeploymentState
├── models.py                 # PingResponse
├── linkage.py                # Linkage encoding version
├── oprf.py                   # VOPRF ciphersuite
├── tools/
│   └── ping.py               # handle_ping()
└── transport/
    └── mcp.py                # MCP tool registration
```

`handle_ping(state)` reads the current deployment state without invoking the Rust evaluator or opening the local Context Graph.

For evaluator verification, use [Evaluate VOPRF](evaluate-voprf.md). See [Errors](errors.md) for MCP transport and application failures.