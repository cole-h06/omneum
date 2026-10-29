
# Paired Latency Analysis

Read-only analysis of the Cohere and Cohere + Omneum experiment.

From the repository root:

```sh
.venv/bin/python -S benchmarks/context_evaluation/heldout/latency_analysis.py
.venv/bin/python -S benchmarks/context_evaluation/heldout/latency_analysis.py --json
.venv/bin/python -m pytest benchmarks/context_evaluation/heldout/test_latency_analysis.py -q
```

Default input: `results/20261008T014713Z/results.jsonl`. An optional positional argument selects another results file; `--expected-cases` defaults to 24.

The script uses only Python's standard library and writes to stdout. It does not modify benchmark artifacts.

## Results

All metrics cover the same 24 cases. Values are seconds (P50 / P95), calculated from per-case totals using linear interpolation at `(n - 1) * q`.

| Timing | Cohere | Cohere + Omneum | Evidence |
|---|---:|---:|---|
| Reranking | 0.1512 / 2.9014 | 0.1512 / 2.9014 | Measured shared responses |
| Omneum evaluation | N/A | 0.0297 / 0.0368 | Measured SDK call |
| Omneum cold integration | N/A | 0.4453 / 0.5353 | Measured integration |
| Cold non-evaluation overhead | N/A | 0.4169 / 0.4998 | Estimated difference |
| Generation | 2.3825 / 3.5416 | 2.2300 / 3.4797 | Measured calls |
| Corrected selection | 0.1512 / 2.9014 | 0.6241 / 3.4118 | Reconstructed sum |
| Recorded end-to-end | 2.6343 / 5.8150 | 2.8065 / 3.9227 | Recorded component sum |
| Corrected end-to-end | 2.6343 / 5.8150 | 3.1765 / 6.0220 | Reconstructed sum |

## Method

All 24 Cohere cases performed uncached reranking. The corresponding Cohere + Omneum cases reused those responses.

The correction adds the shared Cohere response duration once to each cached combined case. It does not duplicate reranking in the baseline. Omneum evaluation is already included in integration time and is not added separately.

The 48 rows represent 24 shared reranking responses, not 48 independent provider measurements.

The analysis verifies matching case/trial identities, request hashes, ranked candidates, relevance settings, and shared response durations. Missing or inconsistent timings are reported as unavailable, with coverage recorded for each metric.

JSON output includes per-case inputs and reconstructed totals.

## Measurement Limitations

**Provider retries.** Cohere SDK 7.1.1 can retry HTTP 429 responses within `client.rerank`. Recorded reranking durations may include retry backoff. Retry counts, HTTP statuses, and individual attempt timings were not captured. The observed tail cannot be separated into retry and inference time.

**Cold integration.** Omneum integration opens and closes a deployment and stdio client for each evaluation. The SDK evaluation timer includes preprocessing, transport, validation, local verification, and mapping. It is not isolated server inference time. Cold non-evaluation overhead is estimated by subtracting SDK evaluation from integration duration; no independent startup or warm-client measurements exist.

**End-to-end timing.** Recorded end-to-end latency is the sum of selection and generation components, not an independent wall-clock measurement. All 48 recorded totals reconcile with their components. The correction restores omitted reranking time for cached combined cases but does not include work outside those timers.

**Comparability.** Generation uses separate method-specific answers. End-to-end differences therefore do not isolate Omneum's incremental overhead.

No new provider calls or measurements were made.