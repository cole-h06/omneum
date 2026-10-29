# Coding Agents

Coding-agent evaluation for the Omneum Cross-Domain Context Curation Benchmark.

Four synthetic cases test context selection for version-specific APIs, transactional replay handling, deployment configuration, and source lineage.

**4 cases · 29 candidate passages · 6 Qwen-token budgets · 13 budgeted configurations**

[Leaderboard](leaderboard.md) | [Benchmark README](README.md) | [Dataset](context_selection/synthetic/DATASET.md) | [Saved Results](context_selection/synthetic/results/)

## Quick Start

Run from the Omneum repository root.

```bash
# Inspect the original competitor results
cat benchmarks/context_selection/synthetic/results/tier1-competitors-20261025-v1/aggregate.csv

# Inspect the completed budget-exhaustion recovery
cat benchmarks/context_selection/synthetic/results/budget-exhaustion-recovery-20261026-v2/report.md

# Inspect the coding-domain results
rg '^domain,coding_agents,' \
  benchmarks/context_selection/synthetic/results/budget-exhaustion-recovery-20261026-v2/domain_budget_case_levels.csv
```

The original benchmark run and completed recovery use the same frozen 24-case dataset.

## Cases

| Case | Candidates | Token budgets | Expected behavior |
|---|---:|---|---|
| [`coding_api_version_change`](#coding_api_version_change) | 8 | 64–256 | Retain the installed API signature and version evidence |
| [`coding_clean_dependency`](#coding_clean_dependency) | 7 | 64–256 | Retain transactional replay-handling evidence |
| [`coding_config_conflict`](#coding_config_conflict) | 6 | 64–256 | Resolve the production port from the deployment manifest |
| [`coding_package_fix_lineage`](#coding_package_fix_lineage) | 8 | 64–256 | Prefer current implementation evidence over repeated obsolete advice |

Each case uses a frozen candidate pool with canonical claim annotations and supporting-source labels. Selection is evaluated at `64`, `96`, `128`, `160`, `192`, and `256` Qwen tokens.

## Recorded Results

The table reports the completed coding-domain evaluation, averaged across four cases and six token budgets. Corrected hybrid rows come from `budget-exhaustion-recovery-20261026-v2/domain_budget_case_levels.csv`.

| Configuration | Precision | Recall | Evidence Retention | Claim Coverage | Origin Coverage | Qwen Tokens |
|---|---:|---:|---:|---:|---:|---:|
| Omneum | 51.597% | 52.222% | 51.142% | 58.157% | 63.472% | 132.000 |
| BM25 + Omneum | 44.395% | 30.278% | 29.145% | 38.308% | 41.111% | 101.292 |
| MiniLM + Omneum | 57.986% | 43.472% | 42.164% | 47.955% | 61.875% | 103.083 |
| BGE + Omneum | 66.131% | 50.417% | 51.223% | 56.641% | 65.625% | 110.833 |
| Cohere + Omneum | 67.867% | 50.278% | 51.527% | 54.646% | 64.722% | 108.042 |

`source_precision` and `source_recall` use annotated supporting-source IDs. Evidence retention measures the retained gold evidence-span footprint. Claim coverage counts canonical claims represented in supporting passages; origin coverage follows the dataset's annotated root-origin units.

The corrected BGE hybrid increases coding evidence retention by **10.720 percentage points**, claim coverage by **17.462 points**, and origin coverage by **11.667 points** relative to its original restricted-discovery run.

## `coding_api_version_change`

**Task:** Submit a CSV export using LedgerKit 3.0.

```text
The lockfile pins LedgerKit 3.0.
How should the export job submit a CSV export using that installed API?
```

### Fixture

```text
8 candidates

old_api_docs         LedgerKit 2.6 reference
old_example          Example pinned to ledgerkit==2.6
current_api_docs     LedgerKit 3.0 reference
changelog            3.0 breaking changes
repository_code      Installed ledgerkit/exports.py
package_metadata     uv.lock resolves ledgerkit 3.0.0
test_output          Export smoke-test result
migration_guide      2.x → 3.0 migration instructions
```

Obsolete API:

```python
job = client.export_csv(account_id)
```

Installed API:

```python
job = client.exports.create(
    account_id=account_id,
    format="csv",
)
```

The installed signature is keyword-only:

```python
Exports.create(self, *, account_id, format)
```

### Recorded selections

The current evaluation ranks the eight passages under six Qwen-token budgets. The gold source annotations identify the installed `LedgerKit 3.0` implementation and migration evidence.

| Source | Evidence |
|---|---|
| `current_api_docs` | `client.exports.create()` signature |
| `repository_code` | Installed `ledgerkit/exports.py` implementation |
| `package_metadata` | `uv.lock` version resolution |
| `changelog` | LedgerKit 3.0 breaking changes |
| `migration_guide` | 2.x-to-3.0 API migration |
| `old_api_docs` | Obsolete 2.6 API |
| `old_example` | Example pinned to `ledgerkit==2.6` |

**Result:** The case measures whether budgeted selection retains the installed API contract while competing with obsolete references. The exact per-budget selections are recorded in `tier1-competitors-20261025-v1/selections.json` and the corrected recovery's `selections.json`.

## `coding_clean_dependency`

**Task:** Make replayed event IDs idempotent while committing balance updates.

```text
How should the Sable event consumer make replayed event IDs
idempotent while committing the balance update?
```

### Fixture

```text
7 candidates

repository_code      consumer.py transaction implementation
unit_test            Duplicate event replay
integration_test     Worker termination before commit
current_docs         Consumer guide
release_notes        Sable 1.8 replay behavior
package_metadata     Runtime and migration metadata
example              Transaction example
```

Required behavior:

```sql
BEGIN;

INSERT INTO processed_events (event_id)
VALUES ('evt_47')
ON CONFLICT DO NOTHING
RETURNING event_id;

-- Apply the balance update only if the insert returned a row.
-- Both writes must commit in the same transaction.

COMMIT;
```

A unique constraint on `processed_events.event_id` prevents a committed event from being applied twice. The balance update and event insertion must commit atomically.

### Recorded selections

| Source | Evidence |
|---|---|
| `repository_code` | `consumer.py` transaction boundary |
| `unit_test` | Duplicate event replay |
| `integration_test` | Worker termination before commit |
| `current_docs` | Consumer transaction semantics |
| `release_notes` | Sable 1.8 replay behavior |
| `example` | Transaction implementation example |

**Result:** The case measures retention of the transaction boundary and replay guard under constrained context budgets. `repository_code` supplies the implementation path; `integration_test` exercises the commit-failure condition. The saved selection records identify the passages retained by each method and budget.

## `coding_config_conflict`

**Task:** Determine the production readiness-probe port.

```text
For the checked-in production deployment of Harbor API,
which TCP port must the readiness probe use?
```

### Fixture

```text
6 candidates

readme               Local quick start: 8080
deployment_config    deploy/prod.yaml: 9092
source_code          server.py: APP_PORT with 8080 fallback
ci_config            Unit-test environment: 8080
test_output          Production manifest integration test
example_config       examples/local.env: 8080
```

Production manifest:

```yaml
# deploy/prod.yaml
env:
  - name: APP_PORT
    value: "9092"

readinessProbe:
  httpGet:
    path: /ready
    port: 9092
```

Application default:

```python
listen_port = int(os.environ.get("APP_PORT", "8080"))
```

The production manifest overrides the application default. Expected port: **9092**.

### Recorded selections

| Source | Configuration evidence |
|---|---|
| `deployment_config` | Production `APP_PORT=9092` and readiness probe |
| `test_output` | Production manifest integration test |
| `source_code` | `APP_PORT` environment override with `8080` fallback |
| `readme` | Local development port `8080` |
| `ci_config` | Unit-test port `8080` |
| `example_config` | `examples/local.env` port `8080` |

**Result:** The case tests selection under conflicting environment-specific configuration values. `deploy/prod.yaml` contains the production override and readiness-probe target. The local `8080` references compete for context space at every token budget.

## `coding_package_fix_lineage`

**Task:** Fix connection-pool exhaustion without adopting obsolete workaround advice.

```text
How should the client fix the connection-pool exhaustion issue?
```

### Fixture

```text
8 candidates

issue_origin         Disable connection reuse
issue_comment        Repeats the workaround
community_note       Repeats the workaround
repository_code      Bounds idle connections and evicts expired entries
release_notes        Version 4.2 fix
package_docs         Keep connection reuse enabled
test_output          Pool regression test
pull_request         Current implementation change
```

Obsolete recommendation:

```text
Disable connection reuse to prevent pool exhaustion.
```

Current fix:

```text
Keep connection reuse enabled.
Bound idle connections.
Evict expired pool entries.
```

The obsolete recommendation appears in three related candidate sources. Omneum's provenance-aware graph inference accounts for their shared evidence origins when computing source reliability and claim support, rather than treating each repeated assertion as independent support.

### Recorded selections

The corrected recovery increases retained evidence for the BGE hybrid in this case.

| Metric | Original | Corrected |
|---|---:|---:|
| Selection precision | 33.333% | 60.000% |
| Evidence retention | 21.875% | 63.542% |
| Origin coverage | 20.000% | 60.000% |
| Qwen tokens | 62 | 113 |

The correction extends discovery beyond the initial expanded neighborhood after its feasible utility is exhausted. Deferred passages must meet the marginal utility-density threshold established by the initial selection.

**Result:** BGE + Omneum increases evidence retention by **41.667 percentage points** and origin coverage by **40 points** in the recorded recovery comparison. The selected context expands from 62 to 113 Qwen tokens while precision increases from 33.333% to 60%.

The recovery preserves the initial selection and admits additional supporting evidence. Remaining exclusions follow the selector's relevance and marginal-utility constraints.

## Inspect Recorded Runs

Authoritative run directories:

```text
benchmarks/context_selection/synthetic/
├── results/
│   ├── tier1-production-20261025-v1/
│   ├── tier1-competitors-20261025-v1/
│   └── budget-exhaustion-recovery-20261026-v2/
└── analysis/
    └── tier1-competitive-analysis-20261026-v1/
```

Inspect the recorded selection results:

```bash
# Original competitor selections
rg -n '"case_id": "coding_' \
  benchmarks/context_selection/synthetic/results/tier1-competitors-20261025-v1/selections.json

# Corrected Omneum selections
rg -n '"case_id": "coding_' \
  benchmarks/context_selection/synthetic/results/budget-exhaustion-recovery-20261026-v2/selections.json

# Corrected domain and budget aggregates
cat benchmarks/context_selection/synthetic/results/budget-exhaustion-recovery-20261026-v2/domain_budget_case_levels.csv
```

Inspect the aggregate comparison:

```bash
cat benchmarks/context_selection/synthetic/results/tier1-competitors-20261025-v1/aggregate.csv

cat benchmarks/context_selection/synthetic/results/budget-exhaustion-recovery-20261026-v2/aggregate.csv
```

Inspect the recovery validation:

```bash
cat benchmarks/context_selection/synthetic/results/budget-exhaustion-recovery-20261026-v2/analysis_validation.json

cat benchmarks/context_selection/synthetic/results/budget-exhaustion-recovery-20261026-v2/improvement_coverage.csv
```

The corrected evaluation preserves the original passages in all 720 Omneum selection cells. The saved audit reproduces selection-quality metrics and checks the corrected outputs against their frozen annotations.

## Evaluation Notes

| Setting | Value |
|---|---|
| Cases | 4 coding cases |
| Candidate pools | 6–8 passages |
| Token budgets | 64, 96, 128, 160, 192, 256 |
| Tokenizer | Qwen2.5 7B GGUF |
| Configurations | 13 budgeted methods plus `raw_full` |
| Ranking trials | 2 saved trials per case |
| Selection entry point | `prepare_context(question=...)` |
| Standalone Omneum relevance | Default lexical relevance |
| Hybrid selection policy | `coverage_support_density` |
| Complementary evidence | `True` |
| Token cost exponent | `1` |
| Discovery anchors | 3 plus score ties |
| Expansion depth | 2 |
| Conflict-aware selection | `False` |
| Source scoring | Annotated supporting-source IDs |
| Evidence scoring | Retained gold evidence-span footprint |
| Claim scoring | Canonical claims represented in supporting passages |
| Origin scoring | Annotated root-origin units |
| Latency | Local post-ranking selection |
| Source revision | `6d430d4efd28559a262212e9f88aba63c080238a` |

The corrected hybrid selector uses staged budget-exhaustion recovery. Original selected passages remain present, and deferred candidates are admitted subject to the recorded utility-density floor. Recovery increases coding-domain completeness for MiniLM and BGE while changing the selected context footprint.

The benchmark uses `tokenizer_tokens` to enforce Qwen budgets. `actual_context_tokens` records the word/punctuation footprint, including rendered passage headers. The two fields have different counting semantics.

Local selection timing begins after relevance scores and structured observations are available. The measured local interval includes graph evaluation, candidate discovery, packing, reconstruction, and SDK verification. Provider ranking latency and extraction are recorded separately.

**Known dataset issue:** `coding_package_fix_lineage` preserves a candidate-type mismatch: matrix slot 3 is labeled `issue_comment`, while the canonical candidate is a community note. The frozen fixture remains unchanged.

These four cases use synthetic software-engineering packages and repositories. The full 24-case evaluation and paired confidence intervals are recorded in [Leaderboard](leaderboard.md) and the [Benchmark README](README.md).