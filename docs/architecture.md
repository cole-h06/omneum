# Omneum Architecture

Omneum evaluates structured information before it enters downstream agent control flow.

The Python SDK adapts application data into Omneum's canonical representation, estimates source dependencies, and performs client-side VOPRF operations. The Python MCP server validates evaluation requests, constructs the source-claim graph, and runs BRAID. Server-side VOPRF evaluation is isolated in `omneumd`, a Rust daemon that owns the deployment private key and exposes a narrow local evaluation interface to the MCP process.

## 1. Evaluation Path

~~~text
Retrieval / Tools / Workflow State
                │
                ▼
        Application Data
                │
                ▼
       Semantic Normalization
                │
                ▼
 StructuredAssertion / ContextMapper
                │
                ▼
       Canonical Observations
                │
                ▼
       Dependency Estimation
                │
                ▼
    Privacy-Preserving Linkage
                │
                │ blinded VOPRF request
                ▼
        Python MCP Server
                │
                │ authenticated local IPC
                ▼
             omneumd
                │
                │ evaluation + proof
                ▼
        Python MCP Server
                │
                │ VOPRF response
                ▼
              SDK
                │
                │ verify + finalize
                ▼
         Linkage Tokens
                │
                ▼
        Python MCP Server
                │
                ▼
         Bipartite Graph
                │
                ▼
    BRAID Reliability Propagation
                │
                ▼
        Evaluation Result
                │
                ▼
        Agent Control Flow
~~~

Semantic normalization is an application responsibility. Omneum does not use an LLM to infer that differently expressed values represent the same structured assertion.

Provenance is optional and may be incomplete. Integrations should map provenance that exists in the originating runtime and leave unavailable fields unset. Missing provenance is not evidence of independence.

## 2. Application Integration

Applications enter the SDK through `StructuredAssertion` or `ContextMapper`.

### `StructuredAssertion`

`StructuredAssertion` is the direct integration path for applications that already represent information as normalized assertions and know which sources supplied each value.

An assertion is represented as:

~~~text
(entity_namespace, entity, attribute) → value
~~~

The application supplies the structured value, supporting sources, and any provenance available for those sources.

### `ContextMapper`

`ContextMapper` adapts existing application records into Omneum observations without requiring the application to reshape its internal data model first.

~~~text
Application Record
        │
        ▼
   ContextMapper
        │
        ▼
Canonical Observation
~~~

The mapper defines how application fields map to Omneum's canonical source, entity, attribute, value, assertion, timestamp, and provenance fields.

Source lineage, citations, assertion lineage, source timestamps, and retrieval records should be mapped when the originating runtime exposes them. Integrations should not synthesize provenance solely to populate the schema.

Application-specific fields without canonical provenance semantics can remain under `metadata`. Arbitrary metadata is not interpreted as a dependency signal.

See [`context_mapper.md`](context_mapper.md) for the mapping contract.

## 3. Canonical Observations

Both integration paths produce observations.

An observation records a source asserting a structured claim:

~~~text
Source ──asserts──> Claim
~~~

The observation also carries the provenance available to the dependency estimator.

~~~text
application representation
          │
          ▼
      Observation
          │
          ├── dependency estimation
          ├── private linkage
          └── evaluation
~~~

Canonicalization provides deterministic representations for source and assertion identity. Private linkage inputs are serialized deterministically before VOPRF blinding so equivalent canonical inputs produce the same linkage input bytes.

See [`canonicalization.md`](canonicalization.md) for canonicalization and encoding rules.

## 4. Dependency Estimation

Multiple sources attached to the same claim are not assumed to represent independent support.

Copied documents, derived agent outputs, duplicated retrievals, common upstream sources, and other shared provenance can create dependency between sources. The SDK estimates pairwise source dependency before constructing the evaluation request sent to the MCP server.

The estimator derives dependency from canonical signals:

~~~text
upstream
citation
assertion_lineage
ownership
temporal
graph
retrieval
~~~

Integrations should prefer observed provenance over manually supplied scores. `DependencySignal` is available when an integration already computes a signal with the corresponding Omneum semantics.

### Missing signals

An observed zero and an unavailable signal have different meanings:

~~~python
DependencySignal(value=0.0, observable=True)
DependencySignal(value=0.0, observable=False)
~~~

`observable=True` means the information required to evaluate that signal was available. A value of zero means that mechanism produced no dependency evidence.

`observable=False` means the signal could not be evaluated from the available information.

Unavailable signals are excluded from the dependency calculation. An observed zero on one mechanism does not weaken positive dependency evidence from another mechanism.

### Pairwise dependency

For each source pair, the estimator takes the strongest observed, non-excluded dependency signal.

Signals represent different mechanisms through which sources may be dependent. An observed zero on one mechanism is therefore not counterevidence to positive dependency evidence from another mechanism.

Weighted signal coverage is reported separately using the configured signal weights, so a strong result derived from limited provenance remains distinguishable from one derived from broad provenance coverage.

For example, if upstream lineage is the only observable signal and establishes complete dependency:

~~~text
upstream = 1.0
~~~

the pairwise dependency can be:

~~~text
dependency = 1.0
~~~

Coverage records that only part of the configured dependency model was observable. It does not weaken the dependency relationship that was actually observed.

Pairwise dependency is converted into the claim-specific independence weights consumed by BRAID.

## 5. Privacy-Preserving Linkage

The MCP server requires stable identities for sources and structured assertion data, but graph evaluation does not require their plaintext values.

Omneum derives opaque linkage tokens using RFC 9497 VOPRF mode with the `ristretto255-SHA512` ciphersuite.

~~~text
Client SDK                    MCP Server                    omneumd
    │                             │                            │
    │ canonicalize + serialize    │                            │
    │ blind                       │                            │
    │                             │                            │
    ├──── blinded element ───────►│                            │
    │                             ├──── blinded element ──────►│
    │                             │                            │ evaluate
    │                             │                            │ with k
    │                             │                            │
    │                             │◄── evaluation + proof ─────┤
    │◄── evaluation + proof ──────┤                            │
    │                             │                            │
    │ verify + finalize           │                            │
    ▼                             │                            │
Linkage Token
~~~

The SDK performs canonicalization, blinding, proof verification, and finalization. Client-side cryptographic operations use the native extension.

The MCP server forwards blinded elements to `omneumd` over authenticated local IPC. It receives the evaluated element and proof and returns them to the SDK.

`omneumd` owns the deployment private key and performs the secret-bearing VOPRF operation. The MCP process does not load the private key or receive a secret-bearing VOPRF server context.

The SDK verifies the returned proof against the configured public key before finalizing the linkage token.

Equivalent encoded inputs evaluated under the same deployment key produce stable opaque linkage tokens.

VOPRF provides linkage privacy; it does not encrypt the evaluation protocol. The MCP server can observe protocol traffic, opaque identifiers submitted later for graph evaluation, and relationships among those identifiers.

See [`protocol.md`](protocol.md) for the VOPRF and MCP wire contracts.

## 6. Bipartite Graph

BRAID operates on a bipartite graph containing source nodes and claim nodes. Assertions form edges between the two partitions.

~~~text
S1 ───── C1
│
└─────── C2
          │
S2 ──────┘

S3 ───── C3
~~~

A source can assert multiple claims, and multiple sources can assert the same claim.

Shared source-claim structure allows reliability to propagate across the graph. A source connected to several claims participates in each of those claim evaluations, while a claim supported by several sources receives reliability through each corresponding assertion edge.

The MCP server constructs this graph from opaque source and claim identifiers. Plaintext source identifiers and structured assertion values are not required for graph construction.

## 7. BRAID Reliability Propagation

BRAID propagates reliability over the source-claim graph.

Each iteration consists of a source-to-claim pass followed by a claim-to-source pass:

~~~text
Source scores
     │
     ▼
source → claim
     │
     ▼
Claim scores
     │
     ▼
claim → source
     │
     ▼
Updated source scores
     │
     └──────── repeat
~~~

### Source → claim

Reliability contributed by a source to a claim is adjusted by the assertion's agreement and independence weights.

~~~text
source reliability
        ×
agreement weight
        ×
independence weight
        │
        ▼
      claim
~~~

The independence weight is derived from the pairwise dependency estimates produced by the SDK. Sources estimated to depend on one another therefore do not contribute as fully independent support.

Source degree is included in the propagation term so adding additional asserted claims does not by itself increase a source's total influence.

### Claim → source

Claim reliability propagates back to the sources asserting the claim.

The reverse pass accounts for the number of sources attached to the claim before updating source scores. Those updated source scores become the input to the next source-to-claim pass.

### Convergence

BRAID repeats the two propagation passes until the score delta falls below the configured convergence tolerance or the iteration limit is reached.

Source and claim scores are graph-derived reliability scores. They are not probabilities that a source or claim is factually correct.

Dependency estimation modifies the independence of support entering propagation; it does not replace BRAID propagation.

## 8. Evaluation Results

The MCP server returns the graph evaluation as structured SDK data.

Claim results contain the propagated support score and conflict information. The result also exposes dependency-derived diagnostics including estimated independent support and pairwise source dependency.

`estimated_independent_support_count` is distinct from the BRAID propagation score:

~~~text
support
    = BRAID graph propagation result

estimated_independent_support_count
    = dependency-adjusted supporting-source count

pairwise_dependencies
    = estimated dependency between source pairs
~~~

Applications can use these values in retrieval, routing, verification, escalation, or other control policies. Threshold selection and downstream policy remain application responsibilities.

## 9. Execution Boundaries

Omneum's local evaluation path spans three execution components with separate responsibilities.

~~~text
┌─────────────────────────┐
│       Client SDK        │
│                         │
│ application adaptation  │
│ dependency estimation   │
│ VOPRF client operations │
└────────────┬────────────┘
             │
             │ MCP stdio
             ▼
┌─────────────────────────┐
│    Python MCP Server    │
│                         │
│ request validation      │
│ graph construction      │
│ BRAID propagation       │
└────────────┬────────────┘
             │
             │ authenticated AF_UNIX
             ▼
┌─────────────────────────┐
│        omneumd          │
│                         │
│ VOPRF private key       │
│ blinded evaluation      │
│ proof generation        │
└─────────────────────────┘
~~~

### Client SDK

The client handles:

- `StructuredAssertion` and `ContextMapper` adaptation
- canonical observations and provenance
- dependency signal derivation
- pairwise dependency estimation
- linkage-input canonicalization
- VOPRF blinding, proof verification, and finalization
- evaluation request construction

### Python MCP Server

The MCP server handles:

- MCP request handling
- evaluation-request validation
- forwarding blinded VOPRF elements to `omneumd`
- returning VOPRF evaluations and proofs to the SDK
- graph construction
- BRAID reliability propagation
- structured evaluation responses

The MCP process does not own or load the VOPRF deployment private key.

### `omneumd`

`omneumd` handles:

- VOPRF deployment private-key ownership
- public-key retrieval
- blinded-element evaluation
- VOPRF proof generation

The daemon accepts only the local VOPRF operations required by the MCP server. Graph construction, dependency processing, assertion evaluation, and BRAID remain outside the daemon.

Raw source identifiers, structured values, detailed provenance, and retrieval records are not required by the MCP server for graph evaluation. The MCP server receives opaque linkage identifiers and the numeric dependency information consumed by BRAID.

## 10. Deployment

Protected local serving is supported on Linux and macOS. See [Linux installation](../deploy/README.md) for automated daemon setup.

`omneum-server` and `omneumd` must run under distinct non-root OS identities. The VOPRF private key belongs to the `omneumd` security domain and must not be readable by the MCP identity.

~~~text
Application
     │
     │ MCP stdio
     ▼
┌──────────────────────┐
│    omneum-server     │
│                      │
│ identity: omneum-mcp │
└──────────┬───────────┘
           │
           │ authenticated Unix socket
           ▼
┌─────────────────────────┐
│        omneumd          │
│                         │
│ identity: omneum-crypto │
│ owns: voprf.key         │
└─────────────────────────┘
~~~

A shared `omneum-ipc` group grants the MCP identity access to the daemon socket without granting access to the private key. The installed daemon binary and service configuration must be administrator-owned and unwritable by either application identity.

The private key is provisioned administratively and retained across daemon restarts. Stable linkage under a deployment depends on retaining the same deployment key. `omneum-server` stores only public deployment configuration, including the pinned VOPRF public key and daemon endpoint.

The daemon authenticates its local peer using kernel-provided credentials. Linux uses `SO_PEERCRED`; macOS uses `getpeereid()`. The socket credential check authenticates the configured MCP OS identity, not an individual Python PID.

Production builds must not enable the `test-daemon` feature or daemon test mode.

Native protected local serving is not supported on Windows. Windows builds retain client-side VOPRF functionality.

The Python SDK currently communicates with the local MCP server over `stdio`. Remote SDK transport is not part of the current local deployment architecture.

## 11. State

Open-source assertion evaluation is request-scoped.

For each evaluation request, the MCP server validates the submitted graph inputs, constructs the source-claim graph, runs BRAID, and returns the resulting evaluation. The local evaluation path does not require the hosted Omneum database.

The VOPRF deployment key is persistent state owned by `omneumd`. The daemon loads the key into its server context at startup and retains that context for its lifetime.

The MCP process retains public deployment configuration and the information required to connect to the daemon. It does not retain the VOPRF private key.

Organizations, workspaces, agents, historical evaluations, and other persistent control-plane state belong to the hosted deployment rather than the open-source local evaluation path.

## 12. Trust Boundaries

The client retains application data that is not required for server-side graph evaluation, including raw source identifiers, structured assertion values, detailed provenance, retrieval records, and application metadata.

The VOPRF path crosses two boundaries:

~~~text
private linkage input
        │
        │ client-side blind
        ▼
blinded element
        │
        │ MCP
        ▼
Python MCP Server
        │
        │ authenticated local IPC
        ▼
     omneumd
        │
        │ evaluation + proof
        ▼
Python MCP Server
        │
        │ MCP
        ▼
Client SDK
        │
        │ verify + finalize
        ▼
opaque linkage token
~~~

The MCP server receives blinded VOPRF elements but not the private linkage inputs from which they were derived. `omneumd` receives blinded elements and owns the deployment private key. The private key does not cross the daemon boundary.

During assertion evaluation, the MCP server receives opaque source and claim identifiers together with the numeric dependency information required by BRAID. It can observe the submitted graph structure and relationships among opaque identifiers.

VOPRF does not conceal graph topology or other information explicitly included in an evaluation request.

Protocol changes should preserve these boundaries. Raw application provenance or private linkage inputs should not cross into the MCP or daemon security domains unless a protocol operation requires them.