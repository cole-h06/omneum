# Omneum Python SDK

Asynchronous Python SDK for Omneum over standard I/O (stdio) process pipes. `OmneumClient.prepare_context()` constructs token-budgeted context for LLM and agent pipelines.

## Installation

```bash
pip install omneum
```

Omneum supports CPython 3.11–3.14.

For local MCP evaluation:

```bash
omneum install
```

See [Installation](guides/installation.md) for platform requirements and managed-service setup.

## Quick Start

Create `prepare_context.py`:

```python
import asyncio
from datetime import datetime, timezone

from omneum import (
    ContextMapper,
    DependencyEstimatorConfig,
    OmneumClientConfig,
    Source,
    SourceReference,
    open_stdio_client,
)
from omneum.context_selection import claim_id
from omneum.mcp import StdioServerParameters


async def main():
    now = datetime.now(timezone.utc)
    policy_url = "https://example.com/security-policy"

    records = [
        {
            "id": "policy",
            "url": policy_url,
            "value": 365,
            "upstream": (),
            "text": "The security policy requires 365 days of audit retention.",
        },
        {
            "id": "faq",
            "url": "https://example.com/faq",
            "value": 365,
            "upstream": (
                SourceReference("web_document", policy_url),
            ),
            "text": "Derived from the security policy: retain audits for 365 days.",
        },
    ]

    mapper = ContextMapper(
        source=lambda row: Source("web_document", row["url"]),
        entity_namespace=lambda row: "service",
        entity=lambda row: "support_copilot",
        attribute=lambda row: "audit_retention_days",
        value="value",
        observation_id="id",
        observed_at=lambda row: now,
        upstream_sources="upstream",
    )

    observations = mapper.map_many(records)

    chunks = [
        {
            "chunk_id": row["id"],
            "raw_text": row["text"],
            "claim_ids": [claim_id(observation.claim)],
        }
        for row, observation in zip(records, observations)
    ]

    estimator = DependencyEstimatorConfig(
        upstream_weight=1.0,
        citation_weight=0.0,
        assertion_lineage_weight=0.0,
        ownership_weight=0.0,
        temporal_weight=0.0,
        graph_weight=0.0,
        temporal_window_seconds=7200.0,
    )

    config = OmneumClientConfig.from_local_deployment()
    server = StdioServerParameters(command="omneum-server")

    async with open_stdio_client(config, server) as client:
        result = await client.prepare_context(
            observations,
            chunks,
            estimator=estimator,
            token_budget=200,
        )

    print(result["context"])
    print(result["selection"])


asyncio.run(main())
```

Run:

```bash
python prepare_context.py
```

`result["context"]` contains the reconstructed original passages. `result["selection"]` reports token usage and claim coverage.


### Context Quality Demo

Run the Raw RAG vs. Omneum comparison from the repository root:

```bash
~/.local/bin/uv run python examples/context_quality_demo/before_after.py
```

The demo evaluates five retrieved chunks against the same 80-unit context budget.

```text
Structural evaluation (all retrieved evidence)
  audit_retention_days:    1 source, 1.00 estimated independent support
  customer_content:        2 sources, 2.00 estimated independent support
  processing_region:       4 sources, 2.00 estimated independent support
  provider_retention_days: 4 sources, 2.00 estimated independent support

Raw RAG
========================================================================
  Selected (rendering order): team-faq, wiki-mirror, gateway-config
  Token usage: 75/80
  Claim coverage: 2/4 (processing_region, provider_retention_days)
  Excluded: security-policy, audit-config

Omneum
========================================================================
  Selected (rendering order): security-policy, audit-config
  Token usage: 51/80
  Claim coverage: 4/4 (processing_region, provider_retention_days, customer_content, audit_retention_days)
  Excluded: team-faq, wiki-mirror, gateway-config
```

The terminal displays structural summaries on `stderr`. The complete evaluation and reconstructed context payloads remain available programmatically. Set `DEBUG_JSON = True` at the bottom of the example to print detailed JSON diagnostics to `stdout`.

## Client Initialization

`open_stdio_client()` starts `omneum-server` over stdio and initializes an asynchronous `OmneumClient`.

```python
from omneum import OmneumClientConfig, open_stdio_client
from omneum.mcp import StdioServerParameters

config = OmneumClientConfig.from_local_deployment()
server = StdioServerParameters(command="omneum-server")

async with open_stdio_client(config, server) as client:
    ...
```

`from_local_deployment()` reads the public configuration created by `omneum install` or `omneum init`.

## Core Operations

### Prepare Context

`prepare_context()` evaluates mapped observations and constructs the final context payload.

```python
result = await client.prepare_context(
    observations,
    chunks,
    estimator=estimator,
    token_budget=4096,
)
```

| Parameter | Type | Description |
|---|---|---|
| `assertion_observations` | `Sequence[Observation]` | Structured observations |
| `chunks` | `Sequence[Mapping[str, Any]]` | Original retrieval chunks |
| `estimator` | `DependencyEstimatorConfig` | Evaluation estimator configuration |
| `token_budget` | `int` | Reconstructed context budget |
| `question` | `str \| None` | Optional question for local question-aware selection |

The default selection strategy is `coverage_support`. Supplying a nonempty `question` automatically uses question-weighted claim support. An omitted, empty, or whitespace-only question preserves question-blind `coverage_support` behavior.

### Chunk Input

Each chunk contains its original text and the identifiers of its associated claims.

```python
chunks = [
    {
        "chunk_id": "release-notes",
        "raw_text": "Version 2.4 removes support for Python 3.9.",
        "claim_ids": [claim_id(claim)],
    },
]
```

`claim_ids` uses canonical identifiers from `omneum.context_selection.claim_id()`.

Multiple chunks can reference the same claim. A chunk can reference multiple claims.

### Context Selection

The default `coverage_support` strategy uses claim-support scores and marginal claim coverage to select chunks.

```python
result = await client.prepare_context(
    observations,
    chunks,
    estimator=estimator,
    token_budget=4096,
    strategy="coverage_support",
    complementary_evidence=True,
)
```

### Question-Aware Selection

Pass the answer question to weight finalized claim contributions by local lexical relevance over the original passage text:

```python
result = await client.prepare_context(
    observations,
    chunks,
    estimator=estimator,
    token_budget=4096,
    question="Which Python versions are supported?",
)
```

The selector weights final claim contributions by passage relevance and credits only improvements over each inferred source cluster's best selected representative. Claim support already includes dependency-adjusted source reliability, so selection does not apply another independence multiplier. Question relevance uses local query-term overlap with passage text; it calls no model or network service. Equally relevant repetitions of the same inferred evidence receive zero marginal credit. The selector divides marginal utility by standalone rendered token cost and enforces the budget on the complete reconstructed context.

`question` controls selection utility. `user_query` is a separate option for local query anchoring and candidate discovery; they cannot be combined in one call.

`complementary_evidence` defaults to `False`.

The selector operates on the candidate chunks and packs the selected text under the token budget.

### Query Conditioning

Pass the retrieval query through `user_query`:

```python
result = await client.prepare_context(
    observations,
    chunks,
    estimator=estimator,
    token_budget=4096,
    user_query="Which Python versions are supported?",
)
```

For retrieval pipelines that already compute relevance scores:

```python
result = await client.prepare_context(
    observations,
    chunks,
    estimator=estimator,
    token_budget=4096,
    chunk_relevance={
        "release-notes": 0.94,
        "installation-guide": 0.81,
    },
    relevance_score_type="similarity",
)
```

Supported score types:

| Value | Input |
|---|---|
| `similarity` | Similarity scores |
| `distance` | Distance scores |
| `rank` | Retrieval ranks |
| `reranker_score` | Reranker scores |

Local relevance computation supports `bm25` and `minilm`.

```python
result = await client.prepare_context(
    observations,
    chunks,
    estimator=estimator,
    token_budget=4096,
    user_query="Which Python versions are supported?",
    local_relevance="bm25",
)
```

Candidate discovery can be configured with `candidate_discovery` and `candidate_count`.

```python
result = await client.prepare_context(
    observations,
    chunks,
    estimator=estimator,
    token_budget=4096,
    user_query="Which Python versions are supported?",
    candidate_discovery="top_k",
    candidate_count=5,
)
```

Supported discovery modes are `all`, `top_k`, and `expanded`.

The `coverage_support_query` strategy supports claim-level relevance:

```python
result = await client.prepare_context(
    observations,
    chunks,
    estimator=estimator,
    token_budget=4096,
    strategy="coverage_support_query",
    claim_relevance={
        claim_id(claim): 1.0,
    },
)
```

### Token Budgeting

`token_budget` limits the reconstructed context, including chunk headers and separators.

The default token counter uses a Unicode word/punctuation proxy.

Pass a model tokenizer through `count_tokens`:

```python
result = await client.prepare_context(
    observations,
    chunks,
    estimator=estimator,
    token_budget=4096,
    count_tokens=count_model_tokens,
    token_counter_name="model_tokenizer",
)
```

The callable accepts a string and returns an integer token count:

```python
Callable[[str], int]
```

`token_counter_name` identifies the counter in the returned selection metadata.

### Inspect Prepared Context

```python
print(result["context"])

for chunk in result["chunks"]:
    print(chunk["chunk_id"])
    print(chunk["score"])
    print(chunk["raw_text"])
```

The selected chunk identifiers are available in final rendering order:

```python
for chunk_id in result["packed_chunk_ids"]:
    print(chunk_id)
```

## Response Schema

`prepare_context()` returns `dict[str, Any]`.

Default response:

```text
context
chunks
packed_chunk_ids
selection
evaluation
```

### Selection

```python
selection = result["selection"]

print(selection["input_tokens"])
print(selection["selected_tokens"])
print(selection["token_budget"])
print(selection["reduction_ratio"])
print(selection["claim_coverage"])
```

| Field | Type |
|---|---|
| `input_tokens` | `int` |
| `selected_tokens` | `int` |
| `token_budget` | `int` |
| `reduction_ratio` | `float \| None` |
| `token_counter` | `str` |
| `claim_coverage` | `dict[str, int]` |

Claim coverage contains `covered` and `total`.

```json
{
  "covered": 1,
  "total": 1
}
```

The reduction ratio is calculated from input and selected token counts:

```text
(input_tokens - selected_tokens) / input_tokens
```

Zero input with zero selected tokens produces `0.0`. Zero input with positive selected tokens produces `null`.

### Evaluation

```python
evaluation = result["evaluation"]

print(evaluation["source_reliability"])
print(evaluation["claim_support"])
print(evaluation["converged"])
```

| Field | Type |
|---|---|
| `source_reliability` | `dict[str, float]` |
| `claim_support` | `dict[str, float]` |
| `max_claim_support` | `float \| None` |
| `converged` | `bool` |
| `iterations` | `int` |
| `convergence_delta` | `float` |
| `convergence_tolerance` | `float` |

Source and claim identifiers are canonical hexadecimal serializations.

### Pairwise Dependencies

Set `include_dependencies=True` to include the evaluated source dependencies.

```python
result = await client.prepare_context(
    observations,
    chunks,
    estimator=estimator,
    token_budget=4096,
    include_dependencies=True,
)

for pair in result["evaluation"]["pairwise_dependencies"]:
    print(pair["source_a"], pair["source_b"], pair["dependency"])
```

Each entry contains `source_a`, `source_b`, and `dependency`.

The field is omitted by default.

### Execution Telemetry

Set `include_telemetry=True` to return execution measurements.

```python
result = await client.prepare_context(
    observations,
    chunks,
    estimator=estimator,
    token_budget=4096,
    include_telemetry=True,
)

telemetry = result["telemetry"]

print(telemetry["sdk_end_to_end_latency_ms"])
print(telemetry["cpu_time_ms"])
print(telemetry["peak_memory_bytes"])
```

| Field | Measurement |
|---|---|
| `sdk_end_to_end_latency_ms` | SDK preparation latency |
| `evaluation_latency_ms` | SDK evaluation latency |
| `graph_evaluation_latency_ms` | Graph evaluation latency |
| `mcp_roundtrip_latency_ms` | MCP round-trip latency |
| `chunk_selection_latency_ms` | Chunk selection latency |
| `context_reconstruction_latency_ms` | Reconstruction latency |
| `local_inference_latency_ms` | Local inference verification latency |
| `cpu_time_ms` | SDK process CPU time |
| `peak_memory_bytes` | SDK process lifetime peak RSS |
| `cpu_time_scope` | CPU measurement scope |
| `peak_memory_scope` | Memory measurement scope |

Measurements unavailable on the current platform may be `null`.

### Execution Logging

`collect_telemetry=True` emits execution measurements through the `omneum.execution` logger.

```python
result = await client.prepare_context(
    observations,
    chunks,
    estimator=estimator,
    token_budget=4096,
    collect_telemetry=True,
    include_telemetry=True,
)
```

`collect_telemetry` controls logging. `include_telemetry` controls the returned telemetry object.

## Local Persistence

The SDK persists evaluations and context-preparation execution history in SQLite.

The default database filename is `omneum.db`, resolved through `get_context_db_path()`.

Each successful `prepare_context()` call records an execution-history entry linked to its evaluation run. The entry includes token counts and execution measurements.

To disable local persistence:

```python
async with open_stdio_client(
    config,
    server,
    local_persistence=None,
) as client:
    result = await client.prepare_context(
        observations,
        chunks,
        estimator=estimator,
        token_budget=4096,
    )
```

## Map Retrieved Chunks

`ContextMapper` converts retrieval records into typed observations.

```python
from datetime import datetime, timezone

now = datetime.now(timezone.utc)

records = [
    {
        "id": "research-result",
        "url": "https://research.example.com/acme-q3",
        "company": "acme-corp",
        "revenue": 42_000_000,
        "text": "Acme reported quarterly revenue of $42 million.",
    },
    {
        "id": "analytics-result",
        "url": "https://analytics.example.com/acme-q3",
        "company": "acme-corp",
        "revenue": 42_000_000,
        "text": "Quarterly revenue was reported as $42 million.",
    },
]
```

Configure the mapper:

```python
from omneum import ContextMapper, Source

mapper = ContextMapper(
    source=lambda row: Source(
        kind="web_document",
        identifier=row["url"],
    ),
    entity_namespace=lambda row: "company",
    entity="company",
    attribute=lambda row: "quarterly_revenue_usd",
    value="revenue",
    observation_id="id",
    observed_at=lambda row: now,
)

observations = mapper.map_many(records)
```

Build the associated chunk mappings:

```python
from omneum.context_selection import claim_id

chunks = [
    {
        "chunk_id": row["id"],
        "raw_text": row["text"],
        "claim_ids": [claim_id(observation.claim)],
    }
    for row, observation in zip(records, observations)
]
```

Pass the mapped observations and original chunks to `prepare_context()`:

```python
result = await client.prepare_context(
    observations,
    chunks,
    estimator=estimator,
    token_budget=4096,
)
```

String mapper arguments reference input fields. Callables can transform values:

```python
mapper = ContextMapper(
    source=lambda row: Source("web_document", row["url"]),
    entity_namespace=lambda row: "company",
    entity="company",
    attribute=lambda row: "quarterly_revenue_usd",
    value=lambda row: normalize_revenue(row),
    observation_id="id",
    observed_at=lambda row: now,
)
```

See [ContextMapper](context-mapper.md) for the full mapping contract.

## Source Provenance

`Observation` records the source and normalized claim.

```python
from omneum import Claim, Observation, Source

claim = Claim(
    entity_namespace="service",
    entity="payment_api",
    attribute="status_code",
    value=200,
)

observation = Observation(
    observation_id="research-result",
    source=Source(
        kind="web_document",
        identifier="https://research.example.com/payment-status",
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

| Field | Description |
|---|---|
| `source_modified_at` | Source-reported modification timestamp |
| `upstream_sources` | Upstream derivation sources |
| `cited_sources` | Explicitly cited sources |
| `parent_observation_ids` | Parent observations |
| `retrievals` | Associated retrieval executions |

Additional metadata can be attached to the observation:

```python
observation = Observation(
    observation_id="research-result",
    source=source,
    claim=claim,
    observed_at=now,
    metadata={
        "request_id": request_id,
        "tool_name": tool_name,
    },
)
```

## Estimator Configuration

`DependencyEstimatorConfig` configures the estimator used during evaluation.

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
```

Pass the configuration to `prepare_context()`:

```python
result = await client.prepare_context(
    observations,
    chunks,
    estimator=estimator,
    token_budget=4096,
)
```

The estimator settings apply to the current evaluation.

## In-Process Evaluation

`omneum.evaluate()` runs the evaluation algorithm synchronously.

```python
import omneum
from omneum.explanations import explain_evaluation

observations = [
    {
        "url": "https://a.example",
        "value": 4_200_000_000,
        "upstream": ["https://sec.example"],
    },
    {
        "url": "https://b.example",
        "value": 4_200_000_000,
        "upstream": ["https://sec.example"],
    },
    {
        "url": "https://c.example",
        "value": 4_200_000_000,
        "upstream": [],
    },
]

result = omneum.evaluate(observations)

print(explain_evaluation(result))
```

Explicit claim identities can be supplied through `claim`:

```python
records = [
    {
        "url": "https://a.example",
        "value": 4_200_000_000,
        "claim": {
            "entity_namespace": "company",
            "entity": "acme",
            "attribute": "fy2025_gross_revenue",
        },
        "upstream": ["https://sec.example"],
    },
]
```

### Typed Evaluation

`evaluate_context()` accepts `Observation` objects and returns a `ContextEvaluation`.

```python
from omneum import evaluate_context

result = evaluate_context(
    observations,
    estimator=estimator,
)
```

For MCP evaluation:

```python
async with open_stdio_client(config, server) as client:
    result = await client.evaluate_context(
        observations,
        estimator=estimator,
    )
```

### Inspect Evaluation Results

```python
for claim in result.claim_support:
    print("Support:", claim.support)
    print(
        "Independent support:",
        claim.estimated_independent_support_count,
    )
    print("Conflicts:", claim.conflicting_claims)
```

`support` contains the normalized claim-support score.

`estimated_independent_support_count` reports the estimated number of independent supporting sources.

`conflicting_claims` contains competing values for the same normalized entity and attribute.

Pairwise source dependencies:

```python
for dependency in result.pairwise_dependencies:
    print(dependency)
```

## Extract assertions from text

`extract_observations()` uses a configured LLM provider to extract structured assertions from retrieval text.

The provider accepts a prompt and returns a mapping containing a `text` field.

```python
import asyncio
import os
from datetime import datetime, timezone

from anthropic import AsyncAnthropic
from omneum import Source, extract_observations


async def main():
    async with AsyncAnthropic() as client:

        async def generate(prompt):
            response = await client.messages.create(
                model=os.environ["ANTHROPIC_MODEL"],
                max_tokens=2048,
                messages=[
                    {"role": "user", "content": prompt},
                ],
            )

            if response.stop_reason != "end_turn":
                raise ValueError("Extraction response is incomplete")

            return {
                "text": "".join(
                    block.text
                    for block in response.content
                    if block.type == "text"
                )
            }

        observations = await extract_observations(
            [
                {
                    "id": "report-chunk-1",
                    "source": Source(
                        "web_document",
                        "https://example.com/report",
                    ),
                    "text": "Acme reported revenue of $4.2 billion in 2025.",
                    "observed_at": datetime.now(timezone.utc),
                }
            ],
            provider=generate,
        )

        for observation in observations:
            print(observation.claim.attribute, observation.claim.value)


asyncio.run(main())
```

Install the provider package:

```bash
pip install anthropic
```

Set `ANTHROPIC_API_KEY` and `ANTHROPIC_MODEL` before running.

Each extracted assertion contains `entity_namespace`, `entity`, `attribute`, and `value`.

Observation IDs use the format:

```text
<chunk_id>:<assertion_index>
```

The originating chunk ID is retained in `metadata["chunk_id"]`.

## Format Results

```python
from omneum import explain_claim, explain_dependency

for claim in result.claim_support:
    print(explain_claim(claim))

for dependency in result.pairwise_dependencies:
    print(explain_dependency(dependency))
```

For a complete evaluation summary:

```python
from omneum.explanations import explain_evaluation

print(explain_evaluation(result))
```

## Configuration

Load the installed deployment configuration:

```python
from omneum import OmneumClientConfig

config = OmneumClientConfig.from_local_deployment()
```

To use another configuration directory:

```bash
export OMNEUM_CONFIG_DIR=/etc/omneum
```

For custom endpoints and administrator-managed deployments, see [Deployment](../deploy/README.md).

## Errors

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
| `ContextEvaluationMappingError` | Evaluation identities or results cannot be mapped consistently |
| `ContextEvaluationRejectedError` | Evaluator rejects the request |
| `ContextEvaluationResponseError` | Invalid evaluator response |
| `ContextEvaluationTransportError` | MCP transport failure |

Invalid `ContextMapper` inputs generally raise `TypeError` or `ValueError`.

See [Evaluate Context](api/evaluate-context.md) for the MCP request and response contract.

## Current Limits

Omneum supports CPython 3.11–3.14.

MCP evaluation uses local stdio transport.

The deployment uses one active VOPRF key at a time. Persisted linkage tokens retain their deployment and key-version association.

## Examples

Framework integrations:

- [LangGraph](../examples/langgraph/)
- [LlamaIndex](../examples/llamaindex/)
- [CrewAI](../examples/crewai/)
- [OpenAI Agents SDK](../examples/openai_agents/)
- [Microsoft Agent Framework](../examples/microsoft/)

For a framework-independent integration, see the [enterprise example](../examples/enterprise/).

## Reference

- [Evaluate Context](api/evaluate-context.md)
- [Evaluate VOPRF](api/evaluate-voprf.md)
- [Ping](api/ping.md)
- [ContextMapper](context-mapper.md)
- [Canonicalization](canonicalization.md)
- [Protocol](protocol.md)
- [Installation](guides/installation.md)
- [Deployment](../deploy/README.md)
