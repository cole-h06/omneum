# Experiment 2: Cohere → Claude judge versus Cohere → Omneum

Completed all 24 frozen cases, one trial per arm. Run ID: `cohere-claude-vs-cohere-omneum-20261008`. No staging or commits.

The paired route reuses the existing reranker, Claude judge, Omneum selector, and Anthropic generator. 181 regression tests passed; two unrelated vector/BGE model-download tests were deselected. No selection behavior was tuned.

## Quality

| Metric | Cohere → Claude judge | Cohere → Omneum |
|---|---:|---:|
| Correct / incorrect / unscored / generation failures | 22 / 0 / 2 / 0 | 20 / 0 / 4 / 0 |
| Selection failures | 0 | 0 |
| Recorded answer accuracy | 91.67% | 83.33% |
| Manually reviewed fully correct answers | 23/24 (95.83%) | 21/24 (87.50%) |
| Other substantive outcomes | 1 partial | 1 partial, 1 unanswered, 1 wrong |
| Selection precision, case average | 91.67% | 82.64% |
| Selection recall, case average | 64.40% | 55.72% |
| Selection precision, pooled | 92.75% | 84.06% |
| Selection recall, pooled | 61.54% | 55.77% |

Recorded and substantive answer comparisons: 0 treatment wins, 2 losses, 22 ties. Selection precision/recall: 0 wins, 4 losses, 20 ties. Selection recall is against all ground-truth supporting sources, some of which exceed the context budget.

Both package-fix answers are substantively correct but miss the literal scoring phrases. Both trust-bundle answers give the right strategy but omit tb17 and are incomplete. The treatment abstains on the production-port case after selecting local/CI sources; it reports an incorrect 240-home estimate with caveats on the census case, where the correct count is 216.

## Latency

Seconds, median / p95. All stages cover all 24 records; percentiles use linear interpolation at (n − 1) × q. End-to-end is the recorded selection duration plus generation duration.

| Stage | Control | Treatment |
|---|---:|---:|
| Shared Cohere | 0.209 / 8.928 | 0.209 / 8.928 |
| Claude judge / Omneum core evaluation | 1.755 / 2.261 | 0.030 / 0.037 |
| Full selection | 2.358 / 10.157 | 1.003 / 9.489 |
| Generation | 2.293 / 3.977 | 2.407 / 3.801 |
| End-to-end | 4.897 / 13.041 | 4.326 / 12.539 |

Omneum full integration before adding Cohere: 0.490 / 0.572 seconds. Integration overhead beyond core evaluation: 0.460 / 0.538 seconds.

Full-selection median/p95 decreased 57.5% / 6.6%; end-to-end decreased 11.7% / 3.8%. Treatment was faster end-to-end in 22/24 cases. Shared Cohere spikes dominated tail latency (35.338 seconds on coding_config_conflict; 9.043 seconds on support_ticket_reference_loop). No outliers were excluded.

## API usage and cost

| Tokens | Control | Treatment |
|---|---:|---:|
| Evaluator input / output | 15,818 / 709 | 0 / 0 |
| Evaluator total | 16,527 | 0 |
| Generator input / output | 5,680 / 5,954 | 5,587 / 6,055 |
| Generator total | 11,634 | 11,642 |
| Total Anthropic tokens | 28,161 | 11,642 |

Cohere returned 24 billed search units for 24 shared reranks. Its input/output token counts were not supplied and remain null. The shared rerank billing must be counted once across the actual paired run.

Claude estimates use published Sonnet 5.5 rates of $2/M input and $10/M output tokens: https://platform.claude.com/docs/en/about-claude/pricing . Judge cost: $0.038726 versus $0. Generation: $0.070900 versus $0.071724. Total Anthropic cost: $0.109626 versus $0.071724, a 34.6% decrease. Total Anthropic tokens decrease 58.7%.

Cohere's current primary pricing page does not expose a pay-as-you-go Rerank 4 Pro rate: https://cohere.com/pricing . At an illustrative $2.50/1,000 search units, the shared Cohere cost is $0.060000. Standalone pipeline estimates, each including its own 24-rerank workload, are $0.169626 versus $0.131724 (22.3% less). Actual paired-run total, counting Cohere once: $0.241350. These are estimates, not an invoice; local compute is excluded.

## Verification

All 24 pairs have identical Cohere shortlist IDs, order, text, scores, and recomputed hashes. Final context budgets match frozen fixtures (21 cases at 3; 3 at 2), and selected IDs remain within the shared shortlist. Generation uses the same prompt template, Anthropic provider, claude-sonnet-5-5 model, and 1024-token cap; prompt source content follows each arm's final selection. Regression tests verify byte-identical prompts when the selected context matches.

24 control Claude judge calls and 48 Claude answer generations completed. The treatment routes directly to local Omneum, with zero evaluator API calls and tokens. Existing fixtures, scoring, historical results, and Omneum algorithms were preserved: 213 file hashes match the pre-run snapshot and all 48 input hashes match the run manifest.

## Case comparisons

Outcomes are from the treatment perspective. C = recorded correct; U = recorded unscored.

| Case | Control score | Treatment score | Substantive outcome | Selection outcome |
|---|:---:|:---:|---|---|
| analytics_derived_metric_cycle | C | C | tie | tie |
| analytics_incomplete_lineage | C | C | tie | tie |
| analytics_metric_definition_conflict | C | C | tie | loss |
| analytics_stale_dashboard | C | C | tie | tie |
| coding_api_version_change | C | C | tie | tie |
| coding_clean_dependency | C | C | tie | tie |
| coding_config_conflict | C | U | loss | loss |
| coding_package_fix_lineage | U | U | tie | tie |
| enterprise_partial_lineage | C | C | tie | tie |
| enterprise_policy_copy_chain | C | C | tie | tie |
| enterprise_semantic_distractors | C | C | tie | tie |
| enterprise_stale_handbook | C | C | tie | tie |
| multi_agent_feedback_loop | C | C | tie | tie |
| multi_agent_independent_error | C | C | tie | tie |
| multi_agent_relevant_wrong_task | C | C | tie | tie |
| multi_agent_repeated_subagent | C | C | tie | tie |
| research_clean_consensus | C | C | tie | tie |
| research_conflicting_reports | C | C | tie | tie |
| research_independent_false_consensus | C | U | loss | loss |
| research_syndicated_reporting | C | C | tie | loss |
| support_clean_resolution | C | C | tie | tie |
| support_resolution_conflict | U | U | tie | tie |
| support_stale_runbook | C | C | tie | tie |
| support_ticket_reference_loop | C | C | tie | tie |

Selection regressions: analytics_metric_definition_conflict P/R 1.000/1.000 → 0.667/0.667; coding_config_conflict 0.500/0.500 → 0/0; research_independent_false_consensus 1.000/1.000 → 0/0; research_syndicated_reporting 1.000/0.750 → 0.667/0.500.

Omneum eliminates Claude judge API cost and reduces latency, but this run has two substantive answer regressions and lower selection quality. It does not establish maintained answer-quality parity. No further experiments or tuning were performed.
