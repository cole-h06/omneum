# Data Analytics Agents

Data Analytics evaluation for the Omneum Cross-Domain Context Curation Benchmark.

Four synthetic cases test context selection for circular reporting dependencies, incomplete transformation lineage, conflicting metric definitions, and stale dashboard snapshots.

**4 cases · 33 candidate passages · 6 Qwen-token budgets · 13 budgeted configurations**

[Leaderboard](leaderboard.md) | [Benchmark README](README.md) | [Dataset](context_selection/synthetic/DATASET.md) | [Saved Results](context_selection/synthetic/results/)

## Quick Start

Run from the Omneum repository root.

```bash
# Run offline benchmark tests
uv sync --locked --group benchmarks
uv run --locked --group benchmarks python \
  tools/run_context_evaluation_tests.py -q -p no:cacheprovider

# Inspect the final benchmark results
cat benchmarks/context_selection/synthetic/results/budget-exhaustion-recovery-20261026-v2/report.md
```

The offline tests exercise benchmark contracts, metrics, and local integration without issuing new provider inference requests. The saved benchmark artifacts contain the recorded selections and measurements.

## Cases

| Case | Candidates | Token Budgets | Expected Answer | Failure Mode |
|---|---:|---|---|---|
| [`analytics_derived_metric_cycle`](#analytics_derived_metric_cycle) | 8 | 64–256 | 612 accounts | Circular derived-data lineage |
| [`analytics_incomplete_lineage`](#analytics_incomplete_lineage) | 9 | 64–256 | 487 parcels | Incomplete transformation lineage |
| [`analytics_metric_definition_conflict`](#analytics_metric_definition_conflict) | 8 | 64–256 | 92% | Conflicting metric definitions |
| [`analytics_stale_dashboard`](#analytics_stale_dashboard) | 8 | 64–256 | 1,284 seats | Stale dashboard snapshot |

Each case uses a fixed candidate pool, source-level relevance labels, canonical claims, and source-provenance annotations.

The six selection budgets are **64, 96, 128, 160, 192, and 256 Qwen tokens**, measured against reconstructed original passage text.

## Recorded Results

The final benchmark evaluates production `prepare_context()` against lexical retrieval, semantic rerankers, and frontier LLM judges.

Omneum's provenance-aware graph inference computes source reliability and claim support, accounting for shared evidence origins and dependencies between sources. `prepare_context()` combines claim support with question relevance and incremental claim coverage to select and reconstruct original passages within the token budget.

The benchmark evaluates context selection only. It does not execute downstream answer generation.

### Configurations

| Configuration | Selection Method |
|---|---|
| Original-Order RAG | `raw_budget` |
| BM25 | `bm25` |
| MiniLM | `embedding` |
| BGE Reranker v2-m3 | `bge` |
| Cohere Rerank v4.0 Pro | `cohere` |
| Claude Sonnet 5.5 | `claude` |
| GPT-6 Astra | `gpt` |
| Gemini 3.8 Flash | `gemini` |
| Omneum Standalone | `omneum` |
| BM25 + Omneum | `bm25_omneum` |
| MiniLM + Omneum | `embedding_omneum` |
| BGE + Omneum | `bge_omneum` |
| Cohere + Omneum | `cohere_omneum` |

An additional unbudgeted `raw_full` configuration provides a full-context reference.

All budgeted configurations use the same six Qwen-token budgets. Hybrid configurations pass external relevance rankings into Omneum's production context-selection pipeline.

Selection precision and recall are computed against annotated supporting-source IDs. Additional metrics measure evidence retention, canonical claim coverage, root-origin coverage, reconstructed-context token count, and selection latency.

### Semantic Reranker Comparisons

The final BGE and Cohere comparisons use identical token budgets for each standalone reranker and its Omneum hybrid.

| Configuration | All-Domain Precision |
|---|---:|
| BGE Reranker v2-m3 | 63.29% |
| BGE + Omneum | **71.74%** |
| Cohere Rerank v4.0 Pro | 71.11% |
| Cohere + Omneum | **74.88%** |

Across all 24 cases, BGE + Omneum improved selection precision by **8.44 percentage points** over standalone BGE, with a paired whole-case bootstrap 95% confidence interval of **+2.19 to +15.37 percentage points**.

Cohere + Omneum improved precision by **3.77 percentage points**, with a 95% confidence interval of **−2.49 to +10.02 percentage points**. This interval includes zero.

These are all-domain results, not Data Analytics-specific measurements.

The final Data Analytics case-budget and domain-budget measurements are preserved in the benchmark artifacts. The earlier fixed-source-budget results are not interchangeable with the final token-budgeted evaluation.

### Final Evaluation Artifacts

```text
benchmarks/context_selection/synthetic/
├── results/
│   ├── tier1-production-20261025-v1/
│   ├── tier1-competitors-20261025-v1/
│   └── budget-exhaustion-recovery-20261026-v2/
└── analysis/
    └── tier1-competitive-analysis-20261026-v1/
```

The final hybrid results incorporate corrected deferred-candidate budget-exhaustion recovery.

The earlier fixed-source-budget precision, recall, downstream answer scores, and latency measurements are not directly comparable to this evaluation.

## `analytics_derived_metric_cycle`

**Task:** Determine Solis daily active accounts for August 17 using distinct production account IDs with at least one session.

```text
What is Solis daily active accounts for August 17,
using distinct production account IDs with at least one session?
```

### Fixture

```text
8 candidates
3 relevant
```

The derived table reports 840 daily active accounts. Its dashboard exports the same value to CSV, which is reimported during nightly repair.

The reporting artifacts form a dependency cycle:

```text
derived_table (840)
      |
      v
dashboard (840)
      |
      v
csv_export (840)
      |
      | nightly repair import
      v
derived_table
```

The three artifacts repeat the same derived value. They are not independent measurements of daily active accounts.

The discrepancy originates from the aggregation: 840 counts sessions rather than distinct production accounts.

The production source tables and a fresh warehouse query establish the expected count.

```sql
SELECT COUNT(DISTINCT account_id)
FROM production_sessions
WHERE session_date = '2026-08-17';
```

The query illustrates the distinct-account aggregation; the fixture's exact table schema and filtering conditions are defined by its recorded source data.

Expected result:

```text
612
```

### Recorded Selections

The three annotated supporting sources are:

| Source | Evidence | Relevance |
|---|---|---|
| `source_table` | Production source data | Supporting |
| `source_table_2` | Additional production source data | Supporting |
| `query_result` | Distinct-account warehouse query | Supporting |
| `derived_table` | Incorrect session-based aggregate | Not supporting |
| `dashboard` | Derived metric display | Not supporting |
| `csv_export` | Export of derived metric | Not supporting |

The final benchmark records identify which passages each configuration retained at each token budget.

### Comparative Analysis

The supporting source set is:

```text
source_table_2
source_table
query_result
```

These sources establish the distinct-account count without relying on the circularly dependent derived table, dashboard, and CSV export.

The circular reporting chain contains three artifacts repeating the same incorrect value. Their agreement does not represent three independent measurements.

Omneum's provenance-aware graph inference accounts for the shared evidence origins and circular dependencies when computing source reliability and claim support. The resulting claim support contributes to passage utility during context selection.

**Result:** The case evaluates whether production source data and a fresh distinct-account query survive context selection despite multiple downstream artifacts repeating the incorrect 840-session count.

The expected value of 612 is a fixture reference answer. The final benchmark does not score generated answers against it.

## `analytics_incomplete_lineage`

**Task:** Determine delivered parcels in the Noria August 16 dispatch cohort, excluding returned parcels.

```text
How many delivered parcels belong to the Noria August 16
dispatch cohort, excluding returned parcels?
```

### Fixture

```text
9 candidates
4 relevant
```

A migrated transformation calculates `delivered_count` using `COUNT(*)`, producing 520 parcels.

That value includes 33 returned parcels.

```text
520 reported delivered parcels
-33 returned parcels
--------------------
487 delivered parcels
```

The derived table, dashboard, and CSV export reproduce the 520 figure.

The transformation's input lineage and the dashboard's SQL attachment are missing, limiting direct reconstruction of the reporting pipeline from those artifacts.

The current dispatch records, carrier receipts, metric store, and reconciliation query establish the expected result of 487.

The relevant aggregation must exclude returned parcels:

```sql
SELECT COUNT(*)
FROM dispatch_parcels
WHERE dispatch_date = '2026-08-16'
  AND delivery_status = 'delivered'
  AND returned = FALSE;
```

This is an illustrative query expressing the fixture's expected filtering behavior, not a verified query copied from its source files.

### Recorded Selections

The four annotated supporting sources are:

| Source | Evidence | Relevance |
|---|---|---|
| `source_table` | Current dispatch records | Supporting |
| `source_table_2` | Carrier evidence | Supporting |
| `metric_store` | Metric definition | Supporting |
| `query_result` | Reconciliation query | Supporting |

The migrated transformation and its downstream reporting artifacts reproduce the incorrect 520-parcel figure.

The final benchmark results record which sources each selector retained at the six token budgets.

### Comparative Analysis

The relevant source set is:

```text
source_table
source_table_2
metric_store
query_result
```

These sources establish the current dispatch count and the filtering requirements for returned parcels.

The missing transformation lineage limits direct attribution of the 520-parcel figure to its upstream inputs.

Omneum's provenance-aware graph inference uses the available source relationships when computing source reliability and claim support. Missing provenance does not establish that sources are independent.

**Result:** The case tests selection of current dispatch and reconciliation evidence when a migrated transformation and its downstream exports report an incorrect aggregate with incomplete provenance.

The reference count is 487 delivered parcels. The final benchmark measures evidence selection rather than generated-answer correctness.

## `analytics_metric_definition_conflict`

**Task:** Determine Atlas July gross revenue retention under the finance definition excluding expansion.

```text
What is Atlas July gross revenue retention under
the finance definition excluding expansion?
```

### Fixture

```text
8 candidates
3 relevant
```

The finance definition excludes expansion revenue from gross revenue retention.

The recorded inputs are:

```text
Starting recurring revenue: 100,000
Contraction:                 5,000
Churn:                       3,000
Expansion:                  20,000
```

The correct finance calculation is:

```text
(100000 - 5000 - 3000) / 100000 = 0.92
```

Therefore:

```text
Gross revenue retention = 92%
```

The semantic layer and dbt transformation incorrectly include expansion revenue:

```text
(100000 - 5000 - 3000 + 20000) / 100000 = 1.12
```

This produces 112%.

The dashboard and exported report inherit the incorrect calculation from the transformation.

```text
Finance definition
    |
    +-- Exclude expansion
    |
    +-- GRR = 92%

Semantic layer / dbt transformation
    |
    +-- Include expansion
    |
    +-- GRR = 112%
           |
           +--> Dashboard
           |
           +--> Exported report
```

The expected answer is defined by the finance metric specification, not by the number of downstream artifacts repeating the alternative calculation.

### Recorded Selections

The three annotated supporting sources are:

| Source | Evidence | Relevance |
|---|---|---|
| `finance_report` | Finance metric definition and result | Supporting |
| `metric_docs` | Gross revenue retention specification | Supporting |
| `warehouse_query` | Warehouse calculation excluding expansion | Supporting |
| `data_catalog` | Alternative catalog evidence | Not supporting |

The final benchmark selections are evaluated against the three supporting source IDs.

### Comparative Analysis

The relevant source set is:

```text
finance_report
metric_docs
warehouse_query
```

These sources establish the finance definition, its documentation, and the warehouse calculation supporting the expected result.

The incorrect semantic-layer calculation adds expansion revenue to gross revenue retention, producing 112% instead of 92%.

The dashboard and exported report repeat that calculation through downstream transformation lineage.

Omneum's provenance-aware graph inference accounts for these shared evidence origins when computing source reliability and claim support. `prepare_context()` combines that support with question relevance and incremental claim coverage when selecting passages.

The earlier fixed-source-budget evaluation exposed a Cohere + Omneum selection error involving `data_catalog` instead of `warehouse_query`. That historical observation identifies the failure mode; it is not a final token-budgeted result.

**Result:** The case measures whether context selection preserves the finance metric definition and its supporting calculation despite conflicting downstream implementations.

## `analytics_stale_dashboard`

**Task:** Determine Meridian's finalized July 2026 paid-seat count after the August 12 backfill.

```text
What is Meridian's finalized July 2026 paid-seat count
after the August 12 backfill?
```

### Fixture

```text
8 candidates
5 relevant
```

The August 2 dashboard snapshot and August 3 report export contain the earlier count:

```text
1,190 paid seats
```

Backfill `B12`, executed on August 12, rebuilds the July warehouse partition.

The finalized count is:

```text
1,284 paid seats
```

The reporting sequence is:

```text
July warehouse partition
         |
         v
August 2 dashboard snapshot
         |
         +--> 1,190 seats
         |
         v
August 3 report export
         |
         +--> 1,190 seats


August 12 backfill B12
         |
         v
Rebuilt July warehouse partition
         |
         +--> 1,284 seats
                 |
                 +--> Current query
                 |
                 +--> Metric store
                 |
                 +--> Metrics API
```

The older dashboard and report are stale snapshots of the metric before the finalized backfill.

The current warehouse query, metric store, and API reflect the revised count.

### Recorded Selections

The final supporting evidence includes the post-backfill warehouse and reporting sources.

| Source | Evidence | Relevance |
|---|---|---|
| `warehouse_table` | Rebuilt July warehouse partition | Supporting |
| `current_query` | Current warehouse query | Supporting |
| `metric_store` | Finalized paid-seat metric | Supporting |
| `api_result` | Current metrics API | Supporting |
| August 2 dashboard snapshot | Earlier 1,190-seat count | Not supporting |
| August 3 report export | Earlier 1,190-seat count | Not supporting |

The fixture contains five annotated supporting sources in total. The table identifies the named current sources established by the case description; the saved fixture defines the complete source IDs.

### Comparative Analysis

The supporting source set includes:

```text
warehouse_table
api_result
metric_store
current_query
```

These sources reflect the finalized post-backfill metric rather than the stale dashboard snapshot.

The warehouse partition was rebuilt by backfill `B12`, and the current query, metric store, and API reflect the revised count.

The dashboard and report export were produced before the backfill. Their agreement on 1,190 seats does not establish the finalized count.

The case tests whether context selection retains current post-backfill evidence rather than earlier reporting snapshots. The relevant distinction is the reporting state before and after backfill `B12`, not the frequency of the repeated 1,190-seat value.

**Result:** The case evaluates whether selected context preserves the finalized warehouse count of 1,284 paid seats instead of older, internally consistent reporting artifacts.

The final benchmark does not execute a downstream generator to score that answer.

## Inspect Recorded Runs

The four analytics cases are part of the frozen synthetic benchmark dataset.

### Case Fixtures

```text
benchmarks/context_selection/synthetic/
├── DATASET.md
├── tier1_benchmark.py
├── tier1_competitors.py
└── tier1_metrics.py
```

Inspect the dataset and benchmark implementation:

```bash
cat benchmarks/context_selection/synthetic/DATASET.md

rg -n \
  'analytics_derived_metric_cycle|analytics_incomplete_lineage|analytics_metric_definition_conflict|analytics_stale_dashboard' \
  benchmarks/context_selection/synthetic/
```

Each case defines a fixed candidate pool, supporting-source annotations, and evaluation metadata.

### Saved Results

```text
benchmarks/context_selection/synthetic/results/
├── tier1-production-20261025-v1/
├── tier1-competitors-20261025-v1/
└── budget-exhaustion-recovery-20261026-v2/
```

The production and competitor directories contain the original benchmark measurements. The recovery directory contains the final corrected hybrid selections.

Inspect the final evaluation:

```bash
cat \
  benchmarks/context_selection/synthetic/results/budget-exhaustion-recovery-20261026-v2/report.md
```

Find the analytics case records:

```bash
rg -n \
  'analytics_derived_metric_cycle|analytics_incomplete_lineage|analytics_metric_definition_conflict|analytics_stale_dashboard' \
  benchmarks/context_selection/synthetic/results/budget-exhaustion-recovery-20261026-v2/
```

Inspect the competitive analysis:

```bash
cat \
  benchmarks/context_selection/synthetic/analysis/tier1-competitive-analysis-20261026-v1/report.md
```

These commands inspect preserved benchmark artifacts without rerunning provider inference.

### Selection Latency

The final aggregate local selection timings across all six domains are:

| Configuration | Selection p50 | Selection p95 |
|---|---:|---:|
| Omneum Standalone | 194.86ms | 451.87ms |
| BM25 + Omneum | 207.79ms | 461.25ms |
| MiniLM + Omneum | 203.84ms | 465.36ms |
| BGE + Omneum | 200.63ms | 430.51ms |
| Cohere + Omneum | 206.89ms | 480.37ms |

These are benchmark-wide measurements, not Data Analytics-specific latency percentiles.

The local selection interval excludes external ranking inference and structured observation extraction. Frontier LLM judges have different inference and timing boundaries.

## Evaluation Notes

| Setting | Value |
|---|---|
| Cases | 4 |
| Candidate passages | 33 total |
| Candidate pools | 8–9 passages per case |
| Selection budgets | 64, 96, 128, 160, 192, 256 Qwen tokens |
| Tokenizer | Qwen2.5 7B GGUF |
| Budgeted configurations | 13 |
| Unbudgeted reference | `raw_full` |
| Initial rankers | BM25, MiniLM, BGE Reranker v2-m3, Cohere Rerank v4.0 Pro |
| Frontier judges | Claude Sonnet 5.5, GPT-6 Astra, Gemini 3.8 Flash |
| Omneum entry point | `prepare_context()` |
| Selection objective | `coverage_support_density` |
| Complementary evidence | `complementary_evidence=True` |
| Token cost exponent | `token_cost_exponent=1` |
| Discovery anchors | 3 plus relevance-score ties |
| Discovery expansion | Depth 2 |
| Deferred-candidate recovery | Enabled for final hybrid results |
| Conflict-aware selection | `conflict_aware=False` |
| Selection scoring | Annotated supporting-source IDs |
| Evidence scoring | Retained annotated evidence |
| Claim scoring | Canonical claims represented in supporting passages |
| Origin scoring | Annotated root-origin units |
| Latency aggregation | Recorded local selection p50 and p95 |

Omneum's provenance-aware graph inference iteratively computes source reliability and claim support across a bipartite graph, accounting for shared evidence origins and dependencies between sources.

The SDK maps finalized claim support to retrieved chunks through their associated claim IDs. `prepare_context()` uses question relevance and incremental claim coverage to select and reconstruct original passages within the configured token budget.

The final hybrid results include deferred-candidate budget-exhaustion recovery. Positive-utility candidates outside the initial discovery neighborhood can be reconsidered when they satisfy the remaining token budget and marginal utility-density threshold.

### Measurement Constraints

The benchmark contains four fixed synthetic analytics cases.

The six token budgets provide repeated measurements of the same underlying cases, not additional independent questions.

Precision measures the proportion of selected sources annotated as supporting. Recall measures the proportion of annotated supporting sources retained.

Evidence retention, claim coverage, and origin coverage measure complementary properties of the selected context. Claim coverage may include incidental claims present in supporting passages, while origin coverage depends on the supplied provenance graph.

The benchmark does not measure downstream answer correctness. It evaluates selected and reconstructed context.

The production selection timings exclude external ranking inference and structured observation extraction. Comparisons with LLM judges must account for differences in information availability and timing boundaries.

The selection policy was developed against the same synthetic case suite. These results support controlled evaluation and regression testing but do not independently establish generalization to unseen analytics workloads.

## Summary

The four Data Analytics cases evaluate distinct failure mechanisms:

- **Derived metric cycle:** Circular reporting dependencies repeat an incorrect 840-session aggregate instead of the correct 612-account count.
- **Incomplete lineage:** Missing transformation provenance accompanies a 520-parcel aggregate that includes 33 returned parcels; current operational evidence establishes 487 delivered parcels.
- **Metric definition conflict:** The finance definition produces 92% gross revenue retention, while the semantic layer and downstream reports incorrectly include expansion revenue and produce 112%.
- **Stale dashboard:** Earlier reporting snapshots show 1,190 paid seats, while the finalized post-backfill warehouse state establishes 1,284.

Across the full 24-case benchmark, BGE + Omneum improved selection precision over standalone BGE by **8.44 percentage points**, with a paired 95% confidence interval of **+2.19 to +15.37 percentage points**.

That aggregate improvement is not a substitute for the Data Analytics-specific measurements preserved in the saved case-budget and domain-budget artifacts.

See the [Leaderboard](leaderboard.md) for aggregate comparisons across all six domains.