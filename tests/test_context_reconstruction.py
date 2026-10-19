from copy import deepcopy
import json

import pytest

from omneum import Claim, evaluate, reconstruct_context
from omneum.context_selection import STRATEGIES, claim_id, map_chunks, select_chunks, token_count


@pytest.fixture
def evaluated_chunks():
    evaluation = evaluate([
        {"url": "https://a.example", "value": "30 days", "upstream": []},
        {"url": "https://b.example", "value": "30 days", "upstream": []},
        {"url": "https://c.example", "value": "14 days", "upstream": []},
    ])
    chunks = [
        {
            "chunk_id": f"chunk-{index}",
            "raw_text": f"Source passage: {item.claim.value}",
            "claim_ids": [claim_id(item.claim)],
        }
        for index, item in enumerate(evaluation.claim_support)
    ]
    return evaluation, chunks


def test_existing_evaluation_stays_local(evaluated_chunks, monkeypatch):
    evaluation, chunks = evaluated_chunks
    before = deepcopy(chunks)

    def unexpected(*args, **kwargs):
        pytest.fail("reconstruction must not evaluate or contact a server")

    monkeypatch.setattr("omneum.client.infer", unexpected)
    monkeypatch.setattr("omneum.client.estimate_dependencies", unexpected)
    monkeypatch.setattr("omneum.client.evaluate_context", unexpected)
    monkeypatch.setattr("omneum.client.OmneumClient.evaluate_context", unexpected)
    monkeypatch.setattr("socket.create_connection", unexpected)
    budget = token_count(f"[chunk-0]\n{chunks[0]['raw_text']}")
    result = reconstruct_context(evaluation, chunks, token_budget=budget, strategy="max_support")
    assert result["selected_chunk_ids"] == ["chunk-0"]
    assert result["context"] == f"[chunk-0]\n{chunks[0]['raw_text']}"
    assert result["token_usage"] == budget
    assert result["selection_scores"][0]["score"] == evaluation.claim_support[0].support
    assert result["mapping"]["chunk_text"] == {"chunk-0": chunks[0]["raw_text"]}
    assert result["mapping"]["chunk_claims"] == {"chunk-0": chunks[0]["claim_ids"]}
    assert result["mapping"]["claim_chunks"] == {chunks[0]["claim_ids"][0]: ["chunk-0"]}
    assert chunks[1]["raw_text"] not in json.dumps(result)
    assert chunks == before


def test_conflicting_and_duplicate_claims(evaluated_chunks):
    evaluation, chunks = evaluated_chunks
    first, second = (chunk["claim_ids"][0] for chunk in chunks)
    assert first != second
    assert first == claim_id(Claim("records", " Default ", "Value", "30 days"))
    chunks[0]["claim_ids"].append(first)
    result = reconstruct_context(evaluation, chunks, token_budget=100)
    assert result["claim_coverage"] == {"covered": 2, "total": 2}
    assert result["mapping"]["chunk_claims"]["chunk-0"] == [first]
    assert result["covered_support"] == sum(item.support for item in evaluation.claim_support)


@pytest.mark.parametrize("case", ["missing", "unknown", "empty", "partial"])
def test_missing_claim_mappings(evaluated_chunks, case):
    evaluation, chunks = evaluated_chunks
    if case == "missing":
        del chunks[0]["claim_ids"]
    elif case == "unknown":
        chunks[0]["claim_ids"] = ["unknown"]
    elif case == "empty":
        chunks[0]["claim_ids"] = []
    else:
        chunks.pop()
    with pytest.raises(ValueError):
        reconstruct_context(evaluation, chunks, token_budget=100)


def test_duplicate_chunks(evaluated_chunks):
    evaluation, chunks = evaluated_chunks
    with pytest.raises(ValueError, match="duplicate chunk ID"):
        reconstruct_context(evaluation, [*chunks, chunks[0]], token_budget=100)


@pytest.mark.parametrize("strategy", STRATEGIES)
def test_deterministic_ties_and_order(strategy):
    evaluation = evaluate([
        {"url": "https://a.example", "value": "yes"},
        {"url": "https://b.example", "value": "no"},
    ])
    assert evaluation.claim_support[0].support == evaluation.claim_support[1].support
    chunks = [
        {"chunk_id": identifier, "raw_text": "same text", "claim_ids": [claim_id(item.claim)]}
        for identifier, item in zip(("z", "a"), evaluation.claim_support)
    ]
    result = reconstruct_context(evaluation, chunks, token_budget=5, strategy=strategy)
    assert result["selected_chunk_ids"] == ["z"]
    assert result == reconstruct_context(evaluation, chunks, token_budget=5, strategy=strategy)
    both = reconstruct_context(evaluation, chunks, token_budget=10, strategy=strategy)
    assert both["context"] == "[z]\nsame text\n\n[a]\nsame text"


@pytest.mark.parametrize("strategy", STRATEGIES)
def test_empty_candidates(evaluated_chunks, strategy):
    evaluation, _ = evaluated_chunks
    result = reconstruct_context(evaluation, [], token_budget=0, strategy=strategy)
    assert result["selected_chunk_ids"] == []
    assert result["context"] == ""
    assert result["token_usage"] == 0
    assert result["claim_coverage"] == {"covered": 0, "total": 2}
    assert result["mapping"] == {
        "chunk_text": {}, "chunk_claims": {}, "claim_chunks": {}, "retrieval_order": [],
    }
    empty = select_chunks(map_chunks([], []), {}, 0, strategy)
    assert empty["context"] == ""


@pytest.mark.parametrize("strategy", STRATEGIES)
def test_full_rendered_budget(evaluated_chunks, strategy):
    evaluation, chunks = evaluated_chunks
    chunks[0]["raw_text"] = "First line\n😀"
    chunks[1]["raw_text"] = "Second line"

    def count_tokens(text):
        return len(text.encode("utf-8"))

    full = reconstruct_context(evaluation, chunks, token_budget=100, strategy=strategy, count_tokens=count_tokens)
    assert full["context"] == "[chunk-0]\nFirst line\n😀\n\n[chunk-1]\nSecond line"
    for budget in (0, 1, 23, full["token_usage"] - 1, full["token_usage"]):
        result = reconstruct_context(
            evaluation, chunks, token_budget=budget, strategy=strategy, count_tokens=count_tokens,
        )
        assert result["token_usage"] == count_tokens(result["context"])
        assert result["token_usage"] <= budget
        for chunk in chunks:
            assert (chunk["raw_text"] in result["context"]) == (chunk["chunk_id"] in result["selected_chunk_ids"])
    assert reconstruct_context(
        evaluation, chunks, token_budget=full["token_usage"], strategy=strategy, count_tokens=count_tokens,
    ) == full


@pytest.mark.parametrize("budget", [-1, True, 1.5, "10"])
def test_invalid_budget(evaluated_chunks, budget):
    evaluation, chunks = evaluated_chunks
    with pytest.raises(ValueError, match="nonnegative integer"):
        reconstruct_context(evaluation, chunks, token_budget=budget)


@pytest.mark.parametrize("count", [-1, 1.5, True])
def test_invalid_token_count(evaluated_chunks, count):
    evaluation, chunks = evaluated_chunks
    with pytest.raises(ValueError, match="token counter"):
        reconstruct_context(evaluation, chunks, token_budget=100, count_tokens=lambda text: count)


def test_empty_encoding_overhead(evaluated_chunks):
    evaluation, _ = evaluated_chunks
    with pytest.raises(ValueError, match="exceeds token budget"):
        reconstruct_context(evaluation, [], token_budget=0, count_tokens=lambda text: 1)
