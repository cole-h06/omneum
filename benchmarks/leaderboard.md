# Omneum Cross-Domain Context Curation Benchmark — Leaderboard

Results from 24 synthetic cases across six domains: coding agents, enterprise RAG, research and analysis, multi-agent systems, data analytics, and support and operations.

The benchmark compares Omneum against BM25, MiniLM, BGE Reranker v2-m3, Cohere Rerank v4.0 Pro, Claude Sonnet 5.5, GPT-6 Astra, and Gemini 3.8 Flash.

Each configuration selects passages from the same fixed candidate pool under context budgets of 64, 96, 128, 160, 192, and 256 Qwen tokens.

Omneum's production `prepare_context()` uses provenance-aware graph inference to compute source reliability and claim support, accounting for shared evidence origins and dependencies between sources. Claim support is mapped to retrieved chunks and used with question relevance and marginal claim coverage to select original passages within the token budget.

The benchmark measures selection precision, recall, evidence retention, claim coverage, root-origin coverage, reconstructed-context token usage, and local selection latency. Downstream answer accuracy is not measured.

See [Benchmark Methodology](README.md) for the dataset, implementation, metric definitions, and reproduction instructions.

## Semantic Rerankers

Compares standalone retrieval and semantic ranking with the corresponding Omneum context-selection configurations.

The evaluated rankers are BM25 (`bm25`), `all-MiniLM-L6-v2` (`embedding`), `BAAI/bge-reranker-v2-m3` (`bge`), and Cohere `rerank-v4.0-pro` (`cohere`). Their Omneum integrations are `bm25_omneum`, `embedding_omneum`, `bge_omneum`, and `cohere_omneum`. Standalone `omneum` executes production `prepare_context(question=...)` with default lexical relevance.

| Configuration | Precision ↑ | Recall ↑ | Evidence ↑ | Claims ↑ | Origins ↑ | Qwen Tokens ↓ |
|---|---:|---:|---:|---:|---:|---:|
| Original-Order RAG | 43.33% | 42.75% | 43.08% | 58.51% | 60.32% | 136.87 |
| BM25 | 59.15% | **55.76%** | **55.79%** | 66.15% | **71.05%** | 136.18 |
| BM25 + Omneum | **63.12%** | 46.86% | 46.90% | **66.22%** | 69.16% | **111.60** |
| MiniLM Embeddings | 63.80% | **59.13%** | **58.86%** | 68.47% | **70.94%** | 136.31 |
| MiniLM + Omneum | **66.83%** | 49.08% | 50.14% | **69.74%** | 68.50% | **111.08** |
| BGE Reranker v2-m3 | 63.29% | **59.19%** | **58.84%** | 68.75% | 71.42% | 136.47 |
| BGE + Omneum | **71.74%** | 54.76% | 55.26% | **75.36%** | **75.21%** | **116.74** |
| Cohere Rerank v4.0 Pro | 71.11% | **64.43%** | **64.39%** | 72.29% | **75.20%** | 136.72 |
| Cohere + Omneum | **74.88%** | 54.91% | 56.20% | **72.99%** | 72.86% | **112.68** |
| Omneum Standalone | 61.55% | 52.65% | 53.42% | 75.85% | 75.52% | 129.27 |

All four Omneum hybrids improved aggregate selection precision. BGE + Omneum gained **8.44 percentage points** in precision and **6.60 points** in claim coverage over standalone BGE. Cohere + Omneum gained **3.77 points** in precision.

The hybrids selected smaller contexts with lower aggregate source recall and evidence retention. BGE + Omneum retained **55.26%** of annotated evidence against **58.84%** for BGE. Cohere + Omneum retained **56.20%** against **64.39%** for Cohere.

| Configuration | Mean Qwen Tokens | Reduction vs. Ranker |
|---|---:|---:|
| BM25 + Omneum | 111.60 | **18.05%** |
| MiniLM + Omneum | 111.08 | **18.51%** |
| BGE + Omneum | 116.74 | **14.46%** |
| Cohere + Omneum | 112.68 | **17.58%** |

Reductions use mean `tokenizer_tokens` from matched case-budget cells. `tokenizer_tokens` counts reconstructed context with the Qwen tokenizer; `actual_context_tokens` records the benchmark's word/punctuation footprint. Each method has the same maximum budget within a matched comparison.

### Omneum Selection Implementation

The production entry point is `prepare_context()` in `omneum/client.py`. Candidate discovery and token-budgeted selection are implemented in `omneum/context_selection.py`; `omneum/query_context.py` handles question-context inputs.

The evaluated hybrids use `coverage_support_density`, `complementary_evidence=True`, and `token_cost_exponent=1`. Discovery starts from three relevance anchors plus ties and expands to depth two. BM25, MiniLM, and Cohere provide similarity scores; BGE uses `reranker_score`. The saved configuration sets `conflict_aware=False`.

Omneum's provenance-aware graph inference iteratively computes source reliability and claim support across a bipartite graph, accounting for shared evidence origins and dependencies between sources.

The SDK maps finalized claim support to the original retrieved chunks through their associated claim IDs. Passage selection uses question relevance and incremental claim coverage, without assigning duplicate marginal credit to repeated claims. Selected passages are reconstructed from their original text under the Qwen-token budget.

The graph evaluation operates on structured observations without reading the original source text. Original passages remain available to the SDK for reconstruction.

The hybrid routes receive their ranking scores before `prepare_context()` selection timing begins. Run manifests preserve the executed configuration and implementation fingerprints.

## Budget-Exhaustion Recovery

The production selector extends candidate discovery when the initial relevance neighborhood exhausts positive, budget-feasible utility.

`discover_chunks()` initializes the neighborhood using three relevance anchors, score ties, and bounded graph expansion. The recovery path in `omneum/client.py` and `omneum/context_selection.py` evaluates deferred passages after this neighborhood is exhausted. Admission requires positive inferred marginal utility, exact token-budget feasibility, and utility density meeting the weakest initially accepted density.

The implementation preserves selected passages and explicit `top_k` constraints. Dependency suppression, relevance normalization, and graph inference retain their configured behavior.

The recorded implementation comparison measures the effect of deferred-candidate recovery on the four Omneum hybrids:

| Configuration | Initial Precision | Final Precision | Initial Evidence | Final Evidence |
|---|---:|---:|---:|---:|
| BM25 + Omneum | 65.45% | 63.12% | 45.79% | **46.90%** |
| MiniLM + Omneum | 67.30% | 66.83% | 45.14% | **50.14%** |
| BGE + Omneum | 73.83% | 71.74% | 52.02% | **55.26%** |
| Cohere + Omneum | 79.71% | 74.88% | 55.42% | **56.20%** |

Evidence retention increased for every hybrid. MiniLM + Omneum gained **5.01 percentage points** and BGE + Omneum gained **3.24 points**. Across all 720 corrected selection cells, the initially selected passages were preserved. Source recall, evidence retention, claim coverage, and origin coverage were nondecreasing within each cell.

Additional supporting passages increased context usage and reduced aggregate precision. The 64-token selections were unchanged. At 256 tokens, BGE + Omneum retained **16.78 percentage points less evidence** than standalone BGE.

The leaderboard uses the final recovered selections. The implementation patch, initial selections, reconstructed passages, and paired comparisons are preserved in [`budget-exhaustion-recovery-20261026-v2/`](context_selection/synthetic/results/budget-exhaustion-recovery-20261026-v2/).

## Frontier LLM Judges

Compares Omneum's context selection against frontier LLMs used to rank candidate passages.

Each judge ranks the supplied passages before budgeted packing. Omneum uses production `prepare_context()` with local source–claim inference and its configured relevance inputs.

The evaluated judges are `claude-sonnet-5-5`, `gpt-6-astra`, and `gemini-3.8-flash`. Two saved ranking trials per case are averaged within each case-budget cell.

| Configuration | Precision ↑ | Recall ↑ | Evidence ↑ | Claims ↑ | Origins ↑ | Qwen Tokens ↓ |
|---|---:|---:|---:|---:|---:|---:|
| Claude Sonnet 5.5 | **85.69%** | **75.85%** | **76.49%** | 81.05% | 82.89% | 136.41 |
| GPT-6 Astra | 85.14% | 75.33% | 76.18% | **81.48%** | **83.50%** | 136.49 |
| Gemini 3.8 Flash | 83.81% | 74.81% | 75.33% | 80.12% | 81.27% | 136.52 |
| Omneum Standalone | 61.55% | 52.65% | 53.42% | 75.85% | 75.52% | 129.27 |
| BGE + Omneum | 71.74% | 54.76% | 55.26% | 75.36% | 75.21% | 116.74 |
| Cohere + Omneum | 74.88% | 54.91% | 56.20% | 72.99% | 72.86% | **112.68** |

The frontier judges achieved higher aggregate selection precision and evidence retention. Claude Sonnet 5.5 retained **76.49%** of annotated evidence, GPT-6 Astra **76.18%**, and Gemini 3.8 Flash **75.33%**. Cohere + Omneum, the highest-retention Omneum hybrid, retained **56.20%**.

Omneum executes its selection locally without a frontier-model judge request. The recorded local selector timings and hosted judge response times have different execution boundaries.

The saved provider usage estimates are **$0.113996** for Claude, **$0.281080** for GPT-6 Astra, and **$0.025231** for Gemini, totaling **$0.420307**. Estimates use recorded token counts and saved pricing assumptions. Cohere API charges are unavailable, and local computation costs are excluded from these estimates.

## Selection Latency

Local selection timing begins after relevance scores and structured observations are available.

| Configuration | Local Selection p50 ↓ | Local Selection p95 ↓ |
|---|---:|---:|
| Omneum Standalone | 194.86ms | 451.87ms |
| BM25 + Omneum | 207.79ms | 461.25ms |
| MiniLM + Omneum | 203.84ms | 465.36ms |
| BGE + Omneum | 200.63ms | 430.51ms |
| Cohere + Omneum | 206.89ms | 480.37ms |

The measured route includes fresh graph evaluation, candidate discovery, token-budgeted selection, passage reconstruction, and SDK verification.

External ranking inference and structured observation extraction occur before this interval. Model initialization and cold tokenization are outside the measured interval. The benchmark uses prewarmed token counts.

The saved timing records also contain overlapping graph, MCP, and verification spans. These spans share execution time within the selection route.

See the [recovery report](context_selection/synthetic/results/budget-exhaustion-recovery-20261026-v2/report.md) for the recorded timing contract and distributions.

## Experimental Setup

The benchmark uses frozen cases and candidate pools. Every configuration receives the same maximum Qwen-token budget within its matched comparison.

| Parameter | Configuration |
|---|---|
| Dataset | 24 synthetic cases; four per domain |
| Domains | 6 |
| Original passages | 189 |
| Canonical claim occurrences | 400 |
| Distinct claim identities | 259 |
| Context budgets | 64, 96, 128, 160, 192, 256 Qwen tokens |
| Tokenizer | Qwen2.5 7B GGUF |
| Budgeted methods | 13 |
| Unbudgeted reference | `raw_full` |
| Baseline packing | `raw_budget` |
| Retrieval and rerankers | `bm25`, `embedding`, `bge`, `cohere` |
| LLM judges | `claude`, `gpt`, `gemini` |
| Omneum | `omneum`, `bm25_omneum`, `embedding_omneum`, `bge_omneum`, `cohere_omneum` |
| Evaluated output | Reconstructed context |

The Omneum hybrids use `coverage_support_density` with `complementary_evidence=True`, `token_cost_exponent=1`, three discovery anchors plus ties, expansion depth two, and `conflict_aware=False`. Deferred-candidate recovery is part of the final selection implementation.

The benchmark runner is `benchmarks/context_selection/synthetic/tier1_benchmark.py`. Competitor integration is implemented in `tier1_competitors.py`, and metric calculations are in `tier1_metrics.py`. Production context selection executes through `omneum/client.py` and `omneum/context_selection.py`.

Structured source–claim observations are supplied to the selection pipeline. Run manifests preserve the executed source hashes, provider settings, model identifiers, and tokenizer configuration.

### Metrics

| Metric | Measurement |
|---|---|
| Selection Precision | Selected source IDs intersected with annotated supporting-source IDs, divided by selected source count |
| Selection Recall | Annotated supporting-source IDs retained, divided by annotated supporting-source count |
| Evidence Retention | Retained merged gold evidence-span word/punctuation footprint divided by total gold evidence footprint |
| Claim Coverage | Selected canonical claim IDs represented in the union of claims from gold passages |
| Origin Coverage | Annotated root-origin units represented by retained gold passages |
| `tokenizer_tokens` | Qwen tokenizer count used to enforce the context budget |
| `actual_context_tokens` | Regex word/punctuation footprint of reconstructed context, including headers |
| Context Reduction | Per-cell reduction in `actual_context_tokens` against the unfiltered context |
| Selection p50 / p95 | Median and 95th-percentile local selection latency |

Quality metrics are macro-averaged across 24 cases and six token budgets. Frontier-ranking trials are averaged within their corresponding case-budget cells.

Claim coverage includes incidental claims present in annotated supporting passages. The dataset records canonical claim identities; explicit required-claim labels are not part of this evaluation. Origin coverage uses the annotated root-origin graph.

The Qwen tokenizer determines budget feasibility. `actual_context_tokens` supplies a separate rendered-context footprint for comparison against `raw_full`.

Higher selection precision and evidence retention indicate stronger retention of annotated supporting material. Context size records the number of tokens passed to the consuming model.

## Statistical Analysis

The final evaluation uses **50,000 paired whole-case bootstrap resamples**, seed `20261026`. Each resample retains the six token budgets for a case. Judge trials are averaged before pairing. A sensitivity analysis resamples four cases within each domain.

| Comparison | Precision Difference | 95% Confidence Interval |
|---|---:|---|
| BM25 + Omneum vs. BM25 | +3.96 pp | −1.23 to +9.71 pp |
| MiniLM + Omneum vs. MiniLM | +3.02 pp | −2.03 to +9.17 pp |
| BGE + Omneum vs. BGE | **+8.44 pp** | **+2.19 to +15.37 pp** |
| Cohere + Omneum vs. Cohere | +3.77 pp | −2.49 to +10.02 pp |

BGE + Omneum's precision advantage has a 95% interval entirely above zero. Its claim-coverage advantage also has an interval above zero; the origin-coverage interval crosses zero.

The intervals use percentile bootstrap resampling over 24 designed synthetic cases. The recovery policy was developed using these cases, so its evaluation reflects performance on the same fixed benchmark suite.

Exact comparisons are saved in `benchmarks/context_selection/synthetic/results/budget-exhaustion-recovery-20261026-v2/paired_comparisons.csv`. Case-level, case-budget, and domain-budget records are in `paired_cases.csv`, `paired_case_budget.csv`, and `paired_domain_budget.csv`.

## Reproduction

The leaderboard is derived from saved selections and timing records for the current evaluation. Offline analysis recomputes selection metrics and confidence intervals from those artifacts.

Benchmark implementation:

```text
benchmarks/context_selection/synthetic/tier1_benchmark.py
benchmarks/context_selection/synthetic/tier1_competitors.py
benchmarks/context_selection/synthetic/tier1_metrics.py
```

Published execution artifacts:

```text
benchmarks/context_selection/synthetic/results/tier1-production-20261025-v1/
benchmarks/context_selection/synthetic/results/tier1-competitors-20261025-v1/
benchmarks/context_selection/synthetic/analysis/tier1-competitive-analysis-20261026-v1/
benchmarks/context_selection/synthetic/results/budget-exhaustion-recovery-20261026-v2/
```

The final paired analysis uses `experiments/analyze_budget_recovery.py`. Its inputs and validation checks are recorded in `budget-exhaustion-recovery-20261026-v2/analysis_validation.json`.

The read-only audit reproduced all **2,328 initial** and **720 corrected** selection records against the saved metric outputs. It verified **11,640 initial** and **3,600 corrected** timing records, aggregate quality metrics, latency percentiles, and paired confidence intervals.

The analysis uses preserved model rankings and selection records. Recomputing these metrics requires no additional provider inference.

### Artifacts

| Artifact | Path |
|---|---|
| Production entry point | [`omneum/client.py`](../omneum/client.py) |
| Context selection | [`omneum/context_selection.py`](../omneum/context_selection.py) |
| Question context | [`omneum/query_context.py`](../omneum/query_context.py) |
| Benchmark runner | [`tier1_benchmark.py`](context_selection/synthetic/tier1_benchmark.py) |
| Competitor runner | [`tier1_competitors.py`](context_selection/synthetic/tier1_competitors.py) |
| Selection metrics | [`tier1_metrics.py`](context_selection/synthetic/tier1_metrics.py) |
| Competitor results | [`tier1-competitors-20261025-v1/`](context_selection/synthetic/results/tier1-competitors-20261025-v1/) |
| Competitive analysis | [`tier1-competitive-analysis-20261026-v1/`](context_selection/synthetic/analysis/tier1-competitive-analysis-20261026-v1/) |
| Final evaluation | [`budget-exhaustion-recovery-20261026-v2/`](context_selection/synthetic/results/budget-exhaustion-recovery-20261026-v2/) |
| Dataset documentation | [`DATASET.md`](context_selection/synthetic/DATASET.md) |
| Publication evidence | [`EVIDENCE.md`](context_selection/synthetic/EVIDENCE.md) |
| Latency analysis | [`LATENCY_ANALYSIS.md`](context_selection/synthetic/LATENCY_ANALYSIS.md) |

## Interpretation

The current evaluation measures the passages selected for an agent's context window, using annotated supporting sources and structured provenance. The benchmark records reconstructed-context size and local selection latency alongside selection quality.

Production `prepare_context()` combines question-aware discovery with Omneum's dependency-adjusted source reliability inference. Derived claim support drives `coverage_support_density` passage selection. Deferred-candidate recovery extends the candidate neighborhood when additional supporting passages meet the marginal utility threshold.

The final hybrids improve aggregate precision over their standalone rankers by **3.02–8.44 percentage points**, with **14.46%–18.51% fewer Qwen tokens** in the reconstructed context. Their aggregate recall and evidence retention remain lower than the corresponding standalone methods.

Frontier LLM judges achieve higher aggregate selection quality across the evaluated cases. Omneum executes local selection without an additional frontier judge call. The recorded timing boundaries separate local selection from external inference.

The dataset contains 24 designed synthetic cases, with repeated ranking trials evaluated at six token budgets. The recovery implementation was developed against these cases. Public-dataset downstream answer evaluation is maintained separately from this leaderboard.

For the benchmark configuration and reproduction instructions, see [Benchmark Methodology](README.md).

## Domain Evaluations

| Domain | Documentation |
|---|---|
| Coding Agents | [coding.md](coding.md) |
| Enterprise RAG | [enterprise-rag.md](enterprise-rag.md) |
| Research & Analysis | [research.md](research.md) |
| Multi-Agent Systems | [multi-agent.md](multi-agent.md) |
| Data Analytics | [analytics.md](analytics.md) |
| Support & Operations | [support.md](support.md) |
