# Enterprise Context Preparation

Enterprise retrieval and context-preparation example using Omneum's Python SDK. Five retrieval modules load policy documents, database records, API responses, and vendor documentation. Omneum evaluates retrieved evidence through provenance-aware graph inference, then selects passages using BM25 query relevance and incremental claim coverage under a configured context budget.

The example evaluates the question:

> May the EU Customer Support Copilot send unredacted customer-ticket content to the approved hosted model in production? What provider-retention and processing-region settings are required?

## Quick Start

From the repository root:

```bash
.venv/bin/python -m examples.enterprise.workflow.run
```

Inspect the selected context and generation messages:

```bash
.venv/bin/python -m examples.enterprise.workflow.run \
  --inspect-context \
  --include-context
```

Compare Omneum with Raw RAG under the same context budget:

```bash
.venv/bin/python -m examples.enterprise.workflow.run \
  --compare \
  --token-budget 600
```

Print structured context-preparation results as JSON:

```bash
.venv/bin/python -m examples.enterprise.workflow.run \
  --inspect-context \
  --json \
  --include-context
```

The workflow uses six fixed evidence records from `data/` and a local Omneum MCP connection over stdio.

## Architecture

Five retrieval modules collect six records from [`data/`](data/).

| Module | Evidence |
|---|---|
| [`agents/documents.py`](agents/documents.py) | AI data-governance policy and stale deployment runbook |
| [`agents/sql.py`](agents/sql.py) | Model registry |
| [`agents/api.py`](agents/api.py) | AI gateway configuration |
| [`agents/research.py`](agents/research.py) | Copilot readiness brief |
| [`agents/search.py`](agents/search.py) | Vendor enterprise data controls |

Each module produces structured `Observation` objects associating a `Source` with a `Claim`. Source and observation metadata supply the dependency estimator with upstream, citation, lineage, and temporal information.

[`workflow/retrieval.py`](workflow/retrieval.py) maps those observations to the original records:

```python
from examples.enterprise.workflow.run import collect_observations
from examples.enterprise.workflow.retrieval import collect_chunks

observations = collect_observations()
chunks = collect_chunks(observations)
```

Each `RetrievedChunk` contains:

| Field | Description |
|---|---|
| `chunk_id` | Identifier derived from the source filename |
| `raw_text` | Original record content |
| `source` | Associated Omneum `Source` |
| `observation_ids` | Observation identifiers associated with the record |
| `claim_ids` | Canonical claims represented by the record |

`validate_chunks()` checks the observation-to-source mappings and ensures every observation is represented by a retrieved chunk.

The execution path is:

```text
Enterprise retrieval modules
         |
         v
  collect_observations()
         |
         +----------------------+
         |                      |
         v                      v
    Observations         collect_chunks()
         |                      |
         |                 Original text
         |                 Claim mappings
         +-----------+----------+
                     |
                     v
            prepare_generation()
                     |
                     v
         OmneumClient.prepare_context()
                     |
                     v
         Source–claim graph inference
         Dependency-adjusted support
                     |
                     v
         Query-conditioned selection
         Budgeted context packing
                     |
                     v
              Context assembly
                     |
                     v
            Generation messages
```

## Omneum's Algorithm

Omneum's algorithm constructs a bipartite graph of sources and claims. Each observation connects a source to an asserted value for an entity and attribute.

Source reliability and claim support are computed iteratively while adjusting for estimated source dependencies, reducing the influence of repeated evidence derived from common upstream sources.

The resulting claim scores are mapped to retrieved passages through `claim_ids`. Chunk selection incorporates BM25 query relevance and the additional claim coverage contributed by each candidate.

Selected passages are ordered and packed within the configured context budget. The SDK assembles their original text with source references into the generation context.

### Dependency Estimation

The enterprise example configures the estimator in [`workflow/run.py`](workflow/run.py):

```python
from examples.enterprise.workflow.run import estimator_config

estimator = estimator_config()
```

| Signal | Weight |
|---|---:|
| Upstream | 25 |
| Citation | 20 |
| Assertion lineage | 20 |
| Ownership | 10 |
| Temporal | 10 |
| Graph redundancy | 15 |

The estimator uses a 172,800-second temporal window and a dependency cluster threshold of `0.4`.

The fixtures include a Copilot readiness brief derived from a stale deployment runbook. The model registry and AI gateway also contain assertions related to the governance policy. The dependency estimator uses these relationships to adjust source contributions during claim-support propagation.

### Claim Support

Omneum evaluates the complete observation set before selecting passages for the model context.

For each claim, Omneum computes relative support and estimated independent support. Competing values for the same entity and attribute remain separate claims.

The enterprise fixture includes conflicts concerning customer-data handling, provider retention, and processing region.

| Attribute | Competing values |
|---|---|
| `input_data_policy` | Redacted customer content only / Unredacted customer content allowed |
| `provider_retention` | 0 days / 30 days |
| `processing_region` | EU / US |

Estimated independent support accounts for dependencies among sources supporting the same claim.

### Chunk Selection

The policy question is passed to the SDK as the query.

Chunk utility incorporates BM25 relevance and graph-derived claim support. Incremental coverage adjusts a candidate's utility according to the claims already represented by selected passages.

The SDK packs passages within the configured budget and returns their identifiers in rendering order.

### Context Assembly

The assembled context contains the selected passages in rendering order, with source references preserved.

The preparation output includes `packed_chunk_ids`, the assembled context, and generation messages. Passages omitted during selection are absent from the final model input.

Original record text remains in the SDK's retrieved chunks. The MCP graph evaluator operates on structured observations and provenance metadata.

## Python API

[`workflow/run.py`](workflow/run.py) exposes `prepare_workflow()`:

```python
import asyncio

from examples.enterprise.workflow.run import prepare_workflow

generation = asyncio.run(
    prepare_workflow(token_budget=600)
)

print(generation["packed_chunk_ids"])
print(generation["messages"][1]["content"])
```

The workflow collects observations and passes them to the shared preparation helper:

```python
return await prepare_generation(
    observations,
    chunks=collect_chunks(observations),
    question=QUESTION,
    estimator=estimator_config(),
    token_budget=token_budget,
    preparation=preparation,
    config=config,
    server=server,
)
```

`prepare_generation()` invokes the production `OmneumClient.prepare_context()` API.

`GenerationInput` contains the graph evaluation and prepared generation payload:

| Field | Description |
|---|---|
| `generation["evaluation"]` | Source–claim evaluation results |
| `generation["retrieved_chunks"]` | Retrieved candidate passages |
| `generation["prepared_context"]` | Context selection and assembly results |
| `generation["packed_chunk_ids"]` | Selected passage identifiers in rendering order |
| `generation["messages"]` | Model-ready generation messages |
| `generation["query_diagnostics"]` | Query relevance diagnostics |
| `generation["comparison"]` | Raw RAG comparison when enabled |
| `generation["telemetry"]` | Available execution measurements |

The existing `run_workflow()` wrapper returns the evaluation and assembled user message:

```python
from examples.enterprise.workflow.run import run_workflow

evaluation, user_message = asyncio.run(
    run_workflow(token_budget=600)
)
```

Both entry points use the same preparation implementation.

## Raw RAG Comparison

The `--compare` option evaluates the same retrieved candidate pool under an identical context budget.

```bash
.venv/bin/python -m examples.enterprise.workflow.run \
  --compare \
  --token-budget 600
```

The CLI reports the source–claim graph evaluation and the passages selected by each strategy.

Each selection reports rendering order, budget consumption, claim coverage, and excluded passages.

A recorded local execution produced:

| Measurement | Raw RAG | Omneum |
|---|---:|---:|
| Selected context units | 534 | 558 |
| Context budget | 600 | 600 |
| Distinct claims covered | 6/6 | 3/6 |

**Raw RAG selected:**

```text
ai_data_governance_policy
copilot_deployment_runbook
copilot_readiness_brief
```

**Omneum selected:**

```text
ai_data_governance_policy
model_registry
ai_gateway
vendor_data_controls
```

The claim coverage metric counts distinct claim values, including conflicting assertions. Omneum's selected context concentrated on the three supported policy values in this fixture.

The source–claim evaluation remains available through `generation["evaluation"]`, regardless of which passages are selected.

## Inspection

The enterprise CLI uses the shared output implementation in [`examples/context_output.py`](../context_output.py).

| Option | Behavior |
|---|---|
| `--token-budget N` | Set the context budget |
| `--inspect-context` | Inspect context preparation |
| `--compare` | Include Raw RAG comparison |
| `--json` | Emit structured JSON |
| `--include-context` | Include original passages and generation messages in JSON |
| `--include-telemetry` | Include available execution measurements |
| `--collect-telemetry` | Enable SDK telemetry collection |
| `--telemetry-format json\|human` | Select execution-log format |
| `--telemetry-log-file PATH` | Write execution logs to a file |

For machine-readable inspection:

```bash
.venv/bin/python -m examples.enterprise.workflow.run \
  --inspect-context \
  --json \
  --include-context \
  --token-budget 600
```

JSON output includes the retrieved chunk pool, selected identifiers, rendering order, evaluation diagnostics, and preparation configuration.

The `--include-context` flag enables original passage text and generation messages in JSON output.

The budget measures Unicode word/punctuation units in the assembled context, including chunk headers. It is separate from a model provider's token accounting.

## Execution Telemetry

```bash
.venv/bin/python -m examples.enterprise.workflow.run \
  --inspect-context \
  --collect-telemetry \
  --include-telemetry \
  --telemetry-format human
```

Available measurements include SDK execution duration, graph evaluation latency, MCP round-trip latency, chunk selection latency, reconstruction latency, CPU time, and peak SDK process memory.

The execution output also records input and selected context units.

Structured execution logs can be written to a file:

```bash
.venv/bin/python -m examples.enterprise.workflow.run \
  --inspect-context \
  --collect-telemetry \
  --telemetry-format json \
  --telemetry-log-file execution.jsonl
```

With local persistence configured, the SDK can associate execution history with the corresponding graph evaluation run.

## Local Deployment

The workflow uses [`config.py`](config.py) to resolve the local Omneum deployment.

```python
from examples.enterprise.config import example_deployment

with example_deployment() as (config, server):
    ...
```

The deployment uses `OmneumClientConfig.from_local_deployment()` and starts the MCP server over stdio using `python -m omneum.server`.

Local persistence stores graph evaluations and context-preparation execution records. The default SQLite database resides in Omneum's application-data directory.

## Using Real Retrieval

Replace the fixture-backed functions in [`agents/`](agents/) with retrieval functions backed by your document stores, databases, or APIs.

The integration requires structured `Observation` objects and corresponding retrieved chunks. Each chunk must preserve its source association and the identifiers connecting it to the observed claims.

The same preparation entry point accepts those records:

```python
generation = await prepare_generation(
    observations,
    chunks=chunks,
    question=question,
    estimator=estimator_config(),
    token_budget=600,
)
```

`ContextMapper` maps structured retrieval results into Omneum `Observation` objects.

The calling agent workflow passes `generation["messages"]` to its configured model interface.

## Files

| Path | Implementation |
|---|---|
| [`workflow/run.py`](workflow/run.py) | Retrieval aggregation, estimator configuration, preparation entry point, CLI |
| [`workflow/retrieval.py`](workflow/retrieval.py) | Original-text chunks and observation mapping |
| [`workflow/generate.py`](workflow/generate.py) | Generation message construction and source references |
| [`config.py`](config.py) | Local MCP deployment configuration |
| [`agents/`](agents/) | Enterprise retrieval modules |
| [`data/`](data/) | Deterministic evidence fixtures |
| [`../context_preparation.py`](../context_preparation.py) | Shared SDK preparation integration |
| [`../context_output.py`](../context_output.py) | Shared inspection and CLI output |

## Framework Integrations

The enterprise evidence fixtures and context-preparation interfaces are also used by:

- [LangGraph](../langgraph/)
- [LlamaIndex](../llamaindex/)
- [CrewAI](../crewai/)
- [OpenAI Agents SDK](../openai_agents/)
- [Google ADK](../google_adk/)
- [Microsoft Agent Framework](../microsoft/)