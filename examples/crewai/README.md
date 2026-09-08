# CrewAI

This example integrates Omneum into a CrewAI Flow.

It reuses the enterprise workflow from `examples/enterprise`. Only the
orchestration changes.

## Flow

- Execute the retrieval steps in parallel.
- Merge the retrieved observations.
- Submit the observations to Omneum.
- Generate the final response from the assertion evaluation.

## Requirements

Use Python 3.11–3.13 for this Omneum example; CrewAI excludes Python 3.14.

From the repository root, install the locked environment with uv 0.12.10:

```bash
uv sync --locked --python 3.13 --group crewai
```

## Run

```bash
uv run --locked --python 3.13 --group crewai -m examples.crewai.run
```

## Files

- `flow.py` — CrewAI Flow definition
- `state.py` — shared workflow state
- `run.py` — entry point
