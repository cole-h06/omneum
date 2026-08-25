# OpenAI Agents SDK

This example integrates Omneum into an OpenAI Agents SDK workflow.

It reuses the enterprise workflow from `examples/enterprise`. Only the
orchestration changes. Because the shared enterprise workflow intentionally uses
Omneum's lower-level `client.evaluate_assertion()` interface, this example
passes `Observation` objects through the same evaluation path.

Applications can instead use `client.evaluate()` with normalized
`StructuredAssertion` objects, or `client.evaluate_mapped()` with a
`ContextMapper` for existing retrieval or tool output.

## Flow

- Invoke the retrieval tool.
- Collect the retrieved observations.
- Submit the observations to Omneum.
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

- `agent.py` — agent and Omneum tool definition
- `run.py` — entry point