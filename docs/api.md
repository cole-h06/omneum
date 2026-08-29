# Omneum API Reference

The Omneum API defines the version-1 wire contract between clients and Omneum
deployments. It specifies the MCP tools, request and response schemas,
validation behavior, protocol limits, and assertion-evaluation semantics.

The Python SDK handles this protocol automatically for normal integrations.
See [`sdk.md`](sdk.md) for the application-facing interface.

Related specifications:

- [`protocol.md`](protocol.md) defines protocol roles, trust, token identity,
  replay, and key lifecycle.
- [`canonicalization.md`](canonicalization.md) defines canonical payloads and
  linkage input encoding.
- [`sdk.md`](sdk.md) defines the Python SDK and application-facing interfaces.
- [`../docs/architecture.md`](../docs/architecture.md) describes the current
  implementation architecture.

## 1. Status

| Tool | Status |
| --- | --- |
| `ping` | Implemented |
| `evaluate_voprf` | Implemented for local MCP stdio |
| `evaluate_assertions` | Implemented for local MCP stdio |
| `trace_claim` | Deferred; no version-1 interface |

This document defines the version-1 wire contract except where a section is
explicitly marked non-normative.

## 2. Versions

| Property | Version-1 value | Description |
| --- | --- | --- |
| `protocol_version` | `"v1"` | Tool request and response contract |
| `algorithm_version` | `"omneum-v1"` | Assertion-evaluation algorithm |
| `voprf_mode` | `"voprf"` | RFC 9497 VOPRF mode |
| `voprf_ciphersuite` | `"ristretto255-SHA512"` | VOPRF ciphersuite |
| `voprf_key_version` | `1..2^32-1` | Active deployment key |
| `linkage_encoding_version` | `1` | Linkage input encoding |

Booleans are not integers for version fields.

## 3. Binary Encoding

All protocol byte strings MUST use strict unpadded base64url:

- only `A-Z`, `a-z`, `0-9`, `-`, and `_` are permitted;
- `=` padding and whitespace are forbidden;
- alternate encodings are forbidden; and
- decoding and canonical re-encoding MUST reproduce the input exactly.

| Value | Bytes | Encoded characters |
| --- | ---: | ---: |
| Blinded element | 32 | 43 |
| Evaluated element | 32 | 43 |
| VOPRF public key | 32 | 43 |
| Proof | 64 | 86 |
| Linkage token | 64 | 86 |

`source_id`, `attribute_id`, and `claim_id` are unpadded base64url encodings of
64-byte linkage tokens. They have no textual prefixes.

## 4. Authentication and Permissions

Local stdio deployments MAY rely on the OS and process boundary.

Remote transports MUST authenticate callers and authorize each operation.
VOPRF evaluation and assertion evaluation are separate permissions. A caller
authorized for one MUST NOT be assumed to be authorized for the other.

Request metadata does not authenticate a caller. Matching a deployment ID or
key version proves only that a request names the active configuration.

Clients authenticate the expected VOPRF public key through out-of-band
configuration as described in `protocol.md`. The evaluation endpoint and
`ping` response do not provision that trust.

## 5. Errors

Omneum failures carry a stable `omneum_code`. The MCP binding MAY represent the
failure as a JSON-RPC error or a tool execution error according to the SDK in
use. Exact numeric JSON-RPC mappings will be fixed with the MCP implementation;
clients MUST use `omneum_code`, not a numeric transport code, to classify
Omneum failures.

An error has this logical shape:

```json
{
  "message": "Request validation failed.",
  "omneum_code": "invalid_request"
}
```

Errors MUST NOT include private keys, private-key paths, public keys, canonical
private inputs, client state, blinded elements, evaluation elements, proofs,
tokens, decoded protocol values, or OS error text.

### 5.1 Error Codes

| Code | Meaning |
| --- | --- |
| `request_too_large` | The transport request exceeds the configured bound. |
| `invalid_request` | The schema, type, or canonical metadata is invalid. |
| `authentication_required` | A remote caller was not authenticated. |
| `permission_denied` | The caller lacks permission for the requested tool. |
| `unsupported_protocol_version` | The protocol version is unsupported. |
| `deployment_mismatch` | The request names another deployment. |
| `voprf_key_version_mismatch` | The request does not name the one active key. |
| `unsupported_voprf_mode` | The VOPRF mode is unsupported. |
| `unsupported_voprf_ciphersuite` | The ciphersuite is unsupported. |
| `unsupported_linkage_encoding_version` | The linkage encoding is unsupported. |
| `invalid_blinded_element` | The blinded element is malformed or invalid. |
| `invalid_graph` | An assertion graph is malformed. |
| `rate_limited` | A caller exceeded an evaluation rate limit. |
| `server_busy` | Concurrency or queue capacity is exhausted. |
| `request_timeout` | Processing exceeded its deadline. |
| `evaluation_failed` | Evaluation failed without a safe client-visible detail. |
| `assertion_evaluation_failed` | Assertion evaluation could not be completed. |
| `internal_error` | An unexpected server failure occurred. |

Unknown, stale, retired, and future key versions all produce
`voprf_key_version_mismatch`. Version 1 does not expose a key inventory.

Invalid base64url, wrong decoded length, noncanonical group encoding, and the
identity element all produce `invalid_blinded_element`.

## 6. Validation Order

A deployment MUST process `evaluate_voprf` in this order:

1. enforce the transport request-size limit;
2. parse the MCP or JSON-RPC envelope;
3. authenticate a remote caller;
4. authorize VOPRF evaluation;
5. validate required fields, types, and the absence of unknown fields;
6. validate canonical metadata and numeric ranges;
7. compare metadata with the active deployment;
8. strictly decode `blinded_element`;
9. require exactly 32 decoded bytes;
10. perform checked group-element deserialization;
11. evaluate and generate a proof;
12. validate native result sizes; and
13. return canonical unpadded base64url.

A gross transport-size failure may occur before authentication. A remote caller
MUST otherwise be authenticated and authorized before detailed deployment or
cryptographic validation failures are disclosed.

The client validation order is defined in `sdk.md`.

## 7. `ping`

Status: **implemented**.

### 7.1 Request

```json
{}
```

Unknown request fields MUST be rejected.

### 7.2 Response

```json
{
  "status": "ok",
  "protocol_version": "v1",
  "algorithm_version": "omneum-v1",
  "deployment_id": "urn:uuid:8d96fc18-f40f-4ec7-8ae8-f3711d88b741",
  "voprf_key_version": 1,
  "voprf_mode": "voprf",
  "voprf_ciphersuite": "ristretto255-SHA512",
  "linkage_encoding_version": 1,
  "configuration_fingerprint": "5b8742c8a3338fd212f3be06635d185bf8804301b2ea12945ba1dd0e1969e82a"
}
```

| Property | Type | Description |
| --- | --- | --- |
| `status` | string | Deployment status; version 1 returns `"ok"`. |
| `protocol_version` | string | Implemented protocol contract. |
| `algorithm_version` | string | Configured assertion-evaluation algorithm. |
| `deployment_id` | string | Canonical lowercase UUID URN. |
| `voprf_key_version` | integer | Active VOPRF key version. |
| `voprf_mode` | string | Active RFC 9497 mode. |
| `voprf_ciphersuite` | string | Active VOPRF ciphersuite. |
| `linkage_encoding_version` | integer | Active linkage encoding. |
| `configuration_fingerprint` | string | Lowercase hexadecimal SHA-256 diagnostic. |

The fingerprint is computed over:

```text
"OMNEUM-VOPRF-CONFIG\x00"
|| field(deployment_id as ASCII)
|| field(voprf_key_version as 4-byte unsigned big-endian)
|| field(voprf_mode as ASCII)
|| field(voprf_ciphersuite as ASCII)
|| field(linkage_encoding_version as 2-byte unsigned big-endian)
|| field(server_public_key)
```

Each `field(value)` is the two-byte unsigned big-endian byte length followed by
the exact value bytes.

The fingerprint is diagnostic only. It may detect replica disagreement, but it
MUST NOT establish public-key trust, caller authentication, or authorization.
The public key itself is not returned by `ping`.

## 8. `evaluate_voprf`

Status: **implemented for single-element local MCP stdio**. The installed MCP
SDK does not provide a pre-parse stdio frame bound, so this implementation does
not claim complete resource-control conformance.

Version 1 evaluates exactly one blinded element per call.

### 8.1 Request

```json
{
  "protocol_version": "v1",
  "deployment_id": "urn:uuid:01234567-89ab-cdef-0123-456789abcdef",
  "voprf_key_version": 1,
  "voprf_mode": "voprf",
  "voprf_ciphersuite": "ristretto255-SHA512",
  "linkage_encoding_version": 1,
  "blinded_element": "AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8"
}
```

The binary strings in this section illustrate wire encoding and lengths; they
are not cryptographic test vectors.

| Property | Type | Requirement |
| --- | --- | --- |
| `protocol_version` | string | Exactly `"v1"`. |
| `deployment_id` | string | Canonical lowercase UUID URN. |
| `voprf_key_version` | integer | `1..2^32-1`, equal to the active version. |
| `voprf_mode` | string | Exactly `"voprf"`. |
| `voprf_ciphersuite` | string | Exactly `"ristretto255-SHA512"`. |
| `linkage_encoding_version` | integer | Exactly `1`. |
| `blinded_element` | string | Strict base64url decoding to exactly 32 bytes. |

Unknown request fields MUST be rejected.

The request MUST NOT contain the private input, linkage purpose, client state,
VOPRF public key, private key, or finalized token. Linkage purpose is already
bound inside the blinded input and is not visible to the evaluator.

### 8.2 Response

```json
{
  "protocol_version": "v1",
  "deployment_id": "urn:uuid:01234567-89ab-cdef-0123-456789abcdef",
  "voprf_key_version": 1,
  "voprf_mode": "voprf",
  "voprf_ciphersuite": "ristretto255-SHA512",
  "linkage_encoding_version": 1,
  "evaluated_element": "ICEiIyQlJicoKSorLC0uLzAxMjM0NTY3ODk6Ozw9Pj8",
  "proof": "AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8gISIjJCUmJygpKissLS4vMDEyMzQ1Njc4OTo7PD0-Pw"
}
```

| Property | Type | Requirement |
| --- | --- | --- |
| `protocol_version` | string | Server protocol version. |
| `deployment_id` | string | Server deployment ID. |
| `voprf_key_version` | integer | Server active key version. |
| `voprf_mode` | string | Server VOPRF mode. |
| `voprf_ciphersuite` | string | Server ciphersuite. |
| `linkage_encoding_version` | integer | Server linkage encoding. |
| `evaluated_element` | string | Strict base64url decoding to exactly 32 bytes. |
| `proof` | string | Strict base64url decoding to exactly 64 bytes. |

The server MUST return its active metadata. The client MUST compare every field
with its pinned request context before proof verification.

The response MUST NOT include the public key. The client verifies the proof
with its authenticated, pinned public key.

### 8.3 Replay

Clients MAY retry the same blinded request after an uncertain transport
failure. The server stores no request state. Each successful call uses fresh
proof randomness, so proofs may differ while valid responses still finalize to
the same token.

## 9. `evaluate_assertions`

Status: **implemented for local MCP stdio**, including the Python SDK flows that
perform local dependency estimation and linkage, submit the assertion-evaluation
request, validate the response, and map opaque results back to local values.
Remote transport and Omneum Cloud integration are not implemented.

The complete assertion graph and its complete source-pair matrix are supplied
in each request. Assertion evaluation is deterministic and request-scoped. The server
MUST NOT retain the graph, pair values, or results after the request.

The MCP tool is named `evaluate_assertions`. The Python SDK exposes this wire
operation through multiple application-facing interfaces.

`client.evaluate()` accepts a `StructuredAssertion` when the application has
already normalized the entity, attribute, value, and supporting sources.
`client.evaluate_mapped()` accepts existing retrieval or tool output together
with a `ContextMapper`. The lower-level `client.evaluate_assertion()` method
accepts `Observation` objects directly.

These SDK interfaces all compile their application-facing inputs into the same
`evaluate_assertions` wire request defined below.

Applications using the Python SDK do not construct the opaque identifiers or
canonical wire structures described below directly. The SDK performs
canonicalization, serialization, VOPRF linkage, and local dependency
estimation before constructing the `evaluate_assertions` request. It validates
the response and maps opaque result identifiers back to the corresponding
local values.

### 9.1 Request

```json
{
  "protocol_version": "v1",
  "deployment_id": "urn:uuid:01234567-89ab-cdef-0123-456789abcdef",
  "voprf_key_version": 1,
  "voprf_mode": "voprf",
  "voprf_ciphersuite": "ristretto255-SHA512",
  "linkage_encoding_version": 1,
  "assertions": [
    {
      "source_id": "YWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYQ",
      "attribute_id": "YmJiYmJiYmJiYmJiYmJiYmJiYmJiYmJiYmJiYmJiYmJiYmJiYmJiYmJiYmJiYmJiYmJiYmJiYmJiYmJiYmJiYg",
      "claim_id": "Y2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjYw"
    }
  ],
  "source_pairs": []
}
```

The request has exactly eight top-level fields: the six authenticated protocol
metadata fields, `assertions`, and `source_pairs`. Unknown fields at every
level MUST be rejected.

| Field | Type | Requirement |
| --- | --- | --- |
| `protocol_version` | string | Exactly `"v1"`. |
| `deployment_id` | string | Canonical lowercase UUID URN. |
| `voprf_key_version` | integer | `1..2^32-1`, equal to the active version. |
| `voprf_mode` | string | Exactly `"voprf"`. |
| `voprf_ciphersuite` | string | Exactly `"ristretto255-SHA512"`. |
| `linkage_encoding_version` | integer | Exactly `1`. |
| `assertions` | array | `1..4096` assertion objects. |
| `source_pairs` | array | The complete canonical upper triangle. |

An assertion has exactly `source_id`, `attribute_id`, and `claim_id`. Each is a
canonical 86-character unpadded-base64url linkage token decoding to 64 bytes.
The list MUST be strictly sorted by the ASCII tuple
`(source_id, attribute_id, claim_id)` and MUST NOT contain duplicates. A graph
MAY contain at most 64 sources, 2048 attributes, and 4096 claims. Each claim
MUST belong to exactly one attribute, and a source MUST NOT assert more than
one claim for an attribute.

For `n` unique assertion sources, `source_pairs` has exactly `n(n-1)/2`
entries, at most 2016. Each object has exactly `source_a_id`, `source_b_id`,
`dependency`, and `weighted_signal_coverage`. Both identifiers MUST be
assertion sources and MUST satisfy `source_a_id < source_b_id` in ASCII order.
The list MUST be strictly sorted by `(source_a_id, source_b_id)` and contain
every pair once, including pairs whose values are zero.

`dependency` and `weighted_signal_coverage` are finite binary64 numbers in
`[0, 1]`; booleans are not numbers. `dependency` estimates the degree to which
two sources may not represent independent support. Weighted signal coverage is
the fraction of the configured dependency-signal weight for which the client
had usable observations. It is not a probability that the dependency estimate or either source is correct. No other pair value is required by version 1.

The request MUST NOT contain provenance or lineage identifiers, citations,
owners, timestamps, retrieval records, raw dependency signals, source names,
claim text, cluster thresholds, cluster membership, or natural-language
explanations.

### 9.2 Response

```json
{
  "protocol_version": "v1",
  "deployment_id": "urn:uuid:01234567-89ab-cdef-0123-456789abcdef",
  "voprf_key_version": 1,
  "voprf_mode": "voprf",
  "voprf_ciphersuite": "ristretto255-SHA512",
  "linkage_encoding_version": 1,
  "summary": {
    "source_count": 1,
    "claim_count": 1,
    "assertion_count": 1
  },
  "source_reliability": [
    {
      "source_id": "YWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYQ",
      "reliability": 1.0
    }
  ],
  "claim_support": [
    {
      "attribute_id": "YmJiYmJiYmJiYmJiYmJiYmJiYmJiYmJiYmJiYmJiYmJiYmJiYmJiYmJiYmJiYmJiYmJiYmJiYmJiYmJiYmJiYg",
      "claim_id": "Y2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjYw",
      "support": 1.0,
      "agreement_weight": 1.0,
      "is_attribute_max_support": true,
      "supporting_source_count": 1,
      "estimated_independent_support_count": 1.0,
      "dependency_signal_coverage": null,
      "supporting_sources": [
        {
          "source_id": "YWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYQ",
          "independence": 1.0,
          "contribution": 1.0
        }
      ],
      "conflicting_claims": []
    }
  ],
  "metadata": {
    "algorithm_version": "omneum-v1",
    "iterations": 1,
    "converged": true,
    "convergence_tolerance": 1e-8,
    "convergence_delta": 0.0
  }
}
```

The response has exactly the six active protocol metadata fields, `summary`,
`source_reliability`, `claim_support`, and `metadata`. A client MUST validate
and compare the metadata as it does for evaluation responses.

`summary` contains the exact integer fields `source_count`, `claim_count`, and
`assertion_count`. `source_reliability` contains one exact
`{source_id, reliability}` object per source. `claim_support` contains one
object per claim with exactly the fields shown above. A conflicting-claim
object has exactly `claim_id` and `support`; a supporting-source object has
exactly `source_id`, `independence`, and `contribution`.

All numeric results MUST be finite binary64 values. Reliability, support,
agreement weight, independence, contribution, and convergence delta are
nonnegative. `dependency_signal_coverage` is `null` for a claim with one supporting
source and otherwise is in `[0, 1]`. `estimated_independent_support_count` is
in `[1, supporting_source_count]`. Support is a deterministic graph score, not
a truth probability. Estimated independent support is a dependency-adjusted
heuristic, not a count of verified origins.

Successful metadata has exactly `algorithm_version`, `iterations`,
`converged`, `convergence_tolerance`, and `convergence_delta`.
`algorithm_version` is `"omneum-v1"`, `iterations` is in `1..1000`,
`converged` is `true`, and `convergence_tolerance` is `1e-8`.
`computation_time_ms` is not interoperable response data.

Response arrays use these deterministic orders:

- sources: descending reliability, then ascending `source_id`;
- claims: ascending `attribute_id`, descending support, then ascending
  `claim_id`;
- supporting sources: descending contribution, then ascending `source_id`;
- conflicts: descending support, then ascending `claim_id`.

All claims tied for the greatest support for an attribute have
`is_attribute_max_support: true`. `conflicting_claims` contains every other
claim for the attribute. Version 1 permits at most 16384 total
`conflicting_claims` entries in one response. For each attribute containing
`m` distinct claims, every claim lists its other claims, so that attribute
contributes:

```text
m * (m - 1)
```

The request-wide total is the sum of `m * (m - 1)` over all attributes. The
server MUST calculate this total from the validated assertion topology before
executor admission. A total greater than 16384 is `invalid_graph`; the server
MUST NOT truncate or omit conflicts.

### 9.3 Algorithm

Let `S` be the sources, `C` the claims, `A(j)` the sources asserting claim
`j`, and `P(j)` the sources asserting any claim for `j`'s attribute. Let
`d(i,k)` be the submitted dependency. Initialize:

```text
s_i^(0) = 1 / |S|
w_j = |A(j)| / |P(j)|
q_ij = 1                                      when |A(j)| = 1
q_ij = 1 - sum(d(i,k), k in A(j), k != i)
             / (|A(j)| - 1)                  otherwise
contribution_ij^(t) = s_i^(t) * w_j * q_ij / |claims asserted by i|
c_j^(t) = sum(contribution_ij^(t), i in A(j))
u_i^(t+1) = sum(c_j^(t), j asserted by i)
s_i^(t+1) = u_i^(t+1) / sum(u_k^(t+1), k in S)
```

Every sum MUST use IEEE 754 binary64 arithmetic. Dependency terms are ordered
by the other `source_id`; claim contributions by `source_id`; a source's claim
terms by `(attribute_id, claim_id)`; normalization terms by `source_id`; and
pair telemetry by `(source_a_id, source_b_id)`. Iteration stops when
`max_i(abs(s_i^(t+1) - s_i^(t))) < 1e-8`, after at most 1000 updates. The
server recomputes claim support and contributions from the converged source
vector. A zero total propagation update, nonconvergence, or a nonfinite result
MUST return `assertion_evaluation_failed`.

For the `n` sources supporting a claim:

```text
supporting_source_count = n
estimated_independent_support_count =
    n^2 / (n + 2 * sum(d(i,k), i < k, i and k support the claim))
dependency_signal_coverage = null                 when n = 1
dependency_signal_coverage =
    2 * sum(weighted_signal_coverage(i,k), i < k) / (n * (n - 1))
                                             otherwise
```

### 9.4 Validation and Failures

An assertion-evaluation deployment MUST process a request in this order:

1. enforce the transport request-size limit and parse the MCP envelope;
2. authenticate and authorize the caller when the transport requires it;
3. validate required fields, types, and absence of unknown fields;
4. validate canonical metadata and its numeric ranges;
5. compare metadata in this order: protocol version, deployment ID, VOPRF key
   version, mode, ciphersuite, linkage encoding version;
6. enforce graph count bounds;
7. decode assertion tokens in list order and field order, then validate
   assertion ordering, uniqueness, membership, topology, and the 16384-entry
   request-wide conflict-response limit;
8. validate pair count, tokens, membership, canonical ordering, completeness,
   finiteness, and value ranges;
9. admit work to the bounded assertion-evaluation executor;
10. run assertion evaluation before the deadline; and
11. validate and order the response.

Strict schema, type, or unknown-field failures are `invalid_request`.
Out-of-range or nonfinite pair values, an incomplete matrix, noncanonical pair
ordering, malformed assertion or pair tokens, pair-token membership failures,
and graph-topology failures are `invalid_graph`. Metadata mismatches use their
specific error codes.
Immediate capacity exhaustion is `server_busy`; a deadline is
`request_timeout`; zero-total propagation, nonconvergence, or invalid numeric
output is `assertion_evaluation_failed`. Failure responses MUST contain only `message`
and `omneum_code` and MUST NOT reflect submitted values.

Assertion-evaluation authorization is separate from VOPRF evaluation authorization.

## 10. Resource Controls

Every `evaluate_voprf` deployment MUST configure:

- a maximum transport request size;
- a maximum number of concurrent evaluations;
- a bounded queue or immediate overload rejection;
- an evaluation deadline;
- a global evaluation rate or capacity limit; and
- for remote transport, a per-caller rate limit.

These numeric values are deployment-configurable and do not affect
interoperability. Cryptographic sizes, strict base64url lengths, single-element
evaluation, canonicalization limits, and linkage input limits are fixed
protocol requirements.

A local-stdio `evaluate_assertions` deployment MUST use a fixed bounded executor,
immediately reject work when all admission slots are occupied, and maintain no
pending queue. Maximum assertion-evaluation concurrency defaults to 1 and is
configurable from 1 through 64. The assertion-evaluation deadline defaults to 1000 milliseconds and is
configurable from 1 through 60000 milliseconds. An admission slot remains
occupied until timed-out assertion-evaluation work actually finishes. These controls are
separate from VOPRF evaluation controls.

The installed MCP SDK does not provide a pre-parse stdio frame bound. Until a
reviewed transport bound exists, the local implementation MUST acknowledge
that limitation and MUST NOT claim complete resource-control conformance.
It reads a complete newline-delimited frame before application validation, so
pre-parse frame-size limiting is unsupported. Duplicate JSON object keys use
the installed parser's last-value semantics.

Timed-out Python work cannot be forcibly terminated. Its admission slot
remains occupied until the underlying work finishes.

Omneum does not intentionally log protocol values. The local server suppresses
MCP SDK protocol-message logging before processing requests, including SDK
records that would otherwise be emitted through the root logger.

## 11. MCP Binding

An MCP client invokes a tool through the transport's standard `tools/call`
operation. For example:

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "tools/call",
  "params": {
    "name": "evaluate_voprf",
    "arguments": {
      "protocol_version": "v1",
      "deployment_id": "urn:uuid:01234567-89ab-cdef-0123-456789abcdef",
      "voprf_key_version": 1,
      "voprf_mode": "voprf",
      "voprf_ciphersuite": "ristretto255-SHA512",
      "linkage_encoding_version": 1,
      "blinded_element": "AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8"
    }
  }
}
```

Request identifiers, initialization, cancellation, and transport framing follow
the MCP specification. The Omneum validation and error requirements in this
document apply inside that binding.
