# Cross-Domain Context Curation Benchmark

Benchmark implementation for evaluating context selection across 24 synthetic cases.

Methodology, setup, metrics, and limitations are documented in the [benchmark README](../README.md). Published results are in the [leaderboard](../leaderboard.md).

## Implementation

The current evaluation runners are `benchmarks.context_selection.synthetic.tier1_benchmark` and `benchmarks.context_selection.synthetic.tier1_competitors`.

Inspect runner options from the repository root:

```bash
python -m benchmarks.context_selection.synthetic.tier1_benchmark --help
python -m benchmarks.context_selection.synthetic.tier1_competitors --help
```

The synthetic dataset is fixed. Case definitions and labels are documented in [DATASET.md](synthetic/DATASET.md).

Recorded runs are documented in [EVIDENCE.md](synthetic/EVIDENCE.md). The [publication manifest](publication_manifest_v1.json) records hashes for the historical experiments; it does not cover the current evaluation.

## Verification

Validate the original case fixtures:

```bash
python -m benchmarks.context_selection.synthetic.validate_dataset
```

Inspect the saved final recovery evaluation validation record:

```bash
python -m json.tool \
  benchmarks/context_selection/synthetic/results/budget-exhaustion-recovery-20261026-v2/analysis_validation.json
```

Run the offline benchmark tests:

```bash
python tools/run_context_evaluation_tests.py
```

CI uses `python tools/run_context_evaluation_tests.py --unit-only` for an explicit offline artifact and unit-test suite that excludes model-backed evaluation and daemon integration.

These checks do not rerun the published model evaluations. Reproduction requirements and provider configuration are documented in the [benchmark README](../README.md).
