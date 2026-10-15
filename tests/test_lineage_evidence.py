import json
from dataclasses import replace
from datetime import datetime
from pathlib import Path

import pytest

from omneum.dependency import (
    SIGNALS, DependencyEstimatorConfig, combine_dependency, estimate_dependencies,
)
from omneum.information import Claim, Observation, Source, SourceReference
from omneum.models import SourcePair
from test_dependency import config, empty_signals, observation, pair


def enterprise_pairs():
    fixture = json.loads((Path(__file__).parent / "vectors"
                         / "enterprise_stdio_assertion_evaluation_v3.json").read_text())
    sources = {
        item["name"]: Source(item["kind"], item["identifier"], item["owner_id"])
        for item in fixture["sources"]
    }
    references = {name: SourceReference(source.kind, source.identifier)
                  for name, source in sources.items()}
    rows = tuple(
        Observation(
            observation_id=item["assertion_id"], source=sources[item["source"]],
            claim=Claim(item["entity_namespace"], item["entity"],
                        item["attribute"], item["value"]),
            observed_at=datetime.fromisoformat(item["observed_at"]),
            source_modified_at=datetime.fromisoformat(item["source_modified_at"]),
            upstream_sources=tuple(references[name] for name in item["upstream_sources"]),
            cited_sources=tuple(references[name] for name in item["cited_sources"]),
            parent_observation_ids=tuple(item["parent_assertion_ids"]), retrievals=(),
        )
        for item in fixture["observations"]
    )
    estimator = DependencyEstimatorConfig(**fixture["estimator"])
    results, _ = estimate_dependencies(tuple(sources.values()), rows, estimator)
    names = {source.identifier: name for name, source in sources.items()}
    return {
        frozenset((names[result.source_a.identifier], names[result.source_b.identifier])): result
        for result in results
    }, estimator


def test_enterprise_dependency_evidence():
    pairs, estimator = enterprise_pairs()
    manual_portal = pairs[frozenset(("policy_manual", "support_portal"))]
    store_portal = pairs[frozenset(("orders_store", "support_portal"))]
    manual_store = pairs[frozenset(("policy_manual", "orders_store"))]

    assert manual_portal.evidence.source_b_cites_source_a
    assert manual_portal.signals.citation == 1.0
    assert manual_portal.signals.ownership == 1.0
    assert manual_portal.evidence.qualifying_time_deltas_seconds == (3600.0, 0.0)
    assert manual_portal.signals.temporal == 0.75
    assert manual_portal.dependency == 1.0
    without_citation = replace(manual_portal.signals, citation=0.0)
    assert combine_dependency(without_citation, estimator)[0] == pytest.approx(0.175)

    assert all(getattr(store_portal.signals, signal) == 0.0 for signal in SIGNALS)
    assert store_portal.dependency == 0.0
    assert store_portal.weighted_signal_coverage == manual_portal.weighted_signal_coverage
    assert store_portal.evidence.matching_claim_count == 2
    assert manual_store.evidence.source_b_parent_count == 2
    assert manual_store.signals.assertion_lineage == 1.0
    assert manual_store.dependency == 1.0


def test_wire_score_loses_signal_kind():
    # A positive representation-context signal and a structural citation can
    # yield identical wire values; the evaluator receives neither signal kind
    # nor estimator configuration. Neither implies exact lineage.
    results = []
    for signal in ("citation", "ownership"):
        estimator = config(**{f"{name}_weight": float(name == signal) for name in SIGNALS})
        score, coverage = combine_dependency(empty_signals(**{signal: 1.0}), estimator)
        results.append(SourcePair(
            source_a_id="a", source_b_id="b", dependency=score,
            weighted_signal_coverage=coverage, exact_equivalence=False,
        ))
    assert results[0] == results[1]
    assert results[0].dependency == results[0].weighted_signal_coverage == 1.0


def test_parent_counts_lose_claim_scope():
    parents = [observation("a-status", "a.example"),
               observation("a-capacity", "a.example", attribute="capacity", value=10)]
    children = [observation("b-status", "b.example", parent_observation_ids=("a-status",)),
                observation("b-capacity", "b.example", attribute="capacity", value=10,
                            parent_observation_ids=("a-capacity",))]
    aligned = pair(parents + children)
    crossed = pair(parents + [
        replace(children[0], parent_observation_ids=("a-capacity",)),
        replace(children[1], parent_observation_ids=("a-status",)),
    ])
    # Even rich pair evidence cannot recover the observation-to-observation
    # relationship, although the raw observations still contain it.
    assert aligned == crossed
    assert aligned.evidence.source_b_parent_count == 2


def test_parentage_allows_multiple_evidence_inputs():
    rows = (observation("a", "a.example"), observation("b", "b.example"),
            observation("c", "c.example", parent_observation_ids=("a", "b")))
    results, _ = estimate_dependencies(tuple(row.source for row in rows), rows, config())
    parents = [result for result in results if result.evidence.source_b_parent_count]
    assert len(parents) == 2
    assert all(result.evidence.source_b_parent_count == 1 for result in parents)
    # General derivation accepts two inputs; it supplies no assertion that
    # either input is an exact alias of the output or of the other input.
    assert all(result.signals.assertion_lineage == 1.0 for result in parents)
