# Canonicalization

This document defines the version-1 canonicalization and linkage encoding used
by the Omneum Python SDK.

`evaluate_context()` handles the conversion from structured input to VOPRF
linkage tokens. Source and claim identities must be established before the
SDK receives the records.

The evaluator only receives opaque identifiers. Canonical payloads remain
inside the client process.

## Sources

A source consists of a `kind` and `identifier`. The kind determines which
canonicalization rule the SDK uses.

| Kind | Identifier |
|---|---|
| `web_publisher` | Publisher hostname |
| `web_document` | Document URL |
| `internal_resource` | Logical internal information resource |
| `internal_service` | Logical service |
| `database` | Logical governed datastore |

`package` is reserved and has no version-1 interoperable encoding.

### Web sources

Use `web_publisher` for a hostname:

```text
https://Docs.Anthropic.com/
    -> docs.anthropic.com
```

The input can be a hostname or URI with an empty path or `/`.

| Component | Handling |
|---|---|
| Hostname | Lowercase |
| Trailing DNS dot | Remove one |
| Internationalized hostname | UTS #46 nontransitional, IDNA2008 ASCII |
| Non-root path | Reject |
| Query | Reject |
| Fragment | Reject |

Use `web_document` for an individual URL:

```text
HTTPS://Example.com:443/docs/api#section
    -> https://example.com/docs/api
```

A scheme and host are required.

| Component | Handling |
|---|---|
| Scheme | Lowercase |
| Hostname | Lowercase, UTS #46 nontransitional, IDNA2008 ASCII |
| HTTP port `80` | Remove |
| HTTPS port `443` | Remove |
| Fragment | Remove |
| Path | Retain normalized path; use `/` if empty |
| Query | Retain normalized query |

The URL normalization vectors are part of the version-1 compatibility tests.

### Internal sources

`internal_resource`, `internal_service`, and `database` use scoped UUIDs:

```text
v1:<scope_uuid>:<object_uuid>
```

Example:

```text
v1:01234567-89AB-4DEF-8123-456789ABCDEF:11111111-2222-4333-8444-555555555555
    -> v1:01234567-89ab-4def-8123-456789abcdef:11111111-2222-4333-8444-555555555555
```

| Component | Requirement |
|---|---|
| Prefix | Exact `v1:` |
| UUIDs | Two, separated by one colon |
| UUID format | Hyphenated `8-4-4-4-12` |
| Hexadecimal | Accept either case; emit lowercase |
| UUID version | Unrestricted |
| UUID variant | Unrestricted |
| Nil and Max UUID | Reject |
| Character set | ASCII |
| Canonical length | 76 bytes |

The parser rejects whitespace and non-ASCII characters. It also rejects
braces, compact UUIDs, URI/URN prefixes, and URL-style identifiers.

Paths, query strings, fragments, user information, ports, percent encoding,
and trailing slashes are invalid.

The `scope_uuid` is issued by the system integrating Omneum. It separates
unrelated internal namespaces. Access control for those namespaces is handled
outside canonicalization.

| Kind | Identity |
|---|---|
| `internal_resource` | One logical organization-managed information resource |
| `internal_service` | One logical service |
| `database` | One logical governed datastore |

An internal resource keeps its identity across revisions. A service keeps its
identity across deployments. A database keeps its identity across physical
endpoints.

For databases, tables and query results are normally observations of the
logical datastore. Use separate database identities when the underlying
datasets have different governance or provenance boundaries.

The identifier format excludes connection strings and credentials. Resource
paths, table names, query text, and network addresses are also excluded.

Canonicalizing a valid canonical identifier returns the same 76 bytes.

Parser errors use fixed messages:

| Condition | Error |
|---|---|
| Input type is not exactly a string | `internal source identifier must be a string` |
| Invalid string | `internal source identifier is invalid` |

The original identifier is excluded from error messages and representations.
Underlying parser errors are not exposed.

## Entities

The SDK uses the supplied `entity_namespace` to select the entity
canonicalization rule.

Version 1 implements `service`:

```text
entity_namespace = service
entity = " Payment_Service "

    -> "payment_service"
```

| Operation | Handling |
|---|---|
| Input | String |
| Unicode | NFC |
| Surrounding whitespace | Trim |
| Case | Lowercase |
| Empty result | Reject |

Other namespaces require a defined profile with cross-language test vectors.

## Attributes

Attribute names are normalized as follows:

```text
" Supports  Streaming "
    -> "supports_streaming"
```

| Operation | Handling |
|---|---|
| Input | String |
| Surrounding whitespace | Trim |
| Internal whitespace | Collapse runs to one space |
| Case | Lowercase |
| Spaces | Replace with underscores |
| Empty result | Reject |

## Values

Version 1 accepts these value types:

| Type | Handling |
|---|---|
| Null | Preserve |
| Boolean | Preserve |
| Safe integer | Preserve |
| Finite IEEE-754 binary64 | Preserve, with signed zero normalized |
| String | NFC, trim |
| Array | Canonicalize elements recursively |
| Object | Canonicalize keys and values recursively |

Empty strings are rejected.

Object keys must be strings. Keys are normalized using NFC and trimmed.
Empty keys and duplicates after normalization are rejected.

NaN and infinities are rejected. Positive and negative zero produce the
same canonical value.

For values with units, normalize the units in the retrieval pipeline before
calling Omneum.

```text
"4.2 billion USD"   # String
4200000000          # Integer
```

These remain different values until the retrieval pipeline maps them to
the same structured representation.

## Linkage payloads

The SDK constructs three fixed JSON payloads.

**Source**

```json
{
  "kind": "web_publisher",
  "identifier": "docs.anthropic.com"
}
```

**Attribute**

```json
{
  "entity_namespace": "service",
  "entity": "messages_api",
  "attribute": "supports_streaming"
}
```

**Claim**

```json
{
  "entity_namespace": "service",
  "entity": "messages_api",
  "attribute": "supports_streaming",
  "value": true
}
```

Each schema contains exactly the fields shown above. RFC 8785 determines
the serialized field order.

The source kind is included in the payload. An identical identifier under
a different kind produces a different linkage input.

For a 76-byte internal source identifier:

| Kind | Serialized payload | Linkage input |
|---|---:|---:|
| `internal_resource` | 120 bytes | 137 bytes |
| `internal_service` | 119 bytes | 136 bytes |
| `database` | 111 bytes | 128 bytes |

An assertion has no separate linkage payload. Its source, attribute, and
claim tokens are derived separately.

## Serialization

The payloads are serialized using
[RFC 8785](https://www.rfc-editor.org/rfc/rfc8785).

RFC 8785 specifies exact UTF-8 output. This includes JSON number formatting
and object-key ordering by UTF-16 code units.

Ordinary sorted JSON is not interchangeable with RFC 8785 serialization.

| Property | Version-1 limit |
|---|---|
| Integer range | `-(2^53 - 1)` through `2^53 - 1` |
| Floating-point | Finite IEEE-754 binary64 |
| Nesting depth | 32 |
| Total value nodes | 4,096 |
| Serialized payload | 65,517 bytes |

`1` and `1.0` serialize identically. The same applies to positive and
negative zero.

Serialization fails for unsupported types or values outside these limits.
Non-string object keys and lone Unicode surrogates are invalid.

The serializer receives already-canonical values. It validates and encodes
them without another normalization pass.

## Linkage encoding

The SDK adds a 17-byte header to each serialized payload.

```text
Offset   Size       Field
------   --------   -------------------
0        12 bytes   protocol_label
12       2 bytes    encoding_version
14       1 byte     purpose
15       2 bytes    payload_length
17       N bytes    canonical_payload
```

| Field | Encoding |
|---|---|
| `protocol_label` | Exact bytes `OMNEUM-OPRF\x00` |
| `encoding_version` | Unsigned 16-bit big-endian, value `1` |
| `purpose` | One byte |
| `payload_length` | Unsigned 16-bit big-endian |
| `canonical_payload` | Exact RFC 8785 UTF-8 bytes |

Purpose tags:

| Purpose | Tag |
|---|---|
| Source | `0x01` |
| Attribute | `0x02` |
| Claim | `0x03` |

Version `0` and purpose `0` are reserved.

For a source payload containing the three bytes `61 62 63`:

```text
4f 4d 4e 45 55 4d 2d 4f 50 52 46 00
00 01
01
00 03
61 62 63
```

The same payload uses purpose `02` for an attribute or `03` for a claim.

| Component | Maximum size |
|---|---:|
| Header | 17 bytes |
| Payload | 65,517 bytes |
| Complete input | 65,534 bytes |

The encoder preserves the payload bytes. Empty payloads and unknown versions
or purposes are rejected. Payloads exceeding the size limit are rejected.

The fixed header and explicit length make the encoding prefix-free.

## VOPRF linkage

Version 1 uses [RFC 9497](https://www.rfc-editor.org/rfc/rfc9497) VOPRF mode
with the `ristretto255-SHA512` ciphersuite.

The client blinds the complete linkage input. It retains the original bytes
and private blinding state until finalization.

The evaluator returns an evaluated element with a proof. The client verifies
the proof against its authenticated public-key pin before finalizing.

A finalized token is 64 bytes.

Blinding uses fresh randomness for each round. The evaluated elements and
proofs can differ between rounds, while finalization returns the same token
for an identical input under the same active key.

Other protocol modes are outside version 1.

## Protocol identifiers

Assertion requests contain:

```text
source_id
attribute_id
claim_id
```

Each identifier is the unpadded base64url encoding of a 64-byte finalized
token. No textual prefix is added.

| Field | Purpose |
|---|---|
| `source_id` | Source |
| `attribute_id` | Attribute |
| `claim_id` | Claim |

The complete token identity includes the deployment ID and key version,
along with the VOPRF mode, ciphersuite, and linkage encoding version.

See [Protocol](protocol.md).

## Versioning

| Change | Version |
|---|---|
| Canonical payload bytes or linkage encoding | Linkage encoding |
| VOPRF key rotation | Key |
| Breaking MCP request contract | Protocol |
| Source-reliability or claim-support computation | Algorithm |

Version-1 requests use one linkage encoding version and one key version.

Stored tokens retain their complete identity.

## Conformance

Cross-language SDKs use the language-neutral canonicalization and linkage
test vectors.

| Area | Verification |
|---|---|
| Source profiles | Canonical identifiers |
| Entity profiles | Canonical identifiers |
| Values | Supported types and limits |
| Serialization | Exact RFC 8785 bytes |
| Linkage encoding | Header, lengths, purpose tags |
| Token encoding | Strict unpadded base64url |

New source kinds or entity namespaces require a defined profile and shared
vectors before claiming version-1 interoperability.

Requirement keywords follow
[RFC 2119](https://www.rfc-editor.org/rfc/rfc2119) and
[RFC 8174](https://www.rfc-editor.org/rfc/rfc8174).