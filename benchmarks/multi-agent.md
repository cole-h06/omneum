
# Multi-Agent Systems

Context-selection benchmark for multi-agent workflows. Tests circular agent references, independent reasoning errors, task-inapplicable evidence, and repeated subagent outputs.

**4 held-out cases · 31 candidate sources · Claude Sonnet 5.5 generator**

[Leaderboard](leaderboard.md) | [Benchmark README](README.md) | [Dataset](context_evaluation/heldout/DATASET.md) | [Saved Results](context_evaluation/heldout/results/)

## Quick Start

Run from the Omneum repository root.

```bash
# Validate all 24 held-out cases, including the four multi-agent cases
.venv/bin/python -m benchmarks.context_evaluation.heldout.validate_dataset

# Run offline benchmark tests
.venv/bin/python tools/run_context_evaluation_tests.py -q

# Verify saved publication metrics
.venv/bin/python -m benchmarks.context_evaluation.heldout.build_dashboard_summary --check
```

No provider calls. These commands validate the frozen dataset, execute offline tests, and check published metrics against saved artifacts. They do not generate new model responses.

Latest verified test result:

```text
572 passed, 15 skipped
```

## Cases

| Case | Candidates | Budget | Expected behavior |
|---|---:|---:|---|
| [`multi_agent_feedback_loop`](#multi_agent_feedback_loop) | 8 | 3 | Reject circular approval claims contradicted by release-gate state |
| [`multi_agent_independent_error`](#multi_agent_independent_error) | 6 | 2 | Reject independently repeated HTTP unit errors |
| [`multi_agent_relevant_wrong_task`](#multi_agent_relevant_wrong_task) | 9 | 3 | Select production upload lifecycle evidence, not staging values |
| [`multi_agent_repeated_subagent`](#multi_agent_repeated_subagent) | 8 | 3 | Prefer actual dispatch records over repeated planned-date estimates |

Each case uses a fixed candidate pool, relevance labels, and a selection budget.

## Recorded Results

BGE + Omneum results below use the 10-trial GPT-6 Astra pairing. Claude and Cohere comparisons use one trial per case.

| Case | BGE + Omneum Precision | Recall | Answer | Selection p50 |
|---|---:|---:|---|---:|
| Feedback loop | 100% | 60% | 10/10 correct | 0.641s |
| Independent error | 100% | 66.7% | 10/10 correct | 0.721s |
| Relevant wrong task | 66.7% | 50% | 10/10 correct | 0.709s |
| Repeated subagent | 66.7% | 66.7% | 10/10 correct | 0.636s |

Omneum matched the BGE + LLM judges' selection precision and recall on three cases. In `multi_agent_relevant_wrong_task`, its selection precision and recall were lower.

Selection precision and recall use fixture relevance labels. `unscored` is a separate recorded answer status, not an incorrect-answer verdict.

## `multi_agent_feedback_loop`

**Task:** Determine whether build Aster 118 can pass release gate RG-2.

```text
Can the orchestrator mark build Aster 118 approved
for production under release gate RG-2?
```

### Fixture

```text
8 candidates
3 selected
5 relevant

researcher_agent     Claims approved; cites reviewer
analyst_agent        Claims approved; relies on researcher
reviewer_agent       Claims approved; relies on analyst
tool_result          Gate CLI: load_test failed
database_result      Release registry: no override
web_result           Release portal: blocked
verifier_agent       Checks gate CLI and registry
api_result           Release-gate API: blocked
```

Three agents claim that Aster 118 is approved. Their references form a cycle:

```text
researcher_agent (approved)
       |
       v
analyst_agent (approved)
       |
       v
reviewer_agent (approved)
       |
       +------> researcher_agent
```

The approval loop contains no independent release-gate authorization.

The operational records instead establish that **RG-2 is blocked**.

Gate CLI evidence:

```text
build: Aster 118
gate: RG-2
status: blocked
failed_check: load_test
```

Release registry:

```sql
SELECT override_id
FROM release_registry
WHERE build_id = 'Aster 118'
  AND gate_id = 'RG-2';

-- override_id: NULL
```

The API and release portal also report the blocked state. The verifier agent derives its conclusion from the gate CLI and registry.

The five relevant sources are:

```text
tool_result
database_result
web_result
verifier_agent
api_result
```

**Expected answer:** No. Aster 118 cannot be marked approved while RG-2 is blocked by the failed load test and no override is recorded.

### Recorded Selections

| Method | Trials | Selected sources | P | R | Answer | Selection p50 |
|---|---:|---|---:|---:|---|---:|
| BGE + Claude Judge | 1 | `tool_result`, `database_result`, `web_result` | 100% | 60% | 1/1 correct | 2.136s |
| BGE + GPT-6 Astra Judge | 10 | Same | 100% | 60% | 10/10 correct | 2.878s |
| BGE + Gemini Judge | 10 | `tool_result`, `web_result`, `database_result` | 100% | 60% | 10/10 correct | 10.108s |
| **BGE + Omneum** | **10** | `verifier_agent`, `tool_result`, `web_result` | **100%** | **60%** | **10/10 correct** | **0.641s** |
| Cohere + Claude Judge | 1 | `database_result`, `tool_result`, `verifier_agent` | 100% | 60% | 1/1 correct | 1.422s |
| Cohere + Omneum | 1 | `database_result`, `tool_result`, `web_result` | 100% | 60% | 1/1 correct | 0.578s |

**Result:** Every configuration excluded the circular approval claims and selected evidence showing the gate was blocked.

Omneum matched judge precision, recall, and recorded answer correctness at lower selection latency.

Its BGE selection included `verifier_agent`, whose conclusion derives from the operational records. Therefore, the selected evidence is relevant but not necessarily fully independent.

## `multi_agent_independent_error`

**Task:** Interpret an HTTP `Retry-After` header before retrying a failed invoice API request.

```text
For the current EU invoice API, how should the orchestrator
interpret a 429 response with Retry-After: 120 before retrying?
```

### Fixture

```text
6 candidates
2 selected
3 relevant

researcher_agent     Interprets 120 as milliseconds
analyst_agent        Interprets 120 as milliseconds
specialist_agent     Interprets 120 as milliseconds
tool_result          HTTP conformance test: 120 seconds
api_result           Invoice API schema: 120 seconds
database_result      Integration trace: 120-second interval
```

Three isolated agents independently make the same unit-conversion error.

```text
researcher_agent  ──> 120 milliseconds
analyst_agent     ──> 120 milliseconds
specialist_agent  ──> 120 milliseconds
```

Their agreement is not explained by copied responses or shared agent output.

The correct interpretation is **120 seconds**.

HTTP response:

```http
HTTP/1.1 429 Too Many Requests
Retry-After: 120
```

The numeric `Retry-After` value represents a delay in seconds.

The integration trace provides an independent operational check:

```text
Request rejected: 10:00:00
Retry permitted:  10:02:00

Elapsed: 120 seconds
```

The three relevant sources are:

```text
tool_result
api_result
database_result
```

**Expected behavior:** Wait at least 120 seconds before retrying, not 120 milliseconds.

### Recorded Selections

| Method | Trials | Selected sources | P | R | Answer | Selection p50 |
|---|---:|---|---:|---:|---|---:|
| BGE + Claude Judge | 1 | `api_result`, `tool_result` | 100% | 66.7% | 1/1 unscored | 1.414s |
| BGE + GPT-6 Astra Judge | 10 | Same | 100% | 66.7% | 7/10 correct; 3 unscored | 2.351s |
| BGE + Gemini Judge | 10 | Same | 100% | 66.7% | 6/10 correct; 4 unscored | 8.501s |
| **BGE + Omneum** | **10** | `api_result`, `database_result` | **100%** | **66.7%** | **10/10 correct** | **0.721s** |
| Cohere + Claude Judge | 1 | `api_result`, `tool_result` | 100% | 66.7% | 1/1 correct | 2.300s |
| Cohere + Omneum | 1 | `api_result`, `tool_result` | 100% | 66.7% | 1/1 correct | 0.649s |

**Result:** All configurations excluded the three independently incorrect agent interpretations.

The BGE judges selected the API schema and conformance test. BGE + Omneum selected the API schema and integration trace.

Both sets establish the correct 120-second delay.

Omneum's ten answers were scored correct. The judges' `unscored` responses cannot be treated as incorrect without additional adjudication.

This case also demonstrates a limitation of dependency-only reasoning: independent agents can produce the same incorrect assertion without sharing upstream information.

## `multi_agent_relevant_wrong_task`

**Task:** Determine how long production retains an unfinished multipart upload before aborting it.

```text
How long does the production Helix upload API retain
an unfinished multipart upload before aborting it?
```

### Fixture

```text
9 candidates
3 selected
4 relevant

researcher_agent     Audit-log retention: 24 hours
code_agent           Staging multipart cleanup: 2 hours
analyst_agent        Staging object expiry: 7 days
operations_agent     Production multipart abort: 48 hours
tool_result          Production lifecycle inspection: 48 hours
tool_result_2        Upload bearer-token lifetime: 1 hour
api_result           Production lifecycle API: 48 hours
database_result      Production cleanup configuration: 48 hours
reviewer_agent       Signed download-link lifetime: 24 hours
```

The production Helix upload API aborts unfinished multipart uploads after **48 hours**.

Several candidate sources contain legitimate timing values, but they govern different environments or operations.

| Source | Value | Applies to |
|---|---:|---|
| `researcher_agent` | 24h | Audit-log retention |
| `code_agent` | 2h | Staging multipart cleanup |
| `analyst_agent` | 7 days | Staging object expiry |
| `operations_agent` | 48h | Production multipart abort |
| `tool_result` | 48h | Production lifecycle inspection |
| `tool_result_2` | 1h | Upload bearer-token lifetime |
| `api_result` | 48h | Production lifecycle API |
| `database_result` | 48h | Production cleanup job |
| `reviewer_agent` | 24h | Signed download-link lifetime |

Production lifecycle configuration:

```yaml
environment: production
multipart_upload:
  abort_incomplete_after_hours: 48
```

Staging cleanup configuration:

```yaml
environment: staging
multipart_upload:
  abort_incomplete_after_hours: 2
```

These snippets illustrate the competing configuration values represented in the fixture.

The four relevant sources are:

```text
operations_agent
tool_result
api_result
database_result
```

**Expected answer:** 48 hours.

### Recorded Selections

| Method | Trials | Selected sources | P | R | Answer | Selection p50 |
|---|---:|---|---:|---:|---|---:|
| BGE + Claude Judge | 1 | `api_result`, `tool_result`, `database_result` | 100% | 75% | 1/1 correct | 1.529s |
| BGE + GPT-6 Astra Judge | 10 | Same | 100% | 75% | 10/10 correct | 3.779s |
| BGE + Gemini Judge | 10 | `operations_agent`, `api_result`, `tool_result` | 100% | 75% | 10/10 correct | 9.468s |
| **BGE + Omneum** | **10** | `operations_agent`, `code_agent`, `api_result` | **66.7%** | **50%** | **10/10 correct** | **0.709s** |
| Cohere + Claude Judge | 1 | `api_result`, `tool_result`, `database_result` | 100% | 75% | 1/1 correct | 1.691s |
| Cohere + Omneum | 1 | `operations_agent`, `database_result`, `tool_result` | 100% | 75% | 1/1 correct | 0.658s |

Some judge trials vary source ordering without changing the selected sets.

**Result:** BGE + Omneum selected the staging `code_agent` result alongside two relevant production sources.

This reduced selection precision to **66.7%** and recall to **50%**, compared with **100% precision and 75% recall** for the BGE + LLM judges.

Claude Sonnet 5.5 nevertheless generated the correct 48-hour answer in all ten Omneum trials.

The correct answer does not eliminate the selection error: the generator received both the staging two-hour value and production 48-hour evidence.

Cohere + Omneum selected three relevant production sources in its single recorded trial.

This is the clearest selection-quality weakness in the Multi-Agent Systems subset. Structural source reliability does not automatically establish applicability to the requested environment or task.

## `multi_agent_repeated_subagent`

**Task:** Determine the actual dispatch date for order OR-821.

```text
For order OR-821, what dispatch date should the orchestrator
give the customer from the current fulfillment records?
```

### Fixture

```text
8 candidates
3 selected
3 relevant

researcher_agent     Planned dispatch: Aug 22
analyst_agent        Reuses researcher estimate
analyst_agent_2      Reuses researcher estimate
summary_agent        Merges analyst estimates
tool_result          Carrier handoff: Aug 19
database_result      Fulfillment record: Aug 19
verifier_agent       Confirms actual dispatch: Aug 19
web_result           Cached planned dispatch: Aug 22
```

The researcher reports a planned dispatch date of August 22, 2026.

Two analyst runs reuse that output, and a summary agent combines their responses.

```text
researcher_agent (planned Aug 22)
       |
       +------------------+
       |                  |
       v                  v
analyst_agent       analyst_agent_2
       |                  |
       +--------+---------+
                |
                v
         summary_agent
         (planned Aug 22)
```

These agent outputs are not independent confirmations of actual dispatch.

The carrier scan and fulfillment database establish that OR-821 was **dispatched August 19, 2026, at 16:42 UTC**.

Fulfillment record:

```text
order_id: OR-821
status: dispatched
dispatched_at: 2026-08-19T16:42:00Z
```

The verifier agent reports the same actual dispatch date using the carrier scan and fulfillment record.

The three relevant sources are:

```text
tool_result
database_result
verifier_agent
```

The cached portal result remains an estimate, not a completed dispatch event.

**Expected answer:** August 19, 2026.

### Recorded Selections

| Method | Trials | Selected sources | P | R | Answer | Selection p50 |
|---|---:|---|---:|---:|---|---:|
| BGE + Claude Judge | 1 | `database_result`, `tool_result`, `web_result` | 66.7% | 66.7% | 1/1 correct | 2.133s |
| BGE + GPT-6 Astra Judge | 10 | Same | 66.7% | 66.7% | 10/10 correct | 2.725s |
| BGE + Gemini Judge | 10 | `database_result`, `tool_result`, `web_result` (6/10); `database_result`, `summary_agent`, `tool_result` (4/10) | 66.7% | 66.7% | 10/10 correct | 12.284s |
| **BGE + Omneum** | **10** | `web_result`, `database_result`, `tool_result` | **66.7%** | **66.7%** | **10/10 correct** | **0.636s** |
| Cohere + Claude Judge | 1 | `database_result`, `tool_result`, `web_result` | 66.7% | 66.7% | 1/1 correct | 2.484s |
| Cohere + Omneum | 1 | `database_result`, `web_result`, `tool_result` | 66.7% | 66.7% | 1/1 correct | 1.611s |

The Gemini selections include ordering variations.

**Result:** Omneum and the judges generally selected the two actual-dispatch records alongside an outdated planned-date source.

Gemini selected the summary agent's outdated estimate in four trials rather than the cached portal entry.

All configurations achieved the same selection precision, recall, and recorded answer correctness.

Omneum did not select the relevant verifier agent and retained the cached planned date. The result therefore does not demonstrate complete removal of repeated or stale context.

## Inspect Recorded Runs

Authoritative run directories:

```text
benchmarks/context_evaluation/heldout/results/
├── bge-claude-vs-bge-omneum-20261008/
├── bge-openai-vs-bge-omneum-20261008/
├── bge-google-vs-bge-omneum-20261008/
└── cohere-claude-vs-cohere-omneum-20261008/
```

### Inspect Multi-Agent Attempts

```bash
# List available result artifacts
ls benchmarks/context_evaluation/heldout/results/bge-openai-vs-bge-omneum-20261008/

# Find the four multi-agent case records
rg -n \
  'multi_agent_feedback_loop|multi_agent_independent_error|multi_agent_relevant_wrong_task|multi_agent_repeated_subagent' \
  benchmarks/context_evaluation/heldout/results/bge-openai-vs-bge-omneum-20261008/results.jsonl
```

Extract matching JSONL records:

```bash
rg \
  'multi_agent_feedback_loop|multi_agent_independent_error|multi_agent_relevant_wrong_task|multi_agent_repeated_subagent' \
  benchmarks/context_evaluation/heldout/results/bge-openai-vs-bge-omneum-20261008/results.jsonl \
  > /tmp/multi-agent-results.jsonl
```

Count extracted records:

```bash
wc -l /tmp/multi-agent-results.jsonl
```

The extracted line count depends on the saved attempt serialization. It is not a count of independent cases.

### Inspect All Recorded Comparisons

```bash
for run in \
  bge-claude-vs-bge-omneum-20261008 \
  bge-openai-vs-bge-omneum-20261008 \
  bge-google-vs-bge-omneum-20261008 \
  cohere-claude-vs-cohere-omneum-20261008
do
  echo "===== $run ====="

  rg -c \
    'multi_agent_feedback_loop|multi_agent_independent_error|multi_agent_relevant_wrong_task|multi_agent_repeated_subagent' \
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

Regenerate it from saved artifacts:

```bash
.venv/bin/python -m benchmarks.context_evaluation.heldout.build_dashboard_summary
```

Regeneration does not make provider calls or reproduce the original model responses.

## Evaluation Notes

| Setting | Value |
|---|---|
| Cases | 4 |
| Candidate sources | 31 total |
| Candidate pools | 6–9 sources per case |
| Selection budgets | 2–3 sources |
| Generator | Claude Sonnet 5.5 |
| Initial rerankers | BGE Reranker v2-m3, Cohere Rerank v4.0 Pro |
| Frontier judges | Claude Sonnet 5.5, GPT-6 Astra, Gemini 3.8 Flash |
| BGE + GPT-6 / Gemini | 10 trials per case |
| BGE + Omneum | 10 trials per case in each paired run |
| Claude / Cohere comparisons | 1 trial per case |
| Latency aggregation | Median across recorded trials |
| Selection scoring | Fixture relevance labels |

BGE + Omneum appears in multiple paired-run artifacts. The tables use its GPT-6 Astra pairing rather than pooling repeated executions into additional cases.

### Selection Latency

Median selection latency in seconds:

| Case | GPT-6 Astra Judge | Gemini Judge | Omneum |
|---|---:|---:|---:|
| Feedback Loop | 2.878s | 10.108s | 0.641s |
| Independent Error | 2.351s | 8.501s | 0.721s |
| Relevant Wrong Task | 3.779s | 9.468s | 0.709s |
| Repeated Subagent | 2.725s | 12.284s | 0.636s |

Omneum recorded lower selection latency in all four cases.

### Interpretation

The four cases expose distinct behavior:

- **Feedback loop:** Omneum excluded circular approval claims and selected the blocked release-gate evidence.
- **Independent error:** Omneum rejected three independently incorrect agent interpretations.
- **Relevant wrong task:** BGE + Omneum selected a staging configuration for a production question, reducing precision and recall relative to the LLM judges.
- **Repeated subagent:** Omneum and the judges selected actual dispatch records but retained one outdated planned-date source.

**The measured advantage is consistent selection speed. The measured selection-quality outcome is three cases matching the judges and one case where BGE + Omneum performs worse.**

These synthetic fixtures do not establish performance in live multi-agent deployments, under larger context graphs, or with different provenance and reranker distributions.

The methods may receive different structural metadata. Precision and recall measure selected-source relevance, not dependency-estimator accuracy.

For the complete evaluation methodology and live execution requirements, see [Benchmark README](README.md).
