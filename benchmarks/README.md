# Omneum Cross-Domain Context Curation Benchmark

Benchmarks evaluating Omneum's context preparation against retrieval methods, semantic rerankers, and frontier LLM judges.

The main evaluation covers **24 synthetic cases across six agentic domains**, with 13 budgeted configurations evaluated at six Qwen-token budgets. Omneum's production `prepare_context()` combines query relevance with provenance-aware graph inference to select and reconstruct original passages under a token budget for the consuming model's context window.

Four additional adversarial tracks cover circular sourcing, conflicting information, data staleness, and prompt injection.

**[Leaderboard](leaderboard.md) | [Dataset](context_selection/synthetic/DATASET.md) | [Saved Results](context_selection/synthetic/results/) | [Evidence](context_selection/synthetic/EVIDENCE.md)**

## Results

Published benchmark comparisons:

- [Semantic Rerankers](leaderboard.md#semantic-rerankers)
- [Budget-Exhaustion Recovery](leaderboard.md#budget-exhaustion-recovery)
- [Frontier LLM Judges](leaderboard.md#frontier-llm-judges)
- [Selection Latency](leaderboard.md#selection-latency)
- [Statistical Analysis](leaderboard.md#statistical-analysis)
- [Domain Evaluations](leaderboard.md#domain-evaluations)

The final hybrid selectors improve aggregate selection precision over their corresponding standalone BM25, MiniLM, BGE, and Cohere rankers by **3.02–8.44 percentage points**, while reducing mean reconstructed-context token usage by **14.46%–18.51%**. BGE + Omneum achieves **71.74% precision** and **75.36% claim coverage**, compared with **63.29% precision** and **68.75% claim coverage** for standalone BGE.

The additional precision and smaller contexts come with lower aggregate source recall and evidence retention for the hybrids. BGE + Omneum retains **55.26%** of annotated evidence, compared with **58.84%** for standalone BGE. Cohere + Omneum retains **56.20%**, compared with **64.39%** for standalone Cohere.

Frontier LLM judges retain more annotated evidence across the evaluated budgets. Claude Sonnet 5.5 reaches **76.49% evidence retention**, GPT-6 Astra **76.18%**, and Gemini 3.8 Flash **75.33%**. The [leaderboard](leaderboard.md) contains the full selection-quality comparisons, context sizes, latency measurements, and paired confidence intervals.

## Quick Start

Run from the repository root with the repository-pinned **uv 0.12.10**:

```sh
uv sync --locked --group benchmarks

uv run --locked --group benchmarks python \
  tools/run_context_evaluation_tests.py -q -p no:cacheprovider
```

The offline test runner covers dataset contracts, selection scoring, SDK integration, and saved-result processing. Provider-backed execution requires the corresponding credentials. Local daemon integration tests depend on Unix-socket permissions.

Benchmark implementation and results:

```text
benchmarks/context_selection/synthetic/
├── tier1_benchmark.py
├── tier1_competitors.py
├── tier1_metrics.py
├── results/
└── analysis/
```

The saved artifacts include the frozen candidate pools, recorded rankings, reconstructed passages, selection measurements, and statistical comparisons.

## Benchmark Suites

### Cross-Domain Context Selection

The main benchmark evaluates 13 context-selection configurations over 24 fixed synthetic cases. Each case supplies an agent task, original source passages, structured source–claim observations, and annotated supporting evidence.

| Configuration | Role |
|---|---|
| Original-Order RAG (`raw_budget`) | Original-order budget packing |
| BM25 (`bm25`) | Lexical retrieval |
| MiniLM (`embedding`) | Embedding similarity |
| BGE Reranker v2-m3 (`bge`) | Cross-encoder reranking |
| Cohere Rerank v4.0 Pro (`cohere`) | Hosted semantic reranking |
| Claude Sonnet 5.5 (`claude`) | Frontier LLM selection judge |
| GPT-6 Astra (`gpt`) | Frontier LLM selection judge |
| Gemini 3.8 Flash (`gemini`) | Frontier LLM selection judge |
| Omneum (`omneum`) | Production context preparation |
| BM25 + Omneum (`bm25_omneum`) | BM25 relevance with Omneum selection |
| MiniLM + Omneum (`embedding_omneum`) | Embedding relevance with Omneum selection |
| BGE + Omneum (`bge_omneum`) | BGE relevance with Omneum selection |
| Cohere + Omneum (`cohere_omneum`) | Cohere relevance with Omneum selection |

`raw_full` supplies the unbudgeted reference context and remains outside the 13 budgeted configurations.

All methods operate on the same candidate passages within each case. Selection budgets are **64, 96, 128, 160, 192, and 256 Qwen tokens**, enforced against the reconstructed context.

The Omneum configurations execute production `prepare_context()` with structured observations and the recorded relevance inputs. The hybrid configurations pass external ranker scores into Omneum's selection pipeline.

`prepare_context()` evaluates source dependencies within its reliability inference, derives claim support, and uses that support in passage utility. The selector packs original passages under the token budget and reconstructs the selected context.

Selection outputs are scored against the frozen source annotations and evidence spans.

**Results:** [Leaderboard](leaderboard.md)

### Omneum Implementation

The production entry point is `prepare_context()` in `omneum/client.py`. Budgeted passage selection is implemented in `omneum/context_selection.py`, with question-context handling in `omneum/query_context.py`.

The evaluated hybrid configuration uses:

| Parameter | Recorded Value |
|---|---|
| Selection objective | `coverage_support_density` |
| Complementary evidence | `complementary_evidence=True` |
| Token cost exponent | `token_cost_exponent=1` |
| Discovery anchors | 3 relevance anchors plus ties |
| Discovery expansion | Depth 2 |
| Conflict-aware selection | `conflict_aware=False` |
| BGE relevance semantics | `reranker_score` |
| BM25, MiniLM, Cohere relevance | Similarity scores |
| Budget exhaustion | Deferred candidate recovery with utility-density threshold |

Structured observations contain source identities, canonical claims, and dependency metadata. Omneum's algorithm estimates source dependence and incorporates it into source reliability during graph inference. The resulting claim support contributes to chunk utility.

`discover_chunks()` initializes the candidate neighborhood from relevance-ranked passages. Selection evaluates marginal utility against the remaining token budget and reconstructs retained chunks using their original source text.

When the initial discovery neighborhood exhausts positive, budget-feasible utility, the selector evaluates deferred candidates. Additional passages must satisfy the utility-density floor established during the initial selection. Previously selected passages remain in the reconstructed context.

This recovery increases aggregate evidence retention for all four hybrid configurations. MiniLM + Omneum retains **50.14%** of annotated evidence, and BGE + Omneum retains **55.26%**. The corresponding precision values are **66.83%** and **71.74%**.

The saved manifests preserve implementation hashes and execution settings for the final measurements.

### Application Domains

Four cases per domain.

| Domain | Evaluation Focus | Report |
|---|---|---|
| Coding Agents | Repository context, implementation dependencies, conflicting evidence | [coding.md](coding.md) |
| Enterprise RAG | Retrieved enterprise information, overlapping sources | [enterprise-rag.md](enterprise-rag.md) |
| Research & Analysis | Source reliability, upstream dependencies, conflicting claims | [research.md](research.md) |
| Multi-Agent Systems | Cross-agent context, feedback loops, shared dependencies | [multi-agent.md](multi-agent.md) |
| Data Analytics | Derived metrics, stale dashboards, conflicting definitions | [analytics.md](analytics.md) |
| Support & Operations | Runbooks, ticket references, competing resolutions | [support.md](support.md) |

The frozen dataset contains **189 original passages**, **400 annotated claim occurrences**, and **259 distinct claim identities**.

Case fixtures, supporting-source annotations, and source–claim contracts are documented in [`DATASET.md`](context_selection/synthetic/DATASET.md).

### Adversarial Evaluations

Controlled evaluations of structural context failures.

| Track | Failure Mode |
|---|---|
| Circular Sourcing | References forming cycles without independent evidence |
| Conflicting Information | Incompatible assertions competing for support |
| Data Staleness | Outdated observations competing with newer evidence |
| Prompt Injection | Untrusted instructions embedded in retrieved context |

Run individual suites:

```sh
# Circular sourcing
python -m benchmarks.context_selection.adversarial.circular_sourcing.run_benchmark

# Conflicting information
python -m benchmarks.context_selection.adversarial.conflicting_information.run_benchmark

# Data staleness
python -m benchmarks.context_selection.adversarial.data_staleness.run_benchmark

# Prompt injection
python -m benchmarks.context_selection.adversarial.prompt_injection.run_benchmark
```

These runners retain their own execution contracts. Provider-backed tracks require configured model access and evaluator services.

The source-dependence track and financial example corpora remain outside the public distribution pending redistribution review. The cross-domain benchmark also includes dependency annotations in its candidate pools.

Implementation: [`context_selection/adversarial/`](context_selection/adversarial/)

## Repository Layout

```text
benchmarks/
├── README.md
├── leaderboard.md
├── coding.md
├── enterprise-rag.md
├── research.md
├── multi-agent.md
├── analytics.md
├── support.md
└── context_selection/
    ├── publication_manifest_v1.json
    ├── synthetic/
    │   ├── DATASET.md
    │   ├── EVIDENCE.md
    │   ├── DASHBOARD_SUMMARY.md
    │   ├── LATENCY_ANALYSIS.md
    │   ├── tier1_benchmark.py
    │   ├── tier1_competitors.py
    │   ├── tier1_metrics.py
    │   ├── results/
    │   │   ├── tier1-production-20261025-v1/
    │   │   ├── tier1-competitors-20261025-v1/
    │   │   └── budget-exhaustion-recovery-20261026-v2/
    │   └── analysis/
    │       └── tier1-competitive-analysis-20261026-v1/
    └── adversarial/
        ├── circular_sourcing/
        ├── conflicting_information/
        ├── data_staleness/
        └── prompt_injection/
```

Benchmark execution code and frozen results are maintained under `benchmarks/context_selection/synthetic/`.

Production context preparation is implemented in:

```text
omneum/client.py
omneum/context_selection.py
omneum/query_context.py
```

## Evaluation Configuration

| Parameter | Value |
|---|---|
| Dataset | 24 synthetic cases |
| Domains | 6 |
| Source passages | 189 |
| Claim occurrences | 400 |
| Distinct claim identities | 259 |
| Candidate pool | Fixed per case |
| Selection budgets | 64, 96, 128, 160, 192, 256 Qwen tokens |
| Budgeted configurations | 13 |
| Unbudgeted reference | `raw_full` |
| Semantic methods | BM25, MiniLM, BGE v2-m3, Cohere v4.0 Pro |
| LLM judges | Claude Sonnet 5.5, GPT-6 Astra, Gemini 3.8 Flash |
| Omneum objective | `coverage_support_density` |
| Omneum discovery | Relevance anchors with depth-2 expansion and deferred recovery |
| Output | Selected source IDs, reconstructed context, metric records, timing samples |

The saved frontier rankings use two trials per case. Their selections are evaluated at each token budget, with trial scores averaged within the case-budget cell before macro aggregation.

The benchmark records source identifiers, selection order, reconstructed context, and tokenizer counts. Source-level metrics use the frozen supporting-source annotations; evidence and claim metrics use the corresponding canonical records.

Final Omneum hybrid measurements include the completed budget-exhaustion recovery. The standalone methods retain their recorded configurations.

### Metrics

| Metric | Definition |
|---|---|
| Selection Precision | Selected supporting-source IDs divided by selected source IDs |
| Selection Recall | Selected supporting-source IDs divided by annotated supporting-source IDs |
| Evidence Retention | Retained gold evidence-span footprint divided by total gold evidence footprint |
| Claim Coverage | Canonical claim IDs represented in selected passages against claims from gold passages |
| Origin Coverage | Annotated root-origin units represented by retained gold passages |
| `tokenizer_tokens` | Qwen tokenizer count of reconstructed context |
| `actual_context_tokens` | Regex word/punctuation footprint of rendered context |
| Context Reduction | Reduction in rendered footprint against `raw_full` |
| Selection p50 / p95 | Median and 95th-percentile local selection latency |

Selection precision and recall compare selected source IDs with the fixture's annotated supporting-source set.

Evidence retention measures merged gold evidence spans using the benchmark's word/punctuation footprint. Claim coverage uses canonical claim IDs from supporting passages, including incidental claims present in those passages.

Origin coverage follows the annotated root-origin graph. Its reference units depend on the dataset's provenance records.

`tokenizer_tokens` enforces the Qwen-token budget. `actual_context_tokens` records the rendered word/punctuation footprint, including passage headers.

Quality metrics are macro-averaged across 24 cases and six budgets. Repeated frontier-ranking trials are averaged within their corresponding case-budget cells.

### Latency

Final local Omneum selection measurements:

| Configuration | Selection p50 | Selection p95 |
|---|---:|---:|
| Omneum | 194.86ms | 451.87ms |
| BM25 + Omneum | 207.79ms | 461.25ms |
| MiniLM + Omneum | 203.84ms | 465.36ms |
| BGE + Omneum | 200.63ms | 430.51ms |
| Cohere + Omneum | 206.89ms | 480.37ms |

The measured interval begins with relevance scores and structured observations available. It covers graph evaluation, candidate discovery, token-budgeted packing, passage reconstruction, and SDK verification.

External relevance-model inference and structured extraction are excluded from the local selector timings. Token counts are prewarmed.

Standalone ranker packing times are substantially smaller because their recorded local interval excludes ranking-model inference and graph evaluation. Frontier provider response times are recorded separately.

See [`LATENCY_ANALYSIS.md`](context_selection/synthetic/LATENCY_ANALYSIS.md) and the [final recovery report](context_selection/synthetic/results/budget-exhaustion-recovery-20261026-v2/report.md).

### Cost

Recorded frontier-model ranking usage:

| Provider | Estimated Cost |
|---|---:|
| Claude Sonnet 5.5 | $0.113996 |
| GPT-6 Astra | $0.281080 |
| Gemini 3.8 Flash | $0.025231 |
| **Total** | **$0.420307** |

Estimates use the saved input/output token counts and pricing assumptions in `provider_usage.csv`. Cohere's historical API charge is unavailable.

The production Omneum selection route executes locally. Provider costs apply to the recorded frontier ranking calls. Structured observation preparation and local compute costs are excluded from these estimates and were not measured.

Saved ranking responses are reused across budgets and applicable hybrid configurations.

## Running Evaluations

### 1. Inspect the Benchmark Implementation

The benchmark execution and metric implementations are maintained in:

```sh
# Production benchmark runner
sed -n '1,240p' \
  benchmarks/context_selection/synthetic/tier1_benchmark.py

# Competitor adapters
sed -n '1,240p' \
  benchmarks/context_selection/synthetic/tier1_competitors.py

# Selection metrics
sed -n '1,240p' \
  benchmarks/context_selection/synthetic/tier1_metrics.py
```

The run manifests identify the executed configuration, source fingerprints, tokenizer contract, and saved output artifacts.

### 2. Run Offline Tests

```sh
uv run --locked --group benchmarks python \
  tools/run_context_evaluation_tests.py -q -p no:cacheprovider
```

The regression runner exercises benchmark contracts and local integration behavior. Publication metrics are independently checked against the saved selections and timing records.

### 3. Inspect Final Results

```sh
# Final selection results
cat \
  benchmarks/context_selection/synthetic/results/budget-exhaustion-recovery-20261026-v2/report.md

# Aggregate paired comparisons
head -n 10 \
  benchmarks/context_selection/synthetic/results/budget-exhaustion-recovery-20261026-v2/paired_comparisons.csv

# Domain and budget comparisons
head -n 10 \
  benchmarks/context_selection/synthetic/results/budget-exhaustion-recovery-20261026-v2/paired_domain_budget.csv
```

The final report contains the corrected Omneum hybrid measurements. `paired_comparisons.csv` records differences against the corresponding standalone rankers and the original hybrid implementations.

### 4. Inspect Competitive Analysis

```sh
cat \
  benchmarks/context_selection/synthetic/analysis/tier1-competitive-analysis-20261026-v1/report.md
```

The competitive analysis contains the frozen competitor measurements, selection-quality comparisons, and provider-call telemetry used alongside the final hybrid results.

### 5. Run a New Evaluation

The benchmark runner's argument contract is defined in `tier1_benchmark.py` and `tier1_competitors.py`. The saved manifests record the configuration used for the published evaluation.

New executions should use separately versioned result directories and retain their implementation fingerprints. Provider-backed configurations require the corresponding credentials and model access.

## Saved Results

Benchmark artifacts:

```text
benchmarks/context_selection/synthetic/
├── results/
│   ├── tier1-production-20261025-v1/
│   ├── tier1-competitors-20261025-v1/
│   └── budget-exhaustion-recovery-20261026-v2/
└── analysis/
    └── tier1-competitive-analysis-20261026-v1/
```

The published benchmark combines frozen competitor results with the final Omneum hybrid selections. The directories preserve their execution-specific configurations and measurements.

The production run contains BM25, MiniLM, BGE, and their Omneum hybrids. The competitor run contains the baseline rankers, frontier judges, standalone Omneum, and initial hybrid results. The final recovery evaluation supplies the published standalone Omneum and four hybrid results, with paired statistical analysis.

### Inspect a Run

```sh
# Final selection report
cat \
  benchmarks/context_selection/synthetic/results/budget-exhaustion-recovery-20261026-v2/report.md

# Paired comparisons
head \
  benchmarks/context_selection/synthetic/results/budget-exhaustion-recovery-20261026-v2/paired_comparisons.csv

# Domain and budget records
head \
  benchmarks/context_selection/synthetic/results/budget-exhaustion-recovery-20261026-v2/domain_budget_case_levels.csv

# Analysis validation
python -m json.tool \
  benchmarks/context_selection/synthetic/results/budget-exhaustion-recovery-20261026-v2/analysis_validation.json
```

The saved records contain the selected passage identities, reconstructed context, token counts, and metric inputs used in the published comparisons.

### Evaluation Records

The final recovery evaluation contains **720 selection records** across five configurations: standalone Omneum and four Omneum hybrids, with **3,600 timing executions**. The original benchmark artifacts contain **2,328 selection records** covering the competitor evaluation and initial Omneum measurements.

The completed audit verified **11,640 original** and **3,600 corrected** timing records. Selection-quality aggregates, latency percentiles, and 232 paired-comparison confidence intervals were recomputed from saved artifacts.

The published comparison uses the final hybrid outputs and unchanged competitor measurements, joined by case, token budget, and configuration.

### Provenance and Integrity

The execution artifacts retain the exact source and result identifiers:

| Artifact | Purpose |
|---|---|
| `tier1-production-20261025-v1/` | BM25, MiniLM, BGE, and their Omneum hybrids |
| `tier1-competitors-20261025-v1/` | Competitor rankings and original hybrid measurements |
| `tier1-competitive-analysis-20261026-v1/` | Competitive metrics and statistical analysis |
| `budget-exhaustion-recovery-20261026-v2/` | Final hybrid outputs and paired statistics |
| `analysis_validation.json` | Final analysis input validation |
| `paired_comparisons.csv` | Paired metric differences and confidence intervals |

The run manifests preserve recorded Git references, source-file hashes, configuration values, and output fingerprints.

The recorded reference revision is `6d430d4efd28559a262212e9f88aba63c080238a`. Implementation hashes and preserved snapshots identify the executed code; the reference revision alone is not an exact source snapshot.

The final hybrid recovery preserves the original selected passages in every corrected selection cell. Source recall, evidence retention, claim coverage, and origin coverage are nondecreasing relative to the initial hybrid outputs.

## Evaluation Scope

- **Dataset:** 24 designed synthetic cases across six agentic domains, evaluated at six Qwen-token budgets.
- **Selector inputs:** Omneum receives structured `Observation` objects, original retrieved chunks, and relevance inputs. Competing methods use their recorded passage rankings or selection inputs.
- **Selection policy:** The final hybrid implementation includes deferred candidate recovery with the recorded marginal utility-density threshold.
- **Selection quality:** Precision and recall use annotated source IDs. Evidence retention measures annotated spans; claim coverage includes incidental claims in supporting passages.
- **Latency:** Local Omneum measurements start after relevance scoring and observation preparation, with prewarmed token counts.
- **Cost:** Provider estimates use recorded token usage and saved pricing assumptions. Local computation and extraction have separate cost boundaries.
- **Reproducibility:** Saved selections, implementation fingerprints, timing records, and paired comparisons support offline verification.
- **Public-dataset evaluation:** The HotpotQA End-to-End Pipeline Evaluation (v1.1.0) — a separate evaluation of the end-to-end pipeline using HotpotQA.

The benchmark contains **13 budgeted configurations**, six Qwen-token budgets, and 24 synthetic cases. The final selection results and their underlying execution artifacts are preserved under `benchmarks/context_selection/synthetic/`.

For aggregate results, see the [Benchmark Leaderboard](leaderboard.md).