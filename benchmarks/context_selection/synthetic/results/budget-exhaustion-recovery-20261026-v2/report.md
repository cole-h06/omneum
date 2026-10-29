# Budget-aware expanded-discovery recovery

General production correction evaluated on frozen Tier 1 inputs. No hosted APIs, new retrieval scores, gold-based selection, canonical modifications, or downstream generation. The v1 timing attempt was interrupted because its early samples overlapped tests; v2 is the isolated completed run. v1 offline alternative quality remains valid and is used only to document the rejected positive-only algorithm.

**Result: partial recovery, not elimination of the precision–completeness tradeoff.** All four hybrids gain aggregate evidence, claims and origins while retaining aggregate precision and token-efficiency advantages over their respective standalone rankers. Their absolute precision decreases versus the old restrictive hybrids. All 64-token outputs are unchanged; 96-token completeness does not regress. Larger-budget gaps shrink but remain, particularly for Cohere. Standalone is unchanged because it did not use restricted discovery.

## Root cause and production path

1. `sdk_adapter.build_observations` supplies structured claims, source identities, timestamps and provenance. `query_context.plan_context` and `dependency.estimate_dependencies` form the complete structural source/claim graph and dependency pairs. The structural service uses linked identifiers, not passage text.
2. `inference.infer`, `_reciprocal_independence`, `_claim_scores` and `_source_update` converge dependency-aware reliability and support. Claim contributions incorporate reliability, agreement, independence and source degree. These functions are unchanged. Native graph support matches every frozen trace within 1e-12, every live SDK evaluation matches that support, and the separate 24-case source-reliability audit also matches within 1e-12.
3. `context_selection._inferred_coverage_terms` sums final source contributions into existing per-claim dependency-cluster masses. The selector credits each cluster via its best selected relevance-weighted representative; it does not multiply independence a second time.
4. `query_context.discover_chunks` selects top-three score anchors plus boundary ties and calls `expand_claims` at depth two. Expansion follows claim/chunk/source adjacency; it does not mean the whole dependency graph becomes eligible.
5. Previously, `OmneumClient.prepare_context` filtered `plan["chunks"]` permanently to that expansion. `select_chunks` could only score and pack this restricted list; it stopped on no positive feasible utility and had no access to excluded candidates. This is a budget-independent discovery ceiling, not evidence that excluded passages have zero utility.
6. `select_chunks` computes exact whole-rendered proposal costs and positive marginal support density, then `reconstruct` returns selected original passages in deterministic support order, preserving text and headers. No summaries or rewritten evidence are produced.

The frozen coding_package_fix_lineage BGE/Cohere pool contains eight passages and fits in 176 Qwen tokens. Its top-three expansion exposes only issue_origin, issue_comment and release_notes (62 tokens), excluding five chunks as outside_expansion. The saved full-graph reliability for repository_code and test_output is about 0.184868 each, versus about 0.074342 for issue_origin: the information was not absent from structural inference. The restriction occurred after that inference was planned and before packing. A separate tail issue remains: dense-rank normalization assigns the lowest distinct score exactly zero, so test_output cannot earn query-weighted utility even after it becomes searchable. Relevance normalization is deliberately unchanged in this correction.

## Alternatives and selected correction

Compared four deterministic variants over the same graph, scores, passages, budgets and unchanged metric definitions. Original reproduces all 720 frozen Omneum cells. Full-pool starts greedy selection over every original candidate, which changes tight-budget choices. Positive-only recovery keeps the initial selection and then admits any positive feasible marginal utility, but loses too much precision. The selected staged recovery also retains the initial selection and searches the deferred pool after the first neighborhood exhausts positive feasible utility; it requires the existing marginal utility/token to meet the weakest utility/token actually accepted during the initial stage. This derived boundary is fixed during recovery and uses no labels, answer content, new score normalization, new model or tuned constant. If the initial stage selects nothing, the boundary is zero and positive feasible evidence can still be selected.

A mandatory occupancy target or raw relevance cutoff was rejected: neither establishes novel structural support. Repeatedly widening top-k and repacking was rejected because it can displace initial choices and repeats selection work unnecessarily. Recovery instead continues with the same covered cluster state and requires no additional graph inference. Existing explicit top_k remains a hard restriction; all-candidate, nonlinear, answer-coverage and question-only standalone behavior are unchanged.

| Variant | Hybrid | Precision % | Evidence % | Claims % | Origins % | Qwen tokens |
| --- | --- | --- | --- | --- | --- | --- |
| original | BM25 + Omneum | 65.453 | 45.789 | 64.028 | 67.998 | 103.757 |
| original | MiniLM + Omneum | 67.295 | 45.136 | 61.844 | 63.750 | 98.729 |
| original | BGE + Omneum | 73.834 | 52.018 | 70.464 | 72.373 | 106.625 |
| original | Cohere + Omneum | 79.712 | 55.416 | 71.452 | 72.025 | 104.222 |
| full_pool | BM25 + Omneum | 58.603 | 49.854 | 69.902 | 72.535 | 124.340 |
| full_pool | MiniLM + Omneum | 61.513 | 52.183 | 74.027 | 71.609 | 123.806 |
| full_pool | BGE + Omneum | 66.961 | 55.949 | 77.744 | 76.123 | 126.188 |
| full_pool | Cohere + Omneum | 66.776 | 56.714 | 75.597 | 74.861 | 126.382 |
| positive_only_recovery | BM25 + Omneum | 59.899 | 51.063 | 70.189 | 74.005 | 124.868 |
| positive_only_recovery | MiniLM + Omneum | 61.571 | 52.556 | 71.939 | 71.030 | 124.257 |
| positive_only_recovery | BGE + Omneum | 67.679 | 56.610 | 76.535 | 76.725 | 126.458 |
| positive_only_recovery | Cohere + Omneum | 69.878 | 59.492 | 76.631 | 76.366 | 126.938 |
| staged_recovery | BM25 + Omneum | 63.115 | 46.898 | 66.217 | 69.155 | 111.604 |
| staged_recovery | MiniLM + Omneum | 66.825 | 50.141 | 69.737 | 68.495 | 111.076 |
| staged_recovery | BGE + Omneum | 71.736 | 55.256 | 75.356 | 75.208 | 116.743 |
| staged_recovery | Cohere + Omneum | 74.878 | 56.202 | 72.990 | 72.859 | 112.681 |

## Before/after competitive table

Quality percentages; equal mean over 24 cases and six budgets. Original competitors and judges are reused, with trial means computed within each case-budget cell. Footprint is the original word/punctuation metric; Qwen tokens enforce the exact budget.

Metrics are unchanged: source precision/recall use annotated supporting-source IDs; evidence retention weights merged exact gold evidence spans by word/punctuation footprint; supporting-passage claim coverage intersects selected canonical claim IDs with the union in gold passages (including incidental facts and matching claims in non-gold passages); origins measure annotated root units represented by retained gold sources. These are distinct quantities. Strict minimal gold-claim coverage, downstream answer accuracy, end-to-end answer latency and real-world independence are not measured.

| Configuration | Precision | Recall | Evidence | Claims | Origins | Footprint | Reduction % | Qwen |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Omneum standalone Original | 61.549 | 52.647 | 53.425 | 75.853 | 75.521 | 108.701 | 49.347 | 129.271 |
| Omneum standalone Corrected | 61.549 | 52.647 | 53.425 | 75.853 | 75.521 | 108.701 | 49.347 | 129.271 |
| BM25 baseline | 59.153 | 55.761 | 55.792 | 66.147 | 71.053 | 114.188 | 46.965 | 136.181 |
| BM25 + Omneum Original | 65.453 | 45.579 | 45.789 | 64.028 | 67.998 | 86.389 | 60.105 | 103.757 |
| BM25 + Omneum Corrected | 63.115 | 46.863 | 46.898 | 66.217 | 69.155 | 93.292 | 56.943 | 111.604 |
| MiniLM baseline | 63.803 | 59.129 | 58.860 | 68.470 | 70.938 | 113.021 | 47.529 | 136.306 |
| MiniLM + Omneum Original | 67.295 | 44.053 | 45.136 | 61.844 | 63.750 | 80.153 | 62.998 | 98.729 |
| MiniLM + Omneum Corrected | 66.825 | 49.077 | 50.141 | 69.737 | 68.495 | 91.049 | 57.737 | 111.076 |
| BGE reranker baseline | 63.292 | 59.193 | 58.845 | 68.752 | 71.424 | 112.847 | 47.585 | 136.472 |
| BGE + Omneum Original | 73.834 | 51.354 | 52.018 | 70.464 | 72.373 | 87.167 | 59.526 | 106.625 |
| BGE + Omneum Corrected | 71.736 | 54.757 | 55.256 | 75.356 | 75.208 | 96.111 | 55.412 | 116.743 |
| Cohere baseline | 71.112 | 64.430 | 64.390 | 72.293 | 75.197 | 112.993 | 47.478 | 136.715 |
| Cohere + Omneum Original | 79.712 | 54.077 | 55.416 | 71.452 | 72.025 | 85.479 | 60.592 | 104.222 |
| Cohere + Omneum Corrected | 74.878 | 54.911 | 56.202 | 72.990 | 72.859 | 92.965 | 57.017 | 112.681 |

## Paired changes and uncertainty

50,000 paired case-cluster bootstrap resamples (seed 20261026); all six budgets stay together and judge trials are averaged first. Domain-stratified sensitivity resamples four cases within each of six domains. These are exploratory percentile intervals, with no multiple-comparison correction. Local timing repeats are not independent cases.

| Reference | Configuration | Metric | Δ pp | Relative % | 95% CI pp | Case W/T/L |
| --- | --- | --- | --- | --- | --- | --- |
| original | BGE + Omneum | Precision | -2.098 | -2.842 | [-6.520, 1.668] | 5/13/6 |
| original | BGE + Omneum | Recall | 3.403 | 6.626 | [0.972, 6.597] | 6/18/0 |
| original | BGE + Omneum | Evidence | 3.238 | 6.225 | [0.867, 6.456] | 6/18/0 |
| original | BGE + Omneum | Claims | 4.892 | 6.942 | [1.215, 10.063] | 6/18/0 |
| original | BGE + Omneum | Origins | 2.836 | 3.918 | [0.509, 6.007] | 5/19/0 |
| original | BM25 + Omneum | Precision | -2.338 | -3.572 | [-5.387, 0.476] | 3/16/5 |
| original | BM25 + Omneum | Recall | 1.285 | 2.819 | [0.000, 3.056] | 3/21/0 |
| original | BM25 + Omneum | Evidence | 1.109 | 2.422 | [0.000, 2.633] | 3/21/0 |
| original | BM25 + Omneum | Claims | 2.189 | 3.418 | [0.000, 5.535] | 3/21/0 |
| original | BM25 + Omneum | Origins | 1.157 | 1.702 | [0.000, 3.009] | 2/22/0 |
| original | Cohere + Omneum | Precision | -4.835 | -6.065 | [-9.352, -1.177] | 2/14/8 |
| original | Cohere + Omneum | Recall | 0.833 | 1.541 | [0.000, 2.361] | 2/22/0 |
| original | Cohere + Omneum | Evidence | 0.787 | 1.420 | [0.000, 2.224] | 2/22/0 |
| original | Cohere + Omneum | Claims | 1.538 | 2.152 | [0.000, 4.464] | 2/22/0 |
| original | Cohere + Omneum | Origins | 0.833 | 1.157 | [0.000, 2.361] | 2/22/0 |
| original | MiniLM + Omneum | Precision | -0.470 | -0.698 | [-4.859, 3.623] | 6/14/4 |
| original | MiniLM + Omneum | Recall | 5.025 | 11.406 | [1.528, 9.415] | 7/17/0 |
| original | MiniLM + Omneum | Evidence | 5.005 | 11.088 | [1.574, 9.333] | 7/17/0 |
| original | MiniLM + Omneum | Claims | 7.893 | 12.763 | [2.423, 14.691] | 7/17/0 |
| original | MiniLM + Omneum | Origins | 4.745 | 7.444 | [1.042, 9.329] | 5/19/0 |
| original | Omneum standalone | Precision | 0.000 | 0.000 | [0.000, 0.000] | 0/24/0 |
| original | Omneum standalone | Recall | 0.000 | 0.000 | [0.000, 0.000] | 0/24/0 |
| original | Omneum standalone | Evidence | 0.000 | 0.000 | [0.000, 0.000] | 0/24/0 |
| original | Omneum standalone | Claims | 0.000 | 0.000 | [0.000, 0.000] | 0/24/0 |
| original | Omneum standalone | Origins | 0.000 | 0.000 | [0.000, 0.000] | 0/24/0 |
| standalone | BGE + Omneum | Precision | 8.444 | 13.342 | [2.186, 15.371] | 16/3/5 |
| standalone | BGE + Omneum | Recall | -4.436 | -7.494 | [-10.192, 1.568] | 6/3/15 |
| standalone | BGE + Omneum | Evidence | -3.588 | -6.098 | [-9.058, 2.385] | 6/1/17 |
| standalone | BGE + Omneum | Claims | 6.604 | 9.606 | [1.506, 12.196] | 13/5/6 |
| standalone | BGE + Omneum | Origins | 3.785 | 5.299 | [-0.926, 8.912] | 10/8/6 |
| standalone | BM25 + Omneum | Precision | 3.962 | 6.698 | [-1.225, 9.709] | 10/2/12 |
| standalone | BM25 + Omneum | Recall | -8.897 | -15.956 | [-14.051, -3.685] | 6/1/17 |
| standalone | BM25 + Omneum | Evidence | -8.894 | -15.941 | [-14.058, -3.673] | 6/0/18 |
| standalone | BM25 + Omneum | Claims | 0.070 | 0.106 | [-5.392, 5.103] | 13/3/8 |
| standalone | BM25 + Omneum | Origins | -1.898 | -2.671 | [-8.958, 4.745] | 8/6/10 |
| standalone | Cohere + Omneum | Precision | 3.765 | 5.295 | [-2.488, 10.019] | 14/2/8 |
| standalone | Cohere + Omneum | Recall | -9.519 | -14.774 | [-15.056, -4.241] | 4/6/14 |
| standalone | Cohere + Omneum | Evidence | -8.188 | -12.716 | [-13.626, -3.047] | 7/3/14 |
| standalone | Cohere + Omneum | Claims | 0.697 | 0.965 | [-4.744, 5.407] | 13/7/4 |
| standalone | Cohere + Omneum | Origins | -2.338 | -3.109 | [-7.697, 2.373] | 5/12/7 |
| standalone | MiniLM + Omneum | Precision | 3.023 | 4.738 | [-2.033, 9.174] | 12/2/10 |
| standalone | MiniLM + Omneum | Recall | -10.051 | -16.999 | [-16.157, -3.889] | 2/2/20 |
| standalone | MiniLM + Omneum | Evidence | -8.719 | -14.814 | [-14.438, -2.770] | 3/2/19 |
| standalone | MiniLM + Omneum | Claims | 1.267 | 1.850 | [-2.664, 5.833] | 8/8/8 |
| standalone | MiniLM + Omneum | Origins | -2.442 | -3.443 | [-6.933, 1.991] | 5/7/12 |

The MiniLM and BGE evidence/origin improvement intervals lie above zero; BM25 and Cohere completeness intervals include zero because gains are sparse. Cohere precision decreases versus its old hybrid with a 95% interval below zero. Corrected precision advantages versus standalone rankers are positive point estimates for all four hybrids, but only BGE has an ordinary case-bootstrap interval wholly above zero. The other three advantages must not be described as statistically established. The stratified sensitivity intervals are included in paired_comparisons.csv; no confirmatory significance claim follows from this designed 24-case set.

## Domain and budget changes versus original Omneum


| Domain | Hybrid | Δ precision pp | Δ evidence pp | Δ claims pp | Δ origins pp |
| --- | --- | --- | --- | --- | --- |
| coding_agents | BM25 + Omneum | 0.437 | 5.698 | 11.742 | 6.944 |
| coding_agents | MiniLM + Omneum | 6.389 | 10.671 | 15.720 | 10.000 |
| coding_agents | BGE + Omneum | 5.714 | 10.720 | 17.462 | 11.667 |
| coding_agents | Cohere + Omneum | 0.437 | 3.906 | 8.333 | 4.167 |
| data_analytics_agents | BM25 + Omneum | -4.792 | 0.000 | 0.000 | 0.000 |
| data_analytics_agents | MiniLM + Omneum | -8.542 | 0.000 | 0.000 | 0.000 |
| data_analytics_agents | BGE + Omneum | -3.125 | 0.000 | 0.000 | 0.000 |
| data_analytics_agents | Cohere + Omneum | -10.000 | 0.000 | 0.000 | 0.000 |
| enterprise_rag | BM25 + Omneum | -2.083 | 0.000 | 0.000 | 0.000 |
| enterprise_rag | MiniLM + Omneum | -6.944 | 0.000 | 0.000 | 0.000 |
| enterprise_rag | BGE + Omneum | -13.889 | 0.000 | 0.000 | 0.000 |
| enterprise_rag | Cohere + Omneum | -13.889 | 0.000 | 0.000 | 0.000 |
| multi_agent_systems | BM25 + Omneum | -4.345 | 0.000 | 0.000 | 0.000 |
| multi_agent_systems | MiniLM + Omneum | 0.665 | 2.457 | 6.667 | 5.556 |
| multi_agent_systems | BGE + Omneum | -2.460 | 0.000 | 0.000 | 0.000 |
| multi_agent_systems | Cohere + Omneum | -4.167 | 0.000 | 0.000 | 0.000 |
| research_analysis_agents | BM25 + Omneum | 0.208 | 0.955 | 1.389 | 0.000 |
| research_analysis_agents | MiniLM + Omneum | 1.042 | 2.865 | 4.167 | 0.000 |
| research_analysis_agents | BGE + Omneum | 1.042 | 2.865 | 4.167 | 0.000 |
| research_analysis_agents | Cohere + Omneum | 0.000 | 0.000 | 0.000 | 0.000 |
| support_operations_agents | BM25 + Omneum | -3.452 | 0.000 | 0.000 | 0.000 |
| support_operations_agents | MiniLM + Omneum | 4.573 | 14.036 | 20.805 | 12.917 |
| support_operations_agents | BGE + Omneum | 0.129 | 5.844 | 7.722 | 5.347 |
| support_operations_agents | Cohere + Omneum | -1.389 | 0.814 | 0.893 | 0.833 |

| Budget | Hybrid | Δ precision pp | Δ evidence pp | Δ claims pp | Δ origins pp |
| --- | --- | --- | --- | --- | --- |
| 64 | BM25 + Omneum | 0.000 | 0.000 | 0.000 | 0.000 |
| 64 | MiniLM + Omneum | 0.000 | 0.000 | 0.000 | 0.000 |
| 64 | BGE + Omneum | 0.000 | 0.000 | 0.000 | 0.000 |
| 64 | Cohere + Omneum | 0.000 | 0.000 | 0.000 | 0.000 |
| 96 | BM25 + Omneum | 0.694 | 0.694 | 1.667 | 0.833 |
| 96 | MiniLM + Omneum | -0.694 | 1.371 | 2.949 | 1.528 |
| 96 | BGE + Omneum | -0.694 | 0.955 | 1.250 | 0.833 |
| 96 | Cohere + Omneum | -0.694 | 0.781 | 1.667 | 0.833 |
| 128 | BM25 + Omneum | -0.972 | 0.694 | 1.667 | 0.833 |
| 128 | MiniLM + Omneum | -0.625 | 3.714 | 6.086 | 3.056 |
| 128 | BGE + Omneum | -1.319 | 2.331 | 4.053 | 3.056 |
| 128 | Cohere + Omneum | -3.889 | 0.781 | 1.667 | 0.833 |
| 160 | BM25 + Omneum | -3.958 | 0.694 | 1.667 | 0.833 |
| 160 | MiniLM + Omneum | 0.069 | 6.940 | 10.451 | 7.500 |
| 160 | BGE + Omneum | -2.917 | 3.590 | 5.347 | 2.708 |
| 160 | Cohere + Omneum | -6.944 | 0.781 | 1.667 | 0.833 |
| 192 | BM25 + Omneum | -4.464 | 1.290 | 2.803 | 2.222 |
| 192 | MiniLM + Omneum | -1.369 | 7.197 | 12.244 | 6.667 |
| 192 | BGE + Omneum | -3.730 | 4.924 | 7.410 | 4.097 |
| 192 | Cohere + Omneum | -8.194 | 0.781 | 1.667 | 0.833 |
| 256 | BM25 + Omneum | -5.327 | 3.280 | 5.328 | 2.222 |
| 256 | MiniLM + Omneum | -0.198 | 10.806 | 15.629 | 9.722 |
| 256 | BGE + Omneum | -3.929 | 7.630 | 11.291 | 6.319 |
| 256 | Cohere + Omneum | -9.286 | 1.595 | 2.560 | 1.667 |

The paired_domain_budget.csv file includes every metric, budget-level case-bootstrap interval, and comparisons against standalone baselines and judges. Domain slices contain only four cases and should not be treated as stable population estimates.

Changing a case is not the same as improving evidence. Actual positive gains are concentrated as follows; unchanged cells are not counted as improvements.

| Hybrid | Metric | Improved cases / 24 | Domains with improving cases / 6 | Improved cells / 144 |
| --- | --- | --- | --- | --- |
| BM25 + Omneum | Evidence | 3 | 2 | 8 |
| BM25 + Omneum | Origins | 2 | 1 | 7 |
| MiniLM + Omneum | Evidence | 7 | 4 | 23 |
| MiniLM + Omneum | Origins | 5 | 3 | 17 |
| BGE + Omneum | Evidence | 6 | 3 | 17 |
| BGE + Omneum | Origins | 5 | 2 | 13 |
| Cohere + Omneum | Evidence | 2 | 2 | 6 |
| Cohere + Omneum | Origins | 2 | 2 | 6 |

| Budget | Hybrid | Old evidence gap vs baseline pp | Corrected evidence gap pp | Old origin gap pp | Corrected origin gap pp |
| --- | --- | --- | --- | --- | --- |
| 64 | BM25 + Omneum | 2.091 | 2.091 | 5.208 | 5.208 |
| 64 | MiniLM + Omneum | -0.942 | -0.942 | -1.389 | -1.389 |
| 64 | BGE + Omneum | 6.254 | 6.254 | 13.194 | 13.194 |
| 64 | Cohere + Omneum | -0.270 | -0.270 | 2.431 | 2.431 |
| 96 | BM25 + Omneum | -5.790 | -5.095 | -8.472 | -7.639 |
| 96 | MiniLM + Omneum | -6.775 | -5.404 | -2.708 | -1.181 |
| 96 | BGE + Omneum | 2.156 | 3.111 | 7.500 | 8.333 |
| 96 | Cohere + Omneum | -6.119 | -5.337 | -2.708 | -1.875 |
| 192 | BM25 + Omneum | -13.001 | -11.711 | -1.111 | 1.111 |
| 192 | MiniLM + Omneum | -21.177 | -13.980 | -14.583 | -7.917 |
| 192 | BGE + Omneum | -14.664 | -9.741 | -4.722 | -0.625 |
| 192 | Cohere + Omneum | -10.836 | -10.055 | -2.292 | -1.458 |
| 256 | BM25 + Omneum | -28.973 | -25.693 | -15.486 | -13.264 |
| 256 | MiniLM + Omneum | -33.930 | -23.124 | -22.361 | -12.639 |
| 256 | BGE + Omneum | -24.408 | -16.778 | -12.847 | -6.528 |
| 256 | Cohere + Omneum | -21.688 | -20.093 | -12.639 | -10.972 |

## coding_package_fix_lineage and residual exclusions


BGE + Omneum: selected chunk-pull_request, chunk-package_docs, chunk-issue_origin, chunk-issue_comment, chunk-release_notes. Evidence 21.875000% → 63.541667%; origins 20.000000% → 60.000000%; precision 33.333333% → 60.000000%; tokens 62 → 113.
Recovery floor 0.002197303603837179. All formerly excluded candidates are considered. The trace records exact marginal gains, proposal token counts and passes_recovery_floor decisions. Positive utility below the density boundary is not accepted; zero-weight or already represented cluster mass is not accepted. Remaining capacity is intentional, not a reason to weaken provenance-aware suppression.

Cohere + Omneum: selected chunk-pull_request, chunk-issue_origin, chunk-issue_comment, chunk-community_note, chunk-release_notes. Evidence 21.875000% → 40.625000%; origins 20.000000% → 40.000000%; precision 33.333333% → 40.000000%; tokens 62 → 102.
Recovery floor 0.0018310863365309828. All formerly excluded candidates are considered. The trace records exact marginal gains, proposal token counts and passes_recovery_floor decisions. Positive utility below the density boundary is not accepted; zero-weight or already represented cluster mass is not accepted. Remaining capacity is intentional, not a reason to weaken provenance-aware suppression.

## Case-level regressions and tradeoffs

The correction is append-only in selected passage identity after the initial neighborhood. Recall, evidence, claim and origin coverage never decrease against the old Omneum selection in any of the 720 case-budget cells. Precision and compression can regress; the complete case table is saved, and the largest precision losses are shown below. This is not a promise that every recovered passage is gold.

| Hybrid | Case | Δ precision pp | Δ evidence pp | Δ origins pp | Δ Qwen |
| --- | --- | --- | --- | --- | --- |
| BGE + Omneum | enterprise_semantic_distractors | -38.889 | 0.000 | 0.000 | 35.833 |
| Cohere + Omneum | enterprise_semantic_distractors | -38.889 | 0.000 | 0.000 | 35.833 |
| MiniLM + Omneum | enterprise_semantic_distractors | -27.778 | 0.000 | 0.000 | 21.667 |
| MiniLM + Omneum | analytics_derived_metric_cycle | -27.500 | 0.000 | 0.000 | 43.167 |
| Cohere + Omneum | analytics_derived_metric_cycle | -27.500 | 0.000 | 0.000 | 44.333 |
| BM25 + Omneum | analytics_stale_dashboard | -19.167 | 0.000 | 0.000 | 33.500 |
| BM25 + Omneum | multi_agent_relevant_wrong_task | -17.381 | 0.000 | 0.000 | 40.000 |
| BM25 + Omneum | coding_clean_dependency | -16.667 | 0.000 | 0.000 | 18.667 |
| BGE + Omneum | enterprise_stale_handbook | -16.667 | 0.000 | 0.000 | 20.000 |
| Cohere + Omneum | enterprise_stale_handbook | -16.667 | 0.000 | 0.000 | 20.000 |
| Cohere + Omneum | multi_agent_relevant_wrong_task | -16.667 | 0.000 | 0.000 | 26.000 |
| BM25 + Omneum | support_ticket_reference_loop | -13.810 | 0.000 | 0.000 | 29.333 |
| BGE + Omneum | analytics_stale_dashboard | -12.500 | 0.000 | 0.000 | 15.500 |
| Cohere + Omneum | analytics_stale_dashboard | -12.500 | 0.000 | 0.000 | 15.500 |
| MiniLM + Omneum | multi_agent_relevant_wrong_task | -9.841 | 0.000 | 0.000 | 22.500 |
| BGE + Omneum | multi_agent_relevant_wrong_task | -9.841 | 0.000 | 0.000 | 22.500 |
| BM25 + Omneum | enterprise_semantic_distractors | -8.333 | 0.000 | 0.000 | 24.000 |
| BGE + Omneum | support_ticket_reference_loop | -8.095 | 3.255 | 3.333 | 21.167 |
| MiniLM + Omneum | analytics_stale_dashboard | -6.667 | 0.000 | 0.000 | 10.333 |
| Cohere + Omneum | support_stale_runbook | -6.667 | 0.000 | 0.000 | 8.667 |

## Timing and validation


| Configuration | Original p50/p95 ms | Corrected p50/p95 ms | Corrected packing p50/p95 ms |
| --- | --- | --- | --- |
| Omneum standalone | 127.946/198.868 | 194.856/451.875 | 0.173/0.421 |
| BM25 + Omneum | 131.615/200.607 | 207.791/461.249 | 0.149/0.366 |
| MiniLM + Omneum | 131.484/194.249 | 203.840/465.363 | 0.149/0.336 |
| BGE + Omneum | 132.423/202.582 | 200.635/430.506 | 0.144/0.329 |
| Cohere + Omneum | 133.640/205.082 | 206.888/480.372 | 0.145/0.345 |

Final run: 720 corrected quality cells, five timing repeats each, 3,600 fresh production prepare_context executions plus five warmups. Every execution matches its native predicted selected passage IDs, exact rendered bytes and Qwen count; all full-graph support agrees with the frozen graph; no graph receipt reuse. Original 2,328 tokenized contexts were independently checked using the cached original Qwen2.5 tokenizer. Tests: 198 selection/API tests passed, including 16 recovery tests. No paid requests or downstream generations. API keys and hosted models are not used.

Historical and current wall-time distributions come from separate sessions; they cannot isolate recovery overhead. Standalone is algorithmically unchanged and serves as a warning about session-wide timing shifts. Packing-stage distributions expose the much smaller client selection work. Both sets exclude semantic ranking inference, structured extraction, startup/loading and cold tokenization. Existing remote provider latency remains historical and separate. Context efficiency remains better than each respective standalone baseline in aggregate, but weaker than the old restrictive hybrid; no claim of cost-free evidence recovery is made.

## Acceptance and remaining weaknesses


| Hybrid | Evidence gain pp | Origins gain pp | Precision advantage vs baseline pp | Qwen savings vs baseline % | Precision change vs old hybrid pp |
| --- | --- | --- | --- | --- | --- |
| BM25 + Omneum | 1.109 | 1.157 | 3.962 | 18.047 | -2.338 |
| MiniLM + Omneum | 5.005 | 4.745 | 3.023 | 18.509 | -0.470 |
| BGE + Omneum | 3.238 | 2.836 | 8.444 | 14.457 | -2.098 |
| Cohere + Omneum | 0.787 | 0.833 | 3.765 | 17.580 | -4.835 |

The discovery bug is corrected within an explicit quality-preserving marginal-density policy. All four hybrids improve completeness over their original versions across multiple cases/domains, while retaining aggregate precision and token-efficiency advantages over their respective standalone baselines. Precision is not preserved at its old absolute level; this is a quantified tradeoff, not full satisfaction of a zero-sacrifice objective. Standalone does not improve because it had no expanded-discovery exclusion to repair. Some evidence remains below the density boundary or has zero normalized relevance; not all high-budget gaps disappear, and all frontier judges remain stronger on aggregate evidence. Small bootstrap gains may span zero; consult intervals rather than equating nonnegative cell changes with a statistically established population gain.

Next steps: evaluate the same fixed policy on an unseen local held-out corpus; separately investigate whether ordinal zero is a justified abstention for strictly positive bounded scorer outputs; study singleton-vs-greedy budget allocation with a utility certificate; and test downstream answers while charging extraction and actual generation costs. Recovery searches the full retrieved pool and can increase greedy-packing work on much larger pools; the small synthetic pools do not establish large-pool latency. Do not tune density thresholds or inference weights to these 24 cases. No public README, leaderboard, domain Markdown report, or canonical artifact was modified.

## Reproduction

Runner: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -B -m benchmarks.context_selection.synthetic.experiments.budget_recovery --output NEW_EXPERIMENT --tokenizer ORIGINAL_QWEN_TOKENIZER`. The runner requires a protected_inputs.json and task-start source snapshots in the new directory, as documented by this experiment. It refuses to overwrite completed selections. Analyze: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -B -m benchmarks.context_selection.synthetic.experiments.analyze_budget_recovery --output benchmarks/context_selection/synthetic/results/budget-exhaustion-recovery-20261026-v2`. The first command runs only local native/SDK inference; the second reads saved results. Production-change.patch is relative to task-start files, excluding unrelated pre-existing working-tree changes.
