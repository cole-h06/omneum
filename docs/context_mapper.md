# ContextMapper reference

`ContextMapper` maps an application's existing runtime records into the canonical fields Omneum uses for evaluation and dependency estimation.

`ContextMapper` takes the application's object as-is. Each argument is either a dotted field path or a callable:

```python
mapper = ContextMapper(
    source=lambda x: ...,
    entity_namespace=lambda x: ...,
    entity="entity_id",
    attribute="attribute",
    value="value",
    assertion_id="id",
    observed_at="observed_at",
)
```

The first seven fields are required. Everything after that is optional. If the application doesn't know something, leave it unset. In particular, don't turn missing provenance into an empty/negative observation.

## Fields

| field | type | notes |
| --- | --- | --- |
| `source` | `Source` | Identity of the resource the assertion came from. |
| `entity_namespace` | `str` | Namespace for `entity`; e.g. `company`, `package`, `device`. |
| `entity` | `str` | Stable ID of the thing being described. |
| `attribute` | `str` | Property being asserted. |
| `value` | JSON value | The asserted value. Normalize application-specific representations here if necessary. |
| `assertion_id` | `str` | ID of this assertion instance. This is what `parent_assertion_ids` points at. |
| `observed_at` | aware `datetime` | When this application saw the assertion. |
| `source_modified_at` | aware `datetime \| None` | Source's own last-modified time, if actually known. |
| `upstream_sources` | source ref(s) | Physical/source lineage: this resource came from these resources. |
| `cited_sources` | source ref(s) | Explicit references made by this source. |
| `parent_assertion_ids` | `str`/sequence | Assertion-level derivation. Different from source lineage. |
| `retrievals` | `Retrieval` sequence | Retrieval executions which surfaced the information. |
| `metadata` | mapping | Anything useful to retain that isn't one of the fields above. |
| `signals` | mapping | Escape hatch for supplying an already-computed canonical dependency signal. Usually don't use this for raw application metadata. |

## Source identity

```python
Source(
    kind: str,
    identifier: str,
    owner_id: str | None = None,
)
```

`identifier` should answer: **are these two assertions coming from the same underlying resource?**

So a document ID, canonical URI, database record ID, etc. is useful. A content hash usually isn't: two copied documents can have identical content and still be two source records whose relationship we want to detect.

`kind` is the source class (`markdown_document`, `web_document`, `agent_memory`, etc.).

`owner_id` is optional. Use an owner/team/service identity only if the source system gives you one. Don't infer it.

## Lineage

There are two intentionally separate levels here.

`upstream_sources` is source lineage:

```text
document B was copied/imported/derived from document A
```

The target shape is:

```python
SourceReference(kind="...", identifier="...")
```

`parent_assertion_ids` is assertion lineage:

```text
assertion B was produced from assertion A
```

Its values are other `assertion_id`s.

`cited_sources` is neither of those. It's for an explicit source reference/citation.

Similarity by itself does not belong in any of these fields.

## Retrievals

```python
Retrieval(
    retrieval_id: str,
    kind: str,
    resource_id: str,
    retrieved_at: datetime,
    fields: dict = {},
)
```

A retrieval is an execution/event, not the source itself. The same source can therefore show up through multiple retrievals.

`fields` is intentionally open-ended JSON data. If the retrieval system exposes rank, query ID, tool information, etc., it can live there.

## Explicit signals

Current names:

```text
upstream
citation
assertion_lineage
ownership
temporal
graph
retrieval
```

An explicit signal is:

```python
DependencySignal(value=0.0, observable=True)
```

or, if there was no observation:

```python
DependencySignal(value=0.0, observable=False)
```

Those are deliberately different.

Most integrations should map concrete provenance into `upstream_sources`, `cited_sources`, `parent_assertion_ids`, etc. and let Omneum compute the signals. `signals` exists for cases where the integration already has something that genuinely matches one of Omneum's signal semantics.

## Missing fields

This matters for the dependency estimator.

If an application gives us a definite upstream relationship and nothing else, the mapping should look conceptually like:

```text
upstream_sources  = <known source>
owner_id          = unknown
cited_sources     = unknown
assertion lineage = unknown
```

Not:

```text
upstream  = 1
ownership = 0
citation  = 0
...
```

The former means "we observed upstream provenance and don't know the rest." The latter claims we checked the other relationships and found none.

With the current estimator, an upstream-only observation can therefore produce:

```text
dependency                1.0
weighted_signal_coverage  0.25
```

assuming the configured upstream weight is `0.25`.

That's intentional: the estimate says the relationship we *did* observe is strong; coverage says we didn't have much metadata to work with.

The important distinction at the mapping boundary is between "the application doesn't have this information" and "the application has this information and observed no relationship."