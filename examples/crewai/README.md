# CrewAI

CrewAI Flows integration for [Omneum](https://github.com/cole-h06/omneum).

Omneum evaluates retrieved evidence through provenance-aware graph inference, selects passages using BM25 query relevance and incremental claim coverage, and assembles the selected text into a budget-constrained model context.

This integration provides two CrewAI `Flow` implementations:

- **Enterprise Flow (`EnterpriseFlow`)** — Retrieves enterprise evidence through parallel Flow entry points, evaluates it with Omneum, assembles the selected original passages, and executes a CrewAI `Task` with an injected `Agent`.
- **Conditional Routing (`RoutingFlow`)** — Uses claim support, estimated independent support, and competing claim values to determine whether additional retrieval is required before context reconstruction and generation.

CrewAI controls Flow execution through `@start`, `@listen`, and `@router`. Omneum's Python SDK performs evidence evaluation and context reconstruction through the local MCP evaluator.

The integration invokes Omneum from Flow methods rather than exposing its MCP tools directly to the generation agent.

## Installation

From the repository root:

```bash
uv sync --locked --python 3.13 --group crewai
```

Provision the local Omneum evaluator using the [installation guide](../../docs/guides/installation.md).

The examples use enterprise evidence fixtures. Context inspection and routing scenarios run without hosted model credentials. Generation requires an injected CrewAI `Agent` with a configured model.

## Quick Start

Inspect the enterprise flow without model generation:

```bash
uv run --locked --python 3.13 --group crewai \
  -m examples.crewai.run --inspect-context
```

Run all conditional routing scenarios:

```bash
uv run --locked --python 3.13 --group crewai \
  -m examples.crewai.routing.run --scenario all
```

Run the conflict-resolution scenario:

```bash
uv run --locked --python 3.13 --group crewai \
  -m examples.crewai.routing.run --scenario resolve_conflicts
```

Compare Omneum's context reconstruction with retrieval-order packing:

```bash
uv run --locked --python 3.13 --group crewai \
  -m examples.crewai.run --compare --token-budget 400
```

## Enterprise Flow

[`flow.py`](flow.py) defines `EnterpriseFlow`, a CrewAI `Flow[WorkflowState]` with five retrieval entry points.

| Method | Retrieved evidence |
|---|---|
| `retrieve_documents()` | Internal documents |
| `retrieve_research()` | Research documents |
| `retrieve_sql()` | Database records |
| `retrieve_api()` | API responses |
| `retrieve_search()` | Search results |

Each retrieval method uses `@start()`. CrewAI schedules the eligible entry points when the Flow begins.

The `merge_observations` listener uses `and_()` to wait for all five retrieval methods to complete before evaluating their combined evidence.

```text
@start()
   |
   +-- retrieve_documents --+
   +-- retrieve_research ---+
   +-- retrieve_sql --------+ 
   +-- retrieve_api --------+--> merge_observations
   +-- retrieve_search -----+            |
                                        v
                                 evaluate_context
                                        |
                                        v
                                  prepare_context
                                        |
                                        v
                                   render_answer
```

The remaining stages execute through `@listen()` dependencies.

[`state.py`](state.py) defines the Pydantic `WorkflowState`, which retains retrieved observations, original chunks, graph evaluation results, reconstructed context, and generation output.

### Executing the Flow

Create `EnterpriseFlow` with an injected CrewAI `Agent`:

```python
from examples.context_preparation import PreparationOptions
from examples.crewai.flow import EnterpriseFlow


async def answer(agent):
    flow = EnterpriseFlow(
        generation_agent=agent,
        preparation=PreparationOptions(token_budget=400),
        tracing=False,
        suppress_flow_events=True,
    )

    await flow.kickoff_async()

    return flow.state.answer, flow.state.generation_task
```

`kickoff_async()` executes the Flow's decorated methods. The resulting state remains accessible through `flow.state`.

`generation_agent` is a CrewAI `Agent`, not a Crew or a Flow.

### Generation Task

After context reconstruction, `render_answer()` creates a native CrewAI `Task`:

```python
self.state.generation_task = Task(
    agent=self.generation_agent,
    description="\n\n".join(
        message["content"]
        for message in self.state.generation["messages"]
    ),
    expected_output=(
        "Answer the question with chunk citations "
        "and explain conflicting evidence."
    ),
)
```

The task description contains the question and Omneum's reconstructed evidence context.

This example passes evidence through `Task.description`. It does not use CrewAI's `Task.context` parameter, which references outputs from other CrewAI tasks.

When an agent is supplied, `render_answer()` executes the task:

```python
output = await asyncio.wrap_future(
    self.state.generation_task.execute_async()
)

self.state.answer = output.raw
```

`Task.execute_async()` returns a future that the Flow awaits using `asyncio.wrap_future()`. The resulting `TaskOutput.raw` is stored in `WorkflowState.answer`.

Without an injected agent, the Flow retains the prepared task description for inspection rather than invoking an LLM.

## Omneum's Algorithm

Both Flows use the shared [`context_preparation.py`](../context_preparation.py) integration to pass retrieved evidence through Omneum.

### Retrieved Evidence

Each retrieved passage is represented by a `RetrievedChunk` containing its original text and links to the observations and claims evaluated by Omneum.

| Field | Content |
|---|---|
| `chunk_id` | Retrieved passage identifier |
| `raw_text` | Original passage text |
| `source` | Source metadata |
| `observation_ids` | Associated Omneum observations |
| `claim_ids` | Claims represented by the passage |

A chunk may contain multiple claims, and the same claim may appear in multiple chunks.

`claim_ids` connects claim-level evaluation results to the original passages considered during context selection.

### Graph Inference

Omneum's algorithm operates on a bipartite source–claim graph constructed from structured observations.

It iteratively computes source reliability and claim support, adjusting evidence contributions using estimated source dependencies.

This allows the evaluation to distinguish repeated assertions from additional independent support. The resulting claim support scores contribute to chunk utility during context reconstruction.

The enterprise Flow uses `ContextMapper` and `evaluate_mapped()`:

```python
with example_deployment() as (config, server):
    async with open_stdio_client(config, server) as client:
        result = await client.evaluate_mapped(
            self.state.observations,
            mapper,
            estimator=estimator_config(),
        )
```

The result is stored in:

```python
self.state.context_evaluation
```

The routing Flow evaluates SDK `Observation` objects directly through `evaluate_context()`.

The MCP evaluator receives structured observations and provenance metadata. It does not require the original retrieved passage text.

### Context Selection

After graph evaluation, the enterprise Flow passes the existing `ContextEvaluation` to `prepare_generation()`:

```python
self.state.generation = await prepare_generation(
    self.state.observations,
    question=self.state.question,
    estimator=estimator_config(),
    chunks=self.state.retrieved_chunks,
    evaluation=self.state.context_evaluation,
    preparation=self.state.preparation,
)
```

`prepare_generation()` delegates context preparation to `OmneumClient.prepare_context()`.

The SDK derives chunk utility from graph-evaluated claim support and query relevance. Selection also accounts for incremental claim coverage: a candidate's contribution depends on which claims are already represented in the selected context.

This reduces the value of repeated evidence while allowing passages covering additional relevant claims to compete for the remaining budget.

The existing `ContextEvaluation` is reused during preparation, avoiding another graph evaluation of unchanged evidence.

### Context Assembly

The prepared context exposes the selected chunk identifiers and reconstructed text:

```python
prepared = self.state.generation["prepared_context"]

prepared["packed_chunk_ids"]
prepared["context"]
```

`packed_chunk_ids` specifies the selected passages in rendering order.

The SDK assembles the selected passages in rendering order using the retrieved chunks. Unselected passages are excluded from the generation context.

The resulting generation messages are available through:

```python
self.state.generation["messages"]
```

`render_answer()` joins those message contents into the CrewAI task description.

The complete retrieved candidate set remains available separately through `generation["retrieved_chunks"]`.

### Generation Payload

`prepare_generation()` returns a `GenerationInput` containing the evaluation and reconstruction results.

| Field | Content |
|---|---|
| `generation["retrieved_chunks"]` | Original retrieved candidates |
| `generation["evaluation"]` | Graph evaluation results |
| `generation["prepared_context"]` | Selected chunks and reconstructed context |
| `generation["messages"]` | Messages used to construct the CrewAI task description |
| `generation["query_diagnostics"]` | Query relevance diagnostics |
| `generation["comparison"]` | Raw RAG comparison when enabled |
| `generation["telemetry"]` | Available SDK execution measurements |

The reconstructed context contains original selected passages, not a serialized report of source reliability or claim support scores.

## Conditional Routing

[`routing/flow.py`](routing/flow.py) defines `RoutingFlow`, a CrewAI `Flow[RoutingState]`.

The Flow evaluates accumulated observations and uses the shared `assess_context()` policy to decide whether to retrieve more evidence or proceed to generation.

### Routing Policy

`route_context()` uses CrewAI's `@router` decorator:

```python
@router(evaluate_context)
def route_context(self):
    decision = assess_context(
        self.state.context_evaluation,
        retries=self.state.retry_count,
    )

    self.state.decision = decision
    self.state.routing_history = (
        *self.state.routing_history,
        decision.route,
    )

    return decision.route
```

The router returns a string label. CrewAI dispatches that label to matching `@listen()` branches.

`assess_context()` applies the configured routing thresholds to Omneum's evaluation results. CrewAI's `@router` dispatches the resulting branch.

### Routing Decisions

| Route | Operation |
|---|---|
| `retrieve_support` | Retrieve additional evidence for insufficiently supported claims |
| `resolve_conflicts` | Retrieve evidence addressing competing claim values |
| `diversify_sources` | Retrieve evidence from additional independent sources |
| `generate` | Reconstruct context and execute the generation task |
| `escalate` | Terminate without model generation |

The included scenarios exercise three retrieval conditions:

| Scenario | Condition |
|---|---|
| `retrieve_support` | Insufficient support for required claims |
| `resolve_conflicts` | Competing claim values require further resolution |
| `diversify_sources` | Insufficient estimated independent support |

### Flow Execution

```text
load_evidence
     |
     v
evaluate_context
     |
     v
route_context (@router)
     |
     +-- retrieve_support -----+
     +-- resolve_conflicts ----+--> reevaluate
     +-- diversify_sources ---+         |
     |                                  v
     |                            evidence_added
     |                                  |
     |                                  v
     |                            evaluate_context
     |
     +-- generate
     |      |
     |      v
     |  select_claims
     |      |
     |      v
     |  generate_answer
     |
     +-- escalate
            |
            v
      escalate_answer
```

Each retrieval branch appends observations with previously unseen observation IDs.

The Flow increments the retry count and reevaluates the updated evidence before applying the routing policy again.

When the policy returns `generate`, `select_claims()` records claim-selection diagnostics and calls `prepare_generation()` with the accumulated evidence and existing evaluation.

`generate_answer()` executes the resulting CrewAI `Task` when an agent is configured.

An `escalate` decision returns an application-level escalation result without invoking the generation agent.

### Executing a Routing Flow

```python
from examples.context_preparation import PreparationOptions
from examples.crewai.routing.flow import RoutingFlow


async def run_routing(agent):
    flow = RoutingFlow(
        generation_agent=agent,
        preparation=PreparationOptions(token_budget=400),
        tracing=False,
        suppress_flow_events=True,
    )

    await flow.kickoff_async(
        inputs={"scenario": "resolve_conflicts"}
    )

    return flow.state.answer, flow.state.routing_history
```

[`routing/state.py`](routing/state.py) retains the observations, evaluation result, current decision, retry count, routing history, and generation payload.

### Routing and Context Selection

`RoutingPolicy` decides whether the accumulated evidence meets the application's support requirements.

Omneum's context reconstruction determines which passages from that evidence enter the generation task.

Additional retrieval expands the candidate evidence set. It does not automatically increase the amount of text passed to the CrewAI agent.

The final task description contains only the passages selected under the configured context budget.

## Context Budgets

Configure Omneum through `PreparationOptions`:

```python
from examples.context_preparation import PreparationOptions

options = PreparationOptions(
    token_budget=600,
    compare=False,
    include_telemetry=False,
    collect_telemetry=False,
)
```

| Parameter | Default | Behavior |
|---|---|---|
| `token_budget` | `600` | Maximum reconstructed evidence budget |
| `compare` | `False` | Include Raw RAG comparison |
| `include_telemetry` | `False` | Return SDK execution measurements |
| `collect_telemetry` | `False` | Emit SDK execution log records |

The current SDK budget counter uses Unicode word/punctuation units rather than a model-provider tokenizer. Reconstructed chunk headers and separators count toward the budget.

The budget applies to Omneum's evidence context, not the complete CrewAI prompt.

The CrewAI `Task` description may include additional instructions, while the `Agent` configuration and framework-generated prompt content contribute separately to model input.

A budget of `0` selects no evidence passages.

## Raw RAG Comparison

Use `--compare` to evaluate retrieval-order packing and Omneum's context reconstruction against the same retrieved candidate pool and budget:

```bash
uv run --locked --python 3.13 --group crewai \
  -m examples.crewai.run --compare --token-budget 400
```

| Configuration | Selection behavior |
|---|---|
| Raw RAG | Packs retrieved chunks in retrieval order using `reconstruct_context(strategy="retrieval")` |
| Omneum | Selects chunks using graph-derived claim support, query relevance, and incremental claim coverage |

Both configurations operate on the same original retrieved passages.

The comparison reports selected chunk IDs, reconstruction order, budget consumption, covered claims, and excluded chunks.

Graph evaluation diagnostics describe the complete evidence set. Competing claim values remain distinct in the evaluation and coverage results.

Access the Raw RAG context programmatically:

```python
raw_context = generation["comparison"]["raw_rag"]["context"]
```

The comparison runs before CrewAI generation and does not require hosted LLM credentials.

## Inspection and Telemetry

Both CLI entry points use the shared `run_cli()` interface.

| Option | Behavior |
|---|---|
| `--token-budget N` | Set the reconstructed evidence budget |
| `--inspect-context` | Inspect prepared generation input |
| `--compare` | Compare Raw RAG and Omneum context selection |
| `--json` | Emit structured inspection output |
| `--include-context` | Include original passages and generation messages |
| `--include-telemetry` | Include available SDK execution measurements |
| `--collect-telemetry` | Emit SDK execution logs |
| `--telemetry-format json\|human` | Select log formatting |
| `--telemetry-log-file PATH` | Write execution logs to a file |
| `--scenario NAME` | Select routing scenarios |

### Context Inspection

```bash
uv run --locked --python 3.13 --group crewai \
  -m examples.crewai.run --inspect-context
```

### JSON Output

Export evaluation and reconstruction diagnostics:

```bash
uv run --locked --python 3.13 --group crewai \
  -m examples.crewai.run --json --include-telemetry
```

Include original selected passages:

```bash
uv run --locked --python 3.13 --group crewai \
  -m examples.crewai.run --json --include-context
```

Inspect all routing scenarios:

```bash
uv run --locked --python 3.13 --group crewai \
  -m examples.crewai.routing.run \
  --scenario all \
  --json
```

JSON inspection includes retrieved, selected, and excluded chunk IDs; reconstruction order; claim coverage; evaluation diagnostics; and evaluation-run identity.

Original passage text and generation messages are included when `--include-context` is enabled.

### Execution Telemetry

Collect human-readable SDK execution logs:

```bash
uv run --locked --python 3.13 --group crewai \
  -m examples.crewai.run \
  --inspect-context \
  --collect-telemetry \
  --telemetry-format human
```

Available measurements include:

| Measurement | SDK field |
|---|---|
| End-to-end SDK latency | `sdk_end_to_end_latency_ms` |
| Graph evaluation latency | `graph_evaluation_latency_ms` |
| MCP round-trip latency | `mcp_roundtrip_latency_ms` |
| Chunk selection latency | `chunk_selection_latency_ms` |
| Context reconstruction latency | `context_reconstruction_latency_ms` |
| CPU time | `cpu_time_ms` |
| Peak memory | `peak_memory_bytes` |

`include_telemetry=True` returns available measurements in the SDK payload.

`collect_telemetry=True` emits `omneum.execution` records through Python logging.

With default SQLite persistence, completed context-preparation executions are recorded in `execution_history` and linked to their evaluation runs:

```sql
SELECT *
FROM execution_history
ORDER BY created_at DESC
LIMIT 1;
```

SDK preparation timing excludes CrewAI model generation and Raw RAG comparison.

## Implementation

| File | Responsibility |
|---|---|
| [`flow.py`](flow.py) | Enterprise Flow entry points, listeners, evaluation, reconstruction, and generation |
| [`state.py`](state.py) | Enterprise Pydantic Flow state |
| [`run.py`](run.py) | Enterprise CLI |
| [`routing/flow.py`](routing/flow.py) | Conditional routing, retrieval, and generation |
| [`routing/state.py`](routing/state.py) | Routing state and diagnostics |
| [`routing/run.py`](routing/run.py) | Routing CLI |
| [`../context_preparation.py`](../context_preparation.py) | Shared Omneum SDK context preparation |
| [`../context_output.py`](../context_output.py) | CLI inspection, JSON output, and comparison |
| [`../langgraph/routing/`](../langgraph/routing/) | Shared routing policy and retrieval strategies |
| [`../enterprise/`](../enterprise/) | Enterprise observations and estimator configuration |

## Requirements

- Python 3.13
- Repository-locked `crewai` dependency group
- Omneum Python SDK
- Provisioned local Omneum MCP service

The fixture-backed examples use local CPU execution with BM25 query relevance.

Injected CrewAI agents may require additional model credentials and configuration.

## Documentation

- [CrewAI Flows](https://docs.crewai.com/en/concepts/flows)
- [CrewAI Agents](https://docs.crewai.com/en/concepts/agents)
- [CrewAI Tasks](https://docs.crewai.com/en/concepts/tasks)
- [Omneum SDK](../../docs/sdk.md)
- [Omneum Installation](../../docs/guides/installation.md)
- [Enterprise Example](../enterprise/)
- [LangGraph Integration](../langgraph/)
- [LlamaIndex Integration](../llamaindex/)