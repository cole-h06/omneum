# Omneum

Omneum is an open-source data trust gateway for agentic systems. It evaluates information returned by retrieval and tool execution before that information is included in the next model context.

Agent workflows routinely assemble context from search results, APIs, databases, internal services, documents, MCP tools, and outputs from earlier agent steps. Omneum evaluates how much independent support exists for the structured assertions produced by those systems, surfaces conflicting values, and preserves source relationships without adding another LLM call.

## 🧠 Why Omneum?

Multi-source agent workflows can retrieve several results that appear to agree even when they ultimately depend on the same upstream resource. Other retrieval branches may return conflicting values, copied information, stale versions, or results whose provenance was partially preserved by the runtime.

Omneum adds an evaluation step between retrieval or tool execution and the model call that consumes the resulting context.

Main features include:

- **Source dependency estimation** - Estimate the independence of supporting sources using available provenance, execution metadata, source relationships, and graph structure.

- **Conflict detection** - Surface competing structured values for the same entity and attribute before they are included in the next model context.

- **Context-quality signals** - Return support, estimated independent support, source-dependency results, and signal coverage without invoking another language model.

- **Privacy-preserving linkage** - Generate stable linkage tokens with an RFC 9497 VOPRF so private source identifiers and structured values do not need to be sent to the server in plaintext.

## Performance

| | Dependency precision | Dependency recall | Evaluation latency | LLM tokens |
|---|---:|---:|---:|---:|
| **Omneum** | **100.0%** | 77.8% | **13.5 ms** | **0** |
| LLM-as-Judge | 81.8% | **100.0%** | 4.7 s | 5,576 |
| Naive Vector RAG | — | — | 5.2 s | 5,093 |

*Results across three real-world financial dependency cases. See [`benchmarks/financial_dependency_suite`](benchmarks/financial_dependency_suite) for methodology and reproducibility notes.*

## 🚀 Quickstart

**Note:** This tutorial assumes a Python-based agent application.

### 1. Installation

Create and activate a virtual environment:

~~~bash
python3.14 -m venv .venv
source .venv/bin/activate
~~~

Install Omneum from the repository:

~~~bash
pip install .
~~~

### 2. Initialize Omneum

Initialize a local deployment:

~~~bash
omneum init
~~~

This creates the deployment configuration and VOPRF key material required by the local Omneum server.

### 3. Connect to the MCP Server

For local development, Omneum runs as an MCP server over `stdio`:

~~~python
from mcp import StdioServerParameters

from omneum import OmneumClientConfig, open_stdio_client

config = OmneumClientConfig.from_local_deployment()

server = StdioServerParameters(
    command="omneum-server",
)
~~~

The SDK loads the initialized deployment configuration when it opens the MCP connection.

### 4. Evaluate a Structured Assertion

If your application has already normalized retrieved information into a structured assertion, use `StructuredAssertion`.

~~~python
from datetime import datetime, timezone

from omneum import (
    AssertionSource,
    DependencyEstimatorConfig,
    Source,
    StructuredAssertion,
)

now = datetime.now(timezone.utc)

assertion = StructuredAssertion(
    entity_namespace="service",
    entity="payment_api",
    attribute="status_code",
    value=200,
    sources=(
        AssertionSource(
            source=Source(
                kind="web_document",
                identifier="https://research.example.com/payment-status",
            ),
            assertion_id="result-1",
            observed_at=now,
        ),
        AssertionSource(
            source=Source(
                kind="web_document",
                identifier="https://analytics.example.com/payment-status",
            ),
            assertion_id="result-2",
            observed_at=now,
        ),
    ),
)

estimator = DependencyEstimatorConfig()

async with open_stdio_client(config, server) as client:
    result = await client.evaluate(
        assertion,
        estimator=estimator,
    )
~~~

`StructuredAssertion` is the high-level entry point when application code already knows the entity, attribute, value, and sources being evaluated. You do not need to construct `Observation`, `Claim`, `Retrieval`, or `SourceReference` objects for this path.

The application remains responsible for semantic normalization. Omneum does not use an LLM to decide that two differently expressed retrieval results represent the same structured assertion.

### 5. Evaluate Existing Tool or Retrieval Output

Most agent integrations already have result objects produced by tool calls, retrieval nodes, connectors, or workflow state. `ContextMapper` adapts those records directly instead of requiring an Omneum-specific data model at the retrieval boundary.

Suppose a retrieval step already returns:

~~~python
results = [
    {
        "id": "result-1",
        "url": "https://research.example.com/payment-status",
        "entity": "payment_api",
        "status_code": 200,
    },
    {
        "id": "result-2",
        "url": "https://analytics.example.com/payment-status",
        "entity": "payment_api",
        "status_code": 200,
    },
]
~~~

Define how fields in that result schema map into the assertion evaluation:

~~~python
from omneum import ContextMapper, Source

mapper = ContextMapper(
    source=lambda result: Source(
        kind="web_document",
        identifier=result["url"],
    ),
    entity_namespace=lambda result: "service",
    entity="entity",
    attribute=lambda result: "status_code",
    value="status_code",
    assertion_id="id",
    observed_at=lambda result: now,
)
~~~

Then pass the existing records directly to `evaluate_mapped()`:

~~~python
async with open_stdio_client(config, server) as client:
    result = await client.evaluate_mapped(
        results,
        mapper,
        estimator=estimator,
    )
~~~

Mappings can read fields from the existing record or use callables when extraction or application-defined normalization is required.

If a tool result or orchestration state already contains provenance, source timestamps, retrieval records, lineage, or dependency signals, those fields can also be mapped. Missing metadata stays unavailable; the integration does not need to synthesize provenance that the runtime never captured.

### 6. Use the Evaluation Result

`evaluate()` and `evaluate_mapped()` return the same `AssertionEvaluation` result:

~~~python
for claim in result.claim_support:
    print("Support:", claim.support)
    print(
        "Independent support:",
        claim.estimated_independent_support_count,
    )
    print("Conflicts:", claim.conflicting_claims)
~~~

These fields are intended for agent control flow. An orchestration layer can run another retrieval when independent support is insufficient, branch when conflicting values are present, or include an explanation alongside the retrieved information passed to the next model call.

Omneum returns evaluation signals. The application decides what happens next.

## 🔌 How It Fits

Omneum runs after information has been retrieved and before the evaluated information is included in a subsequent model context.

~~~text
Search / Retrieval / Tool Execution
                ↓
       Tool Results / Retrieved Data
                ↓
     Application-Defined Normalization
                ↓
  StructuredAssertion / ContextMapper
                ↓
          Omneum Evaluation
                ↓
 Support / Dependency / Conflict Signals
                ↓
       Agent Control Flow
                ↓
        Next Model Context
~~~

Omneum does not replace the retrieval system, MCP client, tool runtime, or orchestration framework. It evaluates information those components have already surfaced.

## 📦 Evaluation Input

Omneum's high-level SDK provides two integration paths.

Use `StructuredAssertion` when application code already has a normalized assertion:

~~~text
(entity_namespace, entity, attribute) → value
~~~

For example:

~~~text
service / payment_api / status_code → 200
company / acme-corp / quarterly_revenue_usd → 42000000
~~~

Each `AssertionSource` records a source-specific occurrence of that assertion together with the assertion identifier and observation time. Optional source and execution metadata can be supplied when the application already has it.

Use `ContextMapper` when the same information already exists inside tool results, retrieval outputs, connector responses, Pydantic models, or orchestration state. The mapper defines how the application's existing fields become the structured assertion data Omneum evaluates.

`ContextMapper` accepts field paths or callables, so an integration can extract nested values or apply application-defined normalization without replacing its existing result schema.

### Lower-Level Observation API

`Observation` is Omneum's lower-level source-specific representation. Each observation associates a `Claim` with the source that produced it and can retain detailed provenance, retrieval metadata, source relationships, assertion lineage, and dependency signals.

`client.evaluate_assertion()` accepts these objects directly.

Applications do not need to use this interface for ordinary `StructuredAssertion` or `ContextMapper` integrations. It remains available when an integration needs direct control over the complete observation representation.

All three entry paths feed the same assertion-evaluation pipeline and return an `AssertionEvaluation`.

See [`sdk.md`](docs/sdk.md) for the complete SDK model and lower-level interfaces.

## 🕸️ Dependency Estimation

Multiple retrieved results are not necessarily multiple independent sources.

Two documents may derive from the same upstream resource. Separate tool calls may resolve to the same underlying resource. Sources can also share ownership, assertion lineage, retrieval history, or structural relationships visible within the current evaluation.

Before constructing the server-side assertion evaluation, the SDK estimates pairwise source dependency from the signals available to the client.

`DependencyEstimatorConfig` controls the contribution of the built-in dependency signals:

~~~python
from omneum import DependencyEstimatorConfig

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
~~~

The estimator operates on metadata already present in the evaluation input. It does not require every signal to be observable for every source pair, and missing metadata is not treated as observed independence.

Applications can also attach dependency signals already produced by their runtime or integration rather than forcing runtime-specific metadata into a fixed provenance schema.

The returned evaluation includes pairwise dependency results and signal coverage alongside claim support. `estimated_independent_support_count` adjusts the raw number of supporting sources according to their estimated dependency.

See [`sdk.md`](docs/sdk.md#dependency-estimation) for estimator configuration and dependency-result fields.

## 🔒 Privacy

Omneum uses an RFC 9497 VOPRF with the `ristretto255-SHA512` ciphersuite to derive stable linkage tokens for private source and structured assertion data.

Canonicalization, serialization, VOPRF blinding, proof verification, finalization, and token encoding occur through the Python SDK. Source identifiers and structured linkage values are not sent to the Omneum server in plaintext during token generation.

The resulting tokens allow matching encoded inputs to resolve to stable opaque identifiers within the same deployment, key version, linkage configuration, and purpose.

VOPRF protects the private values used to derive those tokens; it does not conceal the entire MCP request. The server can still observe protocol traffic and relationships between opaque identifiers submitted for evaluation.

## 📚 Documentation

The Quickstart covers the high-level integration paths. The repository contains deeper documentation for the SDK and wire protocol:

- [`sdk.md`](docs/sdk.md) - `StructuredAssertion`, `ContextMapper`, dependency-estimator configuration, evaluation results, explanations, and the lower-level `Observation` API.

- [`api.md`](docs/api.md) - MCP assertion-evaluation request and response schemas, validation behavior, server limits, and error handling.

- [`protocol.md`](docs/protocol.md) - MCP transport, deployment metadata, linkage flow, and VOPRF protocol behavior.

- [`canonicalization.md`](docs/canonicalization.md) - Canonical source, entity, attribute, and value encodings used to construct deterministic linkage inputs.

- [`examples/`](examples/) - Framework-specific and end-to-end agent workflow integrations.

## 🧪 Status

Omneum is currently in an early design-partner release. The SDK and integration surface may change as the project is exercised against production agent workflows.

As an open-source AI infrastructure project, we gladly welcome any feedback or contributions!

## 📄 License

See [`LICENSE`](LICENSE) for license information.