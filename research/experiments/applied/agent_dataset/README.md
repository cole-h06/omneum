# Agent dataset

Five synthetic agents return fifteen observations. A thin adapter converts the
research records to Omneum production observations. Sequential and LangGraph
workflows produce the same evaluation; neither uses an LLM or external retrieval.
See the [research index](../../../README.md) for execution commands.

`load_dataset()` returns `(sources, observations)`. Each observation contains
`assertion_id`, `source_id`, `entity_namespace`, `entity`, `attribute`, and `value`,
with `observed_at`, `source_modified_at`, `upstream_source_ids`, `cited_source_ids`,
`parent_assertion_ids`, `retrievals`, `metadata`, and `dependency_signals`.
`AgentResult.observations` and workflow results retain these records.

Provenance belongs to each observation. Unknown relationship metadata is `None`;
an empty tuple means capture found no relationships. Timestamps must be
timezone-aware. The fixture uses the namespace `agent_dataset`. Extensible
`metadata` and `dependency_signals` mappings do not override provenance-derived
estimator signals.

The dataset includes upstream relationships, citations, assertion lineage,
shared ownership, structural overlap, and independent conflicting information.
Structural overlap is not active provenance. Modification-time proximity is
unavailable in this dataset; observation times do not substitute for it.
Direct relationships use a maximum; contextual signals use a weighted sum.
Dependency discounts forward contributions, but does not guarantee every
converged claim score decreases.

## Experimental weights

```text
upstream             0.25
citation             0.20
assertion_lineage    0.20
ownership            0.10
temporal             0.10
graph                0.15
retrieval            0.00
```

These weights are hand-tuned, not calibrated against labeled source-dependency
data. The adapter uses a two-hour temporal window. The inactive graph weight
remains in the normalization denominator. These are experimental settings,
not universal defaults.

The LangGraph workflow runs agents in parallel, then collects results in a fixed
order before validation and production evaluation:

```python
from research.experiments.applied.agent_dataset.workflow.pipeline import run_workflow

result = run_workflow()
```

The [enterprise experiment](enterprise/README.md) retrieves synthetic business
facts from local documents, SQLite, and a vendor API snapshot before using the
same dependency and evaluation interfaces.
