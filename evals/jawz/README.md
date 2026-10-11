
# Jawz

External evaluation of Omneum 1.0.3 by [Jawz](https://jawz.ai), a financial research system.

**Evaluator:** Jawz  
**Omneum version:** 1.0.3, dependency estimator v4  
**Environment:** Linux x86_64, Docker (network disabled)  
**Evaluation date:** September 19, 2026  
**Data:** 14 observations, 5 sources, 10 claims

## What was evaluated

Jawz exposes financial indicators built from overlapping economic data. Several outputs consume the same FRED series, even when the resulting indicators describe different things.

That gives Omneum a useful test: can it identify shared dependencies across those outputs without assigning dependency to unrelated source pairs?

Jawz ran the same 14 observations twice. The first mapping explicitly included FRED lineage. The second omitted it.

## Method

The evaluation ran against Omneum's actual `linux-x86_64` daemon in a network-disabled Docker container.

Jawz verified all 80 release checksums before running the tests. The daemon was provisioned and started as `omneum-crypto`; initialization and evaluation ran as `omneum-mcp`.

The input mapping controlled whether FRED appeared in `upstream_sources`.

**Run A — FRED declared**

Every observation derived from FRED included its upstream series in `upstream_sources`. This exposed shared lineage between financial indicators that consumed the same underlying data.

**Run B — FRED omitted**

The same observations were evaluated without those FRED upstream declarations. Existing citation and derivation relationships remained intact.

Both runs were repeated. Results were deterministic.

## Results

### FRED declared

Omneum assigned dependency **1.00** to the declared shared-upstream relationships.

Three unrelated pairs scored **0.00**, including the control.

| Metric | Result |
| --- | ---: |
| Mean dependency | 0.70 |
| Estimated independent support | 1.00 |
| Weighted signal coverage | 0.68 |

The results matched the earlier 1.0.2 evaluation exactly.

### FRED omitted

Two shared-series pairs that scored **0.00** under Omneum 1.0.2 now scored **0.10** under 1.0.3.

The control stayed at **0.00**. Four pairs had zero dependency, while explicitly declared relationships continued to score **1.00**.

| Metric | Result |
| --- | ---: |
| Mean dependency | 0.42 |
| Estimated independent support | 1.245 |
| Weighted signal coverage | 0.68 |

The change comes from estimator v4. Contextual signals can now contribute partial dependency without saturating the score.

### Comparison

| Metric | FRED declared | FRED omitted |
| --- | ---: | ---: |
| Mean dependency | 0.70 | 0.42 |
| Estimated independent support | 1.00 | 1.245 |
| Weighted signal coverage | 0.68 | 0.68 |
| Control pair | 0.00 | 0.00 |

Same observations. Different provenance metadata.

Source-reliability scores were unchanged between configurations.

## Findings

The `upstream_sources` field has a substantial effect on dependency estimates.

When FRED lineage was supplied, Omneum identified the shared relationships at **1.00**. Without it, estimator v4 recovered partial dependency of **0.10** for two shared-series pairs that v3 had treated as independent.

The control remained at zero throughout.

One behavior remains unresolved: explicit lineage saturates dependency at **1.00**. Sharing a single upstream series can produce the same score as sharing several. A direct computational dependency can also reach that value.

The estimator identifies those relationships, but the score does not encode their relative extent.

## Evaluation history

Jawz originally evaluated the workflow against Omneum 1.0.2.

That version assigned dependency **0.00** to shared-series pairs without declared FRED provenance. The explicit-lineage relationships still scored **1.00**.

Omneum 1.0.3 introduced estimator v4. Jawz reran the 14 observations on September 19 and confirmed the new contextual scores.

The declared-FRED run remained identical to 1.0.2. The undeclared run changed where expected, with unrelated pairs still at zero.

## Artifacts

Jawz supplied the methodology and aggregate results from its independent runs.

Complete per-source and pairwise outputs are not included. The evaluation report retains the recorded metrics and observed estimator behavior.