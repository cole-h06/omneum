from dataclasses import FrozenInstanceError
from datetime import datetime, timezone

import pytest

from verity.information import Claim, Observation, Source, SourceReference


def reference(identifier="a"):
    return SourceReference("web_publisher", identifier)


def claim(value="value"):
    return Claim("service", "Entity", "Attribute", value)


def test_models():
    source = Source("web_publisher", "example.com", "owner")
    observation = Observation(
        "assertion-a",
        Source("web_publisher", "example.com"),
        claim(),
        datetime(2026, 1, 1, tzinfo=timezone.utc),
        (),
        (),
        (),
    )

    assert source.owner_id == "owner"
    assert observation.provenance_ids == ()


def test_frozen():
    source = Source("web_publisher", "example.com")

    with pytest.raises(FrozenInstanceError):
        source.identifier = "other.example"


@pytest.mark.parametrize("value", [1, True, None])
def test_source_type(value):
    with pytest.raises(TypeError):
        Source("web_publisher", value)


def test_tuple_type():
    with pytest.raises(TypeError):
        Observation("a", Source("web_publisher", "a"), claim(), None, [])


def test_timestamp():
    with pytest.raises(ValueError):
        Observation("a", Source("web_publisher", "a"), claim(), datetime(2026, 1, 1), ())


def test_missing_timestamp():
    observation = Observation(
        "a", Source("web_publisher", "a"), claim(), None, None, None, None
    )

    assert observation.source_timestamp is None
    assert observation.provenance_ids is None


def test_value_snapshot():
    value = {"outer": [True, {"number": 1}]}
    item = Claim("service", "entity", "attribute", value)

    value["outer"].append("changed")
    returned = item.value
    returned["outer"].append("also changed")

    assert item.value == {"outer": [True, {"number": 1}]}


def test_value_identity():
    assert Claim("service", "e", "a", True) != Claim(
        "service", "e", "a", 1
    )
    assert Claim("service", "e", "a", [["a", 1]]) != Claim(
        "service", "e", "a", {"a": 1}
    )
    assert Claim("service", "e", "a", {"a": 1, "b": 2}) == Claim(
        "service", "e", "a", {"b": 2, "a": 1}
    )


@pytest.mark.parametrize(
    "value",
    [
        9007199254740992,
        [{"nested": "secret-marker\ud800"}],
    ],
)
def test_value_error(value):
    with pytest.raises(ValueError) as caught:
        Claim("service", "entity", "attribute", value)

    assert str(caught.value) == "claim value is invalid"
    assert repr(caught.value) == "ValueError('claim value is invalid')"
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
    item = Claim("service", "secret-entity", "secret-attribute", "secret-value")
    value = Observation(
        "secret-assertion",
        source,
        item,
        datetime(2026, 1, 1, tzinfo=timezone.utc),
        ("secret-provenance",),
        (SourceReference("web_publisher", "secret-citation"),),
        ("secret-parent",),
    )

    text = repr((source, item, value, value.cited_sources[0]))
    assert "secret" not in text
