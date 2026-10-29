# Omneum Protocol

The Omneum Protocol defines how clients generate privacy-preserving linkage tokens and submit assertion graphs for evaluation. Version 1 uses [RFC 9497](https://www.rfc-editor.org/rfc/rfc9497) VOPRF with the `ristretto255-SHA512` ciphersuite.

The Python SDK handles linkage through `evaluate_context()`. The local MCP server evaluates blinded inputs and assertion graphs without receiving the original source content.

## Protocol Versions

Version 1 uses the following configuration:

| Field | Value | Description |
|---|---|---|
| `protocol_version` | `"v1"` | MCP request and response contract |
| `algorithm_version` | `"omneum-v2"` | Provenance-aware graph inference version |
| `voprf_mode` | `"voprf"` | RFC 9497 VOPRF mode |
| `voprf_ciphersuite` | `"ristretto255-SHA512"` | Cryptographic ciphersuite |
| `voprf_key_version` | `1..2^32-1` | Active deployment key version |
| `linkage_encoding_version` | `1` | Canonical linkage encoding |

The protocol version identifies the wire contract. The algorithm version identifies the reliability computation and is returned with assertion evaluation results.

A new algorithm version does not change existing linkage tokens. Key rotation or a change to canonical linkage encoding does.

## Deployment

The local MCP server provides three tools:

| Tool | Description |
|---|---|
| [`ping`](api/ping.md) | Check deployment status and configuration |
| [`evaluate_voprf`](api/evaluate-voprf.md) | Evaluate a blinded VOPRF element |
| [`evaluate_context`](api/evaluate-context.md) | Evaluate an opaque assertion graph |

The server runs over MCP stdio:

```bash
omneum-server
```

The Python SDK constructs protocol requests and handles VOPRF linkage through its evaluation APIs.

See [Installation](guides/installation.md) for the managed local server setup.

### Implementation Status

| Capability | Status |
|---|---|
| Local MCP stdio | Implemented |
| Canonical linkage encoding | Implemented |
| RFC 9497 VOPRF | Implemented |
| Assertion evaluation | Implemented |
| `trace_claim` | Deferred |
| Overlapping-key rotation | Deferred |
| Remote transport | Deferred |
| Omneum Cloud | Outside version 1 |

The local evaluator is stateless. It retains the active VOPRF server context but does not store assertion graphs between evaluation calls.

## Assertion Model

An assertion connects a source to a claim.

```text
Source ──asserts──> Claim
```

The protocol uses four objects:

| Object | Definition |
|---|---|
| Source | Origin of one or more assertions |
| Attribute | Property of an entity within an entity namespace |
| Claim | Canonical entity, attribute, and value tuple |
| Assertion | Directed source-to-claim edge |

For example, a source may assert that a service supports streaming.

```json
{
  "entity_namespace": "service",
  "entity": "messages_api",
  "attribute": "supports_streaming",
  "value": true
}
```

The client converts the structured assertion into linkage tokens before sending it to the evaluator.

The resulting assertion references:

```text
source_id
attribute_id
claim_id
```

Each identifier is an unpadded base64url-encoded 64-byte VOPRF token.

The source, attribute, and claim use separate linkage purposes. This prevents identical canonical payloads under different purposes from producing the same token.

See [Canonicalization](canonicalization.md) for the exact payload schemas and encoding rules.

## VOPRF Evaluation

The client constructs a canonical linkage input, blinds it, and submits the blinded element to the deployment.

The deployment evaluates the element using its active VOPRF key and returns a proof. The client verifies that proof before finalizing the token.

### Blinding

The SDK uses the complete domain-separated linkage input.

```text
blind(input)
    -> blinded_element[32], client_state[64]
```

The 32-byte blinded element is sent to `evaluate_voprf`. The client retains the original input and 64-byte blinding state locally.

### Server Evaluation

```text
evaluate(blinded_element[32])
    -> evaluated_element[32], proof[64]
```

The deployment generates a fresh proof for each evaluation.

See [`evaluate_voprf`](api/evaluate-voprf.md) for the MCP request and response schema.

### Finalization

After validating the response metadata, the client verifies the proof using its pinned public key.

```text
finalize(
    input,
    client_state[64],
    evaluated_element[32],
    proof[64],
    server_public_key[32],
) -> token[64]
```

The server public key is 32 bytes.

Repeated VOPRF rounds use fresh randomness, so the blinded elements and proofs can differ. The finalized token remains identical for the same linkage input under the same active key.

Version 1 supports only VOPRF mode. Other RFC 9497 modes are not implemented.

## Public-Key Configuration

Clients authenticate the VOPRF public key through configuration established outside the evaluation endpoint.

The pinned configuration contains:

```text
deployment_id
voprf_key_version
voprf_mode
voprf_ciphersuite
linkage_encoding_version
server_public_key
```

The client checks the response against this configuration before finalization.

The public key returned by an evaluation endpoint cannot establish its own authenticity. The same applies to the diagnostic fingerprint exposed by `ping`.

TLS can authenticate a remote endpoint, but it does not establish that the deployment loaded the expected VOPRF key.

### Caller Authentication

Local stdio deployments can use the operating system's process and filesystem permissions as their access boundary.

Remote transports require caller authentication. VOPRF evaluation and assertion evaluation require separate authorization.

An authenticated caller is not automatically authorized for both operations.

## Token Identity

A linkage token belongs to a specific deployment and key configuration.

When persisting tokens, store the complete identity:

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

The purpose is `source`, `attribute`, or `claim`.

Two tokens are comparable only when their linkage-space metadata matches.

`protocol_version` and `algorithm_version` are excluded from token identity.

### Linkage Encoding

Before blinding, the SDK serializes the canonical payload using RFC 8785 and adds a 17-byte binary header.

```text
protocol_label       12 bytes
encoding_version      2 bytes
purpose               1 byte
payload_length        2 bytes
canonical_payload     N bytes
```

The protocol label is `OMNEUM-OPRF\x00`.

| Purpose | Byte |
|---|---|
| Source | `0x01` |
| Attribute | `0x02` |
| Claim | `0x03` |

For a source payload containing `abc`, the complete linkage input is:

```text
4f 4d 4e 45 55 4d 2d 4f 50 52 46 00
00 01
01
00 03
61 62 63
```

The encoding version and purpose are included in the blinded input. Changing either produces a different linkage token.

The maximum canonical payload is 65,517 bytes, giving a maximum complete input of 65,534 bytes.

See [Canonicalization](canonicalization.md) for the full encoding specification.

## Assertion Evaluation

`evaluate_context` evaluates an opaque graph of assertions.

The Python SDK exposes two MCP evaluation interfaces:

| Method | Input |
|---|---|
| `client.evaluate_mapped()` | Retrieval records mapped through `ContextMapper` |
| `client.evaluate_context()` | `Observation` objects |

Both produce the same MCP evaluation contract.

For synchronous in-process evaluation, use `omneum.evaluate(records)` without an MCP connection.

The SDK canonicalizes the structured assertions and derives their linkage tokens. It also estimates source dependencies using locally available provenance.

The deployment receives the assertion graph with a dependency estimate and weighted signal coverage for each canonical source pair.

Raw provenance stays on the client. The evaluator cannot independently reconstruct dependency relationships from opaque tokens.

### Evaluation Results

The deployment runs deterministic, dependency-adjusted reliability propagation.

Results include:

| Field group | Description |
|---|---|
| Source scores | Reliability assigned to each source |
| Claim scores | Support assigned to each claim |
| Contributions | Individual source contributions |
| Conflicts | Competing claims for an attribute |
| Independent support | Estimated independent support |
| Weighted signal coverage | Proportion of configured dependency signal weight with observable provenance |
| Convergence | Algorithm iteration metadata |

See [`evaluate_context`](api/evaluate-context.md) for the complete request and response schema.

### Conflict Limit

For an attribute with `m` distinct claims, the evaluator produces:

```text
m * (m - 1)
```

conflict entries.

The total across all attributes is limited to **16,384 entries**. A larger graph fails with `invalid_graph` before executor admission. The evaluator does not truncate conflicts.

### Dependency Clusters

`dependency_clusters` is not an MCP request or response field.

The SDK can compute clusters locally when the caller provides an explicit threshold. The threshold and resulting membership must be retained for reproducible explanations.

There is no default cluster threshold.

### Request Scope

Every evaluation request contains the complete graph for that run. The self-hosted evaluator does not persist it.

`trace_claim` is not implemented in version 1.

## Key Rotation

Version 1 supports one active VOPRF key per deployment.

The deployment requires a configured key version and matching public/private key pair at startup. Invalid key material prevents the server from starting.

Keys are not generated automatically during startup.

### Replicas

Replicas serving the same deployment use identical VOPRF configuration.

This includes the deployment ID, key version, linkage encoding version, and key pair.

The `ping` configuration fingerprint can be compared across replicas to detect configuration differences. It is a diagnostic check rather than an authentication mechanism.

### Rotation Procedure

1. Provision the replacement key and authenticated client pin.
2. Assign a strictly greater `voprf_key_version`.
3. Stop old-key replicas from serving the endpoint.
4. Activate the replacement deployment and client configuration.
5. Retain the complete identity metadata for previously issued tokens.

The evaluator accepts only its active key version.

Requests using a key version other than the active deployment version are rejected with `voprf_key_version_mismatch`.

Concurrent evaluation under old and new keys is not supported. Version 1 also has no persistent rollback floor; rollback protection depends on deployment configuration controls.

## Retries

The VOPRF evaluator maintains no replay database.

A client can retry an evaluation after a transport failure. The returned proof may differ, but a valid evaluation finalizes to the same token.

Each response must be paired with the encoded input and private state from its corresponding blind operation.

The server does not retain that client state.

## Resource Limits

The local deployment enforces execution limits for VOPRF evaluation.

| Control | Behavior |
|---|---|
| Request size | Bounded |
| Concurrent evaluations | Bounded |
| Pending evaluations | Bounded queue or overload rejection |
| Evaluation deadline | Enforced |
| Evaluation capacity | Global limit |
| Native input | Fixed-size decoding |
| Failure response | Secret-free |

Remote deployments additionally require per-caller rate limiting.

The numeric limits are deployment-configurable. Cryptographic sizes and canonicalization bounds are fixed by the protocol.

### MCP Stdio Limitations

The installed MCP SDK reads complete newline-delimited frames before application validation. It does not provide a pre-parse frame-size limit.

Duplicate JSON object keys follow the parser's last-value behavior.

Timed-out Python work cannot be forcibly terminated. Its execution slot remains occupied until the underlying operation completes.

## Security

The evaluator is payload-blind. It processes blinded VOPRF elements during linkage and opaque identifiers during assertion evaluation. Original source content remains on the client.

The submitted graph still exposes its structure. Stable tokens also expose equality within a deployment's linkage space.

VOPRF does not hide transport metadata.

### Logging

The local server suppresses MCP SDK protocol-message logging before processing requests, including when debug logging is enabled.

Failure responses exclude sensitive protocol values.

Successful `evaluate_voprf` responses necessarily return the evaluated element and proof. Successful assertion evaluation responses contain linkage identifiers.

These values are part of the protocol response, not diagnostic output.

### Access Control

Proof verification establishes that an evaluation was produced under the authenticated public key. It does not authenticate the caller.

Deployment authorization remains separate from cryptographic verification.

See [Security Review](security-review.md) for the production security assessment.

## Compatibility

Changes to the protocol use separate version dimensions.

| Change | Required version change |
|---|---|
| Breaking MCP request or response contract | `protocol_version` |
| Canonical payload or linkage encoding | `linkage_encoding_version` |
| VOPRF key rotation | `voprf_key_version` |
| Reliability or claim-support computation | `algorithm_version` |

A version-1 request uses one deployment and one active key configuration.

Persisted tokens retain their original identity metadata. Evaluators are not required to continue serving retired keys.

## References

- [Canonicalization](canonicalization.md)
- [Evaluate VOPRF](api/evaluate-voprf.md)
- [Evaluate Context](api/evaluate-context.md)
- [Architecture](architecture.md)
- [Security Review](security-review.md)
- [RFC 9497 — VOPRF](https://www.rfc-editor.org/rfc/rfc9497)
- [RFC 8785 — JSON Canonicalization Scheme](https://www.rfc-editor.org/rfc/rfc8785)

Requirement terminology follows [RFC 2119](https://www.rfc-editor.org/rfc/rfc2119) and [RFC 8174](https://www.rfc-editor.org/rfc/rfc8174).