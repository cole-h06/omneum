# OpenAI Agents SDK

The enterprise `Agent` exposes an Omneum evaluation tool to OpenAI and prints the model's response. The separate routing example uses deterministic application control and SDK function tools to retrieve evidence, reevaluate it, and select context without OpenAI credentials.

## Installation

Run from the repository root with uv 0.12.10:

```bash
uv sync --locked --python 3.13 --group openai-agents
```

Use `~/.local/bin/uv` if another uv version is on `PATH`. Both CLIs require a provisioned local Omneum daemon; follow the [installation guide](../../docs/guides/installation.md).

## Quick Start: Enterprise Agent

```bash
export OPENAI_API_KEY="your-api-key"
uv run --locked --python 3.13 --group openai-agents -m examples.openai_agents.run
```

The unchanged [`run.py`](run.py) calls `Runner.run(agent, QUESTION)` and prints `result.final_output`. The model decides whether to invoke `evaluate_context` and generates the final response.

The enterprise CLI completed an actual OpenAI request on 2026-10-10 with the locked group and local daemon. Its stdout was:

```text
No. Production use is limited to **redacted customer-ticket content**; unredacted content is not approved.

Required settings for the hosted provider:

- **Retention:** 0 days
- **Processing region:** EU

Do not deploy unless those controls are technically enforced and verified.
```

## Quick Start: Conditional Routing

```bash
env -u OPENAI_API_KEY uv run --locked --python 3.13 --group openai-agents \
  -m examples.openai_agents.routing.run --scenario all
```

```bash
uv run --locked --python 3.13 --group openai-agents \
  -m examples.openai_agents.routing.run --scenario retrieve_support
```

| Scenario | Initial evidence | Retrieval strategy |
|---|---|---|
| `diversify_sources` | 17 enterprise observations | Independent compliance evidence for dependent attributes |
| `retrieve_support` | 11 observations, processing region absent | Evidence for missing or weak attributes |
| `resolve_conflicts` | Nine policy, runbook, and readiness observations | Independent policy-review evidence for competing claims |

`initial_observations` and `retrieve_additional_evidence` are imported from the shared [LangGraph routing package](../langgraph/routing/). Retrieval reads deterministic fixtures rather than live enterprise systems.

## Agent Configuration

The existing [`agent.py`](agent.py) registers this configuration:

```python
agent = Agent(
    name="Enterprise AI Assistant",
    instructions=(
        "Answer deployment-readiness questions using the "
        "evaluate_context tool. Base your response on the "
        "context evaluation results."
    ),
    tools=[evaluate_context],
)
```

The SDK resolves `model=None` using `OPENAI_DEFAULT_MODEL`; installed version 0.20.0 defaults to `gpt-5.6-luna`. The routing CLI never constructs a model or calls `Runner`.

## Native SDK Integration

The locked environment installs `openai-agents` **0.20.0**. Verification inspected `Agent`, `Runner.run`, `function_tool`, `FunctionTool.on_invoke_tool`, `RunContextWrapper`, `ToolContext.from_agent_context`, `handoff`, and `Agent.as_tool` signatures and implementation.

`Runner.run` executes an agent/model loop; handoffs transfer control inside that loop, and `Agent.as_tool` starts a nested runner. The deterministic example uses an application loop because those primitives do not provide a model-free conditional graph.

The SDK creates function schemas, validates JSON arguments, injects context, and executes the async evaluation and retrieval functions. Application code chooses the branch, retry count, context selection, and terminal response. This path does not execute handoffs or the runner's hooks, guardrails, approval handling, or model tracing.

The actual invocation helper in [`routing/workflow.py`](routing/workflow.py):

```python
async def invoke_tool(
    tool: FunctionTool, context: RunContextWrapper[RoutingState], **arguments,
) -> str:
    """Invoke the SDK JSON-validation path without entering a model runner."""
    payload = json.dumps(arguments)
    state = context.context
    tool_context = ToolContext.from_agent_context(
        context,
        tool_call_id=f"routing-{len(state.tool_history) + 1}",
        tool_name=tool.name,
        tool_arguments=payload,
    )
    result = await tool.on_invoke_tool(tool_context, payload)
    state.tool_history = (*state.tool_history, tool.name)
    return result
```

`failure_error_function=None` makes evaluation and retrieval exceptions propagate instead of returning model-visible error text. Failed calls do not enter `tool_history` or produce a successful application decision.

## Context Evaluation

The enterprise tool retrieves 17 observations from six fixture sources using `collect_observations`. Its `ContextMapper` preserves source identity, claim namespace/entity/attribute/value, observation IDs, timestamps, upstream and cited sources, parent observations, retrieval records, and seven dependency signals (`upstream`, `citation`, `assertion_lineage`, `ownership`, `temporal`, `graph`, `retrieval`).

The enterprise tool calls `client.evaluate_mapped(observations, mapper, estimator=estimator_config())` and returns `render_result(result)`. Routing already holds typed Omneum observations and submits them directly:

```python
@function_tool(failure_error_function=None)
async def evaluate_context(ctx: RunContextWrapper[RoutingState]) -> str:
    """Evaluate the accumulated observations through Omneum MCP stdio."""
    state = ctx.context
    with example_deployment() as (config, server):
        async with open_stdio_client(config, server) as client:
            state.context_evaluation = await client.evaluate_context(
                state.observations, estimator=estimator_config(),
            )
    return "Context evaluated."
```

Each retry evaluates the complete accumulated observation set over MCP stdio with the shared enterprise dependency estimator.

| Evaluation field | Observable result |
|---|---|
| `source_reliability` | Relative reliability for each source |
| `claim_support` | Support, supporting-source count, and estimated independent support per claim |
| `pairwise_dependencies` | Estimated dependency between source pairs |
| `evaluation_latency_ms` | Measured evaluation latency |
| `explanation` | Evaluation report used by enterprise formatting |

All evaluated claims remain available in `state.context_evaluation.claim_support`, including alternatives excluded from selected context. Neither example modifies BRAID, SDK contracts, or MCP protocols.

## Routing and Context Selection

```text
initial_observations -> evaluate_context -> assess_context
                                             |
                  retrieve_evidence <--------+ retrieval route
                         |                   |
                         +-> evaluate_context|
                                             +-> select_context -> deterministic answer
                                             +-> escalation
```

The application control loop is copied here from the implementation:

```python
async def run_routing(
    scenario: str, *, policy: RoutingPolicy = RoutingPolicy(),
) -> RoutingState:
    observations = initial_observations(scenario)
    state = RoutingState(scenario, len(observations), observations)
    context = RunContextWrapper(state)

    while True:
        await invoke_tool(evaluate_context, context)
        state.decision = assess_context(
            state.context_evaluation, retries=state.retry_count, policy=policy,
        )
        state.routing_history = (*state.routing_history, state.decision.route)
        if state.decision.route == "generate":
            state.selected_claims = select_context(state.context_evaluation, policy=policy)
            state.answer = "\n".join([
                "Application decision: EVALUATION COMPLETE",
                "Selected context:",
                *(f"{claim.attribute}: {claim.value}" for claim in state.selected_claims),
            ])
            return state
        if state.decision.route == "escalate":
            state.answer = (
                "Application decision: ESCALATE\n"
                "Evidence did not meet the routing policy."
            )
            return state
        await invoke_tool(retrieve_evidence, context, strategy=state.decision.route)
```

`assess_context` prioritizes missing attributes, unresolved conflicts, weak support, and dependent sources. Retrieval uses `decision.attributes`, the selected route, and `retry_count + 1`; observation IDs are deduplicated across existing and newly retrieved evidence.

`select_context` accepts the highest-support claim for each required attribute only when estimated independent support is at least 1.9 and its support is at least twice that of a positive-support competing claim. Weak claims and failing alternatives are excluded from `selected_claims`; accepted claims alone enter the deterministic response.

Insufficient evidence causes another retrieval or `ESCALATE` after the retry limit. Escalation returns no selected claims and performs no unsupported generation.

## Example Output

Recorded on 2026-10-10 with Python 3.13, uv 0.12.10, the locked group, the provisioned local daemon, and `OPENAI_API_KEY` removed. The all-scenario CLI exited 0; stdout follows with MCP startup logs on stderr omitted.

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

The four existing CLIs were executed with these commands, using `~/.local/bin/uv` 0.12.10 and `OPENAI_API_KEY` removed:

```bash
env -u OPENAI_API_KEY uv run --locked --python 3.13 --group langgraph -m examples.langgraph.routing.run --scenario all
env -u OPENAI_API_KEY uv run --locked --python 3.13 --group crewai -m examples.crewai.routing.run --scenario all
env -u OPENAI_API_KEY uv run --locked --python 3.13 --group llamaindex -m examples.llamaindex.routing.run --scenario all
env -u OPENAI_API_KEY uv run --locked --python 3.13 --group microsoft -m examples.microsoft.routing.run --scenario all
```

All five CLIs exited 0. Parsed stdout matched for observation counts, routing histories, retries, selected context, final decisions, and every printed claim-support and independent-support value across all three scenarios. The largest printed numerical difference was 0.0000 for support and 0.000 for independent support; CLI formatting rounds those fields to four and three decimal places. A separate execution compared the unrounded evaluation objects from all five integrations: the maximum absolute support difference was `0.0` and the maximum independent-support difference was `0.0` over all 12 framework/scenario comparisons.

| Scenario | Observation counts in all five CLIs | Routing history | Retries | Final decision |
|---|---|---|---:|---|
| `diversify_sources` | 17 → 18 | `diversify_sources → generate` | 1 | `EVALUATION COMPLETE` |
| `retrieve_support` | 11 → 14 | `retrieve_support → retrieve_support → generate` | 2 | `EVALUATION COMPLETE` |
| `resolve_conflicts` | 9 → 12 | `resolve_conflicts → generate` | 1 | `EVALUATION COMPLETE` |

LangGraph stores retrieval routes in state and appends the terminal route while printing; the other CLIs store the terminal route in their histories. CrewAI disables tracing and suppresses flow events in its CLI.

## Configuration

| Setting or component | Value or implementation |
|---|---|
| `OPENAI_API_KEY` | Enterprise model authentication; unused by routing |
| `OPENAI_DEFAULT_MODEL` | Enterprise SDK model override; default `gpt-5.6-luna` in 0.20.0 |
| `--scenario` | `all`, `diversify_sources`, `retrieve_support`, `resolve_conflicts` |
| `RoutingPolicy.min_independent_support` | 1.9 |
| `RoutingPolicy.min_support_ratio` | 2.0 |
| `RoutingPolicy.max_retries` | Two additional retrieval attempts |
| Policy override | `run_routing(scenario, policy=RoutingPolicy(...))` |
| Retrieval fixtures | Define attempts 1 and 2; larger retry budgets need additional fixtures |
| MCP transport | `open_stdio_client` with `example_deployment` |
| Deployment pin/configuration | `OmneumClientConfig.from_local_deployment()` |
| Estimator | Shared enterprise `estimator_config()` |
| State | `RoutingState`, including `tool_history` and `routing_history` |

## Tests

Run the new routing and enterprise regressions:

```bash
uv run --locked --python 3.13 --group openai-agents \
  -m pytest -q tests/test_openai_agents_routing.py tests/test_enterprise_example.py
```

Run all five routing integrations and shared enterprise regressions:

```bash
uv run --locked --python 3.13 \
  --group openai-agents --group langgraph --group crewai --group llamaindex --group microsoft \
  -m pytest -q \
  tests/test_openai_agents_routing.py tests/test_enterprise_example.py \
  tests/test_langgraph_routing.py tests/test_langgraph_routing_scenarios.py \
  tests/test_langgraph_routing_selection.py tests/test_langgraph_routing_strategies.py \
  tests/test_crewai_routing.py tests/test_llamaindex_routing.py tests/test_microsoft_routing.py
```

Recorded results: **20 passed in 17.65s** for the OpenAI and enterprise command; **78 passed in 71.24s** for the cross-integration command. No tests were skipped.

The new tests cover all scenarios, real SDK tool callbacks and JSON validation, real MCP reevaluation, policy decisions, targeted retrieval, deduplication, selected claims, conflicting and weak claim exclusion, retry exhaustion, zero-retry escalation, and CLI execution without OpenAI credentials. The enterprise regression compares the unchanged mapped evaluation tool against direct Omneum evaluation; the separate enterprise CLI run above validates actual OpenAI response generation.

## Files

| Path | Implementation |
|---|---|
| [`agent.py`](agent.py) | Preserved enterprise `Agent`, function tool, mapper, and MCP evaluation |
| [`run.py`](run.py) | Preserved OpenAI-powered entry point |
| [`routing/__init__.py`](routing/__init__.py) | Separate deterministic routing package |
| [`routing/state.py`](routing/state.py) | Observations, evaluation, decisions, histories, selected claims, answer |
| [`routing/workflow.py`](routing/workflow.py) | SDK function tools and application control loop |
| [`routing/run.py`](routing/run.py) | Scenario CLI and evaluation diagnostics |
| [`../../tests/test_openai_agents_routing.py`](../../tests/test_openai_agents_routing.py) | SDK tool, routing, CLI, and enterprise regression tests |
| [`../langgraph/routing/`](../langgraph/routing/) | Reused policy, selector, scenarios, and retrieval strategies |
| [`../enterprise/`](../enterprise/) | Shared fixtures, deployment, estimator, and report formatter |

## Requirements

- Python 3.13 for the verified locked commands.
- uv 0.12.10 and the locked `openai-agents` group (SDK 0.20.0).
- Omneum Python SDK, MCP stdio server, and a provisioned local daemon.
- OpenAI credentials and network access for the enterprise model request.
- Cargo and Unix-socket access for the isolated fixture daemon used by tests.

The routing example exercises fixture retrieval and deterministic responses; production retrieval adapters must supply evidence for the shared policy to evaluate.

## Documentation

- [OpenAI Agents SDK orchestration](https://developers.openai.com/api/docs/guides/agents/orchestration)
- [Python Agents SDK](https://openai.github.io/openai-agents-python/)
- [Function tools](https://openai.github.io/openai-agents-python/tools/)
- [Omneum SDK](../../docs/sdk.md)
- [Installation](../../docs/guides/installation.md)
- [Enterprise example](../enterprise/)
- [LangGraph integration](../langgraph/)
- [CrewAI integration](../crewai/)
- [LlamaIndex integration](../llamaindex/)
- [Microsoft integration](../microsoft/)
