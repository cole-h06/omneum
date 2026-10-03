# Briefing Service mapping audit

Scope: `data/world.json` only. This is an adapter and mapping audit, not an
evaluation runner. The original three dataset files are unchanged.

## Mapping contract

`adapter.adapt_dataset` retains a deep copy of the entire export, including all
75 candidates in original order and all original fields. Candidate IDs remain
the join key. Canonical URLs identify `web_document` sources; publisher names
are not ownership metadata. Shared URLs are reported in the audit rather than
silently merging candidate records.

Only nonempty strings in `points_isolated` become assertions. Normalization v1
uses Unicode NFC, straight quotes, case folding, collapsed whitespace, and
removal of one final period. It does not remove negation, resolve pronouns,
extract entities, merge paraphrases, or use duplicate groups. A hash of the full
normalized proposition is an opaque claim entity key in the SDK's `service`
namespace; the attribute is `isolated point` and the value is that proposition.
This is a text-level assertion mapping, not a structured semantic fact model.
The derived assertion ID encodes the original candidate ID and zero-based point
index. Original text and indexes remain available. Repeated normalized points
within a candidate share one assertion while retaining every occurrence index.

The export's `generated_at` is explicitly used as the application's export
observation time. `published`, `ranked_at`, and `generated_at` remain unchanged
in the retained dataset. Publication time is not assumed to be last-modified
time, and export observation time does not supply a temporal dependency signal.
Missing canonical URLs or export observation timestamps block observation
construction and are reported, without losing the candidate or its points.

`duplicate_of`, `dup_rule`, and `dup_score` are a separate external baseline.
They and `also_in` never enter Omneum observations or signal inputs. Missing
upstream, citation, assertion lineage, retrieval, and modification-time fields
remain `None`; ownership remains `None`; explicit dependency signals remain
empty. A missing signal is not an observed zero or evidence of independence.

There is deliberately no automatic full-pool observation builder. Callers must
request observations per eligible candidate. Requesting an ineligible candidate
raises an error. All 60 candidates without points remain in the audit. Any
future comparison must retain the same candidate pool across methods and report
these candidates as unavailable for assertion-level scoring; a 15-record subset
must never be presented as a full-pool result.

## Inspection of actual points

The 15 point-bearing candidates contain 48 usable assertions. None match across
candidates under normalization v1. All five duplicate edges have eligible
endpoints, but none have matching normalized assertions:

| Duplicate → target | Point inspection |
| --- | --- |
| `982758730c73` → `3fa3005b12c1` | Both discuss House contempt action involving Black. One says the House held Leon Black in contempt; the other says it voted to hold Black in contempt. Actor reference and action wording would require reviewed semantic alignment. The remaining points concern different details. |
| `af65616e5134` → `5308710e525c` | Denial of involvement in an attempted attack and denial of targeting the holy city may overlap, but differ in wording and scope. Neither supplies an exact point match. |
| `479695dfd391` → `5308710e525c` | Denying the claim that a drone was shot down is not equivalent to denying that Mecca was targeted. No alignment is asserted. |
| `125d54f62bcb` → `5308710e525c` | Denial of targeting Mecca is a plausible semantic overlap with denial of targeting the Islamic holy city; resolving the latter requires context. No automatic equivalence is asserted. |
| `555f9f3fd93d` → `9aac3f7f2734` | Both describe a Seoul restaurant fine involving ants, but operator versus owner, dessert versus garnish, and the distributed restaurant description require interpretation. The monetary and prosecution details differ. |

These are review notes, not additional assertions or alignment overrides.
Duplicate-to-target links are used directly; the audit does not invent extra
duplicate edges between members sharing a target. Absence of a duplicate label
is not verified independence.

## Observability and evaluation boundary

No dependency signals are observable under this mapping: no recorded lineage,
citations, owner identities, retrieval events, or source modification times are
available; the adapter supplies no graph signal. Exact text agreement alone
would not establish dependency either.

The dataset supports an auditable coverage and alignment study, but does not
currently support a meaningful dependency-quality comparison against its
heuristic `duplicate_of` baseline. It has five external duplicate edges, zero
exact assertion matches across their endpoints, no dependency evidence, and
60/75 candidates without assertions. Any later semantic alignment must be
reviewed separately without treating duplicate labels as equivalence evidence;
semantic alignment alone would not fill the missing provenance.

## Reproduce the audit and focused tests

From the repository root, using the existing environment (no downloads):

```sh
.venv/bin/python -m benchmarks.external.briefing_service.adapter
.venv/bin/python -m pytest -q -p no:cacheprovider benchmarks/external/briefing_service/test_adapter.py
```

`mapping_audit.json` records all candidate IDs, eligibility reasons, point
mappings, duplicate comparisons, and observability. The audit command only
prints JSON; it does not run the estimator. Focused tests include a two-candidate
SDK compatibility check verifying that missing signals stay unobserved, not a
benchmark run. No evaluation runner is implemented.
