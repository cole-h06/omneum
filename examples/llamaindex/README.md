# LlamaIndex

This example integrates Omneum into a LlamaIndex Workflow.

It reuses the enterprise workflow from `examples/enterprise`. Only the
orchestration changes.

## Flow

- Execute the retrieval workflow.
- Collect the retrieved observations.
- Submit the observations to Omneum.
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