import pytest

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
        observation_id=lambda x: x["id"],
        observed_at=lambda x: NOW,
    )

    observation = mapper.map(result)

    assert observation.source.kind == "internal_service"
    assert observation.source.identifier == "research-api"
    assert observation.claim.entity == "payment_api"
    assert observation.claim.attribute == "status_code"
    assert observation.claim.value == 200
    assert observation.observation_id == "result-1"


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
        observation_id=lambda x: x["id"],
        observed_at=lambda x: NOW,
    )

    observations = mapper.map_many(results)

    assert len(observations) == 2
    assert observations[0].claim.value == "healthy"
    assert observations[1].claim.value == "healthy"


def test_context_mapper_preserves_arbitrary_metadata():
    result = {
        "source": "example-source",
        "entity": "memory-1",
        "attribute": "content",
        "value": "example",
        "id": "result-1",
        "replaces": "memory-0",
        "write_origin": "agent-session",
        "related_via": [
            {"id": "memory-2", "cosine": 0.91},
        ],
    }

    mapper = ContextMapper(
        source=lambda x: Source(
            kind="memory",
            identifier=x["source"],
        ),
        entity_namespace=lambda x: "memory",
        entity=lambda x: x["entity"],
        attribute=lambda x: x["attribute"],
        value=lambda x: x["value"],
        observation_id=lambda x: x["id"],
        observed_at=lambda x: NOW,
        metadata={
            "replaces": "replaces",
            "write_origin": "write_origin",
            "related_via": "related_via",
        },
    )

    observation = mapper.map(result)

    assert observation.metadata["replaces"] == "memory-0"
    assert observation.metadata["write_origin"] == "agent-session"
    assert observation.metadata["related_via"][0]["cosine"] == 0.91


def test_context_mapper_maps_application_fields_to_canonical_signals():
    from omneum.dependency import DependencySignal

    result = {
        "source": "research-api",
        "entity": "payment_api",
        "attribute": "status",
        "value": "healthy",
        "id": "result-1",
        "session_id": "session-42",
        "retrieved_from": "sec-search",
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
        observation_id=lambda x: x["id"],
        observed_at=lambda x: NOW,
        signals={
            "retrieval": lambda x: DependencySignal(
                value=1.0
                if x["session_id"] == "session-42"
                else 0.0,
                observable=True,
            ),
        },
    )

    observation = mapper.map(result)

    assert set(observation.dependency_signals) == {"retrieval"}
    assert observation.dependency_signals["retrieval"].value == 1.0
    assert (
        observation.dependency_signals["retrieval"].observable
        is True
    )


def test_context_mapper_rejects_noncanonical_dependency_signals():
    from omneum.dependency import DependencySignal

    with pytest.raises(
        ValueError,
        match="unsupported dependency signals: session",
    ):
        ContextMapper(
            source=lambda x: Source(
                kind="internal_service",
                identifier=x["source"],
            ),
            entity_namespace=lambda x: "service",
            entity=lambda x: x["entity"],
            attribute=lambda x: x["attribute"],
            value=lambda x: x["value"],
            observation_id=lambda x: x["id"],
            observed_at=lambda x: NOW,
            signals={
                "session": lambda x: DependencySignal(
                    value=1.0,
                    observable=True,
                ),
            },
        )
