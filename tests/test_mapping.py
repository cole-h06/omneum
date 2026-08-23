from datetime import datetime, timezone

from omneum import ContextMapper, Source


NOW = datetime(2026, 8, 22, 12, tzinfo=timezone.utc)


def test_context_mapper_maps_structured_result():
    result = {
        "source": "research-api",
        "entity": "payment_api",
        "attribute": "status_code",
        "value": 200,
        "id": "result-1",
    }

    mapper = ContextMapper(
        source=lambda x: Source(
            kind="internal_service",
            identifier=x["source"],
        ),
        entity_namespace=lambda x: "service",
        entity=lambda x: x["entity"],
        attribute=lambda x: x["attribute"],
        value=lambda x: x["value"],
        assertion_id=lambda x: x["id"],
        observed_at=lambda x: NOW,
    )

    observation = mapper.map(result)

    assert observation.source.kind == "internal_service"
    assert observation.source.identifier == "research-api"
    assert observation.claim.entity == "payment_api"
    assert observation.claim.attribute == "status_code"
    assert observation.claim.value == 200
    assert observation.assertion_id == "result-1"


def test_context_mapper_maps_many():
    results = [
        {
            "source": "service-a",
            "entity": "payment_api",
            "attribute": "status",
            "value": "healthy",
            "id": "a",
        },
        {
            "source": "service-b",
            "entity": "payment_api",
            "attribute": "status",
            "value": "healthy",
            "id": "b",
        },
    ]

    mapper = ContextMapper(
        source=lambda x: Source(
            kind="internal_service",
            identifier=x["source"],
        ),
        entity_namespace=lambda x: "service",
        entity=lambda x: x["entity"],
        attribute=lambda x: x["attribute"],
        value=lambda x: x["value"],
        assertion_id=lambda x: x["id"],
        observed_at=lambda x: NOW,
    )

    observations = mapper.map_many(results)

    assert len(observations) == 2
    assert observations[0].claim.value == "healthy"
    assert observations[1].claim.value == "healthy"
