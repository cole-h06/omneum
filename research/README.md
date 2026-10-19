# Omneum research

Experiments use the production evaluator in `omneum/inference.py`,
`omneum/dependency.py`, and `omneum/engine_graph.py`. Raw text stays in the
retrieval and context-selection code; only structured observations reach the
mathematical evaluator.

- [Algorithm experiments](experiments/algorithm/README.md): controlled graphs and dependency matrices.
- [Agent dataset](experiments/applied/agent_dataset/README.md): fifteen observations from five synthetic agents.
- [Enterprise context selection](experiments/applied/agent_dataset/enterprise/README.md): local retrieval, claim mappings, and token-budget selection.
- `adapters/`: production graph inputs and identity/provenance conversion.
- [Analysis](analysis/README.md) and `figures/`: exploratory diagnostics and illustrations.
- `history/`: older specifications, fixtures, tests, adapters, package metadata,
  [citation](history/CITATION.cff), and [license](history/LICENSE).

Run from the repository root:

```sh
uv run --locked python -m research.experiments.algorithm.mixed_dependencies
uv run --locked python -m research.experiments.applied.agent_dataset.run
uv run --locked --group langgraph python -m research.experiments.applied.agent_dataset.enterprise
uv run --locked --group langgraph python -m research.experiments.applied.agent_dataset.enterprise.context_selection --token-budget 100
uv run --locked --group langgraph pytest tests/test_research.py research/experiments/applied/agent_dataset/tests -q
```

These experiments need no provider credentials, daemon, or persistent context
database. LangGraph remains an optional research dependency. Applied workflows
return a production `ContextEvaluation` alongside the source metadata and
observations. Only evaluation latency varies between identical evaluations.

Structural experiments retain explicitly supplied dependency matrices. Exact
equivalence is supplied separately; a dependency of one does not certify
identical evidence.

The [historical specification](history/spec/algorithm.md) describes an older
algorithm, not current production behavior. Archived tests require that older
implementation and are excluded from the active suite. Historical package names,
manifest paths, and saved result identifiers remain unchanged for reproducibility.
Existing production benchmarks remain in `benchmarks/`; saved research results
and fixtures are not overwritten.
