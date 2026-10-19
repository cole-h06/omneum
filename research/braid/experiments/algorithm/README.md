# Direct BRAID Experiments

These experiments study BRAID on a shared synthetic context. The context is defined in [`context.py`](context.py) as a set of sources, claims, and assertions, with different dependency structures used to examine how BRAID scores the resulting graph.

The authoritative implementation is Omneum's `omneum/inference.py`. These experiments use `../../adapters/structural.py` to build production graphs.

Run an experiment from the repository root:

```bash
uv run --locked python -m research.braid.experiments.algorithm.independent_sources
```

## Experiments

- [`context.py`](context.py) — synthetic context and dependency structures.
- [`independent_sources.py`](independent_sources.py) — independent sources.
- [`dependent_sources.py`](dependent_sources.py) — highly dependent sources.
- [`mixed_dependencies.py`](mixed_dependencies.py) — mixed source dependencies.