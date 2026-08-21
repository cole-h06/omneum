# Omneum

Omneum is an open-source data trust gateway for agentic systems. It evaluates retrieved information across sources before that context reaches the next model call. Think of it as a fast, lightweight reliability layer that sits between data sources and language models to ground your agents in trusted information.

## 🧠 Why Omneum?

In modern agentic workflows, context is built from multiple retrievals and tool calls. Different sources can conflict, repeat the same information, or appear to agree while depending on the same upstream source. Provenance can also get lost across multi-step execution paths.

Omneum evaluates context quality before it gets passed to the model and can be integrated directly into your existing retrieval or orchestration stack.

Main features include:

- **Preserve provenance** - Preserve source metadata and relationships across retrieval and tool execution.

- **Surface conflicts** - Detect and surface contradictory values before they enter the context window of the next model call.

- **Score context quality** - Evaluate context quality based on the independence of its supporting sources without adding extra model calls.

- **Privacy-preserving linkage** - Recognize matching private values across separate tools while keeping your data private and secure using local VOPRF-blinded tokens.

## Performance

| | Dependency precision | Dependency recall | Evaluation latency | LLM tokens |
|---|---:|---:|---:|---:|
| **Omneum** | **100.0%** | 77.8% | **13.5 ms** | **0** |
| LLM-as-Judge | 81.8% | **100.0%** | 4.7 s | 5,576 |
| Naive Vector RAG | — | — | 5.2 s | 5,093 |

*Results across three real-world financial dependency cases. See [`benchmarks/financial_dependency_suite`](benchmarks/financial_dependency_suite) for methodology and reproducibility notes.*

## 🚀 Quickstart

**Note:** This tutorial assumes a Python-based agentic application.

### 1. Installation

To get started with Omneum, create and activate a virtual environment:

```bash
python3.14 -m venv .venv
source .venv/bin/activate
```

Install Omneum from the repository:

```bash
pip install .
```

### 2. Initialize Omneum

Initialize a local deployment:

```bash
omneum init
```

This will automatically create the local configuration and cryptographic key material required for running the Omneum server.

### 3. Connect to the MCP Server

For local testing, Omneum runs as an MCP server over `stdio`. Connect to your local deployment with the SDK:

```python
from mcp import StdioServerParameters

from omneum import OmneumClientConfig, open_stdio_client

config = OmneumClientConfig.from_local_deployment()

server = StdioServerParameters(
    command="omneum-server",
)
```

The SDK uses this configuration when it opens an MCP connection to your local deployment.

### 4. Evaluate Context

Map your retrieved data and tool outputs into Omneum `Observation` objects with their available provenance and retrieval metadata. Pass them to the client for evaluation:

```python
from datetime import datetime, timezone

from omneum import (
    Claim,
    DependencyEstimatorConfig,
    Observation,
    Retrieval,
    Source,
    SourceReference,
)

now = datetime.now(timezone.utc)

estimator = DependencyEstimatorConfig(
    upstream_weight=0.25,
    citation_weight=0.20,
    assertion_lineage_weight=0.20,
    ownership_weight=0.10,
    temporal_weight=0.10,
    graph_weight=0.15,
    retrieval_weight=0.25,
    temporal_window_seconds=172_800.0,
)

research_service = Source(
    kind="internal_service",
    identifier=(
        "v1:01234567-89ab-4def-8123-456789abcdef:"
        "22222222-2222-4333-8444-555555555555"
    ),
)

analytics_service = Source(
    kind="internal_service",
    identifier=(
        "v1:01234567-89ab-4def-8123-456789abcdef:"
        "33333333-2222-4333-8444-555555555555"
    ),
)

analytics_reference = SourceReference(
    kind="internal_service",
    identifier=(
        "v1:01234567-89ab-4def-8123-456789abcdef:"
        "33333333-2222-4333-8444-555555555555"
    ),
)

observations = [
    Observation(
        assertion_id="result-1",
        source=research_service,
        claim=Claim(
            entity_namespace="service",
            entity="payment_api",
            attribute="status_code",
            value=200,
        ),
        observed_at=now,
        upstream_sources=(analytics_reference,),
        retrievals=(
            Retrieval(
                retrieval_id="retrieval-1",
                kind="tool_call",
                resource_id="research-api",
                retrieved_at=now,
            ),
        ),
    ),
    Observation(
        assertion_id="result-2",
        source=analytics_service,
        claim=Claim(
            entity_namespace="service",
            entity="payment_api",
            attribute="status_code",
            value=200,
        ),
        observed_at=now,
        retrievals=(
            Retrieval(
                retrieval_id="retrieval-2",
                kind="tool_call",
                resource_id="analytics-api",
                retrieved_at=now,
            ),
        ),
    ),
]

async with open_stdio_client(config, server) as client:
    result = await client.evaluate_assertion(
        observations,
        estimator=estimator,
    )
```

Both observations report the same value, but the research service identifies the analytics service as an upstream source. `evaluate_assertion()` uses that relationship when estimating how much independent support the claim actually has.

### 5. Handle the Result

Integrate the structured evaluation signals directly in your orchestration logic:

```python
for claim in result.claim_support:
    print("Support:", claim.support)
    print("Independent support:", claim.estimated_independent_support_count)
    print("Conflicts:", claim.conflicting_claims)
```

Omneum also provides short natural language explanations via the SDK. Use the structured signals to drive routing and control flow, or add an explanation to the context passed into the next model call.

## 🔌 How It Fits

Omneum runs between retrieval and the subsequent model call in your agent workflow.

```text
Retrieval / Tool Calls
        ↓
Retrieved Context
        ↓
Omneum Evaluation
        ↓
Structured Signals + Explanations
        ↓
Application Logic
        ↓
Next Model Call
```

Your application always stays in control of the execution path. Omneum uses retrieved context for evaluation and returns signals that your workflow can act on before continuing.

## 📦 Observation Model

Omneum evaluates `Observation` objects built from information surfaced during retrieval and tool execution. Each observation associates a structured `Claim` with the source that produced it and preserves the provenance available at that point in the agent run.

A `Claim` represents an individual piece of retrieved information as:

```text
entity + attribute + value
```

For example:

```text
acme-corp + quarterly_revenue_usd + 42000000
payment_api + status + healthy
```

The surrounding `Observation` records where that claim came from and how it entered the workflow. It can also preserve retrieval metadata and known relationships to other sources or earlier assertions.

Omneum uses these relationships when evaluating support across the observations in the current agent run. If provenance isn't available for a particular source, the application does not need to reconstruct it before evaluation.

See [`sdk.md`](docs/sdk.md#observation-model) for the full observation model and [`Source Relationships`](docs/sdk.md#source-relationships) for upstream sources, citations, assertion lineage, and source ownership.

## 🕸️ Dependency Estimation

In many cases, multiple tool results can appear to support the same claim independently even when they trace back to the same underlying source. Omneum estimates dependency between those sources before calculating claim support.

The estimator uses metadata already captured during execution. For example, two observations may reference the same upstream source or come from sources under the same owner. Retrieval timing and structural overlap can provide additional signals when that metadata is available.

When metadata is missing, Omneum works with the signals available in the current run rather than requiring your application to reconstruct provenance.

See [`sdk.md`](docs/sdk.md#dependency-estimation) for more detail on dependency estimation, including the available signals and configuration options.

## 🔒 Privacy

Omneum uses an RFC 9497 VOPRF with the `ristretto255-SHA512` ciphersuite to create stable linkage tokens without sending the underlying source, entity, attribute, or claim values to the server.

The SDK handles blinding, proof verification, finalization, and token encoding locally. The private values used to construct linkage tokens never leave the client in plaintext.

The server can still observe protocol traffic and the opaque relationships submitted for evaluation. VOPRF protects the underlying values; it does not make the entire evaluation request invisible to the server.

## 📚 Documentation

The Quickstart above is enough to get a local integration running. More detailed documentation is available for each part of the integration:

- [`sdk.md`](docs/sdk.md) — Build `Observation` objects, configure dependency estimation, inspect evaluation results, and integrate them into agent control flow.
- [`api.md`](docs/api.md) — Reference for the assertion-evaluation contract, request and response schemas, validation behavior, server limits, and error handling.
- [`protocol.md`](docs/protocol.md) — MCP transport and deployment behavior, including the VOPRF request flow.
- [`canonicalization.md`](docs/canonicalization.md) — Deterministic canonicalization and serialization rules used to construct linkage inputs.
- [`examples/`](examples/) — End-to-end examples of Omneum inside agent workflows.

## 🧪 Status

Omneum is currently in an early design-partner release. The SDK and integration may change as it is tested in production agent workflows. As an open-source AI infrastructure project, we gladly welcome any contributions or feedback.

## 📄 License

See [`LICENSE`](LICENSE) for license information.