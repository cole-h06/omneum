# Canonical structured-claim audit

Audited all 24 held-out cases and all 189 original passages. The single corrected
canonical dataset contains **400 claim occurrences and 259 distinct identities**:
189 replacement annotations and 211 additional atomic assertions. This is a data
curation result, not a benchmark result.

## Corrections and evidence

[CHANGES.md](CHANGES.md) records every original passage, original structured
claim, and corrected claims. [changes.jsonl](changes.jsonl) records all 400
occurrences with original/corrected values, source IDs, observation IDs and exact
supporting text. Additional claims have `original: null` and retain the original
candidate claim separately. [claim_catalog.json](claim_catalog.json) groups equal
identities; [identity_notes.json](identity_notes.json) documents contextual scope
resolutions and unit conversion.

Identity uses namespace, entity, attribute and value. Repeated equivalent facts
share an identity while retaining distinct source observations. There are 69
identities shared across source passages and nine properties with conflicting
values. Incorrect assertions remain assertions; conflicting values are not
converted to the expected answer. Quantities, environment, version, temporal
scope, conditions and action modality are retained where supported. Partial dates
retain their precision. A source range is not replaced with an inferred aggregate
count. Each occurrence cites its exact original full-passage span; spans establish
source attribution rather than an automated entailment guarantee.

For `analytics_incomplete_lineage/source_table`, the claims separately record
520 total parcel IDs, 487 delivered and 33 returned. The transformation separately
retains the false delivered-count assertion of 520, the actual COUNT(*) row-count
calculation of 520, and its missing input-table identifier. The false assertion
still shares identity with passages reporting that same delivered count; it does
not share identity with either total parcels or the true delivered count of 487.

The audit also separates production/CI scope, current/historical revisions,
endpoint availability/invocation instructions, SQL effects before COMMIT,
recommendations/observed outcomes, and different metrics concerning one entity.
No source-authority or answer-correctness filtering was used to erase evidence.

## Per-case coverage

| Case | Original passages/claims | Corrected atomic occurrences |
|---|---:|---:|
| `analytics_derived_metric_cycle` | 8 | 16 |
| `analytics_incomplete_lineage` | 9 | 22 |
| `analytics_metric_definition_conflict` | 8 | 30 |
| `analytics_stale_dashboard` | 8 | 18 |
| `coding_api_version_change` | 8 | 19 |
| `coding_clean_dependency` | 7 | 8 |
| `coding_config_conflict` | 6 | 17 |
| `coding_package_fix_lineage` | 8 | 19 |
| `enterprise_partial_lineage` | 8 | 16 |
| `enterprise_policy_copy_chain` | 9 | 14 |
| `enterprise_semantic_distractors` | 10 | 11 |
| `enterprise_stale_handbook` | 8 | 15 |
| `multi_agent_feedback_loop` | 8 | 18 |
| `multi_agent_independent_error` | 6 | 12 |
| `multi_agent_relevant_wrong_task` | 9 | 13 |
| `multi_agent_repeated_subagent` | 8 | 16 |
| `research_clean_consensus` | 7 | 11 |
| `research_conflicting_reports` | 8 | 20 |
| `research_independent_false_consensus` | 7 | 19 |
| `research_syndicated_reporting` | 9 | 17 |
| `support_clean_resolution` | 7 | 17 |
| `support_resolution_conflict` | 7 | 15 |
| `support_stale_runbook` | 8 | 14 |
| `support_ticket_reference_loop` | 8 | 23 |

## Representation and adapter changes

- `schema.py`: `ClaimSpec`, optional `CandidateSpec.claims`, and `candidate_claims` preserve legacy singleton inputs.
- `loader.py::load_case`: accepts either legacy claim fields or a nonempty `claims` array, validates identities/evidence/observation IDs, rejects mixed shapes. `build_observations` delegates to the shared SDK adapter.
- `sdk_adapter.py::build_observations`: flattens atomic claims to existing SDK observations, inheriting original provenance and source identity.
- `prepare_benchmark.py::mapped_chunks`: maps every observation back to its original chunk by explicit observation ID.
- `query_benchmark.py::inputs`: retains all per-chunk claims and uses each claim's own existing fields for claim-text construction.

These files are relative to `benchmarks/context_evaluation/heldout/`. No files in
`omneum/` were changed. The native inference input already accepts multiple
`AssertionTriple` records per source; graph equations, dependency estimation,
selection mathematics and SDK public contracts require no changes. Chunk pools
and raw text remain unchanged. Added observation IDs are deterministic; the first
claim keeps the original assertion ID, preserving existing provenance references.
Canonical catalog IDs are metadata; native SDK claim IDs still use the existing
adapter. See [COMPATIBILITY.md](COMPATIBILITY.md) before any broader use: historical
singleton diagnostics and legacy annotations embedded in retrieval caches must
not be mistaken for multi-claim evaluation support.

## Validation and limits

**154 tests passed in 2.66s**, recorded in [tests.log](tests.log). Tests cover all
24 cases for unchanged nonclaim fields and labels, multi-claim observation/chunk
associations, provenance and parent references, valid native graph inputs,
deterministic reconstruction, legacy frozen chunk-token compatibility, malformed
schema rejection, and targeted semantic distinctions. Graph construction validates
the existing source/property consistency contract; converged inference and
selection were not run on the corrected dataset.

[validation.json](validation.json) verifies 293 protected original files, including
all 55 frozen result files and 48 original case/label files. All 24 copied retrieval
files are byte-identical. Original budgets, questions, expected answers, relevance
scores, source identities and passage order are preserved. Reproduce integrity
checks with:

```sh
.venv/bin/python benchmarks/context_evaluation/heldout/canonical/validate.py
.venv/bin/python -m pytest -q benchmarks/context_evaluation/heldout/canonical/test_canonical.py
```

Semantic corrections are manually audited synthetic annotations, not a general
extractor or proof of exhaustive semantic equivalence. Full-passage evidence spans
are intentionally conservative. Scope resolutions that use explicit cross-source
lineage are listed rather than hidden. No models, paid calls, downstream answer
generations or benchmark selections were run. No precision, recall or accuracy
improvement is claimed. Work stops at dataset correction and focused adapter
validation.
