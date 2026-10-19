# Context optimization: controlled selection

This experiment compares four selectors on the existing 24 synthetic held-out
cases. It adds no inference equations, dependency estimator, MCP schema, or API.

Reusable components:

- Structural research uses production graphs through `research/adapters`.
- The agent dataset provides fifteen observations from five synthetic agents;
  enterprise retrieval adds local documents, SQLite, and a vendor snapshot.
  Its existing experiment demonstrates claim mapping and budgeted reconstruction,
  but has no downstream generator or answer labels.
- The held-out benchmark provides fixed questions, candidates, provenance, truth,
  BGE reranking, generator adapters, string scoring, aggregation, manifests, and
  durable JSONL writing. Its frozen runner budgets candidate counts and its
  original Omneum method mixes relevance with structural scores.
- `OmneumClient.evaluate_context_with_chunks()` evaluates structured observations,
  then calls `reconstruct_context()` locally. This runner uses the equivalent
  production in-memory evaluator and reconstruction directly, without transport,
  keys, persistence, or daemon overhead. Only observations enter the evaluator;
  raw text stays in local selection and is sent to the configured answer generator.

## Design

| Method | Ordering and selection |
| --- | --- |
| `retrieval` | Frozen candidate order; first fitting chunks |
| `semantic` | Full BGE order; first fitting chunks |
| `omneum` | Production `coverage_support`; original order breaks ties |
| `semantic_omneum` | Full BGE order, then production `coverage_support` |

Every method receives the same query, complete candidate evidence, observations,
context budget, generation prompt, generator model, and default 1,024 output-token
cap. No truth enters selection or generation. The combined method uses semantic
order to break equal marginal utility; it does not blend scores or prefilter
evidence. With one claim per candidate, coverage selection avoids repeating a
claim and stops when all remaining marginal gains are zero. Actual context sizes
may differ under the shared ceiling. Original retrieval order is fixture order,
not a measured retrieval system.

The default budget is 100 Unicode word/punctuation units, including source labels.
This reuses the production counter, **not a model tokenizer**. The runner verifies
that generated evidence uses exactly the same units as reconstructed context.
Fixed instructions and question are outside this evidence budget. Provider-reported
input/output tokens include the full prompt and are recorded separately. Changing
the budget creates a separate experiment; it does not alter frozen case budgets.

Each trial runs all methods sequentially, rotating the starting method between
trials. BGE and production evaluation are rerun for each applicable method. Timings
include cold loading when it occurs; there is no warmup or MCP/network evaluator
latency. Selection wall time covers preparation, ranking, evaluation, and
reconstruction. End-to-end wall time additionally includes generation and adapter
overhead. First-call effects and provider stochasticity require repeated trials.

`results.jsonl` retains per-case selections, scores, contexts, evaluator support,
convergence, generated answers, usage, and timings. It checkpoints after each
record in a completed case/trial. `summary.json` reuses held-out aggregation and
adds mean context units and repeated-claim fraction. `manifest.json` records input
hashes, implementation hashes, package versions, estimator, and configuration.
Existing output directories are refused. Interrupted runs retain completed
case/trial records; there is no resume mode.

## Metrics and limits

- Answer accuracy scores actual generated text with existing required/forbidden
  strings. This is an automatic correctness proxy, not a semantic judge. Report
  correct, incorrect, unscored, and failed counts together; unscored is not correct.
- Evidence coverage is labeled supporting-source recall. It does not measure
  completeness of an answer's reasoning or equivalent substitute evidence.
- Redundancy is `1 - distinct mapped claims / selected chunks` (empty is zero).
  It is an annotation-based proxy, not semantic or dependency-weighted redundancy.
- Context units are a size proxy. Generator token usage is provider telemetry.
  Selection and end-to-end latencies are measured wall-clock durations.

Do not infer answer-quality improvements from coverage, support, or redundancy.
Cases and observations are synthetic and manually structured. This experiment
does not measure retrieval, extraction cost, or generalization to real enterprise
traffic. Provider aliases and the existing unpinned BGE adapter can drift; retain
the model cache/snapshot and provider version metadata for a publication run.

## Execution

Prerequisites: repository environment with the locked `benchmarks` dependency
group, BGE weights (or download access), and the selected generator's credentials
and network access. `.venv/bin/python` below uses the existing development
environment; `uv run --locked --group benchmarks python` can provision one.

Focused tests (all offline; semantic ordering and generation use fixtures):

```sh
.venv/bin/python -m pytest research/experiments/applied/context_optimization/test_run.py tests/test_context_reconstruction.py tests/test_client_context_reconstruction.py -q
```

One-case smoke with real reranking and generation:

```sh
HF_HUB_OFFLINE=1 .venv/bin/python -m research.experiments.applied.context_optimization.run \
  --output /tmp/omneum-context-smoke \
  --case enterprise_policy_copy_chain --budget 100 --trials 1 \
  --provider anthropic --model claude-sonnet-5-5
```

Inspect all four statuses before expanding. Generation and selection failures
remain explicit records and count against attempted accuracy. After a successful
smoke, run the same budget on all cases with four trials (384 generations):

```sh
HF_HUB_OFFLINE=1 .venv/bin/python -m research.experiments.applied.context_optimization.run \
  --output /tmp/omneum-context-heldout-b100-t4 --budget 100 --trials 4 \
  --provider anthropic --model claude-sonnet-5-5
```

Four trials balance the starting position across methods. Compare paired per-case
outcomes before testing another budget; this initial runner makes no significance
or answer-quality improvement claim.
