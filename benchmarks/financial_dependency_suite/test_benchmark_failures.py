import pytest

import benchmarks.financial_dependency_suite.application_comparison as app
import benchmarks.financial_dependency_suite.llm_judge as judge
from benchmarks.financial_dependency_suite.adversarial.comparison import (
    score_relationships,
)


def test_dependency_scoring_is_symmetric():
    expected = {("source_a", "source_b")}

    forward = [{
        "source": "source_a",
        "depends_on": "source_b",
    }]
    reverse = [{
        "source": "source_b",
        "depends_on": "source_a",
    }]

    assert score_relationships(forward, expected)["exact_match"]
    assert score_relationships(reverse, expected)["exact_match"]


def test_empty_prediction_has_zero_precision():
    score = score_relationships(
        [],
        {("source_a", "source_b")},
    )

    assert score["precision"] == 0.0
    assert score["recall"] == 0.0
    assert not score["exact_match"]


def test_cohere_failure_is_recorded(monkeypatch):
    def fail(*args, **kwargs):
        raise RuntimeError("provider unavailable")

    monkeypatch.setattr(app, "rerank_cohere", fail)

    result = app.select_cohere_safe(
        "query",
        [{"source": "source_a", "text": "text"}],
        top_n=1,
    )

    assert result["selection"] is None
    assert result["failure"]["answer_score"] == "selection_failure"
    assert result["failure"]["failure_type"] == "provider_error"
    assert "provider unavailable" in result["failure"]["error"]


@pytest.mark.anyio
async def test_llm_parse_failure_keeps_raw_output(monkeypatch):
    raw = '{"selected_sources": ["not_a_source"]}'

    async def fake_generate(*args, **kwargs):
        return {
            "text": raw,
            "provider": "anthropic",
            "model": "claude-sonnet-5",
            "input_tokens": 10,
            "output_tokens": 5,
            "latency_seconds": 0.1,
        }

    monkeypatch.setattr(app, "generate", fake_generate)

    result = await app.select_llm_safe(
        "query",
        [{"source": "source_a", "text": "text"}],
        provider="anthropic",
        model="claude-sonnet-5",
        top_n=1,
    )

    failure = result["failure"]

    assert failure["failure_type"] == "parse_error"
    assert failure["selection"]["raw_output"] == raw


@pytest.mark.anyio
async def test_structural_judge_rejects_malformed_output(monkeypatch):
    async def fake_generate(*args, **kwargs):
        return {
            "text": (
                '{"relationships": ['
                '{"source": "source_a", '
                '"depends_on": "unknown", '
                '"relationship_type": "citation", '
                '"confidence": 0.9}'
                ']}'
            ),
            "provider": "anthropic",
            "model": "claude-sonnet-5",
            "input_tokens": 10,
            "output_tokens": 10,
            "latency_seconds": 0.1,
        }

    monkeypatch.setattr(judge, "generate", fake_generate)

    result = await judge.judge_dependencies_from_results(
        "query",
        [
            {"source": "source_a", "text": "A"},
            {"source": "source_b", "text": "B"},
        ],
        provider="anthropic",
        model="claude-sonnet-5",
    )

    assert result["relationships"] is None
    assert result["parse_error"] is not None
    assert result["generation"]["text"]


def test_generation_failure_is_recorded(monkeypatch):
    import asyncio

    from benchmarks.financial_dependency_suite import application_comparison

    async def fail(*args, **kwargs):
        raise RuntimeError("provider unavailable")

    monkeypatch.setattr(
        application_comparison,
        "generate_answer",
        fail,
    )

    result = asyncio.run(
        application_comparison.generate_answer_safe(
            "query",
            [{"source": "source_a", "text": "text"}],
            provider="anthropic",
            model="claude-sonnet-5",
        )
    )

    assert result["generation"] is None
    assert result["failure"]["answer_score"] == "generation_failure"
    assert result["failure"]["failure_type"] == "provider_error"
    assert result["failure"]["provider"] == "anthropic"
    assert result["failure"]["model"] == "claude-sonnet-5"
    assert result["failure"]["error"] == "provider unavailable"
