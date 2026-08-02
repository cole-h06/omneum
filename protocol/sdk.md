# Verity SDK Guide

This document defines the responsibilities of a version-1 Verity client. It is
an intended SDK contract, not an installation guide for packages that have not
been released.

## 1. Status

The repository currently implements:

- strict fixed-schema RFC 8785 linkage serialization;
- version-1 linkage domain encoding;
- RFC 9497 VOPRF client operations;
- proof verification against a configured public key; and
- purpose-specific source, attribute, and claim linkage methods;
- a strict single-element `evaluate_voprf` MCP client flow; and
- an owned local-stdio client context with authenticated pinned configuration.

The repository does not yet provide:

- an implemented `infer_credibility` client flow;
- remote client transport or authentication;
- an official JavaScript or TypeScript SDK;
- automatic local token metadata storage; or
- response rendering and natural-language explanations.

Those absent capabilities MUST NOT be presented as currently available.

## 2. Client Configuration

A client requires authenticated out-of-band configuration containing:

```text
deployment_id
voprf_key_version
voprf_mode
voprf_ciphersuite
linkage_encoding_version
server_public_key
```

Version-1 values are:

```text
voprf_mode = "voprf"
voprf_ciphersuite = "ristretto255-SHA512"
linkage_encoding_version = 1
```

`deployment_id` is a canonical lowercase UUID URN. `voprf_key_version` is an
integer from 1 through `2^32-1`. The public key is exactly 32 bytes and is
represented in configuration as strict unpadded base64url.

The client MUST authenticate this configuration independently of the
evaluation endpoint. Suitable provisioning may use an operator-managed
configuration system or another authenticated distribution channel. Retrieving
a key from the evaluator itself is insufficient because a substituted
evaluator could return its own key.

The `ping` fingerprint is diagnostic only and MUST NOT be used as public-key
authentication or trust on first use.

The local-stdio client calls `list_tools` once when opening and fails early if
`evaluate_voprf` is absent. This discovery is diagnostic only and does not
authenticate the deployment, its metadata, or its VOPRF public key.

A configured local-stdio client exposes the three purpose-specific async
linkage methods:

```python
import sys

from mcp import StdioServerParameters
from verity import VerityClientConfig, open_stdio_client

config = VerityClientConfig.from_base64url(
    deployment_id="urn:uuid:01234567-89ab-cdef-0123-456789abcdef",
    voprf_key_version=1,
    voprf_mode="voprf",
    voprf_ciphersuite="ristretto255-SHA512",
    linkage_encoding_version=1,
    voprf_public_key=pinned_public_key,
)
server = StdioServerParameters(
    command=sys.executable,
    args=["-m", "verity.server"],
)

async with open_stdio_client(config, server) as client:
    source = await client.link_source("web_publisher", "https://example.com")
    attribute = await client.link_attribute("service", "api", "status")
    claim = await client.link_claim("service", "api", "status", "healthy")
```

`link_source` uses the parameter names `kind` and `identifier`, matching the
source schema. Each method returns a `LinkageToken` whose `value` is the exact
64-byte finalized output.

Remote caller credentials are separate from the VOPRF public-key pin:

- caller authentication proves who may invoke a deployment;
- authorization grants evaluation or inference permission; and
- the pinned VOPRF public key lets the client verify the evaluation proof.

Metadata equality is not authentication.

## 3. Client Processing

A version-1 client performs:

```text
application value
    -> semantic canonicalization
    -> strict fixed-schema RFC 8785 serialization
    -> Verity domain-separated linkage input
    -> randomized VOPRF blind
    -> evaluate_voprf request
    -> metadata and encoding validation
    -> VOPRF proof verification
    -> finalization
    -> unpadded base64url token
```

Content-sensitive operations remain on the client. An evaluation request
contains only a blinded group element and non-secret deployment metadata.

The deployment can still observe caller identity, timing, request size, and
volume. An inference request also reveals equality and topology among the
opaque tokens it contains. Stable tokens reveal equality within their
deployment and key-version boundary.

## 4. Canonicalization and Serialization

Callers currently canonicalize values before invoking strict serialization.
Serialization does not normalize whitespace, case, Unicode, object keys,
numbers, or values.

The client MUST use the fixed schemas in `canonicalization.md`:

- source: `kind`, `identifier`;
- attribute: `entity_namespace`, `entity`, `attribute`;
- claim: `entity_namespace`, `entity`, `attribute`, `value`.

The client MUST NOT construct an arbitrary object and label it as one of these
purposes. The serializer constructs the schema so additional keys cannot be
injected.

Independent SDK implementations MUST reproduce the exact RFC 8785 bytes and
linkage input vectors in the repository.

## 5. Blinding

The client applies the correct purpose automatically:

| Value | Purpose |
| --- | --- |
| Source | `0x01` |
| Attribute | `0x02` |
| Claim | `0x03` |

The client MUST blind the complete 17-byte-header-plus-payload input with
cryptographically secure randomness.

Blinding produces:

```text
blinded_element[32]
client_state[64]
```

The blinded element is public protocol material. Client state is private and:

- MUST remain local;
- MUST NOT be included in requests, errors, logs, or representations;
- MUST be paired with the corresponding encoded input; and
- MUST be used only through an API that preserves that pairing.

Version 1 does not require one-time state enforcement. Reuse or mismatching of
valid state is not an authentication mechanism and must not be treated as one.

## 6. Evaluation Request

Status: **implemented for single-element local MCP stdio**.

The client sends exactly one blinded element:

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

The binary value above illustrates wire encoding and length; it is not a
cryptographic test vector.

`blinded_element` is strict unpadded base64url and decodes to exactly 32 bytes.
The client sends no purpose field because purpose is cryptographically bound
inside the blinded linkage input.

For remote transport, the client also supplies the transport-specific caller
credential. Credentials are not part of the tool arguments above.

## 7. Response Validation and Finalization

The client MUST process an evaluation response in this order:

1. validate the response object, required fields, types, and absence of unknown
   fields;
2. validate canonical deployment and version metadata;
3. compare every metadata field with the pinned request context;
4. strictly decode the evaluated element and proof;
5. require a 32-byte evaluated element and 64-byte proof;
6. perform checked deserialization;
7. verify the proof against the authenticated, pinned public key;
8. finalize with the exact encoded input and client state captured by the
   corresponding blind; and
9. require a 64-byte output.

The client MUST fail closed on a deployment, key-version, mode, ciphersuite, or
linkage-encoding mismatch. It MUST NOT attempt proof verification under a key
returned by the evaluation endpoint.

Proof verification failure covers wrong-key evaluations, modified responses,
and proofs replayed across incompatible blinded requests.

The finalized output is encoded as 86-character unpadded base64url with no
textual prefix.

## 8. Retry Behavior

The client MAY retry the same blinded request after an uncertain transport
failure. The evaluator is stateless and uses fresh proof randomness on every
successful evaluation, so repeated valid responses may not be byte-for-byte
identical.

The client MUST validate and verify any response it uses. It MUST NOT assume
that an evaluation response is valid merely because it arrived over an
authenticated transport.

Retry count, backoff, and timeout values are deployment or application
configuration. Clients SHOULD honor explicit throttling and overload errors.

## 9. Token Storage

A client or application retaining tokens MUST store their complete identity:

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

Purpose is source, attribute, or claim. The token is the 64-byte output,
represented on the wire as unpadded base64url.

Tokens with different identity metadata MUST NOT be compared as if they shared
one linkage space. `protocol_version` and credibility `algorithm_version` are
not part of token identity.

Applications MAY maintain a local mapping from tokens to their original
content. Such a registry is application state, is not sent to the deployment,
and is not currently supplied by a complete Verity SDK.

## 10. Assertion Construction

Protocol assertions retain these field names:

```json
{
  "source_id": "YWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYQ",
  "attribute_id": "YmJiYmJiYmJiYmJiYmJiYmJiYmJiYmJiYmJiYmJiYmJiYmJiYmJiYmJiYmJiYmJiYmJiYmJiYmJiYmJiYmJiYg",
  "claim_id": "Y2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjYw"
}
```

Each field is an unpadded base64url linkage token:

- `source_id` has source purpose;
- `attribute_id` has attribute purpose; and
- `claim_id` has claim purpose.

An inference request has one request-level token context. It MUST NOT mix
deployments, key versions, VOPRF modes, ciphersuites, or linkage encoding
versions.

## 11. Credibility Inference

`infer_credibility` is implemented by the local MCP stdio server. The request,
response, validation order, bounds, and algorithm are defined in `api.md`.
Client SDK inference integration is not implemented, and no SDK may present an
inference client flow as currently available.

Before an inference call, an inference-capable SDK will canonicalize local
assertions, estimate a symmetric dependency and weighted signal coverage for
every source pair, and link source, attribute, and claim identifiers. It will
send the complete canonical assertion list and source-pair list. Raw
provenance, lineage, citations, owners, timestamps, retrieval records, raw
signals, source names, claim text, and natural-language explanations remain
local. Weighted signal coverage records how much configured dependency-signal
weight was observable; it is not correctness confidence.

After validating the response metadata, schema, token membership, numeric
values, and deterministic ordering, the SDK will map opaque results to its
local names. It may explain server-returned support, contributions, conflicts,
estimated independent support, and dependency confidence using locally retained
signal descriptions. Support is a graph score rather than a truth probability,
and estimated independent support is not a count of verified origins.

`dependency_clusters`, thresholds, and membership never cross MCP. There is no
default threshold. If a caller explicitly supplies a finite threshold in
`[0, 1]`, the SDK MAY form an undirected graph among the relevant supporting
sources with an edge where `dependency >= threshold`, then use its connected
components as local dependency clusters. For reproducibility, it MUST retain
both the caller's threshold and the actual cluster membership. Without an
explicit threshold, it MUST omit cluster counts and cluster explanations.

The deployment does not receive original content or generate natural-language
explanations. Pairwise signal descriptions such as shared ownership or close
timing can appear only in SDK explanations derived from retained local data.

The server rejects a graph whose response would contain more than 16384 total
conflicting-claim entries. For an attribute with `m` distinct claims, that
attribute contributes `m * (m - 1)` entries because every claim lists every
other claim.

The installed MCP SDK reads a complete newline-delimited stdio frame before
application validation; pre-parse frame-size limiting is unsupported.
Duplicate JSON object keys use the installed parser's last-value semantics.
Timed-out Python inference work cannot be forcibly terminated and retains its
capacity slot until completion. The server suppresses MCP SDK protocol-message
logging so protocol values are not intentionally logged by Verity.

`trace_claim` is deferred and has no version-1 SDK interface.

## 12. Key Rotation

Version 1 supports one active key without overlap. An SDK does not select
between multiple accepted server keys.

A coordinated cutover provisions a strictly greater key version and new
authenticated public-key pin, prevents mixed-key replicas from sharing an
endpoint, and switches the server and clients as one operational change.

Old stored tokens remain associated with their old token identity. Version 1
does not require the evaluator to continue serving the old key.

Overlapping-key rotation is deferred.

## 13. Language Interoperability

Python, JavaScript, and other future SDKs must agree on:

- semantic canonicalization rules;
- RFC 8785 serialized bytes;
- UTF-16 object-key ordering required by RFC 8785;
- safe-integer and finite-float constraints;
- the 17-byte linkage header;
- unsigned big-endian version and length fields;
- purpose tags;
- strict unpadded base64url;
- request metadata validation; and
- token identity.

Language-neutral serialization and linkage vectors are the interoperability
source of truth. An official SDK must pass them before claiming version-1
conformance.
