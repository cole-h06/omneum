# Support & Operations Agents

Context-selection benchmark for support and operations agents. Evaluates incident recovery, conflicting remediation instructions, stale runbooks, and circular ticket references.

**4 held-out cases · 30 candidate sources · Claude Sonnet 5.5 generator**

[Leaderboard](leaderboard.md) | [Benchmark README](README.md) | [Dataset](context_evaluation/heldout/DATASET.md) | [Saved Results](context_evaluation/heldout/results/)

## Quick Start

Run from the Omneum repository root.

```bash
# Validate the 24 held-out cases
.venv/bin/python -m benchmarks.context_evaluation.heldout.validate_dataset

# Run offline benchmark tests
.venv/bin/python tools/run_context_evaluation_tests.py -q

# Verify saved publication metrics
.venv/bin/python -m benchmarks.context_evaluation.heldout.build_dashboard_summary --check
```

These commands validate the frozen dataset, run offline tests, and verify published metrics against saved artifacts. They do not execute new provider inference.

## Cases

| Case | Candidates | Budget | Expected behavior |
|---|---:|---:|---|
| [`support_clean_resolution`](#support_clean_resolution) | 7 | 3 | Resume the Marlin export worker |
| [`support_resolution_conflict`](#support_resolution_conflict) | 7 | 2 | Restore the previous Opal trust bundle without disabling TLS verification |
| [`support_stale_runbook`](#support_stale_runbook) | 8 | 3 | Refresh the Nimbus v5 credential cache |
| [`support_ticket_reference_loop`](#support_ticket_reference_loop) | 8 | 3 | Resume the Vega ingest consumer without purging queued records |

Each case uses a fixed candidate pool, source-level relevance labels, and a predefined selection budget.

## Recorded Results

The primary BGE + Omneum measurements below use the 10-trial GPT-6 Astra paired run. Claude and Cohere comparisons use one trial per case.

| Case | BGE + Omneum Precision | Recall | Recorded Answer | Selection p50 |
|---|---:|---:|---|---:|
| Clean resolution | **100%** | 42.9% | 10/10 correct | **0.626s** |
| Resolution conflict | 50% | 25% | 9/10 correct | **0.696s** |
| Stale runbook | **100%** | 60% | 10/10 generation failures | **0.729s** |
| Ticket reference loop | **100%** | 60% | 10/10 correct | **0.649s** |

**BGE + Omneum achieved 100% selection precision in three of four cases, matching the evaluated frontier LLM judges' selection quality in those cases at substantially lower selection latency.**

In the resolution-conflict case, BGE + Omneum produced nine correctly scored answers in ten attempts, compared with two for BGE + GPT-6 Astra. Gemini achieved higher selection precision in that case.

The stale-runbook generation failures occurred after successful context selection and affected all repeated BGE configurations. They do not establish incorrect source selection.

### Selection Latency

Median selection latency in seconds:

| Case | GPT-6 Astra Judge | Gemini 3.8 Flash Judge | Omneum |
|---|---:|---:|---:|
| Clean resolution | 4.016s | 2.329s | **0.626s** |
| Resolution conflict | 6.629s | 2.324s | **0.696s** |
| Stale runbook | 3.800s | 4.620s | **0.729s** |
| Ticket reference loop | 7.562s | 2.050s | **0.649s** |

Omneum recorded lower selection latency in every comparison.

These are recorded benchmark timings, not universal performance guarantees.

## `support_clean_resolution`

**Task:** Restore the Marlin export worker after scheduled maintenance.

```text
How should support restore the paused Marlin export
worker after scheduled maintenance?
```

### Fixture

```text
7 candidates
3 selected
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

| Method | Trials | Selected sources | Precision | Recall | Answer | Selection p50 |
|---|---:|---|---:|---:|---|---:|
| BGE + Claude Judge | 1 | `current_runbook`, `service_state`, `kb_article` | 100% | 42.9% | 1/1 correct | 2.238s |
| BGE + GPT-6 Astra Judge | 10 | `current_runbook`, `monitoring_result`, `service_state` | 100% | 42.9% | 10/10 correct | 4.016s |
| BGE + Gemini Judge | 10 | `current_runbook`, `kb_article`, `change_record` | 100% | 42.9% | 10/10 correct | 2.329s |
| **BGE + Omneum** | **10** | `current_runbook`, `kb_article`, `monitoring_result` | **100%** | **42.9%** | **10/10 correct** | **0.626s** |
| Cohere + Claude Judge | 1 | `current_runbook`, `service_state`, `change_record` | 100% | 42.9% | 1/1 correct | 2.008s |
| Cohere + Omneum | 1 | `current_runbook`, `kb_article`, `service_state` | 100% | 42.9% | 1/1 correct | 0.544s |

### Comparative Analysis

Every configuration selected three relevant sources and generated the correct recovery action.

BGE + Omneum selected:

```text
current_runbook
kb_article
monitoring_result
```

The selection includes the current recovery procedure, its knowledge-base reference, and operational monitoring evidence.

GPT-6 Astra instead selected the current runbook, monitoring result, and service state. Gemini selected the runbook, knowledge-base article, and change record.

All three selections achieved identical relevance metrics.

**Result:** Omneum matched the frontier LLM judges' 100% precision, 42.9% recall, and correct recorded answers. Its 0.626-second median selection latency was approximately 6.4× lower than GPT-6 Astra and 3.9× lower than Gemini.

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
2 selected
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

| Method | Trials | Selected sources | Precision | Recall | Answer | Selection p50 |
|---|---:|---|---:|---:|---|---:|
| BGE + Claude Judge | 1 | `runbook`, `service_state` | 50% | 25% | 1/1 unscored | 1.787s |
| BGE + GPT-6 Astra Judge | 10 | Variable; usually `service_state`, `runbook` | 60% | 30% | 2/10 correct | 6.629s |
| BGE + Gemini Judge | 10 | Usually `deployment_config`, `runbook` | 100% | 50% | 10/10 correct | 2.324s |
| **BGE + Omneum** | **10** | `service_state`, `deployment_config` | **50%** | **25%** | **9/10 correct** | **0.696s** |
| Cohere + Claude Judge | 1 | `runbook`, `service_state` | 50% | 25% | 1/1 unscored | 1.756s |
| Cohere + Omneum | 1 | `service_state`, `runbook` | 50% | 25% | 1/1 unscored | 0.582s |

The GPT-6 Astra and Gemini selection metrics are averages across ten trials.

### Comparative Analysis

BGE + Omneum consistently selected:

```text
service_state
deployment_config
```

The service state identifies the missing issuer. The deployment configuration provides the active trust-bundle configuration.

The fixture's relevance labels distinguish diagnostic evidence from sources explicitly supporting the prescribed recovery action. Consequently, the service state does not receive a positive recovery-action relevance label.

Gemini achieved the highest selection precision and recall in this case.

However, the recorded downstream answer outcomes differ:

| Configuration | Correct | Unscored |
|---|---:|---:|
| BGE + Claude Judge | 0 | 1 |
| BGE + GPT-6 Astra Judge | 2 | 8 |
| BGE + Gemini Judge | 10 | 0 |
| **BGE + Omneum** | **9** | **1** |
| Cohere + Claude Judge | 0 | 1 |
| Cohere + Omneum | 0 | 1 |

The separately executed BGE + Omneum trials paired with Gemini recorded 10/10 correct answers.

The GPT-6-paired Omneum run recorded nine correct answers and one unscored response.

Some unscored responses recommended rollback but did not explicitly identify `tb17`. An unscored result is not a confirmed incorrect remediation recommendation.

**Result:** Omneum achieved nine correctly scored answers in ten trials, one fewer than Gemini's ten correctly scored answers and exceeding GPT-6 Astra's two correctly scored answers in the corresponding comparison. Omneum completed selection approximately 9.5× faster than GPT-6 Astra and 3.7× faster than Gemini.

The case distinguishes diagnostic relevance from action-specific relevance. Omneum selected useful configuration and service-state evidence, while Gemini more consistently selected sources matching the fixture's recovery-action labels.

## `support_stale_runbook`

**Task:** Restore credential use after routine signing-key rotation on Nimbus v5.

```text
What restores credential use after routine signing-key
rotation on Nimbus v5 without changing the key?
```

### Fixture

```text
8 candidates
3 selected
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

| Method | Trials | Selected sources | Precision | Recall | Answer | Selection p50 |
|---|---:|---|---:|---:|---|---:|
| BGE + Claude Judge | 1 | `current_runbook`, `deployment_config`, `incident_record` | 100% | 60% | 1/1 correct | 1.931s |
| BGE + GPT-6 Astra Judge | 10 | `current_runbook`, `incident_record`, `deployment_config` | 100% | 60% | 10/10 generation failures | 3.800s |
| BGE + Gemini Judge | 10 | `current_runbook`, `incident_record`, `deployment_config` | 100% | 60% | 10/10 generation failures | 4.620s |
| **BGE + Omneum** | **10** | `current_runbook`, `incident_record`, `deployment_config` | **100%** | **60%** | 10/10 generation failures | **0.729s** |
| Cohere + Claude Judge | 1 | `current_runbook`, `deployment_config`, `incident_record` | 100% | 60% | 1/1 correct | 2.177s |
| Cohere + Omneum | 1 | `current_runbook`, `deployment_config`, `incident_record` | 100% | 60% | 1/1 correct | 0.666s |

### Comparative Analysis

Every configuration selected the same three current sources, regardless of ordering:

```text
current_runbook
incident_record
deployment_config
```

None selected the obsolete restart procedure.

All configurations achieved:

```text
Selection precision: 100%
Selection recall:     60%
```

The repeated BGE runs encountered downstream generation failures after context selection.

These failures affected GPT-6 Astra, Gemini, and Omneum configurations. The single BGE + Omneum attempt in the Claude-paired comparison also failed generation.

By contrast, the single-trial BGE + Claude and Cohere-based configurations generated correctly scored answers.

The recorded evidence does not establish a selector-specific cause for the repeated generation failures.

**Result:** Omneum matched the LLM judges' source selections and achieved 100% precision at 0.729-second median selection latency. The repeated downstream generation failures do not invalidate the measured selection precision or recall.

## `support_ticket_reference_loop`

**Task:** Recover a paused Vega ingest consumer while preserving queued records.

```text
How should support recover the current Vega ingest
backlog when the consumer is paused and storage is healthy?
```

### Fixture

```text
8 candidates
3 selected
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

| Method | Trials | Selected sources | Precision | Recall | Answer | Selection p50 |
|---|---:|---|---:|---:|---|---:|
| BGE + Claude Judge | 1 | `runbook`, `service_state`, `deployment_config` | 100% | 60% | 1/1 correct | 1.868s |
| BGE + GPT-6 Astra Judge | 10 | Usually `runbook`, `service_state`, `deployment_config` | 100% | 60% | 10/10 correct | 7.562s |
| BGE + Gemini Judge | 10 | Usually `runbook`, `service_state`, `deployment_config` | 100% | 60% | 10/10 correct | 2.050s |
| **BGE + Omneum** | **10** | `runbook`, `service_state`, `deployment_config` | **100%** | **60%** | **10/10 correct** | **0.649s** |
| Cohere + Claude Judge | 1 | `runbook`, `service_state`, `deployment_config` | 100% | 60% | 1/1 correct | 10.178s |
| Cohere + Omneum | 1 | `runbook`, `service_state`, `deployment_config` | 100% | 60% | 1/1 correct | 9.606s |

### Comparative Analysis

All configurations selected the same three relevant sources:

```text
runbook
service_state
deployment_config
```

These sources establish the appropriate recovery action without relying on the circular ticket references.

All methods achieved 100% precision, 60% recall, and correct recorded answers.

The principal measured difference was selection latency.

| Selector | Selection p50 |
|---|---:|
| GPT-6 Astra Judge | 7.562s |
| Gemini Judge | 2.050s |
| **Omneum** | **0.649s** |

**Result:** Omneum matched the frontier LLM judges' selection quality and downstream answer correctness while recording approximately 11.7× lower selection latency than GPT-6 Astra and 3.3× lower latency than Gemini.

The fixture demonstrates successful selection of current operational evidence in the presence of circularly referenced recovery instructions.

## Inspect Recorded Runs

The case fixtures and preserved execution artifacts are maintained separately.

### Case Fixtures

```text
benchmarks/context_evaluation/heldout/cases/
├── support_clean_resolution/
│   ├── case.json
│   └── ground_truth.json
├── support_resolution_conflict/
│   ├── case.json
│   └── ground_truth.json
├── support_stale_runbook/
│   ├── case.json
│   └── ground_truth.json
└── support_ticket_reference_loop/
    ├── case.json
    └── ground_truth.json
```

`case.json` contains the frozen case input and candidate context.

`ground_truth.json` contains the expected evidence labels and evaluation data.

### Saved Results

```text
benchmarks/context_evaluation/heldout/results/
├── bge-claude-vs-bge-omneum-20261008/
├── bge-openai-vs-bge-omneum-20261008/
├── bge-google-low-vs-bge-omneum-20261008/
└── cohere-claude-vs-cohere-omneum-20261008/
```

Each listed run contains recorded attempt data in `results.jsonl`.

Inspect the GPT-6 Astra paired run:

```bash
ls benchmarks/context_evaluation/heldout/results/bge-openai-vs-bge-omneum-20261008/
```

Find the four support cases:

```bash
rg -n \
  'support_clean_resolution|support_resolution_conflict|support_stale_runbook|support_ticket_reference_loop' \
  benchmarks/context_evaluation/heldout/results/bge-openai-vs-bge-omneum-20261008/results.jsonl
```

Inspect the saved run summary:

```bash
.venv/bin/python -m json.tool \
  benchmarks/context_evaluation/heldout/results/bge-openai-vs-bge-omneum-20261008/summary.json
```

### Published Dashboard

Inspect the benchmark-wide dashboard:

```bash
.venv/bin/python -m json.tool \
  benchmarks/context_evaluation/heldout/dashboard_summary.json
```

Verify the published metrics:

```bash
.venv/bin/python -m benchmarks.context_evaluation.heldout.build_dashboard_summary --check
```

Regenerate the dashboard from saved artifacts:

```bash
.venv/bin/python -m benchmarks.context_evaluation.heldout.build_dashboard_summary
```

This rebuilds the publication summary without rerunning provider inference.

## Evaluation Notes

| Setting | Value |
|---|---|
| Cases | 4 |
| Candidate sources | 30 total |
| Candidate pools | 7–8 sources per case |
| Selection budgets | 2–3 sources |
| Generator | Claude Sonnet 5.5 |
| Initial rerankers | BGE Reranker v2-m3, Cohere Rerank v4.0 Pro |
| Frontier judges | Claude Sonnet 5.5, GPT-6 Astra, Gemini 3.8 Flash |
| BGE + GPT-6 / Gemini | 10 trials per case |
| BGE + Omneum | 10 trials per case in each paired run |
| Claude / Cohere extracts | 1 trial per case |
| Selection scoring | Frozen source-level relevance labels |
| Latency aggregation | Median across recorded attempts |

BGE + Omneum appears in multiple paired-run artifacts. The main results table uses the GPT-6 Astra pairing rather than treating repeated executions as additional independent cases.

### Answer Status

The benchmark distinguishes:

- `correct`: The generated answer satisfies the frozen correctness check.
- `unscored`: The response does not satisfy that check; it is not automatically a confirmed incorrect answer.
- `generation_failure`: The downstream generation step failed, preventing an answer from being scored.

Selection precision and recall are measured independently of downstream generation.

### Measurement Constraints

The four support cases are synthetic fixtures with fixed candidate pools and relevance labels.

Repeated trials measure execution behavior on identical inputs, not generalization across additional tasks.

Selection latency includes the measured selection stage. End-to-end latency includes downstream generation, and failed-generation timings should not be interpreted as successful answer latency.

The compared selectors do not necessarily receive identical structural and semantic information, even when evaluated against the same candidate pool.

## Summary

Across the four Support & Operations cases, **BGE + Omneum matched the evaluated frontier LLM judges' selection precision and recall in three cases while recording lower selection latency in every repeated BGE comparison**.

The results include:

- **Clean resolution:** 100% selection precision, ten correctly scored answers, and 0.626-second median selection latency.
- **Resolution conflict:** Nine correctly scored answers in ten trials, one fewer than Gemini's ten correctly scored answers and exceeding GPT-6 Astra's two, despite lower source-level selection precision.
- **Stale runbook:** 100% selection precision with the same current evidence selected by every evaluated judge. Repeated downstream generation failures affected all BGE configurations.
- **Ticket reference loop:** 100% selection precision, ten correctly scored answers, and 0.649-second median selection latency.

These results demonstrate that Omneum can provide low-latency context selection for operational recovery tasks while preserving competitive evidence-selection quality against frontier LLM judges.

The domain results are one component of the full 24-case benchmark. See the [leaderboard](leaderboard.md) for aggregate comparisons against standalone semantic rerankers and frontier LLM judges.