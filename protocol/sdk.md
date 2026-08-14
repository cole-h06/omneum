# Verity SDK Guide

This document defines the responsibilities of a version-1 Verity client. It is
an intended SDK contract, not an installation guide for packages that have not
been released.

## 1. Status

The repository currently implements:

- `web_publisher`, `web_document`, `internal_resource`, `internal_service`, and
  `database` source canonicalization;
- strict fixed-schema RFC 8785 linkage serialization;
- version-1 linkage domain encoding;
- RFC 9497 VOPRF client operations;
- proof verification against a configured public key;
- purpose-specific source, attribute, and claim linkage methods;
- a strict single-element `evaluate_voprf` MCP client flow; and
- an owned local-stdio client context with authenticated pinned configuration;
- the local assertion-evaluation SDK flow; and
- deterministic local claim and dependency explanations.

The repository does not yet provide:

- remote client transport or authentication;
- an official JavaScript or TypeScript SDK;
- automatic local token metadata storage.

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
- authorization grants VOPRF or assertion-evaluation permission; and
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
volume. An assertion-evaluation request also reveals equality and topology among the
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
one linkage space. protocol_version and algorithm_version are not part of token identity.

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

An assertion-evaluation request has one request-level token context. It MUST NOT mix
deployments, key versions, VOPRF modes, ciphersuites, or linkage encoding
versions.

## 11. Assertion Evaluation

`evaluate_assertions` is implemented by the local MCP stdio server. The request,
response, validation order, bounds, and algorithm are defined in `api.md`.
The Python SDK implements the local-stdio assertion-evaluation flow and maps
validated opaque results back to application-local `Source` and `Claim` values.

### 11.1 Dependency Estimator Version

The version-1 local dependency estimator is identified by the exact string
`"dependency-estimator-v1"`. An SDK MUST reject any other estimator version. A
new estimator version is required for a change to signal scoring,
observability, source-level aggregation, weight normalization, dependency or
coverage calculation, temporal-window semantics, or cluster construction.

The estimator operates on canonical application-local sources and observations
before linkage. A `Source` has `kind`, `identifier`, and optional `owner_id`.
Each `Observation` contains one stable `assertion_id`, one `Source`, one
`(entity_namespace, entity, attribute, value)` claim, required `observed_at`,
optional `source_modified_at`, optional `upstream_sources`, `cited_sources`,
and `parent_assertion_ids`, and optional `retrievals`. Each source MUST assert
at most one value for an `(entity, attribute)` property. Relationship
references MUST resolve to known local sources and assertions.

For each evidence relationship field, `null` means that the relationship was
not captured, an empty sequence means it was captured and none was found, and
a nonempty sequence contains the captured relationships. Retrieval records and
retrieval timestamps are not estimator inputs.

`observed_at` is timezone-aware and records when the workflow observed the
assertion. It is not a dependency-estimator timestamp. `source_modified_at` is
timezone-aware when present, records when the source resource was modified,
and is the timestamp used by the temporal signal. A null `source_modified_at`
means temporal metadata was unavailable and does not by itself invalidate an
observation or graph.

A `Retrieval` contains `retrieval_id`, `kind`, `resource_id`, a required
timezone-aware `retrieved_at`, and a `fields` object containing exact JSON
values. Retrieval records describe how an underlying resource was retrieved;
neither `retrieved_at` nor `fields` is an estimator input. The temporal window
is supplied explicitly, has a finite positive number of seconds, and has no
version-1 default.

### 11.2 Source-Level Signal Inputs

The estimator first aggregates observation metadata by source. Upstream,
citation, and assertion lineage are distinct binary signals.

`upstream_sources` lists sources known to be upstream of the observation's
source. Let `U(i,k) = 1` when any observation from source `k` lists source `i`
as upstream. The symmetric upstream score is `max(U(i,k), U(k,i))`.

Let `C(i,k) = 1` when any observation from source `i` lists source `k` in
`cited_sources`. The symmetric citation score is `max(C(i,k), C(k,i))`.

Let `P(i,k)` be the count of assertions from source `i` whose direct
`parent_assertion_ids` resolve to assertions from source `k`. The symmetric
assertion-lineage score is one when either `P(i,k)` or `P(k,i)` is nonzero and
zero otherwise. Parent relationships are direct assertion-level lineage; they
are not combined with explicit citations.

For each relationship signal, a positive relationship makes the pair
observable. With no positive relationship, the signal is observable only when
every observation from both sources has a non-null sequence for that signal.
Thus an observed zero differs from unavailable relationship metadata.

Ownership is source-level metadata. It is observable for a pair only when both
sources have a non-null `owner_id`. Its score is one when those exact owner IDs
are equal and zero otherwise. If either owner is unavailable, its score and
observability are both zero.

### 11.3 Temporal Signal

Let a property be the exact canonical `(entity, attribute)` pair. For a pair of
sources, the temporal comparison set contains the properties asserted by both
sources with equal canonical values. For an ordered child-parent pair, let
`M(i,k)` be that set and let `W` be the explicit temporal window:

```text
T(i,k) = 0                                           if M(i,k) is empty
T(i,k) = |{p in M(i,k) :
              0 < source_modified_at(i,p)
                    - source_modified_at(k,p) <= W}|
           / |M(i,k)|                                otherwise

temporal(i,k) = max(T(i,k), T(k,i))
```

Equal timestamps do not qualify. A later observation qualifies at the exact
window boundary. Disagreements and properties present in only one source do
not enter the denominator.

Temporal dependency is observable for a source pair only when both timestamps
are present for every property in its temporal comparison set. If any required
timestamp is missing, the pair's temporal score and observability are both
zero. A missing timestamp on an assertion that is not in the pair's comparison
set does not affect that pair's temporal observability. In particular, a
timestamp is not required for a property absent from either source or for a
shared property whose values differ. The temporal weight is not redistributed
when the signal is unavailable.

`observed_at` and retrieval time MUST NOT affect this score or observability.

### 11.4 Graph Signal

The graph signal uses only the canonical assertion graph. For each exact
canonical `(property, value)` assertion `x`, define:

```text
rarity(x) = 1 / number of sources asserting x
```

For sources `i` and `k`, let `matches` be their shared properties for which the
canonical values are equal. Let `size_i` and `size_k` be their total numbers of
asserted properties. If `matches` is empty, graph dependency is zero.
Otherwise:

```text
inclusion(i,k) = max(|matches| / size_k, |matches| / size_i)
rarity_mean(i,k) =
    sum(rarity(property, matching value) for each match) / |matches|
graph(i,k) = inclusion(i,k) * rarity_mean(i,k)
```

Conflicting values on a shared property do not count as matches and do not
otherwise reduce the score. Graph dependency is observable for every
distinct valid source pair, including an observable zero.

### 11.5 Weights, Dependency, and Coverage

The caller MUST supply exactly six finite, non-negative binary64 weights:
`upstream`, `citation`, `assertion_lineage`, `ownership`, `temporal`, and
`graph`. Their sum
MUST be finite and greater than zero. The values are configuration weights, not
calibrated production defaults. Individual weights are not constrained to
`[0, 1]`; arbitrary non-negative ratios such as `25, 20, 20, 10, 10, 15` are
valid and equivalent to `0.25, 0.20, 0.20, 0.10, 0.10, 0.15`. The SDK normalizes without
modifying the caller's values:

```text
total = upstream + citation + assertion_lineage + ownership + temporal + graph
normalized_weight(name) = supplied_weight(name) / total
```

The sum and all following accumulations use ordinary IEEE-754 binary64
operations in this fixed signal order: upstream, citation, assertion_lineage,
ownership, temporal, graph. Unavailable signals have score zero. Their weights remain
in the configuration and are not redistributed to observable signals.

For every unordered pair of distinct sources:

```text
dependency(i,k) = clamp(
    normalized_upstream * upstream(i,k)
  + normalized_citation * citation(i,k)
  + normalized_assertion_lineage * assertion_lineage(i,k)
  + normalized_ownership * ownership(i,k)
  + normalized_temporal * temporal(i,k)
  + normalized_graph * graph(i,k),
  0,
  1
)

weighted_signal_coverage(i,k) =
    (normalized_upstream * upstream_observable(i,k)
   + normalized_citation * citation_observable(i,k)
   + normalized_assertion_lineage * assertion_lineage_observable(i,k)
   + normalized_ownership * ownership_observable(i,k)
   + normalized_temporal * temporal_observable(i,k)
   + normalized_graph * graph_observable(i,k))
    / sum(all six normalized weights)
```

Each observability value is exactly zero or one. Dependency and coverage are
symmetric. Every signal, observability, dependency, and coverage diagonal is
zero. Weighted signal coverage records how much configured signal weight was
observable. It is not a probability that the dependency estimate or either
source is correct.

Sources MUST be ordered by their canonical source payload bytes. The SDK emits
the complete upper triangle in that order. Within graph accumulation,
matching assertions are ordered by canonical property and value bytes.
Relationship signals use boolean existence, so their results do not depend on
collection iteration order. These ordering rules remove incidental dictionary
and set iteration order without changing defined scores.

Conformance-vector numeric outputs are compared as exact binary64 values after
each JSON number is converted to binary64. Implementations MUST use the fixed
operation and accumulation order above; the vectors do not define a tolerance.

### 11.6 Local Dependency Clusters

Clusters are optional local telemetry. No default or calibrated threshold
exists. When the caller supplies a threshold, it MUST be a finite binary64
number in `[0, 1]`. For the relevant supporting sources, construct an
undirected graph with an edge for every pair whose dependency is greater than
or equal to the threshold. The connected components, including singleton
components, are the dependency clusters.

Sources within a component and the components themselves MUST use canonical
source order. The SDK MUST retain the exact threshold and complete membership
for reproducibility. Without an explicit threshold it MUST omit clusters and
cluster explanations. Thresholds and cluster membership never cross MCP.

### 11.7 Local Privacy Boundary

Before an assertion-evaluation call, an assertion-evaluation-capable SDK will canonicalize local
assertions, estimate a symmetric dependency and weighted signal coverage for
every source pair, and link source, attribute, and claim identifiers. It will
send the complete canonical assertion list and source-pair list. Raw
upstream relationships, citations, assertion lineage, owners, timestamps,
retrieval records, raw signals, source names, claim text, and natural-language
explanations remain local. Weighted signal coverage records how much configured dependency-signal
weight was observable; it is not correctness confidence.

After validating the response metadata, schema, token membership, numeric
values, and deterministic ordering, the SDK will map opaque results to its
local names. It may explain server-returned support, contributions, conflicts,
estimated independent support, and dependency confidence using locally retained
signal descriptions. Support is a graph score rather than a truth probability,
and estimated independent support is not a count of verified origins. Local
cluster behavior is defined in Section 11.6.

The deployment does not receive original content or generate natural-language
explanations. Pairwise signal descriptions such as shared ownership or close
timing can appear only in SDK explanations derived from retained local data.

### 11.8 Local Explanations

The Python SDK exposes `explain_claim` and `explain_dependency`. Both accept
only validated typed SDK results, are deterministic and side-effect-free, and
perform no MCP, network, VOPRF, assertion evaluation, logging, or filesystem work. They
return text without a final newline and display binary64 values rounded to two
decimal places without modifying the typed result.

Claim explanations call the graph score `Support`, state the supporting-source
count and `Independent support`, and use singular grammar for one
source. They emit `Highest support` only when the engine's
`is_attribute_max_support` field is true. Conflicts retain result order. Signal
coverage and dependency clusters remain available in the typed result but are
not part of the default claim explanation.

Independent support estimates how much independent evidence supports a claim
after accounting for source dependency. It is a continuous value, not an
integer or a literal source count. With four fully independent supporting
sources, the value approaches 4. If those sources are highly dependent, the
value may be much lower.

Dependency explanations display `1 - dependency` as `Independence`. They use
locally retained evidence summaries to report upstream and citation direction,
derived assertion counts, common ownership, qualifying update gaps, and
matching-claim counts. Raw identifiers and metadata remain local.
Observed zero and unavailable signals add no fact. These descriptions MUST NOT
classify dependency magnitude or describe copying, coordination, truth
probability, or estimate correctness.

Optional source labels are application-local presentation aliases. Labels MUST
be exact nonempty strings without control characters. They do not affect
canonicalization, identity, linkage, dependency calculation, ordering, or
results and MUST NOT cross MCP. Without an alias, internal sources are displayed
by source kind so their UUID identifiers are not exposed by default.

The server rejects a graph whose response would contain more than 16384 total
conflicting-claim entries. For an attribute with `m` distinct claims, that
attribute contributes `m * (m - 1)` entries because every claim lists every
other claim.

The installed MCP SDK reads a complete newline-delimited stdio frame before
application validation; pre-parse frame-size limiting is unsupported.
Duplicate JSON object keys use the installed parser's last-value semantics.
Timed-out Python assertion-evaluation work cannot be forcibly terminated and retains its
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
