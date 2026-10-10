
# Google ADK

Omneum integration for [Google Agent Development Kit (ADK)](https://google.github.io/adk-docs/). Includes an `LlmAgent` with an Omneum evaluation tool and a custom `BaseAgent` for evaluation-driven retrieval and conditional routing.

## Installation

From the repository root:

```bash
uv sync --locked --python 3.13 --group google-adk
```

The locked environment installs Google ADK 1.14.1 on Python 3.13.

## Quick Start

### Enterprise Agent

The enterprise agent retrieves context, maps observations through `ContextMapper`, evaluates them with Omneum over MCP stdio, and returns the evaluation to Gemini.

```bash
export GOOGLE_API_KEY="your-api-key"
export GOOGLE_GENAI_USE_VERTEXAI=FALSE
export GOOGLE_ADK_MODEL=gemini-2.5-flash

uv run --locked --python 3.13 --group google-adk \
  -m examples.google_adk.run
```

The example uses the retrieval fixtures and local deployment from [`examples/enterprise`](../enterprise/).

### Conditional Routing

Run all three routing scenarios:

```bash
uv run --locked --python 3.13 --group google-adk \
  -m examples.google_adk.routing.run --scenario all
```

Or execute the workflow directly:

```python
import asyncio

from examples.google_adk.routing.workflow import run_routing

state = asyncio.run(run_routing("retrieve_support"))

print(state.routing_history)
print(state.answer)
```

The routing example uses local retrieval fixtures and Omneum MCP evaluation. It requires no Gemini API key or model requests.

## Agent Integration

The enterprise agent registers Omneum evaluation as a native ADK `FunctionTool`.

```python
from examples.google_adk.agent import build_agent, evaluation_tool

agent = build_agent()

assert agent.tools == [evaluation_tool]
print(agent.model)
```

| Component | ADK API | Implementation |
|---|---|---|
| Enterprise agent | `LlmAgent` | Registers `evaluate_context` as a tool |
| Evaluation tool | `FunctionTool` | Maps observations and invokes Omneum MCP |
| Agent execution | `Runner` | Processes tool calls and model responses |
| Sessions | `InMemorySessionService` | Maintains the agent session |
| Conditional routing | `BaseAgent` | Executes deterministic routing inside ADK |
| Workflow state | `Event`, `EventActions` | Publishes stage updates to session state |

The evaluation tool uses the existing enterprise retrieval functions and `ContextMapper`:

```python
from examples.google_adk.agent import evaluate_context

import asyncio

report = asyncio.run(evaluate_context())
print(report)
```

The underlying evaluation uses `client.evaluate_mapped(...)` and returns the formatted result from `render_result()`.

## Conditional Routing

The routing workflow uses a custom `RoutingAgent(BaseAgent)` executed by ADK's `Runner`. Routing decisions are made by Omneum's evaluation results and the application's shared selection policy, not by an LLM.

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

The workflow runs inside `RoutingAgent._run_async_impl()`:

```text
Retrieve observations
        ↓
Evaluate with Omneum
        ↓
Assess evidence
        ├── diversify_sources ──┐
        ├── retrieve_support ───┤
        ├── resolve_conflicts ──┤
        │                       ↓
        │                Retrieve + reevaluate
        │                       │
        ├── generate ←──────────┘
        └── escalate
```

The implementation reuses the routing policy, retrieval strategies, and context selector from [`examples/langgraph/routing`](../langgraph/routing/).

| Scenario | Trigger | Retrieval action |
|---|---|---|
| `diversify_sources` | Insufficient independent support | Retrieve evidence from additional sources |
| `retrieve_support` | Missing or insufficient support | Retrieve evidence for affected attributes |
| `resolve_conflicts` | Competing claim values | Retrieve evidence to resolve the conflict |

The application selects claims using claim support, estimated independent support, and competing-claim evidence. The default policy requires:

| Parameter | Value |
|---|---:|
| Minimum independent support | 1.9 |
| Minimum winner/runner-up support ratio | 2.0 |
| Maximum retrieval attempts | 2 |

Claims that fail selection remain in the evaluation results but are excluded from the final context. Exhausted retrieval attempts result in escalation.

## Results

Recorded from the deterministic routing example on Python 3.13:

| Scenario | Observations | Routing history | Retries |
|---|---|---|---:|
| `diversify_sources` | 17 → 18 | `diversify_sources → generate` | 1 |
| `retrieve_support` | 11 → 14 | `retrieve_support → retrieve_support → generate` | 2 |
| `resolve_conflicts` | 9 → 12 | `resolve_conflicts → generate` | 1 |

All three scenarios selected:

```text
Application decision: EVALUATION COMPLETE
Selected context:
input_data_policy: redacted customer content only
provider_retention: 0 days
processing_region: EU
```

The six framework routing examples produced matching observation counts, routing histories, claim support, independent support, and final selections.

## Configuration

| Setting | Description |
|---|---|
| `GOOGLE_ADK_MODEL` | Enterprise model; defaults to `gemini-2.5-flash` |
| `GOOGLE_API_KEY` | Gemini API credentials |
| `GOOGLE_GENAI_USE_VERTEXAI` | Selects Gemini API or Vertex AI |
| `GOOGLE_CLOUD_PROJECT` | Vertex AI project |
| `GOOGLE_CLOUD_LOCATION` | Vertex AI location |
| `OMNEUM_CONFIG_DIR` | Local Omneum deployment configuration |
| `OMNEUM_DAEMON_SOCKET` | Local Omneum daemon socket |

The enterprise agent requires Gemini API credentials or configured Vertex AI authentication. The deterministic routing example requires neither.

## Tests

```bash
uv run --locked --python 3.13 --group google-adk \
  -m pytest -q tests/test_google_adk_routing.py
```

**18 passed.** Tests cover ADK Runner execution, MCP evaluation, conditional routing, retrieval, claim selection, retry exhaustion, and escalation.

The enterprise Runner was validated against the live Gemini API using `gemini-3.8-flash`, including a real Omneum MCP evaluation and model-generated response.

## Files

| Path | Description |
|---|---|
| [`agent.py`](agent.py) | Enterprise agent and evaluation tool |
| [`run.py`](run.py) | Enterprise agent entry point |
| [`routing/workflow.py`](routing/workflow.py) | Custom ADK routing agent |
| [`routing/state.py`](routing/state.py) | Routing and evaluation state |
| [`routing/run.py`](routing/run.py) | Scenario CLI |
| [`../../tests/test_google_adk_routing.py`](../../tests/test_google_adk_routing.py) | Integration tests |
| [`../langgraph/routing/`](../langgraph/routing/) | Shared routing policy and retrieval |
| [`../enterprise/`](../enterprise/) | Shared enterprise retrieval and MCP deployment |

## Documentation

- [Google ADK](https://google.github.io/adk-docs/)
- [Custom agents](https://google.github.io/adk-docs/agents/custom-agents/)
- [Function tools](https://google.github.io/adk-docs/tools-custom/function-tools/)
- [Omneum enterprise example](../enterprise/README.md)