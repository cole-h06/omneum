# Enterprise

This example integrates Omneum into an enterprise AI application that retrieves information from multiple internal and external sources.

The application answers the question:

> May the EU Customer Support Copilot send unredacted customer-ticket content to
> the approved hosted model in production? What provider-retention and
> processing-region settings are required?

Five retrieval agents collect structured observations from enterprise systems such as governance documents, deployment records, live configuration, generated reports, and vendor documentation.

Omneum evaluates:

- Which claims are most strongly supported
- Where retrieved information conflicts
- Which sources appear dependent
- Source reliability and claim support

The retrieval agents are simple Python functions. They do not call an LLM or access the network.

## Requirements

Install the project and development dependencies.

```bash
pip install -r requirements-dev.txt
```

## Run

```bash
python -m examples.enterprise.workflow.run
```

The example creates a temporary local stdio deployment using a deterministic, example-only VOPRF key. The temporary key is removed when the workflow exits and must never be used in production.

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
