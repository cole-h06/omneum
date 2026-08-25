# LangGraph

This example integrates Omneum into a LangGraph workflow.

It reuses the lower-level enterprise workflow from `examples/enterprise`, where
retrieval results are represented as `Observation` objects and evaluated through
`client.evaluate_assertion()`. Only the orchestration changes.

Applications integrating existing LangGraph retrieval or tool outputs can
instead adapt those outputs through `client.evaluate_mapped()` and a
`ContextMapper`.

## Flow

- Execute the retrieval nodes in parallel.
- Merge the retrieved observations.
- Submit the observations through the enterprise workflow's Omneum evaluation path.
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
