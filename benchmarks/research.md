# Research & Analysis Agents

Research-agent evaluation for the Omneum Cross-Domain Context Curation Benchmark.

Four synthetic cases test context selection for independent agreement, conflicting measurements, false consensus, and syndicated reporting.

**4 cases · 31 candidate passages · 6 Qwen-token budgets · 13 budgeted configurations**

[Leaderboard](leaderboard.md) | [Benchmark README](README.md) | [Dataset](context_selection/synthetic/DATASET.md) | [Saved Results](context_selection/synthetic/results/)

## Quick Start

Run from the Omneum repository root.

```bash
# Install locked benchmark dependencies
uv sync --locked --group benchmarks

# Run offline benchmark tests
uv run --locked --group benchmarks python \
  tools/run_context_evaluation_tests.py -q -p no:cacheprovider

# Inspect the final benchmark results
cat \
  benchmarks/context_selection/synthetic/results/budget-exhaustion-recovery-20261026-v2/report.md
```

The offline tests cover benchmark contracts, metric calculations, and local integration. Published metrics are derived from saved selections and timing records. Inspecting the results requires no additional provider calls.

For the evaluation configuration and reproduction instructions, see [Benchmark README](README.md).

## Benchmark Overview

Research agents encounter several forms of evidence agreement:

- Independent observations supporting the same conclusion.
- Reports measuring different quantities despite using similar terminology.
- Independent researchers reaching the same incorrect conclusion.
- Multiple publications repeating information from one original report.

Omneum's provenance-aware graph inference iteratively computes source reliability and claim support, accounting for shared evidence origins and dependencies between sources. The SDK maps claim support to retrieved chunks and uses question relevance and incremental claim coverage to select and reconstruct original passages within the token budget.

The benchmark compares production `prepare_context()` with BM25, MiniLM, BGE Reranker v2-m3, Cohere Rerank v4.0 Pro, and frontier LLM selection judges: Claude Sonnet 5.5, GPT-6 Astra, and Gemini 3.8 Flash.

The evaluated output is the reconstructed context supplied to a consuming model. This benchmark does not execute downstream answer generation.

### Cases

| Case | Candidates | Token Budgets | Evaluation objective |
|---|---:|---|---|
| [`research_clean_consensus`](#research_clean_consensus) | 7 | 64–256 | Select evidence from sources with different provenance relationships |
| [`research_conflicting_reports`](#research_conflicting_reports) | 8 | 64–256 | Distinguish net forest-cover change from gross additions |
| [`research_independent_false_consensus`](#research_independent_false_consensus) | 7 | 64–256 | Distinguish independently repeated measurement errors from census evidence |
| [`research_syndicated_reporting`](#research_syndicated_reporting) | 9 | 64–256 | Evaluate repeated reporting from a shared information origin |

Each case uses a fixed candidate pool with supporting-source annotations, canonical claims, and provenance metadata.

The six selection budgets are **64, 96, 128, 160, 192, and 256 Qwen tokens**. Budget feasibility is calculated against the reconstructed original passages.

## Recorded Results

Final Research & Analysis results, averaged across four cases and six token budgets:

| Configuration | Precision ↑ | Recall ↑ | Evidence ↑ | Claims ↑ | Origins ↑ | Qwen Tokens ↓ |
|---|---:|---:|---:|---:|---:|---:|
| Omneum Standalone | 77.27% | **57.00%** | **59.52%** | **81.04%** | 79.51% | 129.00 |
| BM25 + Omneum | 76.60% | 53.08% | 54.32% | **81.81%** | **81.25%** | 119.75 |
| MiniLM + Omneum | 67.99% | 45.44% | 48.90% | 76.81% | 60.76% | **115.33** |
| BGE + Omneum | 69.79% | 46.55% | 48.56% | 73.33% | 62.85% | 119.08 |
| Cohere + Omneum | **79.31%** | 51.69% | 55.25% | 78.89% | 71.88% | 118.21 |

Cohere + Omneum achieved the highest selection precision among the five Omneum configurations at **79.31%**. Standalone Omneum retained the most annotated evidence at **59.52%**, with **57.00% recall**.

BM25 + Omneum achieved the highest claim coverage (**81.81%**) and origin coverage (**81.25%**). MiniLM + Omneum produced the smallest mean reconstructed context at **115.33 Qwen tokens**.

The four hybrid configurations differ in their relevance inputs. All four execute production `prepare_context()` with the same provenance-aware graph inference and token-budgeted context selection.

### Selection Latency

Local selection begins after relevance scores and structured observations are available.

The final aggregate Omneum timings across all six domains are:

| Configuration | Local Selection p50 ↓ | Local Selection p95 ↓ |
|---|---:|---:|
| Omneum Standalone | 194.86ms | 451.87ms |
| BM25 + Omneum | 207.79ms | 461.25ms |
| MiniLM + Omneum | 203.84ms | 465.36ms |
| BGE + Omneum | 200.63ms | 430.51ms |
| Cohere + Omneum | 206.89ms | 480.37ms |

These measurements cover graph evaluation, candidate discovery, token-budgeted selection, reconstruction, and SDK verification. External ranking inference and structured observation extraction are outside the measured interval.

The table reports **all-domain latency**, not Research & Analysis-specific percentiles.

See [Selection Latency](leaderboard.md#selection-latency) for the timing contract and [Saved Results](#inspect-recorded-runs) for the execution artifacts.

## `research_clean_consensus`

**Task:** Determine when the Eastbank pedestrian bridge opened to the public.

```text
On what date did the Eastbank pedestrian bridge
open to the public?
```

### Fixture

```text
7 candidates
7 relevant

primary_record       Municipal opening certificate
report               Accessibility group field observation
report_2             Local newspaper on-site reporting
dataset              Municipal asset register
filing               Completion filing
analysis             Mobility study
publication          Walking guide
```

The bridge opened on **June 14, 2026, at 09:00**.

Every candidate reports the correct date, but the sources differ in provenance and independence.

```text
Municipal Opening Certificate
       |
       +----> Asset Register
       |
       +----> Completion Filing

Local Newspaper
       |
       +----> Walking Guide

Accessibility Group: Independent Field Observation
Mobility Study: Independent Study
```

The municipal asset register and completion filing reference the primary opening certificate. The walking guide cites the newspaper.

The accessibility group and newspaper independently observed the opening.

Primary record:

```text
Asset: Eastbank Pedestrian Bridge
Event: Opened to the public
Date: 2026-06-14
Time: 09:00
```

All seven sources are annotated as relevant. Selection precision therefore does not distinguish evidence drawn from independent observations from evidence derived from the same original record.

**Reference answer:** June 14, 2026.

### Recorded Selections

The benchmark evaluates the seven passages at six token budgets. All seven are supporting sources, so selection precision is 100% for any nonempty selection drawn exclusively from this pool.

The available source annotations are:

| Source | Evidence | Provenance |
|---|---|---|
| `primary_record` | Municipal opening certificate | Primary municipal record |
| `report` | Accessibility group field observation | Independent observation |
| `report_2` | Newspaper on-site reporting | Independent reporting |
| `dataset` | Municipal asset register | References opening certificate |
| `filing` | Completion filing | References opening certificate |
| `analysis` | Mobility study | Independent study |
| `publication` | Walking guide | Cites newspaper |

The final benchmark artifacts record the actual selected source IDs and reconstructed passages for each configuration and budget.

### Comparative Analysis

The case separates source relevance from provenance composition.

A selection containing:

```text
primary_record
dataset
filing
```

retains three relevant passages, but the asset register and completion filing reference the same primary record.

A selection containing:

```text
primary_record
report
report_2
```

also retains three relevant passages, with evidence from separate observation and reporting origins.

Both selections have identical source precision and recall under the fixture's relevance labels.

Omneum's provenance-aware graph inference accounts for shared evidence origins and dependencies between sources when computing source reliability and claim support. The benchmark's origin-coverage metric evaluates retention of annotated root-origin units.

**Result:** The case tests whether budgeted selection retains evidence from distinct reporting origins when all candidate passages support the same answer.

The reported selection metrics measure selected source IDs, retained evidence spans, claim coverage, and origin coverage. They do not directly establish the accuracy of individual dependency estimates.

## `research_conflicting_reports`

**Task:** Determine the 2025 net forest-cover change in the Maren district.

```text
What was the 2025 net forest-cover change in the
Maren district, using the district boundary and
accounting for both gains and losses?
```

### Fixture

```text
8 candidates
5 relevant

report               Canopy Watch: +120 ha
report_2             Land Review: -60 ha
primary_publication  Land office publication: -60 ha
dataset              District raster summary: -60 ha
news_article         Repeats Canopy Watch: +120 ha
analysis             Spatial analysis: -60 ha
filing               Land office annex: -60 ha
web_page             Regional gross additions: +120 ha
```

The district gained 120 hectares of forest and lost 180 hectares during 2025.

```python
forest_gained_ha = 120
forest_lost_ha = 180

net_change_ha = forest_gained_ha - forest_lost_ha

assert net_change_ha == -60
```

The correct net change is **−60 hectares**.

The conflicting +120-hectare reports measure gross additions or omit losses.

The relevant sources are:

```text
report_2
primary_publication
dataset
analysis
filing
```

**Reference answer:** −60 hectares.

### Recorded Selections

The candidate pool contains five annotated supporting sources.

| Source | Evidence | Relevance |
|---|---|---|
| `report` | Gross forest additions: +120 ha | Not supporting |
| `report_2` | Net forest-cover change: −60 ha | Supporting |
| `primary_publication` | Land office net-change publication | Supporting |
| `dataset` | District raster summary | Supporting |
| `news_article` | Repeats gross-additions figure | Not supporting |
| `analysis` | Spatial analysis of gains and losses | Supporting |
| `filing` | Land office annex | Supporting |
| `web_page` | Regional gross additions | Not supporting |

The saved benchmark records contain selections for each method and token budget. The evaluation scores retention of the five supporting sources and their annotated evidence.

### Comparative Analysis

The fixture distinguishes two measurements:

```text
Gross additions: +120 hectares
Gross losses:    -180 hectares
Net change:       -60 hectares
```

The +120-hectare value is a valid gross-additions figure but does not answer the net-change question.

The supporting sources describe the district's net forest-cover change, including the effects of losses.

Selection quality depends on retaining passages that address the requested measurement. Source agreement alone does not resolve whether a passage reports gross additions or net change.

**Result:** The case measures selection of net-change evidence from a pool containing related but incompatible quantities.

The final benchmark evaluation scores selected source IDs and evidence retention. Downstream answer correctness is outside this benchmark.

## `research_independent_false_consensus`

**Task:** Determine the number of occupied homes in the North Quay pilot.

```text
How many occupied homes were in the North Quay pilot
at the August 2026 census, excluding vacant units?
```

### Fixture

```text
7 candidates
3 relevant

report               Site-map count: 240
publication          Facade survey: 240
analysis             Parcel-footprint count: 240
dataset              Census microdata: 216
news_article         Door-number count: 240
primary_record       Signed census enumeration: 216
web_page             Census summary: 216
```

North Quay contains 240 residential units, of which 24 were vacant.

```python
residential_units = 240
vacant_units = 24

occupied_homes = residential_units - vacant_units

assert occupied_homes == 216
```

The correct answer is **216 occupied homes**.

Four independently produced sources instead report 240:

```text
Urban Metrics
   └── Counts residential units from a site map

Housing Review
   └── Estimates occupancy from building facades

Property Lab
   └── Counts parcel footprints

Newspaper
   └── Counts door numbers
```

These sources use different methods but share the same measurement problem: none establishes actual occupancy.

The relevant sources are:

```text
dataset
primary_record
web_page
```

**Reference answer:** 216 occupied homes.

### Recorded Selections

The candidate pool contains three census-based supporting sources and four independently produced reports using incorrect occupancy measurements.

| Source | Reported Value | Relevance |
|---|---:|---|
| `report` | 240 | Not supporting |
| `publication` | 240 | Not supporting |
| `analysis` | 240 | Not supporting |
| `dataset` | 216 | Supporting |
| `news_article` | 240 | Not supporting |
| `primary_record` | 216 | Supporting |
| `web_page` | 216 | Supporting |

The final benchmark results record which passages each selector retains at each token budget.

### Comparative Analysis

This case distinguishes structural independence from semantic measurement validity.

The four incorrect sources use different observation methods:

```text
Site-map count
Facade survey
Parcel-footprint count
Door-number count
```

Their agreement on 240 does not establish that 240 homes were occupied. The methods count or estimate residential units without verifying the vacancy adjustment.

The census evidence establishes:

```text
Residential units: 240
Vacant units:       24
Occupied homes:    216
```

Source independence can identify whether multiple observations share an information origin. It cannot, by itself, establish that independently produced measurements answer the user's question.

Omneum's `prepare_context()` uses source reliability and claim support from provenance-aware graph inference alongside question relevance and incremental claim coverage to select retrieved passages. The benchmark evaluates those selections against the annotated census evidence.

**Result:** Independent support is insufficient when multiple sources measure the wrong quantity.

The case provides a concrete test of task-specific evidence selection. The domain aggregate metrics do not isolate this case's final source precision, recall, or evidence retention; those values remain in the saved case-budget records.

## `research_syndicated_reporting`

**Task:** Determine how many battery-electric buses Riverton had accepted into passenger service.

```text
As of August 18, how many battery-electric buses had
Riverton accepted into passenger service under its 2026 order?
```

### Fixture

```text
9 candidates
4 relevant

original_report      Transit Market Report: 60
news_article         Metro News: 60
news_article_2       Regional Daily: 60
news_article_3       Transport Today: 60
primary_record       Municipal acceptance register: 36
independent_report   Depot inspection: 36
filing               Capital filing: 36
web_page             City mobility page: 60
dataset              Fleet acceptance export: 36
```

Riverton ordered 60 battery-electric buses, but only **36 had been accepted into passenger service** as of August 18.

The original Transit Market Report incorrectly treats the ordered quantity as the accepted quantity.

That error propagates through several publications:

```text
Transit Market Report (60)
       |
       +--> Metro News (60)
       |       |
       |       +--> Regional Daily (60)
       |       |
       |       +--> City Mobility Page (60)
       |
       +--> Transport Today (60)
```

The correct evidence comes from operational acceptance records.

```text
Order quantity:         60
Accepted into service:  36
Awaiting acceptance:    24
```

The four relevant sources are:

```text
primary_record
independent_report
filing
dataset
```

**Reference answer:** 36 buses.

### Recorded Selections

The fixture contains four supporting operational sources and five sources reporting the ordered quantity as the accepted quantity.

| Source | Reported Value | Relevance |
|---|---:|---|
| `original_report` | 60 | Not supporting |
| `news_article` | 60 | Not supporting |
| `news_article_2` | 60 | Not supporting |
| `news_article_3` | 60 | Not supporting |
| `primary_record` | 36 | Supporting |
| `independent_report` | 36 | Supporting |
| `filing` | 36 | Supporting |
| `web_page` | 60 | Not supporting |
| `dataset` | 36 | Supporting |

The final benchmark evaluation records selected passages at six token budgets for each configuration.

### Comparative Analysis

This case tests repeated reporting from a shared information origin.

The Transit Market Report supplies the incorrect 60-bus figure. Several subsequent publications repeat that figure, creating apparent agreement across multiple sources.

```text
Original report: 60
   |
   +--> News derivative: 60
   +--> Regional derivative: 60
   +--> Transport derivative: 60
```

The operational acceptance evidence instead establishes:

```text
Municipal acceptance register: 36
Depot inspection:              36
Capital filing:                36
Fleet acceptance export:       36
```

Omneum's provenance-aware graph inference accounts for shared evidence origins and dependencies between sources when computing source reliability and claim support. Repeated reports sharing an upstream origin therefore contribute differently from independent supporting sources when the corresponding dependency signals are available.

The benchmark evaluates the selected passages against the four annotated supporting sources.

**Result:** The case measures whether Omneum's provenance-aware graph inference and relevance-based context selection retain operational acceptance evidence despite repeated reporting of the incorrect ordered quantity.

A high selection score requires retaining the 36-bus evidence. The presence of dependency metadata alone does not establish that the selector eliminated the syndicated error.

## Inspect Recorded Runs

Authoritative benchmark execution artifacts:

```text
benchmarks/context_selection/synthetic/
├── results/
│   ├── tier1-production-20261025-v1/
│   ├── tier1-competitors-20261025-v1/
│   └── budget-exhaustion-recovery-20261026-v2/
└── analysis/
    └── tier1-competitive-analysis-20261026-v1/
```

The published evaluation uses the final Omneum hybrid selections and the preserved competitor measurements.

### Inspect Research Case Records

Inspect the final evaluation:

```bash
cat \
  benchmarks/context_selection/synthetic/results/budget-exhaustion-recovery-20261026-v2/report.md
```

Find the four research case IDs in the saved artifacts:

```bash
rg -n \
  'research_clean_consensus|research_conflicting_reports|research_independent_false_consensus|research_syndicated_reporting' \
  benchmarks/context_selection/synthetic/results/budget-exhaustion-recovery-20261026-v2/
```

The search identifies case-specific records in the final result directory.

To inspect the complete source selections, use the corresponding saved selection artifact identified by the result manifest. Each record is associated with its method, case, and token budget.

### Inspect All Recorded Comparisons

```bash
# Final paired comparisons
head -n 20 \
  benchmarks/context_selection/synthetic/results/budget-exhaustion-recovery-20261026-v2/paired_comparisons.csv

# Case-level comparisons
head -n 20 \
  benchmarks/context_selection/synthetic/results/budget-exhaustion-recovery-20261026-v2/paired_cases.csv

# Case-budget comparisons
head -n 20 \
  benchmarks/context_selection/synthetic/results/budget-exhaustion-recovery-20261026-v2/paired_case_budget.csv

# Domain-budget comparisons
head -n 20 \
  benchmarks/context_selection/synthetic/results/budget-exhaustion-recovery-20261026-v2/paired_domain_budget.csv
```

These files contain paired measurements for the final hybrid selectors and their recorded comparison configurations.

### Inspect the Published Results

```bash
# Final evaluation report
cat \
  benchmarks/context_selection/synthetic/results/budget-exhaustion-recovery-20261026-v2/report.md

# Competitive analysis
cat \
  benchmarks/context_selection/synthetic/analysis/tier1-competitive-analysis-20261026-v1/report.md

# Analysis validation
python -m json.tool \
  benchmarks/context_selection/synthetic/results/budget-exhaustion-recovery-20261026-v2/analysis_validation.json
```

The analysis uses saved source selections, reconstructed contexts, timing records, and metric inputs. Recomputing the published comparisons does not require new provider calls.

## Evaluation Notes

| Setting | Value |
|---|---|
| Cases | 4 |
| Candidate passages | 31 total |
| Candidate pools | 7–9 passages per case |
| Selection budgets | 64, 96, 128, 160, 192, 256 Qwen tokens |
| Tokenizer | Qwen2.5 7B GGUF |
| Budgeted configurations | 13 |
| Unbudgeted reference | `raw_full` |
| Retrieval and rerankers | BM25, MiniLM, BGE Reranker v2-m3, Cohere Rerank v4.0 Pro |
| LLM judges | Claude Sonnet 5.5, GPT-6 Astra, Gemini 3.8 Flash |
| Omneum entry point | `prepare_context()` |
| Selection objective | `coverage_support_density` |
| Complementary evidence | `complementary_evidence=True` |
| Token cost exponent | `token_cost_exponent=1` |
| Discovery anchors | 3 plus relevance-score ties |
| Discovery expansion | Depth 2 |
| Deferred candidate recovery | Enabled |
| Conflict-aware selection | `conflict_aware=False` |
| Selection scoring | Annotated supporting-source IDs |
| Evidence scoring | Retained gold evidence spans |
| Claim scoring | Canonical claims represented in supporting passages |
| Origin scoring | Annotated root-origin units |
| Latency aggregation | Local selection p50 and p95 |

The final hybrid implementation evaluates deferred candidates after the initial discovery neighborhood exhausts positive, budget-feasible utility. Additional passages must meet the recorded marginal utility-density threshold and fit within the remaining token budget.

The Research & Analysis domain showed relatively small completeness gains from this recovery. Cohere + Omneum's aggregate results were unchanged.

### Downstream Answer Results

The benchmark evaluates context selection without running a downstream answer generator.

The benchmark records:

| Measurement | Included |
|---|---|
| Selection precision | Yes |
| Selection recall | Yes |
| Evidence retention | Yes |
| Claim coverage | Yes |
| Origin coverage | Yes |
| Reconstructed-context token count | Yes |
| Local selection latency | Yes |
| Downstream answer correctness | No |

Selection precision and recall measure fixture relevance. Origin coverage measures retention of annotated root-origin units. These metrics do not directly measure dependency-estimation accuracy.

## Interpretation

The Research & Analysis results establish four findings.

**1. Cohere + Omneum achieves the highest precision among the Omneum configurations.**

Cohere + Omneum recorded **79.31% precision** across the four cases and six budgets. Standalone Omneum recorded **77.27%**, BM25 + Omneum **76.60%**, BGE + Omneum **69.79%**, and MiniLM + Omneum **67.99%**.

**2. Standalone Omneum retains more annotated research evidence.**

Standalone Omneum achieved **59.52% evidence retention** and **57.00% recall**. Cohere + Omneum retained **55.25%** of evidence, and BM25 + Omneum retained **54.32%**.

The hybrid configurations used smaller reconstructed contexts, with mean Qwen-token counts between **115.33** and **119.75**, compared with **129.00** for standalone Omneum.

**3. Research evidence quality depends on the quantity being measured.**

The independent-false-consensus fixture contains independently produced sources that agree on 240 residential units. The requested quantity is occupied homes, established by the census evidence as 216.

Structural independence does not resolve this measurement mismatch by itself. Question relevance and claim coverage remain necessary to select passages addressing the requested quantity.

**4. Shared reporting origins remain a distinct evaluation target.**

The syndicated-reporting fixture contains multiple publications repeating an incorrect 60-bus acceptance figure from one original report. The supporting operational records establish 36 accepted buses.

Omneum's provenance-aware graph inference accounts for shared evidence origins and dependencies between sources when computing source reliability and claim support. The final selection metrics measure whether the corresponding operational evidence survives the token budget.

### Overall Result

Across the Research & Analysis cases, **Cohere + Omneum achieved 79.31% selection precision**, while **standalone Omneum retained the most annotated evidence at 59.52%**.

The results reflect different tradeoffs between selection precision, evidence retention, and reconstructed-context size. The final recovery produced limited additional completeness in this domain.

The benchmark uses fixed synthetic candidate pools with supplied structured `Observation` objects. It evaluates context selection and reconstruction, without downstream answer generation or live retrieval across research repositories.

For the complete evaluation methodology and aggregate comparisons, see [Benchmark README](README.md) and [Leaderboard](leaderboard.md).