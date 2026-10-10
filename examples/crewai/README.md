
# CrewAI

CrewAI integration for Omneum — provenance-aware context evaluation for AI agents.

Provides two integration patterns:

- **Enterprise Flow** (`EnterpriseFlow`) — Collect observations from multiple retrieval agents and evaluate source reliability, claim support, and source dependencies.
- **Conditional Routing** (`RoutingFlow`) — Use Omneum evaluation results to retrieve additional evidence, resolve conflicts, diversify sources, and select context before generating a response.

Both examples use CrewAI's native `Flow` API and Omneum's Python SDK over MCP stdio.

## Installation

From the repository root:

```bash
uv sync --locked --python 3.13 --group crewai
```

## Quick Start: Enterprise Flow

Run the five-agent retrieval workflow:

```bash
uv run --locked --python 3.13 --group crewai \
  -m examples.crewai.run
```

Or invoke the Flow directly:

```python
import asyncio

from examples.crewai.flow import EnterpriseFlow
from examples.enterprise.workflow.run import QUESTION


async def main():
    flow = EnterpriseFlow()
    answer = await flow.kickoff_async(
        inputs={"question": QUESTION}
    )
    print(answer)


asyncio.run(main())
```

The Flow collects observations from five retrieval methods, merges them, evaluates the context through Omneum, and returns a formatted evaluation report.

### Parallel Retrieval

```python
from crewai.flow.flow import Flow, and_, listen, start

class EnterpriseFlow(Flow):
    @start()
    def retrieve_documents(self):
        self.state.document_observations = documents_agent()

    @start()
    def retrieve_research(self):
        self.state.research_observations = research_agent()

    @listen(and_(retrieve_documents, retrieve_research))
    def merge_observations(self):
        ...
```

The complete implementation also retrieves evidence from SQL, API, and search agents.

| Retrieval method | Source |
|---|---|
| `retrieve_documents` | Internal documents |
| `retrieve_research` | Research evidence |
| `retrieve_sql` | SQL records |
| `retrieve_api` | API responses |
| `retrieve_search` | Search results |

See [`flow.py`](flow.py).

## Quick Start: Conditional Routing

Run all three routing scenarios:

```bash
uv run --locked --python 3.13 --group crewai \
  -m examples.crewai.routing.run --scenario all
```

Run a specific scenario:

```bash
uv run --locked --python 3.13 --group crewai \
  -m examples.crewai.routing.run --scenario diversify_sources
```

Available scenarios:

| Scenario | Routing condition | Action |
|---|---|---|
| `diversify_sources` | Supporting sources lack sufficient independence | Retrieve evidence from an independent source |
| `retrieve_support` | Required evidence is missing or insufficient | Retrieve additional supporting observations |
| `resolve_conflicts` | Competing claims have insufficient support separation | Retrieve evidence to resolve competing values |

The routing example uses synthetic enterprise evidence fixtures and evaluates each evidence set through the Omneum MCP server.

### CrewAI Routing

Use `@router` to select the next action from Omneum's evaluation results:

```python
from crewai.flow.flow import Flow, listen, router, start

from examples.langgraph.routing.policy import assess_context


class RoutingFlow(Flow):
    @start()
    async def evaluate_context(self):
        ...

    @router(evaluate_context)
    def route_context(self):
        decision = assess_context(
            self.state.context_evaluation,
            retries=self.state.retry_count,
        )
        return decision.route

    @listen("diversify_sources")
    def retrieve_diverse_evidence(self):
        ...

    @listen("retrieve_support")
    def retrieve_support_evidence(self):
        ...

    @listen("resolve_conflicts")
    def retrieve_conflict_evidence(self):
        ...
```

Retrieval branches append new observations and trigger another evaluation. The Flow continues until the context meets the application policy or the retry limit is reached.

See [`routing/flow.py`](routing/flow.py).

## Context Evaluation

Both Flows use Omneum's Python SDK to evaluate mapped observations.

```python
from omneum import ContextMapper, open_stdio_client
from examples.enterprise.config import example_deployment
from examples.enterprise.workflow.run import estimator_config

with example_deployment() as (config, server):
    async with open_stdio_client(config, server) as client:
        evaluation = await client.evaluate_mapped(
            observations,
            mapper,
            estimator=estimator_config(),
        )
```

`ContextMapper` maps the retrieved evidence into Omneum's observation contract, including source identity, claims, timestamps, and dependency signals.

### Evaluation Results

```python
source_scores = evaluation.source_reliability
claim_scores = evaluation.claim_support
dependencies = evaluation.pairwise_dependencies
latency_ms = evaluation.evaluation_latency_ms
```

| Field | Description |
|---|---|
| `source_reliability` | Source reliability scores |
| `claim_support` | Claim support scores, ordered by attribute and descending support |
| `pairwise_dependencies` | Estimated source dependencies |
| `evaluation_latency_ms` | Evaluation latency in milliseconds |
| `explanation` | Formatted evaluation report |

Inspect claim support and estimated independent support:

```python
for result in evaluation.claim_support:
    print(
        result.claim.attribute,
        result.claim.value,
        result.support,
        result.estimated_independent_support_count,
    )
```

Print the standard Omneum report:

```python
print(evaluation.explanation)
```

## Routing and Context Selection

The routing example reuses the policy and selection functions from `examples/langgraph/routing/`.

```python
from examples.langgraph.routing.policy import (
    RoutingPolicy,
    assess_context,
)
from examples.langgraph.routing.selection import select_context

policy = RoutingPolicy(
    min_independent_support=1.9,
    min_support_ratio=2.0,
    max_retries=2,
)

decision = assess_context(
    evaluation,
    retries=retry_count,
    policy=policy,
)

if decision.route == "generate":
    selected = select_context(evaluation, policy=policy)
```

| Route | Behavior |
|---|---|
| `generate` | Select supported claims and produce the response |
| `retrieve_support` | Retrieve additional supporting evidence |
| `resolve_conflicts` | Retrieve evidence for competing claim values |
| `diversify_sources` | Retrieve evidence from independent sources |
| `escalate` | Stop when the retry limit is reached |

The policy operates on Omneum's claim support and estimated independent support. It does not modify BRAID scoring.

## Example Output

Recorded results from the three CrewAI routing scenarios:

| Scenario | Observations | Retries | Routing |
|---|---|---:|---|
| `diversify_sources` | 17 → 18 | 1 | `diversify_sources → generate` |
| `retrieve_support` | 11 → 14 | 2 | `retrieve_support → retrieve_support → generate` |
| `resolve_conflicts` | 9 → 12 | 1 | `resolve_conflicts → generate` |

Example terminal output for `resolve_conflicts`:

```text
=== resolve_conflicts ===
Observations: 9 -> 12
Routing: resolve_conflicts -> generate
Retries: 1

Claim support:
  input_data_policy: redacted customer content only | support=0.1804 | independent=2.000
  input_data_policy: unredacted customer content allowed | support=0.0105 | independent=1.000
  processing_region: EU | support=0.1804 | independent=2.000
  processing_region: US | support=0.0105 | independent=1.000
  provider_retention: 0 days | support=0.1804 | independent=2.000
  provider_retention: 30 days | support=0.0105 | independent=1.000

Answer:
Application decision: EVALUATION COMPLETE
Selected context:
input_data_policy: redacted customer content only
provider_retention: 0 days
processing_region: EU
```

The example generates a deterministic response from selected claims. No LLM call is required.

## Configuration

| Component | Implementation |
|---|---|
| CrewAI orchestration | `Flow`, `@start`, `@listen`, `@router` |
| Context mapping | `omneum.ContextMapper` |
| Evaluation client | `omneum.open_stdio_client` |
| Dependency estimator | `examples.enterprise.workflow.run.estimator_config` |
| Routing policy | `examples.langgraph.routing.policy` |
| Context selection | `examples.langgraph.routing.selection` |
| Evidence fixtures | `examples.langgraph.routing.scenarios` |
| Additional retrieval | `examples.langgraph.routing.retrieval` |

## Tests

```bash
uv run --locked --python 3.13 \
  --group crewai --group langgraph \
  -m pytest -q tests/test_crewai_routing.py
```

Run CrewAI and LangGraph routing tests together:

```bash
uv run --locked --python 3.13 \
  --group crewai --group langgraph \
  -m pytest -q \
  tests/test_crewai_routing.py \
  tests/test_langgraph_routing.py \
  tests/test_langgraph_routing_scenarios.py
```

## Files

| File | Description |
|---|---|
| [`flow.py`](flow.py) | Five-agent CrewAI Flow |
| [`state.py`](state.py) | Enterprise Flow state |
| [`run.py`](run.py) | Enterprise Flow entry point |
| [`routing/flow.py`](routing/flow.py) | Conditional routing and context selection |
| [`routing/state.py`](routing/state.py) | Routing state |
| [`routing/run.py`](routing/run.py) | Routing scenario CLI |
| [`routing/README.md`](routing/README.md) | Routing example |
| [`../../tests/test_crewai_routing.py`](../../tests/test_crewai_routing.py) | Routing and selection tests |
| [`../enterprise/`](../enterprise/) | Shared enterprise retrieval example |

## Requirements

- Python 3.11–3.13
- CrewAI 1.15.18 (locked environment)
- Omneum Python SDK and local MCP server

## Documentation

- [CrewAI Flows](https://docs.crewai.com/en/concepts/flows)
- [CrewAI Documentation](https://docs.crewai.com/)
- [Enterprise Example](../enterprise/)
- [LangGraph Integration](../langgraph/)