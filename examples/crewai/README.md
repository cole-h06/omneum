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

CrewAI currently requires Python 3.10–3.13.

Install the project and development dependencies.

```bash
pip install -r requirements-dev.txt
```

## Run

```bash
python -m examples.crewai.run
```

## Files

- `flow.py` — CrewAI Flow definition
- `state.py` — shared workflow state
- `run.py` — entry point
