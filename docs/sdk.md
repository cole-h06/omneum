# Omneum Python SDK

The Python SDK evaluates context with a local Omneum server.

## Installation

Omneum supports CPython 3.11–3.14.

```bash
pip install omneum
omneum install
```

For platform requirements and managed-service setup, see
[Installation](installation.md).

## Connect

Omneum uses MCP over stdio. `open_stdio_client()` starts `omneum-server` and
returns an async client:

```python
from mcp import StdioServerParameters

from omneum import OmneumClientConfig, open_stdio_client

config = OmneumClientConfig.from_local_deployment()

server = StdioServerParameters(
    command="omneum-server",
)
```

Use the client as an async context manager:

```python
async with open_stdio_client(config, server) as client:
    ...
```

`from_local_deployment()` reads the public configuration created by
`omneum install` or `omneum init`.

## Evaluate context

`evaluate_context()` accepts a sequence of `Observation` objects.

Each observation connects a `Source` to a `Claim`:

```python
from datetime import datetime, timezone

from omneum import Claim, Observation, Source

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
```

Evaluate them:

```python
async with open_stdio_client(config, server) as client:
    result = await client.evaluate_context(observations)
```

The result is a `ContextEvaluation`.

## Read the result

Claim scores are available through `claim_support`:

```python
for claim in result.claim_support:
    print("Support:", claim.support)
    print(
        "Independent support:",
        claim.estimated_independent_support_count,
    )
    print("Conflicts:", claim.conflicting_claims)
```

`support` is Omneum's graph score for the claim. It is not a probability that
the value is correct.

`estimated_independent_support_count` adjusts the number of supporting sources
using the source dependencies estimated for the evaluation. Four sources can,
for example, provide substantially less than four independent confirmations.

`conflicting_claims` contains other values observed for the same normalized
entity and attribute.

Pairwise source dependencies are available separately:

```python
for dependency in result.pairwise_dependencies:
    print(dependency)
```

Applications can use these fields for routing, retrieval, or policy decisions.
Omneum doesn't choose the application action.

## Add provenance

An `Observation` can include provenance already available to the application:

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

Use the field that matches the data your runtime actually has:

| Field | Use |
|---|---|
| `source_modified_at` | Timestamp reported by the source itself |
| `upstream_sources` | Sources this source was derived from |
| `cited_sources` | Sources explicitly cited by this source |
| `parent_observation_ids` | Direct observations this observation was derived from |
| `retrievals` | Retrieval executions that returned the observation |

Leave unavailable fields unset. Don't infer provenance just to populate the
schema.

Application-specific data can stay in `metadata`:

```python
observation = Observation(
    ...,
    metadata={
        "request_id": request_id,
        "tool_name": tool_name,
    },
)
```

`metadata` is retained with the observation but doesn't automatically affect
source-dependency estimation.

## Map existing application objects

Applications don't need to rebuild their retrieval results by hand.

Suppose a tool returns:

```python
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
```

Map the existing fields with `ContextMapper`:

```python
from omneum import ContextMapper, Source

mapper = ContextMapper(
    source=lambda result: Source(
        kind="web_document",
        identifier=result["url"],
    ),
    entity_namespace=lambda result: "company",
    entity="company",
    attribute=lambda result: "quarterly_revenue_usd",
    value="revenue",
    observation_id="id",
    observed_at=lambda result: now,
)
```

Then pass the original records directly:

```python
result = await client.evaluate_mapped(
    results,
    mapper,
)
```

String values such as `"revenue"` and `"id"` select fields from the input
record. Callables can perform application-specific extraction:

```python
mapper = ContextMapper(
    ...,
    value=lambda result: normalize_revenue(result),
)
```

See [ContextMapper](context_mapper.md) for the complete mapping contract.

## Configure source-dependency estimation

Pass a `DependencyEstimatorConfig` when the application needs explicit
estimator settings:

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

result = await client.evaluate_context(
    observations,
    estimator=estimator,
)
```

These values configure the estimator for the evaluation. They aren't
deployment settings or calibrated defaults for every workload.

## Format results

Omneum includes local formatting helpers:

```python
from omneum import explain_claim, explain_dependency

for claim in result.claim_support:
    print(explain_claim(claim))

for dependency in result.pairwise_dependencies:
    print(explain_dependency(dependency))
```

The helpers only format data already returned by Omneum. They don't call an
LLM or run another evaluation.

Use the structured result fields rather than formatted explanations for
application logic.

## Configuration

Load an installed local deployment with:

```python
from omneum import OmneumClientConfig

config = OmneumClientConfig.from_local_deployment()
```

To read public configuration from another directory:

```bash
export OMNEUM_CONFIG_DIR=/etc/omneum
```

The configuration contains the deployment metadata and public VOPRF
information needed by the client. The daemon's private VOPRF key is not stored
with the SDK configuration.

For custom endpoints and administrator-managed deployments, see
[Deployment](../deploy/README.md).

## Errors

Context evaluation can raise:

```python
from omneum import (
    ContextEvaluationMappingError,
    ContextEvaluationRejectedError,
    ContextEvaluationResponseError,
    ContextEvaluationTransportError,
)
```

Use `ContextEvaluationMappingError` for failures while adapting application
records through `ContextMapper`.

Transport, server rejection, and malformed-response failures are exposed
separately so applications can handle them differently.

See [API Reference](api.md) for validation rules and the complete request and
response contract.

## Current limits

The Python SDK currently connects to a local MCP server over stdio. A remote
SDK transport isn't available yet.

Supported Python versions are CPython 3.11–3.14.

One VOPRF key is active at a time. Overlapping old and new keys during key
rotation aren't currently supported.

Applications that persist linkage tokens must also retain the deployment and
key-version information needed to compare those tokens correctly.

## Examples

Framework integrations:

- [LangGraph](../examples/langgraph/)
- [LlamaIndex](../examples/llamaindex/)
- [CrewAI](../examples/crewai/)
- [OpenAI Agents SDK](../examples/openai_agents/)
- [Microsoft Agent Framework](../examples/microsoft_agent_framework/)

For the complete framework-independent workflow, see the
[enterprise policy example](../examples/enterprise/).

## Reference

- [API Reference](api.md)
- [ContextMapper](context_mapper.md)
- [Canonicalization](canonicalization.md)
- [Protocol](protocol.md)
- [Installation](installation.md)
- [Deployment](../deploy/README.md)