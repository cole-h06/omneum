
# Omneum Benchmark Leaderboard

Benchmark results for Omneum against semantic rerankers and frontier LLM judges.

Evaluated on **24 held-out cases across six agentic domains**: coding agents, enterprise RAG, research and analysis, multi-agent systems, data analytics, and support and operations.

All configurations use Claude Sonnet 5.5 as the downstream answer generator. Within each matched experiment, candidate inputs, context budgets, and generator settings are held constant. The context-selection method changes.

See [Benchmark Methodology](README.md) for the evaluation pipeline, dataset validation, and reproduction instructions.

## Semantic Rerankers

Compares standalone semantic reranking against the same reranker with Omneum added to context selection.

The evaluated rerankers are `BAAI/bge-reranker-v2-m3` and Cohere `rerank-v4.0-pro`.

![Semantic Reranker Selection Precision](../assets/benchmarks/semantic-reranker-selection-precision.png)

| Configuration | Precision ↑ | Recall ↑ | Recorded Answer Score ↑ | Selection p50 ↓ | E2E p50 ↓ | Generator Tokens | Generator Cost |
|---|---:|---:|---:|---:|---:|---:|---:|
| BGE Reranker v2-m3 | 69.44% | 47.46% | **91.67%** | **201ms** | **2.467s** | 11,941 | $0.074618 |
| BGE + Omneum | **85.51%** | **59.31%** | 87.50% | 660ms | 3.020s | **11,595** | **$0.070662** |
| Cohere Rerank v4.0 Pro | 77.78% | 53.99% | **87.50%** | **151ms** | **2.634s** | 11,577 | $0.071242 |
| Cohere + Omneum | **82.64%** | **55.72%** | 79.17% | 624ms | 3.176s | **11,535** | **$0.070654** |

Omneum improved context-selection precision and recall with both rerankers. BGE + Omneum achieved a **16.07 percentage-point precision improvement** and an **11.85-point recall improvement**. Cohere + Omneum improved precision by **4.86 points** and recall by **1.73 points**.

Both configurations also reduced downstream generator token usage and estimated generator cost. These improvements came with additional selection latency and lower recorded answer scores: 87.50% versus 91.67% for BGE, and 79.17% versus 87.50% for Cohere.

Generator costs reflect downstream Claude Sonnet 5.5 usage only. Cohere API charges and local computation are excluded.

Cohere timings include the shared rerank response once in each paired route.
The augmented route’s 624ms selection and 3.176s end-to-end medians are
reconstructed component sums, not new measurements; see
[the paired latency analysis](context_evaluation/heldout/LATENCY_ANALYSIS.md).
The frontier table below uses manual complete-answer adjudication, matching
the saved publication dashboard and root README.

## Frontier LLM Judges

Compares Omneum against frontier LLMs used as context-selection judges.

Each judge receives candidate context and selects evidence before answer generation. Omneum performs the corresponding selection without an additional frontier-model judge call.

The evaluated judges are Claude Sonnet 5.5, GPT-6 Astra, and Gemini 3.8 Flash.

![Frontier LLM Judge Selection Latency](../assets/benchmarks/llm-judge-selection-latency.png)

| Configuration | Precision ↑ | Recall ↑ | Adjudicated Answer Accuracy ↑ | Selection p50 ↓ | E2E p50 ↓ | Generator Tokens | Generator Cost |
|---|---:|---:|---:|---:|---:|---:|---:|
| BGE + Claude Sonnet 5.5 Judge | **92.36%** | **65.24%** | **95.83%** | 1.831s | 4.165s | 11,356 | $0.068208 |
| BGE + Omneum | 86.11% | 59.34% | 91.67% | **0.697s** | **3.141s** | 11,811 | $0.072822 |
| BGE + GPT-6 Astra Judge | **92.78%** | **65.45%** | **92.50%** | 3.421s | 5.849s | 111,247 | $0.658998 |
| BGE + Omneum | 86.11% | 59.34% | 91.67% | **0.641s** | **2.983s** | 115,119 | $0.698310 |
| BGE + Gemini 3.8 Flash Judge | **94.44%** | **66.28%** | **95.83%** | 2.487s | 4.924s | 114,250 | $0.686916 |
| BGE + Omneum | 86.11% | 59.34% | 91.67% | **0.639s** | **3.130s** | 115,535 | $0.702470 |

Omneum achieved **2.63×–5.34× faster median context selection** than frontier LLM judges without requiring an additional judge inference call.

| Comparison | Judge p50 | Omneum p50 | Speedup |
|---|---:|---:|---:|
| Claude Sonnet 5.5 | 1.831s | 0.697s | **2.63×** |
| GPT-6 Astra | 3.421s | 0.641s | **5.34×** |
| Gemini 3.8 Flash | 2.487s | 0.639s | **3.89×** |

Omneum also reduced end-to-end median latency in all three comparisons. Its adjudicated answer accuracy trailed the Claude judge by 4.17 percentage points, GPT-6 Astra by 0.83 points, and Gemini by 4.17 points.

Gemini uses the verified low-thinking rerun; 139 Claude generations were recovered while preserving all selections and the historical Omneum baseline. Its E2E median combines original selection and later generation durations; ten explicit refusals are included in answer accuracy.

The LLM judges achieved higher selection precision and recall, reflecting a trade-off between selection quality and inference latency.

**Cost scope:** Generator costs include downstream Claude Sonnet 5.5 usage only. Judge inference costs and local computation are excluded. Omneum eliminates the additional frontier-model judge call, but the resulting savings are not represented in the generator-cost column.

Generator token and cost figures are totals across recorded attempts: 24 per configuration in the Claude comparison and 240 per configuration in the GPT-6 and Gemini comparisons. Totals across different trial counts are not directly comparable.

## Experimental Setup

The benchmark uses fixed cases and candidate context pools. Each selection method operates under the same context budget within its matched comparison.

| Parameter | Configuration |
|---|---|
| Dataset | 24 held-out cases |
| Domains | 6 |
| Candidate pool | 6–10 candidates per case |
| Context budget | 2–3 selected candidates in the saved dataset |
| Answer generator | Claude Sonnet 5.5 |
| Semantic rerankers | BGE Reranker v2-m3, Cohere Rerank v4.0 Pro |
| LLM judges | Claude Sonnet 5.5, GPT-6 Astra, Gemini 3.8 Flash |
| Selection methods | Semantic reranking, LLM judging, Omneum-assisted selection |

Claude Sonnet 5.5 also acts as a selection judge in one experiment; judge and generator are separate inference calls.

Run manifests retain exact model identifiers, provider parameters, execution settings, and implementation fingerprints. Saved results are evaluated under their recorded configurations rather than current provider defaults.

### Metrics

| Metric | Measurement |
|---|---|
| Selection Precision | Fraction of selected candidates marked relevant |
| Selection Recall | Fraction of relevant candidates selected |
| Recorded Answer Score | Recorded correct answers divided by all attempts |
| Selection p50 | Median selection-stage latency |
| E2E p50 | Median measured end-to-end latency |
| Generator Tokens | Total recorded downstream generator token usage |
| Generator Cost | Total estimated downstream generator API charges |

Selection precision and recall are macro-averaged per attempt, with equal case weights in these runs. Latency medians include all measured attempts.

Recorded answer scores use frozen substring-based correctness divided by all attempts, including unscored responses and generation failures. These scores are not equivalent to manually adjudicated complete semantic answer accuracy. The dashboard tracks these outcomes separately. The frontier table uses manual complete-answer accuracy, including refusals and incomplete answers in the denominator.

Higher selection precision, recall, and recorded answer scores are better. Lower latency is better. Generator token and cost totals should be compared only within matched runs with equal attempt counts.

## Reproduction

The leaderboard uses saved benchmark runs. Offline verification checks their integrity and regenerates the derived dashboard without making provider calls.

```bash
# Validate the frozen held-out dataset
python -m benchmarks.context_evaluation.heldout.validate_dataset

# Run the offline benchmark tests
python tools/run_context_evaluation_tests.py -q

# Check saved publication metrics
python -m benchmarks.context_evaluation.heldout.build_dashboard_summary --check

# Regenerate the dashboard from saved results
python -m benchmarks.context_evaluation.heldout.build_dashboard_summary
```

The dashboard is derived from recorded runs. Regenerating it does not reproduce the original model responses.

Historical runs retain input manifests, source fingerprints, checkpoint contracts, and result artifacts. Incomplete runs remain classified separately from authoritative publication results.

### Artifacts

| Artifact | Path |
|---|---|
| Benchmark implementation | [`context_evaluation/heldout/`](context_evaluation/heldout/) |
| Saved run results | [`context_evaluation/heldout/results/`](context_evaluation/heldout/results/) |
| Dashboard summary | [`dashboard_summary.json`](context_evaluation/heldout/dashboard_summary.json) |
| Dashboard schema | [`dashboard_summary.schema.json`](context_evaluation/heldout/dashboard_summary.schema.json) |
| Dataset documentation | [`DATASET.md`](context_evaluation/heldout/DATASET.md) |
| Publication evidence contract | [`publication_manifest_v1.json`](context_evaluation/publication_manifest_v1.json) |

## Interpretation

The benchmark measures context-selection quality, downstream answer outcomes, and execution latency.

Omneum improved selection precision and recall over standalone semantic rerankers while reducing downstream generator token usage. Against frontier LLM judges, Omneum achieved **2.63×–5.34× faster median selection**, reduced end-to-end latency, and eliminated the need for an additional judge inference call.

These results demonstrate Omneum's ability to perform context selection with substantially lower latency than frontier-model judging, while exposing measurable trade-offs in selection precision, recall, and downstream answer quality.

The evaluation covers 24 fixed synthetic cases, with repeated trials rather than additional independent tasks. All results use Claude Sonnet 5.5 as the downstream generator. Provider variability, unequal selector information, non-interleaved timing runs, and recorded scoring contracts limit generalization beyond the evaluated configurations.

For implementation details, dataset contracts, and benchmark commands, see the [Benchmark README](README.md).

## Domain Evaluations

| Domain | Documentation |
|---|---|
| Coding Agents | [coding.md](coding.md) |
| Enterprise RAG | [enterprise-rag.md](enterprise-rag.md) |
| Research & Analysis | [research.md](research.md) |
| Multi-Agent Systems | [multi-agent.md](multi-agent.md) |
| Data Analytics | [analytics.md](analytics.md) |
| Support & Operations | [support.md](support.md) |