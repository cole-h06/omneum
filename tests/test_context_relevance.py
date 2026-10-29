import asyncio
from copy import deepcopy
import json

import pytest

from omneum import OmneumClient, LocalPersistenceConfig, open_stdio_client
from omneum.context_selection import map_chunks, select_chunks
from omneum.mcp import ClientSession
from omneum.query_context import plan_context
from omneum.storage import SQLiteStorage
from benchmarks.context_selection.config import estimator_config
from benchmarks.context_selection.deployment import benchmark_deployment
from test_query_context import Encoder, inputs


def select(chunks, support, relevance, budget=1000):
    return select_chunks(
        map_chunks(chunks, support), support, budget, "coverage_support_query",
        count_tokens=lambda text: len(text.encode()), claim_relevance=relevance,
    )


def test_weighting_recalculates_unique_claim_gain():
    chunks = [
        {"chunk_id": "a", "raw_text": "first", "claim_ids": ["x", "x"]},
        {"chunk_id": "b", "raw_text": "both", "claim_ids": ["x", "y"]},
        {"chunk_id": "c", "raw_text": "third", "claim_ids": ["z"]},
        {"chunk_id": "d", "raw_text": "copy", "claim_ids": ["x"]},
    ]
    result = select(chunks, {"x": 0.8, "y": 0.2, "z": 1.0}, {"x": 1.0, "y": 0.5, "z": 0.01})
    assert result["selection_order"] == ["b", "c"]
    assert result["selection_scores"][0]["marginal_gain"] == pytest.approx(0.9)
    assert result["selection_scores"][1]["marginal_gain"] == 0.01
    assert result["covered_support"] == 2.0
    assert result["candidate_scores"]["b"] == 1.0


def test_covered_claims_are_removed_after_each_selection():
    chunks = [
        {"chunk_id": "a", "raw_text": "a", "claim_ids": ["x"]},
        {"chunk_id": "b", "raw_text": "longer", "claim_ids": ["x", "y"]},
        {"chunk_id": "c", "raw_text": "c", "claim_ids": ["z"]},
    ]
    result = select(chunks, {"x": 1.0, "y": 0.1, "z": 0.2}, {"x": 1, "y": 1, "z": 1})
    assert result["selection_order"] == ["a", "c", "b"]
    assert result["selection_scores"][-1]["marginal_gain"] == 0.1


def test_zero_gain_does_not_hide_other_candidates_and_ties_are_stable():
    chunks = [{"chunk_id": key, "raw_text": "same", "claim_ids": [key]} for key in ("a", "b", "c")]
    result = select(chunks, {"a": 1, "b": 0.5, "c": 0.5}, {"a": 0, "b": 1, "c": 1})
    assert result["selection_order"] == ["b", "c"]
    assert select(chunks, {"a": 1, "b": 1, "c": 1}, {"a": 0, "b": 0, "c": 0})["context"] == ""


@pytest.mark.parametrize("budget", [0, 1, 10, 30, 200])
def test_exact_budget_raw_text_and_determinism(budget):
    chunks = [
        {"chunk_id": "a", "raw_text": "😀\r\n untouched ", "claim_ids": ["x"]},
        {"chunk_id": "b", "raw_text": "exception", "claim_ids": ["y"]},
    ]
    result = select(chunks, {"x": 0.5, "y": 0.5}, {"x": 1, "y": 0.1}, budget)
    assert result == select(chunks, {"x": 0.5, "y": 0.5}, {"x": 1, "y": 0.1}, budget)
    assert len(result["context"].encode()) == result["token_usage"] <= budget
    for chunk in result["chunks"]:
        assert chunk["raw_text"] == next(c["raw_text"] for c in chunks if c["chunk_id"] == chunk["chunk_id"])


@pytest.mark.parametrize("relevance", [{}, {"other": 1}, {"x": -1}, {"x": 1.1}, {"x": True},
                                      {"x": float("nan")}, {"x": float("inf")}, {"x": "1"}])
def test_invalid_and_missing_relevance_rejected(relevance):
    with pytest.raises(ValueError, match="relevance"):
        select([{"chunk_id": "a", "raw_text": "text", "claim_ids": ["x"]}], {"x": 1}, relevance)


def test_default_selector_rejects_relevance_instead_of_changing_behavior():
    with pytest.raises(ValueError, match="requires coverage_support_query"):
        select_chunks(map_chunks([], {}), {}, 0, "coverage_support", claim_relevance={})
    assert select_chunks(map_chunks([], {}), {}, 0, "coverage_support")["context"] == ""


def test_semantic_weights_and_low_similarity_exception_eligibility():
    observations, chunks, texts = inputs()
    result = plan_context(
        observations, chunks, estimator=estimator_config(), user_query="PRIVATE user query",
        anchor_count=1, expansion_depth=1, claim_texts=texts, semantic_model=Encoder(), query_weighted=True,
    )
    exception = chunks[0]["claim_ids"][1]
    assert result["diagnostics"]["relevance_scores"][exception] == 0
    assert exception in result["diagnostics"]["expanded_claim_ids"]
    assert result["chunks"][0]["raw_text"] == chunks[0]["raw_text"]
    # The zero-weight qualification survives inside its original anchor document.
    relevance = result["diagnostics"]["relevance_scores"]
    chosen = select([chunks[0], chunks[2]], dict.fromkeys(relevance, 0.5), relevance)
    assert "Legal hold exception" in chosen["context"]
    assert len(chosen["chunks"]) == 1
    # Eligibility alone cannot protect a zero-weight qualification from a short copy.
    copied = select(chunks, dict.fromkeys(relevance, 0.5), relevance)
    assert copied["selected_chunk_ids"] == ["d"]
    assert "Legal hold exception" not in copied["context"]


def test_weighted_semantics_do_not_invent_missing_scores():
    observations, chunks, texts = inputs()
    class Unavailable:
        def encode(self, *args, **kwargs):
            raise OSError("unavailable")
    for query, available_texts, model in [("", texts, Encoder()), ("q", {}, Encoder()), ("q", texts, Unavailable())]:
        with pytest.raises(ValueError, match="requires relevance"):
            plan_context(observations, chunks, estimator=estimator_config(), user_query=query,
                         anchor_count=1, expansion_depth=1, claim_texts=available_texts,
                         semantic_model=model, query_weighted=True)


def test_sdk_real_mcp_full_scores_persistence_and_text_blindness(tmp_path, monkeypatch, capsys):
    observations, chunks, texts = inputs()
    original = deepcopy(chunks)
    calls = []
    call_tool = ClientSession.call_tool
    async def capture(self, name, arguments=None, *args, **kwargs):
        if name == "evaluate_context":
            calls.append(deepcopy(arguments))
        return await call_tool(self, name, arguments, *args, **kwargs)
    monkeypatch.setattr(ClientSession, "call_tool", capture)

    async def run():
        storage = SQLiteStorage(tmp_path / "omneum.db")
        with benchmark_deployment() as (config, server):
            async with open_stdio_client(config, server, local_persistence=LocalPersistenceConfig(storage)) as client:
                options = dict(estimator=estimator_config(), token_budget=2000, count_tokens=len)
                baseline = await client.prepare_context(observations, chunks, **options)
                for anchored in (False, True):
                    diagnostics = {}
                    result = await client.prepare_context(
                        observations, chunks, **options, user_query="PRIVATE user query", anchor_count=1,
                        claim_texts=texts, semantic_model=Encoder(), strategy="coverage_support_query",
                        query_anchoring=anchored, query_diagnostics=diagnostics,
                    )
                    assert result["evaluation"] == baseline["evaluation"]
                    assert result.keys() == baseline.keys()
                    assert result["selection"]["input_tokens"] == baseline["selection"]["input_tokens"]
                    assert result["selection"]["selected_tokens"] == len(result["context"]) <= 2000
                    assert result["packed_chunk_ids"] == ["d"]
                    assert result["context"] == "[d]\n" + chunks[1]["raw_text"]
                    assert "PRIVATE unrelated" not in result["context"]
                    assert diagnostics["evaluation_scope"] == "full"
                    json.dumps(result, allow_nan=False)
                injected = await client.prepare_context(
                    observations, chunks, **options, strategy="coverage_support_query", query_anchoring=False,
                    claim_relevance={key: 1.0 for key in texts},
                )
                assert injected["evaluation"] == baseline["evaluation"]
                assert await client.prepare_context(observations, chunks, **options) == baseline
        import sqlite3
        with sqlite3.connect(storage.path) as db:
            assert db.execute("SELECT count(*) FROM evaluation_runs").fetchone()[0] == 5
            assert db.execute("SELECT count(*) FROM execution_history").fetchone()[0] == 5
            assert not db.execute("PRAGMA foreign_key_check").fetchall()
    asyncio.run(run())
    assert len(calls) == 5
    assert "PRIVATE" not in json.dumps(calls)
    assert chunks == original
    assert capsys.readouterr() == ("", "")


def test_positive_cosine_normalization_and_injected_scores():
    observations, chunks, texts = inputs()
    class Model:
        def encode(self, values, **kwargs):
            return [[1, 0], [1, 0], [-1, 0], [0, 1]]
    result = plan_context(
        observations, chunks, estimator=estimator_config(), user_query="q",
        anchor_count=1, expansion_depth=1, claim_texts=texts, semantic_model=Model(),
        query_weighted=True, query_anchoring=False,
    )
    assert sorted(result["diagnostics"]["relevance_scores"].values()) == [0, 0, 1]
    assert result["chunks"] == chunks
    supplied = dict.fromkeys(texts, 0.0)
    supplied[chunks[0]["claim_ids"][0]] = 0.7
    injected = plan_context(
        observations, chunks, estimator=estimator_config(), user_query="",
        anchor_count=1, expansion_depth=1, claim_texts=None, semantic_model=object(),
        query_weighted=True, claim_relevance=supplied,
    )
    assert injected["diagnostics"]["relevance_scores"] == supplied


def test_empty_and_all_ones_match_existing_density():
    assert select([], {}, {}, 0)["token_usage"] == 0
    chunks = [{"chunk_id": "a", "raw_text": "multi claim", "claim_ids": ["x", "y"]},
              {"chunk_id": "b", "raw_text": "copy", "claim_ids": ["x"]}]
    support = {"x": 0.5, "y": 0.2}
    weighted = select(chunks, support, {"x": 1, "y": 1})
    density = select_chunks(map_chunks(chunks, support), support, 1000, "coverage_support_density",
                            count_tokens=lambda text: len(text.encode()), token_cost_exponent=1)
    for field in ("context", "chunks", "selection_order", "selection_scores", "candidate_scores"):
        assert weighted[field] == density[field]
    qualification = select(chunks, support, {"x": 1, "y": 0.01})
    assert qualification["selection_order"] == ["b", "a"]
    assert qualification["selection_scores"][-1]["marginal_gain"] == 0.002
