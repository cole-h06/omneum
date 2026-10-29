
# Held-Out Dataset

The [Cross-Domain Context Curation Benchmark](../../README.md) evaluates context selection across 24 synthetic cases in six domains, with four cases per domain.

The original fixtures are preserved in [`cases/`](cases/). The current benchmark uses the multi-claim annotations in [`canonical/`](canonical/), retaining the original passage text and source provenance.

## Dataset Structure

```text
synthetic/
├── cases/
│   └── <case_id>/
│       ├── case.json
│       └── ground_truth.json
├── canonical/
│   ├── cases/
│   ├── manifest.json
│   ├── AUDIT.md
│   ├── CHANGES.md
│   ├── COMPATIBILITY.md
│   ├── changes.jsonl
│   ├── claim_catalog.json
│   └── identity_notes.json
├── case_matrix.json
├── plan.json
├── dataset_manifest.json
└── contracts/
    ├── README.md
    └── v1/
```

| Artifact | Contents |
|---|---|
| [`cases/`](cases/) | Original `case.json` and `ground_truth.json` fixtures for all 24 cases |
| [`canonical/cases/`](canonical/cases/) | Multi-claim case annotations |
| [`canonical/manifest.json`](canonical/manifest.json) | Canonical dataset artifact hashes |
| [`canonical/AUDIT.md`](canonical/AUDIT.md) | Claim inventory, identity rules, and annotation coverage |
| [`canonical/CHANGES.md`](canonical/CHANGES.md) | Original claims and atomic assertion changes |
| [`canonical/COMPATIBILITY.md`](canonical/COMPATIBILITY.md) | Loader, SDK observation, and selection compatibility |
| [`canonical/changes.jsonl`](canonical/changes.jsonl) | Per-occurrence annotation changes and supporting text |
| [`canonical/claim_catalog.json`](canonical/claim_catalog.json) | Canonical claim identities |
| [`canonical/identity_notes.json`](canonical/identity_notes.json) | Claim identity and normalization decisions |
| [`case_matrix.json`](case_matrix.json) | Case IDs, domains, dependency mechanisms, and source roles |
| [`plan.json`](plan.json) | Original experimental constraints |
| [`dataset_manifest.json`](dataset_manifest.json) | Original 56-entry SHA-256 artifact contract |

## Canonical Annotations

The canonical dataset retains the 189 original passages and expands their claim annotations.

| Property | Count |
|---|---:|
| Cases | 24 |
| Domains | 6 |
| Passages | 189 |
| Claim occurrences | 400 |
| Distinct claim identities | 259 |
| Claim identities shared across passages | 69 |
| Properties with conflicting values | 9 |

The 400 occurrences comprise 189 replacement claims and 211 additional atomic assertions.

Claim identity is defined by namespace, entity, attribute, and value. Equivalent assertions can share a claim identity while retaining separate source observations.

Each candidate contains a `claims` array. The first claim preserves the original observation ID; additional claims receive deterministic observation IDs. Original passage text, source IDs, and provenance remain associated with their candidates.

The benchmark loader maps these annotations into the existing `AssertionTriple(source_id, attribute_id, claim_id)` inference contract. Multiple assertions from one source remain associated with their original passage during context selection.

Each claim occurrence is linked to an exact supporting span in the original passage. Incorrect assertions and conflicting values remain in the dataset.

See [`canonical/AUDIT.md`](canonical/AUDIT.md) for annotation coverage and [`canonical/COMPATIBILITY.md`](canonical/COMPATIBILITY.md) for loader and observation compatibility.

## Evaluation Budgets

The original experiments and the current context-selection benchmark use different constraints.

| Evaluation | Budget |
|---|---|
| Historical source-selection experiments | 2–3 candidates per case |
| Cross-Domain Context Curation Benchmark | 64, 96, 128, 160, 192, 256 Qwen tokens |

The current benchmark enforces token ceilings using the Qwen tokenizer. Token counts include the reconstructed context payload.

Context reduction is measured separately using the word/punctuation footprint of the selected context, including rendered passage headers.

## Ground Truth and Scoring

The canonical annotations identify supporting passages, evidence spans, and source-origin relationships.

| Metric | Annotation basis |
|---|---|
| Selection precision | Selected source IDs against annotated supporting-source IDs |
| Selection recall | Retained supporting-source IDs |
| Evidence retention | Retained merged gold evidence-span footprint |
| Supporting-passage claim coverage | Canonical claim IDs associated with annotated supporting passages |
| Source-origin coverage | Root-origin units derived from annotated provenance |

Supporting-passage claim coverage includes incidental claims found in gold passages. Matching claims in non-gold passages may also contribute to coverage.

Explicit minimal required-answer claim labels are absent, so `gold_claim_coverage` is null.

Source-origin coverage is relative to the annotated provenance graph. Unresolved citation cycles and missing lineage do not establish real-world source independence.

Metric implementations are in [`tier1_metrics.py`](tier1_metrics.py).

## Validation

Validate the original case fixtures from the repository root:

```bash
python -m benchmarks.context_selection.synthetic.validate_dataset
```

The validator checks fixture structure, graph references, ground-truth annotations, scoring labels, and cross-file consistency.

Canonical annotation integrity and compatibility requirements are documented in:

- [`canonical/AUDIT.md`](canonical/AUDIT.md)
- [`canonical/COMPATIBILITY.md`](canonical/COMPATIBILITY.md)
- [`canonical/manifest.json`](canonical/manifest.json)

## Artifact Integrity

The original 24 `case.json` and 24 `ground_truth.json` fixtures remain unchanged. Their 56-entry SHA-256 contract is recorded in [`dataset_manifest.json`](dataset_manifest.json).

Superseded source snapshots are retained in [`contracts/v1/`](contracts/v1/). The canonical multi-claim annotations are maintained separately from the original fixtures.

### Known Source-Role Discrepancy

| Case | Record | Source slot 3 |
|---|---|---|
| `coding_package_fix_lineage` | `case_matrix.json` | Issue comment |
| `coding_package_fix_lineage` | Original `case.json` | Community note at `/community/pool-workaround` |

The original fixture is preserved without modifying its source-role annotation.

## Evaluation Scope

The 24 cases were used during subsequent selection-policy development, including budget-exhaustion recovery. The dataset is fixed for the recorded evaluations but is not an untouched test set for the recovery policy.

The benchmark evaluates context selection using supplied structured claims and provenance. Automated claim extraction, extraction cost, and downstream answer generation are outside the measured execution.

## References

- [Benchmark Methodology](../../README.md)
- [Leaderboard](../../leaderboard.md)
- [Execution Evidence](EVIDENCE.md)
- [Source and Checkpoint Contracts](contracts/README.md)