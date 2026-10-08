# Evaluate Context

`evaluate_context` evaluates a set of observations and returns source reliability, claim support, conflicts, and dependency-adjusted support.

The Python SDK handles canonicalization, private linkage, and source-dependency estimation before sending the evaluation to the local evaluator.

## Evaluate observations

```python
result = await client.evaluate_context(observations)
```

`observations` is a sequence of `Observation` objects. Each observation connects a source to a claim and can include provenance used to estimate source dependence.

```python
from omneum import Claim, Observation, Source

observations = [
    Observation(
        observation_id="obs-1",
        source=Source(
            kind="web_document",
            identifier="https://example.com/report",
        ),
        claim=Claim(
            entity_namespace="company",
            entity="acme",
            attribute="revenue",
            value="42 million",
        ),
    )
]

result = await client.evaluate_context(observations)
```

The application decides what constitutes the same source, entity, attribute, and value. Omneum doesn't use an LLM or fuzzy matching to determine whether two application values refer to the same thing.

See [`context_mapper.md`](../context_mapper.md) for the mapping boundary.

## Observations

An `Observation` records one source asserting one claim:

```text
Source ── Observation ──► Claim
```

The source identifies where the context came from. The claim identifies what was stated. The observation connects them and carries the provenance available for that occurrence.

A retrieval is not necessarily a source. If a retrieval system returns several chunks from the same document, those chunks should normally identify the same document as their source. Treating each chunk as a different source makes one document appear to be several independent sources.

`observed_at` is when the application encountered the observation. `source_modified_at` is when the source itself was last modified, when that time is known.

Don't copy `observed_at` into `source_modified_at` when the modification time is unavailable.

## Source dependence

Omneum estimates dependence between every unordered pair of sources before graph evaluation.

The estimator can use:

- upstream lineage;
- citations;
- assertion lineage;
- shared ownership;
- temporal proximity;
- graph redundancy.

Each pair receives a dependency value and `weighted_signal_coverage`.

Missing provenance doesn't mean two sources are independent. It means Omneum has less information available to estimate their dependence.

Omneum uses the resulting dependency matrix when computing source reliability and claim support. The SDK estimates these dependencies before graph propagation.

### Explicit exact equivalence

Derivation, parentage, citations, matching claims, ownership, and timestamps do
not certify that two sources represent identical evidence. They continue to
feed the dependency estimator without creating equivalence components.

When the application can certify identical evidence across all evaluated
claims, with neither representation adding evidence, it can declare this
explicitly:

```python
from omneum import ExactEquivalence, SourceReference

result = await client.evaluate_context(
    observations,
    estimator=estimator,
    exact_equivalences=(ExactEquivalence(
        SourceReference("web_document", "https://example.com/original"),
        SourceReference("web_document", "https://example.com/exact-copy"),
    ),),
)
```

The default is no equivalences. Both endpoints must occur in the evaluation.
The SDK canonicalizes the references and sets the typed request pair field
`exact_equivalence` (default `false`) only for declared pairs. The former
experimental `lineage` request field is not accepted as an alias.

Inference computes on explicit equivalence components. Members must have the
same claim profile, and dependencies between any two components must agree
across all member pairs; inconsistent declarations are rejected. Component
reliability, independence, and contribution are allocated to members after
scoring. Do not multiply the reported member shares together to reconstruct
contributions: the factors were multiplied at component level before allocation.

## Evaluate mapped records

Applications with existing structured records can use `evaluate_mapped()` with a `ContextMapper`:

```python
result = await client.evaluate_mapped(records, mapper)
```

The mapper extracts the source, entity, attribute, value, observation identity, timestamps, and available provenance from each record. Omneum then runs the same evaluation path as `evaluate_context()`.

`evaluate_mapped()` is an SDK convenience. It isn't a separate MCP tool.

See [`context_mapper.md`](../context_mapper.md) for the complete mapping interface.

## Results

`evaluate_context()` returns a `ContextEvaluation`.

The result contains source reliability scores, claim support, independent-support estimates, source contributions, conflicts, dependency coverage, and evaluation metadata.

### Source reliability

Each source receives a reliability score.

Reliability is the normalized source score produced by Omneum. It isn't a probability that the source is truthful.

### Claim support

Each claim receives:

| Field | Description |
|---|---|
| `support` | Omneum support for the claim |
| `agreement_weight` | Share of sources for the attribute asserting the claim |
| `is_attribute_max_support` | Whether the claim is tied for the greatest support for its attribute |
| `supporting_source_count` | Number of sources asserting the claim |
| `estimated_independent_support_count` | Dependency-adjusted estimate of independent support |
| `dependency_signal_coverage` | Dependency-signal coverage across the supporting sources |
| `supporting_sources` | Per-source independence and contribution |
| `conflicting_claims` | Other claims for the same attribute and their support |

`support` isn't a probability that the claim is true.

### Independent support

Source count and independent support are separate.

Five sources can support the same claim without representing five independent sources. If some of those sources depend on one another, `estimated_independent_support_count` discounts the duplicated support.

For `n` supporting sources:

```text
estimated_independent_support_count =
    n² / (n + 2Σ dependency(i,k))
```

Each unordered pair of supporting sources is included once.

### Conflicts

Different claims mapped to the same attribute are evaluated together.

If sources assert different values for that attribute, Omneum returns the competing claims and their support. It doesn't collapse them into one value or treat the highest-support claim as ground truth.

Correct conflict detection depends on correct mapping. Two records mapped to different entities or attributes aren't treated as competing claims.

## MCP tool

The underlying MCP tool is:

```text
evaluate_context
```

Python applications normally don't construct this request directly. The SDK canonicalizes the application objects, derives their private linkage identifiers, estimates source dependence, and builds the request.

The wire representation uses `assertions` rather than `Observation` objects:

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
      "source_id": "<opaque linkage token>",
      "attribute_id": "<opaque linkage token>",
      "claim_id": "<opaque linkage token>"
    }
  ],
  "source_pairs": []
}
```

Each assertion contains:

| Field | Description |
|---|---|
| `source_id` | Private linkage identifier for the source |
| `attribute_id` | Private linkage identifier for the attribute |
| `claim_id` | Private linkage identifier for the claim |

The request contains every unordered source pair, including pairs with zero estimated dependency:

```json
{
  "source_a_id": "<opaque linkage token>",
  "source_b_id": "<opaque linkage token>",
  "dependency": 0.0,
  "weighted_signal_coverage": 1.0
}
```

The evaluator receives the dependency values, not the provenance used to compute them.

## Limits

Version 1 supports:

| Object | Maximum |
|---|---:|
| Sources | 64 |
| Attributes | 2,048 |
| Claims | 4,096 |
| Source pairs | 2,016 |

Assertions and source pairs must be complete, canonical, and deterministically ordered.

Duplicate assertions, incomplete source-pair matrices, invalid linkage identifiers, malformed graph structure, and non-finite dependency values are rejected rather than repaired.

## Persistence

`evaluate_context` doesn't require a database.

With local persistence disabled, evaluations are request-scoped and Omneum runs without PostgreSQL or a persistent context graph.

When local persistence is enabled, completed evaluations can also be written to the deployment's local context graph. Persistence doesn't change the `evaluate_context` request or response.

Local persistence doesn't enable network contribution.

## Errors

Invalid requests and failed evaluations return Omneum error codes rather than partial evaluation results.

See [`errors.md`](errors.md) for the error contract and [`protocol.md`](../protocol.md) for protocol-wide validation and resource limits.
