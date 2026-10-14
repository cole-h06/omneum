
# Python SDK

Use `evaluate()` for dictionary inputs or `evaluate_context()` for structured
observations. Both synchronous functions evaluate entirely in memory, without MCP,
a daemon, service installation, network access, or a database. The existing
`OmneumClient` connects through MCP for isolated VOPRF linkage and service evaluation.
For MCP-only integrations without Python, see [Configuration](guides/configuration.md).

## Installation

Supports CPython 3.11–3.14.

```bash
pip install omneum
```

For MCP integrations, also run `omneum install`. See [Installation](guides/installation.md) for supported platforms and local service setup.

## Evaluate Records

```python
import omneum

records = [
    {"url": "https://a.example", "value": 4200000000,
     "upstream": ["https://sec.example"]},
    {"url": "https://b.example", "value": 4200000000,
     "upstream": ["https://sec.example"]},
    {"url": "https://c.example", "value": 4200000000,
     "upstream": []},
]

result = omneum.evaluate(records)
print(f"Estimated independent support: {result.estimated_independent_support:.2f}")
```

```text
Estimated independent support: 2.00
```

`evaluate(records, *, estimator=None) -> ContextEvaluation` accepts a
sequence of dictionaries. It converts them to `Observation` objects and calls
`evaluate_context()`, which uses the existing dependency estimator, BRAID graph
builder, inference engine, and result mapping. Synthetic examples execute that
same algorithm; there is no alternate scoring implementation.

`evaluate_records()` remains a backward-compatible alias of `evaluate()`.

| Field | Meaning and default |
| --- | --- |
| `url` | Required source URL. Uses the existing `web_document` canonicalization; paths and queries distinguish sources, fragments do not. Nothing is fetched. |
| `value` | Required JSON-compatible asserted value, including `None`. Existing claim canonicalization applies. |
| `upstream` | List of upstream source URLs. Omitted or `None` means unknown provenance; `[]` means no known upstream sources. Shared upstream URLs produce dependency evidence even if they have no record of their own. |
| `claim` | Optional mapping containing exactly `entity_namespace`, `entity`, and `attribute`, each a nonempty string. Supply it on every record or on none. |
| `observation_id` | Optional nonempty string unique within this call. Defaults to `record:<zero-based index>`. |
| `observed_at` | Optional timezone-aware `datetime`. Defaults to a single UTC timestamp captured once per call. |
| `source_modified_at` | Optional timezone-aware `datetime`; default `None` (unknown). Observation time alone does not enable temporal dependency. |
| `owner_id` | Optional source owner string; default `None`. Canonically identical source URLs must have consistent ownership. |
| `cited` | Optional list of cited source URLs; omitted or `None` is unknown, `[]` means no known citations. |
| `parent_observation_ids` | Optional list of observation IDs within this call for lineage; omitted or `None` is unknown, `[]` means no known parents. |
| `metadata` | Optional dictionary of JSON-compatible application metadata; defaults to `{}`. Does not change scores. |

Unknown fields and partial claim identities are rejected. Inputs are not mutated.
Without `claim`, **all records in the call assert the same attribute**, identified
as `entity_namespace="records", entity="default", attribute="value"`. Equal
canonical values support the same claim; different values compete within that
attribute. This mode is only for records that actually address the same question.
Omneum does not infer claim identity from text, URLs, or values.

For multiple attributes or entities, give each record its full claim identity:

```python
records = [
    {"url": "https://a.example", "value": 90,
     "claim": {"entity_namespace": "service", "entity": "payments", "attribute": "retention_days"}},
    {"url": "https://b.example", "value": 30,
     "claim": {"entity_namespace": "service", "entity": "payments", "attribute": "retention_days"}},
    {"url": "https://a.example", "value": "eu",
     "claim": {"entity_namespace": "service", "entity": "payments", "attribute": "region"}},
]
result = omneum.evaluate(records)
for item in result.claim_support:
    print(item.claim.attribute, item.claim.value, item.estimated_independent_support_count)
```

The return value is the full **`ContextEvaluation`**, including `claim_support`,
`source_reliability`, `pairwise_dependencies`, convergence, latency, and explanations.
`result.estimated_independent_support` returns the single claim's
`estimated_independent_support_count` as a float, without rounding or truncation.
It raises `ValueError` for multiple claims, including conflicting values. Select
an item from `result.claim_support` in that case; summing support across unrelated
claims would not describe independent evidence for any one claim.

The convenience API defaults to the upstream-only estimator used in the original
in-process example: `upstream_weight=1.0`, all other signal weights `0.0`,
`temporal_window_seconds=7200.0`, estimator version `dependency-estimator-v4`,
no dependency cluster threshold. This is a new wrapper default, not a change to
`evaluate_context()` or the scoring algorithm. Pass an existing
`DependencyEstimatorConfig` via `estimator=` to use citation, ownership, lineage,
temporal, or graph signals and optional clustering. Fractional estimates from
that estimator are preserved. Missing provenance is not proof of independence;
inspect `dependency_signal_coverage` alongside estimated support.

Existing graph validation and limits apply: at most 64 sources, 2,048 attributes,
4,096 observations/claims, and 16,384 conflicting-claim entries. Duplicate canonical
source/claim observations, duplicate observation IDs, and multiple competing values
from the same source for one attribute raise `InformationGraphError` (`ValueError`).
One source can report several distinct attributes. Invalid field types raise
`TypeError` or `ValueError`; invalid URLs and claim values use existing validation.

This API is for URL sources and explicit structured assertions. For other source
kinds, retrieval metadata, or caller-certified exact equivalence, use the structured
SDK APIs. For direct synchronous evaluation, call
`evaluate_context(observations, estimator=config)`; the estimator remains required.
The in-process functions do not issue VOPRF linkage tokens, isolate keys, persist
history, or contribute to the network. Use the MCP client below when those service
features are needed.

## MCP Quick Start

```python
import asyncio
from datetime import datetime, timezone

from mcp import StdioServerParameters
from omneum import (
    Claim,
    DependencyEstimatorConfig,
    Observation,
    OmneumClientConfig,
    Source,
    open_stdio_client,
)

async def main():
    config = OmneumClientConfig.from_local_deployment()
    server = StdioServerParameters(command="omneum-server")

    observations = [
        Observation(
            observation_id="research-result",
            source=Source(
                kind="web_document",
                identifier="https://research.example.com/acme-revenue",
            ),
            claim=Claim(
                entity_namespace="company",
                entity="acme",
                attribute="revenue_2025",
                value=4_200_000_000,
            ),
            observed_at=datetime.now(timezone.utc),
        ),
    ]

    estimator = DependencyEstimatorConfig(
        upstream_weight=0.25,
        citation_weight=0.20,
        assertion_lineage_weight=0.20,
        ownership_weight=0.10,
        temporal_weight=0.10,
        graph_weight=0.15,
        temporal_window_seconds=7200.0,
    )

    async with open_stdio_client(config, server) as client:
        evaluation = await client.evaluate_context(observations, estimator=estimator)

        for claim in evaluation.claim_support:
            print(claim.support)
            print(claim.estimated_independent_support_count)

asyncio.run(main())
```

## Client Initialization

`open_stdio_client()` starts `omneum-server` and establishes an MCP stdio session.

```python
from mcp import StdioServerParameters
from omneum import OmneumClientConfig, open_stdio_client

config = OmneumClientConfig.from_local_deployment()
server = StdioServerParameters(command="omneum-server")

async with open_stdio_client(config, server) as client:
    ...
```

`from_local_deployment()` reads the public configuration generated by `omneum install` or `omneum init`.

The client communicates with the local evaluator through the MCP server. It does not load the evaluator into the Python process.

## Core Operations

### Evaluate Context

`OmneumClient.evaluate_context()` accepts a sequence of `Observation` objects and returns a `ContextEvaluation`.

```python
from datetime import datetime, timezone
from omneum import Claim, DependencyEstimatorConfig, Observation, Source

claim = Claim(
    entity_namespace="service",
    entity="payment_api",
    attribute="status_code",
    value=200,
)

observations = [
    Observation(
        observation_id="research-result",
        source=Source(
            kind="web_document",
            identifier="https://research.example.com/payment-status",
        ),
        claim=claim,
        observed_at=datetime.now(timezone.utc),
    ),
    Observation(
        observation_id="analytics-result",
        source=Source(
            kind="web_document",
            identifier="https://analytics.example.com/payment-status",
        ),
        claim=claim,
        observed_at=datetime.now(timezone.utc),
    ),
]

estimator = DependencyEstimatorConfig(
    upstream_weight=0.25,
    citation_weight=0.20,
    assertion_lineage_weight=0.20,
    ownership_weight=0.10,
    temporal_weight=0.10,
    graph_weight=0.15,
    temporal_window_seconds=7200.0,
)

evaluation = await client.evaluate_context(observations, estimator=estimator)
```

Each assertion observation links a `Claim` to a `Source`. Multiple observations can report the same claim or conflicting values.

### Evaluate Mapped Context

`evaluate_mapped()` converts application records into Omneum observations using `ContextMapper`, then evaluates them.

```python
from datetime import datetime, timezone
from omneum import ContextMapper, Source

results = [
    {
        "id": "research-result",
        "url": "https://research.example.com/acme-q3",
        "company": "acme-corp",
        "revenue": 42_000_000,
    },
    {
        "id": "analytics-result",
        "url": "https://analytics.example.com/acme-q3",
        "company": "acme-corp",
        "revenue": 42_000_000,
    },
]

mapper = ContextMapper(
    source=lambda r: Source(
        kind="web_document",
        identifier=r["url"],
    ),
    entity_namespace=lambda r: "company",
    entity="company",
    attribute=lambda r: "quarterly_revenue_usd",
    value="revenue",
    observation_id="id",
    observed_at=lambda r: datetime.now(timezone.utc),
)

evaluation = await client.evaluate_mapped(results, mapper)
```

String selectors such as `"company"` and `"revenue"` reference input fields. Callables support custom extraction.

`ContextMapper` does not perform entity resolution or extract assertions from unstructured text.

See [ContextMapper](context-mapper.md) for the mapping contract.

### Configure Source Dependence

Pass `DependencyEstimatorConfig` to override estimator parameters for an evaluation.

```python
from omneum import DependencyEstimatorConfig

estimator = DependencyEstimatorConfig(
    upstream_weight=0.25,
    citation_weight=0.20,
    assertion_lineage_weight=0.20,
    ownership_weight=0.10,
    temporal_weight=0.10,
    graph_weight=0.15,
    temporal_window_seconds=7200.0,
)

evaluation = await client.evaluate_context(
    observations,
    estimator=estimator,
)
```

These parameters apply to the evaluation request, not the local deployment.

See [Source Dependence](architecture.md#source-dependence).

## Evaluation Results

`ContextEvaluation` exposes source reliability, claim support, conflicts, and dependency estimates.

### Claim Support

```python
for claim in evaluation.claim_support:
    print("Support:", claim.support)
    print(
        "Independent support:",
        claim.estimated_independent_support_count,
    )
    print("Conflicts:", claim.conflicting_claims)
```

`support` is a graph-derived score, not a probability of correctness.

`estimated_independent_support_count` adjusts the number of supporting sources using estimated source dependencies.

`conflicting_claims` contains other observed values for the same normalized entity and attribute.

### Source Dependencies

```python
for dependency in evaluation.pairwise_dependencies:
    print(dependency)
```

Dependencies are estimated from available upstream lineage, citations, assertion lineage, ownership, timestamps, and graph structure.

### Format Results

```python
from omneum import (
    explain_evaluation,
    explain_claim,
    explain_dependency,
)

print(explain_evaluation(evaluation))

for claim in evaluation.claim_support:
    print(explain_claim(claim))

for dependency in evaluation.pairwise_dependencies:
    print(explain_dependency(dependency))
```

Formatting helpers operate on existing evaluation results. They do not make additional model calls.

Use structured result fields for application logic.

## Observation Provenance

`Observation` accepts source and retrieval metadata supplied by the application.

```python
observation = Observation(
    observation_id="research-result",
    source=Source(
        kind="web_document",
        identifier="https://research.example.com/acme-q3",
        owner_id="research",
    ),
    claim=claim,
    observed_at=now,
    source_modified_at=source_modified_at,
    upstream_sources=upstream_sources,
    cited_sources=citations,
    parent_observation_ids=parent_observation_ids,
    retrievals=retrievals,
)
```

The example assumes the application has already populated the timestamp, lineage, citation, and retrieval variables.

| Field | Description |
|---|---|
| `source_modified_at` | Source-reported modification timestamp |
| `upstream_sources` | Sources from which information was derived |
| `cited_sources` | Explicitly cited sources |
| `parent_observation_ids` | Direct parent observations |
| `retrievals` | Retrieval executions associated with the observation |

Leave unavailable fields unset. Do not infer provenance to populate the schema.

### Application Metadata

```python
observation = Observation(
    observation_id="research-result",
    source=source,
    claim=claim,
    observed_at=datetime.now(timezone.utc),
    metadata={
        "request_id": request_id,
        "tool_name": tool_name,
    },
)
```

`metadata` is retained with the observation but does not automatically affect source-dependency estimation.

## Configuration

Load the installed local deployment:

```python
from omneum import OmneumClientConfig

config = OmneumClientConfig.from_local_deployment()
```

Override the public configuration directory:

```bash
export OMNEUM_CONFIG_DIR=/etc/omneum
```

The SDK reads deployment metadata and public VOPRF parameters. The private VOPRF key remains with the managed evaluator daemon.

See [Configuration](guides/configuration.md).

## Error Handling

```python
from omneum import (
    ContextEvaluationMappingError,
    ContextEvaluationRejectedError,
    ContextEvaluationResponseError,
    ContextEvaluationTransportError,
)
```

| Exception | Condition |
|---|---|
| `ContextEvaluationMappingError` | Input record mapping failed |
| `ContextEvaluationRejectedError` | Evaluation request rejected |
| `ContextEvaluationResponseError` | Invalid evaluation response |
| `ContextEvaluationTransportError` | MCP transport failure |

See [API Reference](api/) for validation rules and response schemas.

## Current Limits

- **In-process:** `evaluate()` and the synchronous `evaluate_context()` need no transport.
- **Client transport:** Local MCP over stdio. No remote SDK transport.
- **Python:** CPython 3.11–3.14.
- **VOPRF:** One active key per deployment. Overlapping keys during rotation are not supported.
- **Linkage tokens:** Persisted tokens require deployment and key-version metadata for valid comparisons.

## Examples

- [LangGraph](../examples/langgraph/)
- [LlamaIndex](../examples/llamaindex/)
- [CrewAI](../examples/crewai/)
- [OpenAI Agents SDK](../examples/openai_agents/)
- [Microsoft Agent Framework](../examples/microsoft/)
- [Enterprise policy workflow](../examples/enterprise/)

## Reference

- [API Reference](api/)
- [ContextMapper](context-mapper.md)
- [Architecture](architecture.md)
- [Canonicalization](canonicalization.md)
- [Protocol](protocol.md)
- [Configuration](guides/configuration.md)
- [Installation](guides/installation.md)
- [Deployment](guides/deployment.md)
