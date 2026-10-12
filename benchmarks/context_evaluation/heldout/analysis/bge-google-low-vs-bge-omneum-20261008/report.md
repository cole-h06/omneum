# BGE + Gemini 3.8 Flash vs. BGE + Omneum

This comparison uses the October 9 low-thinking Gemini replay, completed by recovering only its 139 failed Claude Sonnet 5.5 generations on October 11. All 240 Gemini selections, 101 successful Gemini-arm generations, and 240 historical Omneum records are preserved. No selection evaluator was rerun.

| Configuration | Precision | Recall | Complete-answer accuracy | Selection p50 | E2E p50 | Generator tokens | Generator cost |
|---|---:|---:|---:|---:|---:|---:|---:|
| BGE + Gemini 3.8 Flash | 94.44% | 66.28% | 95.83% (230/240) | 2.487s | 4.924s | 114,250 | $0.686916 |
| BGE + Omneum | 86.11% | 59.34% | 91.67% (220/240) | 0.639s | 3.130s | 115,535 | $0.702470 |

The 139 recovery calls returned 129 answers and ten explicit Anthropic refusals. There are no unresolved provider failures. Recovery usage is 32,458 input + 31,861 output = 64,319 tokens, costing $0.383526 at the frozen $2/M input and $10/M output accounting rates. These costs are exact calculations from recorded usage at the benchmark rates, not independently verified invoices. Full Gemini-arm generator usage is 56,948 input and 57,302 output tokens. Judge inference and local compute are excluded.

Every final Gemini answer was inspected against the frozen reference and selected evidence. The ten coding pool-fix answers are semantically complete despite inflected wording failing substring scoring. The ten stale-runbook responses have stop_reason=refusal and empty content. The matching historical Omneum audit retains ten substantive census errors and ten refusals. Complete-answer accuracy includes all 240 attempts; frozen substring scores remain separate in summary.json.

Selection precision and recall are macro averages; medians use linear interpolation at (n-1)q. The unrounded selection p50 remains 2.48713827051688s. The Gemini/Omneum median-selection ratio is 3.892391507202761 (3.89×). E2E is a component sum: the original saved selection duration plus the recorded generation duration, including later recovery measurements. It is not contemporaneous wall-clock latency. Omneum is the unchanged historical comparator, not a concurrent rerun.

Original Gemini judge reasoning telemetry has only 10/240 coverage, so full judge-token and whole-pipeline cost totals remain unavailable. Generator telemetry covers all 240 records. Twenty-four fixed synthetic cases with ten repeats per case are not 240 independent tasks; selectors receive different information and the runs were not interleaved.

The canonical manifest pins original source hashes, configuration, source-record preservation digests, recovery implementation and journal hashes, final result/summary/review hashes, and accounting rates. Historical failed snapshots, original comparison and recovery journal are retained in the private archive. See [reproducibility.md](reproducibility.md) for offline verification.
