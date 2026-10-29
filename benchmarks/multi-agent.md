# Multi-Agent Systems

Multi-agent evaluation for the Omneum Cross-Domain Context Curation Benchmark.

Four synthetic cases test context selection for circular agent references, independent reasoning errors, task-inapplicable evidence, and repeated subagent outputs.

**4 cases · 31 candidate passages · 6 Qwen-token budgets · 13 budgeted configurations**

[Leaderboard](leaderboard.md) | [Benchmark README](README.md) | [Dataset](context_selection/synthetic/DATASET.md) | [Saved Results](context_selection/synthetic/results/)

## Quick Start

Run from the Omneum repository root.

```bash
# Run offline benchmark tests
.venv/bin/python tools/run_context_evaluation_tests.py -q

# Inspect the final benchmark results
cat \
  benchmarks/context_selection/synthetic/results/budget-exhaustion-recovery-20261026-v2/report.md
```

The offline tests exercise benchmark contracts and local evaluation components. The saved benchmark artifacts contain the recorded selections and metrics. Inspecting these artifacts does not generate new model responses.

## Cases

| Case | Candidates | Token Budgets | Expected behavior |
|---|---:|---|---|
| [`multi_agent_feedback_loop`](#multi_agent_feedback_loop) | 8 | 64–256 | Reject circular approval claims contradicted by release-gate state |
| [`multi_agent_independent_error`](#multi_agent_independent_error) | 6 | 64–256 | Reject independently repeated HTTP unit errors |
| [`multi_agent_relevant_wrong_task`](#multi_agent_relevant_wrong_task) | 9 | 64–256 | Select production upload lifecycle evidence, not staging values |
| [`multi_agent_repeated_subagent`](#multi_agent_repeated_subagent) | 8 | 64–256 | Prefer actual dispatch records over repeated planned-date estimates |

Each case uses a fixed candidate pool, relevance labels, canonical claims, and source-provenance annotations.

The six selection budgets are **64, 96, 128, 160, 192, and 256 Qwen tokens**, measured against reconstructed original passage text.

## Recorded Results

The final benchmark evaluation measures context selection across all four Multi-Agent Systems cases and six token budgets.

The evaluated configurations include standalone BM25, MiniLM, BGE, Cohere, Claude Sonnet 5.5, GPT-6 Astra, Gemini 3.8 Flash, standalone Omneum, and four reranker + Omneum hybrids. Original-order budgeted RAG and unbudgeted full-context RAG provide additional reference configurations.

| Metric | Measurement |
|---|---|
| Selection precision | Fraction of selected sources annotated as supporting |
| Selection recall | Fraction of annotated supporting sources retained |
| Evidence retention | Retained annotated evidence spans |
| Claim coverage | Canonical claims represented in supporting passages |
| Origin coverage | Annotated root-origin units retained |
| Qwen tokens | Token count of reconstructed context |
| Selection latency | Recorded local selection execution time |

The final domain-level measurements are stored in the benchmark result artifacts. The earlier fixed-source-budget results are not interchangeable with these token-budgeted measurements.

The final Omneum hybrid results incorporate deferred-candidate budget-exhaustion recovery. This allows additional positive-utility candidates to be considered after the initial discovery neighborhood is exhausted, subject to the remaining token budget and marginal utility-density threshold.

## `multi_agent_feedback_loop`

**Task:** Determine whether build Aster 118 can pass release gate RG-2.

```text
Can the orchestrator mark build Aster 118 approved
for production under release gate RG-2?
```

### Fixture

```text
8 candidates
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

The benchmark evaluates selected passages against the five annotated supporting sources.

| Source | Evidence | Relevance |
|---|---|---|
| `researcher_agent` | Approval claim referencing reviewer | Not supporting |
| `analyst_agent` | Approval claim referencing researcher | Not supporting |
| `reviewer_agent` | Approval claim referencing analyst | Not supporting |
| `tool_result` | Failed release-gate load test | Supporting |
| `database_result` | No recorded override | Supporting |
| `web_result` | Blocked release portal | Supporting |
| `verifier_agent` | Verification using gate CLI and registry | Supporting |
| `api_result` | Blocked release-gate API | Supporting |

The final saved selections identify which sources each method retained at each token budget.

**Result:** The case evaluates whether the selector retains operational evidence showing the blocked release gate instead of treating circular agent approval claims as independent authorization.

Omneum's provenance-aware graph inference accounts for shared evidence origins and dependencies between sources when computing source reliability and claim support. The verifier agent's conclusion derives from the gate CLI and registry rather than an independent release-gate observation.

## `multi_agent_independent_error`

**Task:** Interpret an HTTP `Retry-After` header before retrying a failed invoice API request.

```text
For the current EU invoice API, how should the orchestrator
interpret a 429 response with Retry-After: 120 before retrying?
```

### Fixture

```text
6 candidates
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

| Source | Evidence | Relevance |
|---|---|---|
| `researcher_agent` | Incorrect 120-millisecond interpretation | Not supporting |
| `analyst_agent` | Incorrect 120-millisecond interpretation | Not supporting |
| `specialist_agent` | Incorrect 120-millisecond interpretation | Not supporting |
| `tool_result` | HTTP conformance test | Supporting |
| `api_result` | Invoice API schema | Supporting |
| `database_result` | Integration trace | Supporting |

The final benchmark artifacts record source retention at each token budget.

**Result:** The case evaluates whether context selection retains the API schema, conformance test, and operational trace rather than three independently incorrect agent interpretations.

The three agents have no shared upstream output, so their agreement cannot be discounted solely through source-dependency signals. Independent support does not establish that an assertion correctly interprets HTTP semantics.

## `multi_agent_relevant_wrong_task`

**Task:** Determine how long production retains an unfinished multipart upload before aborting it.

```text
How long does the production Helix upload API retain
an unfinished multipart upload before aborting it?
```

### Fixture

```text
9 candidates
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

| Source | Evidence | Relevance |
|---|---|---|
| `researcher_agent` | Audit-log retention | Not supporting |
| `code_agent` | Staging multipart cleanup | Not supporting |
| `analyst_agent` | Staging object expiry | Not supporting |
| `operations_agent` | Production multipart abort | Supporting |
| `tool_result` | Production lifecycle inspection | Supporting |
| `tool_result_2` | Upload bearer-token lifetime | Not supporting |
| `api_result` | Production lifecycle API | Supporting |
| `database_result` | Production cleanup configuration | Supporting |
| `reviewer_agent` | Signed download-link lifetime | Not supporting |

The final benchmark selections are evaluated against the four production-specific supporting sources.

**Result:** The case tests whether context selection distinguishes the requested production multipart-upload lifecycle from staging cleanup and other operational time limits.

A staging configuration may be accurate for its own environment while remaining irrelevant to the production question.

The earlier fixed-source-budget evaluation exposed this failure mode when BGE + Omneum retained the staging `code_agent` passage alongside production evidence. That observation identifies the behavior under test; it is not a substitute for the final token-budgeted case measurements.

Source reliability from provenance-aware graph inference does not, by itself, establish whether a passage applies to the requested environment. `prepare_context()` also uses question relevance and incremental claim coverage when selecting passages.

## `multi_agent_repeated_subagent`

**Task:** Determine the actual dispatch date for order OR-821.

```text
For order OR-821, what dispatch date should the orchestrator
give the customer from the current fulfillment records?
```

### Fixture

```text
8 candidates
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

| Source | Evidence | Relevance |
|---|---|---|
| `researcher_agent` | Planned August 22 dispatch | Not supporting |
| `analyst_agent` | Reused planned-date estimate | Not supporting |
| `analyst_agent_2` | Reused planned-date estimate | Not supporting |
| `summary_agent` | Aggregated planned-date estimates | Not supporting |
| `tool_result` | Actual carrier handoff | Supporting |
| `database_result` | Actual fulfillment dispatch | Supporting |
| `verifier_agent` | Verification from carrier and database | Supporting |
| `web_result` | Cached planned dispatch | Not supporting |

The final benchmark evaluation records whether selected context retains the actual-dispatch evidence at each token budget.

**Result:** The case evaluates repeated subagent outputs and stale planned-date information against current operational dispatch records.

The verifier agent derives its conclusion from the carrier scan and fulfillment database. The repeated analyst and summary outputs derive from the same planned-date estimate. Omneum's provenance-aware graph inference accounts for these shared evidence origins when computing source reliability and claim support.

The earlier fixed-source-budget evaluation retained the cached planned date alongside actual dispatch records. The final benchmark results must be used to determine whether that behavior persists under the token-budgeted selection policy.

## Inspect Recorded Runs

Authoritative benchmark artifact directories:

```text
benchmarks/context_selection/synthetic/
├── results/
│   ├── tier1-production-20261025-v1/
│   ├── tier1-competitors-20261025-v1/
│   └── budget-exhaustion-recovery-20261026-v2/
└── analysis/
    └── tier1-competitive-analysis-20261026-v1/
```

These directories contain phases of the same cross-domain evaluation, not separate benchmark datasets.

### Inspect Multi-Agent Attempts

List the final result artifacts:

```bash
ls \
  benchmarks/context_selection/synthetic/results/budget-exhaustion-recovery-20261026-v2/
```

Find the four Multi-Agent Systems cases:

```bash
rg -n \
  'multi_agent_feedback_loop|multi_agent_independent_error|multi_agent_relevant_wrong_task|multi_agent_repeated_subagent' \
  benchmarks/context_selection/synthetic/results/budget-exhaustion-recovery-20261026-v2/
```

The matching records identify the case-specific selections and metrics saved in the final evaluation.

### Inspect All Recorded Comparisons

Inspect the final evaluation report:

```bash
cat \
  benchmarks/context_selection/synthetic/results/budget-exhaustion-recovery-20261026-v2/report.md
```

Inspect the competitive analysis:

```bash
cat \
  benchmarks/context_selection/synthetic/analysis/tier1-competitive-analysis-20261026-v1/report.md
```

Inspect the case-level and domain-level comparison artifacts:

```bash
find \
  benchmarks/context_selection/synthetic/results/budget-exhaustion-recovery-20261026-v2/ \
  -maxdepth 1 -type f | sort
```

The paired analysis compares the final hybrid selections against their recorded standalone and initial hybrid counterparts.

### Inspect the Published Results

Inspect the saved evaluation artifacts without issuing provider requests:

```bash
ls \
  benchmarks/context_selection/synthetic/results/tier1-production-20261025-v1/

ls \
  benchmarks/context_selection/synthetic/results/tier1-competitors-20261025-v1/

ls \
  benchmarks/context_selection/synthetic/results/budget-exhaustion-recovery-20261026-v2/
```

The final results incorporate the corrected deferred-candidate recovery for Omneum hybrid configurations.

Saved selections and metric records are the source of the published measurements. Re-reading them does not reproduce external model inference.

## Evaluation Notes

| Setting | Value |
|---|---|
| Cases | 4 |
| Candidate passages | 31 total |
| Candidate pools | 6–9 passages per case |
| Selection budgets | 64, 96, 128, 160, 192, 256 Qwen tokens |
| Tokenizer | Qwen2.5 7B GGUF |
| Budgeted configurations | 13 |
| Unbudgeted reference | `raw_full` |
| Initial rankers | BM25, MiniLM, BGE Reranker v2-m3, Cohere Rerank v4.0 Pro |
| Frontier judges | Claude Sonnet 5.5, GPT-6 Astra, Gemini 3.8 Flash |
| Omneum entry point | `prepare_context()` |
| Selection objective | `coverage_support_density` |
| Complementary evidence | `complementary_evidence=True` |
| Token cost exponent | `token_cost_exponent=1` |
| Discovery anchors | 3 plus relevance-score ties |
| Discovery expansion | Depth 2 |
| Deferred-candidate recovery | Enabled for final hybrid results |
| Conflict-aware selection | `conflict_aware=False` |
| Selection scoring | Annotated supporting-source IDs |
| Evidence scoring | Retained annotated evidence |
| Claim scoring | Canonical claims represented in supporting passages |
| Origin scoring | Annotated root-origin units |
| Latency aggregation | Recorded local selection p50 and p95 |

Omneum's provenance-aware graph inference iteratively computes source reliability and claim support across a bipartite graph, accounting for shared evidence origins and dependencies between sources.

The SDK maps finalized claim support to retrieved chunks through their associated claim IDs. `prepare_context()` uses question relevance and incremental claim coverage to select and reconstruct original passages within the configured token budget.

The final recovery allows deferred candidates to be reconsidered when the initial discovery neighborhood exhausts positive, budget-feasible utility. Candidates must satisfy the marginal utility-density threshold and exact remaining-budget constraint.

### Selection Latency

The final aggregate local selection timings across all six domains are:

| Configuration | Selection p50 | Selection p95 |
|---|---:|---:|
| Omneum Standalone | 194.86ms | 451.87ms |
| BM25 + Omneum | 207.79ms | 461.25ms |
| MiniLM + Omneum | 203.84ms | 465.36ms |
| BGE + Omneum | 200.63ms | 430.51ms |
| Cohere + Omneum | 206.89ms | 480.37ms |

These are all-domain measurements, not Multi-Agent Systems-specific latency percentiles.

The local selection interval excludes external ranking inference and structured observation extraction. Frontier judge inference has a different timing boundary.

### Interpretation

The four cases test distinct failure mechanisms:

- **Feedback loop:** Circular agent approval claims conflict with operational release-gate state.
- **Independent error:** Three independently produced agent responses make the same HTTP unit error.
- **Relevant wrong task:** A staging configuration describes a related operation but does not answer the production question.
- **Repeated subagent:** Several agent outputs repeat a planned dispatch estimate while operational records establish the actual date.

The first and fourth cases contain explicit source dependencies. The second tests incorrect agreement without shared upstream information. The third tests task applicability rather than source dependence.

Selection precision and recall measure retained supporting sources. Evidence retention, claim coverage, and origin coverage measure complementary properties of the reconstructed context.

The evaluation uses synthetic candidate pools and supplied structured `Observation` objects. It does not measure live multi-agent execution, open-ended retrieval, or downstream answer correctness.

The final domain-level comparisons should be read from the saved benchmark results rather than the superseded fixed-source-budget experiment.

For complete methodology and aggregate results, see [Benchmark README](README.md) and [Leaderboard](leaderboard.md).