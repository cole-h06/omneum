from copy import deepcopy
import json
from pathlib import Path

import pytest

from omneum import Claim
from research.braid.experiments.applied.agent_dataset.context_selection import (
    STRATEGIES,
    claim_id,
    map_chunks,
    reconstruct,
    select_chunks,
    token_count,
)


def test_many_to_many_mapping():
    mapping = map_chunks([
        {"chunk_id": "one", "raw_text": "first", "claim_ids": ["a", "b", "a"]},
        {"chunk_id": "two", "raw_text": "second", "claim_ids": ["a"]},
        {"chunk_id": "three", "raw_text": "third", "claim_ids": ["b", "c"]},
    ], ["a", "b", "c"])
    assert mapping["chunk_text"] == {"one": "first", "two": "second", "three": "third"}
    assert mapping["chunk_claims"] == {"one": ["a", "b"], "two": ["a"], "three": ["b", "c"]}
    assert mapping["claim_chunks"] == {"a": ["one", "two"], "b": ["one", "three"], "c": ["three"]}


def test_normalized_and_conflicting_claims():
    first = Claim("policies", " Northstar ", "Return Window", "30 days")
    same = Claim("policies", "northstar", "return_window", "30 days")
    conflict = Claim("policies", "northstar", "return_window", "14 days")
    assert claim_id(first) == claim_id(same)
    assert claim_id(first) != claim_id(conflict)
    assert claim_id(first) != claim_id(Claim("other", "northstar", "return_window", "30 days"))
    mapping = map_chunks([
        {"chunk_id": "one", "raw_text": "30 days", "claim_ids": [claim_id(first)]},
        {"chunk_id": "two", "raw_text": "14 days", "claim_ids": [claim_id(conflict)]},
    ], [claim_id(first), claim_id(conflict)])
    assert len(mapping["claim_chunks"]) == 2


@pytest.mark.parametrize("chunks,claims,message", [
    ([{"chunk_id": "one", "raw_text": "text", "claim_ids": []}], ["a"], "known claim"),
    ([{"chunk_id": "one", "raw_text": "text", "claim_ids": ["unknown"]}], ["a"], "known claim"),
    ([{"chunk_id": "one", "raw_text": "text", "claim_ids": ["a"]}], ["a", "b"], "no chunk mapping"),
    ([{"chunk_id": "one", "raw_text": "text", "claim_ids": ["a"]}] * 2, ["a"], "duplicate chunk"),
])
def test_missing_and_duplicate_mappings(chunks, claims, message):
    with pytest.raises(ValueError, match=message):
        map_chunks(chunks, claims)


@pytest.mark.parametrize("strategy,expected", [
    ("retrieval", "one"), ("max_support", "one"),
    ("mean_support", "two"), ("coverage_support", "two"),
])
def test_aggregation(strategy, expected):
    mapping = map_chunks([
        {"chunk_id": "one", "raw_text": "first", "claim_ids": ["a", "b", "a"]},
        {"chunk_id": "two", "raw_text": "second", "claim_ids": ["c", "d"]},
    ], ["a", "b", "c", "d"])
    result = select_chunks(mapping, {"a": 10.0, "b": 0.0, "c": 6.0, "d": 6.0}, 4, strategy)
    assert result["selected_chunk_ids"] == [expected]
    assert result["token_usage"] == 4


def test_duplicate_evidence_has_no_coverage_gain():
    mapping = map_chunks([
        {"chunk_id": "one", "raw_text": "first", "claim_ids": ["a", "b"]},
        {"chunk_id": "duplicate", "raw_text": "first again", "claim_ids": ["a", "a"]},
        {"chunk_id": "new", "raw_text": "third", "claim_ids": ["c"]},
    ], ["a", "b", "c"])
    result = select_chunks(mapping, {"a": 10.0, "b": 2.0, "c": 1.0}, 100, "coverage_support")
    assert result["selection_order"] == ["one", "new"]
    assert [item["score"] for item in result["selection_scores"]] == [12.0, 1.0]
    assert result["covered_support"] == 13.0


@pytest.mark.parametrize("strategy", STRATEGIES)
def test_budget_ties_and_reconstruction(strategy):
    mapping = map_chunks([
        {"chunk_id": "large", "raw_text": "word " * 100, "claim_ids": ["a"]},
        {"chunk_id": "one", "raw_text": "first\nline", "claim_ids": ["a"]},
        {"chunk_id": "two", "raw_text": "second", "claim_ids": ["b"]},
    ], ["a", "b"])
    support = {"a": 1.0, "b": 1.0}
    context = "[one]\nfirst\nline\n\n[two]\nsecond"
    budget = token_count(context)
    result = select_chunks(mapping, support, budget, strategy)
    assert result["selected_chunk_ids"] == ["one", "two"]
    assert result["context"] == context
    assert result["token_usage"] == budget
    assert reconstruct(mapping, ["two", "one"]) == context
    assert select_chunks(mapping, support, 0, strategy)["context"] == ""
    smaller = select_chunks(mapping, support, budget - 1, strategy)
    assert smaller["token_usage"] <= budget - 1
    assert smaller["selected_chunk_ids"] == ["one"]
    reordered = deepcopy(mapping)
    reordered["chunk_text"] = dict(reversed(list(mapping["chunk_text"].items())))
    assert select_chunks(reordered, support, budget, strategy) == result
    with pytest.raises(ValueError, match="unknown selected chunk"):
        reconstruct(mapping, ["missing"])


def test_invalid_selection_configuration():
    mapping = map_chunks([{"chunk_id": "one", "raw_text": "first", "claim_ids": ["a"]}], ["a"])
    with pytest.raises(ValueError, match="scores and mappings disagree"):
        select_chunks(mapping, {}, 10, "max_support")
    with pytest.raises(ValueError, match="unknown selection strategy"):
        select_chunks(mapping, {"a": 1.0}, 10, "unknown")
    with pytest.raises(ValueError, match="nonnegative integer"):
        select_chunks(mapping, {"a": 1.0}, -1, "retrieval")


def test_enterprise_reproducibility_and_engine_boundary(monkeypatch):
    pytest.importorskip("langgraph")
    from research.braid.experiments.applied.agent_dataset.enterprise.context_selection import run_experiment
    from research.braid.experiments.applied.agent_dataset.workflow import pipeline

    evaluate = pipeline.evaluate_context
    inputs = []

    def checked(observations, **kwargs):
        inputs.append(observations)
        assert len(observations) == 15
        assert len({item.source for item in observations}) == 5
        assert all("raw_text" not in item.metadata for item in observations)
        assert all("raw_text" not in retrieval.fields for item in observations for retrieval in item.retrievals)
        return evaluate(observations, **kwargs)

    monkeypatch.setattr(pipeline, "evaluate_context", checked)
    first = run_experiment()
    assert first == run_experiment()
    assert inputs[0] == inputs[1]
    assert len(first["observations"]) == 15
    assert len(first["claims"]) == 6
    assert len(first["dependencies"]) == 10
    assert len(first["mapping"]["chunk_claims"]["returns_faq#policy"]) == 3
    assert any(len(chunks) > 1 for chunks in first["mapping"]["claim_chunks"].values())
    assert all(result["token_usage"] <= 100 for result in first["selections"])
    assert len({tuple(result["selected_chunk_ids"]) for result in first["selections"]}) > 1
    assert all(result["token_usage"] == token_count(result["context"]) for result in first["selections"])


def test_extra_chunk_does_not_create_an_assertion(monkeypatch):
    pytest.importorskip("langgraph")
    from research.braid.experiments.applied.agent_dataset.enterprise import context_selection

    first = context_selection.run_experiment()
    load = context_selection.load_chunks

    def with_duplicate(*args):
        chunks = load(*args)
        return [*chunks, {**chunks[0], "chunk_id": "duplicate"}]

    monkeypatch.setattr(context_selection, "load_chunks", with_duplicate)
    duplicate = context_selection.run_experiment()
    for field in ("observations", "claims", "dependencies", "source_reliability", "convergence"):
        assert duplicate[field] == first[field]


def test_phase2_selection_regression():
    pytest.importorskip("langgraph")
    from research.braid.experiments.applied.agent_dataset.enterprise.context_selection import run_experiment

    path = Path(__file__).resolve().parents[1] / "enterprise/results/context-selection-v1.json"
    recorded = json.loads(path.read_text())
    current = run_experiment(recorded["configuration"]["token_budget"])
    assert current["mapping"] == recorded["mapping"]
    assert len(current["selections"]) == len(recorded["selections"])
    for actual, expected in zip(current["selections"], recorded["selections"]):
        for key, value in expected.items():
            assert actual[key] == value
        assert set(actual["mapping"]["chunk_text"]) == set(actual["selected_chunk_ids"])
