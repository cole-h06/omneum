# OpenAI Agents SDK

This example integrates Verity into an OpenAI Agents SDK workflow.

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
- Project and development dependencies

Install the dependencies:

```bash
pip install -r requirements-dev.txt
```

Export your OpenAI API key:

```bash
export OPENAI_API_KEY=<your-api-key>
```

## Run

```bash
python -m examples.openai_agents.run
```

## Files

- `agent.py` — agent and Verity tool definition
- `run.py` — entry point