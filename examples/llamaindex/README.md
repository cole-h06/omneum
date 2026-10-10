
# LlamaIndex

LlamaIndex integration for [Omneum](https://github.com/cole-h06/omneum) — provenance-aware context evaluation for AI agents.

Provides two integration patterns:

- **Enterprise Workflow** (`EnterpriseWorkflow`) — Collect observations from multiple retrieval agents and evaluate source reliability, claim support, and source dependencies.
- **Conditional Routing** (`RoutingWorkflow`) — Use Omneum evaluations to retrieve additional evidence, resolve conflicts, diversify sources, and select context before generation.

Both examples use LlamaIndex's native `Workflow` API and Omneum's Python SDK over MCP stdio.

## Installation

From the repository root, using the uv version required by `pyproject.toml`:

```bash
uv sync --locked --python 3.13 --group llamaindex
```

The examples use a locally provisioned Omneum daemon. See the [installation guide](../../docs/guides/installation.md). No LLM API key is required.

## Quick Start: Enterprise Workflow

Run the five-agent retrieval workflow:

```bash
uv run --locked --python 3.13 --group llamaindex \
  -m examples.llamaindex.run
```

Or invoke the Workflow directly:

```python
import asyncio

from examples.llamaindex.workflow import EnterpriseWorkflow


async def main():
    workflow = EnterpriseWorkflow(timeout=30, verbose=False)
    result = await workflow.run()
    print(result)


asyncio.run(main())
```

The Workflow collects 17 observations from five retrieval methods, evaluates them through Omneum, and returns a formatted evaluation report.

### Native Workflow

LlamaIndex uses `Workflow`, `@step`, and typed events to coordinate retrieval, evaluation, and response generation.

```python
from llama_index.core.workflow import (
    StartEvent,
    StopEvent,
    Workflow,
    step,
)


class EnterpriseWorkflow(Workflow):
    @step
    async def retrieve(
        self,
        _: StartEvent,
    ) -> RetrievalResultsEvent:
        return RetrievalResultsEvent(
            results=collect_observations(),
        )

    @step
    async def render(
        self,
        event: ContextEvaluationEvent,
    ) -> StopEvent:
        return StopEvent(
            result=render_result(event.result),
        )
```

The evaluation step runs between retrieval and rendering.

| Retrieval method | Source |
|---|---|
| Documents | Internal documents |
| Research | Research evidence |
| SQL | SQL records |
| API | API responses |
| Search | Search results |

Retrieval uses deterministic enterprise fixtures rather than live external connectors.

See [`workflow.py`](workflow.py) and the [enterprise example](../enterprise/).

## Quick Start: Conditional Routing

Run all three routing scenarios:

```bash
uv run --locked --python 3.13 --group llamaindex \
  -m examples.llamaindex.routing.run --scenario all
```

Run an individual scenario:

```bash
uv run --locked --python 3.13 --group llamaindex \
  -m examples.llamaindex.routing.run --scenario resolve_conflicts
```

Available scenarios:

| Scenario | Routing condition | Action |
|---|---|---|
| `diversify_sources` | Supporting sources lack sufficient independence | Retrieve evidence from additional independent sources |
| `retrieve_support` | Required evidence is missing or insufficient | Retrieve additional supporting observations |
| `resolve_conflicts` | Competing claims have insufficient support separation | Retrieve evidence addressing competing values |

The routing example uses synthetic enterprise evidence fixtures. Each retrieval attempt triggers another evaluation through the Omneum MCP server.

### Native Event Routing

LlamaIndex uses typed events to determine which Workflow step executes next.

```python
from examples.llamaindex.routing.workflow import RoutingWorkflow

workflow = RoutingWorkflow(timeout=60, verbose=False)
state = await workflow.run(scenario="resolve_conflicts")

print(state.routing_history)
print(state.answer)
```

The Workflow follows this event sequence:

```text
StartEvent
    |
EvidenceEvent
    |
EvaluatedEvent
    |
    +-- RetrieveSupportEvent ------+
    |                              |
    +-- ResolveConflictsEvent -----+--> EvidenceEvent
    |                              |         |
    +-- DiversifySourcesEvent -----+         |
    |                                        |
    |                          EvaluatedEvent
    |
    +-- SelectContextEvent --> GenerateEvent --> StopEvent
    |
    +-- EscalateEvent -------------------------> StopEvent
```

The routing step selects the next event from the application policy:

```python
@step
async def route_context(
    self,
    ctx: Context,
    event: EvaluatedEvent,
) -> (
    RetrieveSupportEvent
    | ResolveConflictsEvent
    | DiversifySourcesEvent
    | SelectContextEvent
    | EscalateEvent
):
    state = event.state

    decision = assess_context(
        state.context_evaluation,
        retries=state.retry_count,
    )

    state.decision = decision
    state.routing_history = (*state.routing_history, decision.route)

    event_type = {
        "retrieve_support": RetrieveSupportEvent,
        "resolve_conflicts": ResolveConflictsEvent,
        "diversify_sources": DiversifySourcesEvent,
        "generate": SelectContextEvent,
        "escalate": EscalateEvent,
    }[decision.route]

    return emit(ctx, event_type(state=state))
```

Each retrieval branch adds unseen observations and returns an `EvidenceEvent` for reevaluation. The Workflow continues until the application policy passes or the retry limit is reached.

See [`routing/workflow.py`](routing/workflow.py) and [`routing/state.py`](routing/state.py).

## Context Evaluation

Both Workflows use Omneum's Python SDK over MCP stdio.

The enterprise Workflow maps retrieved evidence through `ContextMapper` and calls `evaluate_mapped()`. The routing Workflow operates on existing SDK `Observation` objects and calls `evaluate_context()` directly.

```python
from examples.enterprise.config import example_deployment
from examples.enterprise.workflow.run import estimator_config
from omneum import open_stdio_client


with example_deployment() as (config, server):
    async with open_stdio_client(config, server) as client:
        evaluation = await client.evaluate_context(
            observations,
            estimator=estimator_config(),
        )
```

The evaluation includes source reliability, claim support, estimated independent support, and source dependencies.

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

Scores represent relative evidence support, not probabilities or authorization decisions.

See [`workflow.py`](workflow.py) and [`routing/workflow.py`](routing/workflow.py).

## Routing and Context Selection

The routing Workflow reuses the application policy and selection functions from `examples/langgraph/routing/`.

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

### Context Selection

Selection executes as a native Workflow step:

```python
@step
async def select_claims(
    self,
    ctx: Context,
    event: SelectContextEvent,
) -> GenerateEvent:
    state = event.state

    state.selected_claims = select_context(
        state.context_evaluation
    )

    return emit(ctx, GenerateEvent(state=state))
```

The generation step consumes `selected_claims`, not the complete evaluation. Claims failing the independent-support or competing-value requirements are excluded.

The response is deterministic. No LLM call is required.

See [`routing/workflow.py`](routing/workflow.py), [`../langgraph/routing/policy.py`](../langgraph/routing/policy.py), and [`../langgraph/routing/selection.py`](../langgraph/routing/selection.py).

## Example Output

Recorded results from the three LlamaIndex routing scenarios:

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

Competing values remain available in the evaluation results but are excluded from selected context.

The CrewAI and LangGraph integrations produced the same observation counts, routing histories, retry counts, selected context, and final decisions for all three scenarios.

## Configuration

| Component | Implementation |
|---|---|
| LlamaIndex orchestration | `Workflow`, `@step`, `StartEvent`, `StopEvent`, custom typed events |
| Context mapping | `omneum.ContextMapper` |
| Evaluation client | `omneum.open_stdio_client` |
| Dependency estimator | `examples.enterprise.workflow.run.estimator_config` |
| Routing policy | `examples.langgraph.routing.policy` |
| Context selection | `examples.langgraph.routing.selection` |
| Evidence fixtures | `examples.langgraph.routing.scenarios` |
| Additional retrieval | `examples.langgraph.routing.retrieval` |

The default routing policy requires estimated independent support of at least `1.9`, a competing-value support ratio of at least `2.0`, and allows up to two retrieval attempts.

## Tests

Run the LlamaIndex routing and regression tests:

```bash
uv run --locked --python 3.13 --group llamaindex \
  -m pytest -q tests/test_llamaindex_routing.py
```

Run the integration comparison suite:

```bash
uv run --locked --python 3.13 \
  --group llamaindex --group crewai --group langgraph \
  -m pytest -q \
  tests/test_llamaindex_routing.py \
  tests/test_crewai_routing.py \
  tests/test_langgraph_routing.py \
  tests/test_langgraph_routing_scenarios.py \
  tests/test_langgraph_routing_selection.py \
  tests/test_langgraph_routing_strategies.py \
  tests/test_enterprise_example.py
```

The comparison suite passed **46 tests**, including **14 LlamaIndex tests**, using an isolated functional test daemon.

The tests cover native event transitions, all three routing scenarios, additional evidence retrieval, MCP reevaluation, context selection, conflicting-value exclusion, retry exhaustion, escalation, and the existing enterprise Workflow.

## Files

| File | Description |
|---|---|
| [`workflow.py`](workflow.py) | Enterprise retrieval, evaluation, and rendering |
| [`run.py`](run.py) | Enterprise Workflow entry point |
| [`routing/workflow.py`](routing/workflow.py) | Native event routing and context selection |
| [`routing/state.py`](routing/state.py) | Per-run Workflow state and typed events |
| [`routing/run.py`](routing/run.py) | Routing scenario CLI |
| [`../../tests/test_llamaindex_routing.py`](../../tests/test_llamaindex_routing.py) | Routing and regression tests |
| [`../enterprise/`](../enterprise/) | Shared enterprise retrieval example |
| [`../langgraph/routing/`](../langgraph/routing/) | Shared policy, selection, and evidence fixtures |

## Requirements

- Python 3.13 with the repository's locked `llamaindex` dependency group
- uv 0.12.10, as required by the repository
- Omneum Python SDK and provisioned local MCP daemon

## Documentation

- [LlamaIndex Workflows](https://developers.llamaindex.ai/python/llamaagents/workflows/)
- [Omneum SDK](../../docs/sdk.md)
- [Installation](../../docs/guides/installation.md)
- [Enterprise Example](../enterprise/)
- [CrewAI Integration](../crewai/)
- [LangGraph Integration](../langgraph/)