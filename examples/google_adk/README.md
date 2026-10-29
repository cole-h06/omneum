# Google ADK

Google Agent Development Kit (ADK) integration for [Omneum](https://github.com/cole-h06/omneum).

Omneum evaluates retrieved evidence through provenance-aware graph inference, then reconstructs the model's context using query relevance and incremental claim coverage under a token budget.

This directory contains two Google ADK integrations:

- **Enterprise Agent (`LlmAgent`)** — Exposes Omneum's evaluation through an ADK `FunctionTool`. Gemini receives a formatted evaluation report and generates the answer.
- **Conditional Routing (`RoutingAgent`)** — Uses a custom ADK `BaseAgent` to evaluate evidence, retrieve additional observations, select supported claims, and produce a deterministic response without an LLM.

Both examples invoke Omneum through its Python SDK and local MCP stdio connection.

The existing implementations demonstrate graph evaluation and claim-based routing. They do not yet invoke `OmneumClient.prepare_context()` to reconstruct original retrieved passages under a token budget.

## Installation

From the repository root:

```bash
uv sync --locked --python 3.13 --group google-adk
```

Provision the local Omneum service using the [installation guide](../../docs/guides/installation.md).

The examples use local enterprise evidence fixtures. The enterprise agent requires Gemini API credentials or configured Vertex AI authentication. Conditional routing runs without model credentials.

## Quick Start

### Enterprise Agent

Configure Gemini and start the interactive agent:

```bash
export GOOGLE_API_KEY="your-api-key"
export GOOGLE_GENAI_USE_VERTEXAI=FALSE
export GOOGLE_ADK_MODEL=gemini-2.5-flash

uv run --locked --python 3.13 --group google-adk \
  -m examples.google_adk.run
```

The agent retrieves fixture-backed enterprise observations, evaluates them through Omneum, and returns the evaluation report to Gemini.

The retrieval functions and MCP deployment configuration are shared with [`examples/enterprise`](../enterprise/).

### Conditional Routing

Run all three scenarios:

```bash
uv run --locked --python 3.13 --group google-adk \
  -m examples.google_adk.routing.run --scenario all
```

Run one scenario:

```bash
uv run --locked --python 3.13 --group google-adk \
  -m examples.google_adk.routing.run --scenario resolve_conflicts
```

Execute the routing workflow directly:

```python
import asyncio

from examples.google_adk.routing.workflow import run_routing


state = asyncio.run(run_routing("retrieve_support"))

print(state.routing_history)
print(state.answer)
```

The routing example evaluates observations through Omneum MCP and produces a deterministic result. It does not invoke Gemini.

## Enterprise Agent

[`agent.py`](agent.py) defines the enterprise `LlmAgent`, its Omneum evaluation function, and the ADK `FunctionTool` registered with the agent.

### ADK Integration

```python
from examples.google_adk.agent import build_agent, evaluation_tool

agent = build_agent()

assert agent.tools == [evaluation_tool]
print(agent.model)
```

| Component | ADK API | Responsibility |
|---|---|---|
| Enterprise agent | `LlmAgent` | Invokes Gemini with the registered evaluation tool |
| Evaluation tool | `FunctionTool` | Executes Omneum evaluation through a Python callback |
| Agent execution | `Runner` | Processes model requests, tool calls, and response events |
| Session storage | `InMemorySessionService` | Maintains the ADK session |
| Conditional routing | `BaseAgent` | Implements application-controlled retrieval and routing |
| Workflow events | `Event`, `EventActions` | Publishes execution results and session-state updates |

The enterprise agent registers Omneum as an ADK function tool. It does not register Omneum's MCP server directly as an ADK MCP toolset.

### Evaluation Tool

The evaluation callback collects observations from the enterprise fixtures, maps their source and claim fields, and invokes Omneum:

```python
import asyncio

from examples.google_adk.agent import evaluate_context


report = asyncio.run(evaluate_context())

print(report)
```

The implementation uses `ContextMapper` to convert the enterprise retrieval records into Omneum's structured evaluation input.

It calls:

```python
result = await client.evaluate_mapped(
    observations,
    mapper,
    estimator=estimator_config(),
)
```

The tool returns the formatted output of `render_result(result)`.

The result contains evaluated source and claim support information. It is not a reconstructed collection of original retrieved passages.

### Execution

```text
User question
     |
     v
ADK Runner
     |
     v
Enterprise LlmAgent
     |
     v
evaluate_context FunctionTool
     |
     +-- Collect enterprise observations
     |
     +-- Map sources and claims
     |
     +-- Omneum evaluate_mapped()
     |
     +-- Render evaluation report
     |
     v
Gemini generates answer
```

ADK manages the model interaction and function-tool invocation. Omneum computes the evaluation results returned by the tool.

The enterprise agent's final answer is model-generated. The evaluation scores are inputs to that answer, not a deterministic deployment decision.

## Context Evaluation & Reconstruction

Omneum's algorithm operates on a bipartite source–claim graph constructed from structured observations.

It iteratively computes source reliability and claim support, adjusting evidence contributions using estimated source dependencies during propagation.

Different values for the same entity and attribute remain separate competing claims. Estimated independent support distinguishes repeated assertions from additional independent evidence.

### Evaluation Inputs

The enterprise integration uses `ContextMapper` to preserve source identity, claim identity, observation metadata, and provenance information.

The routing integration receives SDK `Observation` objects and evaluates them directly:

```python
with example_deployment() as (config, server):
    async with open_stdio_client(config, server) as client:
        evaluation = await client.evaluate_context(
            observations,
            estimator=estimator_config(),
        )
```

The evaluator operates on structured observations and provenance metadata without requiring the original retrieved passage text.

### Evaluation Results

`ContextEvaluation` exposes the graph inference results:

| Field | Content |
|---|---|
| `source_reliability` | Relative source reliability scores |
| `claim_support` | Claim support scores and claim identities |
| `pairwise_dependencies` | Estimated dependencies between sources |
| `evaluation_latency_ms` | Evaluation duration |
| `explanation` | Formatted evaluation information |

Individual claim results include estimated independent support:

```python
for item in evaluation.claim_support:
    print(
        item.claim.attribute,
        item.claim.value,
        item.support,
        item.estimated_independent_support_count,
    )
```

Claim support scores are relative evidence measures, not probabilities or authorization decisions.

### Retrieved Chunks

Omneum's context-preparation API connects evaluated claims to original retrieved passages through `RetrievedChunk` records.

| Field | Content |
|---|---|
| `chunk_id` | Retrieved passage identifier |
| `raw_text` | Original passage text |
| `source` | Source metadata |
| `observation_ids` | Associated observation identifiers |
| `claim_ids` | Claims represented by the passage |

A chunk may contain multiple claims, and multiple chunks may reference the same claim.

`claim_ids` links graph-derived claim support to the original passages competing for space in the model's context window.

### Context Selection

The SDK derives chunk utility from claim support and query relevance.

Selection also accounts for incremental claim coverage: a candidate's contribution depends on which claims are already represented in the selected context.

Omneum selects and orders chunks within the configured budget, then reconstructs their original text. Unselected passages are excluded from the generation messages.

The Python SDK retains `raw_text` for reconstruction. The MCP evaluator receives structured observations and provenance metadata rather than original passages.

### SDK Context Preparation

The shared [`context_preparation.py`](../context_preparation.py) helper exposes the context-reconstruction API used by the newer framework integrations:

```python
from examples.context_preparation import (
    PreparationOptions,
    prepare_generation,
)


generation = await prepare_generation(
    observations,
    question=question,
    estimator=estimator_config(),
    chunks=chunks,
    evaluation=evaluation,
    preparation=PreparationOptions(token_budget=400),
)
```

Passing an existing `ContextEvaluation` allows the SDK to reuse completed graph inference.

The prepared context exposes the selected chunk identifiers and reconstructed text:

```python
prepared = generation["prepared_context"]

selected_ids = prepared["packed_chunk_ids"]
context = prepared["context"]
```

`packed_chunk_ids` specifies the selected passages in rendering order.

`prepare_generation()` returns a `GenerationInput` dictionary:

| Field | Content |
|---|---|
| `generation["retrieved_chunks"]` | Original retrieved candidate passages |
| `generation["evaluation"]` | Graph evaluation results |
| `generation["prepared_context"]` | Selected chunks and reconstructed context |
| `generation["messages"]` | Prepared generation messages |
| `generation["query_diagnostics"]` | Query relevance diagnostics |
| `generation["comparison"]` | Raw RAG comparison when enabled |
| `generation["telemetry"]` | Available SDK execution measurements |

The existing Google ADK examples do not call this helper.

The enterprise agent returns `render_result()` to Gemini, while the routing agent selects claim values for a deterministic response.

An ADK integration using Omneum's current context-reconstruction API can prepare the retrieved passages before model generation and supply the reconstructed context through its chosen ADK model-input path.

## Conditional Routing

[`routing/workflow.py`](routing/workflow.py) defines `RoutingAgent`, a custom subclass of ADK's `BaseAgent`.

The agent implements retrieval, evaluation, routing, and deterministic response construction inside `_run_async_impl()`.

ADK's `Runner` executes the custom agent and consumes the events it yields.

### Creating the Routing Agent

```python
from examples.google_adk.routing.state import RoutingState
from examples.google_adk.routing.workflow import RoutingAgent
from examples.langgraph.routing.policy import RoutingPolicy


agent = RoutingAgent(
    name="omneum_routing",
    state=RoutingState("diversify_sources", 0, ()),
    policy=RoutingPolicy(max_retries=2),
)
```

`RoutingState` stores the accumulated observations and routing results.

`RoutingPolicy` defines the application's evidence requirements and retry limit.

Routing decisions are computed in Python from Omneum's evaluation results. They are not Gemini tool calls or model-selected branches.

### Execution

```text
Initial observations
         |
         v
  evaluate_context
         |
         v
    assess_context
         |
         +-- retrieve_support -----+
         |                         |
         +-- resolve_conflicts ----+--> Retrieve additional
         |                         |    observations
         +-- diversify_sources ---+          |
         |                                    v
         |                              Deduplicate IDs
         |                                    |
         |                                    v
         |                              Increment retry
         |                                    |
         |                                    +--> evaluate_context
         |
         +-- generate
         |      |
         |      v
         |  select_context
         |      |
         |      v
         |  Deterministic response
         |
         +-- escalate
                |
                v
         Escalation response
```

The implementation reuses the routing policy, retrieval strategies, scenarios, and claim selector from [`examples/langgraph/routing`](../langgraph/routing/).

Retrieval branches append observations with previously unseen observation IDs. The accumulated evidence is reevaluated before the next routing decision.

### Routing Scenarios

| Scenario | Initial condition | Retrieval action |
|---|---|---|
| `diversify_sources` | Insufficient estimated independent support | Retrieve evidence from additional sources |
| `retrieve_support` | Missing or insufficient support for required claims | Retrieve observations for affected attributes |
| `resolve_conflicts` | Competing claim values lack sufficient support separation | Retrieve evidence addressing those values |

The example policy uses:

```python
RoutingPolicy(
    min_independent_support=1.9,
    min_support_ratio=2.0,
    max_retries=2,
)
```

| Parameter | Value | Purpose |
|---|---:|---|
| `min_independent_support` | `1.9` | Required estimated independent support |
| `min_support_ratio` | `2.0` | Required support separation between competing values |
| `max_retries` | `2` | Maximum additional retrieval attempts |

### Routing Decisions

| Route | Operation |
|---|---|
| `retrieve_support` | Retrieve evidence for missing or insufficiently supported attributes |
| `resolve_conflicts` | Retrieve evidence addressing competing claim values |
| `diversify_sources` | Retrieve evidence from additional sources |
| `generate` | Select supported claims and construct the response |
| `escalate` | Stop without producing a supported-claim response |

`assess_context()` reads the current evaluation and retry count to select the next route.

The retrieval functions use the selected route, target attributes, and attempt number to obtain additional fixture observations.

### Claim Selection

When the routing policy returns `generate`, the example calls the shared `select_context()` function.

This selector operates on evaluated claims. It applies support and conflict requirements to determine which claim values appear in the deterministic response.

Claims that fail selection remain in `ContextEvaluation` but are omitted from the selected-claim output.

This differs from Omneum's `prepare_context()` API:

| Operation | Input | Output |
|---|---|---|
| `select_context()` in the routing example | `ContextEvaluation` | Selected claim values |
| `OmneumClient.prepare_context()` | Evaluated observations and retrieved chunks | Selected, ordered, original-text passages |

The routing example does not perform token-budgeted chunk packing or original-text reconstruction.

### ADK Execution and State

`RoutingAgent._run_async_impl()` runs the routing procedure through ADK's custom-agent execution interface.

The custom agent yields ADK `Event` objects. `EventActions` carries session-state updates through the event stream.

The application retains routing data in `RoutingState`, including:

- Current observations and evaluation results.
- Selected route and routing history.
- Retrieval retry count.
- Selected claims.
- Final deterministic response.

The `Runner` provides the ADK execution environment. Routing remains inside the custom agent rather than being delegated to an `LlmAgent`.

### Escalation

If the routing policy cannot satisfy its evidence requirements within the configured retry limit, it returns `escalate`.

The example produces an application-level escalation result instead of generating an answer from unsupported claim values.

## Configuration

### ADK and Model Configuration

| Setting | Description |
|---|---|
| `GOOGLE_ADK_MODEL` | Enterprise model; defaults to `gemini-2.5-flash` |
| `GOOGLE_API_KEY` | Gemini API credentials |
| `GOOGLE_GENAI_USE_VERTEXAI` | Select Gemini API or Vertex AI |
| `GOOGLE_CLOUD_PROJECT` | Vertex AI project |
| `GOOGLE_CLOUD_LOCATION` | Vertex AI location |

The enterprise agent requires model credentials. Conditional routing does not.

### Omneum Configuration

| Component | Implementation |
|---|---|
| Context mapper | `ContextMapper` |
| Mapped evaluation | `OmneumClient.evaluate_mapped()` |
| Direct evaluation | `OmneumClient.evaluate_context()` |
| MCP transport | `open_stdio_client()` |
| Local deployment | `example_deployment()` |
| Estimator | `estimator_config()` |
| Routing policy | `RoutingPolicy` |
| Claim selection | `select_context()` |
| Context reconstruction API | `OmneumClient.prepare_context()` |

Local deployment settings include:

| Setting | Description |
|---|---|
| `OMNEUM_CONFIG_DIR` | Local Omneum deployment configuration |
| `OMNEUM_DAEMON_SOCKET` | Local Omneum daemon socket |

### Context Budgets

The existing Google ADK examples do not expose `PreparationOptions` or a context-budget CLI option.

For integrations using the shared context-preparation helper:

```python
from examples.context_preparation import PreparationOptions


options = PreparationOptions(
    token_budget=600,
    compare=False,
    include_telemetry=False,
    collect_telemetry=False,
)
```

`token_budget` limits reconstructed evidence context, including passage headers and separators.

The current SDK counter measures Unicode word/punctuation units, not provider-specific model tokens.

The budget does not include ADK agent instructions, conversation history, tool descriptions, or other model input.

A budget of `0` selects no evidence passages.

## Files

| Path | Responsibility |
|---|---|
| [`agent.py`](agent.py) | Enterprise `LlmAgent`, evaluation callback, and `FunctionTool` |
| [`run.py`](run.py) | Enterprise interactive CLI |
| [`routing/workflow.py`](routing/workflow.py) | Custom `RoutingAgent`, retrieval loop, evaluation, and response |
| [`routing/state.py`](routing/state.py) | Routing state and evaluation results |
| [`routing/run.py`](routing/run.py) | Routing scenario CLI |
| [`../context_preparation.py`](../context_preparation.py) | Shared SDK context reconstruction |
| [`../langgraph/routing/`](../langgraph/routing/) | Shared routing policy, claim selection, scenarios, and retrieval |
| [`../enterprise/`](../enterprise/) | Enterprise evidence fixtures, estimator, and MCP deployment |

## Requirements

- Python 3.13 with the repository-locked `google-adk` dependency group.
- Omneum Python SDK and provisioned local MCP service.
- Gemini API credentials or Vertex AI authentication for enterprise model generation.
- Local enterprise fixtures for deterministic routing.

The enterprise example uses a model-generated answer based on an Omneum evaluation report.

The conditional routing example uses deterministic retrieval, graph evaluation, and claim selection without model generation.

Neither existing Google ADK path currently demonstrates Omneum's token-budgeted original-text context reconstruction.

## Documentation

- [Google Agent Development Kit](https://google.github.io/adk-docs/)
- [Custom agents](https://google.github.io/adk-docs/agents/custom-agents/)
- [Function tools](https://google.github.io/adk-docs/tools-custom/function-tools/)
- [ADK sessions](https://google.github.io/adk-docs/sessions/)
- [Omneum SDK](../../docs/sdk.md)
- [Omneum installation](../../docs/guides/installation.md)
- [Enterprise example](../enterprise/)
- [OpenAI Agents SDK integration](../openai_agents/)
- [LangGraph integration](../langgraph/)
- [CrewAI integration](../crewai/)
- [LlamaIndex integration](../llamaindex/)
- [Microsoft Agent Framework integration](../microsoft/)