# OpenAI Agents SDK

This example integrates Omneum into an OpenAI Agents SDK workflow.

It uses the enterprise workflow from `examples/enterprise` as its retrieval
scenario, then maps the retrieved results through `ContextMapper` before
evaluation. The OpenAI Agents SDK provides the orchestration.

## Flow

- Invoke the retrieval tool.
- Collect the retrieved observations.
- Submit the observations to Omneum.
- Generate the final response from the returned assertion evaluation.

## Requirements

- Python 3.11–3.14
- An `OPENAI_API_KEY`
- Project and development dependencies

From the repository root, install the dependencies with uv 0.12.10:

```bash
uv sync --locked --group openai-agents
```

Export your OpenAI API key:

```bash
export OPENAI_API_KEY=<your-api-key>
```

## Run

```bash
uv run --locked --group openai-agents -m examples.openai_agents.run
```

## Files

- `agent.py` — agent and Omneum tool definition
- `run.py` — entry point