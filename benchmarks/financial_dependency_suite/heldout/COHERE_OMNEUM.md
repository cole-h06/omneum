# Cohere Rerank v4 Pro + Omneum comparison

`cohere_omneum` is opt-in and uses the existing Cohere safe selector
(`rerank-v4.0-pro`) followed by the same `select_omneum` pipeline as
`bge_omneum`. The frozen default method matrix and runner stay unchanged.

When this method is requested, both Cohere routes share a single response for
the same question, ordered candidate pool and relevance depth:
`min(candidate_count, 2 * context_budget)`. Standalone `cohere` takes the first
`context_budget` candidates; `cohere_omneum` applies Omneum selection to that
shortlist with the same final budget. Cases, candidate construction, provenance
mapping, inference, generation, TP/FP/FN definitions and scoring are unchanged.

Successful reranks are reused across routes and trials, and saved atomically in
the new run's `cohere_responses.jsonl`. Resume reloads that file. Other run caches
under `--results-dir` are read only. Legacy Cohere result records are eligible
only when their manifest verifies the current case bytes and their ranked
response contains enough matching candidates and scores. Historical top-budget
responses cannot supply a deeper shortlist; missing scores are never invented.

Both routes record the shared request hash, shortlist and scores, relevance
model/depth, cache hit and original response latency. `cohere_latency_seconds`
counts provider work in this run (zero for reuse). Omneum timing is recorded
separately and included in selection and end-to-end latency.

After paid calls are authorized, run from the repository root:

```sh
.venv/bin/python -m benchmarks.financial_dependency_suite.heldout.run_benchmark \
  --methods cohere cohere_omneum --trials 10
```

This schedules 480 records (24 frozen cases × 2 routes × 10 trials), using the
existing Anthropic answer generator. It requires the existing Cohere and
Anthropic credentials plus the normal local benchmark/Omneum setup. A successful
uncached comparison makes one Cohere rerank per case and 480 generation calls.
The runner prints the new results directory; `--resume PATH` continues that run
with the same methods and trial count.
