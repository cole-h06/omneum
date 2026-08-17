# Omneum

Omneum is an open-source data trust gateway for agentic systems. Think of it as a fast, lightweight reliability layer that sits between data sources and language models to ground your agents in trusted information.

## 🧠 Why Omneum?

In modern agentic workflows, context is built from multiple retrievals and tool calls. When that context is passed through continuous loops, it's easy for conflicting or duplicate information to get included and data lineage to get lost across multi-step execution paths.

Omneum evaluates context quality before it gets passed to the model and can be integrated directly into your existing retrieval or orchestration stack.

Main features include:

- **Track provenance data** — Preserve source metadata to isolate duplicate information across separate retrieval runs.

- **Isolate system conflicts** — Detect and surface contradictory data entries before they enter the context window of the next model call.

- **Score context quality** — Evaluate context quality based on the independence of its supporting sources without adding extra model calls.

- **Privacy-preserving linkage** — Recognize matching private values across separate tools while keeping your data private and secure using local VOPRF-blinded tokens.

## 🚀 Quickstart

**Note:** This tutorial assumes a Python-based agentic application.

### 1. Installation

To get started with Omneum, create and activate a virtual environment:

```bash
python3.14 -m venv .venv
source .venv/bin/activate
```

Install the wheel:

```bash
pip install omneum-1.0.0-cp314-cp314-macosx_11_0_arm64.whl
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
)

now = datetime.now(timezone.utc)

estimator = DependencyEstimatorConfig(
    upstream_weight=0.25,
    citation_weight=0.20,
    assertion_lineage_weight=0.20,
    ownership_weight=0.10,
    temporal_weight=0.10,
    graph_weight=0.15,
    temporal_window_seconds=172_800.0,
)

observations = [
    Observation(
        assertion_id="result-1",
        source=Source(
            kind="web_document",
            identifier="https://docs.example.com/service-status",
        ),
        claim=Claim(
            entity_namespace="service",
            entity="payment_api",
            attribute="status",
            value="healthy",
        ),
        observed_at=now,
        retrievals=(
            Retrieval(
                retrieval_id="retrieval-1",
                kind="web_search",
                resource_id="https://docs.example.com/service-status",
                retrieved_at=now,
            ),
        ),
    ),
    Observation(
        assertion_id="result-2",
        source=Source(
            kind="web_document",
            identifier="https://status.example.org/payment-api",
        ),
        claim=Claim(
            entity_namespace="service",
            entity="payment_api",
            attribute="status",
            value="degraded",
        ),
        observed_at=now,
        retrievals=(
            Retrieval(
                retrieval_id="retrieval-2",
                kind="web_search",
                resource_id="https://status.example.org/payment-api",
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

`evaluate_assertion()` evaluates the observations and generates context-quality signals that your application can use before passing the retrieved context to the model.

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

The SDK processes the underlying data locally and handles the privacy-preserving linkage with the server. The private values used to construct linkage tokens never leave the client in plaintext.

## 📦 Observation Model

Omneum evaluates `Observation` objects. Format the retrieved data and tool outputs you want to evaluate as observations, preserving their source and any metadata available at that point in the agent run:

```python
Observation(
    assertion_id="result-1",
    source=Source(
        kind="web_document",
        identifier="https://docs.example.com/service-status",
    ),
    claim=Claim(
        entity_namespace="service",
        entity="payment_api",
        attribute="status",
        value="healthy",
    ),
    observed_at=now,
)
```

Each observation contains a structured value from the agent run, represented as:

```text
entity + attribute + value
```

For example:

```text
payment_api + status + healthy
acme-corp + quarterly_revenue_usd + 42000000
```

Omneum represents that structured value as a `Claim` inside the `Observation`, alongside its source and any metadata captured during execution.

You can also attach retrieval records and relationships to other sources or assertions.

For example, a result returned by an internal research tool can preserve the retrieval that produced it:

```python
observation = Observation(
    assertion_id="research-result-42",
    source=Source(
        kind="internal_service",
        identifier="market-data-api",
        owner_id="research",
    ),
    claim=Claim(
        entity_namespace="company",
        entity="acme-corp",
        attribute="quarterly_revenue_usd",
        value=42_000_000,
    ),
    observed_at=now,
    retrievals=(
        Retrieval(
            retrieval_id="market-data-lookup-42",
            kind="tool_call",
            resource_id="market-data-api",
            retrieved_at=now,
        ),
    ),
)
```

Build observations from the metadata already available during retrieval and tool execution. This could be from your retrieval layer, MCP tools, or agent runtime. If a field isn't available in the current run, you can leave it out.

## 🕸️ Dependency Estimation

In many cases, multiple tool results can appear to support the same claim independently even when they trace back to the same underlying source. Omneum estimates these relationships before calculating claim support.

The estimator uses metadata already captured during execution. For example, two observations may reference the same upstream source or come from sources under the same owner. Retrieval timing and structural overlap can provide additional signals when that metadata is available.

The Quickstart uses the current baseline weights:

```text
upstream             0.25
citation             0.20
assertion_lineage    0.20
ownership            0.10
temporal             0.10
graph                0.15
```

These weights are currently hand-tuned and have not been calibrated against labeled source-dependency data. You can pass a different `DependencyEstimatorConfig` when evaluating observations if you want to test different weighting for your workload.

When metadata is missing, Omneum works with the signals available in the current run rather than requiring your application to reconstruct provenance.

## 🔒 Privacy

Omneum uses an RFC 9497 VOPRF with the `ristretto255-SHA512` ciphersuite to create stable linkage tokens without sending the underlying source, entity, attribute, or claim values to the server.

Before evaluation, the SDK canonicalizes and serializes each value locally and encodes it for its linkage domain. The SDK then blinds the encoded input locally, and only the blinded element is sent to the Omneum server.

```text
Private Input
     ↓
Blind locally
     ↓
Blinded Element ──────────→ Omneum Server
                              ↓
                         VOPRF Evaluate
                              ↓
Evaluated Element + Proof ←───┘
     ↓
Verify + Finalize locally
     ↓
Linkage Token
```

The server evaluates the blinded element with its private key and returns an evaluated element with a DLEQ proof. The SDK verifies that proof against the configured server public key before finalizing the VOPRF output locally.

The finalized linkage token is deterministic for the same encoded linkage input under the same VOPRF server key. This lets Omneum recognize repeated sources and claims across an agent run without learning the values used to create those tokens.

The server can still observe protocol traffic and the opaque relationships submitted for evaluation. VOPRF protects the underlying values; it does not make the entire evaluation request invisible to the server.

## ⚙️ Configuration

`omneum init` creates the configuration and key material for a local deployment. The SDK loads this configuration automatically when you call:

```python
config = OmneumClientConfig.from_local_deployment()
```

By default, Omneum stores deployment state in the platform-specific application config directory. If you would like to use a different location, set `OMNEUM_CONFIG_DIR`:

```bash
export OMNEUM_CONFIG_DIR=/path/to/omneum
```

The directory contains:

```text
config.toml
keys/
└── voprf.key
```

`config.toml` stores the non-secret deployment configuration. The VOPRF private key is stored separately under `keys/`. It should **not** be committed to source control.

Dependency estimation is configured in application code with `DependencyEstimatorConfig`:

```python
estimator = DependencyEstimatorConfig(
    upstream_weight=0.25,
    citation_weight=0.20,
    assertion_lineage_weight=0.20,
    ownership_weight=0.10,
    temporal_weight=0.10,
    graph_weight=0.15,
    temporal_window_seconds=172_800.0,
)
```

Pass the configuration with each evaluation:

```python
result = await client.evaluate_assertion(
    observations,
    estimator=estimator,
)
```

The weights above are Omneum's current baseline. Override them if you are testing a different dependency model for your workload.

## 📚 Documentation

The Quickstart above is enough to get a local integration running. See [`sdk.md`](docs/sdk.md) for the full Python SDK interface and result types.

## 🧪 Status

Omneum is currently in an early design-partner release. The SDK and integration may change as it is tested in production agent workflows. As an open-source AI infrastructure project, we gladly welcome any contributions or feedback.

## 📄 License

See [`LICENSE`](LICENSE) for license information.