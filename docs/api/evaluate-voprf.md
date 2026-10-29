# Evaluate VOPRF

The Python SDK performs VOPRF blinding and verifies the server's DLEQ proof before finalizing linkage tokens. `OmneumClient.evaluate_context()` invokes this protocol internally.

## Evaluate a Blinded Element

Direct MCP clients retrieve the active deployment parameters through `ping` before submitting a blinded element.

```python
result = await session.call_tool("ping", {})
config = result.structuredContent

print(config["deployment_id"])
print(config["voprf_key_version"])
print(config["voprf_ciphersuite"])
```

Create the blinded element using an RFC 9497-compatible VOPRF client with the `ristretto255-SHA512` ciphersuite.

```python
result = await session.call_tool(
    "evaluate_voprf",
    {
        "protocol_version": config["protocol_version"],
        "deployment_id": config["deployment_id"],
        "voprf_key_version": config["voprf_key_version"],
        "voprf_mode": config["voprf_mode"],
        "voprf_ciphersuite": config["voprf_ciphersuite"],
        "linkage_encoding_version": config["linkage_encoding_version"],
        "blinded_element": blinded_element,
    },
)

if result.isError:
    raise RuntimeError(result.structuredContent)

evaluation = result.structuredContent
```

`blinded_element` must be a canonical, unpadded base64url encoding of a 32-byte Ristretto255 element. Generate it with the client-side VOPRF blinding operation; do not submit the plaintext input.

Verify `evaluation["proof"]` against the deployment's pinned public key before unblinding and finalizing. The proof does not replace deployment identity or key-version validation.

## MCP Request

The registered tool accepts `EvaluateVOPRFRequest` from `omneum/models.py`.

```json
{
  "protocol_version": "v1",
  "deployment_id": "urn:uuid:01234567-89ab-cdef-0123-456789abcdef",
  "voprf_key_version": 1,
  "voprf_mode": "voprf",
  "voprf_ciphersuite": "ristretto255-SHA512",
  "linkage_encoding_version": 1,
  "blinded_element": "<base64url-encoded blinded element>"
}
```

| Field | Type | Validation |
| --- | --- | --- |
| `protocol_version` | `str` | Matches server protocol |
| `deployment_id` | `str` | Canonical deployment UUID URN |
| `voprf_key_version` | `int` | `1` through `2³² - 1`; matches active key |
| `voprf_mode` | `str` | `voprf` |
| `voprf_ciphersuite` | `str` | `ristretto255-SHA512` |
| `linkage_encoding_version` | `int` | `1` |
| `blinded_element` | `str` | Canonical unpadded base64url, 32 decoded bytes |

All seven fields are required. Unknown fields and type coercion are rejected.

Deployment identity and VOPRF configuration are checked against the active server configuration before blinded-element evaluation.

## MCP Response

The response follows `EvaluateVOPRFResponse` in `omneum/models.py`.

```json
{
  "protocol_version": "v1",
  "deployment_id": "urn:uuid:01234567-89ab-cdef-0123-456789abcdef",
  "voprf_key_version": 1,
  "voprf_mode": "voprf",
  "voprf_ciphersuite": "ristretto255-SHA512",
  "linkage_encoding_version": 1,
  "evaluated_element": "<base64url-encoded evaluated element>",
  "proof": "<base64url-encoded DLEQ proof>"
}
```

| Field | Encoding |
| --- | --- |
| `evaluated_element` | 32 bytes, unpadded base64url |
| `proof` | 64 bytes, unpadded base64url |

Response metadata identifies the active deployment and VOPRF key version used for evaluation.

`structuredContent` contains the response dictionary. `content` also contains its compact JSON serialization as `TextContent`.

## Encoding

`omneum/base64url.py` implements the protocol encoding checks.

```python
from omneum.base64url import decode_unpadded, encode_unpadded

blinded_bytes = decode_unpadded(
    blinded_element,
    expected_length=32,
)

encoded = encode_unpadded(
    blinded_bytes,
    expected_length=32,
)
```

The decoder rejects padding, non-base64url characters, incorrect lengths, and noncanonical encodings.

| Value | Raw length | Encoded length |
| --- | ---: | ---: |
| Blinded element | 32 bytes | 43 characters |
| Evaluated element | 32 bytes | 43 characters |
| DLEQ proof | 64 bytes | 86 characters |

The encoded lengths exclude `=` padding.

## Evaluation

`EvaluationService` in `omneum/tools/evaluate_voprf.py` submits decoded elements to the configured evaluator.

```text
MCP client
    |
    | evaluate_voprf
    v
omneum/transport/mcp.py
    |
    | EvaluateVOPRFRequest
    v
omneum/tools/evaluate_voprf.py
    |
    | 32-byte blinded element
    v
omneum/daemon.py
    |
    | authenticated Unix socket
    v
omneumd
    |
    | evaluated element + proof
    v
EvaluateVOPRFResponse
```

`EvaluationService` bounds concurrent evaluations using `voprf_max_concurrency`. Requests exceeding available capacity return `server_busy`.

`voprf_evaluation_timeout_ms` sets the evaluation deadline. Expired requests return `request_timeout`.

The VOPRF private scalar remains in the evaluator process. The MCP handler receives only the evaluated element and proof.

## Errors

Failed evaluations return `CallToolResult` with `isError=true`.

```json
{
  "message": "The blinded element is invalid.",
  "omneum_code": "invalid_blinded_element"
}
```

| Code | Condition |
| --- | --- |
| `invalid_request` | Pydantic request validation failed |
| `unsupported_protocol_version` | Protocol mismatch |
| `deployment_mismatch` | Deployment identity mismatch |
| `voprf_key_version_mismatch` | Key version mismatch |
| `unsupported_voprf_mode` | Unsupported mode |
| `unsupported_voprf_ciphersuite` | Unsupported ciphersuite |
| `unsupported_linkage_encoding_version` | Linkage encoding mismatch |
| `invalid_blinded_element` | Invalid encoding or Ristretto255 element |
| `server_busy` | Evaluation capacity exhausted |
| `request_timeout` | Evaluation deadline exceeded |
| `evaluation_failed` | Evaluator protocol or response failure |
| `internal_error` | Unexpected server failure |

Check `isError` before reading `evaluated_element` or `proof`.

See [Errors](errors.md) for the shared MCP error format.

## Implementation

```text
omneum/
├── base64url.py              # Canonical unpadded base64url
├── models.py                 # EvaluateVOPRFRequest/Response
├── oprf.py                   # VOPRF client operations and constants
├── daemon.py                 # Evaluator IPC
├── tools/
│   └── evaluate_voprf.py     # EvaluationService
└── transport/
    └── mcp.py                # MCP tool registration

src/
├── voprf_core.rs             # Ristretto255-SHA512 operations
└── daemon/
    ├── mod.rs                # Evaluator service
    └── os.rs                 # OS isolation and socket handling
```

The public MCP operation is `evaluate_voprf`. Direct clients must retain their blinding state and verify the returned proof before finalization.

See [Ping](ping.md) for deployment metadata and [Evaluate Context](evaluate-context.md) for the context evaluation API.