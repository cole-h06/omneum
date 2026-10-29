import pytest

from omneum.context_selection import map_chunks, select_chunks


def select(chunks, support, penalty=0.0, budget=10000, count=len, strategy="coverage_support"):
    return select_chunks(map_chunks(chunks, support), support, budget, strategy,
                         count_tokens=count, token_penalty=penalty)


def chunk(identifier, text, claims):
    return {"chunk_id": identifier, "raw_text": text, "claim_ids": claims}


def test_zero_penalty_and_other_strategies():
    chunks = [chunk("a", "one", ["a", "b"]), chunk("b", "two", ["b"]), chunk("c", "three", ["c"])]
    support = {"a": 2.0, "b": 1.0, "c": 0.5}
    result = select(chunks, support)
    assert result["selection_order"] == ["a", "c"]
    assert result["selection_scores"] == [
        {"chunk_id": "a", "score": 3.0, "marginal_gain": 3.0},
        {"chunk_id": "c", "score": 0.5, "marginal_gain": 0.5},
    ]
    assert result["context"] == "[a]\none\n\n[c]\nthree"
    for strategy in ("retrieval", "max_support", "mean_support"):
        assert select(chunks, support, strategy=strategy) == select(chunks, support, 1.0, strategy=strategy)


def test_positive_utility_and_duplicate_coverage():
    chunks = [chunk("a", "x", ["a"]), chunk("b", "x", ["a"]), chunk("c", "x", ["c"])]
    result = select(chunks, {"a": 1.0, "c": 0.1}, 0.1)
    assert result["selected_chunk_ids"] == ["a"]
    assert result["selection_scores"][0]["incremental_tokens"] == 5
    assert result["selection_scores"][0]["regularized_utility"] == 0.5
    assert select(chunks, {"a": 0.5, "c": 0.1}, 0.1)["chunks"] == []


def test_size_cost_ties_and_static_reconstruction_order():
    chunks = [chunk("large", "x" * 60, ["a"]), chunk("small", "x", ["b"]), chunk("other", "x", ["c"])]
    result = select(chunks, {"a": 1.0, "b": 0.9, "c": 0.9}, 0.01)
    assert result["selection_order"] == ["small", "other", "large"]
    assert result["selected_chunk_ids"] == ["large", "small", "other"]
    assert result["context"] == "[large]\n" + "x" * 60 + "\n\n[small]\nx\n\n[other]\nx"


def test_large_valuable_chunk_remains_eligible():
    chunks = [chunk("large", "x" * 100, ["a", "b"]), chunk("small", "x", ["c"])]
    result = select(chunks, {"a": 10.0, "b": 10.0, "c": 1.0}, 0.1)
    assert result["selection_order"][0] == "large"
    assert result["selection_scores"][0]["regularized_utility"] > 0


def test_nonadditive_cost_and_exact_budget():
    chunks = [chunk("a", "x", ["a"]), chunk("b", "y", ["b"])]

    def count(text):
        return len(text) - (3 if "\n\n" in text else 0)

    result = select(chunks, {"a": 2.0, "b": 1.0}, 0.1, 9, count)
    assert result["token_usage"] == count(result["context"]) == 9
    assert [item["incremental_tokens"] for item in result["selection_scores"]] == [5, 4]
    assert sum(item["incremental_tokens"] for item in result["selection_scores"]) == 9
    assert select(chunks, {"a": 2.0, "b": 1.0}, 0.1, 8, count)["selected_chunk_ids"] == ["a"]


@pytest.mark.parametrize("penalty", [-1.0, float("nan"), float("inf"), True, "0.1"])
def test_invalid_penalty(penalty):
    with pytest.raises(ValueError, match="penalty"):
        select([chunk("a", "x", ["a"])], {"a": 1.0}, penalty)
