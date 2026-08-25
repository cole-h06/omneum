# Microsoft Agent Framework

This example integrates Omneum into a Microsoft Agent Framework agent.

It reuses the lower-level enterprise workflow from `examples/enterprise`, where
retrieval results are represented as `Observation` objects and evaluated through
`client.evaluate_assertion()`. Only the orchestration changes.

Applications integrating existing Microsoft Agent Framework tool outputs can
instead adapt those outputs through `client.evaluate_mapped()` and a
`ContextMapper`.

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