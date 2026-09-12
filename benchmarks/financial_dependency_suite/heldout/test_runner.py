import asyncio

import pytest
from dataclasses import replace
from datetime import datetime, timezone

import benchmarks.financial_dependency_suite.heldout.runner as runner
from benchmarks.financial_dependency_suite.heldout.schema import (
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
        return {
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
        "select_llm_safe",
        fake_selection,
    )

    result = asyncio.run(
        runner.run_method(
            "llm",
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
