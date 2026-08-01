import pytest

from verity.engine_graph import (
    AssertionTriple,
    GraphError,
    SourcePair,
    build_graph,
)


def assertions():
    return [
        AssertionTriple("source-b", "attribute-a", "claim-a"),
        AssertionTriple("source-a", "attribute-b", "claim-b"),
        AssertionTriple("source-a", "attribute-a", "claim-a"),
    ]


def pairs():
    return [
        SourcePair("source-a", "source-b", 0.0, 0.0),
    ]


def test_graph():
    graph = build_graph(assertions(), pairs())

    assert graph.sources == ("source-a", "source-b")
    assert graph.attributes == ("attribute-a", "attribute-b")
    assert graph.claims == ("claim-a", "claim-b")
    assert graph.source_to_claims == {
        "source-a": ("claim-a", "claim-b"),
        "source-b": ("claim-a",),
    }
    assert graph.claim_to_sources == {
        "claim-a": ("source-a", "source-b"),
        "claim-b": ("source-a",),
    }
    assert graph.claim_to_attribute == {
        "claim-a": "attribute-a",
        "claim-b": "attribute-b",
    }
    assert graph.attribute_to_claims == {
        "attribute-a": ("claim-a",),
        "attribute-b": ("claim-b",),
    }
    assert graph.source_degree == {
        "source-a": 2,
        "source-b": 1,
    }
    assert graph.source_pairs[
        ("source-a", "source-b")
    ].dependency == 0.0
    assert graph.source_pairs[
        ("source-a", "source-b")
    ].weighted_signal_coverage == 0.0
    assert graph.assertion_count == 3


def test_empty():
    with pytest.raises(GraphError):
        build_graph([], [])


def test_duplicate_assertion():
    values = assertions()
    with pytest.raises(GraphError):
        build_graph([*values, values[0]], pairs())


def test_claim_attribute():
    values = [
        AssertionTriple("source-a", "attribute-a", "claim-a"),
        AssertionTriple("source-b", "attribute-b", "claim-a"),
    ]
    with pytest.raises(GraphError):
        build_graph(values, pairs())


def test_source_attribute():
    values = [
        AssertionTriple("source-a", "attribute-a", "claim-a"),
        AssertionTriple("source-a", "attribute-a", "claim-b"),
    ]
    with pytest.raises(GraphError):
        build_graph(values, [])


def test_missing_pair():
    with pytest.raises(GraphError):
        build_graph(assertions(), [])


def test_duplicate_pair():
    values = pairs()
    with pytest.raises(GraphError):
        build_graph(assertions(), [*values, values[0]])


def test_reversed_pair():
    values = [
        SourcePair("source-b", "source-a", 0.0, 0.0),
    ]
    with pytest.raises(GraphError):
        build_graph(assertions(), values)


def test_diagonal_pair():
    values = [
        SourcePair("source-a", "source-a", 0.0, 0.0),
    ]
    with pytest.raises(GraphError):
        build_graph(assertions(), values)


def test_unknown_pair():
    values = [
        SourcePair("source-a", "source-c", 0.0, 0.0),
    ]
    with pytest.raises(GraphError):
        build_graph(assertions(), values)


@pytest.mark.parametrize(
    "value",
    [-0.1, 1.1, float("inf"), float("nan"), True, "0.5"],
)
def test_pair_range(value):
    values = [
        SourcePair("source-a", "source-b", value, 0.0),
    ]
    with pytest.raises(GraphError):
        build_graph(assertions(), values)


def test_pair_coverage():
    values = [
        SourcePair("source-a", "source-b", 0.0, 1.1),
    ]
    with pytest.raises(GraphError):
        build_graph(assertions(), values)


def test_identifier():
    values = [
        AssertionTriple("", "attribute-a", "claim-a"),
    ]
    with pytest.raises(GraphError):
        build_graph(values, [])
