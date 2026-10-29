from copy import deepcopy
import json

import pytest

from omneum import Claim, evaluate, reconstruct_context
from omneum.context_selection import STRATEGIES, claim_id, map_chunks, select_chunks, token_count


def selection_options(evaluation, chunks, strategy):
    if strategy == "coverage_support_query":
        return {"claim_relevance": {claim_id(c.claim): 1.0 for c in evaluation.claim_support}}
    if strategy == "coverage_support_nonlinear":
        return {"chunk_relevance": {c["chunk_id"]: 1.0 for c in chunks}}
    if strategy == "coverage_answer":
        sources = {claim_id(c.claim): c.supporting_sources[0].source for c in evaluation.claim_support}
        for chunk in chunks:
            chunk["source"] = sources[chunk["claim_ids"][0]]
        return {"chunk_relevance": {c["chunk_id"]: 1.0 for c in chunks}}
    return {}


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
    monkeypatch.setattr("omneum.client._evaluate_context", unexpected)
    monkeypatch.setattr("omneum.client.OmneumClient._evaluate_context", unexpected)
    monkeypatch.setattr("socket.create_connection", unexpected)
    budget = token_count(f"[chunk-0]\n{chunks[0]['raw_text']}")
    result = reconstruct_context(evaluation, chunks, token_budget=budget, strategy="max_support")
    assert result["selected_chunk_ids"] == ["chunk-0"]
    assert result["context"] == f"[chunk-0]\n{chunks[0]['raw_text']}"
    assert result["token_usage"] == budget
    assert result["selection_scores"][0]["score"] == evaluation.claim_support[0].support
    assert result["chunks"] == [{
        "chunk_id": "chunk-0",
        "score": evaluation.claim_support[0].support,
        "raw_text": chunks[0]["raw_text"],
    }]
    assert result["mapping"]["chunk_text"] == {"chunk-0": chunks[0]["raw_text"]}
    assert result["mapping"]["chunk_claims"] == {"chunk-0": chunks[0]["claim_ids"]}
    assert result["mapping"]["claim_chunks"] == {chunks[0]["claim_ids"][0]: ["chunk-0"]}
    assert chunks[1]["raw_text"] not in json.dumps(result)
    assert chunks == before


@pytest.mark.parametrize("strategy", STRATEGIES)
def test_chunk_utility_order_and_original_text(evaluated_chunks, strategy):
    evaluation, chunks = evaluated_chunks
    options = selection_options(evaluation, chunks, strategy)
    chunks[0]["raw_text"] = " \t30 days\r\n"
    chunks[1]["raw_text"] = "\n14 days 😀  "
    result = reconstruct_context(evaluation, list(reversed(chunks)), token_budget=100, strategy=strategy, **options)
    expected = list(reversed(chunks)) if strategy == "retrieval" else chunks
    assert result["selected_chunk_ids"] == [chunk["chunk_id"] for chunk in expected]
    assert [chunk["chunk_id"] for chunk in result["chunks"]] == result["selected_chunk_ids"]
    assert [chunk["raw_text"] for chunk in result["chunks"]] == [chunk["raw_text"] for chunk in expected]
    scores = [chunk["score"] for chunk in result["chunks"]]
    assert scores == sorted(scores, reverse=True)
    assert result["context"] == "\n\n".join(
        f"[{chunk['chunk_id']}]\n{chunk['raw_text']}" for chunk in result["chunks"]
    )
    assert result["token_usage"] == token_count(result["context"])


def test_coverage_utility_and_marginal_gain():
    evaluation = evaluate([
        {
            "url": "https://a.example",
            "claim": {"entity_namespace": "research", "entity": "policy", "attribute": attribute},
            "value": attribute,
        }
        for attribute in "abcdef"
    ])
    claims = {item.claim.attribute: claim_id(item.claim) for item in evaluation.claim_support}
    chunks = [
        {"chunk_id": identifier, "raw_text": identifier, "claim_ids": [claims[value] for value in attributes]}
        for identifier, attributes in (("first", "abc"), ("second", "ad"), ("third", "e"), ("fourth", "abf"))
    ]
    result = reconstruct_context(evaluation, chunks, token_budget=100)
    assert result["selection_order"] == ["first", "second", "third", "fourth"]
    assert result["selected_chunk_ids"] == ["first", "fourth", "second", "third"]
    assert [chunk["score"] for chunk in result["chunks"]] == pytest.approx([0.5, 0.5, 1 / 3, 1 / 6])
    assert [item["marginal_gain"] for item in result["selection_scores"]] == pytest.approx([0.5, 1 / 6, 1 / 6, 1 / 6])
    assert result["chunks"][1]["score"] > result["selection_scores"][3]["marginal_gain"]
    assert result["context"] == "[first]\nfirst\n\n[fourth]\nfourth\n\n[second]\nsecond\n\n[third]\nthird"


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
    options = selection_options(evaluation, chunks, strategy)
    result = reconstruct_context(evaluation, chunks, token_budget=5, strategy=strategy, **options)
    assert result["selected_chunk_ids"] == ["z"]
    assert result == reconstruct_context(evaluation, chunks, token_budget=5, strategy=strategy, **options)
    both = reconstruct_context(evaluation, chunks, token_budget=10, strategy=strategy, **options)
    assert both["context"] == "[z]\nsame text\n\n[a]\nsame text"


@pytest.mark.parametrize("strategy", STRATEGIES)
def test_empty_candidates(evaluated_chunks, strategy):
    evaluation, _ = evaluated_chunks
    options = selection_options(evaluation, [], strategy)
    result = reconstruct_context(evaluation, [], token_budget=0, strategy=strategy, **options)
    assert result["selected_chunk_ids"] == []
    assert result["chunks"] == []
    assert result["context"] == ""
    assert result["token_usage"] == 0
    assert result["claim_coverage"] == {"covered": 0, "total": 2}
    assert result["mapping"] == {
        "chunk_text": {}, "chunk_claims": {}, "claim_chunks": {}, "retrieval_order": [],
    }
    empty = select_chunks(map_chunks([], []), {}, 0, strategy,
                          **({"claim_relevance": {}} if strategy == "coverage_support_query" else
                             {"chunk_claim_utility": {}} if strategy == "coverage_answer" else
                             {"chunk_relevance": {}} if strategy == "coverage_support_nonlinear" else {}))
    assert empty["context"] == ""


@pytest.mark.parametrize("strategy", STRATEGIES)
def test_full_rendered_budget(evaluated_chunks, strategy):
    evaluation, chunks = evaluated_chunks
    options = selection_options(evaluation, chunks, strategy)
    chunks[0]["raw_text"] = "First line\n😀"
    chunks[1]["raw_text"] = "Second line"

    def count_tokens(text):
        return len(text.encode("utf-8"))

    full = reconstruct_context(evaluation, chunks, token_budget=100, strategy=strategy, count_tokens=count_tokens, **options)
    assert full["context"] == "[chunk-0]\nFirst line\n😀\n\n[chunk-1]\nSecond line"
    for budget in (0, 1, 23, full["token_usage"] - 1, full["token_usage"]):
        result = reconstruct_context(
            evaluation, chunks, token_budget=budget, strategy=strategy, count_tokens=count_tokens, **options,
        )
        assert result["token_usage"] == count_tokens(result["context"])
        assert result["token_usage"] <= budget
        for chunk in chunks:
            assert (chunk["raw_text"] in result["context"]) == (chunk["chunk_id"] in result["selected_chunk_ids"])
    assert reconstruct_context(
        evaluation, chunks, token_budget=full["token_usage"], strategy=strategy, count_tokens=count_tokens, **options,
    ) == {**full, "token_budget": full["token_usage"]}


@pytest.mark.parametrize("budget", [-1, True, 1.5, "10"])
def test_invalid_budget(evaluated_chunks, budget):
    evaluation, chunks = evaluated_chunks
    with pytest.raises(ValueError, match="nonnegative integer"):
        reconstruct_context(evaluation, chunks, token_budget=budget)


@pytest.mark.parametrize("strategy", ["max_support", "mean_support", "coverage_support"])
def test_budget_counts_utility_order(evaluated_chunks, strategy):
    evaluation, chunks = evaluated_chunks
    full = "\n\n".join(f"[{chunk['chunk_id']}]\n{chunk['raw_text']}" for chunk in chunks)

    def count_tokens(text):
        return token_count(text) + int(text.startswith("[chunk-0]"))

    result = reconstruct_context(
        evaluation, list(reversed(chunks)), token_budget=token_count(full),
        strategy=strategy, count_tokens=count_tokens,
    )
    assert result["selected_chunk_ids"] == ["chunk-0"]
    assert result["chunks"][0]["raw_text"] == chunks[0]["raw_text"]
    assert result["token_usage"] == count_tokens(result["context"])
    assert result["token_usage"] <= token_count(full)


@pytest.mark.parametrize("count", [-1, 1.5, True])
def test_invalid_token_count(evaluated_chunks, count):
    evaluation, chunks = evaluated_chunks
    with pytest.raises(ValueError, match="token counter"):
        reconstruct_context(evaluation, chunks, token_budget=100, count_tokens=lambda text: count)


def test_empty_encoding_overhead(evaluated_chunks):
    evaluation, _ = evaluated_chunks
    with pytest.raises(ValueError, match="exceeds token budget"):
        reconstruct_context(evaluation, [], token_budget=0, count_tokens=lambda text: 1)


def test_query_qualified_properties_reconstruct_exact_multi_chunk_utf8_budget():
    evaluation=evaluate([{'url':'https://a.example','claim':{'entity_namespace':'device','entity':'pump','attribute':'pressure'},'value':200},
        {'url':'https://b.example','claim':{'entity_namespace':'device','entity':'pump','attribute':'startup_condition'},'value':'guard closed'}])
    chunks=[dict(chunk_id=str(i),raw_text=text,claim_ids=[claim_id(c.claim)])
        for i,(c,text) in enumerate(zip(evaluation.claim_support,[' original\r\n😀',' condition\n\t'],strict=True))]
    options=dict(strategy='coverage_support_query',claim_relevance={claim_id(c.claim):1. for c in evaluation.claim_support},count_tokens=lambda t:len(t.encode('utf-8')))
    full=reconstruct_context(evaluation,chunks,token_budget=1000,**options)
    assert len(full['selected_chunk_ids'])==2
    assert all(c['raw_text'] in full['context'] for c in chunks)
    for budget in (full['token_usage']-1,full['token_usage']):
        result=reconstruct_context(evaluation,chunks,token_budget=budget,**options)
        assert result['token_usage']==len(result['context'].encode('utf-8'))<=budget
