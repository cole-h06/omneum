# Errors

`evaluate_context` and `evaluate_voprf` return application errors through MCP `CallToolResult`. Python SDK callers receive typed exceptions from `omneum/client.py`.

## MCP Error Response

Check `isError` before reading `structuredContent`. Failed tool calls return `OmneumErrorResponse`, defined in `omneum/models.py`.

```python
result = await session.call_tool("evaluate_context", request)

if result.isError:
    error = result.structuredContent
    raise RuntimeError(
        f'{error["omneum_code"]}: {error["message"]}'
    )

evaluation = result.structuredContent
```

The error payload contains two fields:

```json
{
  "message": "The assertion graph is invalid.",
  "omneum_code": "invalid_graph"
}
```

`structuredContent` contains the error dictionary. `content` includes the same payload serialized as compact JSON in a `TextContent` entry.

## Error Codes

### Request Validation

Both evaluation tools validate request metadata against the active `DeploymentState`.

| Code | Condition |
| --- | --- |
| `invalid_request` | Invalid field types, missing fields, or unexpected arguments |
| `unsupported_protocol_version` | `protocol_version` mismatch |
| `deployment_mismatch` | `deployment_id` mismatch |
| `voprf_key_version_mismatch` | `voprf_key_version` mismatch |
| `unsupported_voprf_mode` | `voprf_mode` mismatch |
| `unsupported_voprf_ciphersuite` | `voprf_ciphersuite` mismatch |
| `unsupported_linkage_encoding_version` | `linkage_encoding_version` mismatch |

`invalid_request` is returned by `OmneumFastMCP.call_tool()` for evaluation-tool argument validation failures. Pydantic validation failures inside the registered handlers use the same code.

The remaining codes are returned by the tool services after request-model validation.

### Evaluate Context

| Code | Condition |
| --- | --- |
| `invalid_graph` | Invalid assertion graph, linkage tokens, source pairs, or exact-equivalence components |
| `server_busy` | Assertion-evaluation concurrency limit reached |
| `request_timeout` | Assertion evaluation exceeded its configured deadline |
| `assertion_evaluation_failed` | Inference or response validation failed |
| `internal_error` | Unexpected server-side failure |

`invalid_graph` covers duplicate assertions, incomplete source-pair matrices, invalid ordering, conflicting source–attribute assignments, and inconsistent equivalence declarations.

### Evaluate VOPRF

| Code | Condition |
| --- | --- |
| `invalid_blinded_element` | Invalid base64url encoding, element length, or Ristretto255 point |
| `server_busy` | Evaluator capacity exhausted |
| `request_timeout` | VOPRF evaluation exceeded its configured deadline |
| `evaluation_failed` | Evaluator protocol or response failure |
| `internal_error` | Unexpected server-side failure |

`evaluate_voprf` accepts one blinded element per request. A failed evaluation does not return an evaluated element or proof.

## Python SDK Exceptions

`omneum/client.py` defines separate exception types for VOPRF evaluation and context evaluation.

### Context Evaluation

```python
from omneum import (
    ContextEvaluationMappingError,
    ContextEvaluationRejectedError,
    ContextEvaluationResponseError,
    ContextEvaluationTransportError,
)
```

| Exception | Condition |
| --- | --- |
| `ContextEvaluationRejectedError` | MCP evaluator returned an Omneum application error |
| `ContextEvaluationTransportError` | MCP request or response transport failed |
| `ContextEvaluationResponseError` | Evaluator response failed validation |
| `ContextEvaluationMappingError` | Record mapping or evaluation-result identity resolution failed |

Handle application rejection separately from transport failure:

```python
try:
    evaluation = await client.evaluate_context(
        observations,
        estimator=estimator,
    )
except ContextEvaluationRejectedError as exc:
    print(exc.omneum_code)
except ContextEvaluationTransportError as exc:
    print(exc.uncertain)
```

`ContextEvaluationRejectedError.omneum_code` contains the returned application error code.

`ContextEvaluationTransportError.uncertain` indicates whether the transport failure left execution status uncertain. Do not interpret it as an evaluation result.

### VOPRF Evaluation

```python
from omneum import (
    EvaluationRejectedError,
    EvaluationResponseError,
    EvaluationTransportError,
    EvaluationVerificationError,
)
```

| Exception | Condition |
| --- | --- |
| `EvaluationRejectedError` | VOPRF evaluator returned an Omneum application error |
| `EvaluationTransportError` | VOPRF transport failed |
| `EvaluationResponseError` | Invalid or inconsistent VOPRF response |
| `EvaluationVerificationError` | DLEQ proof verification or finalization failed |

`EvaluationRejectedError` exposes `omneum_code`. `EvaluationTransportError` exposes `uncertain`.

VOPRF verification failures are client-side errors. They are not returned as `omneum_code` values by the MCP evaluator.

## Transport Failures

MCP framing and session failures are separate from Omneum application errors.

`omneum/transport/stdio.py` validates incoming frames before MCP dispatch. Invalid framing terminates the affected session rather than returning `OmneumErrorResponse`.

An unavailable `omneum-server`, interrupted stdio stream, or failed MCP initialization can also prevent a tool response from being returned.

For SDK integrations, handle the corresponding transport exception. Direct MCP clients must handle session and transport exceptions from the MCP library.

## Retry Handling

| Failure | Handling |
| --- | --- |
| `invalid_request` | Correct the request schema |
| `invalid_graph` | Rebuild the assertion graph or source-pair matrix |
| Deployment or protocol mismatch | Reload the installed deployment configuration |
| `invalid_blinded_element` | Generate a new valid blinded element |
| `server_busy` | Retry with bounded backoff |
| `request_timeout` | Retry with bounded backoff; the original execution may have completed |
| `evaluation_failed` | Inspect evaluator availability and protocol configuration |
| `assertion_evaluation_failed` | Inspect graph inference and response validation |
| `internal_error` | Inspect server logs |

For a failed VOPRF transport exchange, retain the original client blinding state only while its lifecycle remains valid. Do not finalize an unverified or incomplete response.

## Implementation

```text
omneum/
├── client.py
│   ├── EvaluationRejectedError
│   ├── EvaluationTransportError
│   ├── EvaluationResponseError
│   ├── EvaluationVerificationError
│   ├── ContextEvaluationRejectedError
│   ├── ContextEvaluationTransportError
│   ├── ContextEvaluationResponseError
│   └── ContextEvaluationMappingError
├── models.py
│   └── OmneumErrorResponse
├── tools/
│   ├── evaluate_context.py
│   └── evaluate_voprf.py
└── transport/
    ├── mcp.py
    └── stdio.py
```

`omneum/tools/evaluate_voprf.py` provides the shared `error_result()` serializer. Both evaluation services use it for `CallToolResult` application failures.