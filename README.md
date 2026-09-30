# Omneum

Omneum is an open-source data trust gateway for agentic systems. It evaluates information returned by retrieval and tool execution before that information is included in the next model context.

Agent workflows routinely assemble context from search results, APIs, databases, internal services, documents, MCP tools, and outputs from earlier agent steps. Omneum evaluates how much independent support exists for the structured assertions produced by those systems, surfaces conflicting values, and preserves source relationships without adding another LLM call.

Omneum independently implements BRAID according to the accepted research
specification and frozen fixtures. See [algorithm compatibility](docs/algorithm_compatibility.md)
for the exact revision pin and conformance checks, and
[opt-in research telemetry](docs/research_telemetry.md) for the privacy-safe feedback workflow.

## 🧠 Why Omneum?

Multi-source agent workflows can retrieve several results that appear to agree even when they ultimately depend on the same upstream resource. Other retrieval branches may return conflicting values, copied information, stale versions, or results whose provenance was partially preserved by the runtime.

Omneum adds an evaluation step between retrieval or tool execution and the model call that consumes the resulting context.

Main features include:

- **Source dependency estimation:** Estimate the independence of retrieved results using available provenance, execution metadata, source relationships, and graph structure.

- **Conflict detection:** Surface competing structured values for the same entity and attribute before they are included in the next model context.

- **Context-quality signals:** Return support, estimated independent support, source-dependency results, and signal coverage without invoking another language model.

- **Privacy-preserving linkage:** Generate stable linkage tokens with an RFC 9497 VOPRF so private source identifiers and structured values do not need to be sent to the server in plaintext.

## 🚀 Quickstart

**Note:** This tutorial assumes a Python-based agent application.

### 1. Installation

On macOS (Apple silicon or Intel), or Ubuntu 22.04+ x86_64 with systemd,
install Python 3.11–3.14, then run:

```bash
pip install omneum
omneum install
```

Run `omneum install` as your normal login user. It downloads the daemon matching
exactly your installed package version, verifies the release checksum, and asks
for administrator authorization to install the protected service. A GitHub daemon
release for that exact version must already be published.

### 2. Initialization and platform requirements

`omneum install` initializes public configuration and verifies an authenticated
daemon evaluation before reporting readiness. Existing key pins are never replaced.

On Linux, the command also installs a dedicated, root-owned Python runtime and the
managed MCP server. Your account receives access to the client-facing proxy only;
it never receives direct daemon or private-key access. `omneum-server` automatically
uses that proxy, including immediately after installation without a new login.
Linux without systemd requires administrator-managed supervision and is not an
automatic installation target. Windows and other architectures do not support local
daemon installation.

See [installation details](docs/installation.md) for failures and platform limits.
For source/development installs, use `uv sync --locked` with the pinned uv version
from `pyproject.toml` and a Rust toolchain. The lower-level [deployment instructions](deploy/README.md)
and `omneum init` remain available to administrators.

### 3. Connect to the MCP Server

For local development, Omneum runs as an MCP server over `stdio`:

```python
from mcp import StdioServerParameters

from omneum import OmneumClientConfig, open_stdio_client

config = OmneumClientConfig.from_local_deployment()

server = StdioServerParameters(
    command="omneum-server",
)
```

The SDK loads the initialized deployment configuration when it opens the MCP connection.

### 4. Evaluate a Structured Assertion

If your application has already normalized retrieved information into a structured assertion, use `StructuredAssertion`.

```python
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
```

`StructuredAssertion` is the high-level entry point when your application code already knows the entity, attribute, value, and sources being evaluated. You do not need to construct `Observation`, `Claim`, `Retrieval`, or `SourceReference` objects for this path.

Your application remains responsible for semantic normalization. Omneum does not use an LLM to decide that two differently expressed retrieval results represent the same structured assertion.

### 5. Evaluate Existing Tool or Retrieval Output

Most agent integrations already have result objects produced by tool calls, retrieval nodes, connectors, or workflow state. `ContextMapper` maps fields already present in those objects into Omneum's canonical assertion and provenance fields.

If the runtime doesn't have a field, leave it unset. Missing provenance should not be turned into an observed zero or manufactured just to fill the schema.

Suppose a retrieval step already returns:

```python
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
```

Define where the canonical fields live in that result schema:

```python
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
```

Then evaluate the existing records:

```python
async with open_stdio_client(config, server) as client:
    result = await client.evaluate_mapped(
        results,
        mapper,
        estimator=estimator,
    )
```

Mappings can read fields from the existing record or use callables when extraction or application-defined normalization requires some logic.

If your runtime already has source lineage, citations, source timestamps, assertion lineage, or retrieval records, those fields can also be mapped. If it doesn't have them, leave them unset.

See [`context_mapper.md`](docs/context_mapper.md) for the complete mapping contract.

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

```text
Search / Retrieval / Tool Execution
                ↓
       Tool Results / Retrieved Data
                ↓
     Application-Defined Normalization
                ↓
  StructuredAssertion / ContextMapper
                ↓
       Canonical Observations
                ↓
       Dependency Estimation
                ↓
          Bipartite Graph
                ↓
    BRAID Reliability Propagation
                ↓
        Evaluation Result
                ↓
       Agent Control Flow
                ↓
        Next Model Context
```

Omneum does not replace the retrieval system, MCP client, tool runtime, or orchestration framework. It evaluates information those components have already surfaced.

## 📦 Evaluation Input

Omneum's high-level SDK provides two integration paths.

Use `StructuredAssertion` when your application code already has a normalized assertion:

~~~text
(entity_namespace, entity, attribute) → value
~~~

For example:

~~~text
service / payment_api / status_code → 200
~~~

Each `AssertionSource` records a source-specific occurrence of that assertion together with the assertion identifier and observation time. Source lineage, citations, source timestamps, assertion lineage, and retrieval records can be supplied when the application already has them.

Use `ContextMapper` when the same information already exists inside tool results, retrieval outputs, connector responses, Pydantic models, or orchestration state. The mapper defines where Omneum's canonical assertion and provenance fields live in the application's existing objects.

`ContextMapper` accepts field paths or callables, so an integration can extract nested values, apply application-defined normalization, and map provenance already present in its runtime.

Explicit dependency signals are available for integrations that already compute one of Omneum's canonical signals, but most integrations shouldn't start there.

### Lower-Level Observation API

`Observation` is Omneum's lower-level source-specific representation. Each observation associates a `Claim` with the source that produced it and can retain detailed provenance, retrieval metadata, source relationships, assertion lineage, and dependency signals.

`client.evaluate_assertion()` accepts these objects directly.

Applications do not need to use this interface for ordinary `StructuredAssertion` or `ContextMapper` integrations. It remains available when an integration needs direct control over the complete observation representation.

All three entry paths feed the same assertion-evaluation pipeline and return an `AssertionEvaluation`.

See [`sdk.md`](docs/sdk.md) for the complete SDK model and lower-level interfaces.

## 🕸️ Dependency Estimation

Multiple retrieved results are not necessarily independent sources.

Two documents may derive from the same upstream resource. Separate tool calls may resolve to the same underlying resource. Sources can also share ownership, assertion lineage, retrieval history, or structural relationships visible within the current evaluation.

The SDK estimates pairwise source dependency from the provenance and structural information available in the current evaluation.

Missing information is not treated as evidence of independence. If a dependency signal cannot be observed for a source pair, it remains unavailable. Dependency is calculated from the signals that were observable, while `weighted_signal_coverage` records how much of the configured signal space was available.

The resulting dependency estimates are used to derive the independence weights applied during BRAID reliability propagation. BRAID runs over the bipartite graph of sources and claims and propagates reliability between them until the scores converge.

The returned evaluation includes claim support, pairwise dependency results, conflicts, and signal coverage. `estimated_independent_support_count` is reported separately as a dependency-adjusted source count; it is not the BRAID support score.

Applications can provide explicit dependency signals when their runtime already computes one of Omneum's canonical signals. Most integrations should supply the provenance they actually have and let the SDK derive the corresponding signals.

See [`sdk.md`](docs/sdk.md#dependency-estimation) for estimator behavior and configuration.

## Performance

| | Dependency precision | Dependency recall | Evaluation latency | LLM tokens |
|---|---:|---:|---:|---:|
| **Omneum** | **100.0%** | 77.8% | **13.5 ms** | **0** |
| LLM-as-Judge | 81.8% | **100.0%** | 4.7 s | 5,576 |
| Naive Vector RAG | — | — | 5.2 s | 5,093 |

*Results across three real-world financial dependency cases. See [`benchmarks/financial_dependency_suite`](benchmarks/financial_dependency_suite) for methodology and reproducibility notes.*

## 🔒 Privacy

Omneum uses an RFC 9497 VOPRF with the `ristretto255-SHA512` ciphersuite to derive stable linkage tokens for private source and structured assertion data.

Canonicalization, serialization, VOPRF blinding, proof verification, finalization, and token encoding occur through the Python SDK. Source identifiers and structured linkage values are not sent to the Omneum server in plaintext during token generation.

The resulting tokens allow matching encoded inputs to resolve to stable opaque identifiers within the same deployment, key version, linkage configuration, and purpose.

VOPRF protects the private values used to derive those tokens; it does not conceal the entire MCP request. The server can still observe protocol traffic and relationships between opaque identifiers submitted for evaluation.

## 📚 Documentation

The Quickstart covers the high-level integration paths. The repository contains deeper documentation for the SDK and wire protocol:

- [`sdk.md`](docs/sdk.md) - `StructuredAssertion`, `ContextMapper`, dependency-estimator configuration, evaluation results, explanations, and the lower-level `Observation` API.

- [`context_mapper.md`](docs/context_mapper.md) - `ContextMapper` field contract, source identity, provenance mapping, retrieval records, missing-data behavior, and explicit dependency signals.

- [`api.md`](docs/api.md) - MCP assertion-evaluation request and response schemas, validation behavior, server limits, and error handling.

- [`protocol.md`](docs/protocol.md) - MCP transport, deployment metadata, linkage flow, and VOPRF protocol behavior.

- [`canonicalization.md`](docs/canonicalization.md) - Canonical source, entity, attribute, and value encodings used to construct deterministic linkage inputs.

- [`examples/`](examples/) - Framework-specific and end-to-end agent workflow integrations.

## 🧪 Status

Omneum is currently in an early design-partner release. The SDK and integration surface may change as the project is exercised against production agent workflows.

As an open-source AI infrastructure project, we gladly welcome any feedback or contributions.

## 📄 License

See [`LICENSE`](LICENSE) for license information.
