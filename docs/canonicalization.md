# Omneum Canonicalization and Linkage Encoding

## 1. Introduction

This document defines the version-1 transformation from application values to
the deterministic bytes blinded by the Omneum VOPRF client.

The Python SDK performs this transformation automatically when applications use
the high-level assertion-evaluation API. Applications normally do not construct
canonical linkage payloads or linkage inputs directly.

Before this transformation begins, the application is responsible for semantic
normalization: deciding which retrieved information represents the same entity,
attribute, and structured value.

The SDK then transforms those application-provided structured values through
the deterministic version-1 canonicalization and linkage pipeline:

1. canonicalization according to the applicable Omneum profile;
2. strict fixed-schema RFC 8785 serialization; and
3. versioned, purpose-separated binary linkage encoding.

Canonicalization does not perform semantic matching. The SDK does not use an
LLM or other fuzzy matching step to decide that differently expressed
application data represents the same assertion.

## 2. Requirement Language

The key words **MUST**, **MUST NOT**, **SHOULD**, **SHOULD NOT**, and **MAY**
are to be interpreted as described in RFC 2119 and RFC 8174.

## 3. Status

The repository implements:

- `web_publisher`, `web_document`, `internal_resource`, `internal_service`, and
  `database` source canonicalization;
- the `service` entity namespace;
- attribute and value canonicalization;
- strict source, attribute, and claim serializers;
- the linkage encoding in this document; and
- language-neutral serialization and linkage vectors.

The source kinds with version-1 interoperable canonicalization rules are:

- `web_publisher`;
- `web_document`;
- `internal_resource`;
- `internal_service`; and
- `database`.

The following source-kind name is reserved and deferred:

- `package`.

The reserved kind has no version-1 interoperable canonicalization rule.
Clients MUST NOT claim version-1 conformance for it. Only source kinds with
canonicalization rules specified in this document may claim conformance.

## 4. Canonicalization Profiles

The application supplies the structured source, entity, attribute, and value
data to be evaluated. The SDK canonicalizes those values according to the
deterministic profiles defined below.

These rules normalize representations within an already established semantic
identity. They do not determine whether differently expressed retrieved
information refers to the same entity, attribute, or value. That semantic
normalization remains the application's responsibility.

The deployment does not receive or canonicalize the original values.

### 4.1 Sources

A source consists of a source kind and identifier. The client MUST know the
source kind and MUST NOT infer it from the identifier.

#### `web_publisher`

A client MUST:

- accept a hostname or URI whose path is empty or `/`;
- reject any other path, query, or fragment;
- lowercase the hostname;
- remove one trailing DNS dot; and
- apply UTS #46 nontransitional processing and emit the IDNA2008 ASCII form.

Example:

```text
https://Docs.Anthropic.com/
    -> docs.anthropic.com
```

#### `web_document`

A client MUST:

- require a URI scheme and host;
- lowercase the scheme and host;
- apply UTS #46 nontransitional processing and emit the IDNA2008 ASCII host;
- remove port 80 for HTTP and port 443 for HTTPS;
- remove the fragment;
- retain the normalized path and query; and
- use `/` when the path is empty.

Example:

```text
HTTPS://Example.com:443/docs/api#section
    -> https://example.com/docs/api
```

The precise URI normalization rules must remain covered by cross-language vectors before another SDK claims interoperability.

#### Internal source identifiers

`internal_resource`, `internal_service`, and `database` use the same opaque
identifier grammar:

```text
v1:<scope_uuid>:<object_uuid>
```

The identifier is a structured ASCII value, not a URI or URN. `scope_uuid` is
an application-issued namespace used to prevent accidental collisions between
unrelated internal sources. Authorization to use a namespace is outside
version-1 canonicalization.

A client MUST:

- require the exact, case-sensitive prefix `v1:`;
- require exactly two UUIDs separated by one colon;
- require the hyphenated `8-4-4-4-12` UUID representation;
- accept uppercase or lowercase UUID hexadecimal digits;
- emit lowercase ASCII hexadecimal digits;
- reject the Nil and Max UUID in either position;
- impose no UUID version or variant restriction;
- reject whitespace rather than removing or normalizing it;
- reject non-ASCII input, braces, compact UUIDs, URI or URN prefixes, paths,
  queries, fragments, user information, ports, percent encoding, and trailing
  slashes; and
- produce an identifier of exactly 76 UTF-8 bytes.

Canonicalizing an already canonical identifier MUST return the same 76 bytes.
An input whose exact type is not a string MUST fail with the fixed message
`internal source identifier must be a string`. A malformed string MUST fail
with the fixed message `internal source identifier is invalid`. Failures MUST
NOT include the input or an underlying parser message in error text or
representations.

Example:

```text
v1:01234567-89AB-4DEF-8123-456789ABCDEF:11111111-2222-4333-8444-555555555555
    -> v1:01234567-89ab-4def-8123-456789abcdef:11111111-2222-4333-8444-555555555555
```

The source kinds have these meanings:

- `internal_resource` identifies one logical organization-managed information
  resource. It does not identify a revision, file path, storage location, or
  retrieval event.
- `internal_service` identifies one logical service. It does not identify an
  endpoint, deployment, replica, region, operation, snapshot, or credential.
- `database` identifies one logical governed datastore. It does not identify a
  connection string or physical endpoint. Tables and query results are
  ordinarily observations from the logical database. Applications should
  assign separate database source identities when datasets have materially
  distinct governance or provenance boundaries.

The grammar structurally excludes database credentials, passwords, connection
strings, hostnames, ports, resource paths, table names, and query text.

### 4.2 Entity Namespaces

An entity namespace determines how an entity identifier is interpreted. A
client MUST supply the namespace explicitly and MUST NOT infer
namespace-specific behavior.

The implemented `service` namespace:

- requires a string;
- applies Unicode NFC;
- removes surrounding whitespace;
- rejects an empty result; and
- lowercases the result.

Example:

```text
entity_namespace = service
entity = " Payment_Service "
    -> "payment_service"
```

Additional namespaces require named canonicalization profiles and
cross-language vectors.

### 4.3 Attributes

An attribute:

- is a string;
- has surrounding whitespace removed;
- rejects an empty result;
- collapses each run of whitespace to one space;
- is lowercased; and
- replaces spaces with underscores.

Example:

```text
" Supports  Streaming "
    -> "supports_streaming"
```

### 4.4 Values

Canonical claim values may be:

- null;
- booleans;
- safe integers;
- finite IEEE-754 binary64 numbers;
- Unicode strings;
- arrays; and
- objects with string keys.

Version-1 value canonicalization:

- preserves null and booleans;
- preserves integers;
- rejects NaN and infinities;
- maps positive and negative numeric zero to the same zero value;
- applies NFC and trims strings;
- rejects empty strings;
- recursively canonicalizes arrays;
- applies NFC and trims object keys; and
- rejects empty or duplicate canonical object keys.

Unit conversion and domain-specific value equivalence are outside this
specification. Applications must choose deterministic units before
canonicalization.

Normalization is not idempotently repeated during serialization. The
serializer validates and encodes the values it receives exactly.

## 5. Fixed Linkage Payloads

Version-1 linkage uses exactly three fixed payload schemas. Implementations
MUST NOT add fields to these schemas.

### 5.1 Source

Logical field order is not significant because RFC 8785 orders object keys:

```json
{
  "kind": "web_publisher",
  "identifier": "docs.anthropic.com"
}
```

The schema contains exactly:

```text
kind
identifier
```

The schema and linkage encoding do not change for internal source kinds. The
same identifier used with different source kinds produces distinct RFC 8785
payloads and distinct linkage inputs because `kind` is serialized. For the
76-byte internal identifier, payload and complete linkage-input sizes are:

| Kind | RFC 8785 payload | Complete linkage input |
| --- | ---: | ---: |
| `internal_resource` | 120 bytes | 137 bytes |
| `internal_service` | 119 bytes | 136 bytes |
| `database` | 111 bytes | 128 bytes |

### 5.2 Attribute

```json
{
  "entity_namespace": "service",
  "entity": "messages_api",
  "attribute": "supports_streaming"
}
```

The schema contains exactly:

```text
entity_namespace
entity
attribute
```

### 5.3 Claim

```json
{
  "entity_namespace": "service",
  "entity": "messages_api",
  "attribute": "supports_streaming",
  "value": true
}
```

The schema contains exactly:

```text
entity_namespace
entity
attribute
value
```

There is no linkage payload for a complete assertion. An assertion is
constructed later from independently derived source, attribute, and claim
tokens.

## 6. Strict RFC 8785 Serialization

The fixed payload MUST be serialized using RFC 8785. Implementations MUST
produce identical UTF-8 bytes across supported languages.

The version-1 value model is restricted as follows:

- integers range from `-(2^53 - 1)` through `2^53 - 1`;
- floats are finite IEEE-754 binary64 values;
- `1` and `1.0` intentionally serialize identically;
- positive and negative zero intentionally serialize identically;
- object keys are strings;
- strings contain no lone Unicode surrogate;
- maximum nesting depth is 32;
- maximum total value nodes is 4,096; and
- maximum serialized linkage payload is 65,517 bytes.

RFC 8785 determines number formatting, UTF-8 encoding, escaping, and UTF-16
object-key ordering. Implementations MUST NOT substitute ordinary sorted JSON.

The serializer MUST reject:

- integers outside the safe range;
- NaN and infinities;
- lone surrogates;
- unsupported language-specific types;
- non-string object keys;
- excessive depth;
- more than 4,096 value nodes; and
- payloads longer than 65,517 bytes.

The serializer MUST NOT normalize NFC, whitespace, case, keys, numbers, or
values. Different already-canonical representations remain different inputs
unless RFC 8785 itself assigns them identical bytes.

## 7. Linkage Input Encoding

The exact version-1 binary grammar is:

```text
linkage_input =
    protocol_label       12 bytes
    encoding_version      2 bytes
    purpose               1 byte
    payload_length        2 bytes
    canonical_payload     payload_length bytes
```

Fields:

| Field | Encoding |
| --- | --- |
| `protocol_label` | Exact bytes `OMNEUM-OPRF\x00` |
| `encoding_version` | Unsigned 16-bit big-endian integer, value `1` |
| `purpose` | One-byte purpose tag |
| `payload_length` | Unsigned 16-bit big-endian byte length |
| `canonical_payload` | Exact RFC 8785 UTF-8 bytes |

The header is exactly 17 bytes. Version `0` and purpose `0` are reserved.

Purpose tags are:

| Purpose | Tag |
| --- | ---: |
| Source | `0x01` |
| Attribute | `0x02` |
| Claim | `0x03` |

The encoder MUST:

- accept the canonical payload as exact bytes;
- reject an empty payload;
- reject a payload longer than 65,517 bytes;
- reject unknown or reserved versions and purposes;
- use unsigned big-endian integers;
- preserve the payload bytes without reinterpretation; and
- produce a complete input no longer than 65,534 bytes.

The label, explicit fields, fixed widths, and payload length make the encoding
prefix-free and independent of locale or platform conventions.

Changing the purpose or encoding version deliberately changes the VOPRF input
and finalized output.

### 7.1 Header Example

For a source payload of three bytes `61 62 63`, the complete input is:

```text
4f 4d 4e 45 55 4d 2d 4f 50 52 46 00
00 01
01
00 03
61 62 63
```

For the same payload as an attribute, byte 14 is `02`. As a claim, it is `03`.

## 8. VOPRF Linkage

Version 1 uses only RFC 9497 VOPRF mode with the ristretto255-SHA512
ciphersuite. Implementations MUST NOT substitute another protocol mode or
deterministic linkage algorithm.

The client blinds the complete linkage input. It retains that exact input and
the corresponding private client state. After receiving an evaluated element
and proof, it verifies the proof against its authenticated public-key pin and
finalizes with the retained input and state.

Independent rounds for identical inputs use different randomized blinded
elements and may receive different randomized proofs. Successful finalization
produces the same 64-byte token under the same active key.

Source, attribute, and claim purposes occupy distinct linkage domains even when
their canonical payload bytes are identical.

## 9. Protocol Identifiers

Protocol assertions retain:

```text
source_id
attribute_id
claim_id
```

Each field contains an unpadded base64url encoding of a 64-byte finalized token
without a textual prefix.

The fields imply purpose:

- `source_id` is a source-purpose token;
- `attribute_id` is an attribute-purpose token; and
- `claim_id` is a claim-purpose token.

Token identity also includes deployment ID, key version, mode, ciphersuite, and
linkage encoding version as defined in `protocol.md`.

## 10. Versioning and Compatibility

Any change that alters the strict canonical payload bytes or the binary linkage
encoding requires a new linkage encoding version.

A new VOPRF key uses a new key version, not a new linkage encoding version.
A breaking change to a released MCP request contract requires a new protocol version. A change to the source-reliability or claim-support algorithm used during assertion evaluation requires a new algorithm version.

Version 1 does not mix linkage or key versions within one request. Stored tokens
must retain their complete token identity for as long as they remain in use.

## 11. Conformance

A serializer or SDK claiming version-1 conformance MUST pass the
language-neutral canonical serialization and linkage input vectors.

Conformance requires agreement on:

- canonicalization profiles actually claimed by that SDK;
- supported value types and bounds;
- exact RFC 8785 bytes;
- exact header bytes and lengths;
- purpose tags; and
- strict unpadded base64url token encoding.

Support for an undefined source kind or entity namespace is not interoperable
unless a deterministic profile and shared test vectors are added.
