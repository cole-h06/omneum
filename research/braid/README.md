# BRAID research

These experiments run against Omneum's production evaluator in
`omneum/inference.py`, `omneum/dependency.py`, and `omneum/engine_graph.py`.
The imported specifications describe the older research algorithm; they are
preserved unchanged and are not the definition of current production behavior.

From the Omneum repository root, run the sequential 15-observation experiment:

```sh
uv run --locked python -m research.braid.experiments.applied.agent_dataset.run
```

Run the enterprise experiment with its local documents, in-memory SQLite data,
and captured vendor response:

```sh
uv run --locked --group langgraph python -m research.braid.experiments.applied.agent_dataset.enterprise
```

Both commands print source reliability, claim support, algorithm version and
iteration count. They require no provider credentials, daemon or persistent
context database. The LangGraph workflow uses the existing optional `langgraph`
dependency group; no research dependency was added to the production package.

Run a structural experiment or the adapter regressions:

```sh
uv run --locked python -m research.braid.experiments.algorithm.mixed_dependencies
uv run --locked --group langgraph pytest tests/test_braid_research.py -q
```

- `adapters/`: identity and provenance conversion, and structural graph inputs.
- `experiments/`: synthetic agent, enterprise and direct graph experiments.
- `spec/`: unchanged historical mathematical specifications and manifest.
- `research/analysis/` and `research/figures/`: original diagnostic calculations and figures.
- `history/`: original fixtures, tests, adapters and package metadata.
- [Migration record](migration-map.md): original paths and production adapters.
- [Citation](CITATION.cff) and [license](LICENSE): original attribution.

Applied experiments return a production `ContextEvaluation` in `result["evaluation"]`,
with original source metadata and observations beside it. The former graph,
hybrid-matrix and `debug` interfaces are historical. Dependency signals and
coverage are available through `evaluation.pairwise_dependencies`; scores and
contributions through `evaluation.claim_support` and `evaluation.source_reliability`.
Only evaluation latency is expected to vary between identical executions.

Structural experiments retain their explicitly supplied dependency matrices.
Exact equivalence must be supplied separately; a dependency of one does not
certify identical evidence. Historical sparse zero matrices have been expanded
explicitly, and formerly implicit attributes are now declared in each input.

Existing Omneum benchmarks and external evaluations remain in their original
locations. These experiments do not overwrite their artifacts.
