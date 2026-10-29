# LlamaIndex

LlamaIndex Workflows integration for [Omneum](https://github.com/cole-h06/omneum).

Omneum evaluates retrieved evidence through provenance-aware graph inference, selects passages using BM25 query relevance and incremental claim coverage, and assembles the selected text within a configured context budget.

This integration provides two LlamaIndex `Workflow` implementations:

- **Enterprise Workflow (`EnterpriseWorkflow`):** Evaluates retrieved enterprise observations, selects and assembles the original passages through `OmneumClient.prepare_context()`, and passes the prepared messages to an injected LlamaIndex LLM.
- **Conditional Routing (`RoutingWorkflow`):** Uses claim support, estimated independent support, and competing claim values to determine whether additional retrieval is required before context selection and generation.

Both workflows use LlamaIndex `@step` handlers and typed events. LlamaIndex dispatches events between workflow steps and invokes the configured LLM. Omneum's local MCP evaluator computes source–claim support, while its Python SDK selects and assembles the generation context.

## Installation

From the repository root:

```bash
uv sync --locked --python 3.13 --group llamaindex
```

Provision the local Omneum evaluator using the [installation guide](../../docs/guides/installation.md).

The examples use fixed enterprise evidence records from [`examples/enterprise/data/`](../enterprise/data/). Context inspection and routing scenarios do not require hosted LLM credentials. Generation requires an injected LlamaIndex `LLM` instance.

## Quick Start

Inspect the enterprise workflow without model generation:

```bash
uv run --locked --python 3.13 --group llamaindex \
  -m examples.llamaindex.run --inspect-context
```

Run all conditional routing scenarios:

```bash
uv run --locked --python 3.13 --group llamaindex \
  -m examples.llamaindex.routing.run --scenario all
```

Compare Omneum's context selection with retrieval-order packing:

```bash
uv run --locked --python 3.13 --group llamaindex \
  -m examples.llamaindex.run --compare --token-budget 400
```

## Enterprise Workflow

[`workflow.py`](workflow.py) defines `EnterpriseWorkflow` with typed `@step` handlers for retrieval, graph evaluation, context preparation, and LLM generation.

```python
from examples.context_preparation import PreparationOptions
from examples.llamaindex.workflow import EnterpriseWorkflow


async def answer(chat_model):
    workflow = EnterpriseWorkflow(
        timeout=60,
        chat_model=chat_model,
        preparation=PreparationOptions(token_budget=400),
    )

    handler = workflow.run()
    response = await handler

    generation = await handler.ctx.store.get("generation")
    return response, generation
```

`chat_model` is an injected LlamaIndex `LLM` instance. When `chat_model` is omitted, the workflow completes without invoking an LLM. The prepared generation payload remains available through `handler.ctx.store`.

### Workflow Execution

```text
StartEvent
   |
   v
 retrieve
   |
   v
RetrievalResultsEvent
   |
   v
 evaluate
   |
   v
ContextEvaluationEvent
   |
   v
prepare_context
   |
   v
PreparedContextEvent
   |
   v
 render
   |
   v
StopEvent
```

LlamaIndex dispatches events to `@step` handlers according to their annotated input types. Each handler returns an event consumed by the next step.

| Step | Input | Operation |
|---|---|---|
| `retrieve` | `StartEvent` | Collect enterprise observations and original retrieved chunks |
| `evaluate` | `RetrievalResultsEvent` | Map observations and call Omneum's `evaluate_mapped()` |
| `prepare_context` | `ContextEvaluationEvent` | Reuse the evaluation in `prepare_generation()` |
| `render` | `PreparedContextEvent` | Convert generation messages to `ChatMessage` objects and invoke the LLM |

The workflow's per-run `Context` store retains the `ContextEvaluation` and `GenerationInput`:

```python
await ctx.store.set("evaluation", event.result)
await ctx.store.set("generation", generation)
```

The `render` step converts the prepared messages into LlamaIndex's native message representation:

```python
messages = [
    ChatMessage(**message)
    for message in event.generation["messages"]
]

await ctx.store.set("messages", messages)

if self.chat_model is not None:
    response = await self.chat_model.achat(messages)
    return StopEvent(result=response.message.content)
```

The injected LLM receives the selected original passages through the prepared `ChatMessage` sequence.

See [`workflow.py`](workflow.py) and [`run.py`](run.py).

## Conditional Routing

[`routing/workflow.py`](routing/workflow.py) defines `RoutingWorkflow`. It evaluates accumulated observations, applies the shared `RoutingPolicy`, and maps each routing decision to the event consumed by the corresponding `@step` handler.

```python
from examples.context_preparation import PreparationOptions
from examples.llamaindex.routing.workflow import RoutingWorkflow

workflow = RoutingWorkflow(
    timeout=60,
    preparation=PreparationOptions(token_budget=400),
)

state = await workflow.run(scenario="resolve_conflicts")

print(state.routing_history)
print(state.answer)
```

### Routing Scenarios

| Scenario | Routing condition | Retrieval action |
|---|---|---|
| `diversify_sources` | Insufficient estimated independent support | Retrieve evidence from additional sources |
| `retrieve_support` | Insufficient support for required claims | Retrieve additional evidence and append its observations |
| `resolve_conflicts` | Insufficient separation between competing claim values | Retrieve evidence addressing the conflict |

Run the conflict-resolution scenario:

```bash
uv run --locked --python 3.13 --group llamaindex \
  -m examples.llamaindex.routing.run --scenario resolve_conflicts
```

### Event Routing

```text
StartEvent
   |
   v
EvidenceEvent
   |
   v
EvaluatedEvent
   |
   +-- RetrieveSupportEvent -----+
   |                             |
   +-- ResolveConflictsEvent ----+--> EvidenceEvent
   |                             |         |
   +-- DiversifySourcesEvent ----+         v
   |                                 EvaluatedEvent
   |
   +-- SelectContextEvent
   |         |
   |         v
   |    GenerateEvent
   |         |
   |         v
   |     StopEvent
   |
   +-- EscalateEvent --> StopEvent
```

`route_context()` calls the shared routing policy and maps its decision to a LlamaIndex event type:

```python
decision = assess_context(
    state.context_evaluation,
    retries=state.retry_count,
)

event_type = {
    "retrieve_support": RetrieveSupportEvent,
    "resolve_conflicts": ResolveConflictsEvent,
    "diversify_sources": DiversifySourcesEvent,
    "generate": SelectContextEvent,
    "escalate": EscalateEvent,
}[decision.route]

return emit(ctx, event_type(state=state))
```

Retrieval branches append observations not already present in `RoutingState` and emit another `EvidenceEvent`. The updated observations are evaluated before the next routing decision.

When the policy returns `generate`, `select_claims()` calls Omneum's context preparation through the shared SDK helper. `generate_answer()` passes the resulting `ChatMessage` sequence to the injected LLM.

The `escalate` branch terminates without model generation.

`RoutingState` retains accumulated observations, routing history, and generation results.

See [`routing/workflow.py`](routing/workflow.py) and [`routing/state.py`](routing/state.py).

## Omneum's Algorithm

Both workflows use [`context_preparation.py`](../context_preparation.py) to pass retrieved observations and chunks to `OmneumClient.prepare_context()`.

### Retrieved Chunks

Each retrieved passage retains its original text and identifiers linking it to Omneum's observations and claims.

| Field | Content |
|---|---|
| `chunk_id` | Retrieved passage identifier |
| `raw_text` | Original passage text |
| `source` | Associated Omneum source |
| `observation_ids` | Associated observation identifiers |
| `claim_ids` | Claims represented by the passage |

A passage may contain multiple claims, and multiple passages may reference the same claim.

The `claim_ids` mapping connects graph evaluation results to the retrieved passages considered during budget-constrained context selection.

### Graph Inference and Context Selection

Omneum's algorithm constructs a bipartite source–claim graph from structured observations. It iteratively computes source reliability and claim support, using estimated source dependencies to adjust evidence contributions during propagation.

The resulting claim scores contribute to chunk utility through each passage's `claim_ids` mapping. Selection incorporates BM25 query relevance and incremental claim coverage, adjusting candidate utility according to the claims already represented by selected passages.

`prepare_generation()` calls `OmneumClient.prepare_context()` with the retrieved chunks and optional existing `ContextEvaluation`:

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

The `evaluation` argument allows the SDK to reuse the `ContextEvaluation` computed by an earlier Workflow step.

The SDK selects passages within the configured context budget and returns their identifiers in `packed_chunk_ids` order.

### Context Assembly

Omneum assembles the selected original passages in rendering order. Passages excluded during selection are omitted from the generation messages.

The preparation output contains the selected identifiers and assembled context:

```python
prepared["packed_chunk_ids"]
prepared["context"]
```

Only structured observations and provenance metadata are passed to the MCP graph evaluator. The Python SDK retains `raw_text` for context assembly without sending the original passages to the evaluator.

### Generation Payload

`prepare_generation()` returns a `GenerationInput` containing the graph evaluation, assembled context, and generation messages.

| Field | Content |
|---|---|
| `generation["retrieved_chunks"]` | Retrieved candidate passages |
| `generation["evaluation"]` | Source–claim graph evaluation results |
| `generation["prepared_context"]` | Selected passage identifiers, assembled context, and selection results |
| `generation["packed_chunk_ids"]` | Selected passage identifiers in rendering order |
| `generation["messages"]` | Messages converted to LlamaIndex `ChatMessage` objects |
| `generation["query_diagnostics"]` | BM25 query relevance diagnostics |
| `generation["comparison"]` | Raw RAG comparison when enabled |
| `generation["telemetry"]` | Available SDK execution measurements |

The enterprise workflow stores `generation` in `handler.ctx.store`. The routing workflow retains it in `RoutingState.generation`.

## Evaluation Results

The enterprise workflow uses `ContextMapper` and `evaluate_mapped()`. The routing workflow evaluates accumulated SDK `Observation` objects through `evaluate_context()`.

The routing workflow calls `OmneumClient.evaluate_context()` over the local MCP stdio connection:

```python
with example_deployment() as (config, server):
    async with open_stdio_client(config, server) as client:
        evaluation = await client.evaluate_context(
            observations,
            estimator=estimator_config(),
        )
```

`ContextEvaluation` exposes the graph inference results:

| Field | Content |
|---|---|
| `source_reliability` | Relative source reliability scores |
| `claim_support` | Claim support scores and associated claim data |
| `pairwise_dependencies` | Estimated dependencies between sources |
| `evaluation_latency_ms` | Evaluation duration |
| `explanation` | Formatted evaluation report |

Inspect support for individual claims:

```python
for result in evaluation.claim_support:
    print(
        result.claim.attribute,
        result.claim.value,
        result.support,
        result.estimated_independent_support_count,
    )
```

`RoutingPolicy` applies its configured support thresholds to the current `ContextEvaluation`. `prepare_context()` reuses the evaluation to compute chunk utility and select passages.

## Context Budgets

Configure Omneum's context selection and assembly through `PreparationOptions`:

```python
from examples.context_preparation import PreparationOptions

options = PreparationOptions(
    token_budget=600,
    compare=False,
    include_telemetry=False,
    collect_telemetry=False,
)
```

`token_budget` limits the assembled evidence context, including chunk headers and separators.

The current budget counter measures Unicode word/punctuation units rather than provider-specific model tokens. Additional messages supplied to `LLM.achat()` contribute separately to the model's input-token usage.

A budget of `0` selects no evidence passages.

## Raw RAG Comparison

Use `--compare` to evaluate retrieval-order packing and Omneum's graph-informed selection against the same retrieved candidate pool and context budget:

```bash
uv run --locked --python 3.13 --group llamaindex \
  -m examples.llamaindex.run --compare --token-budget 400
```

| Configuration | Selection behavior |
|---|---|
| Raw RAG | Packs retrieved chunks in retrieval order until the budget is exhausted |
| Omneum | Selects chunks using graph-derived claim support, BM25 relevance, and incremental claim coverage |

The comparison reports selected chunk IDs in rendering order, budget consumption, claim coverage, and excluded chunks.

Graph evaluation diagnostics cover the complete retrieved observation set before passage selection.

Access the Raw RAG context programmatically:

```python
raw_context = generation["comparison"]["raw_rag"]["context"]
```

The comparison runs before LLM generation and does not require hosted model credentials.

## Inspection and Telemetry

Both CLI entry points support context inspection, structured JSON output, and SDK execution telemetry.

| Option | Behavior |
|---|---|
| `--token-budget N` | Set the assembled evidence budget |
| `--inspect-context` | Inspect the prepared generation input without invoking an LLM |
| `--compare` | Compare retrieval-order packing with Omneum's context selection |
| `--json` | Emit structured inspection output |
| `--include-context` | Include selected original passages and generation messages |
| `--include-telemetry` | Include available SDK execution measurements |
| `--collect-telemetry` | Enable SDK telemetry collection and execution logging |
| `--telemetry-format json\|human` | Select execution-log format |
| `--telemetry-log-file PATH` | Write execution logs to a file |
| `--scenario NAME` | Select a routing scenario |

### JSON Inspection

Inspect the enterprise workflow:

```bash
uv run --locked --python 3.13 --group llamaindex \
  -m examples.llamaindex.run --json --include-telemetry
```

Include the selected original passages:

```bash
uv run --locked --python 3.13 --group llamaindex \
  -m examples.llamaindex.run --json --include-context
```

JSON output contains retrieved and selected chunk IDs, rendering order, claim coverage, graph evaluation diagnostics, and preparation configuration.

### Execution Telemetry

Collect human-readable execution logs:

```bash
uv run --locked --python 3.13 --group llamaindex \
  -m examples.llamaindex.run \
  --inspect-context \
  --collect-telemetry \
  --telemetry-format human
```

Available SDK measurements include:

| Measurement | SDK field |
|---|---|
| End-to-end SDK latency | `sdk_end_to_end_latency_ms` |
| Graph evaluation latency | `graph_evaluation_latency_ms` |
| MCP round-trip latency | `mcp_roundtrip_latency_ms` |
| Chunk selection latency | `chunk_selection_latency_ms` |
| Context reconstruction latency | `context_reconstruction_latency_ms` |
| CPU time | `cpu_time_ms` |
| Peak memory | `peak_memory_bytes` |

`include_telemetry=True` returns available measurements in the generation payload.

`collect_telemetry=True` emits `omneum.execution` records through Python logging.

With local SQLite persistence configured, completed context-preparation executions are recorded in `execution_history` and linked to their evaluation runs:

```sql
SELECT *
FROM execution_history
ORDER BY created_at DESC
LIMIT 1;
```

SDK preparation timing excludes downstream LLM generation and Raw RAG comparison.

## Implementation

| File | Responsibility |
|---|---|
| [`workflow.py`](workflow.py) | Enterprise Workflow steps, typed events, evaluation, and generation |
| [`run.py`](run.py) | Enterprise CLI |
| [`routing/workflow.py`](routing/workflow.py) | Typed-event routing, retrieval, and generation |
| [`routing/state.py`](routing/state.py) | Routing state and evaluation results |
| [`routing/run.py`](routing/run.py) | Routing scenario CLI |
| [`../context_preparation.py`](../context_preparation.py) | Shared Omneum SDK context preparation |
| [`../context_output.py`](../context_output.py) | Context inspection, JSON output, and comparison |
| [`../langgraph/routing/`](../langgraph/routing/) | Shared routing policy and retrieval fixtures |
| [`../enterprise/`](../enterprise/) | Enterprise observations and estimator configuration |

## Documentation

- [LlamaIndex Workflows](https://developers.llamaindex.ai/python/llamaagents/workflows/)
- [LlamaIndex Workflow API](https://developers.llamaindex.ai/python/framework-api-reference/workflow/)
- [LlamaIndex Workflow Branches and Loops](https://developers.llamaindex.ai/python/llamaagents/workflows/branches_and_loops/)
- [Omneum SDK](../../docs/sdk.md)
- [Omneum Installation](../../docs/guides/installation.md)
- [Enterprise Example](../enterprise/)
- [LangGraph Integration](../langgraph/)