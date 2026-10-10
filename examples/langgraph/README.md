
# LangGraph

LangGraph integration for [Omneum](https://github.com/cole-h06/omneum) — provenance-aware context evaluation for AI agents.

Provides two integration patterns:

- **Enterprise Graph** (`build_graph`) — Collect observations from parallel retrieval nodes and evaluate source reliability, claim support, and source dependencies.
- **Conditional Routing** (`build_routing_graph`) — Use Omneum evaluations to retrieve additional evidence, resolve conflicts, diversify sources, and select context before generation.

Both examples use LangGraph's `StateGraph` API and Omneum's Python SDK over MCP stdio.

## Installation

From the repository root:

```bash
uv sync --locked --group langgraph
```

## Quick Start: Enterprise Graph

Run the five-agent retrieval workflow:

```bash
uv run --locked --group langgraph -m examples.langgraph.run
```

Or invoke the graph directly:

```python
import asyncio

from examples.enterprise.workflow.run import QUESTION
from examples.langgraph.graph import build_graph


async def main():
    graph = build_graph()

    result = await graph.ainvoke({
        "question": QUESTION,
        "observation_batches": [],
    })

    print(result["answer"])


asyncio.run(main())
```

The graph collects observations from five retrieval nodes, merges them, evaluates the context through Omneum, and returns a formatted evaluation report.

### Parallel Retrieval

LangGraph uses `StateGraph` to coordinate retrieval and evaluation.

```python
from langgraph.graph import START, END, StateGraph

from examples.langgraph.nodes import (
    retrieve_documents,
    retrieve_research,
    retrieve_sql,
    retrieve_api,
    retrieve_search,
    merge_observations,
    evaluate_context,
    render_answer,
)
from examples.langgraph.state import WorkflowState


builder = StateGraph(WorkflowState)

retrieval_nodes = {
    "retrieve_documents": retrieve_documents,
    "retrieve_research": retrieve_research,
    "retrieve_sql": retrieve_sql,
    "retrieve_api": retrieve_api,
    "retrieve_search": retrieve_search,
}

for name, node in retrieval_nodes.items():
    builder.add_node(name, node)
    builder.add_edge(START, name)
    builder.add_edge(name, "merge_observations")

builder.add_node("merge_observations", merge_observations)
builder.add_node("evaluate_context", evaluate_context)
builder.add_node("render_answer", render_answer)

builder.add_edge("merge_observations", "evaluate_context")
builder.add_edge("evaluate_context", "render_answer")
builder.add_edge("render_answer", END)

graph = builder.compile()
```

| Retrieval node | Source |
|---|---|
| `retrieve_documents` | Internal documents |
| `retrieve_research` | Research evidence |
| `retrieve_sql` | SQL records |
| `retrieve_api` | API responses |
| `retrieve_search` | Search results |

The graph collects parallel updates through an `Annotated` state reducer and merges observation batches in deterministic order.

See [`graph.py`](graph.py), [`nodes.py`](nodes.py), and [`state.py`](state.py).

## Quick Start: Conditional Routing

Run all three routing scenarios:

```bash
uv run --locked --group langgraph \
  -m examples.langgraph.routing.run
```

Run an individual scenario:

```bash
uv run --locked --group langgraph \
  -m examples.langgraph.routing.run --scenario resolve_conflicts
```

Available scenarios:

| Scenario | Routing condition | Action |
|---|---|---|
| `diversify_sources` | Supporting sources lack sufficient independence | Retrieve evidence from additional independent sources |
| `retrieve_support` | Required evidence is missing or insufficient | Retrieve additional supporting observations |
| `resolve_conflicts` | Competing claims have insufficient support separation | Retrieve evidence addressing competing values |

The routing example uses synthetic enterprise evidence fixtures and evaluates each evidence set through the Omneum MCP server.

### Build the Routing Graph

```python
from examples.langgraph.routing.graph import build_routing_graph

graph = build_routing_graph()
```

To evaluate a preloaded observation set:

```python
from examples.langgraph.routing.graph import build_routing_graph
from examples.langgraph.routing.scenarios import initial_observations

graph = build_routing_graph(preloaded=True)

result = await graph.ainvoke({
    "question": "Evaluate the EU Customer Support Copilot deployment.",
    "observation_batches": [],
    "observations": initial_observations("resolve_conflicts"),
    "retry_count": 0,
    "routing_history": (),
})

print(result["routing_history"])
print(result["answer"])
```

### Conditional Edges

Use `add_conditional_edges()` to select the next node from Omneum's evaluation results.

```python
from examples.langgraph.routing.policy import assess_context


def route_context(state):
    decision = assess_context(
        state["context_evaluation"],
        retries=state.get("retry_count", 0),
    )
    return decision.route


builder.add_conditional_edges(
    "evaluate_context",
    route_context,
    {
        "generate": "select_context",
        "retrieve_support": "retrieve_support",
        "resolve_conflicts": "resolve_conflicts",
        "diversify_sources": "diversify_sources",
        "escalate": "escalate",
    },
)
```

Each retrieval branch adds observations and returns to evaluation:

```python
for node in (
    "retrieve_support",
    "resolve_conflicts",
    "diversify_sources",
):
    builder.add_edge(node, "evaluate_context")
```

The graph continues until the context satisfies the application policy or the retry limit is reached.

See [`routing/graph.py`](routing/graph.py).

## Context Evaluation

The evaluation node maps retrieved observations and submits them to Omneum through MCP stdio.

```python
from examples.enterprise.config import example_deployment
from examples.enterprise.workflow.run import estimator_config
from omneum import open_stdio_client


async def evaluate_context(state: WorkflowState) -> dict[str, object]:
    with example_deployment() as (config, server):
        async with open_stdio_client(config, server) as client:
            result = await client.evaluate_mapped(
                state["observations"],
                mapper,
                estimator=estimator_config(),
            )

    return {"context_evaluation": result}
```

The shared `ContextMapper` extracts claim fields, source identity, timestamps, lineage, and dependency signals.

### Evaluation Results

```python
evaluation = result["context_evaluation"]

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
for claim in evaluation.claim_support:
    print(
        claim.claim.attribute,
        claim.claim.value,
        claim.support,
        claim.estimated_independent_support_count,
    )
```

Print the standard Omneum report:

```python
print(evaluation.explanation)
```

See [`nodes.py`](nodes.py).

## Routing and Context Selection

The application routing policy uses claim support, estimated independent support, and competing claim values.

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

### Context Selection Node

```python
from examples.langgraph.routing.selection import select_context


def select_claims(state):
    return {
        "selected_claims": select_context(
            state["context_evaluation"]
        ),
    }


builder.add_node("select_context", select_claims)
builder.add_edge("select_context", "generate")
```

The generation node consumes `selected_claims` instead of the complete evaluation. Claims failing the application's independent-support or conflict-separation requirements are excluded.

See [`routing/policy.py`](routing/policy.py) and [`routing/selection.py`](routing/selection.py).

## Example Output

Recorded output from the conflict-resolution scenario:

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

The conflicting values remain available in the evaluation but are excluded from the selected context.

The example produces a deterministic response from selected claims. No LLM call is required.

## Configuration

| Component | Implementation |
|---|---|
| Graph orchestration | `langgraph.graph.StateGraph` |
| Context mapping | `omneum.ContextMapper` |
| Evaluation client | `omneum.open_stdio_client` |
| Dependency estimator | `examples.enterprise.workflow.run.estimator_config` |
| Routing policy | `examples.langgraph.routing.policy` |
| Context selection | `examples.langgraph.routing.selection` |
| Evidence fixtures | `examples.langgraph.routing.scenarios` |
| Additional retrieval | `examples.langgraph.routing.retrieval` |

## Tests

Run routing and selection tests:

```bash
uv run --locked --group langgraph -m pytest -q \
  tests/test_langgraph_selection.py \
  tests/test_langgraph_routing_selection.py \
  tests/test_langgraph_routing.py \
  tests/test_langgraph_routing_scenarios.py \
  tests/test_langgraph_routing_strategies.py
```

Run the enterprise integration tests:

```bash
uv run --locked --group langgraph \
  -m pytest -q tests/test_enterprise_example.py
```

## Files

| File | Description |
|---|---|
| [`graph.py`](graph.py) | Parallel retrieval and evaluation graph |
| [`nodes.py`](nodes.py) | Retrieval, merging, evaluation, and rendering |
| [`state.py`](state.py) | Graph state and parallel reducers |
| [`run.py`](run.py) | Enterprise graph entry point |
| [`routing/graph.py`](routing/graph.py) | Conditional routing graph |
| [`routing/policy.py`](routing/policy.py) | Routing decisions and thresholds |
| [`routing/retrieval.py`](routing/retrieval.py) | Additional evidence retrieval |
| [`routing/scenarios.py`](routing/scenarios.py) | Scenario observation sets |
| [`routing/selection.py`](routing/selection.py) | Claim selection policy |
| [`routing/selection_graph.py`](routing/selection_graph.py) | Standalone context-selection graph |
| [`routing/run.py`](routing/run.py) | Routing scenario CLI |
| [`../enterprise/`](../enterprise/) | Shared enterprise retrieval example |

## Requirements

- Python environment compatible with the repository's locked dependencies
- LangGraph dependency group
- Omneum Python SDK and local MCP server

## Documentation

- [LangGraph Documentation](https://docs.langchain.com/oss/python/langgraph/overview)
- [Enterprise Example](../enterprise/)
- [CrewAI Integration](../crewai/)
