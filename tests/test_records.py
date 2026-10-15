from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timezone

import pytest

from omneum import (
    Claim, ContextEvaluation, DependencyEstimatorConfig, Observation, Source,
    SourceReference, evaluate_context, evaluate, evaluate_records,
)
from omneum.dependency import InformationGraphError
import omneum.records as records_module


def records():
    return [
        {"url": "https://a.example", "value": 4200000000, "upstream": ["https://sec.example"]},
        {"url": "https://b.example", "value": 4200000000, "upstream": ["https://sec.example"]},
        {"url": "https://c.example", "value": 4200000000, "upstream": []},
    ]


def estimator():
    return DependencyEstimatorConfig(
        upstream_weight=1.0, citation_weight=0.0, assertion_lineage_weight=0.0,
        ownership_weight=0.0, temporal_weight=0.0, graph_weight=0.0,
        temporal_window_seconds=7200.0,
    )


@pytest.fixture
def evaluation_calls(monkeypatch):
    calls = []
    evaluate_context = records_module.evaluate_context

    def capture(observations, *, estimator):
        calls.append((observations, estimator))
        return evaluate_context(observations, estimator=estimator)

    monkeypatch.setattr(records_module, "evaluate_context", capture)
    return calls


def test_evaluate_alias():
    assert evaluate_records is evaluate
    assert records_module.evaluate_records is records_module.evaluate is evaluate
    assert evaluate_records(records()) == evaluate(records())


def test_upstream_dependencies():
    values = records()
    original = deepcopy(values)
    result = evaluate(values)
    assert isinstance(result, ContextEvaluation)
    assert result.estimated_independent_support == 2.0
    assert values == original
    assert result.claim_support[0].claim == Claim("records", "default", "value", 4200000000)
    assert len(result.source_reliability) == 3
    assert sorted(p.dependency for p in result.pairwise_dependencies) == [0.0, 0.0, 1.0]
    assert evaluate([dict(r, upstream=[]) for r in values]).estimated_independent_support == 3.0
    assert evaluate([
        dict(r, upstream=[f"https://upstream-{i}.example"]) for i, r in enumerate(values)
    ]).estimated_independent_support == 3.0


def test_fractional_support():
    config = replace(estimator(), ownership_weight=1.0)
    values = [dict(r, upstream=[], owner_id="shared" if i < 2 else "independent")
              for i, r in enumerate(records())]
    result = evaluate(values, estimator=config)
    assert result.estimated_independent_support == pytest.approx(1 + 2 / 1.5)
    assert result.estimated_independent_support == result.claim_support[0].estimated_independent_support_count
    assert result.estimated_independent_support != round(result.estimated_independent_support, 2)


def test_claim_identity():
    revenue = {"entity_namespace": "company", "entity": "acme", "attribute": "revenue"}
    staff = dict(revenue, attribute="staff")
    values = [dict(r, claim=revenue) for r in records()]
    values[2]["value"] = 99
    values.append({"url": "https://a.example", "value": 99, "claim": staff, "upstream": []})
    result = evaluate(values)
    claims = {(c.claim.attribute, c.claim.value): c for c in result.claim_support}
    assert set(claims) == {("revenue", 4200000000), ("revenue", 99), ("staff", 99)}
    assert claims["revenue", 4200000000].estimated_independent_support_count == 1.0
    assert len(claims["revenue", 99].conflicting_claims) == 1
    assert claims["staff", 99].conflicting_claims == ()
    with pytest.raises(ValueError, match="select a claim"):
        _ = result.estimated_independent_support


def test_default_claim_conflicts():
    result = evaluate([{"url": "https://a.example", "value": None},
                               {"url": "https://b.example", "value": 1}])
    assert len(result.claim_support) == 2
    assert all(len(c.conflicting_claims) == 1 for c in result.claim_support)
    with pytest.raises(ValueError, match="conflicting values"):
        _ = result.estimated_independent_support


def test_record_provenance(evaluation_calls):
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    identity = {"entity_namespace": "company", "entity": "ACME", "attribute": "Revenue"}
    values = records()
    for i, record in enumerate(values):
        record.update(claim=identity, observed_at=now, source_modified_at=now,
                      observation_id=f"obs-{i}", owner_id="owner", cited=[],
                      parent_observation_ids=[], metadata={"tag": ["synthetic"]})
    config = replace(estimator(), dependency_cluster_threshold=0.5)
    result = evaluate(values, estimator=config)
    assert len(evaluation_calls) == 1
    expected = [Observation(
        observation_id=f"obs-{i}", source=Source("web_document", r["url"], "owner"),
        claim=Claim(**identity, value=r["value"]), observed_at=now,
        source_modified_at=now,
        upstream_sources=tuple(SourceReference("web_document", u) for u in r["upstream"]),
        cited_sources=(), parent_observation_ids=(), metadata={"tag": ["synthetic"]},
    ) for i, r in enumerate(values)]
    assert evaluation_calls[0] == (expected, config)
    assert result == evaluate_context(expected, estimator=config)


def test_provenance_defaults(evaluation_calls):
    evaluate([{"url": "https://a.example", "value": 1},
              {"url": "https://b.example", "value": 1, "upstream": []}])
    observations, _ = evaluation_calls[0]
    assert [o.observation_id for o in observations] == ["record:0", "record:1"]
    assert observations[0].observed_at == observations[1].observed_at
    assert observations[0].observed_at.utcoffset().total_seconds() == 0
    assert observations[0].upstream_sources is None
    assert observations[1].upstream_sources == ()
    assert all(o.source_modified_at is None for o in observations)


@pytest.mark.parametrize("values, error", [
    (None, TypeError), ({"url": "https://a.example", "value": 1}, TypeError),
    ("records", TypeError), ([1], TypeError), ([], InformationGraphError),
    ([{"url": "https://a.example"}], ValueError),
    ([{"value": 1}], ValueError),
    ([{"url": "invalid", "value": 1}], ValueError),
    ([{"url": 1, "value": 1}], TypeError),
    ([{"url": "https://a.example", "value": float("nan")}], ValueError),
    ([{"url": "https://a.example", "value": object()}], TypeError),
    ([{"url": "https://a.example", "value": 1, "upstream": "https://b.example"}], TypeError),
    ([{"url": "https://a.example", "value": 1, "upstream": [1]}], TypeError),
    ([{"url": "https://a.example", "value": 1, "claim": {"entity": "acme"}}], ValueError),
    ([{"url": "https://a.example", "value": 1, "claim": None}], ValueError),
    ([{"url": "https://a.example", "value": 1, "observed_at": "today"}], TypeError),
    ([{"url": "https://a.example", "value": 1, "observed_at": datetime(2026, 1, 1)}], ValueError),
    ([{"url": "https://a.example", "value": 1, "parent_observation_ids": "parent"}], TypeError),
    ([{"url": "https://a.example", "value": 1, "upsteam": []}], ValueError),
])
def test_invalid_records(values, error):
    with pytest.raises(error):
        evaluate(values)


def test_mixed_claim_identity():
    values = records()
    values[0]["claim"] = {"entity_namespace": "company", "entity": "acme", "attribute": "revenue"}
    with pytest.raises(ValueError, match="every record"):
        evaluate(values)


@pytest.mark.parametrize("change, match", [
    ({}, "duplicate canonical assertion"),
    ({"url": "https://A.example:443/#fragment"}, "duplicate canonical assertion"),
    ({"value": 99}, "multiple claims for an attribute"),
    ({"observation_id": "same", "url": "https://b.example"}, "duplicate observation ID"),
])
def test_duplicate_observations(change, match):
    first = {"url": "https://a.example", "value": 1, "observation_id": "same"}
    second = dict(first, observation_id="other")
    second.update(change)
    with pytest.raises(InformationGraphError, match=match):
        evaluate([first, second])
