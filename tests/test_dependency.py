import json

from datetime import datetime, timezone
from pathlib import Path

import pytest

import verity.dependency as dependency
from verity.dependency import (
    DependencyCluster,
    DependencyEstimatorConfig,
    DependencySignalScores,
    InformationGraphError,
    PairwiseDependencyResult,
    combine_dependency,
    estimate_dependencies,
)
from verity.information import Claim, Observation, Source, SourceReference


VECTOR = Path(__file__).parent / "vectors" / "dependency_estimator_v1.json"
WEIGHTS = {
    "provenance_weight": 0.25,
    "lineage_weight": 0.3,
    "ownership_weight": 0.15,
    "temporal_weight": 0.15,
    "structural_weight": 0.15,
}


def config(**values):
    return DependencyEstimatorConfig(
        **WEIGHTS,
        temporal_window_seconds=values.pop("temporal_window_seconds", 7200.0),
        **values,
    )


def source(identifier, owner=None):
    return Source("web_publisher", f"https://{identifier}", owner)


def reference(identifier):
    return SourceReference("web_publisher", f"https://{identifier}")


def observation(
    assertion_id,
    source_id,
    attribute="status",
    value="active",
    timestamp=datetime(2026, 2, 2, 11, tzinfo=timezone.utc),
    provenance=(),
    cited=(),
    parents=(),
):
    return Observation(
        assertion_id,
        reference(source_id),
        Claim("service", "Entity", attribute, value),
        timestamp,
        provenance,
        tuple(reference(value) for value in cited) if cited is not None else None,
        parents,
    )


def test_pair():
    sources = (source("b.example", "owner"), source("a.example", "owner"))
    observations = (
        observation("b1", "b.example", provenance=("p",)),
        observation("a1", "a.example", provenance=("p",)),
    )

    pairs, clusters = estimate_dependencies(sources, observations, config())

    assert pairs[0].source_a.identifier == "a.example"
    assert pairs[0].source_b.identifier == "b.example"
    assert pairs[0].signals.provenance == 1.0
    assert pairs[0].signals.temporal == 0.0
    assert pairs[0].weighted_signal_coverage == 1.0
    assert clusters == ()


def test_lineage():
    sources = (source("a.example", "owner"), source("b.example", "owner"))
    observations = (
        observation("a1", "a.example", cited=("b.example",)),
        observation("b1", "b.example"),
    )

    pairs, _ = estimate_dependencies(sources, observations, config())

    assert pairs[0].signals.lineage == 1.0
    assert pairs[0].signals.lineage_observable


def test_parent():
    sources = (source("a.example"), source("b.example"))
    observations = (
        observation("a1", "a.example", parents=("b1",)),
        observation("b1", "b.example"),
    )

    pairs, _ = estimate_dependencies(sources, observations, config())

    assert pairs[0].signals.lineage == 1.0


def test_temporal_missing():
    sources = (source("a.example", "owner"), source("b.example", "owner"))
    observations = (
        observation("a1", "a.example", timestamp=None),
        observation("b1", "b.example"),
    )

    pairs, _ = estimate_dependencies(sources, observations, config())

    assert pairs[0].signals.temporal == 0.0
    assert not pairs[0].signals.temporal_observable
    assert pairs[0].weighted_signal_coverage == 0.85


def test_temporal_unrelated():
    sources = (source("a.example"), source("b.example"))
    observations = (
        observation("a1", "a.example"),
        observation("a2", "a.example", "other", timestamp=None),
        observation("b1", "b.example"),
        observation("b2", "b.example", "different", timestamp=None),
    )

    pairs, _ = estimate_dependencies(sources, observations, config())

    assert pairs[0].signals.temporal_observable


def test_cluster():
    sources = (
        source("a.example"),
        source("b.example"),
        source("c.example"),
    )
    observations = tuple(
        observation(f"{name}1", f"{name}.example", provenance=("p",))
        for name in ("a", "b", "c")
    )

    _, clusters = estimate_dependencies(
        sources,
        observations,
        config(dependency_cluster_threshold=0.25),
    )

    assert clusters[0].threshold == 0.25
    assert tuple(value.identifier for value in clusters[0].sources) == (
        "a.example",
        "b.example",
        "c.example",
    )


@pytest.mark.parametrize("threshold", [0.0, 1.0])
def test_threshold(threshold):
    assert config(dependency_cluster_threshold=threshold).dependency_cluster_threshold == threshold


@pytest.mark.parametrize("threshold", [-0.1, 1.1, float("nan"), 1])
def test_bad_threshold(threshold):
    with pytest.raises((TypeError, ValueError)):
        config(dependency_cluster_threshold=threshold)


def test_ratio_weights():
    values = DependencyEstimatorConfig(25.0, 30.0, 15.0, 15.0, 15.0, 7200.0)
    signals = DependencySignalScores(
        1.0, 1.0, 1.0, 1.0, 0.5, True, True, True, True, True
    )

    assert combine_dependency(signals, values) == (0.9249999999999999, 1.0)


def test_vectors():
    vector = json.loads(VECTOR.read_text())
    for case in vector["cases"]:
        VECTOR_OPERATIONS[case["operation"]](case, vector)

    for pair in vector["enterprise_complete_matrix"]["pairs"]:
        scores = DependencySignalScores(
            *(pair["signals"][name] for name in vector["signal_order"]),
            *(bool(pair["observability"][name]) for name in vector["signal_order"]),
        )
        result = combine_dependency(scores, config())
        assert result == (
            pair["dependency"],
            pair["weighted_signal_coverage"],
        )


def _pair(sources, observations, values=None):
    pairs, _ = estimate_dependencies(
        tuple(sources),
        tuple(observations),
        values or config(),
    )
    return pairs[0]


def _provenance(case, vector):
    if "source_a_observations" in case:
        a_values = [item["provenance_ids"] for item in case["source_a_observations"]]
        b_values = [item["provenance_ids"] for item in case["source_b_observations"]]
    else:
        a_values = [case["source_a_ids"]]
        b_values = [case["source_b_ids"]]
    observations = [
        observation(f"a{index}", "a.example", f"a{index}", provenance=None if value is None else tuple(value))
        for index, value in enumerate(a_values)
    ] + [
        observation(f"b{index}", "b.example", f"b{index}", provenance=None if value is None else tuple(value))
        for index, value in enumerate(b_values)
    ]
    result = _pair(
        (source("a.example"), source("b.example")),
        observations,
    ).signals
    assert result.provenance == case.get("expected_score", case.get("expected_pair_score"))
    if "expected_observable" in case or "expected_pair_observable" in case:
        assert result.provenance_observable == bool(
            case.get("expected_observable", case.get("expected_pair_observable"))
        )


def _lineage_case(case, vector):
    a_to_b = case["a_to_b"]
    b_to_a = case["b_to_a"]
    observations = (
        observation(
            "a1",
            "a.example",
            cited=("b.example",) if a_to_b else (),
        ),
        observation(
            "b1",
            "b.example",
            cited=("a.example",) if b_to_a else None,
            parents=() if b_to_a else None,
        ),
    )
    result = _pair(
        (source("a.example"), source("b.example")),
        observations,
    ).signals
    assert result.lineage == case["expected_score"]
    assert result.lineage_observable == bool(
        case["expected_observable_with_missing_reverse_capture"]
    )


def _lineage_evidence(case, vector):
    rows = {item["assertion_id"]: item for item in case["evidence"]}
    observations = []
    for item in case["assertions"]:
        evidence = rows[item["assertion_id"]]
        observations.append(observation(
            item["assertion_id"],
            f'{item["source_id"]}.example',
            cited=None if evidence["cited_source_ids"] is None else tuple(
                f"{value}.example" for value in evidence["cited_source_ids"]
            ),
            parents=None if evidence["parent_assertion_ids"] is None else tuple(
                evidence["parent_assertion_ids"]
            ),
        ))
    result = _pair(
        tuple(source(f"{value}.example") for value in case["source_ids"]),
        observations,
    ).signals
    assert result.lineage == case["expected_score"]
    assert result.lineage_observable == bool(case["expected_observable"])


def _ownership(case, vector):
    result = _pair(
        (
            source("a.example", case["source_a_owner_id"]),
            source("b.example", case["source_b_owner_id"]),
        ),
        (observation("a1", "a.example"), observation("b1", "b.example")),
    ).signals
    assert result.ownership == case["expected_score"]
    assert result.ownership_observable == bool(case["expected_observable"])


def _timestamp(value):
    if value is None:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _temporal(case, vector):
    observations = []
    if "matching_properties" in case:
        for index, item in enumerate(case["matching_properties"]):
            observations.extend((
                observation(
                    f"a{index}", "a.example", f"p{index}",
                    timestamp=_timestamp(item["child_observed_at"]),
                ),
                observation(
                    f"b{index}", "b.example", f"p{index}",
                    timestamp=_timestamp(item["parent_observed_at"]),
                ),
            ))
    else:
        for label, source_id in (("a", "a.example"), ("b", "b.example")):
            for index, item in enumerate(case[f"source_{label}_observations"]):
                observations.append(observation(
                    f"{label}{index}", source_id, item["property"], item["value"],
                    timestamp=_timestamp(item["observed_at"]),
                ))
    result = _pair(
        (source("a.example"), source("b.example")),
        observations,
        config(temporal_window_seconds=case["temporal_window_seconds"]),
    ).signals
    assert result.temporal == case["expected_score"]
    assert result.temporal_observable == bool(case["expected_observable"])


def _temporal_missingness(case, vector):
    observations = []
    for index, item in enumerate(case["matching_properties"]):
        observations.extend((
            observation(
                f"a{index}", "a.example", f"p{index}",
                timestamp=_timestamp(item["source_a_observed_at"]),
            ),
            observation(
                f"b{index}", "b.example", f"p{index}",
                timestamp=_timestamp(item["source_b_observed_at"]),
            ),
        ))
    for index, item in enumerate(case["unrelated_observations"]):
        source_id = f'{item["source"]}.example'
        observations.append(observation(
            f'u{item["source"]}{index}', source_id, f"u{index}",
            value=item["reason"], timestamp=_timestamp(item["observed_at"]),
        ))
    result = _pair(
        (source("a.example", "owner"), source("b.example", "owner")),
        observations,
        config(temporal_window_seconds=case["temporal_window_seconds"]),
    )
    assert result.signals.temporal == case["expected_temporal_score"]
    assert result.signals.temporal_observable == bool(case["expected_temporal_observable"])
    scores = DependencySignalScores(
        case["other_signal_scores"],
        case["other_signal_scores"],
        case["other_signal_scores"],
        result.signals.temporal,
        case["other_signal_scores"],
        bool(case["other_signals_observable"]),
        bool(case["other_signals_observable"]),
        bool(case["other_signals_observable"]),
        result.signals.temporal_observable,
        bool(case["other_signals_observable"]),
    )
    values = case["normalized_weights"]
    assert combine_dependency(
        scores,
        DependencyEstimatorConfig(
            *(values[name] for name in vector["signal_order"]),
            case["temporal_window_seconds"],
        ),
    ) == (
        case["expected_dependency"],
        case["expected_weighted_signal_coverage"],
    )


def _structural(case, vector):
    sources = tuple(source(f"{name}.example") for name in case["source_assertions"])
    observations = []
    for name, assertions in case["source_assertions"].items():
        observations.extend(
            observation(f"{name}{index}", f"{name}.example", prop, value)
            for index, (prop, value) in enumerate(assertions.items())
        )
    pairs, _ = estimate_dependencies(sources, tuple(observations), config())
    result = next(
        pair for pair in pairs
        if pair.source_a.identifier == f'{case["source_a"]}.example'
        and pair.source_b.identifier == f'{case["source_b"]}.example'
    )
    assert result.signals.structural == case["expected_score"]
    assert result.signals.structural_observable == bool(case["expected_observable"])


def _weight_case(case, vector):
    supplied = case["supplied"]
    values = DependencyEstimatorConfig(
        *(supplied[name] for name in vector["signal_order"]),
        7200.0,
    )
    assert dependency._weights(values) == tuple(
        case["expected_normalized"][name] for name in vector["signal_order"]
    )


def _combine(case, vector):
    scores = DependencySignalScores(
        *(case["signals"][name] for name in vector["signal_order"]),
        *(bool(case["observability"][name]) for name in vector["signal_order"]),
    )
    values = case["normalized_weights"]
    assert combine_dependency(
        scores,
        DependencyEstimatorConfig(
            *(values[name] for name in vector["signal_order"]),
            7200.0,
        ),
    ) == (
        case["expected_dependency"],
        case["expected_weighted_signal_coverage"],
    )


def _matrix(case, vector):
    sources = tuple(source(f"{name}.example") for name in ("a", "b", "c"))
    observations = tuple(
        observation(f"{name}1", f"{name}.example")
        for name in ("a", "b", "c")
    )
    pairs, _ = estimate_dependencies(sources, observations, config())
    reversed_pairs, _ = estimate_dependencies(
        tuple(reversed(sources)),
        tuple(reversed(observations)),
        config(),
    )
    keys = {(pair.source_a.identifier, pair.source_b.identifier) for pair in pairs}
    assert len(keys) == 3
    assert all(source_a != source_b for source_a, source_b in keys)
    assert (pairs == reversed_pairs) == case["expected_symmetric"]
    assert all(source_a != source_b for source_a, source_b in keys) == case[
        "expected_zero_diagonal"
    ]


def _cluster_case(case, vector):
    keys = tuple(("web_publisher", value) for value in case["sources"])
    empty = DependencySignalScores(
        0.0, 0.0, 0.0, 0.0, 0.0,
        False, False, False, False, False,
    )
    results = tuple(
        PairwiseDependencyResult(
            SourceReference("web_publisher", item["source_a"]),
            SourceReference("web_publisher", item["source_b"]),
            empty,
            item["dependency"],
            0.0,
        )
        for item in case["dependencies"]
    )
    clusters = dependency._clusters(keys, results, case["threshold"])
    assert [
        [source.identifier for source in cluster.sources]
        for cluster in clusters
    ] == case["expected_components"]
    assert all(type(cluster) is DependencyCluster for cluster in clusters)


VECTOR_OPERATIONS = {
    "provenance": _provenance,
    "provenance_capture": _provenance,
    "lineage": _lineage_case,
    "lineage_evidence": _lineage_evidence,
    "ownership": _ownership,
    "temporal": _temporal,
    "temporal_missingness": _temporal_missingness,
    "structural": _structural,
    "weights": _weight_case,
    "combine": _combine,
    "matrix_invariants": _matrix,
    "clusters": _cluster_case,
}


def test_duplicate_id():
    sources = (source("a.example"), source("b.example"))
    observations = (
        observation("same", "a.example"),
        observation("same", "b.example"),
    )

    with pytest.raises(InformationGraphError):
        estimate_dependencies(sources, observations, config())


def test_unknown_citation():
    sources = (source("a.example"),)
    observations = (observation("a1", "a.example", cited=("b.example",)),)

    with pytest.raises(InformationGraphError):
        estimate_dependencies(sources, observations, config())


def test_self_reference():
    sources = (source("a.example"),)
    observations = (observation("a1", "a.example", cited=("a.example",)),)

    with pytest.raises(InformationGraphError):
        estimate_dependencies(sources, observations, config())


def test_canonical_source():
    sources = (
        source("EXAMPLE.com", "owner-a"),
        source("example.com", "owner-b"),
    )
    observations = (observation("a1", "example.com"),)

    with pytest.raises(InformationGraphError):
        estimate_dependencies(sources, observations, config())


def test_input_unchanged():
    sources = (source("a.example"), source("b.example"))
    observations = (
        observation("a1", "a.example"),
        observation("b1", "b.example"),
    )

    estimate_dependencies(sources, observations, config())

    assert sources[0].identifier == "https://a.example"
    assert observations[0].claim.entity == "Entity"
