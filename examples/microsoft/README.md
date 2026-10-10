# Microsoft Agent Framework

Microsoft Agent Framework integration for Omneum — provenance-aware context evaluation for AI agents.

Provides two integration patterns:

- **Enterprise Agent** (`Agent`) — OpenAI invokes an evaluation tool that collects enterprise fixtures, maps observations, evaluates them through Omneum MCP, and returns a report for model-generated answers.
- **Conditional Routing** (`Workflow`) — Native executors and conditional edges retrieve additional evidence, reevaluate, select supported context, and produce a deterministic response. No OpenAI key or model is required.

## Installation

From the repository root, using uv 0.12.10:

```bash
uv sync --locked --python 3.13 --group microsoft
```

If the default executable differs, use `~/.local/bin/uv`. Both examples require a provisioned local Omneum daemon; see the [installation guide](../../docs/guides/installation.md).

## Quick Start: Enterprise Agent

Configure OpenAI and run the existing interactive agent:

```bash
export OPENAI_API_KEY="your-api-key"
export OPENAI_MODEL="gpt-5.5"
uv run --locked --python 3.13 --group microsoft \
  -m examples.microsoft.run
```

Enter a deployment-readiness question at `Question:`. The model uses the `evaluate_context` tool and generates the final answer.

The configuration in [`agent.py`](agent.py):

```python
agent = Agent(
    client=OpenAIChatClient(),
    name="Enterprise AI Assistant",
    instructions=(
        "Answer deployment-readiness questions using the "
        "evaluate_context tool. Base your response on the "
        "context evaluation results."
    ),
    tools=[evaluate_context],
)
```

| Retrieval module | Evidence |
|---|---|
| [`documents.py`](../enterprise/agents/documents.py) | Current policy and stale runbook |
| [`research.py`](../enterprise/agents/research.py) | Readiness brief derived from the runbook |
| [`sql.py`](../enterprise/agents/sql.py) | Model registry |
| [`api.py`](../enterprise/agents/api.py) | Gateway configuration |
| [`search.py`](../enterprise/agents/search.py) | Vendor data controls |

These modules read local JSON fixtures: 17 observations from six sources. They do not retrieve live enterprise data. The basic agent retains its OpenAI generation and does not use the routing workflow.

## Quick Start: Conditional Routing

Run all scenarios:

```bash
uv run --locked --python 3.13 --group microsoft \
  -m examples.microsoft.routing.run --scenario all
```

Run one scenario:

```bash
uv run --locked --python 3.13 --group microsoft \
  -m examples.microsoft.routing.run --scenario retrieve_support
```

| Scenario | Initial evidence | Retrieval action |
|---|---|---|
| `diversify_sources` | All 17 enterprise observations | Add an independent compliance source |
| `retrieve_support` | 11 observations; processing region missing | Retrieve support for missing or weak attributes |
| `resolve_conflicts` | Nine policy, runbook, and readiness observations | Add independent policy-review evidence |

Scenario fixtures and retrieval strategies come directly from [`../langgraph/routing/`](../langgraph/routing/).

## Native Microsoft Workflow Orchestration

Verified against installed `agent-framework` and `agent-framework-core` **1.11.0**, with the official [executor API](https://learn.microsoft.com/en-us/python/api/agent-framework-core/agent_framework.executor?view=agent-framework-python-latest) and [edge documentation](https://learn.microsoft.com/en-us/agent-framework/concepts/workflows/edges).

The installed builder requires `start_executor` and supports `output_from`. Microsoft's [builder source](https://github.com/microsoft/agent-framework/blob/main/python/packages/core/agent_framework/_workflows/_workflow_builder.py) documents these arguments; the generated Python API reference still shows an older constructor.

```text
load_evidence -> evaluate_context -> route_context
                                        |
                                        +-> retrieve_support -----> evaluate_context
                                        +-> resolve_conflicts ----> evaluate_context
                                        +-> diversify_sources ----> evaluate_context
                                        +-> select_claims -> generate_answer
                                        +-> escalate_answer
```

`@executor` creates function executors. `RetrieveEvidence` subclasses `Executor` and registers its method with `@handler`. `WorkflowContext.send_message` passes typed `RoutingState` messages along edges; terminal executors use `yield_output`.

The complete builder in [`routing/workflow.py`](routing/workflow.py):

```python
def build_routing_workflow() -> Workflow:
    builder = WorkflowBuilder(
        start_executor=load_evidence,
        output_from=[generate_answer, escalate_answer],
    )
    builder.add_edge(load_evidence, evaluate_context)
    builder.add_edge(evaluate_context, route_context)
    for strategy in ("retrieve_support", "resolve_conflicts", "diversify_sources"):
        retrieval = RetrieveEvidence(strategy)
        builder.add_edge(
            route_context, retrieval,
            condition=lambda state, route=strategy: state.decision.route == route,
        )
        builder.add_edge(retrieval, evaluate_context)
    builder.add_edge(
        route_context, select_claims,
        condition=lambda state: state.decision.route == "generate",
    )
    builder.add_edge(
        route_context, escalate_answer,
        condition=lambda state: state.decision.route == "escalate",
    )
    builder.add_edge(select_claims, generate_answer)
    return builder.build()
```

Conditional edges dispatch exactly one matching branch. Retrieval edges return to evaluation, so the framework executes the retry cycle. There is no application control loop for routing.

Run the native workflow directly:

```python
import asyncio

from examples.microsoft.routing.workflow import build_routing_workflow


async def main():
    result = await build_routing_workflow().run("resolve_conflicts")
    state = result.get_outputs()[0]
    print(state.answer)


asyncio.run(main())
```

## Context Evaluation

The basic tool uses `ContextMapper` to preserve source identity, claim fields, timestamps, provenance, retrieval records, and seven dependency signals:

```python
mapper = ContextMapper(
    source=lambda x: x.source,
    entity_namespace=lambda x: x.claim.entity_namespace,
    entity=lambda x: x.claim.entity,
    attribute=lambda x: x.claim.attribute,
    value=lambda x: x.claim.value,
    observation_id=lambda x: x.observation_id,
    observed_at=lambda x: x.observed_at,
    source_modified_at=lambda x: x.source_modified_at,
    upstream_sources=lambda x: x.upstream_sources,
    cited_sources=lambda x: x.cited_sources,
    parent_observation_ids=lambda x: x.parent_observation_ids,
    retrievals=lambda x: x.retrievals,
    signals={
            name: lambda x, name=name: x.dependency_signals.get(
                name
            )
            for name in (
                "upstream",
                "citation",
                "assertion_lineage",
                "ownership",
                "temporal",
                "graph",
                "retrieval",
            )
        },
)
```

It calls `client.evaluate_mapped(observations, mapper, estimator=estimator_config())` and returns `render_result(result)` from the [enterprise workflow](../enterprise/workflow/run.py).

Routing fixtures already use Omneum `Observation` objects. The routing executor submits them directly over MCP stdio:

```python
@executor
async def evaluate_context(state: RoutingState, ctx: WorkflowContext[RoutingState]) -> None:
    with example_deployment() as (config, server):
        async with open_stdio_client(config, server) as client:
            state.context_evaluation = await client.evaluate_context(
                state.observations,
                estimator=estimator_config(),
            )
    await ctx.send_message(state)
```

Each retry evaluates the complete accumulated observation set with the shared enterprise estimator. Neither integration changes BRAID, Omneum scoring, or SDK contracts.

## Evaluation Results

| Field | Description |
|---|---|
| `source_reliability` | Relative source reliability scores |
| `claim_support` | Claim support and estimated independent support |
| `pairwise_dependencies` | Estimated source dependencies |
| `evaluation_latency_ms` | Evaluation latency in milliseconds |
| `explanation` | Formatted Omneum evaluation report |

The routing CLI reads the final evaluation:

```python
for item in sorted(
    state.context_evaluation.claim_support,
    key=lambda item: (item.claim.attribute, -item.support),
):
    print(
        f"  {item.claim.attribute}: {item.claim.value}"
        f" | support={item.support:.4f}"
        f" | independent={item.estimated_independent_support_count:.3f}"
    )
```

These scores represent relative evidence support, not probabilities or deployment authorization.

## Routing and Context Selection

The application reuses [`assess_context`](../langgraph/routing/policy.py) and [`select_context`](../langgraph/routing/selection.py).

```python
@executor
async def route_context(state: RoutingState, ctx: WorkflowContext[RoutingState]) -> None:
    state.decision = assess_context(state.context_evaluation, retries=state.retry_count)
    state.routing_history = (*state.routing_history, state.decision.route)
    await ctx.send_message(state)
```

| Policy setting | Default |
|---|---:|
| `min_independent_support` | 1.9 |
| `min_support_ratio` | 2.0 |
| `max_retries` | 2 |

| Route | Behavior |
|---|---|
| `retrieve_support` | Retrieve missing or insufficiently supported attributes |
| `resolve_conflicts` | Retrieve evidence when competing values lack support separation |
| `diversify_sources` | Retrieve independent evidence when supporting sources are dependent |
| `generate` | Select supported claims and produce the response |
| `escalate` | Stop after two unsuccessful retrieval attempts |

Retrieval targets `decision.attributes`, uses the route-specific strategy and attempt number, and deduplicates observation IDs. Selection excludes claims below the independent-support threshold and values without sufficient separation from competing claims.

The selection and deterministic generation executors:

```python
@executor
async def select_claims(state: RoutingState, ctx: WorkflowContext[RoutingState]) -> None:
    state.selected_claims = select_context(state.context_evaluation)
    await ctx.send_message(state)


@executor
async def generate_answer(state: RoutingState, ctx: WorkflowContext[None, RoutingState]) -> None:
    state.answer = "\n".join([
        "Application decision: EVALUATION COMPLETE",
        "Selected context:",
        *(f"{claim.attribute}: {claim.value}" for claim in state.selected_claims),
    ])
    await ctx.yield_output(state)
```

Escalation returns `Application decision: ESCALATE` with no selected claims. Conflicting observations remain available in the evaluation diagnostics but their values are excluded from the generated context.

## Recorded Example Output

Recorded on 2026-10-10 with Python 3.13, uv 0.12.10, the locked Microsoft group, and the configured local Omneum daemon. The all-scenario command exited successfully. MCP startup logs on stderr are omitted below; stdout is reproduced in full.

```text
=== diversify_sources ===
Observations: 17 -> 18
Routing: diversify_sources -> generate
Retries: 1

Claim support:
  input_data_policy: redacted customer content only | support=0.1139 | independent=2.000
  input_data_policy: unredacted customer content allowed | support=0.0058 | independent=1.000
  processing_region: EU | support=0.0994 | independent=2.000
  processing_region: US | support=0.0058 | independent=1.000
  provider_retention: 0 days | support=0.0994 | independent=2.000
  provider_retention: 30 days | support=0.0058 | independent=1.000

Answer:
Application decision: EVALUATION COMPLETE
Selected context:
input_data_policy: redacted customer content only
provider_retention: 0 days
processing_region: EU

=== retrieve_support ===
Observations: 11 -> 14
Routing: retrieve_support -> retrieve_support -> generate
Retries: 2

Claim support:
  input_data_policy: redacted customer content only | support=0.1163 | independent=2.000
  input_data_policy: unredacted customer content allowed | support=0.0077 | independent=1.000
  processing_region: EU | support=0.1880 | independent=1.905
  provider_retention: 0 days | support=0.1276 | independent=2.000
  provider_retention: 30 days | support=0.0077 | independent=1.000

Answer:
Application decision: EVALUATION COMPLETE
Selected context:
input_data_policy: redacted customer content only
provider_retention: 0 days
processing_region: EU

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

The CrewAI, LangGraph, and LlamaIndex all-scenario CLIs were also executed. Their observation counts, routing histories, retries, selected context, and final decisions matched Microsoft for all three scenarios. Numerical support is shown from the Microsoft run above rather than inferred from another integration.

The unchanged basic agent also completed with `OPENAI_MODEL=gpt-5.5`, an available API key, and the local daemon. Its OpenAI-generated answer required redacted content, zero-day retention, and EU processing. Model wording can vary between runs.

## Configuration

| Component | Implementation or setting |
|---|---|
| Basic agent | `agent_framework.Agent` |
| Basic model client | `agent_framework.openai.OpenAIChatClient` |
| OpenAI credentials | `OPENAI_API_KEY` (basic agent only) |
| OpenAI model | `OPENAI_MODEL` or `OPENAI_CHAT_MODEL` (basic agent only) |
| Routing orchestration | `WorkflowBuilder`, `Executor`, `@executor`, `@handler`, conditional `add_edge` |
| Routing state | [`RoutingState`](routing/state.py) |
| Basic context mapping | `omneum.ContextMapper` |
| MCP client | `omneum.open_stdio_client` |
| Deployment | [`example_deployment`](../enterprise/config.py) |
| Estimator | [`estimator_config`](../enterprise/workflow/run.py) |
| Routing policy | [`RoutingPolicy`](../langgraph/routing/policy.py) |
| Selection | [`select_context`](../langgraph/routing/selection.py) |
| Evidence fixtures | [`initial_observations`](../langgraph/routing/scenarios.py) |
| Additional retrieval | [`retrieve_additional_evidence`](../langgraph/routing/retrieval.py) |

## Tests

Microsoft and enterprise regression tests:

```bash
uv run --locked --python 3.13 --group microsoft \
  -m pytest -q tests/test_microsoft_routing.py tests/test_enterprise_example.py
```

Recorded result: **18 passed**. Tests cover native executor transitions, all scenarios, real MCP reevaluation, targeted retrieval and deduplication, supported-context selection, conflicting-value exclusion, retry exhaustion, CLI scenario selection without OpenAI credentials, and the unchanged basic tool's mapper and report. The basic regression test compares mapped and direct evaluation results, constructs an OpenAI client with an unused test credential, and invokes only the evaluation tool.

Cross-integration checks:

```bash
uv run --locked --python 3.13 \
  --group microsoft --group crewai --group langgraph --group llamaindex \
  -m pytest -q \
  tests/test_microsoft_routing.py \
  tests/test_enterprise_example.py \
  tests/test_crewai_routing.py \
  tests/test_llamaindex_routing.py \
  tests/test_langgraph_routing.py \
  tests/test_langgraph_routing_scenarios.py \
  tests/test_langgraph_routing_selection.py \
  tests/test_langgraph_routing_strategies.py
```

Recorded result: **61 passed**. The repository's test daemon requires Cargo and local Unix-socket access. It is separate from the provisioned daemon used by the CLI.

## Files

| File | Description |
|---|---|
| [`agent.py`](agent.py) | Existing OpenAI agent and mapped Omneum evaluation tool |
| [`run.py`](run.py) | Interactive basic-agent CLI |
| [`routing/workflow.py`](routing/workflow.py) | Native conditional workflow, retrieval, selection, and response |
| [`routing/state.py`](routing/state.py) | State passed between executors |
| [`routing/run.py`](routing/run.py) | All-scenario and individual-scenario CLI |
| [`routing/__init__.py`](routing/__init__.py) | Routing package |
| [`../../tests/test_microsoft_routing.py`](../../tests/test_microsoft_routing.py) | Microsoft routing and basic-tool regression tests |
| [`../enterprise/`](../enterprise/) | Shared retrieval fixtures, deployment, estimator, and reports |
| [`../langgraph/routing/`](../langgraph/routing/) | Shared policy, selection, scenarios, and additional retrieval |

## Requirements

- Python 3.13 for the verified locked commands
- uv 0.12.10
- Microsoft Agent Framework 1.11.0 (locked group)
- Omneum Python SDK, MCP stdio server, and provisioned local daemon
- `OPENAI_API_KEY`, an OpenAI model setting, and network access for the basic agent
- Cargo and local Unix-socket access for the isolated test daemon

Routing uses deterministic fixtures and responses; live retrieval and model-based routing are not demonstrated.

## Documentation

- [Microsoft Agent Framework](https://learn.microsoft.com/en-us/agent-framework/)
- [Executors](https://learn.microsoft.com/en-us/python/api/agent-framework-core/agent_framework.executor?view=agent-framework-python-latest)
- [Workflow Edges](https://learn.microsoft.com/en-us/agent-framework/concepts/workflows/edges)
- [Workflow Builder Source](https://github.com/microsoft/agent-framework/blob/main/python/packages/core/agent_framework/_workflows/_workflow_builder.py)
- [Workflow Context](https://learn.microsoft.com/en-us/python/api/agent-framework-core/agent_framework.workflowcontext?view=agent-framework-python-latest)
- [Omneum SDK](../../docs/sdk.md)
- [Installation](../../docs/guides/installation.md)
- [Enterprise Example](../enterprise/)
- [CrewAI Integration](../crewai/)
- [LangGraph Integration](../langgraph/)
- [LlamaIndex Integration](../llamaindex/)
