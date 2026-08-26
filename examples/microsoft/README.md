# Microsoft Agent Framework

This example integrates Omneum into a Microsoft Agent Framework agent.

It uses the enterprise workflow from `examples/enterprise` as its retrieval
scenario, then maps the retrieved results through `ContextMapper` before
evaluation. The Microsoft Agent Framework agent provides the orchestration.

## Flow

- Invoke the retrieval tool.
- Collect the retrieved observations.
- Submit the observations through the enterprise workflow's Omneum evaluation path.
- Generate the final response from the returned assertion evaluation.

## Requirements

- Python 3.10 or newer
- An `OPENAI_API_KEY`
- An `OPENAI_MODEL`
- Project and development dependencies

Install the dependencies:

```bash
pip install -r requirements-dev.txt
```

Export your OpenAI credentials:

```bash
export OPENAI_API_KEY=<your-api-key>
export OPENAI_MODEL=gpt-5.5
```

## Run

```bash
python -m examples.microsoft.run
```

## Files

- `agent.py` — Microsoft Agent Framework agent and Omneum tool definition
- `run.py` — entry point