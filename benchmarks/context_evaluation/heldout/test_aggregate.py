from benchmarks.context_evaluation.heldout.aggregate import (
    summarize,
)
import pytest


def test_summary_denominator():
    records = [
        {
            "method": "test",
            "answer_score": "correct",
            "selection_score": {
                "precision": 1.0,
                "recall": 1.0,
            },
        },
        {
            "method": "test",
            "answer_score": "incorrect",
            "selection_score": {
                "precision": 0.5,
                "recall": 0.5,
            },
        },
        {
            "method": "test",
            "answer_score": "unscored",
            "selection_score": {
                "precision": 0.0,
                "recall": 0.0,
            },
        },
        {
            "method": "test",
            "answer_score": "selection_failure",
        },
    ]

    result = summarize(records)["test"]

    assert result["attempted"] == 4
    assert result["correct"] == 1
    assert result["incorrect"] == 1
    assert result["unscored"] == 1
    assert result["failures"] == 1
    assert result["accuracy"] == 0.25
    assert result["evaluable_accuracy"] == 0.5
    assert result["selection_precision"] == 0.5
    assert result["selection_recall"] == 0.5


def test_empty_summary():
    assert summarize([]) == {}


def test_generation_failures_are_separate_from_unscored():
    result = summarize([
        {"method": "fixture", "answer_score": "generation_failure", "failure_type": kind}
        for kind in ("provider_error", "refusal", "empty_output")
    ] + [
        {"method": "fixture", "answer_score": "unscored"},
        {"method": "fixture", "answer_score": "selection_failure", "failure_type": "provider_error"},
    ])["fixture"]
    assert result["attempted"] == 5
    assert result["unscored"] == 1
    assert result["failures"] == 4
    assert result["selection_failures"] == 1
    assert result["generation_failures"] == 3
    assert result["generation_failure_types"] == {"provider_error": 1, "refusal": 1, "empty_output": 1}


def test_failure_types_and_unscored_are_not_incorrect():
    records = [
        {"method": "test", "answer_score": "selection_failure", "failure_type": "parse_error"},
        {"method": "test", "answer_score": "selection_failure", "failure_type": "provider_error"},
        {"method": "test", "answer_score": "generation_failure", "failure_type": "provider_error"},
        {"method": "test", "answer_score": "unscored"},
        {"method": "test", "answer_score": "correct"},
        {"method": "test", "answer_score": "incorrect"},
    ]
    result = summarize(records)["test"]
    assert result["incorrect"] == 1
    assert result["unscored"] == 1
    assert result["failures"] == 3
    assert result["accuracy"] == 1 / 6
    assert result["evaluable_accuracy"] == 1 / 2
    assert records[0]["failure_type"] == "parse_error"
    assert records[1]["failure_type"] == "provider_error"


def test_method_aggregation():
    records = [
        {
            "method": "alpha", "answer_score": "correct",
            "selection": {"latency_seconds": 2.0},
            "generation": {"latency_seconds": 3.0, "input_tokens": 10, "output_tokens": 5},
            "end_to_end_latency_seconds": 5.0,
        },
        {
            "method": "alpha", "answer_score": "incorrect",
            "selection": {"latency_seconds": 4.0},
            "generation": {"latency_seconds": 7.0, "input_tokens": 20, "output_tokens": 10},
        },
        {
            "method": "alpha", "answer_score": "generation_failure",
            "failure_type": "provider_error", "selection": {"latency_seconds": None},
            "generation": None,
        },
        {
            "method": "beta", "answer_score": "correct",
            "selection": {"latency_seconds": 2.0, "evaluation_latency_seconds": 0.5},
            "generation": {"latency_seconds": 3.0, "input_tokens": 10, "output_tokens": 5},
        },
        {
            "method": "beta", "answer_score": "incorrect",
            "selection": {"latency_seconds": 4.0, "evaluation_latency_seconds": 1.0},
            "generation": {"latency_seconds": 7.0, "input_tokens": 20, "output_tokens": 10},
        },
    ]
    result = summarize(records)
    for method in ("alpha", "beta"):
        metrics = result[method]
        assert metrics["generator_usage"]["input_tokens"] == {"n": 2, "sum": 30}
        assert metrics["generator_usage"]["output_tokens"] == {"n": 2, "sum": 15}
        assert metrics["generator_usage"]["total_tokens"] == {"n": 2, "sum": 45}
        assert metrics["generator_usage"]["token_efficiency"]["correct_per_1000_tokens"] == pytest.approx(1000 / 45)
        assert metrics["latency"]["selection_seconds"]["p50"] == 3.0
        assert metrics["latency"]["selection_seconds"]["p95"] == pytest.approx(3.9)
        assert metrics["latency"]["end_to_end_seconds"]["p50"] == 8.0
        assert metrics["inference_cost"] == {"usd": None, "availability": "no_pricing_defined"}
    assert result["alpha"]["latency"]["selection_seconds"]["coverage"] == pytest.approx(2 / 3)
    assert result["beta"]["latency"]["omneum_evaluator_seconds"]["p50"] == 0.75
    assert result["beta"]["latency"]["omneum_integration_overhead_seconds"]["p50"] == 2.25
    assert result["alpha"]["latency"]["omneum_evaluator_seconds"]["n"] == 0


def test_missing_generator_usage_is_unavailable_not_inferred():
    result = summarize([{
        "method": "fixture", "answer_score": "correct",
        "selection": {"latency_seconds": 1.0},
        "generation": {"latency_seconds": 1.0, "input_tokens": 5, "output_tokens": None},
    }])["fixture"]
    usage = result["generator_usage"]
    assert usage["input_tokens"] == {"n": 1, "sum": 5}
    assert usage["output_tokens"] == {"n": 0, "sum": None}
    assert usage["total_tokens"] == {"n": 0, "sum": None}
    assert usage["token_efficiency"]["correct_per_1000_tokens"] is None
    assert result["latency"]["end_to_end_seconds"]["n"] == 1


def test_route_latency_components():
    result = summarize([{
        "method": "anthropic_omneum", "answer_score": "correct",
        "selection": {
            "latency_seconds": .6,
            "cold_integration_latency_seconds": .4,
            "evaluation_latency_seconds": .1,
            "evaluator_input_tokens": 12,
            "evaluator_output_tokens": 3,
        },
        "generation": {"latency_seconds": .5, "input_tokens": 10, "output_tokens": 2},
    }])["anthropic_omneum"]
    latency = result["latency"]
    assert latency["selection_seconds"]["p50"] == pytest.approx(.6)
    assert latency["omneum_evaluator_seconds"]["p50"] == pytest.approx(.1)
    assert latency["omneum_integration_overhead_seconds"]["p50"] == pytest.approx(.3)
    assert latency["evaluator_input_tokens"] == {"n": 1, "sum": 12}
    assert latency["evaluator_output_tokens"] == {"n": 1, "sum": 3}
