# Support & Operations Agents

Support and operations evaluation for the Omneum Cross-Domain Context Curation Benchmark.

Four synthetic cases test context selection for incident recovery, conflicting remediation instructions, stale runbooks, and circular ticket references.

**4 cases · 30 candidate passages · 6 Qwen-token budgets · 13 budgeted configurations**

[Leaderboard](leaderboard.md) | [Benchmark README](README.md) | [Dataset](context_selection/synthetic/DATASET.md) | [Saved Results](context_selection/synthetic/results/)

## Quick Start

Run from the Omneum repository root.

```bash
# Run offline benchmark tests
.venv/bin/python tools/run_context_evaluation_tests.py -q

# Inspect the final benchmark results
cat benchmarks/context_selection/synthetic/results/budget-exhaustion-recovery-20261026-v2/report.md
```

The offline tests exercise benchmark components without issuing new provider inference requests. The saved benchmark artifacts contain the recorded selections and metrics.

## Cases

| Case | Candidates | Token Budgets | Expected behavior |
|---|---:|---|---|
| [`support_clean_resolution`](#support_clean_resolution) | 7 | 64–256 | Resume the Marlin export worker |
| [`support_resolution_conflict`](#support_resolution_conflict) | 7 | 64–256 | Restore the previous Opal trust bundle without disabling TLS verification |
| [`support_stale_runbook`](#support_stale_runbook) | 8 | 64–256 | Refresh the Nimbus v5 credential cache |
| [`support_ticket_reference_loop`](#support_ticket_reference_loop) | 8 | 64–256 | Resume the Vega ingest consumer without purging queued records |

Each case uses a fixed candidate pool, source-level relevance labels, canonical claims, and provenance annotations.

The six budgets are **64, 96, 128, 160, 192, and 256 Qwen tokens**. Budget enforcement applies to reconstructed original passage text rather than a fixed number of selected sources.

## Recorded Results

The final evaluation measures selection precision, recall, evidence retention, claim coverage, root-origin coverage, context token usage, and selection latency.

The following are the final corrected **Support & Operations domain averages**, aggregated across four cases and six token budgets.

| Configuration | Precision ↑ | Recall ↑ | Evidence Retention ↑ | Claim Coverage ↑ | Origin Coverage ↑ | Qwen Tokens ↓ |
|---|---:|---:|---:|---:|---:|---:|
| Omneum Standalone | **77.79%** | **56.31%** | **56.99%** | **69.25%** | **62.22%** | 128.33 |
| BM25 + Omneum | 72.94% | 46.99% | 48.40% | 51.01% | 54.38% | 109.63 |
| MiniLM + Omneum | 71.03% | 46.25% | 46.94% | 53.45% | 49.44% | 114.08 |
| BGE + Omneum | 75.82% | 53.45% | 54.10% | 60.77% | 60.28% | 120.00 |
| Cohere + Omneum | 71.32% | 43.33% | 44.37% | 41.70% | 44.31% | 107.21 |

These are domain-level means, not per-case results or downstream answer accuracy measurements.

Standalone Omneum recorded the highest precision, recall, evidence retention, claim coverage, and origin coverage among these five configurations. The hybrids generally used fewer context tokens but retained less annotated evidence.

Relative to their corresponding standalone rankers, the final hybrid evidence-retention differences in this domain were:

| Comparison | Evidence Retention Difference |
|---|---:|
| BM25 + Omneum vs. BM25 | −9.54 pp |
| MiniLM + Omneum vs. MiniLM | −9.50 pp |
| BGE + Omneum vs. BGE | −3.50 pp |
| Cohere + Omneum vs. Cohere | −13.67 pp |

The final deferred-candidate recovery improved evidence completeness most substantially for the MiniLM hybrid in this domain, but the corrected hybrids still retained less annotated evidence than their corresponding standalone rankers.

### Selection Latency

The final aggregate local selection timings across all six domains are:

| Configuration | Selection p50 | Selection p95 |
|---|---:|---:|
| Omneum Standalone | 194.86ms | 451.87ms |
| BM25 + Omneum | 207.79ms | 461.25ms |
| MiniLM + Omneum | 203.84ms | 465.36ms |
| BGE + Omneum | 200.63ms | 430.51ms |
| Cohere + Omneum | 206.89ms | 480.37ms |

These are benchmark-wide measurements, not Support & Operations-specific latency percentiles.

The local selection interval excludes external ranking inference and structured observation extraction. Frontier LLM judges have different inference and timing boundaries.

## `support_clean_resolution`

**Task:** Restore the Marlin export worker after scheduled maintenance.

```text
How should support restore the paused Marlin export
worker after scheduled maintenance?
```

### Fixture

```text
7 candidates
7 relevant
```

All seven sources support the same recovery action. The knowledge-base article explicitly cites the current runbook.

The relevant operational evidence includes:

```text
current_runbook      Current recovery procedure
service_state        Worker state after maintenance
kb_article           Knowledge-base recovery instructions
monitoring_result    Export backlog monitoring
change_record        Scheduled maintenance record
```

**Expected action:**

```bash
marlinctl worker resume export
```

After resuming the worker, verify that pending exports begin draining.

### Recorded Selections

The final evaluation measures retained supporting sources under each of the six token budgets.

| Source | Evidence | Relevance |
|---|---|---|
| `current_runbook` | Current recovery procedure | Supporting |
| `service_state` | Worker state after maintenance | Supporting |
| `kb_article` | Recovery instructions referencing the runbook | Supporting |
| `monitoring_result` | Export backlog monitoring | Supporting |
| `change_record` | Scheduled maintenance record | Supporting |

The fixture contains seven annotated supporting sources in total. The table identifies the five explicitly described operational records; the saved fixture contains the remaining source IDs.

### Comparative Analysis

The earlier fixed-source-budget evaluation selected three relevant sources for every configuration. One recorded BGE + Omneum selection was:

```text
current_runbook
kb_article
monitoring_result
```

The selection includes the current recovery procedure, its knowledge-base reference, and operational monitoring evidence.

The knowledge-base article cites the current runbook. Omneum's provenance-aware graph inference accounts for their shared evidence origin when computing source reliability and claim support, rather than treating both passages as fully independent evidence.

The final benchmark replaces the three-source limit with six token budgets. The number of retained passages can therefore vary with token cost and selection utility.

**Result:** This case measures supporting-evidence retention when all candidate sources agree on the recovery action.

Because every source is annotated as supporting, selection precision alone cannot distinguish the methods in this case. Recall, evidence retention, claim coverage, origin coverage, and context token usage provide additional measurements.

## `support_resolution_conflict`

**Task:** Recover Opal production after a trust-bundle deployment causes TLS verification failures.

```text
What should support do when Opal production reports
upstream_tls_verify_failed immediately after a
trust-bundle deployment?
```

### Fixture

```text
7 candidates
4 relevant
```

The deployment changes the active trust bundle from `tb17` to `tb18`.

After deployment, the service reports:

```text
upstream_tls_verify_failed
```

The service state identifies the missing issuer:

```text
Alder-CA
```

The change record establishes that `Alder-CA` was removed in `tb18`.

Two support tickets propose different recovery actions:

```text
OP-63
  Disable upstream TLS verification

OP-64
  Roll back the trust bundle
```

The current runbook, deployment configuration, and monitoring replay support restoring the previous trust bundle.

**Expected action:** Roll back from `tb18` to `tb17` while keeping TLS verification enabled.

Disabling TLS verification is not an acceptable recovery action.

### Recorded Selections

The final evaluation scores selected passages against four sources annotated as supporting the prescribed recovery action.

| Source | Evidence | Relevance |
|---|---|---|
| `runbook` | Current recovery procedure | Supporting |
| `deployment_config` | Active trust-bundle configuration | Supporting |
| `service_state` | Missing issuer and TLS failure diagnosis | Diagnostic, not labeled supporting |
| `OP-63` | Disable TLS verification | Not supporting |
| `OP-64` | Roll back trust bundle | Recovery recommendation; relevance follows fixture annotation |

The fixture's relevance labels distinguish diagnostic evidence from sources explicitly supporting the prescribed recovery action.

### Comparative Analysis

The earlier fixed-source-budget BGE + Omneum selection was:

```text
service_state
deployment_config
```

The service state identifies the missing issuer. The deployment configuration provides the active trust-bundle configuration.

The service-state evidence is diagnostically useful but does not receive a positive recovery-action relevance label.

This distinction matters because selecting a source that accurately describes the failure is not equivalent to selecting evidence that establishes the prescribed remediation.

The earlier evaluation showed that some generated responses recommended rollback without explicitly naming `tb17`. Those responses were recorded as `unscored`, not confirmed incorrect recommendations.

The final benchmark does not generate answers or assign downstream answer statuses.

**Result:** The case tests whether the selector retains evidence supporting rollback to `tb17` while excluding the instruction to disable TLS verification.

Omneum's `prepare_context()` uses claim support from provenance-aware graph inference alongside question relevance and incremental claim coverage. A passage describing the failure may be reliable without directly supporting the requested recovery action.

## `support_stale_runbook`

**Task:** Restore credential use after routine signing-key rotation on Nimbus v5.

```text
What restores credential use after routine signing-key
rotation on Nimbus v5 without changing the key?
```

### Fixture

```text
8 candidates
5 relevant
```

The candidate pool includes older Nimbus v3 procedures and current Nimbus v5 operational evidence.

Older instructions recommend restarting gateway pods:

```text
Nimbus v3 runbook
   |
   +--> Legacy KB article
   |
   +--> Copied support ticket
```

These documents repeat a procedure that is no longer appropriate for the installed version.

Nimbus v5 uses watch-mode key reload.

The current recovery procedure refreshes the credential cache without restarting the service.

**Expected action:**

```http
POST /admin/keys/refresh
```

After the request, verify the loaded key ID.

Relevant current evidence includes:

```text
current_runbook
deployment_config
incident_record
service_state
change_record
```

### Recorded Selections

The five annotated supporting sources are:

| Source | Evidence | Relevance |
|---|---|---|
| `current_runbook` | Current Nimbus v5 procedure | Supporting |
| `deployment_config` | Watch-mode key reload configuration | Supporting |
| `incident_record` | Current recovery evidence | Supporting |
| `service_state` | Current credential state | Supporting |
| `change_record` | Signing-key rotation record | Supporting |

The older Nimbus v3 runbook, legacy knowledge-base article, and copied support ticket are not annotated as supporting the Nimbus v5 recovery action.

### Comparative Analysis

The earlier fixed-source-budget evaluation selected the same three current sources across all configurations:

```text
current_runbook
incident_record
deployment_config
```

None of those selections included the obsolete restart procedure.

The current evidence establishes that Nimbus v5 refreshes its credential cache through the administrative endpoint rather than restarting gateway pods.

The older instructions are linked through copied and derived documentation. Omneum's provenance-aware graph inference accounts for their shared evidence origins when computing source reliability and claim support. Repetition does not establish that the procedure applies to Nimbus v5.

The earlier repeated BGE evaluations encountered downstream generation failures after context selection. Those failures affected multiple selector configurations and did not establish a selector-specific cause.

The final benchmark measures context selection only, so downstream generation failures are not included in its metrics.

**Result:** The case tests whether token-budgeted selection retains current Nimbus v5 recovery evidence instead of obsolete Nimbus v3 procedures.

The selection must account for the installed version, question relevance, and the supporting claims represented in each passage.

## `support_ticket_reference_loop`

**Task:** Recover a paused Vega ingest consumer while preserving queued records.

```text
How should support recover the current Vega ingest
backlog when the consumer is paused and storage is healthy?
```

### Fixture

```text
8 candidates
5 relevant
```

The candidate pool contains a circular reference chain recommending a destructive recovery action.

```text
Ticket VG-88
   |
   | cites
   v
KB-12
   |
   | cites
   v
Incident VG-71
   |
   | retrospective references
   v
Ticket VG-88
```

The three records reinforce the same recommendation:

```text
Purge the ingest queue.
```

Their circular references do not establish independent support for that action.

The current operational evidence instead indicates:

```text
Consumer state: paused
Storage state:  healthy
Queued records: pending
```

The deployment configuration explicitly identifies queue purge as destructive because it discards pending records.

**Expected action:**

```http
POST /consumers/ingest/resume
```

After resuming the consumer, verify that the queue drains.

Relevant evidence includes:

```text
runbook
service_state
deployment_config
monitoring_probe
change_record
```

### Recorded Selections

The five annotated supporting sources are:

| Source | Evidence | Relevance |
|---|---|---|
| `runbook` | Current consumer recovery procedure | Supporting |
| `service_state` | Paused consumer and healthy storage | Supporting |
| `deployment_config` | Queue preservation requirements | Supporting |
| `monitoring_probe` | Current backlog monitoring | Supporting |
| `change_record` | Operational change history | Supporting |
| `VG-88` | Queue-purge recommendation | Not supporting |
| `KB-12` | Repeated queue-purge recommendation | Not supporting |
| `VG-71` | Circularly referenced queue-purge recommendation | Not supporting |

### Comparative Analysis

The earlier fixed-source-budget evaluation selected:

```text
runbook
service_state
deployment_config
```

These sources establish the appropriate recovery action without relying on the circular ticket references.

The operational state indicates that the consumer is paused, storage is healthy, and queued records remain pending.

The current runbook prescribes resuming the consumer. The deployment configuration identifies purging the queue as destructive.

The ticket, knowledge-base article, and incident report form a citation cycle. Omneum's provenance-aware graph inference accounts for their shared evidence origins and dependencies when computing source reliability and claim support, rather than treating the repeated purge recommendation as independent support.

The final benchmark evaluates the reconstructed context at each token budget against the annotated supporting sources and evidence spans.

**Result:** The case tests retention of current operational evidence in the presence of circularly referenced recovery instructions that would discard pending records.

## Inspect Recorded Runs

The final synthetic dataset and recorded execution artifacts are maintained under `benchmarks/context_selection/synthetic/`.

### Case Fixtures

The benchmark dataset is documented at:

```text
benchmarks/context_selection/synthetic/DATASET.md
```

The four Support & Operations case IDs are:

```text
support_clean_resolution
support_resolution_conflict
support_stale_runbook
support_ticket_reference_loop
```

Find their definitions in the synthetic benchmark files:

```bash
rg -n \
  'support_clean_resolution|support_resolution_conflict|support_stale_runbook|support_ticket_reference_loop' \
  benchmarks/context_selection/synthetic/
```

Each case defines a fixed candidate pool, supporting-source annotations, and evaluation metadata.

### Saved Results

```text
benchmarks/context_selection/synthetic/results/
├── tier1-production-20261025-v1/
├── tier1-competitors-20261025-v1/
└── budget-exhaustion-recovery-20261026-v2/
```

The final corrected hybrid results are preserved in the recovery artifact directory.

Inspect the saved files:

```bash
find \
  benchmarks/context_selection/synthetic/results/budget-exhaustion-recovery-20261026-v2/ \
  -maxdepth 1 -type f -print | sort
```

Find the four support cases:

```bash
rg -n \
  'support_clean_resolution|support_resolution_conflict|support_stale_runbook|support_ticket_reference_loop' \
  benchmarks/context_selection/synthetic/results/budget-exhaustion-recovery-20261026-v2/
```

The matching records can be used to inspect individual case-budget selections and scoring outcomes.

### Published Dashboard

The competitive analysis is stored under:

```text
benchmarks/context_selection/synthetic/analysis/tier1-competitive-analysis-20261026-v1/
```

Inspect the analysis artifacts:

```bash
find \
  benchmarks/context_selection/synthetic/analysis/tier1-competitive-analysis-20261026-v1/ \
  -maxdepth 1 -type f -print | sort
```

The final comparison uses saved selection and scoring records. Inspecting these files does not rerun external provider inference.

## Evaluation Notes

| Setting | Value |
|---|---|
| Cases | 4 |
| Candidate passages | 30 total |
| Candidate pools | 7–8 passages per case |
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

The final hybrid results include deferred-candidate budget-exhaustion recovery. Positive-utility candidates outside the initial discovery neighborhood can be reconsidered when they satisfy the remaining token budget and marginal utility-density threshold.

### Answer Status

The earlier fixed-source-budget benchmark distinguished:

- `correct`: The generated answer satisfied the frozen correctness check.
- `unscored`: The response did not satisfy that check; it was not automatically a confirmed incorrect answer.
- `generation_failure`: The downstream generation step failed, preventing answer scoring.

These statuses belong to the earlier downstream-answer evaluation.

The final benchmark does not execute answer generation. Its metrics are computed from selected passages and their annotations.

### Measurement Constraints

The four support cases are synthetic fixtures with fixed candidate pools and relevance labels.

The six token budgets produce multiple measurements of the same cases, not independent additional tasks.

Selection precision measures the proportion of selected sources annotated as supporting. Recall measures the proportion of annotated supporting sources retained.

Evidence retention, claim coverage, and origin coverage measure complementary properties of the selected context.

The final local selection latency excludes external ranking inference and structured observation extraction. Frontier judge inference has different information and timing boundaries.

The selection policy was developed using the same synthetic case suite. These results are useful for controlled evaluation and regression testing, but do not independently establish performance on unseen support workloads.

## Summary

Across the four Support & Operations cases, **standalone Omneum achieved the highest precision, recall, evidence retention, claim coverage, and origin coverage among the five Omneum configurations**, while the hybrids generally produced smaller contexts.

The final domain results include:

- **Omneum Standalone:** 77.79% precision, 56.31% recall, 56.99% evidence retention, and 128.33 mean Qwen tokens.
- **BM25 + Omneum:** 72.94% precision, 48.40% evidence retention, and 109.63 mean Qwen tokens.
- **MiniLM + Omneum:** 71.03% precision, 46.94% evidence retention, and 114.08 mean Qwen tokens.
- **BGE + Omneum:** 75.82% precision, 54.10% evidence retention, and 120.00 mean Qwen tokens.
- **Cohere + Omneum:** 71.32% precision, 44.37% evidence retention, and 107.21 mean Qwen tokens.

The four fixtures test distinct operational failure modes: straightforward recovery, conflicting remediation instructions, obsolete version-specific procedures, and circular references supporting destructive actions.

The final hybrid configurations retained less annotated evidence than their corresponding standalone rankers in this domain. That tradeoff should be evaluated alongside context-token reductions rather than described as an unqualified selection-quality improvement.

These results contribute to the full 24-case cross-domain benchmark. See the [Leaderboard](leaderboard.md) for aggregate comparisons across all six domains.