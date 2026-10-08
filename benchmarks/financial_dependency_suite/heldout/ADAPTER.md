# Held-out SDK boundary adapter

## Entity namespaces

The frozen case schema stores `CandidateSpec.entity_namespace` and `entity` as
nonempty semantic strings. `load_case` copies these fields verbatim. They are
benchmark identity labels, not Omneum canonicalization profiles. The complete
inventory is below; counts are candidate occurrences.

| Benchmark namespace | Count | Cases (count) |
| --- | ---: | --- |
| `analytics` | 33 | `analytics_derived_metric_cycle` (8), `analytics_incomplete_lineage` (9), `analytics_metric_definition_conflict` (8), `analytics_stale_dashboard` (8) |
| `api_operations` | 6 | `multi_agent_independent_error` (6) |
| `enterprise_policy` | 35 | `enterprise_partial_lineage` (8), `enterprise_policy_copy_chain` (9), `enterprise_semantic_distractors` (10), `enterprise_stale_handbook` (8) |
| `fulfillment` | 8 | `multi_agent_repeated_subagent` (8) |
| `housing` | 7 | `research_independent_false_consensus` (7) |
| `infrastructure` | 7 | `research_clean_consensus` (7) |
| `land_use` | 8 | `research_conflicting_reports` (8) |
| `operations` | 30 | `support_clean_resolution` (7), `support_resolution_conflict` (7), `support_stale_runbook` (8), `support_ticket_reference_loop` (8) |
| `release` | 8 | `multi_agent_feedback_loop` (8) |
| `software` | 29 | `coding_api_version_change` (8), `coding_clean_dependency` (7), `coding_config_conflict` (6), `coding_package_fix_lineage` (8) |
| `storage` | 9 | `multi_agent_relevant_wrong_task` (9) |
| `transport` | 9 | `research_syndicated_reporting` (9) |

Omneum's only accepted entity namespace is `service`. Its canonicalizer performs
Unicode NFC normalization, trims surrounding whitespace, and lowercases. Core
canonicalization is unchanged. The previous adapter passed semantic namespaces
straight to `Claim`; that constructor validates strings, attributes and values,
but does not canonicalize entity identity. `client.evaluate_context` calls
`_snapshot_observations`, which calls `canonicalize_entity` and rejects these
unsupported namespace names before evaluation.

## Lossless identity mapping

`build_observations` now maps every benchmark identity pair `(namespace, entity)`
to an SDK identity as follows:

```python
identity = json.dumps([namespace, entity], ensure_ascii=True, separators=(",", ":"))
sdk_namespace = "service"
sdk_entity = "heldout-entity-v1:" + identity.encode("ascii").hex()
```

This uses `service` as the available canonical identifier profile; it does not
classify every benchmark object as an operational service. The complete original
namespace remains encoded in the identifier. JSON array framing is unambiguous,
and lowercase hexadecimal is reversible and invariant under service
canonicalization. It preserves exact spelling, case, whitespace and Unicode
representation without assuming undocumented aliases. Equal benchmark identity
pairs yield equal SDK identities; different pairs cannot collapse. No case ID is
added, so equal identities also remain equal across cases. The prefix versions
this benchmark-owned encoding. All benchmark identities take this path, including
any label spelled `service`; there is no mixed raw/encoded identity space.

This is justified because entity names are equality/grouping keys in the client
and dependency estimator, with no domain-specific processing of these labels.
The mapping preserves those partitions, including competing claims grouped by
entity and attribute. It does not alter attributes, values, provenance, or
estimator weights. CandidateSpec retains the original labels, and application
candidate text and IDs are unchanged. All observations, and consequently all
claims consumed by selection and evaluation, use the single boundary mapping.
Ground truth contains no entity identity requiring a parallel mapping.

## Local verification

The loader tests call the actual `omneum.client._snapshot_observations` function
on all 24 cases, without creating a client, daemon, or provider connection. They
check decoding, canonicalization idempotence, entity and claim identity
partitions, provenance preservation, the analytics regression, and adversarial
case/Unicode/delimiter collisions. The dataset has 189 observations and 36 distinct
original entity identity pairs. All 24 complete snapshots pass.

The earlier source adapter maps known URL-backed artifact roles to
`web_document` consistently for sources and references, retaining original
SourceSpec metadata. Neither adapter edits frozen inputs or core canonicalizers.
