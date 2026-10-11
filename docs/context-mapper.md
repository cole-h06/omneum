# ContextMapper

`ContextMapper` converts application records into Omneum `Observation` objects.

Pass a field name when the value already exists on the record. Pass a callable when it needs to be constructed or normalized.

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

`source`, `entity_namespace`, `entity`, `attribute`, `value`, `observation_id`, and `observed_at` are required.

Leave optional provenance fields unset when the application doesn't have them. `None` and an observed negative relationship are not equivalent.

## Fields

| Field | Type | What to put here |
|---|---|---|
| `source` | `Source` | Resource that supplied the value |
| `entity_namespace` | `str` | Namespace used to canonicalize `entity` |
| `entity` | `str` | Stable ID of the entity whose attribute was observed |
| `attribute` | `str` | Attribute observed on `entity` |
| `value` | JSON value | Observed value |
| `observation_id` | `str` | ID for this occurrence within the evaluation |
| `observed_at` | aware `datetime` | When the application observed the value |
| `source_modified_at` | aware `datetime \| None` | Modification time reported by the source |
| `upstream_sources` | source reference(s) | Resources this source was copied, imported, or derived from |
| `cited_sources` | source reference(s) | Resources explicitly referenced by this source |
| `parent_observation_ids` | `str` / sequence | Direct observations used to produce this observation |
| `retrievals` | sequence of `Retrieval` | Retrieval executions that returned this source |
| `metadata` | mapping | Application data retained with the observation |
| `signals` | mapping | Explicit `DependencySignal` values; not estimator overrides |

## Field paths

A string reads that field from the input record:

```python
mapper = ContextMapper(
    ...,
    entity="company",
    value="revenue",
    observation_id="id",
)
```

For:

```python
result = {
    "id": "result-42",
    "company": "acme-corp",
    "revenue": 42_000_000,
}
```

the mapper reads:

```text
entity          acme-corp
value           42000000
observation_id  result-42
```

Dotted paths can read nested fields.

Use a callable when the value doesn't exist directly on the record:

```python
mapper = ContextMapper(
    ...,
    value=lambda result: normalize_revenue(result),
)
```

Normalization belongs here when the application needs it before Omneum sees the value.

## Source

`source` returns a `Source`:

```python
Source(
    kind="web_document",
    identifier="https://example.com/report",
    owner_id="example",
)
```

The object has three fields:

```python
Source(
    kind: str,
    identifier: str,
    owner_id: str | None = None,
)
```

### `kind`

Supported source kinds:

```text
web_publisher
web_document
internal_resource
internal_service
database
```

Use the kind that describes the resource being identified.

Examples:

```text
company website                 web_publisher
specific page or document       web_document
agent memory record             internal_resource
internal API/service            internal_service
database record                 database
```

Don't create a new source kind for the file format or framework that happened to return it. A Markdown file in an agent's memory store is still an `internal_resource` if the memory record is the resource being identified.

### `identifier`

`identifier` must identify the resource, not its contents.

Examples:

```text
https://example.com/reports/q3
v1:550e8400-e29b-41d4-a716-446655440000:...
```

For a database source, use the canonical database identifier expected by Omneum's source canonicalization rules.

Two observations from the same underlying resource should resolve to the same canonical source identity.

Don't substitute a content hash for resource identity. Two copied documents can contain identical bytes while remaining separate sources. Omneum needs to preserve that distinction so their relationship can be evaluated.

See [Canonicalization](canonicalization.md) for the exact identifier rules for each source kind.

### `owner_id`

Set `owner_id` when the source system exposes an owner:

```python
Source(
    kind="internal_service",
    identifier="v1:...",
    owner_id="billing-platform",
)
```

Examples include a publisher, organization, internal team, or service identity supplied by the source system.

Don't infer ownership from similar names, URLs, content, or retrieval behavior.

If ownership isn't known:

```python
Source(
    kind="internal_service",
    identifier="v1:...",
)
```

## Upstream sources

`upstream_sources` records source derivation.

Use it when the current resource was copied, imported, generated, synchronized, or otherwise derived from another known resource.

```text
source-a
   │
   ▼
source-b
```

Map the upstream resource as a `SourceReference`:

```python
upstream_sources=(
    SourceReference(
        kind="web_document",
        identifier="https://example.com/original",
    ),
)
```

This says something about the relationship between `source-a` and `source-b`. It does not say that one observation was generated from another observation.

If the application doesn't know the upstream source, leave `upstream_sources` unset.

## Parent observations

`parent_observation_ids` records direct observation-level derivation.

```text
observation-a
      │
      ▼
observation-b
```

For example:

```python
Observation(
    observation_id="summary-result",
    ...,
    parent_observation_ids=("retrieval-result",),
)
```

`retrieval-result` must be another `observation_id` in the same evaluation and must belong to a different canonical source.

Only put direct parents here. Don't expand a parent chain yourself.

Given:

```text
observation-a
      │
      ▼
observation-b
      │
      ▼
observation-c
```

the parent of `observation-c` is `observation-b`, not both `observation-a` and `observation-b`.

The dependency estimator retains the algorithm name `assertion_lineage` for this signal.

### Unknown vs no parents

These are different:

```python
parent_observation_ids=None
```

The application did not capture observation lineage.

```python
parent_observation_ids=()
```

The application captured observation lineage and this observation has no parents.

Don't replace `None` with `()` just to fill the field. The distinction changes signal coverage.

## Citations

`cited_sources` records explicit references made by the source:

```python
cited_sources=(
    SourceReference(
        kind="web_document",
        identifier="https://example.com/source",
    ),
)
```

Use this when the source actually cites or references another source.

A citation is not upstream lineage.

```text
document-a cites document-b
```

does not imply:

```text
document-a was derived from document-b
```

Don't populate `cited_sources`, `upstream_sources`, or `parent_observation_ids` because two pieces of text are similar. Semantic similarity is not provenance.

## Source timestamps

Every observation has `observed_at`:

```python
Observation(
    ...,
    observed_at=retrieved_at,
)
```

This is when the application encountered the value.

Set `source_modified_at` separately when the source exposes its own modification time:

```python
Observation(
    ...,
    observed_at=retrieved_at,
    source_modified_at=document.last_modified,
)
```

For example:

```text
source_modified_at  2026-10-01 09:14 UTC
observed_at         2026-10-05 16:22 UTC
```

The source changed on October 1. The application encountered it on October 5.

Don't copy `observed_at` into `source_modified_at`. If the source doesn't expose a modification time, leave `source_modified_at` unset.

If the only available source timestamp is too coarse for the estimator's configured temporal window, leave it unset rather than inventing precision.

## Retrievals

`Retrieval` records the execution that surfaced a resource:

```python
Retrieval(
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

A retrieval is not a source.

The same source can be returned by multiple retrievals:

```text
retrieval-1 ──┐
              ├── source-a
retrieval-2 ──┘
```

Keep those executions on the observation instead of creating duplicate source/claim edges.

`fields` accepts JSON data emitted by the retrieval system:

```python
fields={
    "rank": 2,
    "query_id": "query-9",
    "tool": "search_internal_docs",
}
```

Omneum doesn't assign dependency semantics to arbitrary `fields` entries.

## Metadata

Use `metadata` for application data that should travel with the observation but doesn't map to one of Omneum's provenance fields:

```python
metadata={
    "request_id": "req-42",
    "execution_id": "run-7",
    "tool_name": "search_internal_docs",
}
```

`metadata` doesn't participate in dependency estimation.

A `request_id` stored in `metadata`, for example, does not cause two sources to be treated as dependent.

If a field describes an actual upstream source, citation, parent observation, source timestamp, or retrieval execution, use the corresponding typed field instead of hiding it in `metadata`.

## Missing provenance

Don't encode missing provenance as zero.

Suppose the application knows that `source-a` and `source-b` share an upstream source, but has no ownership or citation data.

Map the upstream source:

```python
Observation(
    ...,
    upstream_sources=(shared_source,),
)
```

Leave the unavailable fields unset.

The estimator should see:

```text
upstream            observed
ownership           unknown
citation            unknown
assertion_lineage   unknown
```

not:

```text
upstream            1
ownership           0
citation            0
assertion_lineage   0
```

The second version claims the application checked ownership, citations, and observation lineage and found no relationship. That is different data.

This distinction is exposed through `weighted_signal_coverage`.

With:

```text
upstream_weight = 0.25
```

and upstream provenance as the only observable signal, a pair can return:

```text
dependency                1.0
weighted_signal_coverage  0.25
```

`dependency` is the pairwise dependency estimate computed from the observable signals.

`weighted_signal_coverage` is the fraction of configured signal weight for which the estimator had observable data.

A coverage value of `0.25` does not mean the dependency estimate is 25% confident.

## Explicit dependency signals

`signals` accepts named `DependencySignal` objects:

```python
DependencySignal(
    value=1.0,
    observable=True,
)
```

The current signal names are:

```text
upstream
citation
assertion_lineage
ownership
temporal
graph
retrieval
```

`observable` is part of the signal value.

```python
DependencySignal(
    value=0.0,
    observable=False,
)
```

means the application did not observe that signal.

```python
DependencySignal(
    value=0.0,
    observable=True,
)
```

means the application had enough data to evaluate the signal and observed no dependency through that mechanism.

Those values are not interchangeable.

In normal integrations, prefer the concrete provenance fields:

```text
upstream_sources
cited_sources
parent_observation_ids
source_modified_at
retrievals
Source.owner_id
```

Omneum derives dependency signals from those fields.

`ContextMapper.signals` is currently retained as `Observation.dependency_signals`, but the evaluation path does not use those values as estimator overrides. Setting:

```python
signals={
    "upstream": DependencySignal(
        value=1.0,
        observable=True,
    ),
}
```

does not override the dependency estimate returned by `evaluate_context()`.

## Evaluate mapped records

Pass the application records and mapper to `evaluate_mapped()`:

```python
async with open_stdio_client(config, server) as client:
    result = await client.evaluate_mapped(
        results,
        mapper,
        estimator=estimator,
    )
```

`evaluate_mapped()` maps each input record to an `Observation` and runs the same context-evaluation path as `evaluate_context()`.

Both return `ContextEvaluation`.

For result handling and client setup, see the [Python SDK](sdk.md).

For exact source and value encoding rules, see [Canonicalization](canonicalization.md).