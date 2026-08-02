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
        reference("example.com"),
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
        Observation("a", reference(), claim(), None, [])


def test_timestamp():
    with pytest.raises(ValueError):
        Observation("a", reference(), claim(), datetime(2026, 1, 1), ())


def test_missing_timestamp():
    observation = Observation("a", reference(), claim(), None, None, None, None)

    assert observation.source_timestamp is None
    assert observation.provenance_ids is None

