# Verity API Reference

The Verity API defines the version-1 tool schemas used by clients and
deployments. The schemas are transport-independent. The reference
implementation uses the Model Context Protocol (MCP).

Related specifications:

- [`protocol.md`](protocol.md) defines protocol roles, trust, token identity,
  replay, and key lifecycle.
- [`canonicalization.md`](canonicalization.md) defines canonical payloads and
  linkage input encoding.
- [`sdk.md`](sdk.md) defines client behavior.
- [`../docs/architecture.md`](../docs/architecture.md) describes the current
  implementation architecture.

## 1. Status

| Tool | Status |
| --- | --- |
| `ping` | Implemented |
| `evaluate_voprf` | Specified, not implemented |
| `infer_credibility` | Non-normative version-1 draft, not implemented |
| `trace_claim` | Deferred; no version-1 interface |

This document is the intended version-1 contract except where a section is
explicitly marked non-normative. A specified schema is not a claim that the
corresponding tool is currently registered.

## 2. Versions

| Property | Version-1 value | Description |
| --- | --- | --- |
| `protocol_version` | `"v1"` | Tool request and response contract |
| `algorithm_version` | `"verity-v1"` | Credibility-inference implementation |
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
Evaluation and inference are separate permissions. A caller authorized for one
MUST NOT be assumed to be authorized for the other.

Request metadata does not authenticate a caller. Matching a deployment ID or
key version proves only that a request names the active configuration.

Clients authenticate the expected VOPRF public key through out-of-band
configuration as described in `protocol.md`. The evaluation endpoint and
`ping` response do not provision that trust.

## 5. Errors

Verity failures carry a stable `verity_code`. The MCP binding MAY represent the
failure as a JSON-RPC error or a tool execution error according to the SDK in
use. Exact numeric JSON-RPC mappings will be fixed with the MCP implementation;
clients MUST use `verity_code`, not a numeric transport code, to classify
Verity failures.

An error has this logical shape:

```json
{
  "message": "Request validation failed.",
  "verity_code": "invalid_request"
}
```

Errors MUST NOT include private keys, private-key paths, public keys, canonical
private inputs, client state, blinded elements, evaluation elements, proofs,
tokens, decoded protocol values, or OS error text.

### 5.1 Error Codes

| Code | Meaning |
| --- | --- |
| `request_too_large` | The transport request exceeds the configured bound. |
| `invalid_request` | A field is missing, extra, wrongly typed, or noncanonical. |
| `authentication_required` | A remote caller was not authenticated. |
| `permission_denied` | The caller lacks permission for the requested tool. |
| `unsupported_protocol_version` | The protocol version is unsupported. |
| `deployment_mismatch` | The request names another deployment. |
| `voprf_key_version_mismatch` | The request does not name the one active key. |
| `unsupported_voprf_mode` | The VOPRF mode is unsupported. |
| `unsupported_voprf_ciphersuite` | The ciphersuite is unsupported. |
| `unsupported_linkage_encoding_version` | The linkage encoding is unsupported. |
| `invalid_blinded_element` | The blinded element is malformed or invalid. |
| `invalid_graph` | An inference graph is malformed. |
| `rate_limited` | A caller exceeded an evaluation rate limit. |
| `server_busy` | Concurrency or queue capacity is exhausted. |
| `request_timeout` | Processing exceeded its deadline. |
| `evaluation_failed` | Evaluation failed without a safe client-visible detail. |
| `inference_failed` | Inference could not be completed. |
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
  "algorithm_version": "verity-v1",
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
| `algorithm_version` | string | Configured inference algorithm. |
| `deployment_id` | string | Canonical lowercase UUID URN. |
| `voprf_key_version` | integer | Active VOPRF key version. |
| `voprf_mode` | string | Active RFC 9497 mode. |
| `voprf_ciphersuite` | string | Active VOPRF ciphersuite. |
| `linkage_encoding_version` | integer | Active linkage encoding. |
| `configuration_fingerprint` | string | Lowercase hexadecimal SHA-256 diagnostic. |

The fingerprint is computed over:

```text
"VERITY-VOPRF-CONFIG\x00"
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

Status: **specified, not implemented**.

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

## 9. `infer_credibility`

Status: **non-normative version-1 draft, not implemented**.

This section records the current direction for the version-1 inference
milestone. It is not a conformance contract. Exact request and response
validation, graph and resource limits, telemetry semantics, result ordering,
and the response contract will be finalized during that milestone.

The complete assertion graph is supplied in each request. The self-hosted
server does not persist graph state.

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
  ]
}
```

The draft uses request-level metadata for every token and does not mix token
identity metadata.

| Assertion field | Purpose | Requirement |
| --- | --- | --- |
| `source_id` | source | Strict base64url decoding to 64 bytes |
| `attribute_id` | attribute | Strict base64url decoding to 64 bytes |
| `claim_id` | claim | Strict base64url decoding to 64 bytes |

Exact request and assertion validation remains to be finalized.

### 9.2 Response

The illustrative draft response retains the existing graph telemetry:

```json
{
  "summary": {
    "source_count": 1,
    "claim_count": 1,
    "assertion_count": 1
  },
  "source_credibility": [
    {
      "source_id": "YWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYQ",
      "credibility": 1.0
    }
  ],
  "claim_support": [
    {
      "attribute_id": "YmJiYmJiYmJiYmJiYmJiYmJiYmJiYmJiYmJiYmJiYmJiYmJiYmJiYmJiYmJiYmJiYmJiYmJiYmJiYmJiYmJiYg",
      "claim_id": "Y2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjYw",
      "support": 1.0,
      "is_attribute_max_support": true,
      "conflicting_claims": []
    }
  ],
  "metadata": {
    "algorithm_version": "verity-v1",
    "iterations": 1,
    "converged": true,
    "computation_time_ms": 1
  }
}
```

| Response field | Description |
| --- | --- |
| `summary` | Counts of unique sources, claims, and assertions. |
| `source_credibility` | Credibility score for each source. |
| `claim_support` | Support and conflict information for each claim. |
| `metadata` | Algorithm version and execution telemetry. |

Inference authorization is separate from VOPRF evaluation authorization.
Nothing in this draft section establishes version-1 inference conformance.

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

## 11. MCP Binding

An MCP client invokes a tool through the transport's standard `tools/call`
operation. For example, once implemented:

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
the MCP specification. The Verity validation and error requirements in this
document apply inside that binding.
