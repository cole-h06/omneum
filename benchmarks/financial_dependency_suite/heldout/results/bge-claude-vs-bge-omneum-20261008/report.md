# Experiment 1: BGE → Claude judge versus BGE → Omneum

Completed 24 cases, one trial per arm. Run ID: `bge-claude-vs-bge-omneum-20261008`. This report is derived solely from the immutable saved results; no paid API calls were rerun.

## Quality

| Metric | Control | Treatment |
|---|---:|---:|
| Correct / incorrect / unscored / generation failures | 21 / 0 / 3 / 0 | 21 / 0 / 2 / 1 |
| Selection failures | 0 | 0 |
| Recorded answer accuracy | 87.50% | 87.50% |
| Substantively fully correct | 23/24 (95.83%) | 22/24 (91.67%) |
| Selection precision, case average | 92.36% | 86.11% |
| Selection recall, case average | 65.24% | 59.34% |
| Selection precision, pooled | 92.75% | 86.96% |
| Selection recall, pooled | 61.54% | 57.69% |

Recorded answer outcomes from treatment perspective: 2 wins, 2 losses, 20 ties. Substantive outcomes: 1 win, 2 losses, 21 ties. Selection outcomes: 0 wins, 3 losses, 21 ties. Recall is against all supporting sources, including cases with more supporting sources than context slots.

## Scoring and case findings

- coding_package_fix_lineage: both unscored answers correctly bound idle entries, evict expired connections, and retain reuse. Inflected wording misses literal required phrases.
- multi_agent_independent_error: the control correctly specifies a 120-second wait, but is unscored because the required substring is "120 seconds". This recorded treatment win is a substantive tie.
- support_resolution_conflict: the control recommends rollback with verification enabled but omits tb17, making it incomplete. Treatment provides tb17.
- research_independent_false_consensus: treatment answers 240 occupied homes with caveats, versus ground truth 216; the scorer marks this wrong answer unscored.
- support_stale_runbook: treatment receives an empty Claude generation refusal despite selecting the same supporting-source set as control.
- Selection precision/recall regress on coding_config_conflict, multi_agent_relevant_wrong_task, and research_independent_false_consensus.

## Latency

Seconds, median / p95; all 24 records included. Linear interpolation at (n − 1) × q. For the refusal record, end-to-end is reconstructed as saved selection plus generation duration, following the aggregator.

| Stage | Control | Treatment |
|---|---:|---:|
| Shared BGE | 0.210 / 0.283 | 0.210 / 0.283 |
| Claude judge / Omneum core evaluation | 1.549 / 2.230 | 0.030 / 0.037 |
| Full selection | 1.831 / 2.446 | 0.697 / 0.981 |
| Generation | 2.196 / 3.307 | 2.278 / 4.014 |
| End-to-end | 4.165 / 5.465 | 3.141 / 4.722 |

Omneum full integration before BGE: 0.474 / 0.592 seconds, including the first-case 2.246-second integration duration. Full-selection median/p95 fell 61.9% / 59.9%; end-to-end fell 24.6% / 13.6%. Treatment was faster end-to-end in 20/24 cases.

## API usage and estimated costs

| Tokens | Control | Treatment |
|---|---:|---:|
| Evaluator input / output | 15,802 / 702 | 0 / 0 |
| Evaluator total | 16,504 | 0 |
| Generator input / output | 5,669 / 5,687 | 5,661 / 6,150 |
| Generator total | 11,356 | 11,811 |
| Total Anthropic tokens | 27,860 | 11,811 |

Total API tokens decrease 57.6%. BGE and Omneum run locally. For comparison with Experiment 2, estimates use the published Sonnet 5.5 rates verified during that experiment: $2/M input and $10/M output (https://platform.claude.com/docs/en/about-claude/pricing). Judge: $0.038624 versus $0. Generator: $0.068208 versus $0.072822. Total: $0.106832 versus $0.072822, 31.8% less. Local compute is excluded. The original summary has no configured pricing; the earlier conversational report used illustrative $3/$15 rates.

## Verification and reproducibility

All 24 pairs have identical BGE shortlist IDs, order, text, scores, and hashes; context budgets match the frozen inputs (21 cases at 3, 3 at 2). All 48 input hashes match the saved manifest. Both arms use the existing Anthropic generator with claude-sonnet-5-5 and the same prompt template and 1024-token cap; each arm supplies its selected context. Treatment uses local Omneum and has zero Claude judge tokens/calls.

Re-run command (requires explicit authorization for paid APIs):

```sh
.venv/bin/python -m benchmarks.financial_dependency_suite.heldout.run_benchmark --methods bge_anthropic bge_omneum --trials 1 --run-id NEW_UNIQUE_RUN_ID
```

The saved manifest records the original dirty-workspace implementation fingerprint, package versions, estimator settings, git commit, and input hashes. It is retained without rewriting provenance. BGE/Omneum selector algorithms and frozen scoring remain unchanged. The current paired-route tests cover identical shortlist inputs, budget/settings parity, treatment isolation, and partial-run continuation.

## All case outcomes

| Case | Control score | Treatment score | Substantive outcome | Selection outcome |
|---|---|---|---|---|
| analytics_derived_metric_cycle | correct | correct | tie | tie |
| analytics_incomplete_lineage | correct | correct | tie | tie |
| analytics_metric_definition_conflict | correct | correct | tie | tie |
| analytics_stale_dashboard | correct | correct | tie | tie |
| coding_api_version_change | correct | correct | tie | tie |
| coding_clean_dependency | correct | correct | tie | tie |
| coding_config_conflict | correct | correct | tie | loss |
| coding_package_fix_lineage | unscored | unscored | tie | tie |
| enterprise_partial_lineage | correct | correct | tie | tie |
| enterprise_policy_copy_chain | correct | correct | tie | tie |
| enterprise_semantic_distractors | correct | correct | tie | tie |
| enterprise_stale_handbook | correct | correct | tie | tie |
| multi_agent_feedback_loop | correct | correct | tie | tie |
| multi_agent_independent_error | unscored | correct | tie | tie |
| multi_agent_relevant_wrong_task | correct | correct | tie | loss |
| multi_agent_repeated_subagent | correct | correct | tie | tie |
| research_clean_consensus | correct | correct | tie | tie |
| research_conflicting_reports | correct | correct | tie | tie |
| research_independent_false_consensus | correct | unscored | loss | loss |
| research_syndicated_reporting | correct | correct | tie | tie |
| support_clean_resolution | correct | correct | tie | tie |
| support_resolution_conflict | unscored | correct | win | tie |
| support_stale_runbook | correct | generation_failure | loss | tie |
| support_ticket_reference_loop | correct | correct | tie | tie |

Omneum maintained broadly comparable answer quality while reducing judge API cost and latency. Equal recorded accuracy masks one wrong answer, one refusal, and lower selection quality, so this run does not demonstrate quality parity.
