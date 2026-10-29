# Context Selection Latency Analysis

Local context-selection latency for the 24-case Cross-Domain Context Curation Benchmark.

The benchmark evaluates 13 budgeted configurations across six Qwen-token budgets: 64, 96, 128, 160, 192, and 256. Latency measurements are reported separately from selection precision, evidence retention, and reconstructed-context token usage.

The final measurements correspond to the budget-exhaustion recovery implementation used in the published [Leaderboard](../../leaderboard.md).

## Results

Selection latency is reported in milliseconds.

| Configuration | p50 (ms) | p95 (ms) |
|---|---:|---:|
| Omneum Standalone | 194.86 | 451.87 |
| BM25 + Omneum | 207.79 | 461.25 |
| MiniLM + Omneum | 203.84 | 465.36 |
| BGE + Omneum | 200.63 | 430.51 |
| Cohere + Omneum | 206.89 | 480.37 |

The final Omneum configurations have median local selection latency between 194.86 ms and 207.79 ms. Recorded p95 values range from 430.51 ms to 480.37 ms.

These measurements include Omneum's local selection route after structured observations and relevance inputs are available. They do not include upstream retrieval, external reranker inference, structured observation extraction, or downstream answer generation.

## Measurement Boundary

The measured Omneum route includes:

1. Fresh provenance-aware graph inference through the production SDK.
2. Candidate discovery and graph-neighborhood expansion.
3. Claim-support-based chunk utility calculation and token-budgeted selection.
4. Deferred-candidate recovery when the initial candidate neighborhood is exhausted.
5. Reconstruction of selected original passages.
6. SDK verification and response mapping.

Omneum's algorithm incorporates dependencies between sources into source reliability during graph inference. The resulting claim support contributes to chunk selection alongside question relevance and incremental claim coverage.

The benchmark invokes production `prepare_context()` in `omneum/client.py`. Candidate discovery and selection are implemented in `omneum/context_selection.py`, with question-context handling in `omneum/query_context.py`.

The evaluated configurations use `coverage_support_density`, `complementary_evidence=True`, `token_cost_exponent=1`, three relevance anchors plus ties, expansion depth two, and `conflict_aware=False`.

BM25, MiniLM, BGE, and Cohere relevance scores are supplied before the Omneum selection timer starts. The recorded hybrid latency is therefore not a measurement of the complete retrieval-and-reranking pipeline.

## Earlier Competitive Timing Pass

The saved competitive analysis also reports local selection measurements from an earlier execution.

| Configuration | Earlier p50 (ms) | Earlier p95 (ms) |
|---|---:|---:|
| Omneum Standalone | 127.95 | 198.87 |
| BM25 + Omneum | 131.61 | 200.61 |
| MiniLM + Omneum | 131.48 | 194.25 |
| BGE + Omneum | 132.42 | 202.58 |
| Cohere + Omneum | 133.64 | 205.08 |

These values are retained as recorded execution results, not substituted for the final leaderboard timings.

The earlier analysis and final benchmark measurements represent different saved executions. They must not be pooled or interpreted as a controlled before-and-after latency comparison.

The earlier measurements are preserved in:

[`analysis/tier1-competitive-analysis-20261026-v1/report.md`](analysis/tier1-competitive-analysis-20261026-v1/report.md)

## External Model Latency

The competitive analysis preserves historical provider response timings for the ranking methods.

| Provider | Recorded Requests | API p50 (s) | API p95 (s) |
|---|---:|---:|---:|
| Cohere Rerank v4.0 Pro | 24 | 0.176650 | 0.196046 |
| Claude Sonnet 5.5 | 48 | 1.844163 | 3.099168 |
| GPT-6 Astra | 48 | 2.034325 | 2.989370 |
| Gemini 3.8 Flash | 48 | 2.033247 | 2.882411 |

These timings come from the saved provider ranking requests. They are not new remote measurements performed during the final local replay.

Cohere's 24 saved ranking responses are reused across the six context budgets. The 48 requests per frontier judge correspond to two ranking trials per case.

Provider response times and local Omneum selection times have different execution boundaries. Adding their aggregate percentiles would not produce a measured end-to-end latency distribution.

## Timing Methodology

The benchmark uses fixed candidate pools and matched maximum token budgets across configurations.

The local timing boundary starts after relevance scores and structured observations are available. The measured route includes graph requests, discovery, budgeted packing, reconstruction, and client verification.

Model initialization, dataset loading, daemon startup, upstream structured extraction, and relevance inference are excluded. Token counts are prewarmed.

Saved timing records include overlapping graph, MCP, and verification spans. These spans represent portions of the same selection execution and must not be added together.

The original benchmark configurations and subsequently added configurations were timed in separate saved executions. Small differences between local baseline timings are not attributable to model quality or inference performance.

The benchmark does not measure complete retrieval-to-answer latency.

## Measurement Limitations

**Selection versus inference.** The reported Omneum timings measure the production SDK selection route, not isolated graph-inference execution. Graph requests, transport, selection, reconstruction, and verification contribute to the recorded interval.

**External ranking.** Hybrid configurations receive precomputed relevance scores. Their reported selection latency excludes the cost of obtaining those scores from BM25, MiniLM, BGE, or Cohere.

**Prewarmed execution.** Tokenization is prewarmed, and initialization and daemon startup are outside the measured interval. The results do not establish cold-start latency.

**Overlapping stages.** Graph, MCP, and verification timings can overlap. Stage-level measurements cannot be summed to reconstruct total execution time.

**Provider comparisons.** Historical API timings measure remote ranking requests. Local selection timings measure a different execution stage. The results support a comparison of recorded stage costs, not a controlled end-to-end latency comparison.

**Workload scope.** The benchmark contains 24 designed synthetic cases across six domains. Its latency distribution does not establish production performance under concurrent requests, larger candidate pools, different graph sizes, or external retrieval workloads.

**Downstream generation.** No answer-generation latency or downstream answer accuracy is measured in the current benchmark.

## Artifacts

- [Leaderboard](../../leaderboard.md) — Published final selection metrics and latency.
- [Benchmark Methodology](../../README.md) — Dataset, execution configuration, and measurement definitions.
- [Budget-Exhaustion Recovery](results/budget-exhaustion-recovery-20261026-v2/report.md) — Final implementation comparison and timing contract.
- [Competitive Analysis](analysis/tier1-competitive-analysis-20261026-v1/report.md) — Earlier local timing pass and historical provider response measurements.

All values are taken from recorded benchmark artifacts. No additional provider calls or timing measurements were performed for this document.