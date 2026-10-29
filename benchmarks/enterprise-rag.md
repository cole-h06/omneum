# Enterprise RAG

Enterprise RAG evaluation for the Omneum Cross-Domain Context Curation Benchmark.

Four synthetic cases test context selection for incomplete provenance, copied policies, semantically related but inapplicable documents, and outdated documentation.

**4 cases · 35 candidate passages · 6 Qwen-token budgets · 13 budgeted configurations**

[Leaderboard](leaderboard.md) | [Benchmark README](README.md) | [Dataset](context_selection/synthetic/DATASET.md) | [Saved Results](context_selection/synthetic/results/)

## Quick Start

Run from the Omneum repository root.

```bash
# Inspect the original competitor results
cat benchmarks/context_selection/synthetic/results/tier1-competitors-20261025-v1/aggregate.csv

# Inspect the completed budget-exhaustion recovery
cat benchmarks/context_selection/synthetic/results/budget-exhaustion-recovery-20261026-v2/report.md

# Inspect Enterprise RAG domain averages
rg '^domain,enterprise_rag,' \
  benchmarks/context_selection/synthetic/results/budget-exhaustion-recovery-20261026-v2/domain_budget_case_levels.csv
```

The original benchmark run and completed recovery use the same frozen 24-case dataset. Inspecting the saved results does not issue new provider inference requests.

## Cases

| Case | Candidates | Token Budgets | Expected behavior |
|---|---:|---|---|
| [`enterprise_partial_lineage`](#enterprise_partial_lineage) | 8 | 64–256 | Select the applicable retention schedule despite incomplete provenance |
| [`enterprise_policy_copy_chain`](#enterprise_policy_copy_chain) | 9 | 64–256 | Reject a repeatedly copied incorrect policy threshold |
| [`enterprise_semantic_distractors`](#enterprise_semantic_distractors) | 10 | 64–256 | Distinguish VPN revocation from related operational deadlines |
| [`enterprise_stale_handbook`](#enterprise_stale_handbook) | 8 | 64–256 | Prefer the current leave entitlement over superseded documentation |

Each case uses a fixed candidate pool with supporting-source annotations, canonical claims, and source-origin metadata. Selection is evaluated at **64, 96, 128, 160, 192, and 256 Qwen tokens**.

## Recorded Results

The table reports the completed Enterprise RAG evaluation, averaged across four cases and six token budgets. Corrected hybrid rows come from `budget-exhaustion-recovery-20261026-v2/domain_budget_case_levels.csv`.

| Configuration | Precision | Recall | Evidence Retention | Claim Coverage | Origin Coverage | Qwen Tokens |
|---|---:|---:|---:|---:|---:|---:|
| Omneum | 49.38% | 44.79% | 49.38% | 92.50% | 91.67% | 119.25 |
| BM25 + Omneum | 71.53% | 49.65% | 51.60% | 84.44% | 93.75% | 93.79 |
| MiniLM + Omneum | 72.01% | 44.58% | 47.55% | 85.83% | 93.75% | 88.13 |
| BGE + Omneum | 86.11% | 58.61% | 59.74% | 94.44% | 95.83% | 90.21 |
| Cohere + Omneum | 86.11% | 57.57% | 59.20% | 94.44% | 95.83% | 89.29 |

BGE + Omneum and Cohere + Omneum each recorded **86.11% selection precision**, **94.44% claim coverage**, and **95.83% origin coverage**. BGE + Omneum retained **59.74%** of annotated evidence, the highest among the five Omneum configurations in this domain.

The completed recovery preserved evidence retention, claim coverage, and origin coverage for the Enterprise RAG hybrids. Additional selected passages reduced aggregate precision for BGE + Omneum and Cohere + Omneum by **13.89 percentage points** relative to their original restricted-discovery selections.

Selection precision and recall use annotated supporting-source IDs. Evidence retention measures retained gold evidence spans. Claim coverage uses canonical claims represented in supporting passages; origin coverage uses annotated root-origin units. `tokenizer_tokens` records the Qwen tokenizer count of the reconstructed context.

## `enterprise_partial_lineage`

**Task:** Determine the applicable customer chat retention period under schedule CS-8.

```text
What retention period should the Alder team apply to
production customer chat transcripts under schedule CS-8?
```

### Fixture

```text
8 candidates
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

The evaluation selects from eight candidate passages at six token budgets. The supporting-source annotations identify the signed schedule, Records instruction, retention configuration, and announcement.

| Source | Evidence |
|---|---|
| `drive_document_2` | Signed CS-8 schedule specifying 90 days |
| `email` | Records instruction specifying 90 days |
| `system_record` | Retention service configuration with `ttl_days=90` |
| `announcement` | Records announcement specifying 90 days |
| `drive_document` | Superseded onboarding checklist specifying 180 days |
| `confluence_page` | Mirror of the outdated onboarding checklist |
| `team_wiki` | Migrated onboarding wiki retaining the 180-day value |
| `slack_message` | Support handoff with missing document linkage |

**Result:** The case evaluates whether selected context retains the applicable 90-day schedule despite repeated 180-day references and incomplete provenance.

Omneum's provenance-aware graph inference accounts for known shared evidence origins and dependencies when computing source reliability and claim support. Missing provenance limits which relationships can be represented; the signed schedule and current Records sources provide the annotated supporting evidence.

The saved selections record source IDs and reconstructed passages for each configuration and token budget.

## `enterprise_policy_copy_chain`

**Task:** Determine the applicable employee meal receipt threshold under policy TR-17.

```text
Under Larch policy TR-17, what receipt threshold applies
to domestic meals for employees in August 2026?
```

### Fixture

```text
9 candidates
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

The candidate pool contains three annotated supporting sources and six sources repeating the obsolete threshold.

| Source | Evidence |
|---|---|
| `policy_record` | Current TR-17 policy and effective date |
| `hr_system` | Expense-system threshold of $40 |
| `policy_changelog` | Signed policy change effective July 1, 2026 |
| `confluence_page` | Incorrect $75 FAQ |
| `team_wiki` | Copied $75 guidance |
| `slack_message` | Downstream $75 checklist |
| `drive_document` | Copied $75 checklist |
| `email_summary` | FAQ-derived $75 digest |
| `manager_note` | Combined checklist and digest references |

**Result:** The case measures retention of the current $40 policy evidence against a larger group of related sources repeating $75.

Omneum's provenance-aware graph inference accounts for the recorded copy relationships when computing source reliability and claim support, rather than treating each repeated $75 assertion as independent support. The SDK maps claim support to retrieved chunks and uses question relevance and incremental claim coverage to select original passages within the token budget.

The saved selection metrics measure which annotated supporting sources and evidence spans survive each budget.

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

The evaluation scores retained passages against four annotated supporting sources.

| Source | Evidence |
|---|---|
| `policy` | AC-9 production VPN revocation requirement |
| `hr_record` | Contractor engagement-end workflow |
| `operations_doc` | Production offboarding procedure |
| `system_record` | Access scheduler configuration |
| `policy_2` | Employee payroll benefits deadline |
| `project_doc` | Project documentation archive deadline |
| `project_doc_2` | Staging credential rotation |
| `confluence_page` | Production VPN enrollment |
| `slack_message` | Deployment window |
| `drive_document` | Hardware-token return |

**Result:** The case measures whether context selection distinguishes the AC-9 production revocation deadline from semantically related operational deadlines.

The completed budget-exhaustion recovery increased selected context in some Enterprise RAG cells without improving the domain's aggregate evidence retention, claim coverage, or origin coverage.

In `enterprise_semantic_distractors`, BGE + Omneum and Cohere + Omneum each recorded a **38.89-percentage-point decrease in case-average precision** relative to their original selections, with no evidence-retention gain.

The additional selected passages increased the context footprint without retaining more annotated supporting evidence. This case demonstrates that expanding candidate discovery can reduce selection precision when marginal utility admits task-inapplicable passages.

## `enterprise_stale_handbook`

**Task:** Determine the paid volunteer leave entitlement for calendar year 2026.

```text
How many paid volunteer days may a full-time Cedar
employee take in calendar year 2026?
```

### Fixture

```text
8 candidates
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

The five annotated supporting sources establish the current entitlement and its effective date.

| Source | Evidence |
|---|---|
| `current_policy` | Current four-day entitlement |
| `hr_system` | HR system's active benefit allowance |
| `announcement` | People team policy announcement |
| `confluence_page` | Current benefits documentation |
| `policy_changelog` | Two-to-four-day policy change |
| `archived_handbook` | Superseded two-day entitlement |
| `old_team_page` | Outdated engineering onboarding guidance |
| `drive_document` | Historical recruiting overview |

**Result:** The case evaluates whether budgeted context retains the 2026 four-day entitlement and its effective-date evidence while excluding superseded two-day references.

The selected passage sets are preserved in the completed benchmark results. Source recall measures how many of the five annotated supporting sources remain in the reconstructed context at each budget.

The case tests applicability of time-versioned policy evidence. A historically accurate two-day entitlement does not answer a question about the 2026 policy.

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

These directories contain the original benchmark execution, competitor measurements, and completed hybrid recovery for the same frozen dataset.

### Inspect Enterprise RAG Selections

Inspect the original competitor selections:

```bash
rg -n '"case_id": "enterprise_' \
  benchmarks/context_selection/synthetic/results/tier1-competitors-20261025-v1/selections.json
```

Inspect the corrected Omneum selections:

```bash
rg -n '"case_id": "enterprise_' \
  benchmarks/context_selection/synthetic/results/budget-exhaustion-recovery-20261026-v2/selections.json
```

Inspect the corrected domain averages:

```bash
rg '^domain,enterprise_rag,' \
  benchmarks/context_selection/synthetic/results/budget-exhaustion-recovery-20261026-v2/domain_budget_case_levels.csv
```

The saved selection records contain the selected source IDs, reconstructed context, and token counts for the corresponding case-budget configurations.

### Inspect Aggregate Comparisons

```bash
# Original competitor measurements
cat benchmarks/context_selection/synthetic/results/tier1-competitors-20261025-v1/aggregate.csv

# Completed hybrid recovery
cat benchmarks/context_selection/synthetic/results/budget-exhaustion-recovery-20261026-v2/aggregate.csv

# Domain and budget comparisons
head -n 20 benchmarks/context_selection/synthetic/results/budget-exhaustion-recovery-20261026-v2/paired_domain_budget.csv

# Case-level comparisons
head -n 20 benchmarks/context_selection/synthetic/results/budget-exhaustion-recovery-20261026-v2/paired_cases.csv

# Statistical comparisons
head -n 20 benchmarks/context_selection/synthetic/results/budget-exhaustion-recovery-20261026-v2/paired_comparisons.csv
```

The paired records compare the corrected Omneum hybrid selections with their corresponding standalone rankers and original hybrid outputs.

### Inspect Recovery Validation

```bash
# Verify the saved analysis record
python -m json.tool \
  benchmarks/context_selection/synthetic/results/budget-exhaustion-recovery-20261026-v2/analysis_validation.json

# Inspect recovery coverage
head -n 20 \
  benchmarks/context_selection/synthetic/results/budget-exhaustion-recovery-20261026-v2/improvement_coverage.csv

# Inspect the competitive analysis
cat benchmarks/context_selection/synthetic/analysis/tier1-competitive-analysis-20261026-v1/report.md
```

The completed evaluation preserves the original selected passages in all 720 Omneum selection cells. The saved validation reproduces selection-quality metrics and checks the corrected outputs against the frozen annotations.

## Evaluation Notes

| Setting | Value |
|---|---|
| Cases | 4 Enterprise RAG cases |
| Candidate passages | 35 total |
| Candidate pools | 8–10 passages per case |
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
| Deferred candidate recovery | Enabled after initial neighborhood exhaustion |
| Conflict-aware selection | `conflict_aware=False` |
| Selection scoring | Annotated supporting-source IDs |
| Evidence scoring | Retained gold evidence spans |
| Claim scoring | Canonical claims represented in supporting passages |
| Origin scoring | Annotated root-origin units |
| Latency | Local selection after relevance scoring and observation preparation |

Omneum's provenance-aware graph inference iteratively computes source reliability and claim support across a bipartite graph, accounting for shared evidence origins and dependencies between sources.

The SDK maps finalized claim support to retrieved chunks through their associated claim IDs. `prepare_context()` uses question relevance and incremental claim coverage to select and reconstruct original passages within the configured token budget.

The completed recovery evaluates deferred candidates when the initial discovery neighborhood exhausts positive, budget-feasible utility. It preserves previously selected passages and applies the recorded marginal utility-density threshold.

The benchmark uses `tokenizer_tokens` to enforce Qwen budgets. `actual_context_tokens` records the word/punctuation footprint, including rendered passage headers. These fields use different counting semantics.

Local selection timing begins after relevance scores and structured observations are available. The measured interval includes graph evaluation, candidate discovery, packing, reconstruction, and SDK verification. External ranking inference and structured observation extraction are excluded.

### Interpretation

Across the four Enterprise RAG cases, the completed evaluation records:

- **86.11% selection precision** for BGE + Omneum and Cohere + Omneum.
- **94.44% claim coverage** and **95.83% origin coverage** for both hybrids.
- **59.74% evidence retention** for BGE + Omneum and **59.20%** for Cohere + Omneum.
- **90.21** and **89.29** mean Qwen tokens for BGE + Omneum and Cohere + Omneum, respectively.

The budget-exhaustion recovery did not increase Enterprise RAG evidence retention, claim coverage, or origin coverage. It reduced aggregate precision in the BGE and Cohere hybrids as additional passages were admitted.

The benchmark uses synthetic enterprise documents and fixed candidate pools. Structured `Observation` objects supply source identities, canonical claims, and recorded provenance relationships. The measured output is reconstructed context selected under the token budget.

For aggregate comparisons, latency measurements, and paired confidence intervals, see the [Leaderboard](leaderboard.md). For implementation and reproduction details, see the [Benchmark README](README.md).
