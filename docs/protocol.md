# Omneum Protocol

## 1. Introduction

The Omneum Protocol defines the interoperability contract between clients and
Omneum deployments. It describes how clients transform canonical structured
values into privacy-preserving linkage tokens and submit assertion graphs for
assertion evaluation.

The protocol does not define how applications extract structured assertions
from unstructured data. It also does not require a particular implementation of the source-reliability and claim-support algorithm beyond the versioned calculations defined by the API.

This document specifies the intended version-1 contract. Features are marked as
implemented, specified but not implemented, or deferred where appropriate.

## 2. Requirement Language

The key words **MUST**, **MUST NOT**, **SHOULD**, **SHOULD NOT**, and **MAY**
are to be interpreted as described in RFC 2119 and RFC 8174.

## 3. Status

Version 1 has the following implementation status:

| Capability | Status |
| --- | --- |
| Deployment provisioning and `ping` | Implemented |
| Canonical linkage serialization and domain encoding | Implemented |
| RFC 9497 VOPRF client and server primitives | Implemented |
| `evaluate_voprf` MCP tool | Implemented for local stdio |
| `evaluate_assertions` MCP tool | Implemented for local stdio |
| `trace_claim` | Deferred |
| Overlapping-key rotation | Deferred |
| Remote transport profile | Deferred |
| Omneum Cloud and multi-tenancy | Out of scope |

## 4. Core Concepts

A **Source** is an origin that asserts one or more claims.

An **Attribute** identifies a property of an entity within an entity namespace.
It groups claims that describe competing values for that property.

A **Claim** is a canonical entity, attribute, and value tuple.

An **Assertion** is a directed relationship from one source to one claim.
Assertions are the edges of the Omneum assertion graph.

A **Client** performs content-sensitive processing locally, constructs protocol
requests, and verifies VOPRF evaluations.

A **Deployment** evaluates blinded inputs and performs deterministic assertion
evaluation over request-scoped opaque graphs.

## 5. Design Principles

### 5.1 Content Blindness

Clients MUST NOT send canonical source, entity, attribute, or claim content in
evaluation or assertion-evaluation requests. Deployments operate on blinded elements or
opaque linkage tokens.

VOPRF limits what an evaluator learns from an individual evaluation. It does
not hide traffic metadata, request timing, caller identity, request volume, or
the graph structure submitted for evaluation.

### 5.2 Deterministic Linkage

Independent valid VOPRF rounds over the same encoded input and active
deployment key produce the same finalized token, even though client blinds and
server proofs are randomized.

Stable tokens reveal equality within their deployment and key-version
boundary. Assertion evaluation additionally reveals the submitted equality and
topology.

Tokens MUST be compared only when their complete token identity matches.

### 5.3 Stateless Evaluation

The self-hosted version-1 evaluator is stateless. It retains one active VOPRF
server context but does not retain requests, blinded elements, client state,
proofs, finalized tokens, replay nonces, or assertion graphs between calls.

### 5.4 Domain Separation

Source, attribute, and claim inputs use distinct linkage purposes. The same
canonical payload used for different purposes MUST produce different linkage
inputs and finalized tokens.

## 6. Version Dimensions

Version 1 separates values that evolve for different reasons:

| Field | Version-1 value | Meaning |
| --- | --- | --- |
| `protocol_version` | `"v1"` | MCP request and response contract |
| `algorithm_version` | `"omneum-v1"` | Algorithm used for assertion evaluation |
| `voprf_mode` | `"voprf"` | RFC 9497 protocol mode |
| `voprf_ciphersuite` | `"ristretto255-SHA512"` | VOPRF group and hash suite |
| `voprf_key_version` | integer `1..2^32-1` | Deployment VOPRF key |
| `linkage_encoding_version` | integer `1` | Omneum linkage input encoding |

`algorithm_version` identifies the version of the source-reliability and
claim-support algorithm used during assertion evaluation. It does not apply
to VOPRF evaluation.

Changing the protocol version alone does not change token identity. Changing
the deployment, VOPRF key, mode, ciphersuite, linkage encoding version, purpose,
or finalized output does.

## 7. Client Processing

A conforming client performs the following steps:

```text
application-defined semantic normalization
    -> structured assertion data
    -> strict RFC 8785 fixed-schema serialization
    -> Omneum linkage domain encoding
    -> VOPRF blinding
    -> server evaluation and proof generation
    -> response metadata validation
    -> proof verification with the pinned public key
    -> VOPRF finalization
    -> assertion message construction
```

The client MUST:

- canonicalize application-provided structured values according to the fixed linkage schemas before strict serialization;
- use the fixed source, attribute, and claim schemas;
- apply the correct linkage purpose;
- use cryptographically secure randomness when blinding;
- retain the encoded input and client state for the corresponding blind;
- validate evaluation response metadata;
- verify the proof using its authenticated, pinned public key;
- finalize with the exact encoded input and state captured during blinding; and
- encode finalized tokens as strict unpadded base64url.

The application is responsible for semantic normalization before assertion evaluation. The client MUST NOT ask the deployment to perform semantic normalization, fuzzy matching, or content extraction.

## 8. VOPRF Trust

### 8.1 Caller Authentication and Authorization

Caller authentication protects the deployment from unauthorized callers.
Authorization determines which operations an authenticated caller may perform.

Local stdio deployments MAY rely on the OS user, process-launch, filesystem,
and IPC boundary.

Remote transports MUST authenticate callers and MUST authorize VOPRF evaluation
separately from assertion evaluation. Permission to evaluate VOPRF inputs does
not imply permission to evaluate assertions, and permission to evaluate
assertions does not imply permission to evaluate VOPRF inputs.

Request metadata is validation input. It does not authenticate the caller.

### 8.2 VOPRF Public-Key Authentication

VOPRF public-key authentication protects the client from a substituted,
misconfigured, or wrong evaluator key.

Before evaluation, a client MUST obtain this tuple through authenticated
out-of-band configuration:

```text
deployment_id
voprf_key_version
voprf_mode
voprf_ciphersuite
linkage_encoding_version
server_public_key
```

The client MUST pin that tuple. It MUST NOT establish trust by retrieving the
public key solely from the evaluation endpoint. TLS authenticates a transport
endpoint but does not prove that the endpoint loaded the expected VOPRF key.

The diagnostic fingerprint returned by `ping` MUST NOT be used to provision or
authenticate the public key.

Caller authentication and VOPRF public-key authentication are separate
mechanisms. A deployment may correctly authenticate a caller while using the
wrong VOPRF key, and a client may possess the correct VOPRF public key while
lacking permission to call the deployment.

## 9. VOPRF Flow

Version 1 uses only RFC 9497 VOPRF mode with the ristretto255-SHA512
ciphersuite. Other RFC 9497 modes are not supported.

The client blinds the complete domain-separated linkage input:

```text
blind(input) -> blinded_element[32], client_state[64]
```

The server evaluates the checked blinded element and generates a fresh proof:

```text
evaluate(blinded_element[32])
    -> evaluated_element[32], proof[64]
```

The client validates response metadata, checks all encodings, verifies the
proof against its pinned 32-byte public key, and finalizes:

```text
finalize(
    input,
    client_state[64],
    evaluated_element[32],
    proof[64],
    server_public_key[32],
) -> token[64]
```

The client uses fresh secure randomness for each blind. The server uses fresh
secure randomness for each proof. The evaluator never receives the private
input or client state, and the client never receives the server private key.

The exact linkage encoding is defined in `canonicalization.md`. The MCP
evaluation schema is defined in `api.md`.

## 10. Assertions and Token Identity

Every assertion-evaluation entry contains:

- `source_id`;
- `attribute_id`; and
- `claim_id`.

Each value is a 64-byte linkage token encoded as unpadded base64url without a
textual prefix.

A persisted linkage token is identified by:

```text
(
    deployment_id,
    voprf_key_version,
    voprf_mode,
    voprf_ciphersuite,
    linkage_encoding_version,
    purpose,
    token,
)
```

Purpose is `source`, `attribute`, or `claim`. Although purpose and linkage
encoding version are cryptographically bound into the VOPRF input, they remain
explicit persisted metadata so applications can interpret stored tokens.

`protocol_version` is not part of token identity. `algorithm_version` is not
part of token identity.

Tokens with different identity metadata MUST NOT be compared as members of the
same linkage space. A single request MUST NOT mix deployment IDs, VOPRF key
versions, VOPRF modes, ciphersuites, or linkage encoding versions.

## 11. Replay and Retry

Clients MAY retry the same blinded evaluation request after an uncertain
transport failure. The server maintains no replay database or per-request
state. A repeated evaluation may contain a different randomized proof while
remaining valid and producing the same finalized token.

Replay prevention is not a VOPRF correctness requirement. Authentication,
authorization, rate limiting, concurrency bounds, and deadlines mitigate
abusive replay.

Client state is local to the blind operation. A client MUST pair an evaluation
with the exact encoded input and client state that produced its blinded
element.

## 12. Key Lifecycle

Version 1 supports exactly one active VOPRF key for a deployment. It does not
support an overlap in which old and new keys are evaluated concurrently.
Overlapping-key rotation is deferred.

Startup MUST require a configured deployment ID, key version, public-key pin,
and private-key file. A deployment MUST NOT generate a key during startup.
Startup MUST fail before serving when the configured public key does not match
the private key or when key material is invalid.

All replicas serving one deployment MUST use the same deployment ID, key
version, mode, ciphersuite, linkage encoding version, and key pair. A
misconfigured replica MUST fail startup or be removed before it receives
requests. Operators SHOULD compare the `ping` configuration fingerprint across
replicas as a diagnostic check, but that fingerprint does not establish trust.

A version-1 rotation is a coordinated single-key cutover:

1. provision a new key and authenticated client pin;
2. assign a strictly greater key version;
3. prevent mixed old-key and new-key replicas from serving the same endpoint;
4. activate the new server fleet and client configuration as one operational
   change; and
5. retain complete token identity metadata for any stored old tokens.

The server rejects every key version other than its one active version.
Unknown, stale, retired, and future versions are indistinguishable at the API
boundary.

Version 1 has no persistent rollback floor. Rollback protection depends on
authenticated configuration management and deployment controls.

## 13. Assertion Evaluation

`evaluate_assertions` is implemented for local MCP stdio. The exact wire contract
and algorithm are defined in `api.md`. Remote transport and Omneum Cloud
integration are not implemented.

The Python SDK exposes the wire operation through multiple application-facing
interfaces. `client.evaluate()` accepts a `StructuredAssertion` when the
application has already normalized the entity, attribute, value, and supporting
sources. `client.evaluate_mapped()` adapts existing retrieval or tool output
through a `ContextMapper`. The lower-level `client.evaluate_assertion()` method
accepts `Observation` objects directly.

All three paths produce the same assertion-evaluation protocol request. Before
linkage, the SDK canonicalizes the application-local assertion data and
estimates the symmetric dependency and weighted signal coverage for every
source pair. It retains raw provenance, lineage, ownership, timestamps,
retrieval records, signal observations, names, claim text, and explanation
text locally. The request contains only opaque assertion triples and the two
numeric values for every canonical source pair.

The deployment validates that complete graph and performs deterministic,
dependency-adjusted reliability propagation. It returns opaque identifiers,
scores, contributions, conflicts, independent-support telemetry, dependency
confidence, and deterministic convergence metadata. It cannot recover or
validate provenance relationships from opaque tokens alone. The submitted
dependency and weighted-signal-coverage values are client estimates that the
deployment cannot independently verify.

For an attribute with `m` distinct claims, the response contains
`m * (m - 1)` conflict entries. The sum across all attributes MUST NOT exceed
16384. The deployment rejects a larger topology as `invalid_graph` before
executor admission and does not truncate the response.

The self-hosted server remains stateless and request-scoped: the complete graph
required for an assertion-evaluation run is supplied in that request and is
not persisted.
`dependency_clusters`, cluster thresholds, and cluster membership are not MCP
request or response fields. No default cluster threshold exists. An SDK MAY
compute clusters locally only when its caller supplies an explicit threshold;
it MUST retain that threshold and the actual cluster membership for a
reproducible explanation.

`trace_claim` is deferred. Version 1 defines no normative trace interface.

## 14. Resource Controls

Every deployment exposing `evaluate_voprf` MUST enforce:

- a bounded transport request size;
- bounded evaluation concurrency;
- a bounded pending queue or immediate overload rejection;
- an evaluation deadline;
- a global evaluation rate or capacity limit;
- fixed-size decoding before native evaluation; and
- secret-free failure responses.

Remote deployments MUST additionally enforce per-caller rate limits after
authentication. Local stdio deployments MAY omit identity-based rate limiting
when the OS/process boundary admits only one trusted caller.

The numeric request-size, concurrency, queue, deadline, and rate limits are
deployment-configurable. Cryptographic sizes, one-element evaluation, linkage
payload limits, and canonicalization bounds are protocol constants.

The installed MCP SDK reads each complete newline-delimited stdio frame before
application validation and does not support a pre-parse frame-size limit.
Duplicate JSON object keys use its parser's last-value semantics. Timed-out
Python work cannot be forcibly terminated and retains its capacity slot until
completion.

## 15. Security Considerations

VOPRF does not replace authenticated transport, caller authorization, secure
private-key storage, process isolation, rate limiting, or operational
monitoring.

Errors, logs, diagnostics, and representations of failures MUST NOT expose
protocol values or secrets, including private keys, private-key paths, client
state, canonical private inputs, blinded elements, evaluation elements, proofs,
finalized tokens, or decoded protocol values.

Successful `evaluate_voprf` responses necessarily contain the evaluated
element and proof. Successful assertion-evaluation responses may contain linkage
identifiers.

Omneum does not intentionally log protocol values. The local server suppresses
MCP SDK protocol-message logging before processing requests, even when the root
logger is configured for debug output.

Metadata mismatch detection is not authentication. Proof verification
authenticates an evaluation relative to the already authenticated public key;
it does not establish who called the server or whether that caller was
authorized.

## 16. Compatibility

Breaking changes to the request or response structure of a released protocol require a new protocol version.
Changes that alter canonical serialized bytes or domain encoding require a new
linkage encoding version. Key rotation uses a new VOPRF key version. Changes to the source-reliability or claim-support calculations used during
assertion evaluation require a new algorithm version.

Older token identity metadata must remain available for as long as old tokens
are retained. Version 1 does not require an evaluator to continue serving old
keys.
