# OpenAI Agents SDK

OpenAI Agents SDK integration for [Omneum](https://github.com/cole-h06/omneum).

Omneum evaluates retrieved evidence through provenance-aware graph inference, selects passages using BM25 query relevance and incremental claim coverage, and assembles the selected text within a configured context budget.

Provides two integration patterns:

| Pattern | OpenAI Agents SDK | Omneum integration |
|---|---|---|
| **Enterprise Agent** | `Agent`, `Runner.run()`, `@function_tool` | Prepares retrieved passages before model generation |
| **Conditional Routing** | `FunctionTool`, `RunContextWrapper` | Evaluates evidence, retrieves additional observations, and prepares context after routing |

Both patterns use the shared `prepare_generation()` entry point and Omneum's local MCP evaluator.

## Quick Start

Install the OpenAI Agents SDK dependency group from the repository root:

```bash
uv sync --locked --python 3.13 --group openai-agents
```

Provision the local Omneum evaluator using the [installation guide](../../docs/guides/installation.md).

**Inspect selected context without an OpenAI model:**

```bash
uv run --locked --python 3.13 --group openai-agents \
  -m examples.openai_agents.run --inspect-context
```

**Compare Omneum with Raw RAG:**

```bash
uv run --locked --python 3.13 --group openai-agents \
  -m examples.openai_agents.run --compare --token-budget 400
```

**Run the enterprise agent:**

```bash
export OPENAI_API_KEY="your-api-key"

uv run --locked --python 3.13 --group openai-agents \
  -m examples.openai_agents.run
```

**Run conditional routing without model generation:**

```bash
uv run --locked --python 3.13 --group openai-agents \
  -m examples.openai_agents.routing.run --scenario all
```

Context inspection, Raw RAG comparison, and deterministic routing do not require OpenAI credentials.

## How It Works

The integration uses two execution paths. Both produce context from original retrieved passages rather than passing only graph scores to the model.

```text
Enterprise Agent

  Enterprise observations
           |
           v
   prepare_generation()
           |
           +-- Graph evaluation
           +-- Chunk ranking and selection
           +-- Context assembly
           |
           v
     GenerationInput
           |
           v
       Runner.run()
           |
           v
      Model response


Conditional Routing

   Initial observations
           |
           v
     evaluate_context
           |
           v
      assess_context
           |
      +----+-----------------------+
      |                            |
      v                            v
Retrieve evidence               Generate
      |                            |
      v                            v
Reevaluate claims           prepare_context
      |                            |
      +----> assess_context        v
                              Runner.run()
                              (if configured)
```

The routing path can also terminate with `escalate` when the evidence fails the configured support requirements.

| Stage | Implementation | Behavior |
|---|---|---|
| Retrieval | Enterprise fixtures, `retrieve_evidence()` | Collects observations and original passages |
| Graph inference | `evaluate_context()` | Computes source reliability, claim support, and dependencies |
| Routing | `RoutingPolicy`, `assess_context()` | Selects retrieval, generation, or escalation |
| Chunk ranking | `OmneumClient.prepare_context()` | Scores chunks using query relevance and claim coverage |
| Context assembly | `prepare_generation()` | Returns selected original passages in generation messages |
| Generation | `Runner.run()` | Invokes the configured OpenAI agent |

## Enterprise Agent

[`agent.py`](agent.py) defines the `Agent`, its `evaluate_context` function tool, and `run_agent()`.

### Function Tool

The registered tool calls `prepare_generation()` and returns the selected passages:

```python
@function_tool(failure_error_function=None)
async def evaluate_context(question: str = QUESTION) -> str:
    generation = await prepare_generation(
        collect_observations(),
        question=question,
        estimator=estimator_config(),
    )

    return generation["messages"][1]["content"]
```

The tool is registered with the OpenAI Agents SDK:

```python
agent = Agent(
    name="Enterprise AI Assistant",
    instructions=(
        "Answer deployment-readiness questions using the "
        "evaluate_context tool with the user's question before answering. "
        "Use its retrieved passages as evidence, cite chunk IDs, and explain conflicts."
    ),
    tools=[evaluate_context],
)
```

`@function_tool` exposes the Python function to the agent. The tool returns prepared passage text, not a report containing only source reliability and claim support.

### Direct Context Preparation

`run_agent()` prepares context before invoking `Runner.run()`:

```python
generation = await prepare_generation(
    collect_observations(),
    question=question,
    estimator=estimator_config(),
    preparation=preparation,
)

if inspect_context:
    return generation, None

consumer = generation_agent or agent.clone(
    instructions=generation["messages"][0]["content"],
    tools=[],
)

result = await Runner.run(consumer, generation["messages"])

return generation, result.final_output
```

The default generation path uses `agent.clone(tools=[])` to pass prepared messages directly to the model without another evaluation tool call.

| `run_agent()` argument | Purpose |
|---|---|
| `question` | Query used for context preparation |
| `preparation` | Context budget and comparison settings |
| `generation_agent` | Optional injected OpenAI Agents SDK `Agent` |
| `inspect_context` | Return `GenerationInput` without calling a model |

`--inspect-context` returns the prepared generation input with no OpenAI request.

### Enterprise Evidence

The example loads 17 observations from six sources through five enterprise retrieval modules.

| Module | Evidence |
|---|---|
| [`documents.py`](../enterprise/agents/documents.py) | Current policy and stale runbook |
| [`research.py`](../enterprise/agents/research.py) | Readiness brief derived from the runbook |
| [`sql.py`](../enterprise/agents/sql.py) | Model registry |
| [`api.py`](../enterprise/agents/api.py) | Gateway configuration |
| [`search.py`](../enterprise/agents/search.py) | Vendor data controls |

The modules load local JSON fixtures, not live enterprise systems. The fixtures include competing claim values and evidence sharing upstream sources.

## Omneum's Algorithm

[`context_preparation.py`](../context_preparation.py) provides `prepare_generation()`, the shared entry point for graph evaluation, chunk selection, and context assembly.

```python
generation = await prepare_generation(
    observations,
    question=question,
    estimator=estimator_config(),
    chunks=chunks,
    evaluation=evaluation,
    preparation=PreparationOptions(token_budget=400),
)
```

When `evaluation` is supplied, the SDK reuses the existing `ContextEvaluation` instead of repeating graph inference.

### 1. Graph Inference

Omneum constructs a bipartite source–claim graph from structured observations.

Source nodes represent evidence producers. Claim nodes represent asserted entity–attribute–value relationships. Observation edges connect sources to the claims they support.

The algorithm iteratively computes source reliability and claim support. Estimated dependencies adjust contributions from sources sharing upstream evidence.

| Evaluation field | Content |
|---|---|
| `source_reliability` | Relative source reliability scores |
| `claim_support` | Claim support scores and estimated independent support |
| `pairwise_dependencies` | Estimated dependencies between sources |
| `evaluation_latency_ms` | Graph evaluation duration |
| `explanation` | Formatted evaluation report |

Two claim-level measurements serve different purposes:

| Measurement | Meaning |
|---|---|
| `support` | Graph-derived claim support score |
| `estimated_independent_support_count` | Estimated effective number of independent supporting sources |

Support scores are not probabilities. Competing claim values remain separate during evaluation.

### 2. Retrieved Chunks

`collect_chunks()` retains original passage text and identifiers linking each passage to graph-evaluated observations and claims.

| Field | Description |
|---|---|
| `chunk_id` | Retrieved passage identifier |
| `raw_text` | Original passage text |
| `source` | Source metadata |
| `observation_ids` | Associated observations |
| `claim_ids` | Claims represented by the passage |

Multiple chunks can reference the same claim.

The MCP evaluator receives structured observations and provenance metadata. Original `raw_text` remains in the Python SDK.

### 3. Chunk Selection

The SDK maps graph-derived claim scores to retrieved passages through `claim_ids`.

Chunk utility incorporates BM25 query relevance, claim support, and incremental claim coverage. The selection process favors passages that add useful evidence without repeatedly consuming the budget for the same claims.

| Input | Role in selection |
|---|---|
| Query | BM25 relevance |
| `claim_ids` | Maps claim support to chunks |
| Source dependencies | Adjusts graph-derived evidence support |
| Previously selected claims | Determines incremental coverage |
| Context budget | Limits selected passage content |

The selection strategy is `coverage_support_density`.

### 4. Context Assembly

`OmneumClient.prepare_context()` selects and orders chunks within the configured budget.

The SDK assembles the selected passages using their original `raw_text`. Unselected chunks remain in `retrieved_chunks` but are excluded from generation messages.

```python
prepared = generation["prepared_context"]

print(prepared["packed_chunk_ids"])
print(prepared["context"])
```

`packed_chunk_ids` records the final passage order. `context` contains the assembled text supplied to generation.

The context budget uses the SDK's Unicode word-and-punctuation accounting, including passage headers and separators. It does not represent an exact token count from the OpenAI model tokenizer.

### 5. Generation Input

`prepare_generation()` returns a `GenerationInput`.

| Field | Content |
|---|---|
| `retrieved_chunks` | Full retrieved candidate set |
| `evaluation` | Graph inference results |
| `prepared_context` | Selected chunks and assembled context |
| `messages` | Messages passed to `Runner.run()` |
| `query_diagnostics` | Query relevance diagnostics |
| `comparison` | Raw RAG comparison, when enabled |
| `telemetry` | SDK execution measurements, when collected |

The prepared messages contain the selected original passages. The full retrieved candidate set remains available separately for inspection.

## Conditional Routing

[`routing/workflow.py`](routing/workflow.py) uses the shared [`RoutingPolicy`](../langgraph/routing/policy.py) and `assess_context()` to select retrieval, generation, or escalation.

`run_routing()` controls retries and invokes OpenAI Agents SDK function tools directly. It does not require a model to choose each routing action.

### Routing Decisions

| Route | Operation |
|---|---|
| `retrieve_support` | Retrieve evidence for missing or weakly supported claims |
| `resolve_conflicts` | Retrieve evidence addressing competing claim values |
| `diversify_sources` | Retrieve evidence from additional independent sources |
| `generate` | Prepare selected passages for generation |
| `escalate` | Stop without generation |

The shared policy uses:

```python
RoutingPolicy(
    min_independent_support=1.9,
    min_support_ratio=2.0,
    max_retries=2,
)
```

| Parameter | Behavior |
|---|---|
| `min_independent_support` | Minimum effective independent support |
| `min_support_ratio` | Required separation between competing claim values |
| `max_retries` | Maximum additional retrieval attempts |

### Routing Execution

```text
initial_observations()
        |
        v
  evaluate_context
        |
        v
   assess_context
        |
        +-- retrieve_support --+
        |                      |
        +-- resolve_conflicts -+--> retrieve_evidence()
        |                      |            |
        +-- diversify_sources -+            v
        |                             evaluate_context
        |                                    |
        |                                    +--> assess_context
        |
        +-- generate --> prepare_context --> Runner.run()
        |
        +-- escalate --> terminal result
```

Each retrieval strategy adds fixture observations for the selected route. Observation IDs are deduplicated before reevaluation.

### Graph Evaluation Tool

The `evaluate_context` function tool evaluates accumulated observations over MCP stdio:

```python
@function_tool(failure_error_function=None)
async def evaluate_context(
    ctx: RunContextWrapper[RoutingState],
) -> str:
    state = ctx.context
    state.retrieved_chunks = collect_chunks(state.observations)

    with example_deployment() as (config, server):
        async with open_stdio_client(config, server) as client:
            state.context_evaluation = await client.evaluate_context(
                state.observations,
                estimator=estimator_config(),
            )

    return "Context evaluated."
```

`RoutingState` retains the observations, retrieved chunks, evaluation, routing history, and generation payload.

After evaluation, `assess_context()` reads the latest `ContextEvaluation` to determine the next action.

### Context Preparation Tool

When the policy returns `generate`, the `prepare_context` function tool calls `prepare_generation()`:

```python
@function_tool(failure_error_function=None)
async def prepare_context(
    ctx: RunContextWrapper[RoutingState],
) -> str:
    state = ctx.context

    state.generation = await prepare_generation(
        state.observations,
        question=state.question,
        estimator=estimator_config(),
        chunks=state.retrieved_chunks,
        evaluation=state.context_evaluation,
        preparation=state.preparation,
    )

    return state.generation["messages"][1]["content"]
```

The `evaluation` argument reuses the graph scores computed by the routing workflow. The `chunks` argument supplies the original passages for ranking and assembly.

This separates the two operations:

| Operation | Function | Output |
|---|---|---|
| Evidence evaluation | `evaluate_context()` | `ContextEvaluation` |
| Context preparation | `prepare_generation()` | Selected chunks, assembled text, generation messages |

### Generation

When a generation agent is provided, the workflow passes prepared messages to `Runner.run()`:

```python
if generation_agent is not None:
    result = await Runner.run(
        generation_agent,
        state.generation["messages"],
        context=state,
    )
    state.answer = result.final_output
```

Without a generation agent, the CLI returns the selected context directly.

Escalation skips context preparation and generation.

### Direct Function-Tool Execution

`invoke_tool()` calls registered OpenAI Agents SDK function tools without starting a model run:

```python
async def invoke_tool(
    tool: FunctionTool,
    context: RunContextWrapper[RoutingState],
    **arguments,
) -> str:
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

`FunctionTool.on_invoke_tool()` executes the registered callback using the serialized arguments and tool context.

`run_routing()` controls the execution order and retry limits. `failure_error_function=None` allows tool exceptions to propagate to the application.

### Routing Scenarios

Run all scenarios:

```bash
uv run --locked --python 3.13 --group openai-agents \
  -m examples.openai_agents.routing.run --scenario all
```

Run conflict resolution:

```bash
uv run --locked --python 3.13 --group openai-agents \
  -m examples.openai_agents.routing.run \
  --scenario resolve_conflicts \
  --token-budget 400
```

| Scenario | Initial evidence | Retrieval action |
|---|---|---|
| `diversify_sources` | 17 observations | Add an independent compliance source |
| `retrieve_support` | 11 observations | Retrieve missing or weak processing-region evidence |
| `resolve_conflicts` | 9 observations | Add independent policy-review evidence |

Scenario definitions and retrieval strategies are shared with [`../langgraph/routing/`](../langgraph/routing/).

## Context Inspection

Both CLIs use the shared [`context_output.py`](../context_output.py) utilities.

| Option | Behavior |
|---|---|
| `--token-budget N` | Set the context budget |
| `--inspect-context` | Print prepared context diagnostics without generation |
| `--compare` | Compare Raw RAG and Omneum selection |
| `--json` | Emit structured inspection output |
| `--include-context` | Include selected original passages in JSON |
| `--include-telemetry` | Include SDK execution measurements |
| `--collect-telemetry` | Emit execution logs |
| `--telemetry-format json\|human` | Select log format |
| `--telemetry-log-file PATH` | Write logs to a file |
| `--scenario NAME` | Select a routing scenario |

### Raw RAG Comparison

```bash
uv run --locked --python 3.13 --group openai-agents \
  -m examples.openai_agents.run --compare --token-budget 400
```

Both configurations use the same retrieved candidates and context budget.

| | Raw RAG | Omneum |
|---|---|---|
| Candidate pool | Retrieved chunks | Same retrieved chunks |
| Selection | Retrieval order | Graph support, BM25 relevance, incremental claim coverage |
| Context budget | Same limit | Same limit |
| Original passage text | Preserved | Preserved |
| Output | Packed context | Packed context |

The comparison reports selection order, budget consumption, claim coverage, and excluded chunks.

Graph evaluation diagnostics describe the full retrieved evidence set, not only the selected passages.

### JSON Output

```bash
uv run --locked --python 3.13 --group openai-agents \
  -m examples.openai_agents.run --json --include-context
```

JSON inspection includes retrieved and selected chunk IDs, selection order, claim coverage, and preparation diagnostics.

`--include-context` adds selected original passage text and generation messages.

### Telemetry

```bash
uv run --locked --python 3.13 --group openai-agents \
  -m examples.openai_agents.run \
  --inspect-context \
  --collect-telemetry \
  --telemetry-format human
```

The SDK exposes these measurements when available:

| Field | Measurement |
|---|---|
| `sdk_end_to_end_latency_ms` | SDK execution duration |
| `graph_evaluation_latency_ms` | Graph inference duration |
| `mcp_roundtrip_latency_ms` | MCP request and response duration |
| `chunk_selection_latency_ms` | Chunk selection duration |
| `context_reconstruction_latency_ms` | Context assembly duration |
| `cpu_time_ms` | CPU time |
| `peak_memory_bytes` | Peak memory usage |

`include_telemetry=True` includes measurements in the returned payload. `collect_telemetry=True` emits execution logs through Python logging.

These measurements exclude downstream OpenAI model generation.

## Configuration

| Component | Implementation |
|---|---|
| Agent execution | `Agent`, `Runner.run()` |
| Function tools | `@function_tool`, `FunctionTool.on_invoke_tool()` |
| Tool context | `RunContextWrapper`, `ToolContext` |
| Routing | `RoutingPolicy`, `RoutingState`, `assess_context()` |
| Context preparation | `prepare_generation()` |
| Chunk selection | `OmneumClient.prepare_context()` |
| MCP transport | `open_stdio_client()` |
| Local deployment | `example_deployment()` |
| Dependency estimator | `estimator_config()` |
| Query relevance | BM25 |
| Selection strategy | `coverage_support_density` |
| Model credentials | `OPENAI_API_KEY` |

`PreparationOptions` configures the context budget, comparison, and telemetry settings.

`run_routing(scenario, policy=RoutingPolicy(...))` accepts an overridden routing policy.

## Implementation

| File | Responsibility |
|---|---|
| [`agent.py`](agent.py) | Enterprise agent, function tool, and generation workflow |
| [`run.py`](run.py) | Enterprise CLI |
| [`routing/workflow.py`](routing/workflow.py) | Routing tools, retrieval, reevaluation, and context preparation |
| [`routing/state.py`](routing/state.py) | Routing state and generation payload |
| [`routing/run.py`](routing/run.py) | Routing CLI |
| [`../context_preparation.py`](../context_preparation.py) | Shared graph evaluation and context preparation |
| [`../context_output.py`](../context_output.py) | Context inspection, comparison, and telemetry |
| [`../langgraph/routing/`](../langgraph/routing/) | Shared routing policy, scenarios, and retrieval fixtures |
| [`../enterprise/`](../enterprise/) | Enterprise observations, deployment, and estimator configuration |

## Documentation

- [OpenAI Agents SDK](https://openai.github.io/openai-agents-python/)
- [Running Agents](https://openai.github.io/openai-agents-python/running_agents/)
- [Function Tools](https://openai.github.io/openai-agents-python/tools/)
- [Omneum SDK](../../docs/sdk.md)
- [Installation](../../docs/guides/installation.md)
- [Enterprise Example](../enterprise/)
- [LangGraph Integration](../langgraph/)
- [CrewAI Integration](../crewai/)
- [LlamaIndex Integration](../llamaindex/)
- [Microsoft Agent Framework Integration](../microsoft/)