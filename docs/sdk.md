# Omneum Python SDK

This document covers the Python SDK for interacting with an Omneum server.

For a shorter end-to-end setup, start with the repository [`README`](../README.md). For the complete `ContextMapper` field contract, see [`context_mapper.md`](context_mapper.md).

## Getting Started

### Install Omneum

Omneum currently supports CPython 3.11 through 3.14.

Install uv 0.12.10 and a Rust toolchain, then install Omneum from a source checkout:

```bash
git clone https://github.com/cole-h06/omneum.git
cd omneum
uv sync --locked --no-default-groups
source .venv/bin/activate
```

If you're developing Omneum itself:

```bash
uv sync --locked
uv run --locked pytest
```

### Initialize Omneum

First follow the [daemon deployment instructions](architecture.md#10-deployment), then initialize the public configuration as `omneum-mcp`:

```bash
omneum init
```

This obtains the initial public key from the authenticated daemon and creates public deployment configuration only.

### Connect to the server

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

## Evaluation Paths

There are two normal entry points into assertion evaluation.

Use `StructuredAssertion` when the application already has a normalized assertion and knows which sources supplied it.

Use `ContextMapper` when the same information already exists inside retrieval results, tool outputs, connector records, Pydantic models, or workflow state.

Both paths feed the same evaluation pipeline.

### `StructuredAssertion`

An assertion is identified by:

```text
(entity_namespace, entity, attribute) → value
```

For example:

```text
("service", "acme-corp", "quarterly_revenue_usd") → 42000000
```

Construct it directly when your application already has that structure:

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

This is the high-level path. You do not need to construct `Observation`, `Claim`, `Retrieval`, or `SourceReference` objects unless you need the lower-level API.

Semantic normalization remains an application responsibility. Omneum does not use an LLM to decide whether differently worded retrieved content represents the same structured assertion.

Once the application establishes that boundary, the SDK handles canonicalization, privacy-preserving linkage, dependency estimation, and assertion evaluation.

### `ContextMapper`

Most agent applications already have their own result objects. Don't rebuild them just to satisfy Omneum's internal representation.

Suppose a retrieval branch produces:

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

Define where the canonical fields live:

```python
from omneum import ContextMapper, Source

mapper = ContextMapper(
    source=lambda result: Source(
        kind="web_document",
        identifier=result["url"],
    ),
    entity_namespace=lambda result: "service",
    entity="company",
    attribute=lambda result: "quarterly_revenue_usd",
    value="revenue",
    assertion_id="id",
    observed_at=lambda result: now,
)
```

Then evaluate the mapped records:

```python
result = await client.evaluate_mapped(
    results,
    mapper,
    estimator=estimator,
)
```

Field mappings can use dotted field paths or callables. Callables are useful when extraction or application-defined normalization requires some logic:

```python
mapper = ContextMapper(
    ...,
    value=lambda result: normalize_revenue(result),
)
```

`ContextMapper` is also the boundary where provenance already captured by the application can enter Omneum.

If the runtime knows a source's upstream origin, modification time, citations, assertion lineage, or retrieval history, map it.

If it doesn't know, leave it unset.

Do not manufacture provenance to fill the schema.

See [`context_mapper.md`](context_mapper.md) for the complete field contract, source identity rules, lineage semantics, retrievals, and explicit dependency signals.

## Runtime Provenance

`AssertionSource` can carry additional context when the application already has it:

```python
source = AssertionSource(
    source=Source(
        kind="web_document",
        identifier="https://research.example.com/acme-q3",
        owner_id="research",
    ),
    assertion_id="research-result",
    observed_at=now,
    source_modified_at=source_modified_at,
    upstream_sources=upstream_sources,
    cited_sources=citations,
    parent_assertion_ids=parent_assertion_ids,
    retrievals=retrievals,
)
```

These fields have different semantics.

`upstream_sources` describes source-level origin or derivation.

`cited_sources` records explicit source references.

`parent_assertion_ids` identifies the direct parent assertions from which an assertion was derived. The v2 assertion-lineage signal evaluates these direct relationships; it does not infer transitive ancestry.

`retrievals` records retrieval executions that surfaced the information.

`source_modified_at` is the source's own known modification time. Do not substitute `observed_at` when that timestamp is unavailable. Leave it unset when the available timestamp is too coarse for the configured temporal window.

Extra application context can be retained as metadata:

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

Arbitrary metadata does not automatically participate in dependency estimation.

That is intentional. A request ID or tool-specific field should not become dependency evidence merely because the integration happened to preserve it.

## Explicit Dependency Signals

Applications normally supply concrete provenance and let Omneum derive the corresponding dependency signals.

There is also an escape hatch for integrations that already have a signal expressed in Omneum's canonical semantics.

The supported signal names are:

```text
upstream
citation
assertion_lineage
ownership
temporal
graph
retrieval
```

An explicit signal is represented by `DependencySignal`:

```python
from omneum import DependencySignal

signal = DependencySignal(
    value=1.0,
    observable=True,
)
```

`value` must be between `0.0` and `1.0`.

The `observable` flag matters.

These two states are not equivalent:

```python
DependencySignal(value=0.0, observable=True)
DependencySignal(value=0.0, observable=False)
```

The first says the integration had information about the relationship and observed zero dependency on that axis.

The second says the relationship was not observed.

Do not convert missing application fields into observable zero-valued signals.

Likewise, don't use `dependency_signals` as a generic bag for runtime-specific metadata. Preserve application-specific fields under `metadata`; use explicit signals only when the integration already has a value matching one of the canonical signal semantics.

## Dependency Estimation

The SDK estimates pairwise source dependency from the provenance and structural information available in the current evaluation.

Start with the default configuration unless you have a reason to change it:

```python
from omneum import DependencyEstimatorConfig

estimator = DependencyEstimatorConfig()
```

Pass it with either evaluation path:

```python
result = await client.evaluate(
    assertion,
    estimator=estimator,
)
```

or:

```python
result = await client.evaluate_mapped(
    results,
    mapper,
    estimator=estimator,
)
```

Two different source identifiers do not automatically imply independence.

Sources may share an upstream origin, cite one another, descend from related assertions, share ownership, identify the same retrieved resource, or exhibit structural relationships within the current evaluation.

Omneum uses whichever of those signals are actually observable.

### Missing signals

You do not need every signal for every source pair.

Missing metadata stays unavailable rather than being inferred by the SDK, and an absent observation is not treated as evidence of independence.

Suppose upstream provenance is the only observable signal for a pair and establishes complete dependency:

```text
upstream           = 1.0
ownership          = unknown
citation           = unknown
assertion_lineage  = unknown
...
```

The estimator takes the strongest observed, non-excluded dependency signal. An observed zero on another dependency mechanism does not dilute positive upstream evidence.

With an upstream weight of `0.25`, the result can therefore be:

```text
dependency                = 1.0
weighted_signal_coverage  = 0.25
```

Those values describe different things.

`dependency` is the estimate produced from the information that was observed.

`weighted_signal_coverage` records how much of the configured signal space was observable for the pair.

Low coverage does not dilute an observed dependency relationship into apparent independence.

It also should not be read as a probability that the dependency estimate is correct.

### Temporal information

The temporal signal uses `source_modified_at` when the runtime exposes a source update timestamp:

```python
source = AssertionSource(
    ...,
    source_modified_at=source_modified_at,
)
```

If the source modification time is unknown or too coarse for the configured temporal window, leave it unset.

### Custom estimator configuration

`DependencyEstimatorConfig` exposes weights and temporal-window configuration for applications that need to tune the estimator.

These are application settings, not deployment settings.

The baseline configuration is not a calibrated production model. Do not interpret its weights as validated for a particular workload.

## Evaluation Results

`evaluate()` and `evaluate_mapped()` return the same structured evaluation result.

Inspect claim-level support through `claim_support`:

```python
for claim in result.claim_support:
    print("Support:", claim.support)
    print(
        "Independent support:",
        claim.estimated_independent_support_count,
    )
    print("Conflicts:", claim.conflicting_claims)
```

### `support`

`support` is the graph score calculated for that value from its supporting sources.

It is not a probability that the value is correct.

### `estimated_independent_support_count`

`estimated_independent_support_count` adjusts raw supporting-source count according to estimated dependency among those sources.

Several sources can therefore support the same value without being counted as several fully independent observations.

### `conflicting_claims`

Different values for the same normalized entity and attribute remain separate.

For example:

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

A workflow can use the conflict information directly:

```python
for claim in result.claim_support:
    if claim.conflicting_claims:
        # Retrieve again, route to another check, or apply application policy.
        ...
```

### Pairwise dependency

The result also contains the pairwise dependency data calculated for the evaluation.

This lets application code inspect which supporting sources were estimated to depend on one another and how much signal coverage was available for each pair.

Omneum returns these values as structured SDK data. Routing policy stays in the application.

## Local Explanations

Omneum includes local formatting helpers for inspecting evaluation results during development or turning structured results into readable downstream context.

Format claim results with `explain_claim()`:

```python
from omneum import explain_claim

for claim in result.claim_support:
    print(explain_claim(claim))
```

Format source-dependency results with `explain_dependency()`:

```python
from omneum import explain_dependency

for dependency in result.pairwise_dependencies:
    print(explain_dependency(dependency))
```

The helpers format information already present in the local result and retained SDK context.

They do not run another evaluation or call an LLM.

They also do not change the evaluation result.

Use the structured fields for application logic. The explanation helpers are just a formatting layer.

## Lower-Level Observation API

`Observation` is the source-specific representation underneath the high-level SDK paths.

An observation associates a `Claim` with a source and can retain source relationships, timestamps, retrieval records, assertion lineage, application metadata, and explicit dependency signals.

`client.evaluate_assertion()` accepts observations directly.

Most integrations shouldn't start here.

Use it when the integration actually needs control over the complete observation representation. Otherwise, `StructuredAssertion` or `ContextMapper` is less machinery.

All entry paths feed the same assertion-evaluation pipeline.

## Privacy and Linkage

The Python SDK creates stable linkage tokens for private source and structured assertion data before assertion evaluation reaches the server.

Source identifiers and structured linkage values are canonicalized and serialized locally. The SDK then uses Omneum's RFC 9497 VOPRF flow to derive linkage tokens without sending those values to the server in plaintext.

Applications using the high-level evaluation API do not need to construct VOPRF requests themselves.

The flow is:

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

The client blinds the encoded input locally. The server evaluates the blinded element with its VOPRF key and returns the evaluated element and proof. The client verifies the proof, unblinds the result, and finalizes it into the linkage token.

Matching encoded inputs resolve to stable opaque identifiers within the same linkage configuration.

Raw source identifiers and structured linkage values remain on the client during token generation.

This is not general request encryption.

The server can still observe protocol traffic and relationships among opaque identifiers submitted during evaluation. VOPRF protects the private input used to derive a token; it does not make the rest of the MCP interaction invisible.

The SDK handles blinding, proof verification, finalization, and token encoding automatically through the high-level evaluation API.

## Configuration

`omneum init` obtains the initial public key from the authenticated daemon and creates public configuration. Existing pins are preserved; `--public-key-hex` optionally checks an expected key. See [daemon deployment instructions](architecture.md#10-deployment).

Load it with:

```python
from omneum import OmneumClientConfig

config = OmneumClientConfig.from_local_deployment()
```

By default, Omneum stores local deployment state in the platform-specific application configuration directory.

Set `OMNEUM_CONFIG_DIR` to use another location:

```bash
export OMNEUM_CONFIG_DIR=/path/to/omneum
```

A local deployment keeps non-secret configuration separate from its VOPRF private key:

```text
config.toml  # Python: public metadata only
# Separate crypto identity: protected directory containing voprf.key
```

Never retain an MCP-readable private-key copy; follow the [daemon deployment instructions](architecture.md#10-deployment).

For local `stdio`, `from_local_deployment()` loads the deployment ID, VOPRF settings, linkage-encoding version, and pinned server public key required by the client.

Dependency-estimator settings belong to the application rather than the deployment:

```python
from omneum import DependencyEstimatorConfig

estimator = DependencyEstimatorConfig()

result = await client.evaluate(
    assertion,
    estimator=estimator,
)
```

## Known Limitations

- **Remote transport** is not currently supported by the Python SDK. Client connections use a local MCP server over `stdio`.

- **Python support** currently covers CPython 3.11 through 3.14. JavaScript and TypeScript SDKs are not yet available.

- **Token metadata storage** is not managed automatically by the SDK. Applications that persist linkage tokens are responsible for retaining the deployment, key version, linkage configuration, purpose, and token metadata needed to compare them correctly.

- **Key rotation** currently supports one active VOPRF key at a time. Overlapping old and new keys during a rotation is not supported.

- **Assertion evaluation over `stdio`** reads a complete newline-delimited MCP frame before application-level validation. A pre-parse frame-size limit is not currently available through the installed MCP SDK.

- **Timed-out assertion evaluations** cannot forcibly terminate the underlying Python work. The evaluation continues to hold its capacity slot until that work exits.

- **Dependency-estimator weights** are configuration values rather than calibrated production defaults. Applications should not interpret the baseline weights as validated for a specific workload.

- **Dependency clusters** require an explicit threshold. Omneum does not currently provide a default or calibrated clustering threshold.

## Related Documentation

- [`context_mapper.md`](context_mapper.md) — Complete `ContextMapper` field contract, source identity, lineage semantics, retrievals, missing-data behavior, and explicit dependency signals.

- [`api.md`](api.md) — Assertion-evaluation request and response schemas, validation rules, server limits, and errors.

- [`canonicalization.md`](canonicalization.md) — Canonical source, entity, attribute, and value encodings used to construct deterministic linkage inputs.

- [`protocol.md`](protocol.md) — MCP transport, deployment metadata, linkage flow, and VOPRF protocol behavior.

- [`../examples/`](../examples/) — Agent and framework integration examples.

## Contributing

If you find a bug or hit an integration boundary that doesn't fit the data your runtime actually exposes, open an issue with enough detail to reproduce it.

In particular, don't work around an awkward provenance mapping by inventing metadata. If the SDK makes information your runtime already has difficult to represent, that's useful feedback.

Development and contribution guidelines will be expanded as the SDK moves beyond the current early release.

## License

Omneum is licensed under the terms in [`LICENSE`](../LICENSE).
