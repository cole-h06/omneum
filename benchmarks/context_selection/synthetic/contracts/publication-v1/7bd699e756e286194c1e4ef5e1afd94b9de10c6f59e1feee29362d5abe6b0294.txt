
# Held-Out Dataset

24 synthetic cases across six domains, four cases per domain.

Each directory in [`cases/`](cases/) contains:
- `case.json` — task, candidate context, and provenance
- `ground_truth.json` — expected answers and scoring labels

| File | Purpose |
|---|---|
| [`case_matrix.json`](case_matrix.json) | Case IDs, domains, mechanisms, source roles, and context budgets |
| [`plan.json`](plan.json) | Experimental constraints |
| [`dataset_manifest.json`](dataset_manifest.json) | Original 56-entry SHA-256 contract |

Context budgets: 2–3 candidates per case.

## Validation

From the repository root:

```bash
python -m benchmarks.context_evaluation.heldout.validate_dataset
```

The validator checks dataset structure, graph references, labels, scoring, and consistency.

## Frozen Artifacts

The 48 case and ground-truth files are unchanged. Superseded source snapshots are retained in [`contracts/v1/`](contracts/v1/).

Known discrepancy: `coding_package_fix_lineage` identifies source slot 3 as an issue comment in the matrix and a community note in the case. The fixture remains unchanged.

See the [benchmark methodology](../../README.md) and [source-contract documentation](contracts/README.md).