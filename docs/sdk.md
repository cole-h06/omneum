# Omneum Python SDK

The Python SDK evaluates context directly in-process or through a local Omneum server.

## Installation

Omneum supports CPython 3.11–3.14.

```bash
pip install omneum
```

The Python API runs in-process without a daemon or database.

For a managed MCP deployment, run:

```bash
omneum install
```

For platform requirements and managed-service setup, see
[Installation](installation.md).

## Quick Start

Install the Python package:

```bash
pip install omneum
```

Create `evaluate.py`:

Evaluate three observations against a single claim. Two sources reference the same upstream document.

```python
import omneum
from omneum.explanations import explain_evaluation

observations = [
    {
        "url": "https://a.example",
        "value": 4200000000,
        "claim": {
            "entity_namespace": "company",
            "entity": "acme",
            "attribute": "fy2025_gross_revenue",
        },
        "upstream": ["https://sec.example"],
    },
    {
        "url": "https://b.example",
        "value": 4200000000,
        "claim": {
            "entity_namespace": "company",
            "entity": "acme",
            "attribute": "fy2025_gross_revenue",
        },
        "upstream": ["https://sec.example"],
    },
    {
        "url": "https://c.example",
        "value": 4200000000,
        "claim": {
            "entity_namespace": "company",
            "entity": "acme",
            "attribute": "fy2025_gross_revenue",
        },
        "upstream": [],
    },
]

result = omneum.evaluate(observations)
print(explain_evaluation(result))
```

Run:

```bash
python evaluate.py
```

Output:

```text
Omneum Evaluation
Evaluation latency: 1.6 ms

Fy2025 gross revenue

  4200000000
  Support: 0.67
  Supporting sources: 3
  Estimated independent support: 2.00
  Dependency signal coverage: 1.00

  Explanation:
    3 sources support this claim, with an estimated 2.00 independent sources. The available dependency signals indicate that some supporting sources are related.
```

`evaluate()` runs Omneum's graph-based evaluation algorithm in-process; it computes source reliability and claim support scores while accounting for dependencies between sources.

## MCP Client Initialization

For MCP evaluation, `open_stdio_client()` starts `omneum-server` over stdio and returns an asynchronous client.

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

## Core Operations

### Evaluate Context

`omneum.evaluate()` accepts observations as Python dictionaries and runs synchronously in-process.

```python
import omneum

result = omneum.evaluate(observations)
```

For typed inputs, `evaluate_context()` accepts a sequence of `Observation` objects. Each observation connects a `Source` to a `Claim`:

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


Evaluate directly in-process:

```python
from omneum import evaluate_context

result = evaluate_context(observations)
```

Or evaluate through the MCP client:

```python
async with open_stdio_client(config, server) as client:
    result = await client.evaluate_context(observations)
```

Both methods return a `ContextEvaluation`.

## Inspect the Result

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

Use these fields to control retrieval, routing, or policy decisions. Omneum returns evaluation results without selecting an action.

## Add Provenance

An `Observation` can include source provenance:

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

Additional fields can be stored in metadata:

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

## Map Retrieved Chunks

ContextMapper converts existing retrieval results into `Observation` objects.

Suppose a retrieval tool returns chunks with extracted values and source metadata:

```python
from datetime import datetime, timezone

now = datetime.now(timezone.utc)

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

Pass the original retrieval results to `evaluate_mapped()`:

```python
result = await client.evaluate_mapped(
    results,
    mapper,
)
```

String values such as `"revenue"` and `"id"` select fields from the input
record. Callables can extract or transform values:

```python
mapper = ContextMapper(
    ...,
    value=lambda result: normalize_revenue(result),
)
```

See [ContextMapper](context_mapper.md) for the complete mapping contract.

## Extract assertions from text

`extract_observations()` optionally calls an LLM before evaluation. Pass an
explicitly configured async provider that accepts a prompt and returns a mapping
with `text` containing a JSON list of assertions. This uses the same callable
contract as the benchmark `generate()` integrations.

For example, install `anthropic` separately and set `ANTHROPIC_API_KEY` and
`ANTHROPIC_MODEL`:

```python
import asyncio
import os
from datetime import datetime, timezone

from anthropic import AsyncAnthropic
from omneum import Source, evaluate_context, extract_observations
from omneum.dependency import DependencyEstimatorConfig


async def main():
    async with AsyncAnthropic() as client:
        async def generate(prompt):
            response = await client.messages.create(
                model=os.environ["ANTHROPIC_MODEL"],
                max_tokens=2048,
                messages=[{"role": "user", "content": prompt}],
            )
            if response.stop_reason != "end_turn":
                raise ValueError("extraction response is incomplete")
            return {"text": "".join(
                block.text for block in response.content if block.type == "text"
            )}

        observations = await extract_observations([{
            "id": "report-chunk-1",
            "source": Source("web_document", "https://example.com/report"),
            "text": "Acme reported revenue of $4.2 billion in 2025.",
            "observed_at": datetime.now(timezone.utc),
        }], provider=generate)

    if observations:
        estimator = DependencyEstimatorConfig(
            upstream_weight=1.0, citation_weight=0.0,
            assertion_lineage_weight=0.0, ownership_weight=0.0,
            temporal_weight=0.0, graph_weight=0.0,
            temporal_window_seconds=7200.0,
        )
        result = evaluate_context(observations, estimator=estimator)
        print(result.explanation)


asyncio.run(main())
```

Each chunk requires a unique `id`, a `Source`, `text`, and a timezone-aware
`observed_at`. Optional observation provenance fields and `metadata` pass through
from the chunk. Each assertion receives an observation ID of `<chunk id>:<index>`
and `metadata["chunk_id"]` identifies its originating chunk. Multiple chunks from
one resource should use the same source identity and different chunk IDs.

The provider must return a JSON list of objects containing exactly
`entity_namespace`, `entity`, `attribute`, and `value`. An empty list produces no
observations. Invalid or incomplete output raises `ValueError`; provider errors
propagate without returning a partial result. Existing claim and observation
validation applies. Structural validation cannot establish extraction accuracy.

Raw text is sent to the configured provider. Source identity and provenance come
from the caller. Extraction does not infer dependency signals. BRAID remains
data-blind, and evaluation and the demo require no provider package or API key.

## Configure source-dependency estimation

Pass a `DependencyEstimatorConfig` to override the estimator settings:

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

`ContextEvaluationMappingError` indicates a failure while mapping input data through `ContextMapper`.

Transport failures, server rejections, and malformed responses raise separate exception types.

See [API Reference](api.md) for validation rules and the complete request and
response contract.

## Current limits

The Python SDK supports synchronous in-process evaluation and asynchronous MCP evaluation over local stdio. Remote MCP transport is not currently supported.

Supported Python versions are CPython 3.11–3.14.

One VOPRF key is active at a time. Overlapping old and new keys during key
rotation aren't currently supported.

Persisted linkage tokens require their associated deployment and key-version information for valid comparisons.

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