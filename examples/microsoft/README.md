# Microsoft Agent Framework

This example integrates Verity into a Microsoft Agent Framework agent.

It reuses the enterprise workflow from `examples/enterprise`. Only the
orchestration changes.

## Flow

- Invoke the retrieval tool.
- Collect the retrieved observations.
- Submit the observations to Verity.
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
python -m examples.microsoft_agent_framework.run
```

## Files

- `agent.py` — Microsoft Agent Framework agent and Verity tool definition
- `run.py` — entry point