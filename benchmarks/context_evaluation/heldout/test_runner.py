import asyncio

import pytest
from dataclasses import replace
from datetime import datetime, timezone

import benchmarks.context_evaluation.heldout.runner as runner
from benchmarks.context_evaluation.heldout.schema import (
    AnswerScoring,
    BenchmarkCase,
    CandidateSpec,
    GroundTruth,
    ProvenanceSpec,
    SourceSpec,
)


def case():
    source = SourceSpec(
        kind="web_document",
        identifier="https://example.com/a",
    )
    provenance = ProvenanceSpec(
        assertion_id="assertion-a",
        observed_at=datetime(
            2026, 9, 11, tzinfo=timezone.utc
        ),
        source_modified_at=None,
        upstream_sources=(),
        cited_sources=(),
        parent_assertion_ids=(),
    )

    return BenchmarkCase(
        case_id="test_case",
        domain="test",
        question="What was the value?",
        context_budget=1,
        candidates=(
            CandidateSpec(
                source_id="source_a",
                source=source,
                text="The value was 42.",
                entity_namespace="test",
                entity="example",
                attribute="value",
                value=42,
                provenance=provenance,
            ),
        ),
    )


def truth():
    return GroundTruth(
        case_id="test_case",
        answer="42",
        supporting_sources=("source_a",),
        scoring=AnswerScoring(
            required=("42",),
            forbidden=("99",),
        ),
    )


def test_run_method(monkeypatch):
    async def fake_selection(*args, **kwargs):
        selection = {
            "selected": [
                {
                    "source": "source_a",
                    "text": "The value was 42.",
                }
            ],
            "provider": "anthropic",
            "model": "selector",
            "latency_seconds": 0.1,
            "input_tokens": 10,
            "output_tokens": 2,
            "parse_error": None,
            "raw_output": (
                '{"selected_sources":["source_a"]}'
            ),
        }

        return {"selection": selection, "failure": None}

    async def fake_generation(*args, **kwargs):
        return {
            "generation": {
                "text": "The value was 42.",
                "provider": "anthropic",
                "model": "generator",
                "latency_seconds": 0.2,
                "input_tokens": 20,
                "output_tokens": 5,
            },
            "failure": None,
        }

    monkeypatch.setattr(
        runner,
        "select_llm_safe",
        fake_selection,
    )
    monkeypatch.setattr(
        runner,
        "generate_answer_safe",
        fake_generation,
    )

    result = asyncio.run(
        runner.run_method(
            "llm",
            case(),
            truth(),
            provider="anthropic",
            model="selector",
            generator_provider="anthropic",
            generator_model="generator",
        )
    )

    assert result["selected"] == ["source_a"]
    assert result["selection_score"]["precision"] == 1.0
    assert result["selection_score"]["recall"] == 1.0
    assert result["answer_score"] == "correct"
    assert result["end_to_end_latency_seconds"] == pytest.approx(0.3)


def test_selection_failure(monkeypatch):
    async def fake_selection(*args, **kwargs):
        return {
            "selected": [],
            "provider": "openai",
            "model": "selector",
            "latency_seconds": None,
            "input_tokens": None,
            "output_tokens": None,
            "parse_error": None,
            "raw_output": None,
            "selection_failure": "provider unavailable",
            "failure_type": "provider_error",
        }

    monkeypatch.setattr(
        runner,
        "select_llm_provenance_safe",
        fake_selection,
    )

    result = asyncio.run(
        runner.run_method(
            "llm_provenance",
            case(),
            truth(),
            provider="openai",
            model="selector",
            generator_provider="anthropic",
            generator_model="generator",
        )
    )

    assert result["answer_score"] == "selection_failure"
    assert result["failure_type"] == "provider_error"
    assert result["generation"] is None


def test_ground_truth_does_not_change_selection(monkeypatch):
    seen = []

    async def fake_selection(method, benchmark_case, **kwargs):
        seen.append(benchmark_case)
        return {
            "selected": [
                {
                    "source": "source_a",
                    "text": "The value was 42.",
                }
            ],
            "model": "test",
            "latency_seconds": 0.1,
        }

    async def fake_generation(*args, **kwargs):
        return {
            "generation": {
                "text": "The value was 42.",
                "provider": "anthropic",
                "model": "generator",
                "latency_seconds": 0.2,
                "input_tokens": 20,
                "output_tokens": 5,
            },
            "failure": None,
        }

    monkeypatch.setattr(
        runner,
        "run_selection",
        fake_selection,
    )
    monkeypatch.setattr(
        runner,
        "generate_answer_safe",
        fake_generation,
    )

    first = truth()
    second = replace(
        first,
        answer="99",
        scoring=AnswerScoring(
            required=("99",),
            forbidden=("42",),
        ),
    )

    asyncio.run(
        runner.run_method(
            "vector",
            case(),
            first,
            generator_provider="anthropic",
            generator_model="generator",
        )
    )
    asyncio.run(
        runner.run_method(
            "vector",
            case(),
            second,
            generator_provider="anthropic",
            generator_model="generator",
        )
    )

    assert seen[0] == seen[1]


@pytest.mark.parametrize("method,outcome", [
    (method, outcome)
    for method in ("llm", "llm_provenance", "cohere")
    for outcome in ("success", "provider_error", "parse_error", "generation_failure")
    if (method, outcome) != ("cohere", "parse_error")
])
def test_real_safe_selector_contracts(monkeypatch, method, outcome):
    import benchmarks.context_evaluation.application_comparison as app

    raw = ('{"selected_sources":["source_a"]}'
           if outcome != "parse_error" else "invalid JSON")

    async def fake_generate(*args, **kwargs):
        if outcome == "provider_error":
            raise RuntimeError("provider unavailable")
        return {
            "text": raw, "provider": "anthropic", "model": "selector",
            "latency_seconds": 0.1, "input_tokens": 10, "output_tokens": 2,
        }

    def fake_rerank(query, candidates, *, top_n):
        if outcome == "provider_error":
            raise RuntimeError("provider unavailable")
        assert top_n == 1
        return {"selected": candidates, "latency_seconds": 0.1, "model": "test"}

    generated = []

    async def fake_answer(query, documents, **kwargs):
        generated.append(documents)
        if outcome == "generation_failure":
            raise RuntimeError("generator unavailable")
        return {"text": "42", "latency_seconds": 0.2}

    monkeypatch.setattr(app, "generate", fake_generate)
    monkeypatch.setattr(app, "rerank_cohere", fake_rerank)
    monkeypatch.setattr(app, "answer_from_context", fake_answer)
    result = asyncio.run(runner.run_method(
        method, case(), truth(), provider="anthropic", model="selector",
        generator_provider="anthropic", generator_model="generator",
    ))

    if outcome in ("provider_error", "parse_error"):
        assert not generated
        assert result["answer_score"] == "selection_failure"
        assert result["failure_type"] == outcome
        assert result["generation"] is None
        assert "selection_score" not in result
        if outcome == "parse_error":
            assert result["selection"]["raw_output"] == raw
        else:
            assert "provider unavailable" in result["error"]
    else:
        assert generated[0][0]["source"] == "source_a"
        assert result["selected"] == ["source_a"]
        if outcome == "generation_failure":
            assert result["answer_score"] == "generation_failure"
            assert result["selection"]["selected"][0]["source"] == "source_a"
        else:
            assert result["answer_score"] == "correct"
            assert result["end_to_end_latency_seconds"] == pytest.approx(0.3)


@pytest.mark.parametrize("field", ["selection_failure", "parse_error"])
def test_empty_provenance_error_is_still_failure(monkeypatch, field):
    async def fake_selection(*args, **kwargs):
        return {"selected": [], field: "", "failure_type": "provider_error"}

    async def unexpected_generation(*args, **kwargs):
        pytest.fail("Failed selection must not generate an answer")

    monkeypatch.setattr(runner, "select_llm_provenance_safe", fake_selection)
    monkeypatch.setattr(runner, "generate_answer_safe", unexpected_generation)
    result = asyncio.run(runner.run_method(
        "llm_provenance", case(), truth(), provider="anthropic", model="selector",
        generator_provider="anthropic", generator_model="generator",
    ))
    assert result["answer_score"] == "selection_failure"
    assert result["error"] == ""


@pytest.mark.parametrize("reason,kind", [("refusal", "refusal"), ("end_turn", "empty_output")])
def test_generation_outcome_reaches_summary_and_artifact(monkeypatch, tmp_path, reason, kind):
    import json
    from benchmarks.context_evaluation import application_comparison as app
    from .aggregate import summarize
    from .artifacts import checkpoint

    async def select(*args, **kwargs):
        return {"selected": [{"source": "source_a", "text": "A"}], "latency_seconds": 0.1}

    async def generate(*args, **kwargs):
        return {"text": "", "provider": "anthropic", "model": "generator",
                "output_tokens": 0, "response_diagnostics": {
                    "stop_reason": reason, "content_block_types": [],
                }}

    def unexpected_score(*args):
        pytest.fail("Unanswered generations must not enter answer scoring")

    monkeypatch.setattr(runner, "run_selection", select)
    monkeypatch.setattr(app, "generate_answer", generate)
    monkeypatch.setattr(runner, "score_answer", unexpected_score)
    record = asyncio.run(runner.run_method(
        "vector", case(), truth(), generator_provider="anthropic", generator_model="generator",
    ))
    record.update(method="fixture", case_id="fixture", trial=1)
    path = tmp_path / "results.jsonl"
    checkpoint(path, [record])
    saved = json.loads(path.read_text())
    assert saved["selected"] == ["source_a"]
    assert saved["answer"] == ""
    assert saved["generation"]["response_diagnostics"]["stop_reason"] == reason
    summary = summarize([saved])["fixture"]
    assert summary["unscored"] == 0
    assert summary["failures"] == summary["generation_failures"] == 1
    assert summary["selection_failures"] == 0
    assert summary["generation_failure_types"] == {kind: 1}
