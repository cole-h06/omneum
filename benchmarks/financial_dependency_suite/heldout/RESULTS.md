# Held-out Benchmark Results

## Benchmark Results

| Method | Correct | Incorrect | Unscored / failures | Accuracy | Selection precision | Selection recall | Selection p50 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| BGE | 220 | 8 | 12 | **91.67%** | 69.44% | 47.46% | 192 ms |
| Google + provenance | 218 | 0 | 22 | 90.83% | 95.87% | 67.75% | 7.186 s |
| OpenAI | 218 | 0 | 22 | 90.83% | **97.04%** | **69.37%** | 3.175 s |
| OpenAI + provenance | 218 | 0 | 22 | 90.83% | 95.51% | 67.42% | 3.393 s |
| Anthropic | 217 | 0 | 23 | 90.42% | 96.41% | 67.93% | 1.701 s |
| Anthropic + provenance | 217 | 0 | 23 | 90.42% | 92.46% | 65.87% | 1.408 s |
| Google | 215 | 2 | 23 | 89.58% | 95.69% | 68.08% | 5.244 s |
| Vector | 197 | 3 | 40 | 82.08% | 65.28% | 45.17% | 50 ms |
| Cohere | 194 | 1 | 45 | 80.83% | 76.71% | 53.74% | 150 ms |
| **Omneum** | **184** | **0** | **56** | **76.67%** | **66.67%** | **42.20%** | **481 ms** |

### Omneum Results

| Metric | Result |
| --- | ---: |
| Correct | 184 |
| Incorrect | 0 |
| Unscored | 46 |
| Generator refusals | 10 |
| Selection failures | 0 |
| Evaluable accuracy | 100.00% |

### Omneum Runtime

| Component | p50 | p95 |
| --- | ---: | ---: |
| Evaluator | **38.8 ms** | **64.7 ms** |
| Integration overhead | 442.2 ms | 521.9 ms |
| Selection | 481.3 ms | 574.4 ms |
| Generator | 2.683 s | 4.818 s |
| End-to-end | 3.179 s | 5.295 s |

Latency measurements contain 240 samples.

## Test Configuration

| Configuration | Value |
| --- | --- |
| Cases | 24 |
| Trials per case | 10 |
| Attempts per method | 240 |
| Candidate pool | 6–10 |
| Context budget | 2–4 |
| Answer generator | `claude-sonnet-5-5` |
| Python | CPython 3.13.15 |
| Platform | macOS 26.6.2 arm64 |

Each method receives the same candidate pool and context budget. Selected context is passed to `claude-sonnet-5-5` for answer generation.

### Selection Methods

| Method | Model / implementation |
| --- | --- |
| Omneum | Omneum |
| Vector | `all-MiniLM-L6-v2` |
| BGE | `BAAI/bge-reranker-v2-m3` |
| Cohere | `rerank-v4.0-pro` |
| Anthropic | `claude-sonnet-5-5` |
| OpenAI | `gpt-6-astra` |
| Google | `gemini-3.8-flash` |
| Anthropic + provenance | `claude-sonnet-5-5` |
| OpenAI + provenance | `gpt-6-astra` |
| Google + provenance | `gemini-3.8-flash` |

`+ provenance` methods receive the candidate provenance fields supplied to Omneum.

### Omneum Dependency Estimator

| Parameter | Value |
| --- | ---: |
| Version | `dependency-estimator-v4` |
| Upstream weight | 25 |
| Citation weight | 20 |
| Assertion lineage weight | 20 |
| Graph weight | 15 |
| Ownership weight | 10 |
| Temporal weight | 10 |
| Retrieval weight | 0 |
| Dependency cluster threshold | 0.3 |
| Temporal window | 172,800 s |

### Software

| Package | Version |
| --- | --- |
| `anthropic` | `0.125.0` |
| `cohere` | `7.1.1` |
| `google-genai` | `2.21.0` |
| `numpy` | `2.5.2` |
| `openai` | `2.54.0` |
| `sentence-transformers` | `5.7.0` |

## Evaluation Metrics

- `Accuracy`: correct answers / 240 attempts
- `Evaluable accuracy`: correct / (correct + incorrect)
- `Selection precision`: relevant selected candidates / selected candidates
- `Selection recall`: selected relevant candidates / relevant candidates
- `Selection latency`: total selection-stage runtime
- `Evaluator latency`: Omneum evaluator runtime

## Result Artifacts

### Baselines

```text
results/final-10trial-definitive-fresh-20261005/
```

Commit: `09fed729d4079abe77e3956376622dd127c679f1`

### Omneum

```text
results/braid-1.1-omneum-only-20261006/
```

Commit: `b6450c05d9324bb0452aa26087ac2f4c3281a700`

Each result directory contains:

```text
manifest.json
results.jsonl
summary.json
```

Benchmark configuration:

```text
plan.json
case_matrix.json
dataset_manifest.json
DATASET.md
ADAPTER.md
OBSERVABILITY.md
```