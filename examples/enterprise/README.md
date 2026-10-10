# Enterprise policy evaluation

This example evaluates conflicting evidence about an enterprise AI deployment using Omneum's MCP server.

The application answers:

> May the EU Customer Support Copilot send unredacted customer-ticket content to the approved hosted model in production? What provider-retention and processing-region settings are required?

## Architecture

Five retrieval modules collect evidence from local fixtures:

| Module | Evidence |
|---|---|
| `agents/documents.py` | AI data-governance policy and stale deployment runbook |
| `agents/sql.py` | Model registry |
| `agents/api.py` | AI gateway configuration |
| `agents/research.py` | Copilot readiness brief |
| `agents/search.py` | Vendor enterprise data controls |

The retrieval modules produce `Observation` objects linking a `Source` to a `Claim`.

```python
from omneum import Claim, Observation, Source
```

Each observation identifies the source asserting a value for a particular entity and attribute. Provenance annotations provide evidence for estimating dependencies between sources.

The workflow in `workflow/run.py` collects the observations and evaluates them through the MCP stdio client:

```python
async with open_stdio_client(config, server) as client:
    result = await client.evaluate_context(
        collect_observations(),
        estimator=estimator_config(),
    )
```

The retrieval fixtures are deterministic. They do not invoke an LLM or make network requests.

## Evaluation

Omneum constructs a source–claim graph from the observations and evaluates the evidence using BRAID.

The evaluation computes:

- **Source reliability:** numerical reliability scores for sources participating in the evaluation.
- **Claim support:** numerical support scores for asserted values.
- **Source dependency:** estimated dependence between sources based on available provenance signals.
- **Independent support:** estimated effective source count after accounting for dependencies.
- **Conflicts:** competing values asserted for the same entity and attribute.

The example includes two provenance relationships relevant to the evaluation:

- The Copilot readiness brief derives from the stale deployment runbook.
- The model registry and AI gateway contain assertions related to the governance policy.

These relationships affect how much independent evidence the evaluation attributes to each claim. Multiple retrieved documents do not automatically count as independent confirmation.

## Run

From the repository root, using the project virtual environment:

```bash
.venv/bin/python -m examples.enterprise.workflow.run
```

The workflow starts Omneum's MCP server over stdio using the local deployment configuration in `examples/enterprise/config.py`.

The evaluation uses the configured local persistence backend. The default SQLite database is stored in the application-data directory.

## Output

The workflow prints the application decision, source reliability scores, claim explanations, and pairwise source dependencies.

The application selects the highest-supported value for each required attribute. Missing evidence produces an escalation decision; tied leading claims produce a request for additional evidence.

A successful evaluation produces:

```text
Application decision: EVALUATION COMPLETE
Highest-supported claims:
input_data_policy: redacted customer content only (support 0.0373, independent support 1.00)
provider_retention: 0 days (support 0.1078, independent support 2.00)
processing_region: EU (support 0.1078, independent support 2.00)
```

The evaluation also retains competing claims:

| Attribute | Claim | Support | Independent support |
|---|---|---:|---:|
| Input data policy | Redacted customer content only | 0.0373 | 1.00 |
| Input data policy | Unredacted customer content allowed | ~0.01 | 1.00 |
| Provider retention | 0 days | 0.1078 | 2.00 |
| Provider retention | 30 days | ~0.01 | 1.00 |
| Processing region | EU | 0.1078 | 2.00 |
| Processing region | US | ~0.01 | 1.00 |

The retention claim is supported by four retrieved sources, with an estimated independent support count of `2.00`. Omneum discounts correlated evidence rather than treating all four sources as independent.

The `30 days` claim remains in the evaluation as conflicting evidence.

Claim support scores represent relative evidence support, not calibrated probabilities. The application's selection logic does not itself authorize a production deployment.

### Source dependencies

The output includes dependency explanations for source pairs with detected relationships.

For example:

```text
AI data-governance policy ↔ Model registry

Independence: 0.00

• Direct citation
• 3 derived assertions
• Updated 23 hours apart
• 3 matching claims
```

These explanations expose the provenance signals contributing to the dependency estimate.

## Using real retrieval

Replace the fixture-backed retrieval functions in `agents/` with application-specific retrieval or tool calls.

The evaluation boundary remains the same:

```python
result = await client.evaluate_context(
    observations,
    estimator=estimator_config(),
)
```

Applications with structured tool output can use `ContextMapper` and `client.evaluate_mapped(...)` instead of constructing every observation directly.

The application is responsible for mapping retrieved records into sources, claims, and provenance annotations. Omneum evaluates the resulting evidence; it does not perform entity resolution or determine deployment authorization.

## Framework examples

The same enterprise workflow is integrated with:

- [`examples/langgraph`](../langgraph)
- [`examples/crewai`](../crewai)
- [`examples/openai_agents`](../openai_agents)