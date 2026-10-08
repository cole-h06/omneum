from dataclasses import FrozenInstanceError
from datetime import datetime, timezone

import pytest

from omneum.information import Claim, Observation, Retrieval, Source, SourceReference


NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def reference(identifier="a"):
    return SourceReference("web_publisher", identifier)


def claim(value="value"):
    return Claim("service", "Entity", "Attribute", value)


def observation(**changes):
    values = {
        "observation_id": "assertion-a",
        "source": Source("web_publisher", "example.com"),
        "claim": claim(),
        "observed_at": NOW,
        "source_modified_at": NOW,
        "upstream_sources": (),
        "cited_sources": (),
        "parent_observation_ids": (),
        "retrievals": (),
        "metadata": {},
        "dependency_signals": {},
    }
    values.update(changes)
    return Observation(**values)


def test_models():
    source = Source("web_publisher", "example.com", "owner")
    item = observation()

    assert source.owner_id == "owner"
    assert item.upstream_sources == ()
    assert item.source_modified_at == NOW
    assert item.metadata == {}
    assert item.dependency_signals == {}


def test_retrieval():
    fields = {"status": 200, "nested": {"values": [1]}}
    retrieval = Retrieval(
        retrieval_id="retrieval-a",
        kind="http",
        resource_id="https://example.com/document",
        retrieved_at=NOW,
        fields=fields,
    )

    fields["nested"]["values"].append(2)

    assert retrieval.fields == {
        "status": 200,
        "nested": {"values": [1]},
    }
    assert observation(retrievals=(retrieval,)).retrievals == (retrieval,)

    with pytest.raises(TypeError):
        Retrieval("a", "http", "resource", NOW, {1: "invalid"})

    with pytest.raises(ValueError):
        Retrieval("a", "http", "resource", datetime(2026, 1, 1), {})


def test_frozen():
    source = Source("web_publisher", "example.com")

    with pytest.raises(FrozenInstanceError):
        source.identifier = "other.example"


@pytest.mark.parametrize("value", [1, True, None])
def test_source_type(value):
    with pytest.raises(TypeError):
        Source("web_publisher", value)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("upstream_sources", []),
        ("cited_sources", []),
        ("parent_observation_ids", []),
        ("retrievals", []),
    ],
)
def test_tuple_type(field, value):
    with pytest.raises(TypeError):
        observation(**{field: value})


def test_timestamps():
    with pytest.raises(ValueError):
        observation(observed_at=datetime(2026, 1, 1))

    with pytest.raises(TypeError):
        observation(observed_at=None)

    item = observation(source_modified_at=None)

    assert item.source_modified_at is None


def test_metadata():
    metadata = {
        "owner_id": "team-a",
        "upstream_lineage_uri": "https://example.com/source",
        "custom_context": {"rank": 3},
    }

    item = observation(metadata=metadata)

    assert item.metadata == metadata

    metadata["custom_context"]["rank"] = 99

    assert item.metadata["custom_context"]["rank"] == 3


def test_dependency_signals():
    signals = {
        "upstream": 0.75,
        "retrieval": 1.0,
    }

    item = observation(dependency_signals=signals)

    assert item.dependency_signals == signals


def test_metadata_type():
    with pytest.raises(TypeError):
        observation(metadata=[])


def test_dependency_signals_type():
    with pytest.raises(TypeError):
        observation(dependency_signals=[])


def test_dependency_signal_names():
    with pytest.raises(TypeError):
        observation(dependency_signals={1: 0.5})

    with pytest.raises(TypeError):
        observation(dependency_signals={"": 0.5})


def test_value_snapshot():
    value = {"outer": [True, {"number": 1}]}
    item = Claim("service", "entity", "attribute", value)

    value["outer"].append("changed")
    returned = item.value
    returned["outer"].append("also changed")

    assert item.value == {"outer": [True, {"number": 1}]}


def test_value_identity():
    assert Claim("service", "e", "a", True) != Claim("service", "e", "a", 1)
    assert Claim("service", "e", "a", [["a", 1]]) != Claim(
        "service", "e", "a", {"a": 1}
    )
    assert Claim("service", "e", "a", {"a": 1, "b": 2}) == Claim(
        "service", "e", "a", {"b": 2, "a": 1}
    )


@pytest.mark.parametrize(
    "value",
    [9007199254740992, [{"nested": "secret-marker\ud800"}]],
)
def test_value_error(value):
    with pytest.raises(ValueError) as caught:
        Claim("service", "entity", "attribute", value)

    assert str(caught.value) == "claim value is invalid"
    assert "secret-marker" not in repr(caught.value)


def test_value_type_error():
    class SecretValue:
        def __repr__(self):
            return "secret-marker"

    with pytest.raises(TypeError) as caught:
        Claim("service", "entity", "attribute", [{"nested": SecretValue()}])

    assert str(caught.value) == "claim value must use exact JSON types"
    assert "secret-marker" not in repr(caught.value)


def test_repr():
    source = Source("web_publisher", "secret.example", "secret-owner")
    item = observation(
        observation_id="secret-assertion",
        source=source,
        claim=Claim(
            "service",
            "secret-entity",
            "secret-attribute",
            "secret-value",
        ),
        upstream_sources=(reference("secret-upstream"),),
        cited_sources=(reference("secret-citation"),),
        parent_observation_ids=("secret-parent",),
        retrievals=(
            Retrieval(
                "secret-retrieval",
                "http",
                "secret-resource",
                NOW,
            ),
        ),
        metadata={
            "secret_context": "secret-value",
        },
        dependency_signals={
            "upstream": 1.0,
        },
    )

    text = repr((source, item, item.cited_sources[0], item.retrievals[0]))

    assert "secret" not in text


def test_observation_helpers():
    from omneum import observe, reference, retrieval

    source = Source(
        "internal_service",
        "v1:01234567-89ab-4def-8123-456789abcdef:"
        "11111111-1111-4111-8111-111111111111",
    )

    upstream = reference(
        kind="external_service",
        identifier="example-upstream",
    )

    item = observe(
        observation_id="assertion-a",
        source=source,
        entity_namespace="service",
        entity="payment_api",
        attribute="status_code",
        value=200,
        observed_at=NOW,
        upstream_sources=(upstream,),
        retrievals=(
            retrieval(
                retrieval_id="retrieval-a",
                kind="tool_output",
                resource_id="get_payment_status",
                retrieved_at=NOW,
            ),
        ),
        metadata={
            "custom_context": "example",
        },
        dependency_signals={
            "upstream": 1.0,
        },
    )

    assert item.claim.attribute == "status_code"
    assert item.claim.value == 200
    assert item.upstream_sources == (upstream,)
    assert item.retrievals[0].resource_id == "get_payment_status"
    assert item.metadata["custom_context"] == "example"
    assert item.dependency_signals["upstream"] == 1.0


def test_reference_from_source():
    from omneum import reference

    source = Source(
        "internal_service",
        "v1:01234567-89ab-4def-8123-456789abcdef:"
        "11111111-1111-4111-8111-111111111111",
    )

    assert reference(source) == SourceReference(
        source.kind,
        source.identifier,
    )

def test_legacy_observation_names():
    from dataclasses import replace
    from omneum.information import AssertionSource, StructuredAssertion

    item = Observation(
        assertion_id="child", source=Source("web_publisher", "example.com"),
        claim=claim(), observed_at=NOW, parent_assertion_ids=("parent",),
    )
    assert item.observation_id == item.assertion_id == "child"
    assert item.parent_observation_ids == item.parent_assertion_ids == ("parent",)
    assert replace(item, observation_id="renamed").assertion_id == "renamed"
    legacy = AssertionSource(item.source, item.assertion_id, NOW)
    assert StructuredAssertion("service", "entity", "status", "active", (legacy,)).sources == (legacy,)


@pytest.mark.parametrize("changes", [
    {"assertion_id": "other"},
    {"parent_observation_ids": ("one",), "parent_assertion_ids": ("two",)},
])
def test_conflicting_observation_aliases(changes):
    with pytest.raises(ValueError, match="disagree"):
        observation(**changes)


def test_legacy_observe_helper():
    from omneum.observations import observe

    item = observe(
        assertion_id="legacy", source=Source("web_publisher", "example.com"),
        entity_namespace="service", entity="entity", attribute="status",
        value="active", observed_at=NOW, parent_assertion_ids=(),
    )
    assert item.observation_id == "legacy"
    assert item.parent_observation_ids == ()
