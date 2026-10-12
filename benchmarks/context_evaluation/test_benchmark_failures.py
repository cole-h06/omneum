import pytest

import benchmarks.context_evaluation.application_comparison as app
import benchmarks.context_evaluation.llm_judge as judge
from benchmarks.context_evaluation.adversarial.comparison import (
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

    from benchmarks.context_evaluation import application_comparison

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


def test_provenance_provider_failure(monkeypatch):
    import asyncio

    import benchmarks.context_evaluation.application_comparison as app

    async def fail_generate(*args, **kwargs):
        raise RuntimeError("provider unavailable")

    monkeypatch.setattr(app, "generate", fail_generate)

    result = asyncio.run(
        app.select_llm_provenance_safe(
            "question",
            [{"source": "source_a", "text": "A"}],
            [],
            {},
            provider="anthropic",
            model="test-model",
            top_n=1,
        )
    )

    assert result["selected"] == []
    assert result["failure_type"] == "provider_error"
    assert result["selection_failure"] == "provider unavailable"
    assert result["raw_output"] is None


@pytest.mark.parametrize("provider", ["anthropic", "google", "openai"])
@pytest.mark.parametrize("text,diagnostics,kind", [
    ("42", {"stop_reason": "end_turn"}, None),
    ("", {"stop_reason": "refusal", "content_block_types": []}, "refusal"),
    ("Cannot answer.", {"stop_reason": "refusal"}, "refusal"),
    ("", {"content_block_types": ["refusal"]}, "refusal"),
    ("", {"stop_reason": "end_turn"}, "empty_output"),
    (" \n\t", {}, "empty_output"),
    ("", {"stop_reason": "max_tokens", "content_block_types": ["thinking"]}, "empty_output"),
])
def test_generation_outcomes_preserve_response(monkeypatch, provider, text, diagnostics, kind):
    import asyncio
    generation = {"text": text, "provider": provider, "model": "fixture",
                  "response_diagnostics": diagnostics, "output_tokens": 0, "latency_seconds": 0.1}
    calls = []

    async def generate(*args, **kwargs):
        calls.append(kwargs)
        return generation

    monkeypatch.setattr(app, "generate_answer", generate)
    result = asyncio.run(app.generate_answer_safe(
        "query", [], provider=provider, model="fixture",
    ))
    assert len(calls) == 1
    assert result["generation"] is generation
    if kind is None:
        assert result["failure"] is None
    else:
        failure = result["failure"]
        assert failure["failure_type"] == kind
        assert failure["answer_score"] == "generation_failure"
        assert failure["answer"] == text
        assert failure["generation"] is generation
        assert failure["response_diagnostics"] == diagnostics


@pytest.mark.parametrize("status,category", [(429, "rate_or_quota_limit"), (503, "service_unavailable")])
def test_provider_diagnostics_are_explicit_and_redacted(status, category):
    from benchmarks.context_evaluation.heldout.diagnostics import safe_artifact

    class ProviderError(Exception):
        status_code = status

    diagnostics = app.provider_error_diagnostics(ProviderError("secret body"))
    result = safe_artifact({"response_diagnostics": diagnostics})
    assert result["response_diagnostics"] == {
        "http_status": status, "error_type": "ProviderError", "error_category": category,
    }


def test_prompt_injection_runner_uses_shared_cases():
    from .adversarial.prompt_injection import cases, run_benchmark

    assert run_benchmark.QUERY == cases.QUERY
    assert run_benchmark.clean_results is cases.clean_results
    assert run_benchmark.provenance_injection is cases.provenance_injection
    clean = cases.clean_results()
    injected = cases.provenance_injection()
    assert clean[:-1] == injected[:-1]
    assert "Source provenance:" in injected[-1]["text"]
    assert clean[-1]["text"] == "The payments-api retention period is 30 days."
