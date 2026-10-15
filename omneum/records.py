"""Dictionary inputs for request-scoped, in-process evaluation."""

from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from typing import Any

from .client import ContextEvaluation, evaluate_context
from .dependency import DependencyEstimatorConfig, _UPSTREAM_ESTIMATOR
from .information import Claim, Observation, Source, SourceReference


_FIELDS = {
    "url", "value", "upstream", "claim", "observation_id", "observed_at",
    "source_modified_at", "owner_id", "cited", "parent_observation_ids", "metadata",
}
_CLAIM_FIELDS = {"entity_namespace", "entity", "attribute"}


def _references(value: Any, name: str) -> tuple[SourceReference, ...] | None:
    if value is None:
        return None
    if type(value) is not list:
        raise TypeError(f"{name} must be a list of URL strings or None")
    return tuple(SourceReference("web_document", url) for url in value)


def evaluate(
    records: Sequence[Mapping[str, Any]],
    *,
    estimator: DependencyEstimatorConfig | None = None,
) -> ContextEvaluation:
    """Evaluate URL/value dictionaries in memory through evaluate_context().

    Records without ``claim`` describe one attribute: records/default/value.
    For multiple attributes, every record must provide a complete ``claim``
    mapping with entity_namespace, entity, and attribute. Values distinguish
    competing claims within an attribute. URLs identify web_document sources.

    Missing upstream/cited/lineage is unknown; an empty list records no known
    dependencies. One UTC timestamp per call supplies missing observed_at;
    observation IDs default to record:<zero-based index>. The default estimator
    uses only upstream provenance; pass estimator= to select other signals.

    Returns the full ContextEvaluation, including per-claim fractional support.
    Its estimated_independent_support property requires exactly one claim.
    No transport, daemon, network, keys, or database is used. See docs/sdk.md
    for the full input schema and existing evaluation bounds.
    """
    if not isinstance(records, Sequence) or isinstance(records, (str, bytes)):
        raise TypeError("records must be a sequence of mappings")
    values = tuple(records)
    if any(not isinstance(record, Mapping) for record in values):
        raise TypeError("records must contain mappings")
    explicit_claims = ["claim" in record for record in values]
    if any(explicit_claims) and not all(explicit_claims):
        raise ValueError("provide claim identity for every record or for none")

    now = datetime.now(timezone.utc)
    observations = []
    for index, record in enumerate(values):
        unknown = record.keys() - _FIELDS
        if unknown:
            raise ValueError(f"record {index} contains unsupported fields: {unknown}")
        if "url" not in record or "value" not in record:
            raise ValueError(f"record {index} requires url and value")
        identity = record.get("claim", {
            "entity_namespace": "records", "entity": "default", "attribute": "value",
        })
        if not isinstance(identity, Mapping) or identity.keys() != _CLAIM_FIELDS:
            raise ValueError("claim must contain exactly entity_namespace, entity, and attribute")
        parents = record.get("parent_observation_ids")
        if parents is not None and type(parents) is not list:
            raise TypeError("parent_observation_ids must be a list of strings or None")
        observations.append(Observation(
            observation_id=record.get("observation_id", f"record:{index}"),
            source=Source("web_document", record["url"], record.get("owner_id")),
            claim=Claim(**identity, value=record["value"]),
            observed_at=record.get("observed_at", now),
            source_modified_at=record.get("source_modified_at"),
            upstream_sources=_references(record.get("upstream"), "upstream"),
            cited_sources=_references(record.get("cited"), "cited"),
            parent_observation_ids=None if parents is None else tuple(parents),
            metadata=record.get("metadata", {}),
        ))
    return evaluate_context(
        observations, estimator=_UPSTREAM_ESTIMATOR if estimator is None else estimator,
    )


# Backward-compatible name for the dictionary convenience API.
evaluate_records = evaluate
