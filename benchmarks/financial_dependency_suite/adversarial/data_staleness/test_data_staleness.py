import asyncio

import pytest

from benchmarks.financial_dependency_suite.adversarial.data_staleness.cases import (
    dependent_stale_data,
    independent_stale_data,
)
from benchmarks.financial_dependency_suite.adversarial.data_staleness.application import (
    QUERY,
)
from benchmarks.financial_dependency_suite.omneum_rag import (
    evaluate_context,
    map_observations,
)
from benchmarks.financial_dependency_suite.config import estimator_config


def _mapped(case):
    return map_observations(
        case["documents"],
        case["observations"],
        case["source_ids"],
    )


def _claim_by_value(evaluation, value):
    return next(
        claim
        for claim in evaluation.claim_support
        if claim.claim.value == value
    )


@pytest.mark.anyio
async def test_dependency_changes_stale_data_conflict():
    dependent = dependent_stale_data()
    independent = independent_stale_data()

    dependent_result = await evaluate_context(
        _mapped(dependent),
        estimator=estimator_config(),
    )
    independent_result = await evaluate_context(
        _mapped(independent),
        estimator=estimator_config(),
    )

    dependent_stale = _claim_by_value(
        dependent_result,
        30,
    )
    dependent_current = _claim_by_value(
        dependent_result,
        90,
    )

    independent_stale = _claim_by_value(
        independent_result,
        30,
    )
    independent_current = _claim_by_value(
        independent_result,
        90,
    )

    print("\nDEPENDENT STALE DATA")
    print(
        f"30 days: support={dependent_stale.support:.6f} | "
        f"independent="
        f"{dependent_stale.estimated_independent_support_count:.6f} | "
        f"winner={dependent_stale.is_attribute_max_support}"
    )
    print(
        f"90 days: support={dependent_current.support:.6f} | "
        f"independent="
        f"{dependent_current.estimated_independent_support_count:.6f} | "
        f"winner={dependent_current.is_attribute_max_support}"
    )

    print("\nINDEPENDENT STALE DATA")
    print(
        f"30 days: support={independent_stale.support:.6f} | "
        f"independent="
        f"{independent_stale.estimated_independent_support_count:.6f} | "
        f"winner={independent_stale.is_attribute_max_support}"
    )
    print(
        f"90 days: support={independent_current.support:.6f} | "
        f"independent="
        f"{independent_current.estimated_independent_support_count:.6f} | "
        f"winner={independent_current.is_attribute_max_support}"
    )

    assert (
        dependent_stale.estimated_independent_support_count
        < independent_stale.estimated_independent_support_count
    )

    assert dependent_current.support > dependent_stale.support

    assert dependent_current.is_attribute_max_support
    assert not dependent_stale.is_attribute_max_support

    # v4 uses max(0, 1 - |delta| / window) for temporal proximity,
    # not recency. Equal current timestamps give each pair d=0.1;
    # the independent stale timestamps are all outside the two-day window.
    # Effective count is n² / (n + 2Σd). The stale chain has two d=1 edges.
    assert dependent_stale.estimated_independent_support_count == pytest.approx(9 / 7)
    assert independent_stale.estimated_independent_support_count == pytest.approx(3.0)
    for current in (dependent_current, independent_current):
        assert current.estimated_independent_support_count == pytest.approx(2.5)

    assert independent_stale.support > independent_current.support
    assert independent_stale.is_attribute_max_support
    assert not independent_current.is_attribute_max_support


@pytest.mark.anyio
async def test_stale_selection():
    dependent = dependent_stale_data()
    independent = independent_stale_data()

    from benchmarks.financial_dependency_suite.omneum_rag import (
        select_context,
    )

    dependent_mapped = _mapped(dependent)
    dependent_result = await evaluate_context(
        dependent_mapped,
        estimator=estimator_config(),
    )
    dependent_selected = select_context(
        QUERY,
        dependent_mapped,
        dependent_result,
        top_n=6,
    )

    independent_mapped = _mapped(independent)
    independent_result = await evaluate_context(
        independent_mapped,
        estimator=estimator_config(),
    )
    independent_selected = select_context(
        QUERY,
        independent_mapped,
        independent_result,
        top_n=6,
    )

    print("\nDEPENDENT SELECTED")
    for item in dependent_selected:
        print(
            item["retrieved"]["source"],
            "claim=", item["claim"].value,
            "relevance=", round(item["relevance"], 4),
            "support=", round(item["claim_support"], 4),
            "contribution=", round(item["omneum_contribution"], 4),
            "score=", round(item["selection_score"], 4),
        )

    print("\nINDEPENDENT SELECTED")
    for item in independent_selected:
        print(
            item["retrieved"]["source"],
            "claim=", item["claim"].value,
            "relevance=", round(item["relevance"], 4),
            "support=", round(item["claim_support"], 4),
            "contribution=", round(item["omneum_contribution"], 4),
            "score=", round(item["selection_score"], 4),
        )

    assert {
        item["claim"].value
        for item in dependent_selected
    } == {90}

    independent_values = [
        item["claim"].value
        for item in independent_selected
    ]

    # Only winners are eligible; top_n is a cap, not a backfill requirement.
    # The independent stale claim wins under v4's temporal dependency signal.
    assert independent_values == [30, 30, 30]
    assert {
        item["retrieved"]["source"]
        for item in independent_selected
    } == {"stale_origin", "stale_copy_a", "stale_copy_b"}
    assert {
        item["retrieved"]["source"]
        for item in dependent_selected
    } == {"current_a", "current_b", "current_c"}
