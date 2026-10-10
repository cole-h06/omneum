"""Tests for routing strategies and escalation behavior."""

from types import SimpleNamespace

import pytest

from examples.langgraph.routing.graph import escalate
from examples.langgraph.routing.policy import (
    RoutingPolicy,
    assess_context,
)
from examples.langgraph.routing.retrieval import (
    retrieve_additional_evidence,
)


@pytest.mark.parametrize(
    "strategy",
    [
        "retrieve_support",
        "resolve_conflicts",
        "diversify_sources",
    ],
)
def test_retrieval_strategy(strategy):
    observations = retrieve_additional_evidence(
        ("processing_region",),
        strategy=strategy,
    )

    assert len(observations) == 1
    assert observations[0].claim.attribute == "processing_region"
    assert observations[0].claim.value == "EU"
    assert observations[0].observation_id.startswith(
        f"routing-{strategy}-"
    )


def test_strategies_use_distinct_sources():
    observations = [
        retrieve_additional_evidence(
            ("processing_region",),
            strategy=strategy,
        )[0]
        for strategy in (
            "retrieve_support",
            "resolve_conflicts",
            "diversify_sources",
        )
    ]

    assert len({item.source.identifier for item in observations}) == 3
    assert len({item.source.owner_id for item in observations}) == 3


def test_retrieval_attempts_use_distinct_sources():
    first = retrieve_additional_evidence(
        ("processing_region",),
        strategy="retrieve_support",
        attempt=1,
    )
    second = retrieve_additional_evidence(
        ("processing_region",),
        strategy="retrieve_support",
        attempt=2,
    )

    assert first[0].source.identifier != second[0].source.identifier
    assert first[0].observation_id != second[0].observation_id


def test_retrieval_targets_requested_attributes():
    observations = retrieve_additional_evidence(
        ("processing_region", "processing_region"),
        strategy="retrieve_support",
    )

    assert len(observations) == 1
    assert observations[0].claim.attribute == "processing_region"


def test_invalid_strategy():
    with pytest.raises(ValueError):
        retrieve_additional_evidence(
            ("processing_region",),
            strategy="unknown",
        )


def test_invalid_attempt():
    with pytest.raises(ValueError):
        retrieve_additional_evidence(
            ("processing_region",),
            strategy="retrieve_support",
            attempt=3,
        )


def test_retry_limit_escalates():
    evaluation = SimpleNamespace(claim_support=())

    decision = assess_context(
        evaluation,
        retries=2,
        policy=RoutingPolicy(max_retries=2),
    )

    assert decision.route == "escalate"
    assert decision.attributes


def test_escalation_answer():
    result = escalate({})

    assert "ESCALATE" in result["answer"]
    assert "EVALUATION COMPLETE" not in result["answer"]
