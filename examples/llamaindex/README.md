# LlamaIndex

This example integrates Omneum into a LlamaIndex Workflow.

It uses the enterprise workflow from `examples/enterprise` as its retrieval
scenario, then maps the retrieved results through `ContextMapper` before
evaluation. The LlamaIndex Workflow provides the orchestration.

## Flow

- Execute the retrieval workflow.
- Collect the retrieved observations.
- Submit the observations through the enterprise workflow's Omneum evaluation path.
- Generate the final response from the returned assertion evaluation.

## Requirements

From the repository root, install the locked environment with uv 0.12.10:

```bash
uv sync --locked --group llamaindex
```

## Run

```bash
uv run --locked --group llamaindex -m examples.llamaindex.run
```

## Files

- `workflow.py` — LlamaIndex Workflow definition
- `run.py` — entry point