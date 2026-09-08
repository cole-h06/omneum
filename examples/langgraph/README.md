# LangGraph

This example integrates Omneum into a LangGraph workflow.

It uses the enterprise workflow from `examples/enterprise` as its retrieval
scenario, then maps the retrieved results through `ContextMapper` before
evaluation. The LangGraph graph provides the orchestration.

## Flow

- Execute the retrieval nodes in parallel.
- Merge the retrieved observations.
- Submit the observations through the enterprise workflow's Omneum evaluation path.
- Generate the final response from the assertion evaluation.

## Requirements

From the repository root, install the locked environment with uv 0.12.10:

```bash
uv sync --locked --group langgraph
```

## Run

```bash
uv run --locked --group langgraph -m examples.langgraph.run
```

## Files

- `graph.py` — graph definition
- `nodes.py` — retrieval and Omneum nodes
- `state.py` — shared graph state
- `run.py` — entry point
