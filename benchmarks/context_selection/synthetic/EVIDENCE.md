
# Benchmark Evidence

Execution records, validation results, and reproducibility artifacts for the [Cross-Domain Context Curation Benchmark](../../README.md).

The published [leaderboard](../../leaderboard.md) combines the original competitor selections with the final Omneum budget-exhaustion recovery results. All configurations use the same 24 synthetic cases and six Qwen-token budgets: `64`, `96`, `128`, `160`, `192`, and `256`.

## Execution Records

| Run | Configurations | Records | Artifacts |
|---|---|---:|---|
| [Production](results/tier1-production-20261025-v1/) | BM25, MiniLM, BGE, and their Omneum hybrids | 4,320 | [Selections](results/tier1-production-20261025-v1/selections.json), [timings](results/tier1-production-20261025-v1/timings.csv), [validation](results/tier1-production-20261025-v1/validation.json) |
| [Competitors](results/tier1-competitors-20261025-v1/) | 13 budgeted configurations and unbudgeted `raw_full` | 11,640 | [Selections](results/tier1-competitors-20261025-v1/selections.json), [timings](results/tier1-competitors-20261025-v1/timings.csv), [validation](results/tier1-competitors-20261025-v1/validation.json) |
| [Final recovery](results/budget-exhaustion-recovery-20261026-v2/) | Omneum standalone and four reranker/Omneum hybrids | 3,600 | [Selections](results/budget-exhaustion-recovery-20261026-v2/selections.json), [timings](results/budget-exhaustion-recovery-20261026-v2/timings.csv), [validation](results/budget-exhaustion-recovery-20261026-v2/validation.json) |

The competitor run supplies the published non-Omneum results. The final recovery run supplies the published results for:

- `omneum`
- `bm25_omneum`
- `embedding_omneum`
- `bge_omneum`
- `cohere_omneum`

The production run remains the preceding execution record. The competitor run preserves those original selections while adding hosted and local selector configurations.

### Execution Verification

| Check | Production | Competitors | Final recovery |
|---|---:|---:|---:|
| Cases | 24 | 24 | 24 |
| Token budgets | 6 | 6 | 6 |
| Configurations | 6 | 14 | 5 |
| Recorded executions | 4,320 | 11,640 | 3,600 |
| Timing repetitions | 5 | 5 | 5 |
| Exact budget violations | 0 | 0 | 0 |
| New paid API calls | 0 | 0 | 0 |

The [production validation](results/tier1-production-20261025-v1/validation.json) checks all 4,320 executions, including 2,160 fresh graph executions. Regenerated `summary.json` output matches the saved summary.

The [competitor validation](results/tier1-competitors-20261025-v1/validation.json) checks 2,328 unique case-budget-trial cells and 11,640 timing records. Selected passages are identical across timing repetitions, and the original production selections remain preserved.

The [recovery validation](results/budget-exhaustion-recovery-20261026-v2/validation.json) checks deterministic selections and tokenizer counts across 3,600 executions. Reconstructed context stays within the Qwen-token budget, and full-graph claim support matches the frozen inference trace.

## Budget-Exhaustion Recovery

The completed recovery evaluation measures a correction to `OmneumClient.prepare_context()`.

Previously, `query_context.discover_chunks()` restricted selection to a neighborhood constructed from three relevance anchors, including score ties, with expansion depth two. Passages outside that neighborhood could not be selected, even when token capacity remained.

The corrected implementation preserves the initial selection and evaluates deferred passages after the discovered neighborhood has no remaining positive, feasible marginal utility. A deferred passage must meet the weakest utility-per-token density accepted during initial selection.

Recovery reuses the covered claim-cluster state without rerunning graph inference.

| Parameter | Value |
|---|---|
| Selection objective | `coverage_support_density` |
| Complementary evidence | `True` |
| Token cost exponent | `1` |
| Conflict-aware selection | `False` |
| Discovery anchors | 3, plus score ties |
| Expansion depth | 2 |

The correction does not change graph inference equations, relevance normalization, or token-budget enforcement.

### Recovery Artifacts

| Artifact | Contents |
|---|---|
| [Recovery report](results/budget-exhaustion-recovery-20261026-v2/report.md) | Corrected results and evaluated alternatives |
| [Production patch](results/budget-exhaustion-recovery-20261026-v2/production-change.patch) | Recorded implementation changes |
| [Source reliability validation](results/budget-exhaustion-recovery-20261026-v2/source_reliability_validation.json) | Source reliability checks |
| [Offline validation](results/budget-exhaustion-recovery-20261026-v2/offline_validation.json) | Offline execution checks |
| [Paired case-budget results](results/budget-exhaustion-recovery-20261026-v2/paired_case_budget.csv) | Per-case and per-budget comparisons |
| [Execution manifest](results/budget-exhaustion-recovery-20261026-v2/manifest.json) | Source and artifact provenance |

The completed recovery is `budget-exhaustion-recovery-20261026-v2`. The earlier V1 analysis was interrupted during timing collection because initial samples overlapped concurrent tests. Its valid offline results remain methodological evidence for the evaluated alternatives, not the final published execution.

## Competitive Analysis

The [competitive analysis](analysis/tier1-competitive-analysis-20261026-v1/report.md) recomputes the 2,328 original selection records against canonical case annotations.

Its integrity checks cover candidate membership, passage text, selection metrics, timing percentiles, and preservation of the original production selections.

Statistical comparisons use 50,000 paired whole-case bootstrap resamples with seed `20261026`. All six budgets remain grouped within each sampled case. Frontier judge trials are averaged before pairing.

| Artifact | Contents |
|---|---|
| [Paired comparisons](analysis/tier1-competitive-analysis-20261026-v1/paired_comparisons.csv) | Matched configuration differences |
| [Hybrid confidence intervals](analysis/tier1-competitive-analysis-20261026-v1/hybrid_budget_confidence_intervals.csv) | Bootstrap intervals for hybrid comparisons |
| [Domain results](analysis/tier1-competitive-analysis-20261026-v1/by_domain.csv) | Metrics across six domains |
| [Budget results](analysis/tier1-competitive-analysis-20261026-v1/by_budget.csv) | Metrics at each Qwen-token ceiling |
| [Dependency strata](analysis/tier1-competitive-analysis-20261026-v1/dependency_strata.csv) | Results grouped by annotated dependency characteristics |
| [Audit](analysis/tier1-competitive-analysis-20261026-v1/audit.json) | Selection and artifact-integrity checks |

These files describe the original competitor run. Corrected Omneum comparisons are recorded separately in the final recovery artifacts.

### Recovery Comparisons

| Artifact | Contents |
|---|---|
| [Paired comparisons](results/budget-exhaustion-recovery-20261026-v2/paired_comparisons.csv) | Corrected versus original and matched-ranker differences |
| [Paired cases](results/budget-exhaustion-recovery-20261026-v2/paired_cases.csv) | Whole-case paired results |
| [Paired case budgets](results/budget-exhaustion-recovery-20261026-v2/paired_case_budget.csv) | Per-case, per-budget results |
| [Paired domain budgets](results/budget-exhaustion-recovery-20261026-v2/paired_domain_budget.csv) | Domain and budget comparisons |
| [Improvement coverage](results/budget-exhaustion-recovery-20261026-v2/improvement_coverage.csv) | Cases and cells with completeness gains |
| [Alternative comparison](results/budget-exhaustion-recovery-20261026-v2/alternative_comparison.csv) | Original, full-pool, positive-only, and staged-recovery results |

The recovery comparison preserves the original selected passages in every corrected cell. Evidence retention, recall, claim coverage, and source-origin coverage do not decrease across the corrected cells; precision and context reduction can decrease.

Bootstrap intervals are exploratory estimates over 24 designed synthetic cases. They are not adjusted for multiple comparisons.

## Provider Response Provenance

The competitor and recovery executions replay saved provider rankings. No new hosted inference requests were issued.

| Provider | Saved requests | Model |
|---|---:|---|
| Cohere | 24 | `rerank-v4.0-pro` |
| Anthropic | 48 | Claude Sonnet 5.5 |
| OpenAI | 48 | GPT-6 Astra |
| Google | 48 | Gemini 3.8 Flash |

Cohere supplies one ranking per case. Each frontier judge supplies two ranking trials per case. Saved rankings are reused across all six token budgets.

The [original provider responses](results/question-aware-release-v1/provider_results.jsonl) preserve the recorded responses. The [provider timing record](results/tier1-competitors-20261025-v1/historical_provider.json) records request timings and model identifiers, and the [competitor manifest](results/tier1-competitors-20261025-v1/manifest.json) records model configurations and execution provenance.

Historical provider latency and recorded token usage are separate from local selection timings. See [Latency Analysis](LATENCY_ANALYSIS.md).

## Historical Publication

The earlier selection-and-answer experiments remain separate from the current context-selection benchmark.

Their original six-run publication includes BGE and Cohere comparisons with Omneum and frontier LLM judges. Those experiments measured source selection and downstream answer generation under source-count budgets.

The original [`publication_manifest_v1.json`](../publication_manifest_v1.json) records the historical publication artifact hashes. It does not cover the newer production, competitor, or recovery executions.

Historical result directories are preserved under [`results/`](results/). Their execution manifests record reference Git revisions, but dirty working trees mean those commits alone do not identify the exact executed source.

The current evaluation uses its execution manifests, recorded source hashes, validation artifacts, and recovery patch to distinguish the evaluated implementations.

## Measurement Scope

| Component | Recorded scope |
|---|---|
| Context selection | Saved ranking inputs and structured claim/provenance observations |
| Local selection latency | Graph evaluation, discovery, packing, reconstruction, SDK verification |
| Token budgets | Qwen tokenizer counts for reconstructed context |
| Evidence retention | Annotated supporting-span footprint |
| Source-origin coverage | Annotated provenance graph |
| Provider inference | Historical saved ranking responses |
| Downstream answer generation | Not measured in the current benchmark |

Ranker inference and structured extraction are excluded from local selection timings. Original and recovery timing sessions are not directly attributable to a single implementation change.

The 24 cases were used during subsequent recovery-policy development. The resulting confidence intervals and performance comparisons describe the recorded synthetic evaluation, not an untouched external test set.

## References

- [Benchmark Methodology](../../README.md)
- [Leaderboard](../../leaderboard.md)
- [Dataset](DATASET.md)
- [Latency Analysis](LATENCY_ANALYSIS.md)
- [Final Recovery Report](results/budget-exhaustion-recovery-20261026-v2/report.md)
- [Source Contracts](contracts/README.md)