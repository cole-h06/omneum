# Omneum Architecture

Omneum evaluates structured information before it is passed further into an agent workflow.

The Python SDK handles application adaptation, dependency estimation, and private linkage. The MCP server builds the evaluation graph and runs BRAID reliability propagation.

## 1. Evaluation Path

```text
Retrieval / Tools / Workflow State
              ↓
       Application Data
              ↓
      Semantic Normalization
              ↓
StructuredAssertion / ContextMapper
              ↓
       Canonical Observations
              ↓
      Dependency Estimation
              ↓
    Privacy-Preserving Linkage
              ↓
        Omneum MCP Server
              ↓
      Bipartite Graph
              ↓
 BRAID Reliability Propagation
              ↓
       Evaluation Result
              ↓
       Agent Control Flow
```

Semantic normalization belongs to the application. Omneum does not use an LLM to decide whether two differently expressed pieces of information represent the same structured assertion.

Provenance can be partial. If the runtime has it, map it. If it doesn't, leave it unset.

Missing provenance is not observed independence.

## 2. Application Integration

Applications normally enter the SDK through `StructuredAssertion` or `ContextMapper`.

### `StructuredAssertion`

Use `StructuredAssertion` when the application already has a normalized assertion and knows which sources supplied it.

An assertion has the form:

```text
(entity_namespace, entity, attribute) → value
```

The application supplies that structured value and its supporting sources.

### `ContextMapper`

Use `ContextMapper` when the same information already exists in retrieval results, tool outputs, connector records, models, or workflow state.

```text
Application Record
       ↓
 ContextMapper
       ↓
Canonical Observation
```

The mapper tells Omneum where its canonical fields exist in the application's data.

Source lineage, citations, assertion lineage, source timestamps, and retrieval records should be mapped when the runtime already has them.

Do not manufacture provenance to fill the schema.

Application-specific fields that do not correspond to canonical provenance can remain under `metadata`. Arbitrary metadata does not automatically affect dependency estimation.

See [`context_mapper.md`](context_mapper.md) for the mapping contract.

## 3. Canonical Observations

Both high-level entry paths produce observations.

An observation associates a structured claim with the source that produced it:

```text
Source ──asserts──> Claim
```

It can also retain the provenance needed by the dependency estimator.

The relevant boundary is:

```text
application representation
          ↓
       Observation
          ↓
dependency + linkage + evaluation
```

Canonicalization is also used to produce deterministic byte representations for private values that need stable linkage.

The encoding rules are documented in [`canonicalization.md`](canonicalization.md).

## 4. Dependency Estimation

BRAID should not treat every source attached to a claim as independent support.

A search result, copied document, derived agent output, or duplicated retrieval may ultimately depend on information already represented elsewhere in the graph.

The SDK estimates pairwise source dependency before sending the evaluation to the server.

It can derive dependency from these canonical signals:

```text
upstream
citation
assertion_lineage
ownership
temporal
graph
retrieval
```

Concrete provenance is preferred. Explicit `DependencySignal` values are available for integrations that already compute something with the same semantics, but most integrations should not start there.

### Missing signals

A missing signal and an observed zero are different:

```python
DependencySignal(value=0.0, observable=True)
DependencySignal(value=0.0, observable=False)
```

The first means the required information was available and indicated zero dependency on that axis.

The second means the information was unavailable.

Unavailable signals are not inserted into the dependency calculation as zero-valued observations.

### Pairwise dependency

For a source pair, the estimator combines the signals it could actually observe.

Dependency is normalized over those observable signals. Weighted signal coverage is reported separately.

For example, if upstream provenance is the only observable signal and establishes complete dependency:

```text
upstream = 1.0
```

then the pair can have:

```text
dependency = 1.0
```

even if upstream represents only part of the configured signal weight.

Coverage records that difference. It does not dilute the observed upstream relationship.

The pairwise estimates are then used to derive the independence weights BRAID applies during propagation.

## 5. Privacy-Preserving Linkage

The server needs stable identifiers for sources and structured assertion data, but it does not need their plaintext values.

The SDK derives opaque linkage tokens using an RFC 9497 VOPRF with the `ristretto255-SHA512` ciphersuite.

```text
Private Value
     ↓
Canonicalize + Serialize
     ↓
Blind
     ↓
Server VOPRF Evaluation
     ↓
Verify + Unblind + Finalize
     ↓
Linkage Token
```

Blinding and finalization happen on the client.

The server evaluates the blinded element with its VOPRF private key and returns the evaluated element and proof. The client verifies the proof before finalizing the token.

Matching encoded inputs under the same linkage configuration produce stable opaque identifiers.

This is linkage privacy, not general request encryption. The server can still observe protocol traffic and relationships among opaque identifiers submitted during evaluation.

See [`protocol.md`](protocol.md) for the wire protocol and VOPRF flow.

## 6. Bipartite Graph

BRAID operates on a bipartite graph with sources and claims as nodes. Assertions are the edges.

```text
S1 ───── C1
│
└─────── C2
          │
S2 ──────┘

S3 ───── C3
```

A source can assert multiple claims. A claim can be supported by multiple sources.

That shared structure is what makes propagation useful. Reliability learned through one part of the graph can affect another part through their shared source and claim relationships.

The server constructs the graph from opaque source and claim identifiers. It does not need the plaintext values represented by those identifiers.

## 7. BRAID Reliability Propagation

BRAID is the reliability algorithm run over the graph.

It alternates between source-to-claim and claim-to-source propagation until the scores converge:

```text
Source scores
     ↓
source → claim propagation
     ↓
Claim scores
     ↓
claim → source propagation
     ↓
Updated source scores
     ↓
    repeat
```

### Source → claim

Reliability flowing from a source to a claim is adjusted by the assertion's agreement weight and independence weight.

Conceptually:

```text
source reliability
        ×
agreement weight
        ×
independence weight
        ↓
claim
```

The independence term comes from the dependency estimates calculated by the SDK.

This is where dependency affects BRAID directly. Sources estimated to depend on one another do not contribute as though each were a fully independent path of support.

Source degree is also accounted for so a source does not gain influence merely by asserting more claims.

### Claim → source

Claim reliability then propagates back to the sources asserting it.

The reverse pass accounts for the number of sources supporting the claim before updating source scores.

The next iteration uses those updated source scores for another source-to-claim pass.

### Convergence

BRAID repeats these passes until the score change falls below the configured convergence tolerance or the iteration limit is reached.

The resulting source and claim scores come from the graph structure and propagation process. They are not probabilities that a source or claim is correct.

Dependency estimation is part of this calculation, not a replacement for it. It controls how much apparently separate support should behave as independent support while reliability moves through the graph.

## 8. Evaluation Results

The server returns the graph evaluation as structured SDK data.

Claim results include the propagated support score and conflict information. The evaluation also exposes dependency-derived values such as estimated independent support and pairwise dependency.

`estimated_independent_support_count` is not the BRAID propagation score. It is a separate diagnostic derived from supporting-source count and estimated dependency.

That distinction matters when interpreting results:

```text
support
    = graph propagation result

estimated_independent_support_count
    = dependency-adjusted source count

pairwise_dependencies
    = source-pair dependency estimates
```

Applications can use those values for routing, retrieval, verification, or other policy decisions. Omneum does not prescribe the threshold or routing policy.

## 9. Client / Server Boundary

The SDK keeps application-specific information on the client where the server does not need it.

### Client

The client handles:

- `StructuredAssertion` and `ContextMapper` adaptation
- canonical observations and provenance
- dependency signal derivation
- pairwise dependency estimation
- linkage-input canonicalization
- VOPRF blinding, verification, and finalization
- evaluation request construction

### Server

The server handles:

- MCP requests
- VOPRF evaluation with the deployment key
- evaluation-request validation
- graph construction
- BRAID reliability propagation
- structured evaluation responses

Raw source identifiers, structured values, detailed provenance, and retrieval records do not need to be sent to the server for graph evaluation.

The server receives opaque linkage identifiers and the numeric source-pair information needed by BRAID.

## 10. Deployment

Initialize a local deployment with:

```bash
omneum init
```

Local deployment state contains:

```text
config.toml
keys/
└── voprf.key
```

`config.toml` contains non-secret deployment configuration. `keys/voprf.key` contains the VOPRF private key and must not be committed.

The current Python SDK connects to the local MCP server over `stdio`.

```text
Application
    │
Python SDK
    │
MCP stdio
    │
Omneum Server
```

Remote transport is not currently supported by the Python SDK.

## 11. State

Open-source assertion evaluation is request-scoped.

For each evaluation, the server receives the required inputs, constructs the graph, runs BRAID, and returns the result.

The local MCP server does not require the hosted Omneum database.

VOPRF key material persists across requests because stable linkage depends on the deployment key.

Organizations, workspaces, agents, historical evaluations, and other persistent control-plane state belong to the hosted deployment rather than the local evaluation path.

## 12. Trust Boundary

The client retains the private application values used to construct linkage inputs.

This includes raw source identifiers, structured assertion values, provenance, retrieval records, and application metadata.

During VOPRF linkage, the server receives blinded inputs.

During assertion evaluation, it receives opaque linkage identifiers and the numeric dependency information required by BRAID.

The server can therefore observe relationships among opaque identifiers and the structure submitted for an evaluation. VOPRF does not hide that structure.

New protocol fields should not move raw application provenance across this boundary unless the server actually requires it.