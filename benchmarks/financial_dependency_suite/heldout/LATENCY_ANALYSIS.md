# Read-only paired latency analysis

Run from the repository root, using only Python's standard library:

```sh
.venv/bin/python -S benchmarks/financial_dependency_suite/heldout/latency_analysis.py
.venv/bin/python -S benchmarks/financial_dependency_suite/heldout/latency_analysis.py --json
.venv/bin/python -m pytest benchmarks/financial_dependency_suite/heldout/test_latency_analysis.py -q
```

The default input is `results/20261008T014713Z/results.jsonl`. An optional positional
path selects another input; `--expected-cases` defaults to 24. Output goes only to
stdout. The script reads results and the adjacent shared response file, without
importing benchmark runners, provider SDKs, or the inference algorithm. It does
not modify fixtures, results, summaries, or manifests.

The comparison requires identical case/trial sets, one trial per distinct case,
shared request hashes, relevance model/depth/ranked candidates, and matching
response durations. It also checks durations against `cohere_responses.jsonl`
when present. Identity or shared-response conflicts stop the analysis. Missing,
nonfinite, negative, or inconsistent component timings produce explicit warnings
and unavailable estimates, with coverage reported for every metric.

## This run

All rows below cover the same 24 cases. Values are seconds, P50 / P95, using
linear interpolation at `(n - 1) * q`. Percentiles are calculated from per-case
totals, not added from component percentiles.

| Timing | Cohere | Cohere + Omneum | Evidence |
| --- | ---: | ---: | --- |
| Reranking | 0.1512 / 2.9014 | 0.1512 / 2.9014 | Measured shared responses |
| Omneum evaluation | N/A | 0.0297 / 0.0368 | Measured SDK call |
| Omneum cold integration | N/A | 0.4453 / 0.5353 | Measured integration |
| Cold non-evaluation overhead | N/A | 0.4169 / 0.4998 | Estimated difference |
| Generation | 2.3825 / 3.5416 | 2.2300 / 3.4797 | Measured calls |
| Corrected selection | 0.1512 / 2.9014 | 0.6241 / 3.4118 | Reconstructed sum |
| Recorded end-to-end | 2.6343 / 5.8150 | 2.8065 / 3.9227 | Recorded component sum |
| Corrected end-to-end | 2.6343 / 5.8150 | 3.1765 / 6.0220 | Reconstructed sum |

All 24 Cohere rows made uncached reranks; all 24 Cohere + Omneum rows reused
those responses. The correction replaces the run-local Cohere work with
`cohere_response_latency_seconds` exactly once. It does not add a full rerank to
an already uncached selection. Evaluation is nested inside Omneum integration
and is never added again. The shared timings represent 24 provider responses,
not 48 independent measurements. The JSON output includes the per-case inputs
and reconstructed totals for auditing.

## Timing limits

`semantic_reranker.rerank_cohere` times `client.rerank`, after client creation.
The recorded Cohere SDK version is 7.1.1; its local HTTP implementation retries
429 responses inside that call. Backoff and retries therefore can inflate the
reranking tail, and that same duration enters both corrected comparisons.
These artifacts do not record successful-call HTTP statuses, retry counts,
backoff durations, or individual attempt timings. Long calls cannot establish
which cases encountered 429s. Retain the observed tail; a retry-free provider
latency cannot be recovered fairly.

`application_comparison.select_omneum` measures the full cold integration.
`omneum_rag.evaluate_context` opens and closes a deployment and stdio client for
each evaluation. `Client.evaluate_context` measures its own evaluation call,
including preprocessing, transport, validation, local verification and mapping.
That SDK timing is not isolated server inference. Cold integration minus SDK
evaluation is an estimate containing deployment/connection/teardown and other
integration work. There is no independent startup timer and no persistent-client
warm-start measurement; neither can be inferred from these fields.

The runner's `end_to_end_latency_seconds` is selection plus generation, rather
than a separate wall-clock timer. All 48 recorded sums reconcile with their
components, but the cached combined rows omit the rerank cost for a standalone
request. The reconstructed total repairs that omission; it still excludes work
outside those timers. Generation uses separate method-specific answers, so
end-to-end differences do not isolate the incremental cost of Omneum. No paid
calls or new performance measurements are needed for this analysis.
