# LangGraph

This example integrates Omneum into a LangGraph workflow.

It reuses the enterprise workflow from `examples/enterprise`. Only the
orchestration changes.

## Flow

- Execute the retrieval nodes in parallel.
- Merge the retrieved observations.
- Submit the observations to Omneum.
- Generate the final response from the assertion evaluation.

## Requirements

Install the project and development dependencies.

```bash
pip install -r requirements-dev.txt
```

## Run

```bash
python -m examples.langgraph.run
```

## Files

- `graph.py` — graph definition
- `nodes.py` — retrieval and Omneum nodes
- `state.py` — shared graph state
- `run.py` — entry point
