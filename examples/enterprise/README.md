# Enterprise policy evaluation

This example uses Omneum to resolve conflicting context about an enterprise AI deployment.

The application needs to answer:

> May the EU Customer Support Copilot send unredacted customer-ticket content to
> the approved hosted model in production? What provider-retention and
> processing-region settings are required?

## How it works

Five retrieval functions return context from governance documents, deployment
records, runtime configuration, generated reports, and vendor documentation.

Each result is represented as an Omneum `Observation` connecting a `Source` to
a `Claim`:

```python
Observation(
    source=Source(...),
    claim=Claim(...),
    ...
)
```

The application sends the observations to:

```python
evaluation = await client.evaluate_context(observations)
```

Omneum scores the sources and claims, estimates how much independent support
each claim has, and surfaces conflicting values.

The retrieval functions in this example are deterministic fixtures. They don't
call an LLM or make network requests, so the same source relationships can be
reproduced locally.

## Run

From the repository root:

```bash
uv sync --locked
uv run --locked -m examples.enterprise.workflow.run
```

The example starts a temporary stdio deployment and uses an example-only VOPRF
key. The key is deleted when the process exits and must not be reused outside
the example.

## Output

```text
Application conclusion
Customer content must be redacted.
Provider retention must be 0 days.
Processing must remain in the EU.

...

Provider retention = 0 days
Support: 0.19

Highest support

Supporting sources: 4
Independent support: 2.37

Conflicting value:
30 days (support 0.00)
```

Here, four retrieved sources support the `0 days` retention setting, but their
estimated independent support is `2.37`. Omneum doesn't treat every retrieved
source as an independent confirmation when their provenance indicates source
dependence.

The conflicting `30 days` value remains visible in the evaluation rather than
being silently discarded by retrieval.

## Using real retrieval

The example constructs `Source`, `Claim`, and `Observation` objects directly:

```python
from omneum import Claim, Observation, Source
```

Applications that already have structured retrieval or tool output can map it
into the same evaluation path with:

```python
await client.evaluate_mapped(...)
```

using a `ContextMapper`.

## Framework examples

The same enterprise workflow is used by:

- [`examples/langgraph`](../langgraph)
- [`examples/crewai`](../crewai)
- [`examples/openai_agents`](../openai_agents)