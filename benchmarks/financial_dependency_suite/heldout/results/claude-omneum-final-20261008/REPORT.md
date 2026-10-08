# Anthropic paired benchmark comparison

The completed original paired run has equal aggregate downstream correctness (22/24), with worse selection precision/recall. Local Omneum evaluation is fast and uses no model tokens. The current anthropic_omneum route includes a Claude shortlist call, so the complete judge pipeline does not demonstrate lower latency or model token usage. Cost savings are not established; no pricing is configured.

Primary artifact: `../claude-omneum-paired-20261008/` (24 cases, one trial each, frozen Claude baseline reused unchanged).

| Metric | Claude | Claude + Omneum |
| --- | ---: | ---: |
| Answer correctness | 22/24 (91.67%) | 22/24 (91.67%) |
| Incorrect / unscored / failures | 0 / 1 / 1 | 0 / 2 / 0 |
| Selection precision (24-case macro) | 96.53% | 86.81% |
| Selection recall (24-case macro) | 67.67% | 58.29% |
| Selection TP / FP / FN | 67 / 2 / 37 | 60 / 9 / 44 |
| Generation failures | 1 (refusal) | 0 |
| Estimated USD cost | Unavailable | Unavailable |
| Full judge pipeline p50 / p95 | 1.7707 / 1.9995 s | 2.1826 / 3.4791 s |
| Claude selector / shortlist p50 / p95 | 1.7707 / 1.9995 s | 1.6987 / 2.7642 s |
| Total latency p50 / p95 | 4.2327 / 4.9526 s | 4.9773 / 6.6096 s |
| Generation latency p50 / p95 | 2.4702 / 3.0571 s | 2.6663 / 3.7961 s |
| Local Omneum evaluator p50 / p95 | — | 28.84 / 54.84 ms |
| Full local Omneum integration p50 / p95 | — | 0.4600 / 0.5431 s |
| Judge API input / output tokens | 18,516 / 712 | 18,516 / 1,101 |
| Generation input / output tokens | 5,708 / 5,329 | 5,690 / 6,337 |
| Local Omneum model tokens | — | 0 |
| Total model tokens | 30,265 | 31,644 |

Local evaluator p50 is about 61.4 times faster than the Claude selector. This component comparison excludes Claude shortlisting and local integration overhead; it does not establish a speedup for the complete paired route.

## Additional rerun disclosure

The user explicitly requested reuse of the already-completed run. The additional rerun was initiated under the earlier instruction to rerun all 24 cases and completed before it could be interrupted after clarification. Both are disclosed; no trials are pooled or selected by outcome.

The additional rerun has 21/24 correct (87.50%), 3 unscored, 0 generation failures; selection precision/recall 86.81%/58.29%. Full judge p50/p95: 2.0294/4.2543 s; total p50/p95: 4.3959/8.5691 s. Local evaluator p50/p95: 29.05/44.12 ms. Judge input/output tokens: 18,516/1,080; generation input/output: 5,690/6,451; total: 31,737. Its saved results and summary remain intact.

## Diagnosis and validation

The evaluator receives claims and provenance, not source text. Structural support favors the independent 240 claims over the 216 claim with a dependent census summary. The maximum-support selector then excludes census sources. No implementation correction is warranted for this behavior. The actual replay input/output is saved in `../claude-omneum-final-20261008-diagnostic/false_consensus_trace.json`.

No algorithm, selection, estimator, expectation, fixture, baseline, prompt or scorer changes. All 64 protected file hashes matched. All 24 baseline records in each run match the originals. Relevant tests: 124 passed, two local model-loading tests deselected. Dataset validation and git diff --check passed.

## Measurement limits

- One original paired trial and one disclosed additional trial; equivalence and determinism are not statistically established.
- Historical Claude timing and new pipeline timing were measured at different times.
- Saved summary selection-score coverage is Claude 23/24 and Omneum 24/24. This comparison adds explicitly identified 24-case macro metrics computed with the existing score_selection from stored selections; historical rows and scores remain unchanged.
- The 240 response stays unscored under the frozen scorer; no outcomes are relabeled.
- Estimated USD cost is unavailable because the infrastructure has no pricing table or recorded local compute cost. Local Omneum performs no model API inference; the paired route still pays for Claude shortlisting and generation.

Stopping after Anthropic. No next-judge preparation or calls. Full machine-readable metrics for both runs are in `comparison.json`.
