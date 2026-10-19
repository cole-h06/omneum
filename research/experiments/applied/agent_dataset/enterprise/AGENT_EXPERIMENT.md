# Enterprise consuming-agent experiment

The playground previously had no consuming LLM. This experiment adds a fixed,
executable policy-assistance workflow with two real local model requests and an
intervening eligibility tool. It uses the existing enterprise fixtures, retrieval
functions, source/claim adapter, dependency configuration, and production client.
It does not run the held-out context-optimization benchmark.

## Inspection findings

| Existing component | Actual execution and evidence mapping |
| --- | --- |
| `../agents/research.py` | Returns three hard-coded policy observations; no research requests. |
| `../agents/search.py` | Returns three hard-coded observations with synthetic document retrieval, citation, and assertion-lineage metadata; no search service. |
| `../agents/sql.py` | Returns three hard-coded observations; does not execute SQL. |
| `../agents/documents.py` | Returns three hard-coded observations; does not read documents. |
| `../agents/api.py` | Returns three hard-coded observations; does not call an API. |
| `../run.py`, `../workflow/pipeline.py` | Sequential or parallel LangGraph collection, validation, and local production evaluation. No model or consuming context boundary. |
| `agents.py`, `retrieve.py`, `workflow.py` | Enterprise LangGraph roots read hash-checked handbook and FAQ sections, execute SQLite queries against `company.sql`, and parse `vendor.json`. These are local synthetic snapshots, not external retrieval. `make_result()` maps records to assertions with source IDs, normalized attributes/values, timestamps, upstream relationships, and retrieval fields. A joined research node copies three parent claims with citations and lineage; it is deterministic. |
| `context_selection.py` | Re-reads snapshots, maps raw chunks to source/assertion/canonical claim IDs, evaluates four selection strategies, and reconstructs context. No model consumption or answer scoring. Existing coverage/support and regex token counts are structural metrics. |

Existing infrastructure supplied provenance validation, controlled timestamps,
manifest hashes, LangGraph orchestration, chunk mappings, production evaluation,
and structural regression tests. Missing pieces were a model transport, model
tokenizer, consuming prompts, task oracle, downstream tool execution, generated
answer evaluation, and per-request usage/latency capture.

The enterprise retrieval workflow is the smallest useful starting point. The new
runner invokes its existing agent functions in stable collection order, including
the parent-dependent research step, rather than invoking the old graph's terminal
local evaluation. `load_chunks()` re-reads the same hash-checked snapshots to retain
raw text. The existing source–claim adapter maps all observations, including derived
claims, to the production observation graph. Raw evidence for derived claims remains
the original source chunks; no aggregate prose is invented.

## Execution path and controls

`agent_experiment.retrieve()` → source/claim adapter →
`OmneumClient.evaluate_context_with_chunks()` over real stdio MCP →
selection and ordering → first LLM policy extraction → deterministic eligibility
tool → second LLM final answer → fixture-oracle scoring.

All three arms use the same task, retrieved records, source/claim mapping, prompts,
local Qwen model digest, temperature 0, seed 42, 256-token output cap, and tools.
Retrieval and Omneum selection are shared within each task to freeze evidence.
Arm execution order rotates across tasks/repeats. No model pulls occur.

* Baseline uses the existing `retrieval` strategy: whole chunks in retrieval order,
  skipping any that do not fit. Its selection ignores Omneum support scores. There
  was no pre-existing consuming-agent baseline; this is the playground's retrieval
  selection convention applied to the new consuming workflow.
* Omneum selection uses the API's default `coverage_support` selection, then restores
  original retrieval order.
* Omneum ranked uses exactly that same selection in descending API utility order,
  retaining retrieval-order ties. The experiment asserts identical ID/text membership.

The raw text stays in client memory and is inserted unchanged, with chunk headers,
into both consuming requests. Only structured observations reach the MCP client;
its production transport transmits opaque source/attribute/claim assertions.
Reliability, claim support, convergence, and dependency evidence are retained in
per-task telemetry. Focused tests inspect the actual MCP calls for absence of raw
text and chunk IDs.

The configurable budget counts evidence plus headers with the resident model's
actual tokenizer. Both evidence orders are counted; if ordering changes the token
count past the ceiling, the shared selection budget is reduced until both fit.
The model's own chat template renders each full request, sent with `raw=true`.
Every full-prompt count must equal runtime `prompt_eval_count`; prompt plus reserved
output must fit the 8192-token window. There is no approximate tokenizer fallback.
The local adapter currently requires one resident Ollama Qwen2 llama-server worker.

The three synthetic customer tasks ask about returns after 10, 20, and 35 days.
Gold policy is explicitly the internal handbook: 30 days, 2 years, customer pays.
The prompt supplies a shared conflict-resolution rule but does not supply gold
values. The final decision must match the task oracle, all three policy fields must
match, and citations must name selected chunks for task success. Citation membership
does not establish entailment. Claim coverage and duplicate mapped-claim occurrences
are explicitly labeled structural proxies, not measured factual quality.

Run from the repository root with the existing environment (httpx, LangGraph,
Omneum native module, bundled MCP and benchmark deployment dependencies installed),
a local Ollama service, the installed `qwen2.5:7b` model, and Cargo dependencies cached:

```sh
.venv/bin/python -m research.experiments.applied.agent_dataset.enterprise.agent_experiment --token-budget 400 --repeats 1 --output research/experiments/applied/agent_dataset/enterprise/results/agent-live-v2
```

Output directories must be new; use another name when reproducing. The command
uses the existing `benchmarks.context_evaluation.deployment.benchmark_deployment`
helper only to launch a disposable test-key daemon and stdio MCP server. It does
not invoke a benchmark runner, use the user's persisted graph, or change production
configuration. Cargo may rebuild the existing test daemon.

```sh
.venv/bin/python -m pytest -q research/experiments/applied/agent_dataset/tests/test_agent_experiment.py research/experiments/applied/agent_dataset/tests/test_context_selection.py tests/test_client_context_reconstruction.py
```

## Saved runs and interpretation

`results/agent-live-v1/` is the initial pilot. The model emitted fenced JSON;
the original parser called `json.loads(text)` directly and returned `{}` on failure.
Consequently the tool received no window and all nine task executions failed. Its
saved scores and outputs are preserved, not re-scored with the corrected parser.
The runner now accepts JSON and complete JSON fences, with focused parser checks.
`results/agent-live-v2/` reruns all three configurations after this repair.

Every run records the exact rendered model request, original selected chunks,
responses, actual input/output usage, model timings, wall-clock timings, and scores.
Each task also records observations, all retrieved chunks, and Omneum telemetry.
Manifests record model identity, options, prompts, fixture/source hashes and tool
availability. `summary.json` gives per-task comparisons and pairwise differences.
The v1 manifest hashes identify the pre-repair parser and pre-summary runner;
the parser difference above is necessary to reproduce that diagnostic pilot.

Selection latency includes MCP evaluation, mapping, tokenizer calls, and both order
checks for Omneum. Both Omneum arms are charged this same shared selection cost;
the ranking comparison therefore does not independently time selection. Baseline
is charged retrieval selection only. End-to-end latency is retrieval plus charged
selection plus actual two-request/tool execution. Startup, model warmup, output
serialization, and post-run scoring are excluded. Runtime prompt caching is
uncontrolled; rotating arm order does not eliminate cache or scheduling effects.

This is a small fixed workflow over synthetic snapshots, not autonomous planning,
live web search, or an enterprise accuracy benchmark. The tasks share one evidence
pool and gold policy. More independent tasks, repetitions, models, tighter budgets,
and citation entailment scoring remain necessary before generalizing.

## Corrected live results

The verification command above passed **23 tests**. A separate artifact audit
checked all nine executions and 18 requests, exact saved context construction,
unchanged code hashes, paired evidence membership, distinct Omneum orderings,
actual versus predicted prompt tokens, options, budgets, usage totals, and summary
reconstruction.

| Metric (mean across 3 tasks) | Baseline | Omneum selection | Omneum ranked |
| --- | ---: | ---: | ---: |
| Task successes | 3/3 | 3/3 | 3/3 |
| Policy-field accuracy | 100% | 100% | 100% |
| Correct eligibility | 3/3 | 3/3 | 3/3 |
| Evidence tokens per request | 376 | 150 | 150 |
| Evidence budget utilization | 94% | 37.5% | 37.5% |
| Actual total input tokens, two requests | 994 | 504 | 490 |
| Actual total output tokens, two requests | 213 | 128 | 100 |
| Selection latency | 30.96 ms | 97.33 ms | 97.33 ms |
| End-to-end latency | 9.661 s | 5.849 s | 4.779 s |
| Distinct mapped claim coverage (proxy) | 5/6 | 6/6 | 6/6 |
| Repeated mapped claim occurrences (proxy) | 6 | 0 | 0 |

| Task | Success, all arms | Baseline latency | Selection latency | Ranked latency |
| --- | --- | ---: | ---: | ---: |
| return-10 | yes | 9.783 s | 5.701 s | 4.743 s |
| return-20 | yes | 9.655 s | 5.871 s | 4.846 s |
| return-35 | yes | 9.544 s | 5.974 s | 4.748 s |

Omneum reduced evidence tokens by **60.1%** in this sample while retaining task
success. The baseline contains nine chunks; both Omneum arms contain the FAQ chunk
and three vendor chunks. The ranked arm moves the vendor shipping chunk before
the vendor return-window and warranty chunks. There is **no observed accuracy gain
from ranking**. Intermediate model outputs differ in citation verbosity, so the
second request's input length and final output lengths also differ, despite the
same evidence budget, prompts, and selected evidence. The evidence itself remains
150 tokens in both orders.

The coverage denominator includes conflicting policy alternatives; greater mapped
coverage does not necessarily mean more relevant or more correct evidence. The
smaller observed latencies are measurements of this warm local run, with differing
output lengths and uncontrolled caches. They do not establish a statistically
reliable speedup or an accuracy improvement. No further generalization was made.
