
# Research & Analysis Agents

Context-selection benchmark for research agents. Evaluates how Omneum and frontier LLM judges select evidence under independent agreement, conflicting measurements, false consensus, and syndicated reporting.

**4 held-out cases · 31 candidate sources · Claude Sonnet 5.5 generator**

[Leaderboard](leaderboard.md) | [Benchmark README](README.md) | [Dataset](context_evaluation/heldout/DATASET.md) | [Saved Results](context_evaluation/heldout/results/)

## Quick Start

Run from the Omneum repository root.

```bash
# Validate all 24 held-out cases, including the four research cases
.venv/bin/python -m benchmarks.context_evaluation.heldout.validate_dataset

# Run offline benchmark tests
.venv/bin/python tools/run_context_evaluation_tests.py -q

# Verify saved publication metrics
.venv/bin/python -m benchmarks.context_evaluation.heldout.build_dashboard_summary --check
```

These commands do not make provider calls. They validate the frozen dataset, execute offline tests, and verify the published metrics against saved benchmark artifacts.

To reproduce live model executions, see [Benchmark README](README.md).

## Benchmark Overview

Research agents routinely encounter evidence that agrees for different reasons:

- Independent observations can support the same conclusion.
- Reports can disagree because they measure different quantities.
- Independent researchers can reach the same incorrect conclusion.
- Multiple publications can repeat information originating from one report.

Omneum evaluates structural relationships between sources and assertions, including estimated dependencies and independent support, without requiring an LLM judge during context selection.

The benchmark compares that approach with Claude Sonnet 5.5, GPT-6 Astra, and Gemini 3.8 Flash as LLM-based context judges.

All configurations use Claude Sonnet 5.5 for downstream answer generation.

### Cases

| Case | Candidates | Budget | Evaluation objective |
|---|---:|---:|---|
| [`research_clean_consensus`](#research_clean_consensus) | 7 | 3 | Select evidence from sources with different provenance relationships |
| [`research_conflicting_reports`](#research_conflicting_reports) | 8 | 3 | Distinguish net forest-cover change from gross additions |
| [`research_independent_false_consensus`](#research_independent_false_consensus) | 7 | 3 | Distinguish independently repeated measurement errors from census evidence |
| [`research_syndicated_reporting`](#research_syndicated_reporting) | 9 | 3 | Evaluate repeated reporting from a shared information origin |

Each case uses a fixed candidate pool, fixture relevance labels, and a selection budget of three sources.

## Recorded Results

The primary comparison uses the 10-trial BGE + GPT-6 Astra pairing and its separately executed BGE + Omneum alternative.

| Case | GPT-6 Astra Precision | Omneum Precision | GPT-6 Astra Recall | Omneum Recall | Omneum Selection p50 |
|---|---:|---:|---:|---:|---:|
| Clean consensus | 100% | 100% | 42.9% | 42.9% | 0.603s |
| Conflicting reports | 100% | 100% | 60% | 60% | 0.624s |
| Independent false consensus | 66.7% | 0% | 66.7% | 0% | 0.630s |
| Syndicated reporting | 33.3% | 33.3% | 25% | 25% | 0.620s |

**Omneum matched GPT-6 Astra's selection precision and recall in three of four research cases while recording substantially lower selection latency.**

The exceptions and shared weaknesses are documented in the individual case results.

### Selection Latency

Median selection latency in seconds:

| Case | GPT-6 Astra Judge | Gemini 3.8 Flash Judge | Omneum |
|---|---:|---:|---:|
| Clean consensus | 3.706s | 1.926s | **0.603s** |
| Conflicting reports | 6.255s | 2.308s | **0.624s** |
| Independent false consensus | 6.038s | 2.517s | **0.630s** |
| Syndicated reporting | 3.453s | 2.269s | **0.620s** |

Across all four cases, Omneum completed context selection in approximately 0.60–0.63 seconds.

The GPT-6 Astra judge required 3.45–6.26 seconds, while Gemini required 1.93–2.52 seconds.

**Omneum recorded approximately 5.6–10.0× lower selection latency than GPT-6 Astra and 3.2–4.2× lower selection latency than Gemini**, comparing the reported per-case medians.

These are recorded benchmark timings, not universal performance guarantees.

## `research_clean_consensus`

**Task:** Determine when the Eastbank pedestrian bridge opened to the public.

```text
On what date did the Eastbank pedestrian bridge
open to the public?
```

### Fixture

```text
7 candidates
3 selected
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

All seven sources are labeled relevant. The relevance metric does not distinguish between independently observed evidence and records derived from the same origin.

**Expected answer:** June 14, 2026.

### Recorded Selections

| Method | Trials | Selected sources | Precision | Recall | Answer | Selection p50 |
|---|---:|---|---:|---:|---|---:|
| BGE + Claude Judge | 1 | `primary_record`, `dataset`, `filing` | 100% | 42.9% | 1/1 correct | 1.527s |
| BGE + GPT-6 Astra Judge | 10 | `primary_record`, `filing`, `dataset` | 100% | 42.9% | 10/10 correct | 3.706s |
| BGE + Gemini Judge | 10 | Same | 100% | 42.9% | 10/10 correct | 1.926s |
| **BGE + Omneum** | **10** | `primary_record`, `filing`, `publication` | **100%** | **42.9%** | **10/10 correct** | **0.603s** |
| Cohere + Claude Judge | 1 | `primary_record`, `dataset`, `filing` | 100% | 42.9% | 1/1 correct | 2.269s |
| Cohere + Omneum | 1 | `primary_record`, `publication`, `report` | 100% | 42.9% | 1/1 correct | 0.579s |

### Comparative Analysis

Every method selected three relevant sources and generated the correct date.

The BGE + LLM judges generally selected:

```text
primary_record
dataset
filing
```

Both `dataset` and `filing` reference the primary opening certificate.

BGE + Omneum selected:

```text
primary_record
filing
publication
```

This selection includes the primary record and a walking guide that derives from a different reporting chain.

Cohere + Omneum selected:

```text
primary_record
publication
report
```

This includes the accessibility group's independent field observation.

The selections demonstrate different provenance compositions, although the fixture's relevance labels score them equally.

**Result:** Omneum matched every LLM judge on precision, recall, and recorded answer correctness, while recording lower selection latency.

The case establishes that Omneum can select fully relevant evidence without an LLM judge in the selection stage. It does not establish a measured advantage in source independence because the reported metrics do not score that property directly.

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
3 selected
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

**Expected answer:** −60 hectares.

### Recorded Selections

| Method | Trials | Selected sources | Precision | Recall | Answer | Selection p50 |
|---|---:|---|---:|---:|---|---:|
| BGE + Claude Judge | 1 | `primary_publication`, `dataset`, `report_2` | 100% | 60% | 1/1 correct | 2.420s |
| BGE + GPT-6 Astra Judge | 10 | Same (6/10); `primary_publication`, `dataset`, `filing` (4/10) | 100% | 60% | 10/10 correct | 6.255s |
| BGE + Gemini Judge | 10 | `primary_publication`, `dataset`, `report_2` | 100% | 60% | 10/10 correct | 2.308s |
| **BGE + Omneum** | **10** | `primary_publication`, `dataset`, `report_2` | **100%** | **60%** | **10/10 correct** | **0.624s** |
| Cohere + Claude Judge | 1 | `primary_publication`, `dataset`, `filing` | 100% | 60% | 1/1 correct | 3.434s |
| Cohere + Omneum | 1 | `primary_publication`, `report_2`, `dataset` | 100% | 60% | 1/1 correct | 2.175s |

### Comparative Analysis

All configurations selected evidence supporting the correct net-change calculation.

BGE + Omneum consistently selected:

```text
primary_publication
dataset
report_2
```

This matches the Gemini judge's selected sources and the GPT-6 Astra judge's selection in six of ten trials.

GPT-6 Astra selected the land office filing instead of Land Review in four trials. Both sets were fully relevant.

The difference is execution cost.

| Selector | Selection p50 |
|---|---:|
| GPT-6 Astra Judge | 6.255s |
| Gemini Judge | 2.308s |
| **Omneum** | **0.624s** |

**Result:** Omneum matched the frontier LLM judges' 100% precision, 60% recall, and correct recorded answers while completing selection approximately 10× faster than GPT-6 Astra and 3.7× faster than Gemini in this case.

This is a strong measured result for using Omneum as a lower-latency context-selection component.

## `research_independent_false_consensus`

**Task:** Determine the number of occupied homes in the North Quay pilot.

```text
How many occupied homes were in the North Quay pilot
at the August 2026 census, excluding vacant units?
```

### Fixture

```text
7 candidates
3 selected
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

**Expected answer:** 216 occupied homes.

### Recorded Selections

| Method | Trials | Selected sources | Precision | Recall | Answer | Selection p50 |
|---|---:|---|---:|---:|---|---:|
| BGE + Claude Judge | 1 | `dataset`, `web_page`, `report` | 66.7% | 66.7% | 1/1 correct | 1.497s |
| BGE + GPT-6 Astra Judge | 10 | `dataset`, `web_page`, `publication` (7/10); `dataset`, `web_page`, `report` (3/10) | 66.7% | 66.7% | 10/10 correct | 6.038s |
| BGE + Gemini Judge | 10 | `analysis`, `dataset`, `web_page` | 66.7% | 66.7% | 10/10 correct | 2.517s |
| **BGE + Omneum** | **10** | `analysis`, `report`, `publication` | **0%** | **0%** | 10/10 unscored | **0.630s** |
| Cohere + Claude Judge | 1 | `primary_record`, `dataset`, `web_page` | 100% | 100% | 1/1 correct | 2.205s |
| Cohere + Omneum | 1 | `analysis`, `report`, `publication` | 0% | 0% | 1/1 unscored | 0.649s |

### Comparative Analysis

This case distinguishes structural independence from semantic measurement validity.

Omneum selected:

```text
analysis
report
publication
```

All three report 240 occupied homes, although their underlying methods count residential units rather than verified occupancy.

No selected source was labeled relevant.

The BGE + LLM judges performed better, selecting two relevant census sources. However, each also selected one incorrect source:

```text
GPT-6 Astra:
  dataset       relevant
  web_page      relevant
  publication   irrelevant

Gemini:
  dataset       relevant
  web_page      relevant
  analysis      irrelevant
```

The Cohere + Claude judge selected all three relevant sources.

The comparison exposes a genuine distinction between the evaluated methods.

Omneum evaluates structural reliability and estimated independence. The LLM judges can also interpret the semantic difference between counting residential units and measuring occupied households.

Independent sources can agree on an incorrect measurement without sharing upstream information.

That is a limitation of structural evidence as a substitute for semantic validation, rather than evidence that the sources are structurally dependent.

The recorded Omneum answers were `unscored`. They cannot be counted as correct or incorrect without additional adjudication.

**Result:** The LLM judges outperformed Omneum on source relevance in this case. Omneum's 0% precision and recall identify a concrete boundary of structural context evaluation: independent support does not guarantee that sources measure the requested quantity.

This result is relevant to system design because it distinguishes what structural evaluation can establish from what requires semantic or domain-specific validation.

## `research_syndicated_reporting`

**Task:** Determine how many battery-electric buses Riverton had accepted into passenger service.

```text
As of August 18, how many battery-electric buses had
Riverton accepted into passenger service under its 2026 order?
```

### Fixture

```text
9 candidates
3 selected
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
Order quantity:       60
Accepted into service: 36
Awaiting acceptance:  24
```

The four relevant sources are:

```text
primary_record
independent_report
filing
dataset
```

**Expected answer:** 36 buses.

### Recorded Selections

| Method | Trials | Selected sources | Precision | Recall | Answer | Selection p50 |
|---|---:|---|---:|---:|---|---:|
| BGE + Claude Judge | 1 | `dataset`, `original_report`, `news_article` | 33.3% | 25% | 1/1 correct | 1.494s |
| BGE + GPT-6 Astra Judge | 10 | Same | 33.3% | 25% | 10/10 correct | 3.453s |
| BGE + Gemini Judge | 10 | Same | 33.3% | 25% | 10/10 correct | 2.269s |
| **BGE + Omneum** | **10** | `original_report`, `news_article`, `dataset` | **33.3%** | **25%** | **10/10 correct** | **0.620s** |
| Cohere + Claude Judge | 1 | `primary_record`, `dataset`, `filing` | 100% | 75% | 1/1 correct | 4.970s |
| Cohere + Omneum | 1 | `primary_record`, `original_report`, `dataset` | 66.7% | 50% | 1/1 correct | 3.990s |

### Comparative Analysis

This case is particularly important because it tests a problem that structural dependency analysis is intended to address: repeated reporting from a common origin.

All BGE configurations selected the same evidence set:

```text
dataset
original_report
news_article
```

Only the fleet dataset was relevant.

The incorrect original report and its direct news derivative were both retained by:

- Claude Sonnet 5.5 Judge
- GPT-6 Astra Judge
- Gemini 3.8 Flash Judge
- Omneum

**None of the BGE-based selectors successfully eliminated the duplicated misinformation from the selected context.**

All achieved 33.3% precision and 25% recall.

Despite this, the downstream generator produced correct recorded answers.

The Cohere comparison shows that the initial reranker also materially affected selection quality.

Cohere + Claude selected:

```text
primary_record
dataset
filing
```

Cohere + Omneum selected:

```text
primary_record
original_report
dataset
```

The Claude judge achieved 100% precision and 75% recall. Omneum achieved 66.7% precision and 50% recall.

**Result:** Omneum matched all three BGE + LLM judges on selection quality while recording lower latency, but the shared selections were weak.

With Cohere, the Claude judge selected a better evidence set.

The case establishes that syndicated-reporting dependencies remain challenging for all evaluated BGE configurations. It does not demonstrate superior dependency handling by Omneum, and it should not be represented as a successful elimination of copied misinformation by the LLM judges either.

Gemini figures use the completed low-thinking replay; Gemini speedups use its unchanged historical Omneum comparator. Other Omneum rows retain their original paired run. Gemini E2E sums combine original selection and later recovered generation timings.

## Inspect Recorded Runs

Authoritative run directories:

```text
benchmarks/context_evaluation/heldout/results/
├── bge-claude-vs-bge-omneum-20261008/
├── bge-openai-vs-bge-omneum-20261008/
├── bge-google-low-vs-bge-omneum-20261008/
└── cohere-claude-vs-cohere-omneum-20261008/
```

### Inspect Research Case Records

```bash
# List the recorded result artifacts
ls benchmarks/context_evaluation/heldout/results/bge-openai-vs-bge-omneum-20261008/

# Find all four research cases
rg -n \
  'research_clean_consensus|research_conflicting_reports|research_independent_false_consensus|research_syndicated_reporting' \
  benchmarks/context_evaluation/heldout/results/bge-openai-vs-bge-omneum-20261008/results.jsonl
```

Extract matching JSONL records:

```bash
rg \
  'research_clean_consensus|research_conflicting_reports|research_independent_false_consensus|research_syndicated_reporting' \
  benchmarks/context_evaluation/heldout/results/bge-openai-vs-bge-omneum-20261008/results.jsonl \
  > /tmp/research-results.jsonl
```

Count the extracted records:

```bash
wc -l /tmp/research-results.jsonl
```

The number of JSONL records depends on how attempts and method comparisons are serialized. It should not be interpreted as the number of independent cases.

### Inspect All Recorded Comparisons

```bash
for run in \
  bge-claude-vs-bge-omneum-20261008 \
  bge-openai-vs-bge-omneum-20261008 \
  bge-google-low-vs-bge-omneum-20261008 \
  cohere-claude-vs-cohere-omneum-20261008
do
  echo "===== $run ====="

  rg -c \
    'research_clean_consensus|research_conflicting_reports|research_independent_false_consensus|research_syndicated_reporting' \
    "benchmarks/context_evaluation/heldout/results/$run/results.jsonl" || true
done
```

### Inspect the Published Dashboard

```bash
.venv/bin/python -m json.tool \
  benchmarks/context_evaluation/heldout/dashboard_summary.json
```

Verify the dashboard:

```bash
.venv/bin/python -m benchmarks.context_evaluation.heldout.build_dashboard_summary --check
```

Regenerate the dashboard from saved artifacts:

```bash
.venv/bin/python -m benchmarks.context_evaluation.heldout.build_dashboard_summary
```

Regeneration does not make provider calls or reproduce the original model responses.

## Evaluation Notes

| Setting | Value |
|---|---|
| Cases | 4 |
| Candidate sources | 31 total |
| Candidate pools | 7–9 sources per case |
| Selection budget | 3 sources per case |
| Generator | Claude Sonnet 5.5 |
| Initial rerankers | BGE Reranker v2-m3, Cohere Rerank v4.0 Pro |
| LLM judges | Claude Sonnet 5.5, GPT-6 Astra, Gemini 3.8 Flash |
| BGE + GPT-6 / Gemini | 10 trials per case |
| BGE + Omneum | 10 trials per case in each paired run |
| Claude / Cohere comparisons | 1 trial per case |
| Latency aggregation | Median across recorded trials |
| Selection scoring | Fixture relevance labels |

BGE + Omneum appears in multiple paired-run artifacts. The primary comparisons use its GPT-6 Astra pairing rather than treating repeated executions as additional independent cases.

### Downstream Answer Results

| Case | GPT-6 Astra Judge | Gemini Judge | Omneum |
|---|---|---|---|
| Clean consensus | 10/10 correct | 10/10 correct | 10/10 correct |
| Conflicting reports | 10/10 correct | 10/10 correct | 10/10 correct |
| Independent false consensus | 10/10 correct | 10/10 correct | 10/10 unscored |
| Syndicated reporting | 10/10 correct | 10/10 correct | 10/10 correct |

Answer results reflect the fixed downstream Claude Sonnet 5.5 generator after each selection method.

The benchmark uses frozen answer-scoring criteria. An `unscored` response is not automatically an incorrect response.

Selection precision and recall measure fixture relevance, not source independence or the accuracy of dependency estimation directly.

## Interpretation

The Research & Analysis benchmark demonstrates that **Omneum can provide context-selection performance comparable to frontier LLM judges at substantially lower recorded latency**, while also identifying cases where semantic interpretation improves selection.

The results support four specific conclusions.

**1. Omneum matches frontier LLM judges on straightforward research evidence selection.**

In clean consensus and conflicting reports, Omneum achieved the same precision, recall, and recorded answer correctness as Claude, GPT-6 Astra, and Gemini.

It did so without using an LLM judge in the selection stage.

**2. Omneum consistently reduces selection latency.**

Across the four cases, Omneum recorded selection medians of 0.603–0.630 seconds, compared with 3.453–6.255 seconds for GPT-6 Astra and 1.926–2.517 seconds for Gemini.

This is a measurable efficiency advantage for context-selection workflows.

**3. The LLM judges also retain misleading or dependent evidence.**

In syndicated reporting, every BGE + LLM judge selected the same incorrect original report and its news derivative as Omneum.

All four BGE configurations achieved only 33.3% precision and 25% recall.

The presence of an LLM judge did not eliminate that failure.

**4. Structural independence alone cannot resolve every semantic measurement error.**

In independent false consensus, Omneum selected independently produced but incorrect evidence, while the LLM judges identified more of the census sources.

This distinguishes structural reliability evaluation from semantic task interpretation.

### Overall Result

**Omneum matched GPT-6 Astra and Gemini on source-selection precision and recall in three of four research cases, with substantially lower recorded selection latency.**

Its principal weakness in this subset was independent false consensus, where the task required recognizing that multiple independent sources measured the wrong quantity.

The syndicated-reporting case exposed a shared weakness across all BGE-based configurations, including the frontier LLM judges.

These results support Omneum's value as a fast, structural context-evaluation component. They do not establish that structural evaluation replaces semantic reasoning or that the measured performance generalizes to all research workflows.

The benchmark uses synthetic fixtures with fixed candidate pools and relevance labels. It does not evaluate open-ended retrieval across live research repositories.

For complete methodology, live execution requirements, and aggregate results, see [Benchmark README](README.md) and [Leaderboard](leaderboard.md).
