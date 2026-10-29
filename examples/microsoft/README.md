# Microsoft Agent Framework

Microsoft Agent Framework integration for [Omneum](https://github.com/cole-h06/omneum).

Omneum evaluates retrieved evidence through provenance-aware graph inference, selects passages using BM25 query relevance and incremental claim coverage, and assembles the selected text within a configured context budget.

Two integration patterns:

| Pattern | Microsoft API | Omneum entry point | Output |
|---|---|---|---|
| **Enterprise Agent** | `Agent`, `OpenAIChatClient` | `prepare_generation()` | Prepared original passages and an OpenAI-generated answer |
| **Conditional Routing** | `WorkflowBuilder`, `@executor`, conditional `add_edge()` | `evaluate_context()` → `prepare_generation()` | Budgeted context payload, followed by a deterministic response or an optional agent response |

Both paths use the shared context-preparation implementation. The enterprise agent can run with an OpenAI model; routing can run entirely without one.

## Quick Start

Install the Microsoft dependency group from the repository root:

```bash
uv sync --locked --python 3.13 --group microsoft
```

Provision Omneum's local MCP evaluator using the [installation guide](../../docs/guides/installation.md).

**Inspect selected context without a model:**

```bash
uv run --locked --python 3.13 --group microsoft \
  -m examples.microsoft.run --inspect-context
```

**Run all routing scenarios:**

```bash
uv run --locked --python 3.13 --group microsoft \
  -m examples.microsoft.routing.run --scenario all
```

**Run the OpenAI-backed enterprise agent:**

```bash
export OPENAI_API_KEY="your-api-key"
export OPENAI_MODEL="gpt-5.5"

uv run --locked --python 3.13 --group microsoft \
  -m examples.microsoft.run
```

The interactive CLI prompts for a deployment-readiness question. Context inspection and deterministic routing do not require `OPENAI_API_KEY`.

## How It Works

Microsoft Agent Framework controls execution. Omneum evaluates structured observations and prepares the passages passed to generation.

```text
Enterprise Agent
  Enterprise observations
           |
           v
   prepare_generation()
           |
           +--> graph evaluation over MCP stdio
           +--> rank and select retrieved chunks
           +--> assemble original passage text
           |
           v
    Prepared messages
           |
           v
    OpenAI-backed Agent


Conditional Routing
    load evidence
           |
           v
   evaluate_context
           |
           v
     route_context
       /       \
  retrieve   generate
     |          |
     +--> reevaluate
                |
                v
          select_claims
                |
                v
          prepare_context
                |
                v
             generate
```

The routing workflow also has an `escalate` terminal branch. Its `prepare_context` executor calls the shared `prepare_generation()` function; it does not implement a second ranking algorithm.

| Stage | Code | Behavior |
|---|---|---|
| Observation collection | `collect_observations()` | Loads enterprise evidence fixtures |
| Graph evaluation | `evaluate_context()`, `evaluate_mapped()` | Computes source reliability, claim support, and dependencies |
| Routing | `assess_context()` | Chooses retrieval, generation, or escalation |
| Chunk collection | `collect_chunks()` | Builds retrieved chunks from observations |
| Context preparation | `prepare_generation()` | Evaluates or reuses scores, selects chunks, assembles text |
| Generation | `Agent.run()` or workflow terminal executor | Uses prepared messages or returns a deterministic payload |

### What Goes to the MCP Evaluator?

The evaluator receives structured source, claim, observation, and dependency metadata. Original passage text remains in the Python context-preparation path.

| Data | MCP graph evaluation | Python context preparation |
|---|:---:|:---:|
| Source identities and provenance | Yes | Yes |
| Claim identities and values | Yes | Yes |
| Dependency signals | Yes | Yes |
| `RetrievedChunk.raw_text` | No | Yes |
| BM25 query relevance | No | Yes |
| Chunk selection and passage assembly | No | Yes |

## Enterprise Agent

[`agent.py`](agent.py) registers the `evaluate_context` tool with Microsoft Agent Framework:

```python
from agent_framework import Agent
from agent_framework.openai import OpenAIChatClient

from .tools import evaluate_context

agent = Agent(
    client=OpenAIChatClient(),
    name="Enterprise AI Assistant",
    instructions=(
        "Answer deployment-readiness questions using the "
        "evaluate_context tool with the user's question before answering. "
        "Use its original passages as evidence, cite chunk IDs, and explain conflicts."
    ),
    tools=[evaluate_context],
)
```

The tool is defined in [`tools.py`](tools.py):

```python
async def evaluate_context(question: str = QUESTION) -> str:
    generation = await prepare_generation(
        collect_observations(),
        question=question,
        estimator=estimator_config(),
    )
    return generation["messages"][1]["content"]
```

Despite its name, this tool returns **prepared original passages**, not just a graph-evaluation report. The agent receives the selected context as tool output.

### Direct Context Preparation

`run_agent()` also exposes the preparation result to application code, without requiring the model to choose a tool call:

```python
from examples.context_preparation import PreparationOptions
from examples.microsoft.tools import run_agent

generation, response = await run_agent(
    preparation=PreparationOptions(token_budget=400),
    inspect_context=True,
)
```

With `inspect_context=True`, `response` is `None` and no OpenAI request is made.

Without inspection, `run_agent()` converts the prepared `generation["messages"]` to Microsoft `Message` objects and passes them to `Agent.run()`.

| `run_agent()` argument | Purpose |
|---|---|
| `question` | Retrieval and generation query |
| `preparation` | `PreparationOptions`, including context budget |
| `generation_agent` | Optional injected Microsoft `Agent` |
| `inspect_context` | Return prepared context without model generation |

### Enterprise Fixtures

The example loads 17 observations from six sources using the shared enterprise modules.

| Module | Evidence |
|---|---|
| [`documents.py`](../enterprise/agents/documents.py) | Current policy and stale runbook |
| [`research.py`](../enterprise/agents/research.py) | Readiness brief derived from the runbook |
| [`sql.py`](../enterprise/agents/sql.py) | Model registry |
| [`api.py`](../enterprise/agents/api.py) | Gateway configuration |
| [`search.py`](../enterprise/agents/search.py) | Vendor data controls |

The modules read local JSON fixtures; they do not connect to live enterprise services. The evidence includes competing values and shared upstream material.

## Conditional Routing

[`routing/workflow.py`](routing/workflow.py) defines `build_routing_workflow()`. Microsoft `WorkflowBuilder` connects executors with conditional edges; Omneum's source–claim graph is a separate data structure used to score evidence.

### Execution Graph

```text
load
 |
 v
evaluate_context <-----------------------------+
 |                                            |
 v                                            |
route_context                                  |
 |                                            |
 +-- retrieve_support ------------------------+
 +-- resolve_conflicts -----------------------+
 +-- diversify_sources ----------------------+
 |
 +-- generate --> select_claims --> prepare_context --> generate
 |
 +-- escalate -------------------------------> escalate_answer
```

The actual route names are returned by the shared `assess_context()` policy. Each retrieval branch appends new observations, then reevaluates the expanded set.

### Build and Run

```python
import asyncio

from examples.context_preparation import PreparationOptions
from examples.microsoft.routing.workflow import build_routing_workflow


async def main():
    workflow = build_routing_workflow(
        preparation=PreparationOptions(token_budget=400),
    )
    result = await workflow.run("resolve_conflicts")
    state = result.get_outputs()[0]

    print(state.routing_history)
    print(state.generation["prepared_context"]["context"])
    print(state.answer)


asyncio.run(main())
```

`build_routing_workflow()` also accepts `generation_agent`. When supplied, the terminal `generate` executor calls `generation_agent.run(state.generation_messages)`. Without one, it returns the prepared context in a deterministic response.

### Executor Responsibilities

| Executor | Input | Operation |
|---|---|---|
| `load` | Scenario name | Creates `RoutingState`, sets `PreparationOptions` |
| `evaluate_context` | `RoutingState` | Calls `collect_chunks()` and evaluates observations over MCP stdio |
| `route_context` | Latest `ContextEvaluation` | Calls `assess_context()` and appends routing history |
| `RetrieveEvidence` | Selected retrieval strategy | Adds unseen observation IDs and increments retry count |
| `select_claims` | Evaluated claims | Calls the shared `select_context()` claim filter |
| `prepare_context` | Observations, chunks, prior evaluation | Calls `prepare_generation()` and constructs Microsoft messages |
| `generate` | Prepared messages | Runs an injected agent or returns prepared context |
| `escalate_answer` | Failed routing policy | Returns the escalation result |

### Reuse the Graph Evaluation

The `prepare_context` executor passes the evaluation already computed by the routing workflow:

```python
@executor
async def prepare_context(
    state: RoutingState,
    ctx: WorkflowContext[RoutingState],
) -> None:
    state.generation = await prepare_generation(
        state.observations,
        question=state.question,
        estimator=estimator_config(),
        chunks=state.retrieved_chunks,
        evaluation=state.context_evaluation,
        preparation=state.preparation,
    )
    state.generation_messages = [
        Message(message["role"], contents=[message["content"]])
        for message in state.generation["messages"]
    ]
    await ctx.send_message(state)
```

The `evaluation` argument lets the shared preparation function reuse the latest `ContextEvaluation`. The `chunks` argument supplies original passages for ranking and assembly.

### Routing Policy

The shared [`RoutingPolicy`](../langgraph/routing/policy.py) uses:

```python
RoutingPolicy(
    min_independent_support=1.9,
    min_support_ratio=2.0,
    max_retries=2,
)
```

| Route | Triggered action |
|---|---|
| `retrieve_support` | Retrieve evidence for missing or weakly supported attributes |
| `resolve_conflicts` | Retrieve evidence addressing competing values |
| `diversify_sources` | Add evidence from independent sources |
| `generate` | Select claims, prepare passages, generate |
| `escalate` | Return an escalation result |

`select_claims` and `prepare_context` serve different purposes: the first filters evaluated claims; the second ranks and assembles retrieved **text chunks** under a budget.

### Routing Scenarios

| Scenario | Initial observations | Retrieval strategy |
|---|---:|---|
| `diversify_sources` | 17 | Add an independent compliance source |
| `retrieve_support` | 11 | Retrieve missing or weak processing-region evidence |
| `resolve_conflicts` | 9 | Add independent policy-review evidence |

The scenarios and retrieval strategies are shared with [`../langgraph/routing/`](../langgraph/routing/).

## Omneum's Algorithm

Context preparation uses one unified path from structured evidence to selected original text.

### 1. Evaluate Evidence

Omneum constructs a bipartite graph of sources and claims. Observation edges connect sources to asserted entity–attribute–value claims.

The evaluator iteratively computes source reliability and claim support. Estimated source dependencies adjust contributions from evidence sharing upstream material.

| Evaluation field | Meaning |
|---|---|
| `source_reliability` | Relative source reliability scores |
| `claim_support` | Claim support scores and estimated independent support |
| `pairwise_dependencies` | Estimated source dependencies |
| `evaluation_latency_ms` | Graph evaluation duration |
| `explanation` | Formatted evaluation report |

`support` is a graph-derived score. `estimated_independent_support_count` estimates the effective number of independent supporting sources; neither is a probability.

### 2. Rank Retrieved Chunks

`RetrievedChunk` records retain the original passage text and mappings to evaluated claims.

| Field | Purpose |
|---|---|
| `chunk_id` | Stable identifier for a retrieved passage |
| `raw_text` | Original passage content |
| `source` | Passage source |
| `observation_ids` | Associated observations |
| `claim_ids` | Links between the passage and graph-evaluated claims |

The SDK combines BM25 query relevance, graph-derived claim support, and incremental claim coverage to score candidate chunks. Claim mappings connect graph results to passages without sending passage text to the evaluator.

### 3. Select and Assemble Context

The SDK selects chunks within the configured context budget, orders the selected passages, and assembles their original `raw_text` into a generation payload.

```python
from examples.context_preparation import PreparationOptions, prepare_generation

generation = await prepare_generation(
    observations,
    question=question,
    estimator=estimator_config(),
    chunks=chunks,
    evaluation=evaluation,
    preparation=PreparationOptions(token_budget=400),
)
```

The Microsoft workflow calls this shared function through its `prepare_context` executor.

The budget uses the SDK's context-unit accounting, not the downstream model provider's tokenizer. Model instructions and other messages are outside the selected-passage budget.

### 4. Generate from Prepared Messages

`prepare_generation()` returns a `GenerationInput` containing the evaluation, retrieved candidates, prepared context, and model messages.

| Key | Content |
|---|---|
| `retrieved_chunks` | Full retrieved candidate set |
| `evaluation` | `ContextEvaluation` |
| `prepared_context` | Selected passage context and packing details |
| `messages` | Messages constructed for generation |
| `query_diagnostics` | Query and selection diagnostics |
| `comparison` | Raw RAG comparison when enabled |
| `telemetry` | Execution metrics when collected |

Microsoft's `Message` objects are created from `generation["messages"]`. The prepared passages—not a claim-score dump—become the content supplied to generation.

## Context Inspection and Comparison

Use the shared CLI to inspect selection before calling a model:

```bash
uv run --locked --python 3.13 --group microsoft \
  -m examples.microsoft.run --inspect-context --token-budget 400
```

Compare retrieval-order packing with Omneum's selection:

```bash
uv run --locked --python 3.13 --group microsoft \
  -m examples.microsoft.run --compare --token-budget 400
```

Run a routing scenario with a budget:

```bash
uv run --locked --python 3.13 --group microsoft \
  -m examples.microsoft.routing.run \
  --scenario resolve_conflicts \
  --token-budget 400
```

| Mode | Selection |
|---|---|
| Raw RAG comparison | Packs candidates in retrieval order under the same budget |
| Omneum | Uses BM25 relevance, graph-derived support, and incremental claim coverage |

The comparison uses the same candidate pool and context-unit budget. It does not require an OpenAI model.

## Configuration

| Setting | API or value |
|---|---|
| Microsoft agent | `agent_framework.Agent` |
| OpenAI client | `agent_framework.openai.OpenAIChatClient` |
| OpenAI credentials | `OPENAI_API_KEY` |
| Model selection | `OPENAI_MODEL` or `OPENAI_CHAT_MODEL` |
| Workflow construction | `WorkflowBuilder` |
| Function executors | `@executor` |
| Class executors | `Executor`, `@handler` |
| Conditional routing | `WorkflowBuilder.add_edge(..., condition=...)` |
| Workflow state | `RoutingState` |
| Context options | `PreparationOptions` |
| Shared preparation | `prepare_generation()` |
| Graph evaluation | `evaluate_context()` |
| MCP transport | `open_stdio_client()` |
| Local deployment | `example_deployment()` |
| Dependency estimator | `estimator_config()` |
| Routing policy | `RoutingPolicy`, `assess_context()` |
| Claim filtering | `select_context()` |

### Implementation Files

| File | Responsibility |
|---|---|
| [`agent.py`](agent.py) | OpenAI-backed agent and registered preparation tool |
| [`tools.py`](tools.py) | `evaluate_context()` tool and `run_agent()` preparation path |
| [`run.py`](run.py) | Enterprise CLI |
| [`routing/workflow.py`](routing/workflow.py) | Evaluation, routing, retrieval, context preparation, and generation executors |
| [`routing/state.py`](routing/state.py) | Observations, chunks, evaluation, generation payload, and routing history |
| [`routing/run.py`](routing/run.py) | Routing CLI |
| [`../context_preparation.py`](../context_preparation.py) | Shared context-preparation implementation |
| [`../context_output.py`](../context_output.py) | Shared CLI inspection and comparison |
| [`../enterprise/`](../enterprise/) | Enterprise fixtures and evaluator configuration |
| [`../langgraph/routing/`](../langgraph/routing/) | Shared policy, scenarios, retrieval, and claim filtering |

## Documentation

- [Microsoft Agent Framework](https://learn.microsoft.com/en-us/agent-framework/)
- [Workflow Builder](https://learn.microsoft.com/en-us/agent-framework/workflows/workflows)
- [Conditional Edges](https://learn.microsoft.com/en-us/agent-framework/concepts/workflows/edges)
- [Omneum SDK](../../docs/sdk.md)
- [Local Installation](../../docs/guides/installation.md)
- [Enterprise Example](../enterprise/)
- [LangGraph Integration](../langgraph/)
- [LlamaIndex Integration](../llamaindex/)
- [CrewAI Integration](../crewai/)
- [OpenAI Agents SDK Integration](../openai_agents/)