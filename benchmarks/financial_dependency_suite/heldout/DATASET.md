# Held-out dataset audit

The 24 static case pairs follow `case_matrix.json` and `plan.json`. These are
synthetic, self-contained scenarios; `benchmark.example` URLs identify fixture
artifacts, not fetched publications. No provider or selection-method output was
used to author them. Candidate order follows the matrix source order and is not
an ordering of quality. The original example is preserved byte for byte.

`case.json` contains source excerpts, normalized claims, and source history only.
`ground_truth.json` contains the answer, the eligible supporting-source set, and
terms for the existing scorer. Supporting-source sets can exceed the context
budget: they enumerate eligible evidence, not a demand to select every source.
No selection policy, expected method winner, or quality score is encoded in
provenance. The new records use the matrix source roles as `source.kind`; the
original example uses the generic `web_document` kind.

Source links describe the scenario's publishing or processing history, independently
of the answer labels. A citation is not necessarily an assertion dependency.
Cycles are references among mutable notes or recurring ETL snapshots, not claims
that three immutable artifacts were each created before the others. Missing
metadata in the partial-lineage cases is deliberately left absent. In those cases,
a broad folder/import citation can connect artifacts making different claims;
it does not establish which claim is true. The loader's existing conversion of
missing relation fields to empty tuples is unchanged.

## Scenario and history review

| Case | Scenario and history |
| --- | --- |
| coding_api_version_change | Versioned export API, archived example branch, installed source and CI execution. |
| coding_config_conflict | Production environment override versus local defaults and CI configuration. |
| coding_clean_dependency | Transactional event deduplication; tests, code, documentation, and an example with a documented derivation. |
| enterprise_policy_copy_chain | Domestic meal receipts; a Confluence root branches through wiki, Slack, email, and a merged manager note. |
| enterprise_stale_handbook | Volunteer leave entitlement; archived benefits branch versus an effective-dated policy and HR rollout. |
| enterprise_partial_lineage | Chat transcript retention; lost revision dates, a partial mirror chain, and a retained folder-level email citation. |
| enterprise_semantic_distractors | Contractor VPN revocation versus onboarding, staging rotation, payroll, hardware return, and project deadlines. |
| research_syndicated_reporting | Bus acceptance versus order quantity; multi-hop syndication and separate depot inspection. |
| research_conflicting_reports | Net forest change versus gross gains; primary accounting and raster analysis. |
| research_independent_false_consensus | Occupied homes versus visible housing units; independently produced map, facade, parcel, and door-number estimates. |
| research_clean_consensus | Bridge opening date; municipal records, independent on-site reports, and derived publications. |
| multi_agent_repeated_subagent | Planned versus recorded dispatch; researcher fan-out, analyst merge, and a verifier joining two operational records. |
| multi_agent_feedback_loop | Release approval; a three-note citation loop alongside gate checks and a tool-backed verifier. |
| multi_agent_independent_error | Retry header units; isolated agents share a unit misconception without consuming each other's answers. |
| multi_agent_relevant_wrong_task | Unfinished production upload retention versus download URLs, staging uploads, audit events, and credentials. |
| analytics_stale_dashboard | Backfilled paid-seat totals; immutable dashboard/export branch versus refreshed warehouse and metric store. |
| analytics_derived_metric_cycle | Active accounts versus session rows; dashboard CSV repair loop alongside source ledgers and a distinct-count query. |
| analytics_metric_definition_conflict | Gross retention versus expansion-inclusive retention; two definition pipelines with different formulas. |
| analytics_incomplete_lineage | Delivered parcels versus dispatch rows; disconnected migrated transform/dashboard paths and a broad import tag. |
| support_stale_runbook | Key refresh across software versions; newly copied old advice versus current deployment behavior. |
| support_ticket_reference_loop | Paused consumer recovery; ticket/KB/retrospective loop alongside current state and a canary drain test. |
| support_resolution_conflict | TLS trust-bundle incident; competing ticket remedies, a deployment diff, and comparative probes. |
| support_clean_resolution | Completed maintenance; consistent command evidence from runbook, config, state, monitoring, and history. |

## Local validation

From the repository root, in an environment with the repository and pytest installed:

```sh
python -m benchmarks.financial_dependency_suite.heldout.validate_dataset
python -m pytest benchmarks/financial_dependency_suite/heldout
```

The validator imports the loader and scorer only. The held-out runner tests use
mocks. Neither command invokes benchmark methods, downloads models, or calls
providers. The dataset tests check exact membership, counts, budgets, source roles,
strict field allowlists, reference integrity, timezone-aware timestamps, SDK
observation construction, reference-answer scoring, and obvious label leakage.
They also check mechanism structure and use corrupted fixtures to test rejection.
Leakage heuristics cannot establish semantic independence or prove the absence of
all indirect cues; the scenario review above remains necessary.

`dataset_manifest.json` pins SHA-256 digests of all 48 case/truth files plus the
existing specification, loader, runner, methods, scoring, and parent README.
This makes subsequent input edits visible locally; it is not permission to tune
fixtures after final evaluation. No runtime selector reads this audit manifest.

## Preserved specification limitations

- The existing `coding_package_fix_lineage` matrix requests two issue comments,
  but its third candidate is a community note at `/community/pool-workaround`.
  Exact source-role conformance for that one existing slot conflicts with the
  instruction to preserve the example. Validation reports this explicit exception;
  all 23 new cases match matrix source roles exactly.
- The supplied README is in the parent benchmark directory; there was no held-out
  README. It and the root README were read, without modifying either.
- Answer scoring normalizes strings and checks substrings, without numeric,
  date, paraphrase, or negation reasoning. For example, a negated forbidden phrase
  can still fail the canonical case, and a differently formatted number can be
  unscored. New ground truths use minimal identifying required terms and empty
  forbidden lists where contradictory values can legitimately appear in an
  explanation. The scorer is unchanged. Reference answers pass it, but this does
  not imply it recognizes every valid generated answer.
- Matrix order itself groups many source roles. No shuffle was added and no
  position-dependent method was introduced. No empirical method ranking is claimed.

No design issue blocked any of the 23 new implementations. The pre-existing
source-role mismatch remains visible rather than being silently repaired.

## Files created

All 50 paths below are relative to `benchmarks/financial_dependency_suite/heldout/`.
No pre-existing repository file was modified by this implementation.

```text
cases/analytics_derived_metric_cycle/case.json
cases/analytics_derived_metric_cycle/ground_truth.json
cases/analytics_incomplete_lineage/case.json
cases/analytics_incomplete_lineage/ground_truth.json
cases/analytics_metric_definition_conflict/case.json
cases/analytics_metric_definition_conflict/ground_truth.json
cases/analytics_stale_dashboard/case.json
cases/analytics_stale_dashboard/ground_truth.json
cases/coding_api_version_change/case.json
cases/coding_api_version_change/ground_truth.json
cases/coding_clean_dependency/case.json
cases/coding_clean_dependency/ground_truth.json
cases/coding_config_conflict/case.json
cases/coding_config_conflict/ground_truth.json
cases/enterprise_partial_lineage/case.json
cases/enterprise_partial_lineage/ground_truth.json
cases/enterprise_policy_copy_chain/case.json
cases/enterprise_policy_copy_chain/ground_truth.json
cases/enterprise_semantic_distractors/case.json
cases/enterprise_semantic_distractors/ground_truth.json
cases/enterprise_stale_handbook/case.json
cases/enterprise_stale_handbook/ground_truth.json
cases/multi_agent_feedback_loop/case.json
cases/multi_agent_feedback_loop/ground_truth.json
cases/multi_agent_independent_error/case.json
cases/multi_agent_independent_error/ground_truth.json
cases/multi_agent_relevant_wrong_task/case.json
cases/multi_agent_relevant_wrong_task/ground_truth.json
cases/multi_agent_repeated_subagent/case.json
cases/multi_agent_repeated_subagent/ground_truth.json
cases/research_clean_consensus/case.json
cases/research_clean_consensus/ground_truth.json
cases/research_conflicting_reports/case.json
cases/research_conflicting_reports/ground_truth.json
cases/research_independent_false_consensus/case.json
cases/research_independent_false_consensus/ground_truth.json
cases/research_syndicated_reporting/case.json
cases/research_syndicated_reporting/ground_truth.json
cases/support_clean_resolution/case.json
cases/support_clean_resolution/ground_truth.json
cases/support_resolution_conflict/case.json
cases/support_resolution_conflict/ground_truth.json
cases/support_stale_runbook/case.json
cases/support_stale_runbook/ground_truth.json
cases/support_ticket_reference_loop/case.json
cases/support_ticket_reference_loop/ground_truth.json
DATASET.md
dataset_manifest.json
test_dataset.py
validate_dataset.py
```
