import pytest

from .cases import (
    CORRECT_VALUE,
    FALSE_VALUE,
    balanced_control,
    conflict,
)
from ...braid_rag import evaluate_context, map_observations
from ...config import estimator_config


def target_observations(case):
    return tuple(
        observation
        for observation in case["observations"]
        if observation.claim.value in {
            CORRECT_VALUE,
            FALSE_VALUE,
        }
    )


async def evaluate(case):
    documents = {
        item["source"]: item["text"]
        for item in case["documents"]
    }

    target = target_observations(case)

    mapped = [
        {
            "retrieved": {
                "source": case["source_ids"][observation.source],
                "score": 0.0,
                "text": documents[
                    case["source_ids"][observation.source]
                ],
            },
            "observation": observation,
        }
        for observation in target
    ]

    mapped.extend(
        {
            "retrieved": {
                "source": case["source_ids"][observation.source],
                "score": 0.0,
                "text": "",
            },
            "observation": observation,
        }
        for observation in case["observations"]
        if observation not in target
    )

    return await evaluate_context(
        mapped,
        estimator=estimator_config(),
    )


def by_value(evaluation):
    return {
        claim.claim.value: claim
        for claim in evaluation.claim_support
        if claim.claim.value in {
            CORRECT_VALUE,
            FALSE_VALUE,
        }
    }


def test_case_shape():
    treatment = conflict()
    control = balanced_control()

    assert len(control["observations"]) == 6
    assert len(treatment["observations"]) == 18

    target = target_observations(treatment)

    assert len(target) == 6

    assert sum(
        observation.claim.value == CORRECT_VALUE
        for observation in target
    ) == 3

    assert sum(
        observation.claim.value == FALSE_VALUE
        for observation in target
    ) == 3


@pytest.mark.anyio
async def test_balanced_control_ties():
    evaluation = await evaluate(
        balanced_control()
    )
    claims = by_value(evaluation)

    assert claims[CORRECT_VALUE].support == pytest.approx(
        claims[FALSE_VALUE].support
    )
    assert claims[CORRECT_VALUE].is_attribute_max_support
    assert claims[FALSE_VALUE].is_attribute_max_support


@pytest.mark.anyio
async def test_network_breaks_tie():
    evaluation = await evaluate(
        conflict()
    )
    claims = by_value(evaluation)

    assert (
        claims[CORRECT_VALUE].support
        > claims[FALSE_VALUE].support
    )
    assert claims[CORRECT_VALUE].is_attribute_max_support
    assert not claims[FALSE_VALUE].is_attribute_max_support


def test_application_case():
    from .application import case_data

    candidates, observations, source_ids = case_data()

    assert len(candidates) == 6
    assert len(observations) == 18
    assert len(source_ids) == 6

    candidate_ids = {
        candidate["source"]
        for candidate in candidates
    }

    assert candidate_ids == set(source_ids.values())


@pytest.mark.anyio
async def test_application_braid(monkeypatch):
    from ... import application_comparison
    from .application import case_data

    candidates, observations, source_ids = case_data()
    seen = {}

    async def evaluate(mapped, *, estimator):
        seen["count"] = len(mapped)
        return object()

    def select(mapped, evaluation, *, top_n):
        seen["selectable"] = len(mapped)
        return []

    monkeypatch.setattr(
        "benchmarks.financial_dependency_suite.braid_rag.evaluate_context",
        evaluate,
    )
    monkeypatch.setattr(
        "benchmarks.financial_dependency_suite.braid_rag.select_context",
        select,
    )

    await application_comparison.select_braid(
        candidates,
        observations,
        source_ids,
        estimator=object(),
        top_n=3,
        evaluation_observations=observations,
    )

    assert seen["count"] == 18
    assert seen["selectable"] == 6


def test_summary_provider_failure():
    from .application import summary

    failure = {
        "selected": [],
        "selection": {
            "model": "gemini-3.8-flash",
            "provider": "google",
            "latency_seconds": None,
            "input_tokens": None,
            "output_tokens": None,
        },
        "answer": None,
        "answer_score": "selection_failure",
        "generation": None,
        "failure_type": "provider_error",
        "error": "ServerError: 503 UNAVAILABLE",
    }

    report = summary([
        {
            "methods": {
                "llm_google": failure,
            }
        }
    ])

    result = report["methods"]["llm_google"]

    assert result["selection_failures"] == 1
    assert result["correct"] == 0
    assert result["mean_selection_latency_seconds"] is None
    assert result["mean_generation_latency_seconds"] is None
    assert result["mean_end_to_end_latency_seconds"] is None
