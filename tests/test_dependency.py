import json

from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import verity.dependency as dependency
from verity.dependency import (
    DependencyEvidence,
    DependencyEstimatorConfig,
    DependencySignalScores,
    InformationGraphError,
    PairwiseDependencyResult,
    combine_dependency,
    estimate_dependencies,
)
from verity.information import Claim, Observation, Source, SourceReference


NOW = datetime(2026, 2, 2, 12, tzinfo=timezone.utc)
VECTOR = Path(__file__).parent / "vectors" / "dependency_estimator_v1.json"
WEIGHTS = {
    "upstream_weight": 0.25,
    "citation_weight": 0.20,
    "assertion_lineage_weight": 0.20,
    "ownership_weight": 0.10,
    "temporal_weight": 0.10,
    "graph_weight": 0.15,
}


def config(**changes):
    values = {**WEIGHTS, "temporal_window_seconds": 7200.0}
    values.update(changes)
    return DependencyEstimatorConfig(**values)


def source(identifier, owner=None):
    return Source("web_publisher", f"https://{identifier}", owner)


def reference(identifier):
    return SourceReference("web_publisher", f"https://{identifier}")


def observation(assertion_id, source_id, attribute="status", value="active", **changes):
    values = {
        "assertion_id": assertion_id,
        "source": source(source_id),
        "claim": Claim("service", "Entity", attribute, value),
        "observed_at": NOW,
        "source_modified_at": NOW,
        "upstream_sources": (),
        "cited_sources": (),
        "parent_assertion_ids": (),
        "retrievals": (),
    }
    values.update(changes)
    return Observation(**values)


def pair(observations, sources=None, values=None):
    if sources is None:
        sources = tuple(dict.fromkeys(item.source for item in observations))
    results, _ = estimate_dependencies(tuple(sources), tuple(observations), values or config())
    return results[0]


def empty_signals(**changes):
    values = {
        name: 0.0 for name in dependency.SIGNALS
    } | {
        f"{name}_observable": True for name in dependency.SIGNALS
    }
    values.update(changes)
    return DependencySignalScores(**values)


def vector_observation(item, sources):
    return Observation(
        assertion_id=item["assertion_id"],
        source=sources[item["source_id"]],
        claim=Claim("service", "Entity", item["attribute"], item["value"]),
        observed_at=datetime.fromisoformat(item["observed_at"]),
        source_modified_at=(
            datetime.fromisoformat(item["source_modified_at"])
            if item["source_modified_at"] is not None
            else None
        ),
        upstream_sources=(
            tuple(reference(value) for value in item["upstream_source_ids"])
            if item["upstream_source_ids"] is not None
            else None
        ),
        cited_sources=(
            tuple(reference(value) for value in item["cited_source_ids"])
            if item["cited_source_ids"] is not None
            else None
        ),
        parent_assertion_ids=(
            tuple(item["parent_assertion_ids"])
            if item["parent_assertion_ids"] is not None
            else None
        ),
        retrievals=(),
    )


def test_vectors():
    vector = json.loads(VECTOR.read_text())
    assert vector["estimator_version"] == "dependency-estimator-v1"
    assert tuple(vector["signal_order"]) == dependency.SIGNALS
    assert vector["output_comparison"] == {
        "mode": "exact_binary64",
        "tolerance": None,
    }

    for case in vector["weight_cases"]:
        values = {
            f"{name}_weight": value
            for name, value in zip(dependency.SIGNALS, case["supplied"])
        }
        values["temporal_window_seconds"] = 7200.0
        assert dependency._weights(DependencyEstimatorConfig(**values)) == tuple(
            case["expected"]
        )

    for case in vector["combine_cases"]:
        values = dict(zip(dependency.SIGNALS, case["scores"]))
        values.update(
            (f"{name}_observable", value)
            for name, value in zip(dependency.SIGNALS, case["observability"])
        )
        assert combine_dependency(DependencySignalScores(**values), config()) == (
            case["expected_dependency"],
            case["expected_weighted_signal_coverage"],
        )

    for case in vector["pair_cases"]:
        sources = {
            item["id"]: source(item["id"], item["owner_id"])
            for item in case["sources"]
        }
        observations = tuple(
            vector_observation(item, sources)
            for item in case["observations"]
        )
        result = pair(observations, tuple(sources.values()))
        assert tuple(getattr(result.signals, name) for name in dependency.SIGNALS) == tuple(
            case["expected_signals"]
        )
        assert tuple(
            getattr(result.signals, f"{name}_observable")
            for name in dependency.SIGNALS
        ) == tuple(case["expected_observability"])
        assert result.dependency == case["expected_dependency"]
        assert result.weighted_signal_coverage == case[
            "expected_weighted_signal_coverage"
        ]
        if "expected_evidence" in case:
            expected = dict(case["expected_evidence"])
            expected["qualifying_time_deltas_seconds"] = tuple(
                expected["qualifying_time_deltas_seconds"]
            )
            assert asdict(result.evidence) == expected

    case = vector["matrix_case"]
    source_map = {
        value: source(value, f"owner-{value}")
        for value in case["sources"]
    }
    sources = tuple(source_map.values())
    observations = tuple(
        observation(
            f"{value}1",
            value,
            attribute=value,
            value=value,
            source=source_map[value],
        )
        for value in case["sources"]
    )
    results, _ = estimate_dependencies(sources, observations, config())
    assert [
        [result.source_a.identifier, result.source_b.identifier]
        for result in results
    ] == case["expected_pairs"]
    assert [result.dependency for result in results] == case["expected_dependencies"]
    assert [result.weighted_signal_coverage for result in results] == case[
        "expected_weighted_signal_coverages"
    ]

    case = vector["cluster_case"]
    keys = tuple(("web_publisher", value) for value in case["sources"])
    results = tuple(
        PairwiseDependencyResult(
            SourceReference("web_publisher", item["source_a"]),
            SourceReference("web_publisher", item["source_b"]),
            empty_signals(),
            item["dependency"],
            1.0,
        )
        for item in case["dependencies"]
    )
    clusters = dependency._clusters(keys, results, case["threshold"])
    assert [
        [source.identifier for source in cluster.sources]
        for cluster in clusters
    ] == case["expected_components"]


def test_pair_and_graph_signal():
    sources = (source("b.example", "owner"), source("a.example", "owner"))
    observations = (
        observation("b1", "b.example"),
        observation("a1", "a.example"),
    )
    results, clusters = estimate_dependencies(sources, observations, config())
    result = results[0]
    assert (result.source_a.identifier, result.source_b.identifier) == (
        "a.example", "b.example"
    )
    assert result.signals.graph == 0.5
    assert result.signals.ownership == 1.0
    assert result.weighted_signal_coverage == 1.0
    assert clusters == ()


def test_six_independent_signals():
    a = source("a.example", "owner")
    b = source("b.example", "owner")
    observations = (
        observation(
            "a1", "a.example",
            source=a,
            source_modified_at=NOW,
            upstream_sources=(reference("b.example"),),
            cited_sources=(reference("b.example"),),
            parent_assertion_ids=("b1",),
        ),
        observation(
            "b1", "b.example", source=b,
            source_modified_at=NOW - timedelta(hours=1),
        ),
    )
    result = pair(observations, (a, b))
    assert result.signals == DependencySignalScores(
        upstream=1.0, citation=1.0, assertion_lineage=1.0,
        ownership=1.0, temporal=1.0, graph=0.5,
        upstream_observable=True, citation_observable=True,
        assertion_lineage_observable=True, ownership_observable=True,
        temporal_observable=True, graph_observable=True,
    )
    assert result.evidence == DependencyEvidence(
        source_a_upstream_of_source_b=False,
        source_b_upstream_of_source_a=True,
        source_a_cites_source_b=True,
        source_b_cites_source_a=False,
        source_a_parent_count=1,
        source_b_parent_count=0,
        same_owner=True,
        matching_claim_count=1,
        qualifying_time_deltas_seconds=(3600.0,),
    )


def test_signal_missingness_and_coverage():
    result = pair((
        observation("a1", "a.example", source_modified_at=None,
                    upstream_sources=None, cited_sources=None,
                    parent_assertion_ids=None),
        observation("b1", "b.example", source_modified_at=None,
                    upstream_sources=None, cited_sources=None,
                    parent_assertion_ids=None),
    ))
    assert not result.signals.upstream_observable
    assert not result.signals.citation_observable
    assert not result.signals.assertion_lineage_observable
    assert not result.signals.ownership_observable
    assert not result.signals.temporal_observable
    assert result.signals.graph_observable
    assert result.weighted_signal_coverage == pytest.approx(0.15)


def test_observed_at_and_retrieval_time_do_not_drive_temporal():
    result = pair((
        observation("a1", "a.example", observed_at=NOW,
                    source_modified_at=None),
        observation("b1", "b.example", observed_at=NOW - timedelta(hours=1),
                    source_modified_at=None),
    ))
    assert result.signals.temporal == 0.0
    assert not result.signals.temporal_observable


def test_pair_constructor_and_evidence_validation():
    signals = empty_signals()
    a = SourceReference("web_publisher", "a.example")
    b = SourceReference("web_publisher", "b.example")
    assert PairwiseDependencyResult(a, b, signals, 0.0, 1.0).source_a == a
    with pytest.raises(ValueError):
        PairwiseDependencyResult(a, a, signals, 0.0, 1.0)
    with pytest.raises(ValueError):
        PairwiseDependencyResult(b, a, signals, 0.0, 1.0)
    with pytest.raises(TypeError):
        DependencyEvidence(1, False, False, False, 0, 0, False, 0, ())
    with pytest.raises(ValueError):
        DependencyEvidence(False, False, False, False, -1, 0, False, 0, ())


def test_weight_normalization_and_combination():
    values = DependencyEstimatorConfig(
        upstream_weight=25.0, citation_weight=20.0,
        assertion_lineage_weight=20.0, ownership_weight=10.0,
        temporal_weight=10.0, graph_weight=15.0,
        temporal_window_seconds=7200.0,
    )
    assert dependency._weights(values) == (0.25, 0.2, 0.2, 0.1, 0.1, 0.15)
    signals = empty_signals(
        upstream=1.0, citation=1.0, assertion_lineage=1.0,
        ownership=1.0, temporal=1.0, graph=0.5,
    )
    assert combine_dependency(signals, values) == (0.925, 1.0)


@pytest.mark.parametrize("threshold", [0.0, 1.0])
def test_threshold(threshold):
    assert config(dependency_cluster_threshold=threshold).dependency_cluster_threshold == threshold


@pytest.mark.parametrize("threshold", [-0.1, 1.1, float("nan"), 1])
def test_bad_threshold(threshold):
    with pytest.raises((TypeError, ValueError)):
        config(dependency_cluster_threshold=threshold)


def test_clusters_are_deterministic():
    sources = tuple(source(f"{name}.example") for name in "abc")
    observations = tuple(observation(f"{name}1", f"{name}.example") for name in "abc")
    _, clusters = estimate_dependencies(
        sources, observations, config(dependency_cluster_threshold=0.04)
    )
    assert tuple(item.identifier for item in clusters[0].sources) == (
        "a.example", "b.example", "c.example"
    )


@pytest.mark.parametrize(
    "change,match",
    [
        ({"upstream_sources": (reference("missing.example"),)}, "upstream source is unknown"),
        ({"cited_sources": (reference("missing.example"),)}, "cited source is unknown"),
        ({"parent_assertion_ids": ("missing",)}, "parent assertion is unknown"),
    ],
)
def test_unknown_relationships(change, match):
    with pytest.raises(InformationGraphError, match=match):
        pair((observation("a1", "a.example", **change), observation("b1", "b.example")))


def test_duplicate_and_canonical_source_validation():
    a = source("a.example")
    with pytest.raises(InformationGraphError, match="duplicate assertion ID"):
        estimate_dependencies((a,), (
            observation("a1", "a.example", attribute="one"),
            observation("a1", "a.example", attribute="two"),
        ), config())
    with pytest.raises(InformationGraphError, match="conflicting owners"):
        estimate_dependencies(
            (source("A.example", "one"), source("a.example", "two")),
            (observation("a1", "a.example"),), config()
        )
