import asyncio

import pytest

import benchmarks.financial_dependency_suite.heldout.suite as suite
from benchmarks.financial_dependency_suite.heldout.methods import (
    MethodSpec,
)
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

    methods = (
        MethodSpec(
            name="vector",
            method="vector",
        ),
        MethodSpec(
            name="anthropic",
            method="llm",
            provider="anthropic",
            model="selector",
            stochastic=True,
        ),
        MethodSpec(
            name="braid",
            method="braid",
        ),
    )

    records = asyncio.run(
        suite.run_case(
            case(),
            truth(),
            trials=3,
            generator_provider="anthropic",
            generator_model="generator",
            methods=methods,
        )
    )

    assert len(records) == 5

    assert [
        record["trial"]
        for record in records
        if record["method"] == "vector"
    ] == [1]

    assert [
        record["trial"]
        for record in records
        if record["method"] == "anthropic"
    ] == [1, 2, 3]

    assert [
        record["trial"]
        for record in records
        if record["method"] == "braid"
    ] == [1]


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
