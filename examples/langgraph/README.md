
# LangGraph

LangGraph integration for [Omneum](https://github.com/cole-h06/omneum).

Omneum evaluates retrieved evidence through provenance-aware source–claim graph inference, selects passages using BM25 query relevance and incremental claim coverage, and assembles the selected text within a configured context budget.

This integration provides two LangGraph workflows:

- **Enterprise retrieval graph:** Runs five retrieval nodes in parallel, evaluates the combined observations with Omneum, selects and assembles the original passages, and passes the prepared messages to an injected LangChain chat model.
- **Conditional routing:** Uses `RoutingPolicy` to request additional retrieval when claim support, estimated independent support, or competing claim values fail the configured thresholds.

Both workflows use LangGraph's `StateGraph` API. LangGraph schedules nodes and combines parallel state updates through configured reducers. Omneum's Python SDK prepares the generation context using its local MCP graph evaluator.

## Installation

From the repository root:

```bash
uv sync --locked --group langgraph
```

Provision the local Omneum evaluator using the [installation guide](../../docs/guides/installation.md).

## Quick Start

Run the enterprise retrieval graph:

```bash
uv run --locked --group langgraph \
  -m examples.langgraph.run
```

Inspect the prepared context without invoking a model:

```bash
uv run --locked --group langgraph \
  -m examples.langgraph.run --inspect-context
```

Run the conditional routing examples:

```bash
uv run --locked --group langgraph \
  -m examples.langgraph.routing.run
```

Run a specific routing scenario:

```bash
uv run --locked --group langgraph \
  -m examples.langgraph.routing.run \
  --scenario resolve_conflicts
```

Compare Omneum with retrieval-order context packing:

```bash
uv run --locked --group langgraph \
  -m examples.langgraph.run --compare --token-budget 400
```

## Enterprise Retrieval Graph

[`graph.py`](graph.py) defines `build_graph()`, which constructs a LangGraph `StateGraph` and compiles it into an executable graph.

Five retrieval nodes run in parallel:

| Node | Retrieved evidence |
|---|---|
| `retrieve_documents` | Internal documents |
| `retrieve_research` | Research documents |
| `retrieve_sql` | Database records |
| `retrieve_api` | API responses |
| `retrieve_search` | Search results |

```text
START
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
                                       |
                                       v
                                      END
```

The retrieval nodes write their results to shared graph state. [`state.py`](state.py) defines the state schema and reducers used to combine updates from parallel branches.

`merge_observations` collects the retrieved observations before `evaluate_context` invokes Omneum's graph evaluator. `prepare_context` reuses the resulting `ContextEvaluation` to select passages and assemble the generation context.

[`nodes.py`](nodes.py) contains the node implementations.

### Generation

`render_answer` receives the prepared generation messages and invokes an injected LangChain `BaseChatModel` through `ainvoke()`.

Without an injected model, the graph retains the prepared context for inspection.

`build_graph()` returns the compiled graph, which supports LangGraph's standard invocation interface.

## Omneum's Algorithm

The enterprise graph uses the shared [`context_preparation.py`](../context_preparation.py) helper to pass retrieved observations and chunks to `OmneumClient.prepare_context()`.

### Retrieved Chunks

Each retrieved passage retains its original text and the identifiers linking it to Omneum's source–claim graph.

```python
{
    "chunk_id": "record-123",
    "raw_text": "...",
    "source": source,
    "observation_ids": [...],
    "claim_ids": [...],
}
```

| Field | Purpose |
|---|---|
| `chunk_id` | Identifies the passage during selection and assembly |
| `raw_text` | Preserves the original passage text |
| `source` | Identifies the evidence source |
| `observation_ids` | Links the passage to its Omneum observations |
| `claim_ids` | Links the passage to claims evaluated in the source–claim graph |

A chunk can contain multiple claims, and multiple chunks can reference the same claim.

The `claim_ids` mapping connects claim-level evaluation results to the original passages considered during budget-constrained context selection.

### Graph Inference

Omneum's algorithm constructs a bipartite graph from structured source and claim observations.

It iteratively computes source reliability and claim support, using estimated source dependencies to adjust evidence contributions during propagation.

Dependency-adjusted propagation reduces the influence of repeated assertions derived from shared upstream material. Claim scores contribute to chunk utility through each passage's `claim_ids` mapping.

The `evaluate_context` node stores the resulting `ContextEvaluation` in LangGraph state.

### Context Selection

`prepare_generation()` accepts the retrieved observations, user query, estimator configuration, and optional `RetrievedChunk` records.

The shared helper invokes `OmneumClient.prepare_context()` with the configured selection parameters:

```python
prepared = await client.prepare_context(
    observations,
    chunks,
    estimator=estimator,
    token_budget=token_budget,
    user_query=question,
    local_relevance="bm25",
    strategy="coverage_support_density",
    token_cost_exponent=1.0,
    complementary_evidence=True,
    query_diagnostics=diagnostics,
    include_dependencies=True,
)
```

The example uses local BM25 relevance and the `coverage_support_density` selection strategy.

Chunk utility incorporates graph-derived claim support and BM25 relevance. Incremental coverage adjusts each candidate's contribution according to the claims already represented by selected passages.

The SDK packs passages within the configured context budget and assembles their original text in rendering order.

The enterprise graph passes its existing `ContextEvaluation` to `prepare_generation()`. The shared helper forwards that evaluation to `OmneumClient.prepare_context()`, avoiding another graph evaluation of unchanged observations.

### Context Assembly

`prepare_context()` returns the selected passage identifiers and assembled context:

```python
prepared["packed_chunk_ids"]
prepared["context"]
```

The selected identifiers are resolved against the original retrieved chunks:

```python
by_id = {
    chunk["chunk_id"]: chunk
    for chunk in chunks
}

selected = [
    by_id[identifier]
    for identifier in prepared["packed_chunk_ids"]
]
```

`generation_messages()` constructs the messages supplied to the injected LangChain chat model:

```python
messages = generation_messages(
    question,
    prepared["context"],
    selected,
)
```

The selected chunks retain their original `raw_text`. Passages excluded during selection are omitted from the assembled generation context.

The MCP evaluator processes structured observations and provenance metadata. The Python SDK retains the retrieved passage text for context assembly.

### Generation Input

`prepare_generation()` returns a `GenerationInput` dictionary.

| Field | Content |
|---|---|
| `retrieved_chunks` | Original retrieved candidates |
| `evaluation` | Source–claim graph evaluation results |
| `prepared_context` | Selected chunk identifiers and assembled context |
| `messages` | Messages supplied to the injected chat model |
| `query_diagnostics` | BM25 query relevance diagnostics |
| `comparison` | Raw RAG comparison when enabled |
| `telemetry` | Available SDK execution measurements |

The generation messages contain the selected original passages. The complete retrieved candidate set remains available through `retrieved_chunks`.

## Conditional Routing

[`routing/graph.py`](routing/graph.py) defines `build_routing_graph()`.

The routing graph evaluates accumulated observations in LangGraph state and applies `RoutingPolicy` to determine whether additional retrieval is required before generation.

### Routing Policy

The example configures:

```python
RoutingPolicy(
    min_independent_support=1.9,
    min_support_ratio=2.0,
    max_retries=2,
)
```

| Decision | Operation |
|---|---|
| `retrieve_support` | Retrieve additional evidence for insufficiently supported claims |
| `resolve_conflicts` | Retrieve evidence addressing competing claim values |
| `diversify_sources` | Retrieve evidence from additional independent sources |
| `generate` | Proceed to context selection and generation |
| `escalate` | Terminate without model generation |

The included scenarios exercise three retrieval conditions:

| Scenario | Condition |
|---|---|
| `retrieve_support` | Insufficient support for required claims |
| `resolve_conflicts` | Competing claim values require further resolution |
| `diversify_sources` | Insufficient estimated independent support |

### Retrieval Loop

The routing graph evaluates accumulated observations before applying `RoutingPolicy`.

When the policy requests additional retrieval, the corresponding branch appends observations to graph state. The updated observation set is evaluated before the next routing decision.

```text
                 +-------------------+
                 | Retrieved evidence|
                 +---------+---------+
                           |
                           v
                   evaluate_context
                           |
                           v
                      route_context
                           |
         +-----------------+------------------+
         |                 |                  |
         v                 v                  v
  retrieve_support  resolve_conflicts  diversify_sources
         |                 |                  |
         +-----------------+------------------+
                           |
                           v
                   Updated evidence
                           |
                           +----> evaluate_context

                 route_context
                      |
            +---------+---------+
            |                   |
            v                   v
         generate             escalate
            |                   |
            v                   v
      prepare_context          END
            |
            v
       render_answer
            |
            v
           END
```

`max_retries` limits additional retrieval attempts.

When the decision is `generate`, the graph calls `prepare_generation()` with the accumulated observations and configured context budget.

`escalate` terminates the retry sequence without invoking the chat model.

### Routing and Context Selection

`RoutingPolicy` applies the configured support thresholds to the current `ContextEvaluation`.

`OmneumClient.prepare_context()` selects passages from the accumulated evidence using graph-derived claim support, BM25 relevance, incremental claim coverage, and the configured context budget.

Retrieval branches append observations to graph state before reevaluation. The resulting candidate pool is passed to context preparation when the routing policy permits generation.

The selected passages are assembled into the final generation messages.

## Configuration

The examples use the following LangGraph and Omneum settings:

| Parameter | Value |
|---|---|
| Graph API | `StateGraph` |
| MCP client | `open_stdio_client()` |
| SDK method | `OmneumClient.prepare_context()` |
| Default context budget | `600` |
| `local_relevance` | `"bm25"` |
| `strategy` | `"coverage_support_density"` |
| `token_cost_exponent` | `1.0` |
| `complementary_evidence` | `True` |
| `include_dependencies` | `True` |
| `min_independent_support` | `1.9` |
| `min_support_ratio` | `2.0` |
| `max_retries` | `2` |

`token_budget` is passed through `prepare_generation()` and can be overridden by the calling workflow.

Routing thresholds are configured separately through `RoutingPolicy`.

The context budget applies to assembled retrieved evidence. The SDK counts Unicode word/punctuation units, including rendered chunk headers, rather than model-provider tokens.

The complete model input may also include the query and additional system or conversation messages.

## Inspection and Telemetry

Both CLI entry points use the shared `run_cli()` interface.

### Context Inspection

```bash
uv run --locked --group langgraph \
  -m examples.langgraph.run --inspect-context
```

Inspection reports the selected chunk identifiers and prepared context without invoking a chat model.

### Raw RAG Comparison

```bash
uv run --locked --group langgraph \
  -m examples.langgraph.run --compare --token-budget 400
```

The comparison evaluates retrieval-order packing and Omneum's graph-informed selection against the same retrieved chunks and context budget.

| Configuration | Selection behavior |
|---|---|
| Raw RAG | Packs retrieved chunks in retrieval order |
| Omneum | Selects chunks using BM25 relevance, graph-derived claim support, and incremental claim coverage |

The comparison reports selected chunk IDs, rendering order, budget consumption, claim coverage, and excluded chunks.

Graph evaluation diagnostics cover the complete observation set before passage selection.

### JSON Output

```bash
uv run --locked --group langgraph \
  -m examples.langgraph.run --json --include-context
```

JSON output includes retrieved chunk identifiers, selected chunk identifiers, rendering order, graph evaluation diagnostics, and context-preparation results.

`--include-context` adds the selected original passages and generation messages.

### Execution Telemetry

```bash
uv run --locked --group langgraph \
  -m examples.langgraph.run \
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

SDK telemetry measures graph evaluation and context preparation. Model generation latency is excluded.

## Files

| File | Responsibility |
|---|---|
| [`graph.py`](graph.py) | Enterprise `StateGraph` construction |
| [`nodes.py`](nodes.py) | Enterprise retrieval, evaluation, preparation, and generation nodes |
| [`state.py`](state.py) | Shared graph state schema and reducers |
| [`run.py`](run.py) | Enterprise CLI |
| [`routing/graph.py`](routing/graph.py) | Conditional routing graph |
| [`routing/policy.py`](routing/policy.py) | Routing thresholds and decisions |
| [`routing/retrieval.py`](routing/retrieval.py) | Routing retrieval records |
| [`routing/scenarios.py`](routing/scenarios.py) | Routing scenarios |
| [`routing/selection.py`](routing/selection.py) | Claim-selection functions |
| [`routing/selection_graph.py`](routing/selection_graph.py) | Selection graph |
| [`routing/run.py`](routing/run.py) | Routing CLI |
| [`../context_preparation.py`](../context_preparation.py) | Shared Omneum SDK context preparation |

## Documentation

- [LangGraph Graph API](https://docs.langchain.com/oss/python/langgraph/graph-api)
- [Using the LangGraph Graph API](https://docs.langchain.com/oss/python/langgraph/use-graph-api)
- [Omneum Python SDK](../../docs/sdk.md)
- [Omneum Installation](../../docs/guides/installation.md)
- [Omneum Enterprise Example](../enterprise/)
- [Omneum Repository](https://github.com/cole-h06/omneum)