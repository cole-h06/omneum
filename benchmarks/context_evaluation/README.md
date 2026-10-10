
# Context Evaluation

Benchmark implementation for evaluating context selection across 24 held-out cases.

Methodology, setup, metrics, and limitations are documented in the [benchmark README](../README.md). Published results are in the [leaderboard](../leaderboard.md).

## Implementation

The evaluation runner is available at `benchmarks.context_evaluation.heldout.run_benchmark`.

Run it from the repository root:

```bash
python -m benchmarks.context_evaluation.heldout.run_benchmark --help
```

The held-out dataset is fixed. Case definitions and labels are documented in [DATASET.md](heldout/DATASET.md).

Recorded runs are documented in [EVIDENCE.md](heldout/EVIDENCE.md). The [publication manifest](publication_manifest_v1.json) records hashes for public artifacts.

## Verification

Validate the dataset:

```bash
python -m benchmarks.context_evaluation.heldout.validate_dataset
```

Check the published dashboard summary:

```bash
python -m benchmarks.context_evaluation.heldout.build_dashboard_summary --check
```

Run the offline benchmark tests:

```bash
python tools/run_context_evaluation_tests.py
```

These checks do not rerun the published model evaluations. Reproduction requirements and provider configuration are documented in the [benchmark README](../README.md).