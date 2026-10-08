# Bastra Recall

External evaluation of Omneum 1.0.3 by Daniel Nevoigt, creator of Bastra Recall [Bastra Recall](https://github.com/n0mad-ai/bastra-recall).

**Evaluator:** Daniel Nevoigt  
**System:** Bastra Recall  
**Omneum version:** 1.0.3  
**Environment:** macOS arm64, Python 3.14  
**Data:** Synthetic

## What was evaluated

Daniel used synthetic Bastra Recall memories to test Omneum against common problems in agent memory and retrieved context.

The test data includes memories copied from the same upstream source, memories that replace older versions, conflicting values, and records created at different times. Omneum receives the source and provenance metadata attached to each memory and evaluates how much independent support the resulting context actually contains.

The evaluation runs Omneum locally without the MCP server or managed daemon.

## Method

Each Bastra Recall memory was converted into an Omneum evaluation record with its own source. Daniel preserved the source IDs, timestamps, replacement links, and conflict records already present in the synthetic memories.

Memories with the same `source` value were linked to the same upstream source. A `replaces` relationship linked a newer memory to the record it replaced. Timestamps were passed through unchanged, and conflicting values were represented as separate records from separate sources.

Daniel ran two sets of tests. The first used 10 small cases designed to isolate how different source relationships affect estimated independent support. The second used 14 cases with multiple values in the same evaluation, including replacement histories and conflicting values.

## Results

### Independent support

Omneum distinguished between memories constructed as independent sources and memories that ultimately came from the same source.

Three memories from three independent sources produced an estimated independent support of **3.0**. Four memories derived from the same upstream source produced an estimated independent support of **1.0**.

Daniel also tested four memories connected through both a shared source and a replacement relationship. Omneum still counted them as **1.0** independent source rather than counting both relationships separately.

| Test case | Records | Estimated independent support |
| --- | ---: | ---: |
| Independent sources | 3 | 3.0 |
| Shared upstream source | 4 | 1.0 |
| Shared source + replacement relationship | 4 | 1.0 |

### Records created at different times

Daniel tested three otherwise independent memories created at different times to see whether closely timed records would be treated as completely independent.

When all three had identical timestamps, estimated independent support was **2.50**. As the timestamps moved farther apart, it increased gradually:

| Timestamps | Estimated independent support |
| --- | ---: |
| Identical | 2.50 |
| 0h / 1h / 2h | 2.51 |
| 0h / 6h / 30h | 2.69 |
| 0h / 24h / 47h | 2.81 |
| 48h+ apart | 3.00 |

This was a change from Omneum 1.0.2, where the same temporal test could reduce the three memories to an estimated independent support of **1.0**.

### Replacement histories

Daniel tested histories where a memory was replaced by a newer version but the older values were still present in the evaluated context.

Omneum recognized the records as related, but the replacement relationship did not make the newest value authoritative. In the retention-history case, the `7d`, `30d`, `90d`, and `180d` values each received the same support score of **0.0625**.

A four-version replacement chain also exposed an unresolved dependency case. Four linked versions that Daniel expected to count as one underlying source produced an estimated independent support of **1.60** instead of **1.0**. Omneum detected the direct replacement relationships between adjacent versions, but did not propagate that dependency across the complete chain.

### Conflicting context

Daniel tested memory records containing competing values for the same field. Omneum detected all of the conflicts in the test set.

When two conflicting values each came from a single source, neither was given an artificial advantage: both received a support score of **0.25**.

The larger K3 replacement case exposed a different limitation. The current rate-limit value of `1000/min` received a support score of **0.0447**, while the superseded `100/min` and `300/min` values each received **0.0610**. The source containing the current value still received the highest source-reliability score, but that did not cause the current value itself to rank first.

### Support across evaluations

Daniel also compared the same conflicting values when evaluated alone and when evaluated alongside unrelated records.

A `500` versus `50` conflict received support scores of **0.25** each when evaluated alone. In the larger combined evaluation, those same values received **0.0417** each.

This means the absolute support score is relative to the context being evaluated. Scores from different evaluations should not be compared as though they share a fixed global scale.

## Findings

The evaluation identified two unresolved behaviors in Omneum 1.0.3.

First, dependency from replacement relationships is only applied directly. In a four-version replacement chain, adjacent versions were recognized as dependent, but that relationship did not propagate across the full chain. The four records therefore produced an estimated independent support of **1.60** instead of **1.0**.

Second, a replacement relationship does not tell Omneum that the newer value should supersede the older one. Older values can therefore receive equal or greater support when both versions remain in the evaluated context.

Daniel also found that support scores change with the other context included in an evaluation. They should be interpreted within an evaluation rather than compared as fixed scores across separate evaluations.

## Evaluation history

Daniel tested Omneum across several releases while developing the Bastra Recall test harness.

Testing of Omneum 1.0.2 exposed a problem with timestamp-based dependency scoring that could collapse otherwise independent memories to a single effective source. Omneum 1.0.3 changed that behavior to vary gradually with the time between records. Daniel independently reran the cases against 1.0.3 and verified the corrected results.

The replacement-chain behavior described above remained unresolved in 1.0.3.

## Artifacts

The original evaluation outputs supplied by Daniel are included unchanged.

The JSON files contain the saved evaluation records from the September 28 run. The TXT files are Daniel's developer-facing rendering of those same saved results, generated with `render_report` from `local_evaluation.py`. Nothing was recomputed, and the reported latencies are the measurements from the original run.

- [`omneum-103-local-evaluation.json`](artifacts/omneum-103-local-evaluation.json)
- [`omneum-103-local-evaluation-multiclaim.json`](artifacts/omneum-103-local-evaluation-multiclaim.json)
- [`omneum-103-local-evaluation-output.txt`](artifacts/omneum-103-local-evaluation-output.txt)
- [`omneum-103-local-evaluation-multiclaim-output.txt`](artifacts/omneum-103-local-evaluation-multiclaim-output.txt)

SHA-256:

- `omneum-103-local-evaluation.json` — `b0725f741be3827b667499454c423e81c0f8d4e67bdcde640ea6611567afd693`
- `omneum-103-local-evaluation-multiclaim.json` — `f0dcc855dece665dc6c83e5e5014c8332b1dbe0e17efd46dc3eb61a3f1e749b5`
- `omneum-103-local-evaluation-output.txt` — `d38a083632c2cf1eff803fc8c6954ed1e9ab35588f28271646d06d0f4fe8b3b1`
- `omneum-103-local-evaluation-multiclaim-output.txt` — `93706a637656abd0aeb5fabb8b6f0fabb7caf2d7a90ee8fd3c47fb21049b2e9c`