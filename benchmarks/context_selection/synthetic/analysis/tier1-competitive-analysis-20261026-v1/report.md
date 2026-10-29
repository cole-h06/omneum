# Tier 1 competitive analysis — frozen 2026-10-25 results

Evidence-ranked leaderboard and paired analysis; generated from saved artifacts only. No benchmark reruns, inference, network calls, or production changes.

## Main conclusion

The saved benchmark does not support a blanket claim that Omneum improves established rerankers. Hybrids generally increase precision and reduce context size, but every hybrid loses aggregate source recall and evidence retention. BGE + Omneum has small positive aggregate claim/origin changes whose case-bootstrap intervals include zero. Standalone Omneum improves several metrics over original-order RAG and is competitive on claim/origin coverage against traditional selectors, but loses evidence retention to BM25, MiniLM, BGE, Cohere and all frontier judges. All frontier judges exceed every Omneum configuration on the five aggregate quality metrics. These are selection results conditional on enriched, supplied structured observations.

## Validation and configuration inventory

| Requested configuration | Saved arm | Status |
| --- | --- | --- |
| Standard RAG | raw_budget | Present: original input order plus first-fit packing; no new retrieval run |
| BM25 | bm25 | Present: frozen complete-pool scores |
| MiniLM embeddings | embedding | Present: all-MiniLM-L6-v2 bi-encoder |
| BGE embeddings | — | Missing; BGE reranker is not an embedding substitute |
| MiniLM Cross-Encoder | — | Missing |
| BGE Reranker v2-m3 | bge | Present: BAAI/bge-reranker-v2-m3 cross-encoder |
| Cohere Rerank v4.0 Pro | cohere | Present: rerank-v4.0-pro |
| Claude Sonnet 5.5 | claude | Present: two saved ranking trials/case |
| GPT-6 Astra | gpt | Present: two saved ranking trials/case |
| Gemini 3.8 Flash | gemini | Present: two saved ranking trials/case |
| Omneum standalone | omneum | Present: production prepare_context |
| BM25 + Omneum | bm25_omneum | Present: production prepare_context |
| MiniLM + Omneum | embedding_omneum | Present: production prepare_context |
| BGE Reranker + Omneum | bge_omneum | Present: production prepare_context |
| Cohere + Omneum | cohere_omneum | Present: production prepare_context |
| Additional reference | raw_full | Unbudgeted; excluded from competitive ranks |

13 of the requested 15 configurations are present, plus one unbudgeted reference. “BGE + Omneum” means BGE reranker + Omneum. The case.json context_budget field is a legacy passage-count field; the actual Tier 1 budgets are the six token ceilings in the manifests.

Recomputed all 2,328 selection records with the existing tier1_metrics.measure function and canonical ground truth; every metric matches. All aggregate and per-budget quality means and local timing percentiles reproduce the primary summary. Verified 11,640 timing records, five timing repeats per quality record, complete factorial coverage, canonical selected passage text, candidate membership, saved frontier/Cohere ranking pools, and exact preservation of the 864 original production selections. See audit.json for input hashes and historical source hash checks.

Pool and annotation identity holds at the full input level. Selector eligibility is not identical: hybrid candidate discovery/expansion may shortlist or exclude chunks. Rankers use whole-passage first-fit; Omneum uses its production graph-aware packing/discovery. Thus this compares complete selection systems under the same ceilings, not the same packing algorithm. Structured Omneum input includes supplied claims, timestamps, provenance links and evidence metadata; text rankers/judges see question and passages. Gold supporting-source labels are used only for evaluation. Equal passage pools do not establish equal information access or account for extraction/annotation cost.

Hybrids use coverage_support_density, complementary_evidence=True, token_cost_exponent=1, expanded candidate discovery with candidate_count=3 (plus score ties), expansion_depth=2 and full query evaluation. BGE uses reranker_score relevance semantics; BM25/MiniLM use similarity, and the saved Cohere hybrid also passes similarity. Standalone uses question=... on the full graph with default lexical passage relevance. All use conflict_aware=False. These exact configurations, rather than a generic Omneum algorithm, are the experimental treatments.

Recorded Qwen2.5 7B tokenizer counts satisfy every budget. No tokenizer or daemon was started; this audit did not independently retokenize or re-execute skipped packing proposals. Historical validation records describe exhaustive warmed tokenizer counts and execution equality. Source hashes in audit.json distinguish saved implementation provenance from the present working tree.

Of 130 historical source-path hash checks, 124 match after resolving the repository directory rename. Five current files differ and omneum/demo.py is absent (details in audit.json). These working-tree differences do not change the frozen metrics, but the current tree should not be presented as byte-identical to the recorded execution. The analysis performs no inference with the changed files.

## Metric and statistical definitions

- Precision/recall: selected source IDs against all annotated supporting sources; an empty selection has precision zero.
- Evidence retention: retained gold passage evidence-span word/punctuation footprint divided by all gold evidence footprint, after overlapping spans are merged. This weights evidence length.
- Claims: union of canonical claim IDs present in selected passages intersected with the union in gold passages. Claims in non-gold passages can earn this coverage; incidental facts are included. This is not minimal answer completeness or strict gold-claim coverage.
- Origins: annotated root-origin units represented by retained gold passages divided by those represented by all gold passages. Root cycles count as one unresolved origin unit; absent edges do not prove real independence.
- Actual context tokens: regex word/punctuation footprint, including chunk headers. This is not the Qwen tokenizer count. Reduction uses the same footprint on raw and retained context.
- Macro estimator: mean of trials within each case-budget cell, then equal mean across six budgets and 24 cases. Four cases per domain makes equal-domain and equal-case means identical. Raw full is averaged over 24 cases only.
- Paired differences compare identical case-budget cells. Bootstrap: 50,000 paired whole-case resamples (seed 20261026), retaining budgets and both judge trials, percentile 95% intervals. A domain-stratified sensitivity resamples four cases within each domain. No multiplicity correction or population-representativeness claim; intervals are descriptive, not confirmatory significance tests. Timing repeats never increase the 24-case sample size.

## Complete leaderboard

Ranked by evidence retention, with no invented composite score. All quality columns are percentages. Footprint and Qwen columns are mean counts. Per-metric ranks are in metric_rankings.csv.

| Rank | Configuration | Precision | Recall | Evidence | Claims | Origins | Footprint | Reduction | Qwen |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | Claude Sonnet 5.5 | 85.694 | 75.848 | 76.491 | 81.051 | 82.894 | 114.118 | 47.061 | 136.406 |
| 2 | GPT-6 Astra | 85.137 | 75.327 | 76.181 | 81.477 | 83.501 | 114.299 | 46.993 | 136.493 |
| 3 | Gemini 3.8 Flash | 83.806 | 74.807 | 75.330 | 80.117 | 81.273 | 114.198 | 47.020 | 136.524 |
| 4 | Cohere Rerank v4.0 Pro | 71.112 | 64.430 | 64.390 | 72.293 | 75.197 | 112.993 | 47.478 | 136.715 |
| 5 | MiniLM embeddings | 63.803 | 59.129 | 58.860 | 68.470 | 70.937 | 113.021 | 47.529 | 136.306 |
| 6 | BGE Reranker v2-m3 | 63.292 | 59.193 | 58.845 | 68.752 | 71.424 | 112.847 | 47.585 | 136.472 |
| 7 | BM25 | 59.153 | 55.761 | 55.792 | 66.147 | 71.053 | 114.188 | 46.965 | 136.181 |
| 8 | Cohere + Omneum | 79.712 | 54.077 | 55.416 | 71.452 | 72.025 | 85.479 | 60.592 | 104.222 |
| 9 | Omneum standalone | 61.549 | 52.647 | 53.425 | 75.853 | 75.521 | 108.701 | 49.347 | 129.271 |
| 10 | BGE Reranker + Omneum | 73.834 | 51.354 | 52.018 | 70.464 | 72.373 | 87.167 | 59.526 | 106.625 |
| 11 | BM25 + Omneum | 65.453 | 45.579 | 45.789 | 64.028 | 67.998 | 86.389 | 60.105 | 103.757 |
| 12 | MiniLM + Omneum | 67.295 | 44.053 | 45.136 | 61.844 | 63.750 | 80.153 | 62.998 | 98.729 |
| 13 | Standard RAG (original-order first-fit) | 43.328 | 42.750 | 43.078 | 58.506 | 60.324 | 113.583 | 47.262 | 136.868 |

Unbudgeted raw full: precision 55.759%; recall/evidence/claims/origins 100%; footprint 218.417; Qwen 262.417. Its complete retention is not a fair budgeted win.

| Metric | Strongest Omneum arm | Value |
| --- | --- | --- |
| Precision | Cohere + Omneum | 79.712 |
| Recall | Cohere + Omneum | 54.077 |
| Evidence | Cohere + Omneum | 55.416 |
| Claims | Omneum standalone | 75.853 |
| Origins | Omneum standalone | 75.521 |
| Reduction | MiniLM + Omneum | 62.998 |

Reduction alone rewards discarding context; it is not an evidence-quality win. MiniLM + Omneum has the smallest mean context footprint and Qwen usage among Omneum arms.

## Five strongest quantitative findings

1. **Largest hybrid precision improvement:** BGE → BGE + Omneum: 63.291722% → 73.834325%; Δ +10.542604 pp (+16.657160% relative); 95% CI [+3.980345, +17.488853] pp. It improves precision in 17 cases, ties in 3, and loses in 4. Evidence nevertheless changes: 58.844598% → 52.018170%; Δ -6.826428 pp (-11.600772% relative); 95% CI [-13.214937, -0.370412] pp.
2. **Standalone beats original-order RAG:** evidence: 43.078186% → 53.424915%; Δ +10.346729 pp (+24.018487% relative); 95% CI [+2.672676, +18.282122] pp; claims: 58.505750% → 75.853200%; Δ +17.347450 pp (+29.650846% relative); 95% CI [+8.748394, +25.862350] pp; origins: 60.324074% → 75.520833%; Δ +15.196759 pp (+25.191865% relative); 95% CI [+6.192130, +24.143519] pp. This is original-order packing, not a semantic reranker.
3. **Tight-budget BGE gains reverse:** budget 64, Evidence Δ +6.254021 pp, 95% CI [+0.922179, +12.640551] pp; budget 64, Origins Δ +13.194444 pp, 95% CI [+2.777778, +25.000000] pp; budget 256, Evidence Δ -24.408057 pp, 95% CI [-33.299843, -15.748313] pp; budget 256, Origins Δ -12.847222 pp, 95% CI [-22.152778, -5.000000] pp. Budget slices are exploratory.
4. **Compression has a completeness cost:** MiniLM → MiniLM + Omneum: Qwen tokens 136.305556 → 98.729167 (-27.567760%); Context footprint 113.020833 → 80.152778 (-29.081413%); evidence: 58.860158% → 45.136084%; Δ -13.724073 pp (-23.316406% relative); 95% CI [-20.210739, -7.345902] pp; origins: 70.937500% → 63.750000%; Δ -7.187500 pp (-10.132159% relative); 95% CI [-14.074363, -0.752315] pp.
5. **Frontier lead persists against the best Omneum evidence arm:** Claude Sonnet 5.5 → Cohere + Omneum evidence: 76.491000% → 55.415564%; Δ -21.075436 pp (-27.552831% relative); 95% CI [-27.446042, -15.513347] pp; GPT-6 Astra → Cohere + Omneum evidence: 76.180854% → 55.415564%; Δ -20.765290 pp (-27.257886% relative); 95% CI [-26.798463, -15.429216] pp; Gemini 3.8 Flash → Cohere + Omneum evidence: 75.329901% → 55.415564%; Δ -19.914337 pp (-26.436166% relative); 95% CI [-25.740464, -14.723986] pp. All three judges also exceed every Omneum arm on aggregate precision, recall, claim coverage and origin coverage.

Exact machine-readable values are authoritative; the assertions and tables below are generated from full precision. Narrative quantities are rounded displays, not additional estimates.

## Paired baseline → hybrid changes

Deltas and confidence intervals are percentage points. Relative changes use (hybrid mean / baseline mean − 1); full results and both bootstrap schemes are in paired_comparisons.csv.

| Pair | Metric | Baseline % | Hybrid % | Δ pp | Relative % | 95% CI pp | Case W/T/L |
| --- | --- | --- | --- | --- | --- | --- | --- |
| BM25 → BM25 + Omneum | Precision | 59.153 | 65.453 | 6.300 | 10.650 | [0.345, 12.364] | 14/2/8 |
| BM25 → BM25 + Omneum | Recall | 55.761 | 45.579 | -10.182 | -18.260 | [-15.972, -4.673] | 4/2/18 |
| BM25 → BM25 + Omneum | Evidence | 55.792 | 45.789 | -10.003 | -17.929 | [-15.664, -4.516] | 5/0/19 |
| BM25 → BM25 + Omneum | Claims | 66.147 | 64.028 | -2.118 | -3.203 | [-8.979, 4.011] | 12/3/9 |
| BM25 → BM25 + Omneum | Origins | 71.053 | 67.998 | -3.056 | -4.300 | [-10.694, 3.970] | 7/7/10 |
| MiniLM embeddings → MiniLM + Omneum | Precision | 63.803 | 67.295 | 3.492 | 5.474 | [-3.111, 10.578] | 12/2/10 |
| MiniLM embeddings → MiniLM + Omneum | Recall | 59.129 | 44.053 | -15.076 | -25.497 | [-21.678, -8.652] | 2/2/20 |
| MiniLM embeddings → MiniLM + Omneum | Evidence | 58.860 | 45.136 | -13.724 | -23.316 | [-20.211, -7.346] | 3/2/19 |
| MiniLM embeddings → MiniLM + Omneum | Claims | 68.470 | 61.844 | -6.626 | -9.678 | [-14.479, 0.250] | 6/8/10 |
| MiniLM embeddings → MiniLM + Omneum | Origins | 70.937 | 63.750 | -7.188 | -10.132 | [-14.074, -0.752] | 5/7/12 |
| BGE Reranker v2-m3 → BGE Reranker + Omneum | Precision | 63.292 | 73.834 | 10.543 | 16.657 | [3.980, 17.489] | 17/3/4 |
| BGE Reranker v2-m3 → BGE Reranker + Omneum | Recall | 59.193 | 51.354 | -7.839 | -13.243 | [-14.311, -1.452] | 5/4/15 |
| BGE Reranker v2-m3 → BGE Reranker + Omneum | Evidence | 58.845 | 52.018 | -6.826 | -11.601 | [-13.215, -0.370] | 6/1/17 |
| BGE Reranker v2-m3 → BGE Reranker + Omneum | Claims | 68.752 | 70.464 | 1.713 | 2.491 | [-6.671, 9.253] | 13/5/6 |
| BGE Reranker v2-m3 → BGE Reranker + Omneum | Origins | 71.424 | 72.373 | 0.949 | 1.329 | [-5.949, 7.407] | 9/9/6 |
| Cohere Rerank v4.0 Pro → Cohere + Omneum | Precision | 71.112 | 79.712 | 8.600 | 12.093 | [1.613, 15.259] | 16/2/6 |
| Cohere Rerank v4.0 Pro → Cohere + Omneum | Recall | 64.430 | 54.077 | -10.352 | -16.067 | [-16.498, -4.628] | 4/6/14 |
| Cohere Rerank v4.0 Pro → Cohere + Omneum | Evidence | 64.390 | 55.416 | -8.975 | -13.938 | [-15.045, -3.371] | 7/3/14 |
| Cohere Rerank v4.0 Pro → Cohere + Omneum | Claims | 72.293 | 71.452 | -0.840 | -1.162 | [-8.328, 5.141] | 13/7/4 |
| Cohere Rerank v4.0 Pro → Cohere + Omneum | Origins | 75.197 | 72.025 | -3.171 | -4.217 | [-9.433, 2.118] | 5/12/7 |

| Pair | Δ footprint | Δ Qwen tokens | Footprint relative % | Δ reduction pp |
| --- | --- | --- | --- | --- |
| BM25 → hybrid | -27.799 | -32.424 | -24.345 | 13.140 |
| MiniLM embeddings → hybrid | -32.868 | -37.576 | -29.081 | 15.470 |
| BGE Reranker v2-m3 → hybrid | -25.681 | -29.847 | -22.757 | 11.941 |
| Cohere Rerank v4.0 Pro → hybrid | -27.514 | -32.493 | -24.350 | 13.114 |

## Frontier judges versus every Omneum arm

Each entry is Omneum minus judge, in percentage points; both judge trials are averaged before pairing. Every aggregate quality delta below is negative. Detailed case-bootstrap intervals for every entry are in paired_comparisons.csv.

| Judge | Omneum arm | Δ precision | Δ recall | Δ evidence | Δ claims | Δ origins | Evidence 95% CI |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Claude Sonnet 5.5 | Omneum standalone | -24.145 | -23.201 | -23.066 | -5.198 | -7.373 | [-28.702, -17.680] |
| Claude Sonnet 5.5 | BM25 + Omneum | -20.241 | -30.270 | -30.702 | -17.022 | -14.896 | [-38.579, -23.914] |
| Claude Sonnet 5.5 | MiniLM + Omneum | -18.399 | -31.796 | -31.355 | -19.207 | -19.144 | [-39.387, -23.838] |
| Claude Sonnet 5.5 | BGE Reranker + Omneum | -11.860 | -24.494 | -24.473 | -10.587 | -10.521 | [-29.959, -19.477] |
| Claude Sonnet 5.5 | Cohere + Omneum | -5.982 | -21.771 | -21.075 | -9.598 | -10.868 | [-27.446, -15.513] |
| GPT-6 Astra | Omneum standalone | -23.588 | -22.680 | -22.756 | -5.624 | -7.980 | [-28.428, -17.331] |
| GPT-6 Astra | BM25 + Omneum | -19.684 | -29.749 | -30.392 | -17.449 | -15.503 | [-38.260, -23.627] |
| GPT-6 Astra | MiniLM + Omneum | -17.842 | -31.275 | -31.045 | -19.633 | -19.751 | [-39.060, -23.570] |
| GPT-6 Astra | BGE Reranker + Omneum | -11.303 | -23.973 | -24.163 | -11.013 | -11.128 | [-29.554, -19.259] |
| GPT-6 Astra | Cohere + Omneum | -5.425 | -21.250 | -20.765 | -10.025 | -11.476 | [-26.798, -15.429] |
| Gemini 3.8 Flash | Omneum standalone | -22.257 | -22.159 | -21.905 | -4.264 | -5.752 | [-27.699, -16.436] |
| Gemini 3.8 Flash | BM25 + Omneum | -18.353 | -29.228 | -29.541 | -16.089 | -13.275 | [-37.469, -22.887] |
| Gemini 3.8 Flash | MiniLM + Omneum | -16.511 | -30.754 | -30.194 | -18.273 | -17.523 | [-38.201, -22.704] |
| Gemini 3.8 Flash | BGE Reranker + Omneum | -9.972 | -23.452 | -23.312 | -9.653 | -8.900 | [-28.696, -18.447] |
| Gemini 3.8 Flash | Cohere + Omneum | -4.094 | -20.729 | -19.914 | -8.665 | -9.248 | [-25.740, -14.724] |

## Standalone Omneum versus standalone selectors


| Baseline | Δ precision | Δ recall | Δ evidence | Δ claims | Δ origins |
| --- | --- | --- | --- | --- | --- |
| Standard RAG (original-order first-fit) | 18.221 | 9.897 | 10.347 | 17.347 | 15.197 |
| BM25 | 2.396 | -3.113 | -2.367 | 9.706 | 4.468 |
| MiniLM embeddings | -2.253 | -6.481 | -5.435 | 7.383 | 4.583 |
| BGE Reranker v2-m3 | -1.742 | -6.546 | -5.420 | 7.102 | 4.097 |
| Cohere Rerank v4.0 Pro | -9.563 | -11.782 | -10.965 | 3.560 | 0.324 |
| Claude Sonnet 5.5 | -24.145 | -23.201 | -23.066 | -5.198 | -7.373 |
| GPT-6 Astra | -23.588 | -22.680 | -22.756 | -5.624 | -7.980 |
| Gemini 3.8 Flash | -22.257 | -22.159 | -21.905 | -4.264 | -5.752 |

## Domain findings

Each domain has four cases. Entries are paired hybrid-minus-baseline percentage points, averaged over six budgets. Domain comparisons are exploratory and have very small case counts; do not infer causal effects of dependency type.

| Domain | Pair | Δ precision | Δ evidence | Δ claims | Δ origins |
| --- | --- | --- | --- | --- | --- |
| coding_agents | BM25 | -3.681 | -25.297 | -27.551 | -27.292 |
| coding_agents | MiniLM embeddings | -2.778 | -21.229 | -25.417 | -16.528 |
| coding_agents | BGE Reranker v2-m3 | -0.417 | -17.562 | -22.828 | -17.222 |
| coding_agents | Cohere Rerank v4.0 Pro | 5.903 | -10.711 | -16.048 | -13.750 |
| data_analytics_agents | BM25 | 6.880 | -9.386 | 4.896 | -4.167 |
| data_analytics_agents | MiniLM embeddings | 4.826 | -6.176 | 5.764 | -3.472 |
| data_analytics_agents | BGE Reranker v2-m3 | 4.211 | -6.637 | 7.222 | 2.083 |
| data_analytics_agents | Cohere Rerank v4.0 Pro | 3.239 | -8.129 | 4.236 | -3.472 |
| enterprise_rag | BM25 | 17.077 | -12.915 | 1.667 | 0.000 |
| enterprise_rag | MiniLM embeddings | 13.872 | -24.237 | 0.833 | 4.167 |
| enterprise_rag | BGE Reranker v2-m3 | 25.470 | -18.174 | 8.333 | 2.083 |
| enterprise_rag | Cohere Rerank v4.0 Pro | 26.372 | -19.003 | 6.667 | 6.250 |
| multi_agent_systems | BM25 | 12.097 | 4.662 | 9.583 | 9.028 |
| multi_agent_systems | MiniLM embeddings | 2.692 | -7.791 | -5.000 | -13.889 |
| multi_agent_systems | BGE Reranker v2-m3 | 21.581 | 12.600 | 19.167 | 20.139 |
| multi_agent_systems | Cohere Rerank v4.0 Pro | 13.684 | 2.524 | 6.250 | 2.778 |
| research_analysis_agents | BM25 | 3.264 | -7.542 | 0.903 | 12.500 |
| research_analysis_agents | MiniLM embeddings | 9.107 | 0.626 | 5.556 | 6.597 |
| research_analysis_agents | BGE Reranker v2-m3 | 9.732 | -1.839 | 2.083 | 3.472 |
| research_analysis_agents | Cohere Rerank v4.0 Pro | 2.778 | -4.045 | 1.667 | 1.042 |
| support_operations_agents | BM25 | 2.163 | -9.539 | -2.209 | -8.403 |
| support_operations_agents | MiniLM embeddings | -6.766 | -23.538 | -21.493 | -20.000 |
| support_operations_agents | BGE Reranker v2-m3 | 2.679 | -9.346 | -3.702 | -4.861 |
| support_operations_agents | Cohere Rerank v4.0 Pro | -0.377 | -14.483 | -7.814 | -11.875 |

## Budget findings


| Budget | Pair | Δ precision | Δ evidence | Δ claims | Δ origins |
| --- | --- | --- | --- | --- | --- |
| 64 | BM25 | 14.583 | 2.091 | 13.144 | 5.208 |
| 64 | MiniLM embeddings | 4.167 | -0.942 | 3.922 | -1.389 |
| 64 | BGE Reranker v2-m3 | 20.833 | 6.254 | 13.922 | 13.194 |
| 64 | Cohere Rerank v4.0 Pro | 10.417 | -0.270 | 8.127 | 2.431 |
| 96 | BM25 | -2.778 | -5.790 | 2.063 | -8.472 |
| 96 | MiniLM embeddings | -4.861 | -6.775 | 2.862 | -2.708 |
| 96 | BGE Reranker v2-m3 | 9.722 | 2.156 | 10.885 | 7.500 |
| 96 | Cohere Rerank v4.0 Pro | -2.083 | -6.119 | 0.934 | -2.708 |
| 128 | BM25 | 0.694 | -5.132 | 0.764 | 5.625 |
| 128 | MiniLM embeddings | 2.431 | -9.517 | 0.361 | -0.972 |
| 128 | BGE Reranker v2-m3 | 3.819 | -2.798 | 5.130 | 2.153 |
| 128 | Cohere Rerank v4.0 Pro | 5.208 | -4.565 | 0.502 | 0.764 |
| 160 | BM25 | 5.605 | -9.213 | -2.773 | -4.097 |
| 160 | MiniLM embeddings | 6.647 | -10.004 | -5.096 | -1.111 |
| 160 | BGE Reranker v2-m3 | 6.161 | -7.498 | 1.251 | 0.417 |
| 160 | Cohere Rerank v4.0 Pro | 6.786 | -10.371 | -0.111 | -4.583 |
| 192 | BM25 | 10.045 | -13.001 | -6.224 | -1.111 |
| 192 | MiniLM embeddings | 4.509 | -21.177 | -14.836 | -14.583 |
| 192 | BGE Reranker v2-m3 | 9.023 | -14.664 | -6.419 | -4.722 |
| 192 | Cohere Rerank v4.0 Pro | 13.467 | -10.836 | -1.947 | -2.292 |
| 256 | BM25 | 9.649 | -28.973 | -19.685 | -15.486 |
| 256 | MiniLM embeddings | 8.062 | -33.930 | -26.971 | -22.361 |
| 256 | BGE Reranker v2-m3 | 13.697 | -24.408 | -14.493 | -12.847 |
| 256 | Cohere Rerank v4.0 Pro | 17.804 | -21.688 | -12.547 | -12.639 |

Complete metric levels for all 13 configurations by domain, budget, and individual case are in by_domain.csv, by_budget.csv, and by_case.csv. paired_domain_budget_deltas.csv covers all 40 specified baseline/Omneum comparisons, not just hybrids.

BGE hybrid evidence changes by domain: coding_agents: -17.561739 pp; data_analytics_agents: -6.637496 pp; enterprise_rag: -18.173862 pp; multi_agent_systems: +12.600329 pp; research_analysis_agents: -1.839344 pp; support_operations_agents: -9.346454 pp. Its origin changes are positive in four domains and negative in coding (−17.222 pp) and support (−4.861 pp). This is not a domain-uniform improvement. BGE hybrid precision improves at all six budgets; its evidence improves only at 64 and 96. BM25, MiniLM and Cohere hybrid precision each regresses at 96 tokens. At 256 tokens all four hybrids lose evidence, claims and origin coverage. No hybrid demonstrates all-metric gains that persist across every domain and budget.

## Individual cases, regressions and ties


BM25 → hybrid: case-average deltas across all six budgets (pp).

| Case | Δ precision | Δ evidence | Δ claims | Δ origins |
| --- | --- | --- | --- | --- |
| analytics_derived_metric_cycle | 12.917 | -22.678 | 8.333 | -8.333 |
| analytics_incomplete_lineage | 4.167 | -6.734 | 8.333 | 0.000 |
| analytics_metric_definition_conflict | -7.540 | -5.485 | -10.417 | -8.333 |
| analytics_stale_dashboard | 17.976 | -2.648 | 13.333 | 0.000 |
| coding_api_version_change | 2.143 | -7.350 | -9.091 | -0.000 |
| coding_clean_dependency | 15.437 | -14.935 | -13.889 | -12.500 |
| coding_config_conflict | -13.056 | -34.286 | -38.889 | -50.000 |
| coding_package_fix_lineage | -19.246 | -44.618 | -48.333 | -46.667 |
| enterprise_partial_lineage | 25.913 | -0.165 | 6.667 | 0.000 |
| enterprise_policy_copy_chain | 43.472 | -22.511 | 0.000 | 0.000 |
| enterprise_semantic_distractors | 4.894 | -11.047 | 0.000 | 0.000 |
| enterprise_stale_handbook | -5.972 | -17.938 | -0.000 | 0.000 |
| multi_agent_feedback_loop | 16.667 | 4.701 | 6.667 | 11.111 |
| multi_agent_independent_error | -3.056 | -12.360 | -6.667 | -11.111 |
| multi_agent_relevant_wrong_task | 15.608 | 1.932 | 8.333 | 11.111 |
| multi_agent_repeated_subagent | 19.167 | 24.375 | 30.000 | 25.000 |
| research_clean_consensus | 0.000 | -12.267 | 6.667 | 8.333 |
| research_conflicting_reports | -16.944 | -15.517 | 4.167 | 16.667 |
| research_independent_false_consensus | 7.857 | -3.077 | 6.667 | -8.333 |
| research_syndicated_reporting | 22.143 | 0.694 | -13.889 | 33.333 |
| support_clean_resolution | 0.000 | -5.736 | 6.410 | -2.778 |
| support_resolution_conflict | -7.024 | -22.549 | -6.250 | -20.833 |
| support_stale_runbook | -7.857 | -16.903 | -18.519 | -16.667 |
| support_ticket_reference_loop | 23.532 | 7.031 | 9.524 | 6.667 |

MiniLM embeddings → hybrid: case-average deltas across all six budgets (pp).

| Case | Δ precision | Δ evidence | Δ claims | Δ origins |
| --- | --- | --- | --- | --- |
| analytics_derived_metric_cycle | 29.583 | -3.552 | 4.167 | -8.333 |
| analytics_incomplete_lineage | -15.833 | -14.141 | 5.556 | -5.556 |
| analytics_metric_definition_conflict | 0.794 | 0.000 | 0.000 | 0.000 |
| analytics_stale_dashboard | 4.762 | -7.009 | 13.333 | 0.000 |
| coding_api_version_change | -1.190 | -8.799 | -16.667 | -11.111 |
| coding_clean_dependency | 5.714 | -22.078 | -19.444 | -8.333 |
| coding_config_conflict | 3.611 | -7.857 | -5.556 | 0.000 |
| coding_package_fix_lineage | -19.246 | -46.181 | -60.000 | -46.667 |
| enterprise_partial_lineage | 5.754 | 0.330 | 6.667 | 8.333 |
| enterprise_policy_copy_chain | 37.917 | -45.455 | 0.000 | 0.000 |
| enterprise_semantic_distractors | 19.735 | -31.202 | 0.000 | 8.333 |
| enterprise_stale_handbook | -7.917 | -20.621 | -3.333 | 0.000 |
| multi_agent_feedback_loop | -20.357 | -20.513 | -36.667 | -38.889 |
| multi_agent_independent_error | 16.389 | 0.000 | 0.000 | 0.000 |
| multi_agent_relevant_wrong_task | 20.291 | 4.348 | 16.667 | 16.667 |
| multi_agent_repeated_subagent | -5.556 | -15.000 | 0.000 | -33.333 |
| research_clean_consensus | 0.000 | -13.467 | 0.000 | -4.167 |
| research_conflicting_reports | -8.333 | -6.753 | 0.000 | 5.556 |
| research_independent_false_consensus | -0.476 | -4.359 | 0.000 | 0.000 |
| research_syndicated_reporting | 45.238 | 27.083 | 22.222 | 25.000 |
| support_clean_resolution | 0.000 | -36.905 | -39.744 | -27.778 |
| support_resolution_conflict | 5.476 | -17.974 | -4.167 | -16.667 |
| support_stale_runbook | -18.968 | -26.123 | -27.778 | -22.222 |
| support_ticket_reference_loop | -13.571 | -13.151 | -14.286 | -13.333 |

BGE Reranker v2-m3 → hybrid: case-average deltas across all six budgets (pp).

| Case | Δ precision | Δ evidence | Δ claims | Δ origins |
| --- | --- | --- | --- | --- |
| analytics_derived_metric_cycle | 0.972 | -9.016 | 8.333 | 8.333 |
| analytics_incomplete_lineage | 11.111 | -1.178 | 13.889 | 0.000 |
| analytics_metric_definition_conflict | 0.000 | 0.000 | 0.000 | 0.000 |
| analytics_stale_dashboard | 4.762 | -16.355 | 6.667 | 0.000 |
| coding_api_version_change | -5.635 | -15.321 | -25.758 | -22.222 |
| coding_clean_dependency | 2.381 | -17.208 | -16.667 | -16.667 |
| coding_config_conflict | 20.833 | 8.810 | 11.111 | 16.667 |
| coding_package_fix_lineage | -19.246 | -46.528 | -60.000 | -46.667 |
| enterprise_partial_lineage | 16.032 | -10.561 | 3.333 | -8.333 |
| enterprise_policy_copy_chain | 43.472 | -22.511 | 0.000 | 0.000 |
| enterprise_semantic_distractors | 19.735 | -31.008 | 0.000 | 16.667 |
| enterprise_stale_handbook | 22.639 | -8.616 | 30.000 | 0.000 |
| multi_agent_feedback_loop | 21.865 | 13.675 | 13.333 | 22.222 |
| multi_agent_independent_error | -8.333 | -2.622 | 0.000 | 0.000 |
| multi_agent_relevant_wrong_task | 20.291 | 4.348 | 16.667 | 16.667 |
| multi_agent_repeated_subagent | 52.500 | 35.000 | 46.667 | 41.667 |
| research_clean_consensus | 0.000 | -14.400 | 3.333 | 0.000 |
| research_conflicting_reports | 2.222 | -3.305 | 0.000 | 5.556 |
| research_independent_false_consensus | 1.190 | -6.667 | -3.333 | 0.000 |
| research_syndicated_reporting | 35.516 | 17.014 | 8.333 | 8.333 |
| support_clean_resolution | 0.000 | -6.602 | 15.385 | 8.333 |
| support_resolution_conflict | 1.310 | -15.359 | -14.583 | -16.667 |
| support_stale_runbook | -11.190 | -16.076 | -20.370 | -11.111 |
| support_ticket_reference_loop | 20.595 | 0.651 | 4.762 | 0.000 |

Cohere Rerank v4.0 Pro → hybrid: case-average deltas across all six budgets (pp).

| Case | Δ precision | Δ evidence | Δ claims | Δ origins |
| --- | --- | --- | --- | --- |
| analytics_derived_metric_cycle | 29.583 | -3.552 | 4.167 | -8.333 |
| analytics_incomplete_lineage | -20.833 | -14.478 | 2.778 | -5.556 |
| analytics_metric_definition_conflict | -0.556 | 0.000 | 0.000 | 0.000 |
| analytics_stale_dashboard | 4.762 | -14.486 | 10.000 | 0.000 |
| coding_api_version_change | 14.643 | 8.075 | 3.030 | 0.000 |
| coding_clean_dependency | 2.381 | -21.753 | -22.222 | -25.000 |
| coding_config_conflict | 25.833 | 16.667 | 16.667 | 16.667 |
| coding_package_fix_lineage | -19.246 | -45.833 | -61.667 | -46.667 |
| enterprise_partial_lineage | 22.976 | -10.066 | 3.333 | 8.333 |
| enterprise_policy_copy_chain | 43.472 | -22.511 | 0.000 | 0.000 |
| enterprise_semantic_distractors | 19.735 | -31.008 | 0.000 | 16.667 |
| enterprise_stale_handbook | 19.306 | -12.429 | 23.333 | 0.000 |
| multi_agent_feedback_loop | 11.111 | 5.271 | 10.000 | 11.111 |
| multi_agent_independent_error | 16.389 | 0.000 | 0.000 | 0.000 |
| multi_agent_relevant_wrong_task | 21.958 | 0.242 | 8.333 | 0.000 |
| multi_agent_repeated_subagent | 5.278 | 4.583 | 6.667 | 0.000 |
| research_clean_consensus | 0.000 | -13.467 | 0.000 | -4.167 |
| research_conflicting_reports | -6.111 | -7.328 | 0.000 | 0.000 |
| research_independent_false_consensus | 10.913 | 4.615 | 6.667 | 8.333 |
| research_syndicated_reporting | 6.310 | 0.000 | 0.000 | 0.000 |
| support_clean_resolution | 0.000 | -13.745 | 6.410 | -0.000 |
| support_resolution_conflict | -30.635 | -37.908 | -35.417 | -37.500 |
| support_stale_runbook | 31.032 | 2.837 | 3.704 | 0.000 |
| support_ticket_reference_loop | -1.905 | -9.115 | -5.952 | -10.000 |

Every case-budget delta, including ties, remains available in paired_case_budget_deltas.csv; trial_level_metrics.csv preserves both judge trials. A positive precision change with negative evidence/recall means cleaner but less complete selection, not more retained evidence. Origin coverage is not interchangeable with claim coverage or amount of evidence.

The largest recurring evidence regression is coding_package_fix_lineage: case-average loss **44.618 pp** for BM25, **46.181 pp** for MiniLM, **46.528 pp** for BGE, and **45.833 pp** for Cohere hybrids. At budget 256, both BGE and Cohere baselines retain all eight passages using 176 Qwen tokens; their hybrids retain only issue_origin, issue_comment, and release_notes using 62 tokens. Five chunks, including repository_code and test_output, are explicitly excluded as outside_expansion. This directly documents a shortlist-induced completeness ceiling even when the full pool fits the budget; it does not isolate every contribution of graph scoring versus discovery.

| Arm | Cells with exclusions / 144 | Mean eligible passages | Mean excluded passages |
| --- | --- | --- | --- |
| Omneum standalone | 0/144 | 7.875 | 0.000 |
| BM25 + Omneum | 102/144 | 5.625 | 2.250 |
| MiniLM + Omneum | 102/144 | 5.333 | 2.542 |
| BGE Reranker + Omneum | 108/144 | 5.500 | 2.375 |
| Cohere + Omneum | 108/144 | 5.292 | 2.583 |

## Statistical strength and sensitivity

The paired case intervals support substantial precision gains for BM25, BGE and Cohere hybrids under this synthetic-case resampling scheme; MiniLM precision spans zero. Every hybrid evidence-retention interval and source-recall interval lies below zero. BGE aggregate claim gain **+1.712579 pp** has CI **[−6.6712, +9.2533] pp**, and origin gain **+0.949074 pp** has CI **[−5.9491, +7.4074] pp**: neither supports a strong population improvement claim. MiniLM origin regression has CI **[−14.0744, −0.7523] pp**. Most BGE origin cell comparisons tie: **24 wins, 98 ties, 22 losses** out of 144; the aggregate origin gain is small and uneven. All 40 comparisons and eight metrics were examined without multiplicity adjustment.

Domain-stratified sensitivity does not reverse any point estimate. Some marginal intervals change whether they cross zero: MiniLM claim loss crosses zero with ordinary case resampling but not with domain-stratified resampling; standalone Omneum claim differences versus Claude/Gemini and origin differences versus Gemini are similarly sensitive. These must not be promoted as robust superiority/inferiority results. Strong frontier evidence gaps and the major hybrid completeness losses persist under both resampling schemes. Only four cases/domain limits domain inference; synthetic case design limits any population interpretation.

## Dependency structure

Saved provenance defines the exploratory strata below. Root-cycle presence refers to a terminal strongly connected origin unit, not every possible internal cycle. Groups overlap with domain/scenario composition, are not randomized, and cannot isolate the mechanism responsible for changes. Case names and texts describe syndication/copy chains, feedback loops, stale sources, conflicting values and missing lineage; individual-case tables supply the direct evidence without treating these scenario names as new gold labels.

| Feature | Value | Cases | Pair | Δ evidence pp | Δ origins pp |
| --- | --- | --- | --- | --- | --- |
| has_declared_dependency | False | 2 | BM25 | -17.454 | -15.972 |
| has_declared_dependency | False | 2 | MiniLM embeddings | -8.987 | -8.333 |
| has_declared_dependency | False | 2 | BGE Reranker v2-m3 | -8.991 | -8.333 |
| has_declared_dependency | False | 2 | Cohere Rerank v4.0 Pro | -18.954 | -18.750 |
| has_declared_dependency | True | 22 | BM25 | -9.325 | -1.881 |
| has_declared_dependency | True | 22 | MiniLM embeddings | -14.155 | -7.083 |
| has_declared_dependency | True | 22 | BGE Reranker v2-m3 | -6.630 | 1.793 |
| has_declared_dependency | True | 22 | Cohere Rerank v4.0 Pro | -8.067 | -1.755 |
| has_root_cycle | False | 21 | BM25 | -10.911 | -3.942 |
| has_root_cycle | False | 21 | MiniLM embeddings | -13.912 | -5.331 |
| has_root_cycle | False | 21 | BGE Reranker v2-m3 | -8.054 | -0.370 |
| has_root_cycle | False | 21 | Cohere Rerank v4.0 Pro | -9.904 | -3.280 |
| has_root_cycle | True | 3 | BM25 | -3.648 | 3.148 |
| has_root_cycle | True | 3 | MiniLM embeddings | -12.405 | -20.185 |
| has_root_cycle | True | 3 | BGE Reranker v2-m3 | 1.770 | 10.185 |
| has_root_cycle | True | 3 | Cohere Rerank v4.0 Pro | -2.465 | -2.407 |

## Latency, tokens and cost


| Configuration | Local p50 ms | Local p95 ms | Historical API p50 s | Historical API p95 s |
| --- | --- | --- | --- | --- |
| Claude Sonnet 5.5 | 0.009042 | 0.014125 | 1.844163 | 3.099168 |
| GPT-6 Astra | 0.009125 | 0.013921 | 2.034325 | 2.989370 |
| Gemini 3.8 Flash | 0.009042 | 0.013417 | 2.033247 | 2.882411 |
| Cohere Rerank v4.0 Pro | 0.009250 | 0.013917 | 0.176650 | 0.196046 |
| MiniLM embeddings | 0.011313 | 0.016333 | NA | NA |
| BGE Reranker v2-m3 | 0.011625 | 0.017167 | NA | NA |
| BM25 | 0.011666 | 0.016750 | NA | NA |
| Cohere + Omneum | 133.640459 | 205.081550 | 0.176650 | 0.196046 |
| Omneum standalone | 127.946229 | 198.868458 | NA | NA |
| BGE Reranker + Omneum | 132.422646 | 202.582092 | NA | NA |
| BM25 + Omneum | 131.614646 | 200.607183 | NA | NA |
| MiniLM + Omneum | 131.484125 | 194.248714 | NA | NA |
| Standard RAG (original-order first-fit) | 0.008750 | 0.012711 | NA | NA |
| Raw full (unbudgeted) | 0.001583 | 0.003377 | NA | NA |

Local ranker times measure sorting/packing/rendering after supplied scores, not relevance inference. Omneum times include graph requests, discovery, packing and client verification, after observations are supplied. Model initialization, dataset loading, daemon startup, upstream structured extraction and relevance scoring are excluded. Token counts were prewarmed. Original six arms and added arms were timed in separate saved executions; avoid attributing tiny local timing differences to model quality. Historical API samples are 24 Cohere requests and 48 per judge, not five fresh remote repeats. Shared ranking cost/latency must not be charged six times for six budgets. No end-to-end latency is available. Stage times overlap and must not be summed.

| Provider | Saved requests | Input tokens | Output tokens | Reported reasoning | Cost at saved rates USD |
| --- | --- | --- | --- | --- | --- |
| Claude Sonnet 5.5 | 48 | 36738 | 4052 | Unknown | 0.11399600 |
| GPT-6 Astra | 48 | 16518 | 2318 | 0 | 0.28108000 |
| Gemini 3.8 Flash | 48 | 17596 | 3209 | Unknown | 0.02523075 |
| Cohere Rerank v4.0 Pro | 24 | None | None | Unknown | NA |

Cost estimates use only the saved spending.py assumptions: Claude $2/$10, GPT $10/$50, Gemini $0.75/$3.75 per million input/output tokens. These are repriced saved usage, not verified invoices or a new live pricing verification. Gemini output uses total_token_count minus prompt tokens; no additional thinking remainder appears in these records. GPT reports zero reasoning; Claude/Gemini reasoning fields are null. Cohere token usage and verified historical cost are unavailable. Cohere + Omneum shares the same 24 Cohere scoring requests, rather than adding another 24. New API expenditure for the completed local replay and this analysis is zero; hardware/electricity, original provider spend and upstream extraction are not zero-cost claims.

## What the results establish

1. **Established rerankers:** no broad completeness improvement. BGE and Cohere hybrids increase precision, but lose evidence/recall; Cohere also loses claim/origin coverage.
2. **Largest hybrid gains:** BGE hybrid has the largest precision gain among the four matched hybrids; it is also the only hybrid with positive aggregate claim and origin deltas, which require checking the intervals above. Cohere hybrid has the highest absolute precision among Omneum arms.
3. **Standalone:** Omneum exceeds original-order RAG on all five quality metrics. Against traditional scored selectors it trades lower evidence/recall for higher aggregate claim/origin coverage; source precision is higher than BM25 but lower than MiniLM, BGE and Cohere.
4. **Frontier judges:** all three beat all Omneum configurations on aggregate precision, recall, evidence, claims and origins. This does not imply every individual cell is a loss; paired files preserve exceptions.
5. **Matched budgets:** same maximum budgets, different realized usage. No all-around evidence-quality dominance and no equal-realized-token causal comparison. Smaller contexts alone do not establish better evidence.
6. **Latency/cost:** roughly 128–134 ms median Omneum selection versus sub-millisecond post-ranking packing; historical judge calls take roughly two seconds. This is a conditional pipeline comparison, not end-to-end retrieval/answer latency.
7. **Persistence:** inspect domain and budget tables for sign changes; aggregate precision gains do not imply origin gains across domains or budgets.
8. **Defensible claims:** quote the exact case set, metric, baseline, budget aggregation, confidence interval, input enrichment, and completeness tradeoff. Do not claim broad reranker superiority, frontier-model superiority, downstream answer improvement, or equal-information access.
9. **Tier 1 limitations:** 24 designed synthetic cases, four/domain; provided structured observations/provenance; no extraction quality/cost evaluation, downstream generation, strict minimal gold claims, answer accuracy, end-to-end latency or real-world independence validation. No unseen public-corpus generalization or ablation-based attribution follows from these artifacts.

## Publication readiness

Suitable for a transparent, narrowly scoped synthetic selection report with these tables and frozen input hashes. Not sufficient for a headline claim that Omneum substantially improves rerankers or beats frontier judges. Research-paper conclusions require external held-out datasets, comparable input-information conditions, extraction accounting, downstream answer evaluation, ablations, and a preregistered primary endpoint. A README can report measured precision/context-size tradeoffs and the conditional latency scope, while showing the evidence/recall regressions alongside them.

## Reproduction and files

Run from the repository root: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -B benchmarks/context_selection/synthetic/analysis/tier1-competitive-analysis-20261026-v1/analyze.py`. This reads saved files and overwrites only derived files in this analysis folder. It launches no tokenizer, daemon, ranking model, API call, or benchmark. Primary and prior runs are combined only through the already-validated primary-run reuse, not through unrelated experiments. Provider records are used solely as the provenance and usage of the rankings already replayed in the primary run.
