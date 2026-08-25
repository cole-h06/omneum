# Omneum Python SDK

This document contains the Python SDK for interacting with an Omneum server.

## Getting Started

### 1. Install Omneum

To get started with the Python SDK, you can install with:

~~~bash
pip install .
~~~

### 2. Initialize Omneum

Initialize a local deployment:

~~~bash
omneum init
~~~

You will need an initialized deployment before creating a client. For local development, `omneum init` creates the deployment configuration and VOPRF key material, and the SDK will automatically load that configuration when connecting to the local server.

### Connect to the Server

For local development, Omneum runs as an MCP server over `stdio`. Load the local deployment configuration and define the server process:

```python
from mcp import StdioServerParameters

from omneum import OmneumClientConfig, open_stdio_client

config = OmneumClientConfig.from_local_deployment()

server = StdioServerParameters(
    command="omneum-server",
)
```

The client uses the local deployment configuration when opening the MCP connection.

### Evaluate Assertions

Omneum evaluates semantically normalized assertions from the context your agent has retrieved.

The application defines the assertion identity — the entity, attribute, and structured value being evaluated — and supplies the sources that surfaced it. Source provenance and dependency metadata are optional.

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
    entity_namespace="company",
    entity="acme-corp",
    attribute="quarterly_revenue_usd",
    value=42_000_000,
    sources=(
        AssertionSource(
            source=Source(
                kind="web_document",
                identifier="https://research.example.com/acme-q3",
            ),
            assertion_id="research-result",
            observed_at=now,
        ),
        AssertionSource(
            source=Source(
                kind="web_document",
                identifier="https://analytics.example.com/acme-q3",
            ),
            assertion_id="analytics-result",
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

That's the basic evaluation path. You do not need to construct retrieval lineage, citations, ownership metadata, or custom dependency signals before Omneum can evaluate an assertion.

The application does own semantic normalization. Omneum does not use an LLM to decide that differently worded retrieved content expresses the same assertion. Your integration converts the information it wants evaluated into a stable:

```text
(entity_namespace, entity, attribute) → value
```

For the example above:

```text
("company", "acme-corp", "quarterly_revenue_usd") → 42000000
```

Once that boundary is established, the SDK handles canonicalization, privacy-preserving linkage, dependency estimation, and assertion evaluation.

### Existing Agent and Retrieval Data

Most agent applications already have retrieval results, tool outputs, or workflow state in their own schemas. You do not need to rebuild those objects around Omneum.

`ContextMapper` adapts existing runtime data into the evaluation pipeline.

Suppose a retrieval branch already produces records like:

```python
results = [
    {
        "id": "research-result",
        "url": "https://research.example.com/acme-q3",
        "company": "acme-corp",
        "revenue": 42_000_000,
    },
    {
        "id": "analytics-result",
        "url": "https://analytics.example.com/acme-q3",
        "company": "acme-corp",
        "revenue": 42_000_000,
    },
]
```

Define how those fields map into the assertion evaluation:

```python
from omneum import ContextMapper, Source

mapper = ContextMapper(
    source=lambda result: Source(
        kind="web_document",
        identifier=result["url"],
    ),
    entity_namespace=lambda result: "company",
    entity="company",
    attribute=lambda result: "quarterly_revenue_usd",
    value="revenue",
    assertion_id="id",
    observed_at=lambda result: now,
)

result = await client.evaluate_mapped(
    results,
    mapper,
    estimator=estimator,
)
```

Mappings can reference fields already present in the runtime object or use callables when extraction or transformation is required.

This is also the integration point for application-specific semantic normalization. If two retrieval systems encode the same value differently, the `value` mapping can normalize those representations before evaluation:

```python
mapper = ContextMapper(
    ...,
    value=lambda result: normalize_revenue(result),
)
```

`evaluate()` is the direct path when your application already has a `StructuredAssertion`. `evaluate_mapped()` is the adapter path when assertions need to be constructed from existing retrieval results, tool outputs, or workflow state.

### Optional Runtime Context

Omneum can use additional provenance and dependency information when your runtime already has it. You do not need to manufacture missing metadata.

An `AssertionSource` can carry source relationships and retrieval lineage:

```python
source = AssertionSource(
    source=Source(
        kind="web_document",
        identifier="https://research.example.com/acme-q3",
        owner_id="research",
    ),
    assertion_id="research-result",
    observed_at=now,
    upstream_sources=upstream_sources,
    cited_sources=citations,
    parent_assertion_ids=parent_assertion_ids,
    retrievals=retrievals,
)
```

These fields describe information the agent runtime may already know: where a resource originated, what it cites, whether an assertion was derived from an earlier workflow step, or which retrieval execution surfaced it.

If the runtime exposes useful context that does not fit one of those fields, preserve it as metadata:

```python
source = AssertionSource(
    ...,
    metadata={
        "request_id": request_id,
        "execution_id": execution_id,
        "tool_name": tool_name,
    },
)
```

Applications can also provide dependency signals they already compute or observe:

```python
source = AssertionSource(
    ...,
    dependency_signals={
        "shared_execution": shared_execution_signal,
        "same_generation_path": generation_path_signal,
    },
)
```

Omneum does not require a fixed metadata schema from the surrounding agent stack. Integrations can preserve runtime-specific context while supplying explicit dependency signals when that context should participate in dependency estimation.

Arbitrary metadata is retained as context; it does not automatically become a dependency signal.

### Use the Evaluation Result

Both evaluation paths return the same structured result:

```python
for claim in result.claim_support:
    print("Support:", claim.support)
    print(
        "Independent support:",
        claim.estimated_independent_support_count,
    )
    print("Conflicts:", claim.conflicting_claims)
```

These values are designed to feed back into agent control flow. A workflow can continue normally, retrieve additional context when support is too dependent, route conflicting values through another verification step, or require human review before disputed context reaches the next model call.

Omneum returns evaluation signals. The application retains control over routing and policy.

### How It Fits Together

For applications that already construct structured assertions:

```text
Retrieved Context
        ↓
Semantic Normalization
        ↓
StructuredAssertion
        ↓
client.evaluate()
        ↓
Evaluation Result
        ↓
Agent Control Flow
```

For applications integrating with existing agent runtime objects:

```text
Retrieval Results / Tool Outputs / Workflow State
        ↓
ContextMapper
        ↓
client.evaluate_mapped()
        ↓
Evaluation Result
        ↓
Agent Control Flow
```

Omneum does not replace the retrieval layer, tool runtime, or orchestration framework. It evaluates the information those systems have already surfaced before that context is consumed downstream.

## Dependency Estimation

Before sending an assertion evaluation to the server, the SDK estimates source dependency from the metadata available in the current run.

Configure the estimator with `DependencyEstimatorConfig`:

```python
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
```

Pass the configuration when evaluating a structured assertion:

```python
async with open_stdio_client(config, server) as client:
    result = await client.evaluate(
        assertion,
        estimator=estimator,
    )
```

The estimator combines source relationships and dependency signals available on the assertion sources with structural overlap found across the sources participating in the current evaluation.

For the research example above, two different URLs do not automatically count as independent sources. If both results came from the same upstream source, cite one another, share assertion lineage, or belong to the same owner, those signals can increase their estimated dependency. Matching claims can also receive a retrieval dependency signal when their retrieval metadata identifies the same underlying resource.

The temporal signal uses `source_modified_at` when the runtime exposes a source update timestamp:

```python
source = AssertionSource(
    ...,
    source_modified_at=source_modified_at,
)
```

You do not need every signal for every source. Missing metadata stays unavailable rather than being inferred by the SDK.

The weights above are Omneum's current baseline configuration and are not calibrated production defaults. Applications can provide different weights and temporal windows for their workload.

## Evaluation Results

`evaluate()` and `evaluate_mapped()` return the same structured evaluation result. Use `claim_support` to inspect the support calculated for each distinct value:

```python
for claim in result.claim_support:
    print("Support:", claim.support)
    print("Independent support:", claim.estimated_independent_support_count)
    print("Conflicts:", claim.conflicting_claims)
```

`support` is the graph score calculated for that value from its supporting sources. It is not a probability that the value is correct.

`estimated_independent_support_count` adjusts the number of supporting sources for estimated source dependency. Multiple sources can therefore support the same value without being treated as fully independent.

For the quarterly revenue example, Omneum evaluates the competing values separately:

```text
acme-corp / quarterly_revenue_usd

42000000
  Support: ...
  Independent support: ...
  Conflicts: 39500000

39500000
  Support: ...
  Independent support: ...
  Conflicts: 42000000
```

Your application can use these fields directly in its control flow. For example, a workflow can run another retrieval when conflicting values are present:

```python
for claim in result.claim_support:
    if claim.conflicting_claims:
        # Route back to retrieval or verification before the next model call.
        ...
```

The result also includes the source-dependency data calculated for the evaluation. This lets application code inspect how dependency between supporting sources affected the returned support signals.

Signal coverage records how much of the configured dependency metadata was available for a source pair. It should not be interpreted as confidence that the dependency estimate is correct.

Omneum returns these values as structured SDK data and leaves routing decisions to your application.

## Local Explanations

Omneum includes local helpers for formatting evaluation results into readable text. These are useful when you want to inspect a result during development, write it to application logs, or include an explanation in downstream model context.

Use `explain_claim()` with the claim results returned by `evaluate()` or `evaluate_mapped()`:

```python
from omneum import explain_claim

for claim in result.claim_support:
    print(explain_claim(claim))
```

The helper formats fields already present in the result, including support, supporting-source count, independent support, and conflicts. It does not run another evaluation.

Source-dependency results can be formatted with `explain_dependency()`:

```python
from omneum import explain_dependency

for dependency in result.pairwise_dependencies:
    print(explain_dependency(dependency))
```

`explain_dependency()` uses source context retained locally by the SDK to describe which dependency signals were available for the source pair. Depending on the runtime context supplied with the assertion sources, this can include upstream relationships, citations, assertion lineage, shared ownership, source update timing, retrieval relationships, structural overlap, or application-provided dependency signals.

Both helpers run entirely in the Python process. They do not make an MCP request, call an LLM, modify the evaluation result, or send additional data to the Omneum server.

Use the structured result fields for application logic. The explanation helpers are a formatting layer for cases where the same result needs to be readable by a developer or included in downstream context.

## Privacy and Linkage

The Python SDK creates stable linkage tokens for private source, attribute, and claim data before sending an assertion evaluation to the Omneum server.

Source identifiers and structured attribute and claim values are canonicalized and serialized locally. The SDK then uses Omneum's RFC 9497 VOPRF flow to generate linkage tokens without sending those values to the server in plaintext.

Applications using `evaluate()` or `evaluate_mapped()` do not need to canonicalize linkage inputs, construct VOPRF requests, or invoke the VOPRF operations directly. These steps are handled by the SDK.

During linkage, the SDK blinds each encoded input locally and sends the blinded element to the server for evaluation. The server returns an evaluated element and proof, which the SDK verifies and finalizes locally.

```text
Application Value
        ↓
Canonicalize + Serialize
        ↓
Blind Locally
        ↓
VOPRF Evaluation over MCP
        ↓
Verify + Finalize Locally
        ↓
Linkage Token
```

The finalized token is deterministic for the same encoded linkage input under the same VOPRF server key. This allows matching sources, attributes, and claims to resolve to the same opaque identifiers within that linkage space.

Raw source identifiers, entity names, attributes, claim values, retrieval records, source relationships, and natural-language explanations remain in the client. Assertion evaluation sends the generated linkage tokens and the source-pair data required by the server-side evaluation.

VOPRF protects the private values used to create linkage tokens; it does not hide the entire request. The server can still observe request metadata and relationships between opaque identifiers submitted in an evaluation.

The SDK handles blinding, proof verification, finalization, and token encoding automatically when you use the high-level assertion-evaluation API. Applications normally do not need to call the VOPRF operations directly.

## Configuration

`omneum init` creates the configuration and VOPRF key material for a local deployment. The Python SDK can load that deployment directly:

```python
from omneum import OmneumClientConfig

config = OmneumClientConfig.from_local_deployment()
```

By default, Omneum stores local deployment state in the platform-specific application config directory. Set `OMNEUM_CONFIG_DIR` when you need to use a different location:

```bash
export OMNEUM_CONFIG_DIR=/path/to/omneum
```

A local deployment contains the non-secret configuration separately from its VOPRF private key:

```text
config.toml
keys/
└── voprf.key
```

Do not commit the contents of `keys/` to source control.

Dependency-estimator settings are application configuration rather than deployment configuration. Create a `DependencyEstimatorConfig` in your application and pass it with the evaluation:

```python
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

result = await client.evaluate(
    assertion,
    estimator=estimator,
)
```

The dependency weights control how the SDK combines the available dependency signals for that evaluation. The values shown here are Omneum's current baseline configuration, not calibrated production defaults.

For local `stdio`, `from_local_deployment()` loads the deployment ID, VOPRF settings, linkage-encoding version, and pinned server public key required by the client. Applications using another deployment configuration should construct `OmneumClientConfig` from authenticated configuration supplied for that deployment.

## Known Limitations

- **Remote transport** is not currently supported by the Python SDK. Client connections use a local MCP server over `stdio`.

- **Python 3.14** is currently required. JavaScript and TypeScript SDKs are not yet available.

- **Token metadata storage** is not managed automatically by the SDK. Applications that persist linkage tokens are responsible for storing the deployment, key version, linkage configuration, purpose, and token metadata required to compare them correctly.

- **Key rotation** currently supports one active VOPRF key at a time. Overlapping old and new keys during a rotation is not supported.

- **Assertion evaluation over `stdio`** reads a complete newline-delimited MCP frame before application-level validation. A pre-parse frame-size limit is not currently available through the installed MCP SDK.

- **Timed-out assertion evaluations** cannot forcibly terminate the underlying Python work. The evaluation continues to hold its capacity slot until that work exits.

- **Dependency-estimator weights** are configuration values rather than calibrated production defaults. Applications should not interpret the baseline weights as validated for a specific workload.

- **Dependency clusters** require an explicit threshold. Omneum does not currently provide a default or calibrated clustering threshold.

## Documentation

For the full assertion-evaluation API contract, request and response schemas, validation rules, and server limits, see [`api.md`](api.md).

Implementation details for canonicalization and linkage are documented separately in [`canonicalization.md`](canonicalization.md), including the structured source, attribute, and claim formats used to generate linkage inputs.

The MCP protocol, deployment metadata, and VOPRF request flow are covered in [`protocol.md`](protocol.md). Additional cryptographic implementation details and interoperability requirements are documented alongside the protocol documentation.

For examples of integrating Omneum into agent workflows, see the [`examples/`](../examples/) directory.

## Contributing

Contributions are welcome. Whether you find a bug, run into an integration issue, or want to propose a change to documentation, please open an issue with enough detail to reproduce the behavior.

Development and contribution guidelines will be added as the SDK moves beyond the current design-partner release.

## License

Omneum is licensed under the terms in [`LICENSE`](../LICENSE).