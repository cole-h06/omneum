# Evaluate Context

`evaluate_context` runs Omneum's provenance-aware graph inference to compute source reliability and claim support from observations.

## Evaluate Observations

`OmneumClient.evaluate_context()` accepts a sequence of `Observation` objects. `DependencyEstimatorConfig` controls source dependency estimation.

```python
evaluation = await client.evaluate_context(
    observations,
    estimator=estimator,
)
```

The SDK derives canonical identities from the observations and generates opaque linkage tokens using VOPRF. Source dependency estimates are computed from observation provenance before submission to the MCP evaluator.

See [Python SDK](../sdk.md) for client initialization.

## Evaluate Mapped Records

`OmneumClient.evaluate_mapped()` evaluates records produced by retrieval pipelines through a configured `ContextMapper`.

```python
evaluation = await client.evaluate_mapped(
    records,
    mapper,
    estimator=estimator,
)
```

Field mappings construct `Observation` instances from the existing record schema. Evaluation follows the `evaluate_context()` execution path.

See [ContextMapper](../context-mapper.md).

## Source Equivalence

Declare `ExactEquivalence` only for source references containing identical evidence across the evaluated claims.

```python
from omneum import ExactEquivalence, SourceReference

evaluation = await client.evaluate_context(
    observations,
    estimator=estimator,
    exact_equivalences=(
        ExactEquivalence(
            SourceReference(
                "web_document",
                "https://example.com/original",
            ),
            SourceReference(
                "web_document",
                "https://example.com/exact-copy",
            ),
        ),
    ),
)
```

Both references must occur in `observations`. The evaluator rejects inconsistent claim profiles or component dependencies.

`exact_equivalences` defaults to an empty sequence. Provenance does not automatically create exact-equivalence declarations.

## Evaluation Results

`OmneumClient.evaluate_context()` returns `ContextEvaluation`.

```python
for source in evaluation.source_reliability:
    print(source.source, source.reliability)

for claim in evaluation.claim_support:
    print(claim.claim, claim.support)
```

### ContextEvaluation

| Field | Type |
|---|---|
| `source_reliability` | `tuple[SourceEvaluation, ...]` |
| `claim_support` | `tuple[ClaimSupportResult, ...]` |
| `pairwise_dependencies` | `tuple[PairwiseDependencyResult, ...]` |
| `convergence` | `ConvergenceMetadata` |
| `dependency_cluster_threshold` | `float \| None` |
| `evaluation_latency_ms` | `float \| None` |

`SourceEvaluation.reliability` contains the inferred reliability score for a source. `ClaimSupportResult.support` contains the inferred support score for a claim.

### ClaimSupportResult

| Field | Type |
|---|---|
| `claim` | `Claim` |
| `support` | `float` |
| `agreement_weight` | `float` |
| `is_attribute_max_support` | `bool` |
| `supporting_source_count` | `int` |
| `estimated_independent_support_count` | `float` |
| `dependency_signal_coverage` | `float \| None` |
| `supporting_sources` | `tuple[SupportingSourceResult, ...]` |
| `conflicting_claims` | `tuple[ConflictingClaimResult, ...]` |
| `dependency_clusters` | `tuple[DependencyCluster, ...] \| None` |

`supporting_sources` contains per-source independence estimates and contributions. `conflicting_claims` identifies competing claim values within the evaluated attribute.

### ConvergenceMetadata

| Field | Type |
|---|---|
| `algorithm_version` | `str` |
| `iterations` | `int` |
| `converged` | `bool` |
| `convergence_tolerance` | `float` |
| `convergence_delta` | `float` |

## MCP Tool

`evaluate_context` is registered as an MCP tool in `omneum/transport/mcp.py`. Requests are validated against `EvaluateAssertionRequest` in `omneum/models.py`.

```json
{
  "protocol_version": "v1",
  "deployment_id": "urn:uuid:01234567-89ab-cdef-0123-456789abcdef",
  "voprf_key_version": 1,
  "voprf_mode": "voprf",
  "voprf_ciphersuite": "ristretto255-SHA512",
  "linkage_encoding_version": 1,
  "assertions": [
    {
      "source_id": "<opaque linkage token>",
      "attribute_id": "<opaque linkage token>",
      "claim_id": "<opaque linkage token>"
    }
  ],
  "source_pairs": []
}
```

Use the deployment parameters returned by `ping`. Linkage identifiers are canonical unpadded base64url encodings of 64-byte tokens. The SDK generates these identifiers and retains their local mappings.

### Assertions

`assertions` contains source–attribute–claim edges.

| Field | Type |
| --- | --- |
| `source_id` | `str` |
| `attribute_id` | `str` |
| `claim_id` | `str` |

Assertions must be unique and sorted by `(source_id, attribute_id, claim_id)`.

### Source Pairs

`source_pairs` contains every unordered pair of distinct sources.

```json
{
  "source_a_id": "<opaque linkage token>",
  "source_b_id": "<opaque linkage token>",
  "dependency": 0.0,
  "weighted_signal_coverage": 1.0,
  "exact_equivalence": false
}
```

`dependency` and `weighted_signal_coverage` must be finite values in `[0, 1]`. `exact_equivalence` defaults to `false`.

For `n` sources, submit exactly `n * (n - 1) // 2` pairs, sorted by `(source_a_id, source_b_id)`, with `source_a_id < source_b_id`.

The SDK builds this matrix from the observation provenance. Direct MCP callers must supply it.


## MCP Response

The MCP handler returns `CallToolResult` with `structuredContent` containing an `EvaluateAssertionResponse`, defined in `omneum/models.py`.

```text
EvaluateAssertionResponse
├── protocol_version
├── deployment_id
├── voprf_key_version
├── voprf_mode
├── voprf_ciphersuite
├── linkage_encoding_version
├── evaluation_latency_ms
├── summary
│   ├── source_count
│   ├── claim_count
│   └── assertion_count
├── source_reliability[]
│   ├── source_id
│   └── reliability
├── claim_support[]
│   ├── attribute_id
│   ├── claim_id
│   ├── support
│   ├── agreement_weight
│   ├── is_attribute_max_support
│   ├── supporting_source_count
│   ├── estimated_independent_support_count
│   ├── dependency_signal_coverage
│   ├── supporting_sources[]
│   │   ├── source_id
│   │   ├── independence
│   │   └── contribution
│   └── conflicting_claims[]
│       ├── claim_id
│       └── support
└── metadata
    ├── algorithm_version
    ├── iterations
    ├── converged
    ├── convergence_tolerance
    └── convergence_delta
```

`evaluation_latency_ms` measures server-side elapsed time from graph validation through response validation, including queue wait and inference execution. SDK dependency estimation, linkage, transport, persistence, and context reconstruction are excluded.

`OmneumClient` resolves returned linkage identifiers to the corresponding `Source` and `Claim` instances.

## Validation

Limits are enforced by `omneum/tools/evaluate_context.py`.

| Resource | Maximum |
| --- | ---: |
| Assertions | 4,096 |
| Sources | 64 |
| Attributes | 2,048 |
| Claims | 4,096 |
| Source pairs | 2,016 |
| Conflicting-claim entries | 16,384 |

Duplicate assertions, missing source pairs, invalid linkage tokens, noncanonical ordering, and inconsistent equivalence declarations are rejected.

## Errors

Failed MCP tool executions return `CallToolResult` with `isError=true`. The structured error payload follows `OmneumErrorResponse`.

```json
{
  "message": "The assertion graph is invalid.",
  "omneum_code": "invalid_graph"
}
```

The Python SDK raises `ContextEvaluationRejectedError` for rejected evaluations, `ContextEvaluationResponseError` for invalid evaluation responses, and `ContextEvaluationTransportError` for MCP transport failures. `ContextEvaluationMappingError` reports failures when resolving evaluator response identifiers to local objects.

See [Errors](errors.md) for the error codes and exception handling.

## Implementation

```text
omneum/
├── client.py                 # SDK evaluation and response mapping
├── information.py            # Observation, Source, Claim
├── dependency.py             # Source-pair estimation
├── models.py                 # MCP request/response models
├── tools/
│   └── evaluate_context.py   # Graph validation and evaluation
└── transport/
    ├── mcp.py                # Tool registration
    └── stdio.py              # MCP framing
```