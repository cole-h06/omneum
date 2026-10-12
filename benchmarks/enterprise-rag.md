
# Enterprise RAG

Context-selection benchmark for enterprise retrieval systems. Tests incomplete provenance, copied policies, semantic distractors, and outdated documentation.

**4 held-out cases · 35 candidate sources · Claude Sonnet 5.5 generator**

[Leaderboard](leaderboard.md) | [Benchmark README](README.md) | [Dataset](context_evaluation/heldout/DATASET.md) | [Saved Results](context_evaluation/heldout/results/)

## Quick Start

Run from the Omneum repository root.

```bash
# Validate all 24 held-out cases, including the four Enterprise RAG cases
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
| [`enterprise_partial_lineage`](#enterprise_partial_lineage) | 8 | 3 | Select the applicable retention schedule despite incomplete provenance |
| [`enterprise_policy_copy_chain`](#enterprise_policy_copy_chain) | 9 | 3 | Reject a repeatedly copied incorrect policy threshold |
| [`enterprise_semantic_distractors`](#enterprise_semantic_distractors) | 10 | 3 | Distinguish VPN revocation from related operational deadlines |
| [`enterprise_stale_handbook`](#enterprise_stale_handbook) | 8 | 3 | Prefer the current leave entitlement over superseded documentation |

Each case uses a fixed candidate pool, relevance labels, and a selection budget of three sources.

## Recorded Results

BGE + Omneum results below use the 10-trial GPT-6 Astra pairing. Claude and Cohere comparisons use one trial per case.

| Case | BGE + Omneum Precision | Recall | Answer | Selection p50 |
|---|---:|---:|---|---:|
| Partial lineage | 100% | 75% | 10/10 correct | 0.612s |
| Policy copy chain | 100% | 100% | 10/10 correct | 0.619s |
| Semantic distractors | 100% | 75% | 10/10 correct | 0.631s |
| Stale handbook | 100% | 60% | 10/10 correct | 0.619s |

All evaluated LLM judge configurations achieved the same selection precision, recall, and recorded answer correctness on these four cases.

Selection precision and recall use fixture relevance labels. Recorded answer correctness uses the benchmark's frozen answer-scoring procedure.

## `enterprise_partial_lineage`

**Task:** Determine the applicable customer chat retention period under schedule CS-8.

```text
What retention period should the Alder team apply to
production customer chat transcripts under schedule CS-8?
```

### Fixture

```text
8 candidates
3 selected
4 relevant

drive_document       Imported onboarding checklist: 180 days
confluence_page      Onboarding checklist mirror: 180 days
slack_message        Support handoff: 180 days
drive_document_2     Signed CS-8 schedule: 90 days
team_wiki            Migrated onboarding wiki: 180 days
email                Records instruction: 90 days
system_record        Retention service configuration: 90 days
announcement         Records announcement: 90 days
```

The applicable retention schedule specifies **90 days, excluding legal holds**.

The older 180-day value appears across multiple internal systems. Some provenance relationships are observable, while others are missing.

```text
Imported Drive Checklist (180 days)
          |
          v
Confluence Mirror (180 days)
          |
          v
Team Wiki (180 days)

Slack Handoff (180 days)
  └── Original document link unavailable
```

The original Drive document has no preserved revision history. The Slack handoff lacks a document link, and the Records email archive retains only a folder-level reference.

The relevant evidence is:

```text
drive_document_2
email
system_record
announcement
```

Signed schedule:

```text
Schedule: CS-8
Record class: Production customer chat transcripts
Retention: 90 days
Exception: Legal holds
```

Retention service configuration:

```ini
ttl_days=90
```

The system record also contains `legal_hold bypass enabled`. Its exact operational meaning is not established by the fixture.

### Recorded Selections

| Method | Trials | Selected sources | P | R | Answer | Selection p50 |
|---|---:|---|---:|---:|---|---:|
| BGE + Claude Judge | 1 | `drive_document_2`, `system_record`, `announcement` | 100% | 75% | 1/1 correct | 1.725s |
| BGE + GPT-6 Astra Judge | 10 | Same | 100% | 75% | 10/10 correct | 4.896s |
| BGE + Gemini Judge | 10 | `announcement`, `email`, `drive_document_2` | 100% | 75% | 10/10 correct | 3.288s |
| **BGE + Omneum** | **10** | `announcement`, `email`, `drive_document_2` | **100%** | **75%** | **10/10 correct** | **0.612s** |
| Cohere + Claude Judge | 1 | `drive_document_2`, `system_record`, `announcement` | 100% | 75% | 1/1 correct | 4.480s |
| Cohere + Omneum | 1 | `drive_document_2`, `announcement`, `system_record` | 100% | 75% | 1/1 correct | 3.288s |

**Result:** All configurations selected three relevant sources and generated the correct 90-day answer.

Omneum selected the signed schedule, Records announcement, and Records email. Claude and GPT-6 Astra preferred the signed schedule, retention service record, and announcement.

Omneum matched their selection quality at lower recorded latency. The result does not establish that missing provenance relationships were reconstructed.

## `enterprise_policy_copy_chain`

**Task:** Determine the applicable employee meal receipt threshold under policy TR-17.

```text
Under Larch policy TR-17, what receipt threshold applies
to domestic meals for employees in August 2026?
```

### Fixture

```text
9 candidates
3 selected
3 relevant

policy_record        Current TR-17 policy: $40
confluence_page      Travel desk FAQ: $75
team_wiki            Sales wiki: $75
slack_message        Sales checklist: $75
hr_system            Expense system rule: $40
drive_document       Copied checklist: $75
email_summary        Travel FAQ digest: $75
manager_note         Combined checklist/digest: $75
policy_changelog     Signed policy change log: $40
```

The applicable threshold is **$40 or more**, effective July 1, 2026.

Six sources specify an incorrect $75 threshold. Their provenance shows that much of this apparent agreement originates from the same Confluence FAQ.

```text
Confluence FAQ ($75)
├── Team Wiki ($75)
│   ├── Slack Checklist ($75)
│   │   └── Manager Note ($75)
│   └── Drive Checklist ($75)
└── Email Digest ($75)
    └── Manager Note ($75)
```

The relevant evidence is:

```text
policy_record
hr_system
policy_changelog
```

Policy record:

```text
Policy: TR-17
Effective: 2026-07-01
Expense category: Domestic employee meals
Receipt required: Amount >= $40
```

The expense-system rule and signed policy change log agree with the effective policy.

The six $75 sources do not represent six independent policy determinations.

### Recorded Selections

| Method | Trials | Selected sources | P | R | Answer | Selection p50 |
|---|---:|---|---:|---:|---|---:|
| BGE + Claude Judge | 1 | `policy_record`, `hr_system`, `policy_changelog` | 100% | 100% | 1/1 correct | 1.794s |
| BGE + GPT-6 Astra Judge | 10 | Same | 100% | 100% | 10/10 correct | 2.615s |
| BGE + Gemini Judge | 10 | Same | 100% | 100% | 10/10 correct | 2.246s |
| **BGE + Omneum** | **10** | Same | **100%** | **100%** | **10/10 correct** | **0.619s** |
| Cohere + Claude Judge | 1 | Same | 100% | 100% | 1/1 correct | 3.667s |
| Cohere + Omneum | 1 | Same | 100% | 100% | 1/1 correct | 1.692s |

Source ordering varied between methods, but all selected the same three source IDs.

**Result:** Every configuration rejected the copied $75 threshold and selected the current $40 policy evidence.

All methods achieved 100% precision, 100% recall, and correct recorded answers. Omneum matched the LLM judges' selection quality at lower selection latency.

This fixture does not demonstrate a judge failure.

## `enterprise_semantic_distractors`

**Task:** Determine the production VPN revocation deadline for an offboarded contractor.

```text
For a contractor leaving the Iris project, what is the
deadline to revoke production VPN access after the
engagement ends?
```

### Fixture

```text
10 candidates
3 selected
4 relevant

policy               AC-9 production VPN revocation
policy_2             Employee payroll benefit access
project_doc          Iris documentation archive deadline
project_doc_2        Staging VPN credential rotation
hr_record            Contractor offboarding workflow
confluence_page      Production VPN enrollment
slack_message        Iris deployment window
operations_doc       AC-9 offboarding procedure
drive_document       VPN hardware-token return
system_record        Access scheduler configuration
```

The governing policy requires production VPN access to be revoked **within four hours of the engagement end timestamp**.

The candidate pool contains several related but inapplicable deadlines:

| Source | Deadline | Applies to |
|---|---|---|
| `policy` | 4 hours | Production VPN revocation |
| `policy_2` | 30 days | Employee payroll benefit access |
| `project_doc` | 14 days | Project documentation archive |
| `project_doc_2` | 24 hours | Staging VPN credential rotation |
| `confluence_page` | 2 business days | Production VPN enrollment |
| `slack_message` | 4 hours | Deployment window |
| `drive_document` | 7 days | Hardware-token return |

The relevant evidence is:

```text
policy
hr_record
operations_doc
system_record
```

Access policy:

```text
Policy: AC-9
Subject: Contractor production VPN access
Trigger: Engagement end
Revocation deadline: Within 4 hours
```

Scheduler calculation:

```python
revoke_due = engagement_end + timedelta(hours=4)
```

The four-hour deployment window and seven-day hardware-token return requirement do not determine the production VPN revocation deadline.

### Recorded Selections

| Method | Trials | Selected sources | P | R | Answer | Selection p50 |
|---|---:|---|---:|---:|---|---:|
| BGE + Claude Judge | 1 | `policy`, `system_record`, `operations_doc` | 100% | 75% | 1/1 correct | 1.585s |
| BGE + GPT-6 Astra Judge | 10 | Same | 100% | 75% | 10/10 correct | 2.537s |
| BGE + Gemini Judge | 10 | Same | 100% | 75% | 10/10 correct | 2.576s |
| **BGE + Omneum** | **10** | Same | **100%** | **75%** | **10/10 correct** | **0.631s** |
| Cohere + Claude Judge | 1 | Same | 100% | 75% | 1/1 correct | 4.048s |
| Cohere + Omneum | 1 | Same | 100% | 75% | 1/1 correct | 2.472s |

Some Gemini trials changed source ordering without changing the selected set.

**Result:** All methods selected the governing access policy, scheduler record, and offboarding procedure.

Omneum matched the judges' 100% precision and 75% recall with lower selection latency.

The result demonstrates successful task-specific context selection, not superior selection accuracy.

## `enterprise_stale_handbook`

**Task:** Determine the paid volunteer leave entitlement for calendar year 2026.

```text
How many paid volunteer days may a full-time Cedar
employee take in calendar year 2026?
```

### Fixture

```text
8 candidates
3 selected
5 relevant

archived_handbook     2024 handbook: 2 days
old_team_page         2024 engineering onboarding: 2 days
current_policy        2026 leave policy: 4 days
hr_system             Current HR entitlement: 4 days
announcement          People team announcement: 4 days
confluence_page       Current benefits page: 4 days
drive_document        2024 recruiting overview: 2 days
policy_changelog      Change history: 2 → 4 days
```

Cedar increased annual paid volunteer leave from two to **four days**, effective January 1, 2026.

The older documents are historically accurate but no longer applicable.

```text
2024 Policy
    |
    | 2 paid volunteer days
    |
    v
2026 Policy (effective 2026-01-01)
    |
    | 4 paid volunteer days
    v
Current Entitlement
```

Current policy:

```text
Employee type: Full-time
Benefit: Paid volunteer leave
Effective date: 2026-01-01
Annual entitlement: 4 days
```

The five relevant sources are:

```text
current_policy
hr_system
announcement
confluence_page
policy_changelog
```

### Recorded Selections

| Method | Trials | Selected sources | P | R | Answer | Selection p50 |
|---|---:|---|---:|---:|---|---:|
| BGE + Claude Judge | 1 | `current_policy`, `hr_system`, `announcement` | 100% | 60% | 1/1 correct | 2.544s |
| BGE + GPT-6 Astra Judge | 10 | Same | 100% | 60% | 10/10 correct | 2.920s |
| BGE + Gemini Judge | 10 | `confluence_page`, `current_policy`, `hr_system` (6/10); `announcement`, `confluence_page`, `current_policy` (3/10); `announcement`, `current_policy`, `hr_system` (1/10) | 100% | 60% | 10/10 correct | 2.305s |
| **BGE + Omneum** | **10** | `current_policy`, `confluence_page`, `announcement` | **100%** | **60%** | **10/10 correct** | **0.619s** |
| Cohere + Claude Judge | 1 | `current_policy`, `hr_system`, `policy_changelog` | 100% | 60% | 1/1 correct | 2.415s |
| Cohere + Omneum | 1 | `current_policy`, `confluence_page`, `announcement` | 100% | 60% | 1/1 correct | 0.650s |

**Result:** Every configuration selected three sources supporting the current four-day allowance and generated the correct answer.

Omneum preferred the current policy, Confluence benefits page, and announcement. The LLM judges generally preferred the current policy and HR system record.

Both selections satisfy the relevance labels. Omneum recorded lower selection latency without improving scored selection quality.

Gemini figures use the completed low-thinking replay; Gemini speedups use its unchanged historical Omneum comparator. Other Omneum rows retain their original paired run. Gemini E2E sums combine original selection and later recovered generation timings.

## Inspect Recorded Runs

Authoritative run directories:

```text
benchmarks/context_evaluation/heldout/results/
├── bge-claude-vs-bge-omneum-20261008/
├── bge-openai-vs-bge-omneum-20261008/
├── bge-google-low-vs-bge-omneum-20261008/
└── cohere-claude-vs-cohere-omneum-20261008/
```

### Inspect Enterprise RAG Attempts

```bash
# List available result artifacts
ls benchmarks/context_evaluation/heldout/results/bge-openai-vs-bge-omneum-20261008/

# Find all four Enterprise RAG cases
rg -n \
  'enterprise_partial_lineage|enterprise_policy_copy_chain|enterprise_semantic_distractors|enterprise_stale_handbook' \
  benchmarks/context_evaluation/heldout/results/bge-openai-vs-bge-omneum-20261008/results.jsonl
```

Extract matching JSONL records into a separate file:

```bash
rg \
  'enterprise_partial_lineage|enterprise_policy_copy_chain|enterprise_semantic_distractors|enterprise_stale_handbook' \
  benchmarks/context_evaluation/heldout/results/bge-openai-vs-bge-omneum-20261008/results.jsonl \
  > /tmp/enterprise-rag-results.jsonl
```

Count the extracted records:

```bash
wc -l /tmp/enterprise-rag-results.jsonl
```

This extracts records matching the four case IDs. The resulting line count depends on how the run serializes attempts and method comparisons; it should not be interpreted as a count of independent cases.

### Inspect All Recorded Comparisons

```bash
for run in \
  bge-claude-vs-bge-omneum-20261008 \
  bge-openai-vs-bge-omneum-20261008 \
  bge-google-low-vs-bge-omneum-20261008 \
  cohere-claude-vs-cohere-omneum-20261008
do
  echo "===== $run ====="

  rg -c \
    'enterprise_partial_lineage|enterprise_policy_copy_chain|enterprise_semantic_distractors|enterprise_stale_handbook' \
    "benchmarks/context_evaluation/heldout/results/$run/results.jsonl" || true
done
```

### Inspect the Published Dashboard

```bash
.venv/bin/python -m json.tool \
  benchmarks/context_evaluation/heldout/dashboard_summary.json
```

Verify the dashboard against saved evidence:

```bash
.venv/bin/python -m benchmarks.context_evaluation.heldout.build_dashboard_summary --check
```

Regenerate it:

```bash
.venv/bin/python -m benchmarks.context_evaluation.heldout.build_dashboard_summary
```

Regeneration processes saved artifacts. It does not call providers or reproduce original model responses.

## Evaluation Notes

| Setting | Value |
|---|---|
| Cases | 4 |
| Candidate sources | 35 total |
| Candidate pools | 8–10 sources per case |
| Selection budget | 3 sources per case |
| Generator | Claude Sonnet 5.5 |
| Initial rerankers | BGE Reranker v2-m3, Cohere Rerank v4.0 Pro |
| Frontier judges | Claude Sonnet 5.5, GPT-6 Astra, Gemini 3.8 Flash |
| BGE + GPT-6 / Gemini | 10 trials per case |
| BGE + Omneum | 10 trials per case in each paired run |
| Claude / Cohere comparisons | 1 trial per case |
| Latency aggregation | Median across recorded trials |
| Selection scoring | Fixture relevance labels |

BGE + Omneum appears in multiple paired-run artifacts. The tables use the GPT-6 Astra paired run rather than pooling repeated executions as additional independent cases.

### Interpretation

Across the four Enterprise RAG cases:

- All configurations selected relevant evidence and generated correct recorded answers.
- Omneum matched the LLM judges' selection precision and recall.
- Omneum recorded lower selection latency in every case.
- The measured advantage was latency, not selection accuracy.

The evaluation uses synthetic fixtures with predefined candidate pools. It does not measure retrieval over live enterprise repositories, large-scale metadata completeness, or performance under changing production documents.

The selector methods may receive different metadata and provenance information. Equal candidate pools do not imply identical selector inputs.

Live model outputs and provider latency may differ on re-execution. For benchmark execution configuration and methodology, see [Benchmark README](README.md).
