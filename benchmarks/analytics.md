# Data Analytics Agents

Context-selection benchmark for data analytics agents operating across warehouse tables, SQL queries, metric definitions, transformation outputs, dashboards, and reporting APIs.

Evaluates four failure modes: circular derived-data lineage, incomplete transformation lineage, conflicting metric definitions, and stale dashboard snapshots.

**4 held-out cases · 33 candidate sources · Claude Sonnet 5.5 generator**

[Leaderboard](leaderboard.md) | [Benchmark README](README.md) | [Saved Results](context_evaluation/heldout/results/)

## Cases

| Case | Candidates | Budget | Expected Answer | Failure Mode |
|---|---:|---:|---|---|
| [`analytics_derived_metric_cycle`](#analytics_derived_metric_cycle) | 8 | 3 | 612 accounts | Circular derived-data lineage |
| [`analytics_incomplete_lineage`](#analytics_incomplete_lineage) | 9 | 3 | 487 parcels | Incomplete transformation lineage |
| [`analytics_metric_definition_conflict`](#analytics_metric_definition_conflict) | 8 | 3 | 92% | Conflicting metric definitions |
| [`analytics_stale_dashboard`](#analytics_stale_dashboard) | 8 | 3 | 1,284 seats | Stale dashboard snapshot |

Each case uses a fixed candidate pool, source-level relevance labels, and a selection budget of three sources.

## Evaluation Setup

BGE Reranker v2-m3 and Cohere Rerank v4.0 Pro provide the initial ranking. Each configuration then uses either a frontier LLM judge or Omneum for context selection.

Claude Sonnet 5.5 is held fixed as the downstream answer generator.

| Configuration | Trials per Case |
|---|---:|
| BGE + Claude Sonnet 5.5 Judge | 1 |
| BGE + GPT-6 Astra Judge | 10 |
| BGE + Gemini 3.8 Flash Judge | 10 |
| BGE + Omneum | 10 |
| Cohere + Claude Sonnet 5.5 Judge | 1 |
| Cohere + Omneum | 1 |

BGE + Omneum results use the paired GPT-6 Astra run. The BGE + Claude and Cohere comparisons contain one trial per case.

Selection precision and recall are computed against frozen source-level relevance labels. Latency is measured in seconds, with repeated-run latency reported as p50.

## Results

**BGE + Omneum achieved 100% selection precision across all four Data Analytics cases, matched the evaluated frontier LLM judges' selection precision and recall, and produced correctly scored downstream answers in all 40 recorded trials.**

Its median selection latency ranged from 0.649s to 0.708s, compared with 2.433–3.612s for GPT-6 Astra and 2.076–3.643s for Gemini.

### BGE Reranker v2-m3

| Case | Selector | Precision | Recall | Correct Answers | Selection p50 | E2E p50 |
|---|---|---:|---:|---:|---:|---:|
| Derived metric cycle | Claude Judge | 100% | 100% | 1/1 | 2.008s | 3.624s |
| | GPT-6 Judge | 100% | 100% | 10/10 | 3.165s | 4.979s |
| | Gemini Judge | 100% | 100% | 10/10 | 2.859s | 5.005s |
| | **Omneum** | **100%** | **100%** | **10/10** | **0.694s** | **2.567s** |
| Incomplete lineage | Claude Judge | 100% | 75% | 1/1 | 1.987s | 4.240s |
| | GPT-6 Judge | 100% | 75% | 10/10 | 2.657s | 4.745s |
| | Gemini Judge | 100% | 75% | 10/10 | 2.076s | 4.240s |
| | **Omneum** | **100%** | **75%** | **10/10** | **0.708s** | **2.855s** |
| Metric definition conflict | Claude Judge | 100% | 100% | 1/1 | 1.651s | 3.776s |
| | GPT-6 Judge | 100% | 100% | 10/10 | 2.433s | 4.772s |
| | Gemini Judge | 100% | 100% | 10/10 | 2.582s | 5.117s |
| | **Omneum** | **100%** | **100%** | **10/10** | **0.649s** | **2.919s** |
| Stale dashboard | Claude Judge | 100% | 60% | 1/1 | 1.991s | 4.753s |
| | GPT-6 Judge | 100% | 60% | 10/10 | 3.612s | 5.964s |
| | Gemini Judge | 100% | 60% | 10/10 | 3.643s | 5.955s |
| | **Omneum** | **100%** | **60%** | **10/10** | **0.662s** | **3.106s** |

BGE + Omneum matched the LLM judges' source-level precision and recall in every case. All configurations generated correct answers, with Omneum recording the lowest median selection and end-to-end latency in each repeated GPT-6 Astra and Gemini comparison.

### Cohere Rerank v4.0 Pro

| Case | Selector | Precision | Recall | Correct Answers | Selection | E2E |
|---|---|---:|---:|---:|---:|---:|
| Derived metric cycle | Claude Judge | 66.7% | 66.7% | 1/1 | 2.477s | 4.267s |
| | **Omneum** | **66.7%** | **66.7%** | **1/1** | **2.151s** | 4.357s |
| Incomplete lineage | Claude Judge | 100% | 75% | 1/1 | 1.832s | 3.642s |
| | **Omneum** | **100%** | **75%** | **1/1** | **0.721s** | **2.637s** |
| Metric definition conflict | Claude Judge | 100% | 100% | 1/1 | 10.041s | 11.906s |
| | Omneum | 66.7% | 66.7% | 1/1 | **8.822s** | **11.305s** |
| Stale dashboard | Claude Judge | 100% | 60% | 1/1 | 2.145s | 4.369s |
| | **Omneum** | **100%** | **60%** | **1/1** | **0.579s** | **2.722s** |

Cohere + Omneum matched the Claude judge's selection precision and recall in three of four cases, with lower selection latency in all four.

In `analytics_metric_definition_conflict`, Cohere + Omneum selected `data_catalog` instead of `warehouse_query`, reducing source-level precision and recall to 66.7%. Both configurations nevertheless generated the correct answer.

All eight Cohere downstream answers were correctly scored.

## Case Details

### 1. Derived Metric Cycle

`analytics_derived_metric_cycle`

**Question:** What is Solis daily active accounts for August 17, using distinct production account IDs with at least one session?

**Expected answer:** `612`

#### Fixture

```text
8 candidates
3 selected
3 relevant
```

The derived table reports 840 daily active accounts. Its dashboard exports the same value to CSV, which is reimported during nightly repair.

The resulting dependency chain contains a cycle:

```text
derived_table
     |
     v
dashboard
     |
     v
csv_export
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

#### Recorded Selections

| Configuration | Selected Sources | Precision | Recall |
|---|---|---:|---:|
| BGE + Claude Judge | `source_table`, `query_result`, `source_table_2` | 100% | 100% |
| BGE + GPT-6 Judge | `source_table`, `query_result`, `source_table_2` | 100% | 100% |
| BGE + Gemini Judge | `source_table_2`, `source_table`, `query_result` | 100% | 100% |
| **BGE + Omneum** | `source_table_2`, `source_table`, `query_result` | **100%** | **100%** |
| Cohere + Claude Judge | `metric_store`, `source_table`, `query_result` | 66.7% | 66.7% |
| Cohere + Omneum | `metric_store`, `query_result`, `source_table` | 66.7% | 66.7% |

#### Comparative Analysis

BGE + Omneum selected all three labeled positive sources:

```text
source_table_2
source_table
query_result
```

These selections exclude the circularly dependent derived table, dashboard, and CSV export.

Every BGE configuration achieved 100% precision and recall, and all downstream answers returned 612.

Both Cohere configurations included `metric_store`, which is outside the three labeled positive count sources. Their precision and recall were therefore 66.7%.

**Result:** BGE + Omneum matched the frontier LLM judges' perfect selection precision, recall, and downstream answer correctness. Its 0.694-second selection p50 was approximately 4.6× lower than GPT-6 Astra and 4.3× lower than Gemini.

### 2. Incomplete Lineage

`analytics_incomplete_lineage`

**Question:** How many delivered parcels belong to the Noria August 16 dispatch cohort, excluding returned parcels?

**Expected answer:** `487`

#### Fixture

```text
9 candidates
3 selected
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

#### Recorded Selections

| Configuration | Selected Sources | Precision | Recall |
|---|---|---:|---:|
| BGE + Claude Judge | `source_table`, `source_table_2`, `query_result` | 100% | 75% |
| BGE + GPT-6 Judge | `source_table`, `source_table_2`, `query_result` | 100% | 75% |
| BGE + Gemini Judge | `source_table`, `source_table_2`, `query_result` (8/10); `source_table`, `source_table_2`, `metric_store` (2/10) | 100% | 75% |
| **BGE + Omneum** | `source_table`, `source_table_2`, `metric_store` | **100%** | **75%** |
| Cohere + Claude Judge | `source_table`, `query_result`, `source_table_2` | 100% | 75% |
| Cohere + Omneum | `source_table`, `query_result`, `source_table_2` | 100% | 75% |

#### Comparative Analysis

BGE + Omneum selected:

```text
source_table
source_table_2
metric_store
```

The selection combines dispatch records, carrier evidence, and the metric definition rather than relying on the migrated transformation or its downstream exports.

The LLM judges selected `query_result` instead of `metric_store`.

Both source sets contain three of the four labeled positive sources.

All configurations achieved:

```text
Precision: 100%
Recall:     75%
```

Every downstream answer returned 487.

**Result:** Omneum matched the frontier LLM judges' selection precision, recall, and downstream answer correctness. Its 0.708-second selection p50 was approximately 3.8× lower than GPT-6 Astra and 3.1× lower than Gemini.

The case demonstrates successful selection of current source evidence when transformation lineage is incomplete.

### 3. Metric Definition Conflict

`analytics_metric_definition_conflict`

**Question:** What is Atlas July gross revenue retention under the finance definition excluding expansion?

**Expected answer:** `92%`

#### Fixture

```text
8 candidates
3 selected
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

The two definitions can be represented as:

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

#### Recorded Selections

| Configuration | Selected Sources | Precision | Recall |
|---|---|---:|---:|
| BGE + Claude Judge | `finance_report`, `metric_docs`, `warehouse_query` | 100% | 100% |
| BGE + GPT-6 Judge | `finance_report`, `metric_docs`, `warehouse_query` | 100% | 100% |
| BGE + Gemini Judge | `finance_report`, `metric_docs`, `warehouse_query` | 100% | 100% |
| **BGE + Omneum** | `finance_report`, `metric_docs`, `warehouse_query` | **100%** | **100%** |
| Cohere + Claude Judge | `metric_docs`, `finance_report`, `warehouse_query` | 100% | 100% |
| Cohere + Omneum | `metric_docs`, `finance_report`, `data_catalog` | 66.7% | 66.7% |

#### Comparative Analysis

All BGE configurations selected the same three labeled positive sources:

```text
finance_report
metric_docs
warehouse_query
```

The source set includes the finance definition, its documentation, and the warehouse query supporting the expected result.

BGE + Omneum matched all three frontier LLM judges at 100% precision and recall.

The Cohere + Omneum configuration selected:

```text
metric_docs
finance_report
data_catalog
```

The `data_catalog` source is not one of the three labeled positive sources, reducing precision and recall to 66.7%. Cohere + Claude selected `warehouse_query` instead and achieved 100%.

Both Cohere configurations nevertheless generated the correct downstream answer.

**Result:** BGE + Omneum achieved perfect selection precision and recall and generated 92% in all ten recorded trials. Its 0.649-second selection p50 was approximately 3.7× lower than GPT-6 Astra and 3.9× lower than Gemini.

### 4. Stale Dashboard

`analytics_stale_dashboard`

**Question:** What is Meridian's finalized July 2026 paid-seat count after the August 12 backfill?

**Expected answer:** `1,284`

#### Fixture

```text
8 candidates
3 selected
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

#### Recorded Selections

| Configuration | Selected Sources | Precision | Recall |
|---|---|---:|---:|
| BGE + Claude Judge | `metric_store`, `api_result`, `current_query` | 100% | 60% |
| BGE + GPT-6 Judge | `warehouse_table`, `api_result`, `metric_store` | 100% | 60% |
| BGE + Gemini Judge | `warehouse_table`, `api_result`, `metric_store` | 100% | 60% |
| **BGE + Omneum** | `warehouse_table`, `api_result`, `metric_store` | **100%** | **60%** |
| Cohere + Claude Judge | `metric_store`, `api_result`, `current_query` | 100% | 60% |
| Cohere + Omneum | `metric_store`, `warehouse_table`, `api_result` | 100% | 60% |

#### Comparative Analysis

BGE + Omneum selected:

```text
warehouse_table
api_result
metric_store
```

These sources reflect the finalized post-backfill metric rather than the stale dashboard snapshot.

GPT-6 Astra and Gemini selected the same three sources.

Claude selected `current_query` instead of `warehouse_table`. Both selections contain three of the five labeled positive sources.

All configurations achieved:

```text
Precision: 100%
Recall:     60%
```

Every downstream answer returned 1,284.

**Result:** Omneum matched the frontier LLM judges' selection quality and downstream answer correctness. Its 0.662-second selection p50 was approximately 5.5× lower than GPT-6 Astra and 5.9× lower than Gemini.

## Artifacts

### Case Fixtures

The four frozen analytics cases are located under:

```text
benchmarks/context_evaluation/heldout/cases/
├── analytics_derived_metric_cycle/
├── analytics_incomplete_lineage/
├── analytics_metric_definition_conflict/
└── analytics_stale_dashboard/
```

List the fixture contents from the repository root:

```bash
find benchmarks/context_evaluation/heldout/cases \
  -maxdepth 2 -path '*analytics_*' -print
```

Each case defines a fixed candidate pool and expected evaluation outcome.

### Recorded Results

```text
benchmarks/context_evaluation/heldout/results/
├── bge-claude-vs-bge-omneum-20261008/
├── bge-openai-vs-bge-omneum-20261008/
├── bge-google-low-vs-bge-omneum-20261008/
└── cohere-claude-vs-cohere-omneum-20261008/
```

Each results directory contains `results.jsonl`.

Inspect the BGE + GPT-6 Astra / BGE + Omneum paired run:

```bash
ls benchmarks/context_evaluation/heldout/results/bge-openai-vs-bge-omneum-20261008/
```

Find the analytics records:

```bash
rg -n \
  'analytics_derived_metric_cycle|analytics_incomplete_lineage|analytics_metric_definition_conflict|analytics_stale_dashboard' \
  benchmarks/context_evaluation/heldout/results/bge-openai-vs-bge-omneum-20261008/results.jsonl
```

Inspect the corresponding Gemini paired run:

```bash
rg -n 'analytics_' \
  benchmarks/context_evaluation/heldout/results/bge-google-low-vs-bge-omneum-20261008/results.jsonl
```

Inspect the Cohere comparison:

```bash
rg -n 'analytics_' \
  benchmarks/context_evaluation/heldout/results/cohere-claude-vs-cohere-omneum-20261008/results.jsonl
```

These commands inspect preserved benchmark artifacts without rerunning provider inference.

## Evaluation Notes

| Setting | Value |
|---|---|
| Cases | 4 |
| Candidate sources | 33 total |
| Candidate pools | 8–9 sources per case |
| Selection budget | 3 sources |
| Generator | Claude Sonnet 5.5 |
| Initial rerankers | BGE Reranker v2-m3, Cohere Rerank v4.0 Pro |
| Frontier judges | Claude Sonnet 5.5, GPT-6 Astra, Gemini 3.8 Flash |
| BGE + GPT-6 / Gemini | 10 trials per case |
| BGE + Omneum | 10 trials per case in each paired run |
| Claude / Cohere comparisons | 1 trial per case |
| Selection scoring | Frozen source-level relevance labels |
| Latency aggregation | Median across recorded attempts |

### Measurement Constraints

The benchmark contains four fixed synthetic analytics cases.

Repeated trials measure execution variability on identical inputs, not generalization across additional questions.

Precision measures the proportion of selected sources labeled relevant. Recall measures the proportion of all labeled relevant sources selected within the selection budget.

The downstream correctness measure records whether generated answers satisfy the fixture's expected-answer check. It does not independently establish general factual correctness beyond those checks.

The benchmark uses a fixed Claude Sonnet 5.5 answer generator, allowing the measured downstream differences to be evaluated with the same generator configuration.

The recorded comparisons establish selection behavior and timing for these fixtures. They do not establish universal performance across arbitrary analytics workloads.

## Summary

Across all four Data Analytics cases, **BGE + Omneum matched the frontier LLM judges' selection precision, recall, and downstream answer correctness while recording substantially lower selection latency**.

The results include:

- **Derived metric cycle:** 100% precision and recall, correct answers in all ten trials, and 0.694-second selection p50.
- **Incomplete lineage:** 100% precision, 75% recall, correct answers in all ten trials, and 0.708-second selection p50.
- **Metric definition conflict:** 100% precision and recall, correct answers in all ten trials, and 0.649-second selection p50.
- **Stale dashboard:** 100% precision, 60% recall, correct answers in all ten trials, and 0.662-second selection p50.

Omneum selected the relevant warehouse, operational, and metric-definition evidence in all four BGE configurations, including cases involving circular reporting dependencies, missing transformation lineage, inconsistent metric definitions, and stale dashboard data.

Cohere + Omneum also produced correctly scored downstream answers in all four single-trial cases and matched the Claude judge's selection metrics in three of four cases.

The Data Analytics results contribute to the full 24-case benchmark comparing Omneum with standalone semantic rerankers and frontier LLM judges. See the [leaderboard](leaderboard.md) for aggregate selection precision, recall, answer accuracy, latency, token usage, and cost.