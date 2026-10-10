from datetime import datetime, timezone

from omneum import Claim, Observation, Source

from examples.enterprise.agents.common import ENTITY, ENTITY_NAMESPACE

SCOPE = "7c710000-1234-4abc-8def-123456789abc"

ROUTING_VALUES = {
    "input_data_policy": "redacted customer content only",
    "provider_retention": "0 days",
    "processing_region": "EU",
}

STRATEGIES = {
    "retrieve_support": {
        "owner": "evidence-retrieval",
        "source_kind": "internal_resource",
        "source_number": 10,
    },
    "resolve_conflicts": {
        "owner": "independent-policy-review",
        "source_kind": "internal_resource",
        "source_number": 20,
    },
    "diversify_sources": {
        "owner": "independent-compliance-audit",
        "source_kind": "internal_resource",
        "source_number": 30,
    },
}


def retrieve_additional_evidence(
    attributes: tuple[str, ...],
    *,
    strategy: str,
    attempt: int = 1,
) -> tuple[Observation, ...]:
    """Retrieve attribute-specific evidence using the selected strategy."""
    if strategy not in STRATEGIES:
        raise ValueError(f"Unknown retrieval strategy: {strategy}")
    if attempt < 1 or attempt > 2:
        raise ValueError("Only two retrieval attempts are defined")

    config = STRATEGIES[strategy]
    source_number = config["source_number"] + attempt

    source = Source(
        config["source_kind"],
        f"v1:{SCOPE}:{source_number:08d}-0000-4000-8000-{source_number:012d}",
        f"{config['owner']}-{attempt}",
    )

    timestamp = datetime(
        2026, 7, 17 + attempt, 9, 0, tzinfo=timezone.utc
    )

    selected = tuple(dict.fromkeys(attributes))

    return tuple(
        Observation(
            observation_id=f"routing-{strategy}-{attempt}-{attribute}",
            source=source,
            claim=Claim(
                ENTITY_NAMESPACE,
                ENTITY,
                attribute,
                ROUTING_VALUES[attribute],
            ),
            observed_at=timestamp,
            source_modified_at=timestamp,
            upstream_sources=(),
            cited_sources=(),
            parent_observation_ids=(),
            retrievals=(),
        )
        for attribute in selected
        if attribute in ROUTING_VALUES
    )
