import inspect

import pytest

from omneum import Claim, Source
from omneum.client import ClaimSupportResult, ContextEvaluation, ConvergenceMetadata, SourceEvaluation, SupportingSourceResult
from omneum.context_selection import map_chunks, reconstruct_context, select_chunks, token_count
from omneum.question_selection import lexical_claim_relevance
from omneum.context_selection import claim_id


def reconstruct_context_from_chunks(chunks, selected):
    order = [chunk["chunk_id"] for chunk in chunks if chunk["chunk_id"] in selected]
    by_id = {chunk["chunk_id"]: chunk for chunk in chunks}
    return "\n\n".join(f"[{key}]\n{by_id[key]['raw_text']}" for key in order)


def test_lexical_relevance_is_normalized_and_handles_empty_inputs():
    scores = lexical_claim_relevance("Which retention period applies?", {
        "period": "account retention 30 days", "noise": "account quota 8", "missing": None,
    })
    assert scores == {"period": pytest.approx(1 / 3), "noise": 0.0, "missing": 0.0}
    assert lexical_claim_relevance(None, {"period": "retention"}) == {"period": 0.0}
    assert lexical_claim_relevance("  ", {"period": "retention"}) == {"period": 0.0}
    with pytest.raises(TypeError, match="question"):
        lexical_claim_relevance(1, {})


def test_normalized_entity_match_does_not_dominate_claim_field_relevance():
    wanted = Claim("service", "account-17", "retention_period", "30 days")
    noise = Claim("service", "account-17", "dashboard_color", "blue")
    other_entity = Claim("service", "account-18", "retention_period", "30 days")
    scores = lexical_claim_relevance("For account 17, what is the retention period for records?", {
        "wanted": wanted, "noise": noise, "other": other_entity,
    })
    assert scores["wanted"] > scores["noise"]
    assert scores["wanted"] > scores["other"]
    assert all(0 <= score <= 1 for score in scores.values())


def test_question_and_support_jointly_rank_claims_and_suppress_cluster_duplicates():
    chunks = [
        {"chunk_id": "relevant", "raw_text": "retention evidence", "claim_ids": ["x"]},
        {"chunk_id": "irrelevant", "raw_text": "quota evidence", "claim_ids": ["y"]},
        {"chunk_id": "dependent", "raw_text": "copied retention", "claim_ids": ["x"]},
        {"chunk_id": "independent", "raw_text": "independent retention", "claim_ids": ["x"]},
    ]
    source_utility = {
        "relevant": {"x": (("cluster", "a", "b"), .25)},
        "irrelevant": {"y": (("source", "c"), .95)},
        "dependent": {"x": (("cluster", "a", "b"), .15)},
        "independent": {"x": (("source", "d"), .30)},
    }
    mapping = map_chunks(chunks, {"x": .55, "y": .95})
    relevance = {"x": 1.0, "y": 0.0}
    result = select_chunks(mapping, {"x": .55, "y": .95}, 1000,
        "coverage_support_query", count_tokens=lambda text: len(text),
        claim_relevance=relevance, claim_source_utility=source_utility)
    assert result["selection_order"] == ["relevant", "independent"]
    assert "dependent" not in result["selected_chunk_ids"]
    assert "irrelevant" not in result["selected_chunk_ids"]
    assert result["context"] == reconstruct_context_from_chunks(chunks, result["selected_chunk_ids"])
    # Regression contract for the cached marginal path: preserve the original
    # gains, selection ordering, and rendered passage order exactly.
    assert [item["marginal_gain"] for item in result["selection_scores"]] == pytest.approx([.25, .30])
    assert [item["chunk_id"] for item in result["selection_scores"]] == ["relevant", "independent"]
    assert result["context"] == (
        "[relevant]\nretention evidence\n\n[independent]\nindependent retention"
    )
    assert result["token_usage"] <= 1000


def test_support_weight_breaks_similar_relevance_and_exact_budget_is_deterministic():
    chunks = [
        {"chunk_id": "strong", "raw_text": "strong claim", "claim_ids": ["x"]},
        {"chunk_id": "weak", "raw_text": "weak claim", "claim_ids": ["y"]},
    ]
    support = {"x": .8, "y": .3}
    values = {"strong": {"x": (("source", "a"), .8)},
              "weak": {"y": (("source", "b"), .3)}}
    mapping = map_chunks(chunks, support)
    budget = token_count("[strong]\nstrong claim")
    a = select_chunks(mapping, support, budget, "coverage_support_query",
        claim_relevance={"x": .9, "y": .9}, claim_source_utility=values)
    b = select_chunks(mapping, support, budget, "coverage_support_query",
        claim_relevance={"x": .9, "y": .9}, claim_source_utility=values)
    assert a == b
    assert a["selected_chunk_ids"] == ["strong"]
    assert a["token_usage"] <= budget
    assert a["context"] == "[strong]\nstrong claim"


def test_question_can_prioritize_qualification_and_empty_question_is_explicit():
    chunks = [
        {"chunk_id": "rule", "raw_text": "Normal retention is 30 days.", "claim_ids": ["normal"]},
        {"chunk_id": "exception", "raw_text": "Legal hold exception suspends deletion.", "claim_ids": ["exception"]},
    ]
    support = {"normal": .9, "exception": .4}
    relevance = lexical_claim_relevance("What happens during legal hold?", {
        "normal": "account retention 30 days", "exception": "account legal hold exception suspends deletion",
    })
    mapping = map_chunks(chunks, support)
    utilities = {"rule": {"normal": (("source", "a"), .9)},
                 "exception": {"exception": (("source", "b"), .4)}}
    result = select_chunks(mapping, support, 1000, "coverage_support_query",
        claim_relevance=relevance, claim_source_utility=utilities)
    assert result["selection_order"][0] == "exception"
    empty = lexical_claim_relevance("", {"normal": "retention", "exception": "legal hold"})
    assert empty == {"normal": 0.0, "exception": 0.0}


def test_question_reconstruction_preserves_inference_and_sdk_api_compatibility():
    source = Source("web_document", "https://source.example")
    claims = [Claim("service", "account", "retention", "30 days"),
              Claim("service", "account", "quota", 8)]
    supports = tuple(ClaimSupportResult(claim, value, 1.0, True, 1, 1.0, None,
        (SupportingSourceResult(source, 1.0, value),), (), None)
        for claim, value in zip(claims, (.8, .9), strict=True))
    evaluation = ContextEvaluation((SourceEvaluation(source, 1.0),), supports, (),
        ConvergenceMetadata("omneum-v2", 1, True, 1e-8, 0.0), None)
    chunks = [
        {"chunk_id": "retention", "raw_text": "Retention is 30 days.",
         "claim_ids": [claim_id(claims[0])], "source": source},
        {"chunk_id": "quota", "raw_text": "Quota is 8.",
         "claim_ids": [claim_id(claims[1])], "source": source},
        {"chunk_id": "retention-copy", "raw_text": "Copied retention is 30 days.",
         "claim_ids": [claim_id(claims[0])], "source": source},
    ]
    baseline = reconstruct_context(evaluation, chunks, token_budget=1000)
    assert reconstruct_context(evaluation, chunks, token_budget=1000, question=None) == baseline
    result = reconstruct_context(evaluation, chunks, token_budget=1000, question="What is the retention period?")
    assert baseline["strategy"] == "coverage_support"
    assert result["strategy"] == "coverage_support_query"
    assert result["selection_order"][0] == "retention"
    assert "retention-copy" not in result["selected_chunk_ids"]
    assert result["token_usage"] <= 1000
    assert evaluation.claim_support == supports
    # Question-aware selection consumes normalized claim support only; it does
    # not require another source-level dependency score or raw passage analysis.
    assert reconstruct_context(
        evaluation,
        [{key: value for key, value in chunk.items() if key != "source"} for chunk in chunks],
        token_budget=1000,
        question="What is the retention period?",
    ) == result
    assert reconstruct_context(evaluation, chunks, token_budget=1000, question="") == baseline
    from omneum.client import OmneumClient
    assert "question" in inspect.signature(OmneumClient.prepare_context).parameters

