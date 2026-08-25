# LlamaIndex

This example integrates Omneum into a LlamaIndex Workflow.

It reuses the lower-level enterprise workflow from `examples/enterprise`, where
retrieval results are represented as `Observation` objects and evaluated through
`client.evaluate_assertion()`. Only the orchestration changes.

Applications integrating existing LlamaIndex retrieval or tool outputs can
instead adapt those outputs through `client.evaluate_mapped()` and a
`ContextMapper`.

## Flow

- Execute the retrieval workflow.
- Collect the retrieved observations.
- Submit the observations through the enterprise workflow's Omneum evaluation path.
- Generate the final response from the returned assertion evaluation.

## Requirements

Install the project and development dependencies.

```bash
pip install -r requirements-dev.txt
```

## Run

```bash
python -m examples.llamaindex.run
```

## Files

- `workflow.py` — LlamaIndex Workflow definition
- `run.py` — entry point