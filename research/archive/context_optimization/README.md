# Context optimization

This experiment compares four context-selection methods across 24 synthetic held-out cases. Each method selects source chunks under the same context budget before passing them to an LLM.

The experiment uses Omneum's production inference and `reconstruct_context()`. Candidate evidence, BGE reranking, generation, and answer scoring come from `benchmarks/context_evaluation/heldout/`.

## Methods

- `retrieval` — selects chunks in retrieval order.
- `semantic` — selects chunks in BGE reranker order.
- `omneum` — selects chunks using `coverage_support`.
- `semantic_omneum` — uses BGE order to break ties in `coverage_support`.

All four methods receive the same candidates and token budget. The combined method does not combine BGE and Omneum scores.

## Metrics

The runner records answer accuracy, supporting-source recall, repeated-claim redundancy, context size, token usage, and latency.

Answer accuracy uses the held-out string scorer. Context budgets use word/punctuation units, not model tokens.

Per-case results are written to `results.jsonl`, with aggregate metrics in `summary.json` and run metadata in `manifest.json`.

## Execution

Run a single case from the repository root:

```bash
HF_HUB_OFFLINE=1 .venv/bin/python -m research.experiments.applied.context_optimization.run \
  --output /tmp/omneum-context-smoke \
  --case enterprise_policy_copy_chain --budget 100 --trials 1 \
  --provider anthropic --model claude-sonnet-5-5
```

Run all 24 cases with four trials:

```bash
HF_HUB_OFFLINE=1 .venv/bin/python -m research.experiments.applied.context_optimization.run \
  --output /tmp/omneum-context-heldout-b100-t4 \
  --budget 100 --trials 4 \
  --provider anthropic --model claude-sonnet-5-5
```