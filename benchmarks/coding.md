
# Coding Agents

Context-selection benchmark for software-engineering agents. Tests version-specific APIs, repository evidence, deployment configuration, and source lineage.

**4 held-out cases · 29 candidate sources · Claude Sonnet 5.5 generator**

[Leaderboard](leaderboard.md) | [Benchmark README](README.md) | [Dataset](context_evaluation/heldout/DATASET.md) | [Saved Results](context_evaluation/heldout/results/)

## Quick Start

Run from the Omneum repository root.

```bash
# Validate all 24 held-out cases, including the four coding cases
.venv/bin/python -m benchmarks.context_evaluation.heldout.validate_dataset

# Run offline benchmark tests
.venv/bin/python tools/run_context_evaluation_tests.py -q

# Verify saved publication metrics
.venv/bin/python -m benchmarks.context_evaluation.heldout.build_dashboard_summary --check
```

No provider calls. These commands verify the frozen dataset, benchmark tests, and saved dashboard; they do not generate new model responses.

Latest verified test result:

```text
572 passed, 15 skipped
```

## Cases

| Case | Candidates | Budget | Expected behavior |
|---|---:|---:|---|
| [`coding_api_version_change`](#coding_api_version_change) | 8 | 3 | Use the installed API, not obsolete examples |
| [`coding_clean_dependency`](#coding_clean_dependency) | 7 | 3 | Select atomic replay-handling evidence |
| [`coding_config_conflict`](#coding_config_conflict) | 6 | 2 | Prefer production configuration over local defaults |
| [`coding_package_fix_lineage`](#coding_package_fix_lineage) | 8 | 3 | Discount repeated obsolete workaround advice |

Each case uses a fixed candidate pool, relevance labels, and selection budget.

## Recorded Results

BGE + Omneum results below use the 10-trial GPT-6 Astra pairing. Claude and Cohere comparisons use one trial per case.

| Case | BGE + Omneum Precision | Recall | Answer | Selection p50 |
|---|---:|---:|---|---:|
| API version change | 100% | 60% | 10/10 correct | 0.757s |
| Clean dependency | 100% | 50% | 10/10 correct | 0.611s |
| Configuration conflict | 50% | 50% | 10/10 correct | 0.623s |
| Package fix lineage | 100% | 60% | 10/10 unscored | 0.593s |

`unscored` is a separate recorded status, not an incorrect-answer verdict. Selection precision and recall use fixture relevance labels.

## `coding_api_version_change`

**Task:** Submit a CSV export using LedgerKit 3.0.

```text
The lockfile pins LedgerKit 3.0.
How should the export job submit a CSV export using that installed API?
```

### Fixture

```text
8 candidates
3 selected

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

| Method | Trials | Selected sources | P | R | Answer | Selection p50 |
|---|---:|---|---:|---:|---|---:|
| BGE + Claude Judge | 1 | `current_api_docs`, `repository_code`, `changelog` | 100% | 60% | 1/1 correct | 2.450s |
| BGE + GPT-6 Astra Judge | 10 | Same | 100% | 60% | 10/10 correct | 3.005s |
| BGE + Gemini Judge | 10 | Same | 100% | 60% | 10/10 correct | 4.993s |
| **BGE + Omneum** | **10** | Same | **100%** | **60%** | **10/10 correct** | **0.757s** |
| Cohere + Claude Judge | 1 | `current_api_docs`, `repository_code`, `package_metadata` | 67% | 40% | 1/1 correct | 1.703s |
| Cohere + Omneum | 1 | `package_metadata`, `current_api_docs`, `repository_code` | 67% | 40% | 1/1 correct | 0.637s |

**Result:** Omneum matched the BGE + judge selections at lower selection latency. Both Cohere configurations included `package_metadata` instead of `changelog`, reducing scored relevance without changing answer correctness.

## `coding_clean_dependency`

**Task:** Make replayed event IDs idempotent while committing balance updates.

```text
How should the Sable event consumer make replayed event IDs
idempotent while committing the balance update?
```

### Fixture

```text
7 candidates
3 selected

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

A unique constraint on `processed_events.event_id` prevents a committed event from being applied twice. The balance update and event insertion must be atomic.

### Recorded selections

| Method | Trials | Selected sources | P | R | Answer | Selection p50 |
|---|---:|---|---:|---:|---|---:|
| BGE + Claude Judge | 1 | `current_docs`, `repository_code`, `example` | 100% | 50% | 1/1 correct | 1.501s |
| BGE + GPT-6 Astra Judge | 10 | `current_docs`, `repository_code`, `integration_test` | 100% | 50% | 10/10 correct | 3.063s |
| BGE + Gemini Judge | 10 | `current_docs`, `repository_code`, `example` | 100% | 50% | 10/10 correct | 5.776s |
| **BGE + Omneum** | **10** | `integration_test`, `repository_code`, `release_notes` | **100%** | **50%** | **10/10 correct** | **0.611s** |
| Cohere + Claude Judge | 1 | `current_docs`, `repository_code`, `example` | 100% | 50% | 1/1 correct | 4.487s |
| Cohere + Omneum | 1 | `current_docs`, `release_notes`, `repository_code` | 100% | 50% | 1/1 correct | 2.974s |

Some GPT-6 and Gemini trials vary source ordering.

**Result:** All methods selected three relevant sources and generated correct answers. Omneum preferred implementation, integration-test, and release-note evidence, with the lowest BGE-based selection latency.

## `coding_config_conflict`

**Task:** Determine the production readiness-probe port.

```text
For the checked-in production deployment of Harbor API,
which TCP port must the readiness probe use?
```

### Fixture

```text
6 candidates
2 selected

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

The production manifest overrides the default. Expected answer: **9092**.

### Recorded selections

| Method | Trials | Selected sources | P | R | Answer | Selection p50 |
|---|---:|---|---:|---:|---|---:|
| BGE + Claude Judge | 1 | `deployment_config`, `test_output` | 100% | 100% | 1/1 correct | 1.979s |
| BGE + GPT-6 Astra Judge | 10 | Same | 100% | 100% | 10/10 correct | 2.097s |
| BGE + Gemini Judge | 10 | Same | 100% | 100% | 10/10 correct | 3.568s |
| **BGE + Omneum** | **10** | `readme`, `deployment_config` | 50% | 50% | 10/10 correct | **0.623s** |
| Cohere + Claude Judge | 1 | `deployment_config`, `readme` | 50% | 50% | 1/1 correct | 36.949s |
| Cohere + Omneum | 1 | `example_config`, `ci_config` | 0% | 0% | 1/1 unscored | 35.866s |

**Result:** Omneum included the relevant production manifest but missed the integration-test evidence. The generator still answered `9092` correctly. Cohere + Omneum selected only local-environment evidence and produced an unscored response.

This case separates correct answer generation from correct evidence selection.

## `coding_package_fix_lineage`

**Task:** Fix connection-pool exhaustion without adopting obsolete workaround advice.

```text
How should the client fix the connection-pool exhaustion issue?
```

### Fixture

```text
8 candidates
3 selected

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

Three candidate sources repeat the same outdated recommendation. Their apparent agreement does not establish independent support.

### Recorded selections

| Method | Trials | Selected sources | P | R | Answer | Selection p50 |
|---|---:|---|---:|---:|---|---:|
| BGE + Claude Judge | 1 | `release_notes`, `pull_request`, `package_docs` | 100% | 60% | 1/1 unscored | 1.632s |
| BGE + GPT-6 Astra Judge | 10 | `release_notes`, `package_docs`, `pull_request` | 100% | 60% | 10/10 unscored | 2.944s |
| BGE + Gemini Judge | 10 | Same | 100% | 60% | 10/10 unscored | 4.887s |
| **BGE + Omneum** | **10** | Same | **100%** | **60%** | 10/10 unscored | **0.593s** |
| Cohere + Claude Judge | 1 | `release_notes`, `pull_request`, `package_docs` | 100% | 60% | 1/1 unscored | 2.209s |
| Cohere + Omneum | 1 | `release_notes`, `pull_request`, `package_docs` | 100% | 60% | 1/1 unscored | — |

**Result:** All recorded configurations selected current-fix evidence rather than the repeated obsolete workaround. Omneum matched the BGE + judge selection quality with lower selection latency.

The Cohere + Omneum latency and complete answer-status row must be read from its saved result; the supplied report excerpt ends before those fields.

## Inspect Recorded Runs

Authoritative run directories:

```text
benchmarks/context_evaluation/heldout/results/
├── bge-claude-vs-bge-omneum-20261008/
├── bge-openai-vs-bge-omneum-20261008/
├── bge-google-vs-bge-omneum-20261008/
└── cohere-claude-vs-cohere-omneum-20261008/
```

Inspect the recorded JSONL results:

```bash
# List available result artifacts
ls benchmarks/context_evaluation/heldout/results/bge-openai-vs-bge-omneum-20261008/

# Find the four coding case records
rg -n 'coding_api_version_change|coding_clean_dependency|coding_config_conflict|coding_package_fix_lineage' \
  benchmarks/context_evaluation/heldout/results/bge-openai-vs-bge-omneum-20261008/results.jsonl
```

Inspect the published aggregate:

```bash
.venv/bin/python -m json.tool \
  benchmarks/context_evaluation/heldout/dashboard_summary.json
```

Regenerate it from saved evidence:

```bash
.venv/bin/python -m benchmarks.context_evaluation.heldout.build_dashboard_summary
```

Regeneration does not make provider calls or reproduce the original model responses.

## Evaluation Notes

| Setting | Value |
|---|---|
| Cases | 4 |
| Candidate pools | 6–8 sources |
| Selection budgets | 2–3 sources |
| Generator | Claude Sonnet 5.5 |
| BGE + GPT-6 / Gemini | 10 trials per case |
| BGE + Omneum | 10 trials per case in each paired run |
| Claude / Cohere extracts | 1 trial per case |
| Latency aggregation | Median across recorded trials |
| Selection scoring | Fixture relevance labels |

BGE + Omneum appears in three BGE paired-run files. The tables use its GPT-6 Astra pairing rather than combining repeated records into additional cases.

**Known dataset issue:** `coding_package_fix_lineage` has a documented candidate-type mismatch: matrix slot 3 is labeled `issue_comment`, while the preserved canonical candidate is a community note. The validator reports this issue without changing the frozen fixture.

These are synthetic software-engineering fixtures, not documentation for real external packages. See [Benchmark Methodology](README.md) for the complete evaluation contract.