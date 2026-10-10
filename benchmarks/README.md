# Omneum Benchmarks

Benchmarks evaluating Omneum's context selection against semantic rerankers and frontier LLM judges.

The main evaluation covers **24 fixed synthetic cases across six agentic domains**, with six authoritative paired runs and 12 published configurations. Four additional public adversarial tracks test circular sourcing, conflicting information, data staleness, and prompt injection.

**[Leaderboard](leaderboard.md) | [Dataset](context_evaluation/heldout/DATASET.md) | [Saved Results](context_evaluation/heldout/results/) | [Evidence](context_evaluation/heldout/EVIDENCE.md)**

## Results

Published comparisons:

- [Semantic Rerankers](leaderboard.md#semantic-rerankers)
- [Frontier LLM Judges](leaderboard.md#frontier-llm-judges)
- [Domain Evaluations](leaderboard.md#domain-evaluations)

The leaderboard reports selection precision, recall, answer accuracy, latency, and downstream generator usage. In the recorded comparisons, Omneum improved selection precision and recall over standalone BGE and Cohere rerankers. Against frontier LLM judges, it achieved **2.63×–10.68× faster median selection**, without an additional frontier-model judge call. See the [leaderboard](leaderboard.md) for matched configurations and trade-offs.

## Quick Start

Run from the repository root with the repository-required **uv 0.12.10**:

```sh
uv sync --locked --group benchmarks
uv run --locked --group benchmarks python tools/run_context_evaluation_tests.py -q -p no:cacheprovider
uv run --locked --group benchmarks python -m benchmarks.context_evaluation.heldout.validate_dataset
uv run --locked --group benchmarks python -m benchmarks.context_evaluation.heldout.build_dashboard_summary --check
```

No provider credentials or paid inference are required for offline verification. The test runner blocks TCP/IP connections and skips live provider and uncached model integrations. Local Unix-socket daemon tests require host permissions.

## Benchmark Suites

### Held-Out Context Evaluation

The main benchmark compares context-selection methods across 24 fixed cases. Each case contains an agent task, candidate context, expected selections, and ground-truth evaluation data.

| Configuration | Role |
|---|---|
| BGE Reranker v2-m3 | Semantic reranking |
| Cohere Rerank v4.0 Pro | Semantic reranking |
| Claude Sonnet 5.5 | Frontier LLM judge |
| GPT-6 Astra | Frontier LLM judge |
| Gemini 3.8 Flash | Frontier LLM judge |
| Omneum | Provenance-aware context selection |

**Answer generator:** Claude Sonnet 5.5, held constant within matched comparisons.

Selection and answer generation are evaluated separately. Each method selects context from a fixed candidate pool, and Claude Sonnet 5.5 generates the final answer using the selected context.

Omneum replaces the frontier LLM judge call in the corresponding comparisons. Published BGE judge pairs use the same saved BGE shortlist; Cohere judge pairs share recorded rerank responses. Selector inputs differ: Omneum receives structured provenance, while ordinary judges receive candidate text.

**Results:** [Leaderboard](leaderboard.md)

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

Dataset fixtures:

```text
benchmarks/context_evaluation/heldout/cases/
├── coding_api_version_change/
│   ├── case.json
│   └── ground_truth.json
├── enterprise_policy_copy_chain/
│   ├── case.json
│   └── ground_truth.json
├── research_syndicated_reporting/
│   ├── case.json
│   └── ground_truth.json
├── multi_agent_feedback_loop/
│   ├── case.json
│   └── ground_truth.json
├── analytics_derived_metric_cycle/
│   ├── case.json
│   └── ground_truth.json
└── support_stale_runbook/
    ├── case.json
    └── ground_truth.json
```

Representative fixtures shown; the complete dataset contains 24 cases.

See [`DATASET.md`](context_evaluation/heldout/DATASET.md) for the complete inventory, source annotations, and validation contracts.

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
python -m benchmarks.context_evaluation.adversarial.circular_sourcing.run_benchmark

# Conflicting information
python -m benchmarks.context_evaluation.adversarial.conflicting_information.run_benchmark

# Data staleness
python -m benchmarks.context_evaluation.adversarial.data_staleness.run_benchmark

# Prompt injection
python -m benchmarks.context_evaluation.adversarial.prompt_injection.run_benchmark
```

These are evaluation runners, not the offline regression suite. Some require a running evaluator, provider credentials, or paid model access.

The source-dependence track and financial example corpora are excluded from the public release pending third-party redistribution review. Source dependence is also represented in the canonical synthetic cases.

Implementation: [`context_evaluation/adversarial/`](context_evaluation/adversarial/)

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
└── context_evaluation/
    ├── publication_manifest_v1.json
    ├── publication_manifest_v1.schema.json
    ├── heldout/
    │   ├── DATASET.md
    │   ├── EVIDENCE.md
    │   ├── DASHBOARD_SUMMARY.md
    │   ├── LATENCY_ANALYSIS.md
    │   ├── cases/
    │   ├── contracts/
    │   ├── results/
    │   ├── analysis/
    │   ├── run_benchmark.py
    │   ├── validate_dataset.py
    │   ├── build_dashboard_summary.py
    │   ├── source_manifest_v5.json
    │   ├── dashboard_summary.json
    │   └── dashboard_summary.schema.json
    └── adversarial/
        ├── circular_sourcing/
        ├── conflicting_information/
        ├── data_staleness/
        └── prompt_injection/
```

The held-out runner, canonical fixtures, recorded outputs, and publication dashboard are maintained separately. Six authoritative runs and one tied-maxima diagnostic remain public. Superseded experiments are retained in the private pre-cleanup archive.

## Evaluation Configuration

| Parameter | Value |
|---|---|
| Dataset | 24 fixed synthetic cases |
| Domains | 6 |
| Candidate pool | Fixed per case; see `case_matrix.json` |
| Selection budget | 2–3 candidates in the canonical dataset |
| Generator | Claude Sonnet 5.5 |
| Rerankers | BGE v2-m3, Cohere v4.0 Pro |
| LLM judges | Claude Sonnet 5.5, GPT-6 Astra, Gemini 3.8 Flash |
| Trial counts | 1 or 10 per case, depending on experiment |
| Pair identity | Run, case, and trial |
| Output | JSONL results, run summaries, public manifests |

The preserved experimental plan permits selection budgets of 2–4; the released case fixtures use 2–3.

Experiments were executed in separate arm blocks rather than interleaved. Published comparisons use matched configurations, but the experiments are not pooled into a single trial population.

### Metrics

| Metric | Definition |
|---|---|
| Selection Precision | TP / (TP + FP) |
| Selection Recall | TP / (TP + FN) |
| Selection F1 | 2TP / (2TP + FP + FN) |
| Recorded Answer Score | Frozen substring-based correctness across attempts |
| Adjudicated Answer Accuracy | Manually reviewed complete-answer correctness |
| Selection p50 / p95 | Median / 95th-percentile selection latency |
| E2E p50 / p95 | Median / 95th-percentile end-to-end latency |
| Generator Tokens | Downstream generator token usage |
| Generator Cost | Estimated downstream generator API cost |

Selection precision, recall, and F1 are macro-averaged per attempt. The dashboard also preserves micro-aggregated metrics and underlying counts.

Recorded answer scores use frozen substring matching. Refusals, unscored responses, and generation failures remain in the attempt denominator. Complete-answer accuracy is reported separately where adjudication evidence exists.

**Ten trials per case measure repeated execution, not 240 independent tasks.** The dataset contains 24 distinct cases.

### Latency

Latency distributions use recorded execution components. End-to-end measurements are component sums, not independently measured wall-clock durations.

For the Cohere augmented route, the shared rerank duration is added once per case. Integration timing already includes SDK evaluation and must not be added a second time.

See [`LATENCY_ANALYSIS.md`](context_evaluation/heldout/LATENCY_ANALYSIS.md) for the paired timing methodology and recorded measurements.

### Cost

Headline token and cost columns cover downstream answer generation only.

Estimates use the preserved pricing snapshot and exclude local compute, discounts, credits, and unlogged retries. Judge inference costs are accounted for separately.

Missing Cohere token telemetry and unverified rerank pricing prevent reliable whole-pipeline cost totals for those configurations.

## Running Evaluations

### 1. Validate the Dataset

```sh
uv run --locked --group benchmarks python -m benchmarks.context_evaluation.heldout.validate_dataset
```

Expected dataset coverage:

```json
{
  "cases": 24,
  "environments": {
    "coding_agents": 4,
    "enterprise_rag": 4,
    "research_analysis_agents": 4,
    "multi_agent_systems": 4,
    "data_analytics_agents": 4,
    "support_operations_agents": 4
  }
}
```

The validator also reports the documented source-role discrepancy in `coding_package_fix_lineage`. The preserved case and scoring rules are unchanged.

### 2. Run Offline Tests

```sh
uv run --locked --group benchmarks python tools/run_context_evaluation_tests.py -q -p no:cacheprovider
```

Last verified cleanup run:

```text
528 passed, 10 skipped
```

The offline suite covers dataset validation, selection scoring, saved-result processing, publication provenance, checkpoint handling, and compatibility checks.

### 3. Verify Saved Results

```sh
uv run --locked --group benchmarks python -m benchmarks.context_evaluation.heldout.build_dashboard_summary --check
```

Checks the published dashboard against retained evidence and publication integrity contracts without rerunning provider inference.

### 4. Regenerate the Dashboard

```sh
uv run --locked --group benchmarks python -m benchmarks.context_evaluation.heldout.build_dashboard_summary
```

Output:

```text
benchmarks/context_evaluation/heldout/dashboard_summary.json
```

This processes recorded artifacts. It does **not** rerun provider inference. Regeneration should not be used to overwrite frozen publication evidence without reviewing the resulting changes.

### 5. Run a Live Evaluation

Inspect supported arguments before executing:

```sh
uv run --locked --group benchmarks python -m benchmarks.context_evaluation.heldout.run_benchmark --help
```

Live execution requires relevant provider credentials and may incur API charges. Use a new run ID and `heldout/reproductions/` for new evaluations. Do not overwrite authoritative results or attempt to resume historical paid runs from public manifest projections.

## Saved Results

Recorded experiments are stored under:

```text
benchmarks/context_evaluation/heldout/results/
├── bge-claude-vs-bge-omneum-20261008/
│   ├── manifest.public-v1.json
│   ├── results.jsonl
│   └── summary.json
├── bge-openai-vs-bge-omneum-20261008/
│   ├── manifest.public-v1.json
│   ├── results.jsonl
│   └── summary.json
├── bge-google-vs-bge-omneum-20261008/
│   ├── manifest.public-v1.json
│   ├── results.jsonl
│   └── summary.json
└── cohere-claude-vs-cohere-omneum-20261008/
    ├── manifest.public-v1.json
    ├── results.jsonl
    └── summary.json
```

Representative runs shown. The public results directory contains six authoritative runs and one tied-maxima diagnostic, not the complete historical experiment archive.

See [`EVIDENCE.md`](context_evaluation/heldout/EVIDENCE.md) for the complete run inventory and configuration mapping.

### Inspect a Run

```sh
# Inspect the public execution manifest
uv run --locked --group benchmarks python -m json.tool \
  benchmarks/context_evaluation/heldout/results/bge-claude-vs-bge-omneum-20261008/manifest.public-v1.json

# Inspect recorded attempts
head -n 2 \
  benchmarks/context_evaluation/heldout/results/bge-claude-vs-bge-omneum-20261008/results.jsonl

# Inspect aggregate results
uv run --locked --group benchmarks python -m json.tool \
  benchmarks/context_evaluation/heldout/results/bge-claude-vs-bge-omneum-20261008/summary.json
```

Public manifests normalize developer-specific absolute paths while retaining original artifact hashes and execution fingerprints. They are explicitly versioned projections, not byte-identical copies of the private execution manifests.

### Dashboard Record

The publication dashboard identifies configurations by run and method without pooling unrelated experiments.

Each configuration record contains selection metrics, answer scores, latency distributions, token usage, estimated cost, measurement coverage, and execution lineage.

The publication contract pins the exact 12 configuration objects and published metric tables:

[`publication_manifest_v1.json`](context_evaluation/publication_manifest_v1.json)

Schema: [`dashboard_summary.schema.json`](context_evaluation/heldout/dashboard_summary.schema.json)

Documentation: [`DASHBOARD_SUMMARY.md`](context_evaluation/heldout/DASHBOARD_SUMMARY.md)

### Provenance and Integrity

The public evidence uses versioned integrity contracts:

| Contract | Purpose |
|---|---|
| `publication_manifest_v1.json` | Published configuration objects, metric tables, and artifact hashes |
| `source_manifest_v5.json` | Source implementation hashes |
| `manifest.public-v1.json` | Public representation of individual recorded runs |
| Checkpoint v3 | Compatibility and resume validation for new execution |

Current source and publication contracts preserve reviewed hash revisions, including previous values and reasons for changes.

Historical source and checkpoint contracts retain necessary inert snapshots under [`contracts/`](context_evaluation/heldout/contracts/).

A fresh checkout can verify the public evidence without historical Git objects, removed package aliases, or machine-specific symlinks. The original private manifests and removed historical artifacts remain in the pre-cleanup archive.

Historical Git revisions identify committed reference versions. Recorded dirty checkouts do not establish exact executed-source snapshots.

## Limitations

- **Dataset:** 24 fixed synthetic cases. Repeated trials are not independent tasks.
- **Held-out status:** Subsequent selection-policy analysis used the original held-out cases as development evidence. They are not an untouched test set for those later policies.
- **Selector inputs:** Competing methods receive different information. Matched candidate pools do not imply identical selector capabilities.
- **Timing:** Execution was recorded in arm blocks, not interleaved. End-to-end component sums are not independent wall-clock measurements.
- **Answer scoring:** Frozen substring scores are not complete semantic accuracy measurements. Manually adjudicated complete-answer accuracy is reported separately.
- **Cost:** API estimates exclude local compute, credits, discounts, and unlogged retries. Generator-only costs exclude judge inference.
- **Reproducibility:** Saved metrics are verifiable offline. Original provider outputs may differ on live re-execution.
- **Publication:** Superseded runs and private source materials are archived rather than distributed. Financial example redistribution rights remain unresolved.
- **Rendering:** Exact reproduction of publication figures requires matching font bytes supplied externally.

The six authoritative runs, canonical 24-case dataset, 12 published configuration objects, and publication metric tables are preserved without modification.