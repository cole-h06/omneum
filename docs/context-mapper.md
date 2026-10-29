# ContextMapper

`ContextMapper` maps retrieval records and tool outputs to Omneum's `Observation` schema. It supports field paths, nested fields, and callable transformations.

Mappings define source identities, structured claims, timestamps, and provenance used by the dependency estimator.

```python
from omneum import ContextMapper, Source

mapper = ContextMapper(
    source=lambda result: Source(
        kind="web_document",
        identifier=result["url"],
    ),
    entity_namespace=lambda result: "service",
    entity="service_id",
    attribute="attribute",
    value="value",
    observation_id="id",
    observed_at="observed_at",
)
```

String arguments reference fields in the input record. Callables receive the record and return the mapped value.

## Fields

| Field | Type | Description |
|---|---|---|
| `source` | `Source` | Source identity |
| `entity_namespace` | `str` | Entity namespace |
| `entity` | `str` | Entity identifier |
| `attribute` | `str` | Claim attribute |
| `value` | JSON value | Claim value |
| `observation_id` | `str` | Observation identifier |
| `observed_at` | aware `datetime` | Observation timestamp |
| `source_modified_at` | aware `datetime \| None` | Source modification timestamp |
| `upstream_sources` | source reference(s) | Source derivation |
| `cited_sources` | source reference(s) | Explicit source citations |
| `parent_observation_ids` | `str` / sequence | Direct observation lineage |
| `retrievals` | sequence of `Retrieval` | Retrieval execution records |
| `metadata` | mapping | Additional observation metadata |
| `signals` | mapping | Explicit `DependencySignal` values |

The first seven fields are required. Provenance fields are optional.

## Field paths

String mappings resolve fields from each input record.

```python
mapper = ContextMapper(
    ...,
    entity="company",
    value="revenue",
    observation_id="id",
)
```

Input:

```python
result = {
    "id": "result-42",
    "company": "acme-corp",
    "revenue": 42_000_000,
}
```

Mapped values:

```text
entity          acme-corp
value           42000000
observation_id  result-42
```

Dotted paths support nested fields. Callables support computed values and normalization:

```python
mapper = ContextMapper(
    ...,
    value=lambda result: normalize_revenue(result),
)
```

The resulting values are used to construct `Source`, `Claim`, and `Observation` objects. Entity resolution and value normalization are handled by the supplied mappings.

## Source

`Source` identifies a resource using a canonical `(kind, identifier)` pair.

```python
from omneum import Source

source = Source(
    kind="web_document",
    identifier="https://example.com/report",
    owner_id="example",
)
```

| Field | Type | Description |
|---|---|---|
| `kind` | `str` | Source type |
| `identifier` | `str` | Canonical resource identifier |
| `owner_id` | `str \| None` | Optional ownership identifier |

### `kind`

Supported source kinds:

| Kind | Resource |
|---|---|
| `web_publisher` | Website or publisher |
| `web_document` | Web page or document |
| `internal_resource` | Internal document or agent memory record |
| `internal_service` | Internal API or service |
| `database` | Database resource or record |

Source kinds identify resources independently of their retrieval mechanism or file format.

### `identifier`

`identifier` provides the resource identity used during canonicalization.

```text
https://example.com/reports/q3
v1:550e8400-e29b-41d4-a716-446655440000:...
```

Records from the same resource resolve to the same canonical source identity. Separate resources retain distinct identities, including when their content is identical.

Use the identifier format defined for each source kind.

See [Canonicalization](canonicalization.md).

### `owner_id`

`owner_id` supplies an ownership signal for dependency estimation.

```python
Source(
    kind="internal_service",
    identifier="v1:...",
    owner_id="billing-platform",
)
```

Use ownership identifiers supplied by the source system, such as a publisher, organization, internal team, or service. Leave the field unset when ownership is unavailable.

## Upstream sources

`upstream_sources` records resource-level derivation, including copied, imported, synchronized, or generated resources.

```python
from omneum import SourceReference

upstream_sources=(
    SourceReference(
        kind="web_document",
        identifier="https://example.com/original",
    ),
)
```

The dependency estimator uses upstream references to identify shared source origins. Unknown upstream relationships remain unset.

## Parent observations

`parent_observation_ids` records direct observation lineage.

```python
Observation(
    observation_id="summary-result",
    ...,
    parent_observation_ids=("retrieval-result",),
)
```

Each parent must reference an observation in the same evaluation and belong to a different canonical source.

For `observation-a → observation-b → observation-c`, the direct parent of `observation-c` is `observation-b`.

The corresponding dependency signal is `assertion_lineage`.

### Unknown vs no parents

| Value | Meaning |
|---|---|
| `None` | Observation lineage unavailable |
| `()` | Lineage observed; no parent observations |
| `("observation-id",)` | Direct parent observation recorded |

The distinction affects signal observability and `weighted_signal_coverage`.

## Citations

`cited_sources` records explicit references to other sources.

```python
cited_sources=(
    SourceReference(
        kind="web_document",
        identifier="https://example.com/source",
    ),
)
```

Citations and upstream derivation are separate provenance signals. Citation metadata does not establish source derivation.

The estimator uses the recorded references to compute source dependencies.

## Source timestamps

`observed_at` records when a retrieval pipeline or agent encountered an assertion. `source_modified_at` records the modification timestamp reported by the source.

```python
Observation(
    ...,
    observed_at=retrieved_at,
    source_modified_at=document.last_modified,
)
```

Example:

```text
source_modified_at  2026-10-01 09:14 UTC
observed_at         2026-10-05 16:22 UTC
```

The temporal dependency signal uses `source_modified_at` and the configured `temporal_window_seconds`.

Leave `source_modified_at` unset when unavailable or insufficiently precise for the configured window.

## Retrievals

`Retrieval` records an execution that returned a source.

```python
from omneum import Retrieval

retrieval = Retrieval(
    retrieval_id="search-42",
    kind="vector_search",
    resource_id="document-17",
    retrieved_at=now,
    fields={
        "rank": 2,
        "query_id": "query-9",
    },
)
```

Multiple retrieval executions can reference the same canonical source. Retrieval metadata is attached to the observation without creating duplicate source–claim edges.

`fields` accepts JSON-compatible metadata from the retrieval system, including ranks, query identifiers, and tool names.

```python
fields={
    "rank": 2,
    "query_id": "query-9",
    "tool": "search_internal_docs",
}
```

Arbitrary `fields` entries do not contribute to dependency estimation.

## Metadata

`metadata` retains additional observation metadata.

```python
metadata={
    "request_id": "req-42",
    "execution_id": "run-7",
    "tool_name": "search_internal_docs",
}
```

Metadata is excluded from dependency estimation. Use typed provenance fields for source derivation, citations, observation lineage, source timestamps, and retrieval executions.

## Missing provenance

The dependency estimator distinguishes observable provenance from unavailable signals.

For two sources with a known shared upstream resource:

```python
Observation(
    ...,
    upstream_sources=(shared_source,),
)
```

If ownership, citation, and observation-lineage metadata are unavailable:

```text
upstream            observed
ownership           unknown
citation            unknown
assertion_lineage   unknown
```

`weighted_signal_coverage` reports the proportion of configured signal weight supported by observable provenance.

With `upstream_weight=0.25` and upstream as the only observable signal:

```text
dependency                1.0
weighted_signal_coverage  0.25
```

`dependency` is the pairwise source dependency estimate. `weighted_signal_coverage` measures provenance availability, not statistical confidence.

## Explicit dependency signals

`DependencySignal` contains a numeric value and an observability flag.

```python
from omneum import DependencySignal

signal = DependencySignal(
    value=1.0,
    observable=True,
)
```

Supported signals:

| Signal | Provenance |
|---|---|
| `upstream` | Shared upstream sources |
| `citation` | Source citations |
| `assertion_lineage` | Parent observations |
| `ownership` | Source ownership |
| `temporal` | Source modification timestamps |
| `graph` | Reserved; currently unobservable |
| `retrieval` | Retrieval execution metadata |

Observability controls whether a signal contributes to the dependency estimate.

| Value | Meaning |
|---|---|
| `DependencySignal(value=0.0, observable=False)` | Signal unavailable |
| `DependencySignal(value=0.0, observable=True)` | Signal observed with zero dependency |
| `DependencySignal(value=1.0, observable=True)` | Signal observed with maximum dependency value |

For standard integrations, the estimator derives signals from `upstream_sources`, `cited_sources`, `parent_observation_ids`, `source_modified_at`, `retrievals`, and `Source.owner_id`.

`ContextMapper.signals` is retained as `Observation.dependency_signals`. These values are not used as estimator overrides in the current evaluation path.

```python
signals={
    "upstream": DependencySignal(
        value=1.0,
        observable=True,
    ),
}
```

The dependency estimate returned by `evaluate_context()` is computed from the supported provenance inputs.

Pairwise dependencies are subsequently applied during provenance-aware graph inference to adjust source contributions and estimate independent claim support.

## Evaluate mapped records

`OmneumClient.evaluate_mapped()` maps retrieval records and runs context evaluation.

```python
async with open_stdio_client(config, server) as client:
    result = await client.evaluate_mapped(
        results,
        mapper,
        estimator=estimator,
    )
```

`evaluate_mapped()` applies the configured mapper to each record and executes the same evaluation path as `evaluate_context()`.

Both return `ContextEvaluation`, containing:

| Field | Description |
|---|---|
| `source_reliability` | Source reliability scores |
| `claim_support` | Claim support and independent-support estimates |
| `pairwise_dependencies` | Source dependency diagnostics |
| `convergence` | Graph inference convergence diagnostics |

See [Python SDK](sdk.md) for client configuration and evaluation APIs.

See [Canonicalization](canonicalization.md) for source identity and value encoding.