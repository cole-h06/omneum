# Enterprise

This example integrates Omneum into an enterprise AI application that retrieves information from multiple internal and external sources.

The application answers the question:

> May the EU Customer Support Copilot send unredacted customer-ticket content to
> the approved hosted model in production? What provider-retention and
> processing-region settings are required?

Five retrieval agents collect structured observations from enterprise systems such as governance documents, deployment records, live configuration, generated reports, and vendor documentation.

This workflow intentionally uses Omneum's lower-level `client.evaluate_assertion()` interface, supplying `Observation` objects directly. Applications that already normalize information into `StructuredAssertion` objects can instead use `client.evaluate()`. Existing retrieval or tool outputs can be adapted through `client.evaluate_mapped()` and a `ContextMapper`.

Omneum evaluates:

- Which claims are most strongly supported
- Where retrieved information conflicts
- Which sources appear dependent
- Source reliability and claim support

For reproducibility purposes, the retrieval agents are simulated with simple Python functions. They do not call an LLM or access the network.

## Requirements

From the repository root, install the locked environment with uv 0.12.10:

```bash
uv sync --locked
```

## Run

```bash
uv run --locked -m examples.enterprise.workflow.run
```

This example creates a temporary local stdio deployment using a deterministic, example-only VOPRF key. The temporary key is removed when the workflow exits and must never be used in production.

## Output

Representative output:

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

## Related examples

The enterprise workflow is reused by the framework integrations.

- `examples/langgraph`
- `examples/crewai`
- `examples/openai_agents`
