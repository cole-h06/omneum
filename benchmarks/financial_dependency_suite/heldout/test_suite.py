import asyncio

import pytest

from benchmarks.financial_dependency_suite.heldout.artifacts import checkpoint
import benchmarks.financial_dependency_suite.heldout.suite as suite
from benchmarks.financial_dependency_suite.heldout.methods import METHODS, MethodSpec
from benchmarks.financial_dependency_suite.heldout.test_runner import (
    case,
    truth,
)


def test_trial_counts(monkeypatch):
    async def fake_run_method(method, case, truth, **kwargs):
        return {
            "selected": ["source_a"],
            "answer_score": "correct",
        }

    monkeypatch.setattr(
        suite,
        "run_method",
        fake_run_method,
    )

    records = asyncio.run(
        suite.run_case(
            case(),
            truth(),
            trials=3,
            generator_provider="anthropic",
            generator_model="generator",
            methods=METHODS,
        )
    )

    assert len(records) == len(METHODS) * 3
    expected_methods = {
        "vector", "bge", "cohere", "anthropic", "openai", "google",
        "anthropic_provenance", "openai_provenance", "google_provenance", "omneum",
    }
    assert {method.name for method in METHODS} == expected_methods
    assert {record["method"] for record in records} == expected_methods
    for method in METHODS:
        assert [record["trial"] for record in records if record["method"] == method.name] == [1, 2, 3]


def test_deterministic_and_provider_methods_run_all_requested_trials(monkeypatch):
    async def fake_run_method(method, case, truth, **kwargs):
        return {"selected": ["source_a"], "answer_score": "correct"}

    monkeypatch.setattr(suite, "run_method", fake_run_method)
    methods = (
        MethodSpec(name="deterministic_fixture", method="vector", stochastic=False),
        MethodSpec(name="provider_fixture", method="llm", provider="anthropic",
                   model="fixture", stochastic=True),
    )
    records = asyncio.run(suite.run_case(
        case(), truth(), trials=4, generator_provider="anthropic",
        generator_model="generator", methods=methods,
    ))

    assert len(records) == 2 * 4
    for method in methods:
        assert [r["trial"] for r in records if r["method"] == method.name] == [1, 2, 3, 4]


def test_structured_provider_error_is_committed_and_logged(tmp_path, caplog, monkeypatch):
    import json
    import logging

    error = ('Error code: 429 - {"type":"error","error":{"type":"rate_limit_error",'
             '"code":"rate_limit_exceeded","message":"Too many requests"}}')

    async def failed(*args, **kwargs):
        return {
            "selected": [],
            "answer_score": "selection_failure",
            "failure_type": "provider_error",
            "error": error,
            "selection": {"provider": "anthropic", "model": "fixture"},
            "response_diagnostics": {"http_status": 429, "error_type": "RateLimitError"},
        }

    monkeypatch.setattr(suite, "run_method", failed)
    path = tmp_path / "results.jsonl"
    caplog.set_level(logging.WARNING)
    asyncio.run(suite.run_case(
        case(), truth(), trials=1, generator_provider="anthropic", generator_model="fixture",
        methods=(MethodSpec(name="anthropic", method="llm", provider="anthropic", model="fixture"),),
        on_result=lambda record: checkpoint(path, [record]),
    ))

    saved = json.loads(path.read_text())
    assert saved["case_id"] == "test_case"
    assert saved["answer_score"] == "selection_failure"
    assert saved["diagnostics"]["provider_error_details"]["type"] == "rate_limit_error"
    assert saved["diagnostics"]["provider_error_details"]["code"] == "rate_limit_exceeded"
    assert "Failed case_id=test_case method=anthropic trial=1" in caplog.text
    assert "Provider request failed; see diagnostic type and status." in caplog.text


def test_case_truth_mismatch():
    bad_truth = truth()
    object.__setattr__(
        bad_truth,
        "case_id",
        "different_case",
    )

    with pytest.raises(
        ValueError,
        match="case/truth mismatch",
    ):
        asyncio.run(
            suite.run_case(
                case(),
                bad_truth,
                trials=1,
                generator_provider="anthropic",
                generator_model="generator",
                methods=(),
            )
        )


def test_unexpected_execution_error_identifies_attempt(monkeypatch, caplog):
    async def broken(*args, **kwargs):
        raise KeyError("selected")

    monkeypatch.setattr(suite, "run_method", broken)
    with pytest.raises(KeyError) as error:
        asyncio.run(suite.run_case(
            case(), truth(), trials=1,
            generator_provider="anthropic", generator_model="generator",
            methods=(MethodSpec(name="anthropic", method="llm"),),
        ))
    context = "case_id=test_case method=anthropic trial=1"
    assert context in caplog.text
    assert context in error.value.__notes__
