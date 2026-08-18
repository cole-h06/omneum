# Omneum Python SDK

This document contains the Python SDK for interacting with an Omneum server.

## Getting Started

To get started with the Python SDK, install the wheel:

```bash
pip install omneum-1.0.0-cp314-cp314-macosx_11_0_arm64.whl
```

Initialize a local deployment:

```bash
omneum init
```

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

`client.evaluate_assertion()` evaluates a set of `Observation` objects from the current agent run. Each observation associates a structured value with the source that produced it and can include provenance metadata captured during retrieval or tool execution.

```python
from datetime import datetime, timezone

from omneum import Claim, DependencyEstimatorConfig, Observation, Source

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
            identifier="https://research.example.com/acme-q3",
        ),
        claim=Claim(
            entity_namespace="company",
            entity="acme-corp",
            attribute="quarterly_revenue_usd",
            value=42_000_000,             # retrieved value
        ),
        observed_at=now,
    ),
    Observation(
        assertion_id="result-2",
        source=Source(
            kind="web_document",
            identifier="https://analysis.example.org/acme-q3",
        ),
        claim=Claim(
            entity_namespace="company",
            entity="acme-corp",
            attribute="quarterly_revenue_usd",
            value=39_500_000,             # conflicting value
        ),
        observed_at=now,
    ),
]

async with open_stdio_client(config, server) as client:
    result = await client.evaluate_assertion(
        observations,
        estimator=estimator,
    )
```

### Use the Evaluation Result

`evaluate_assertion()` returns structured signals your application can use before continuing the agent run. Each evaluated value includes its support score and any conflicting values found in the current evaluation:

```python
for claim in result.claim_support:
    print("Support:", claim.support)                              # support score
    print("Independent support:", claim.estimated_independent_support_count)
    print("Conflicts:", claim.conflicting_claims)                 # conflicting values
```

Feed these signals back into your orchestration logic. Your application might continue normally when support is strong, or trigger another retrieval when the available sources are too dependent. Other workflows can use conflicts to branch execution (request another tool call, invoke a verification step, mandate human review, or withhold disputed context from the next model call).

Omneum returns the evaluation signals without deciding how your agent should act on them.

### How It Fits Together

Omneum sits between the data your agent retrieves and the model call that consumes it.

```text
Retrieval / Tool Calls
        ↓
Observation Objects
        ↓
client.evaluate_assertion()
        ↓
Evaluation Result
        ↓
Application Control Flow
        ↓
Next Model Call
```

Your application decides where evaluation belongs in the workflow and how to act on the returned result. Omneum does not replace your retrieval layer or agent runtime.

## Observation Model

`Observation` is the application-facing input to Omneum. It represents a structured value encountered during an agent run and preserves where that value came from.

A value returned by a retrieval step or tool call is represented as a `Claim`:

```python
claim = Claim(
    entity_namespace="company",
    entity="acme-corp",
    attribute="quarterly_revenue_usd",
    value=42_000_000,
)
```

Here, `Claim` is a structured data model rather than a natural-language statement. It identifies the entity being described, the property being evaluated, and the value returned by the source.

An `Observation` associates that value with its source:

```python
observation = Observation(
    assertion_id="result-1",
    source=Source(
        kind="web_document",
        identifier="https://research.example.com/acme-q3",
    ),
    claim=claim,
    observed_at=now,
)
```

In an agent workflow, observations can be constructed from values already present in tool results, retrieval outputs, or workflow state. Metadata captured during execution can be attached to the observation when available.

### Sources

`Source` identifies the resource or system that produced the observed value.

```python
source = Source(
    kind="internal_service",
    identifier="market-data-api",
    owner_id="research",
)
```

The `kind` describes the type of source, while `identifier` identifies the specific resource within that source type. `owner_id` can be supplied when the application knows that multiple sources are operated by the same owner.

### Claims

`Claim` represents the structured value Omneum evaluates:

```text
(entity_namespace, entity, attribute) → value
```

For example:

```text
("company", "acme-corp", "quarterly_revenue_usd") → 42000000
("company", "acme-corp", "quarterly_revenue_usd") → 39500000
```

Values with the same entity and attribute describe the same property. Different values for that property can therefore be evaluated against one another when they appear across observations.

### Retrieval Metadata

Observations can include metadata about the retrieval or tool call that surfaced the underlying resource during the agent run.

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

`Retrieval` records the execution that surfaced the resource (`tool_call`, `web_search`, etc.), while `Source` identifies the resource that produced the observed value.

This distinction lets Omneum preserve provenance across multi-step agent workflows without treating every retrieval as a new source.

Retrieval metadata is optional. Build observations from the metadata already available in your retrieval layer, tool execution, or orchestration framework.

### Source Relationships

If your agent runtime already knows how one source relates to another, attach that information to the observation. Omneum can use upstream sources, citations, assertion lineage, and source ownership when estimating source dependency.

For example, a research result may have been retrieved from one document while the application knows that its data came from an upstream company filing:

```python
observation = Observation(
    assertion_id="result-1",
    source=Source(
        kind="web_document",
        identifier="https://research.example.com/acme-q3",
    ),
    claim=Claim(
        entity_namespace="company",
        entity="acme-corp",
        attribute="quarterly_revenue_usd",
        value=42_000_000,
    ),
    observed_at=now,
    upstream_sources=(
        Source(
            kind="web_document",
            identifier="https://investors.example.com/acme/q3-results",
        ),
    ),
)
```

If the document explicitly cites another source, record it with `cited_sources`:

```python
observation = Observation(
    ...,
    cited_sources=(
        Source(
            kind="web_document",
            identifier="https://investors.example.com/acme/q3-results",
        ),
    ),
)
```

If the value was produced from an earlier assertion in the same agent run, preserve that execution lineage with `parent_assertion_ids`:

```python
observation = Observation(
    ...,
    parent_assertion_ids=("research-step-12",),
)
```

Known ownership is attached to the source:

```python
source = Source(
    kind="internal_service",
    identifier="market-data-api",
    owner_id="research",
)
```

Pass these fields when the information already exists in your application state, retrieval metadata, tool output, or orchestration runtime. You do not need to infer missing relationships before calling Omneum.

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
    temporal_window_seconds=172_800.0,
)
```

Pass the configuration when evaluating your observations:

```python
async with open_stdio_client(config, server) as client:
    result = await client.evaluate_assertion(
        observations,
        estimator=estimator,
    )
```

The estimator combines source relationships already present in the observation metadata with overlap found across the observations in the current evaluation.

For the research example above, two different URLs do not automatically count as independent sources. If both results came from the same upstream filing, cite one another, share assertion lineage, or belong to the same owner, those signals can increase their estimated dependency.

The temporal signal uses `source_modified_at` when your application has source update timestamps:

```python
observation = Observation(
    ...,
    source_modified_at=source_modified_at,
)
```

You do not need every signal for every source. Missing metadata stays unavailable rather than being inferred by the SDK.

The weights above are Omneum's current baseline configuration and are not calibrated production defaults. Applications can provide different weights and temporal windows for their workload.

## Evaluation Results

`evaluate_assertion()` returns a structured result for the observations in the current evaluation. Use `claim_support` to inspect the support calculated for each distinct value:

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

Use `explain_claim()` with the claim results returned by `evaluate_assertion()`:

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

`explain_dependency()` uses the source metadata retained locally by the SDK to describe which dependency signals were available for the source pair. Depending on the metadata supplied with the observations, this can include upstream relationships, citations, assertion lineage, shared ownership, source update timing, or matching values.

Both helpers run entirely in the Python process. They do not make an MCP request, call an LLM, modify the evaluation result, or send additional data to the Omneum server.

Use the structured result fields for application logic. The explanation helpers are a formatting layer for cases where the same result needs to be readable by a developer or included in downstream context.

## Privacy and Linkage

The Python SDK creates stable linkage tokens for private source, attribute, and claim data before sending an assertion evaluation to the Omneum server.

Source identifiers and structured attribute and claim values are canonicalized and serialized locally. The SDK then uses Omneum's RFC 9497 VOPRF flow to generate linkage tokens without sending those values to the server in plaintext.

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
    temporal_window_seconds=172_800.0,
)

result = await client.evaluate_assertion(
    observations,
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

For the full assertion-evaluation API contract, request and response schemas, validation rules, and server limits, see [`api.md`](docs/api.md).

Implementation details for canonicalization and linkage are documented separately in [`canonicalization.md`](docs/canonicalization.md), including the structured source, attribute, and claim formats used to generate linkage inputs.

The MCP protocol, deployment metadata, and VOPRF request flow are covered in [`protocol.md`](docs/protocol.md). Additional cryptographic implementation details and interoperability requirements are documented alongside the protocol documentation.

For examples of integrating Omneum into agent workflows, see the [`examples/`](../examples/) directory.

## Contributing

Contributions are welcome. Whether you find a bug, run into an integration issue, or want to propose a change to documentation, please open an issue with enough detail to reproduce the behavior.

Development and contribution guidelines will be added as the SDK moves beyond the current design-partner release.

## License

Omneum is licensed under the terms in [`LICENSE`](../LICENSE).