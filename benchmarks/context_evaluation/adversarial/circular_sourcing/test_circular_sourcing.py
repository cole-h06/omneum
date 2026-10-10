import pytest

from benchmarks.context_evaluation.adversarial.circular_sourcing.cases import (
    independent_sources_control,
    circular_sources,
)
from benchmarks.context_evaluation.omneum_rag import (
    evaluate_context,
    map_observations,
)
from benchmarks.context_evaluation.config import estimator_config


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
async def test_circular_sources_is_discounted():
    circular = circular_sources()
    control = independent_sources_control()

    circular_result = await evaluate_context(
        _mapped(circular),
        estimator=estimator_config(),
    )
    control_result = await evaluate_context(
        _mapped(control),
        estimator=estimator_config(),
    )

    circular_30 = _claim_by_value(circular_result, 30)
    circular_60 = _claim_by_value(circular_result, 60)

    control_30 = _claim_by_value(control_result, 30)
    control_60 = _claim_by_value(control_result, 60)

    print("\nCIRCULAR CONSENSUS")
    print(
        f"30 seconds: support={circular_30.support:.6f} | "
        f"independent="
        f"{circular_30.estimated_independent_support_count:.6f} | "
        f"winner={circular_30.is_attribute_max_support}"
    )
    print(
        f"60 seconds: support={circular_60.support:.6f} | "
        f"independent="
        f"{circular_60.estimated_independent_support_count:.6f} | "
        f"winner={circular_60.is_attribute_max_support}"
    )

    print("\nACYCLIC CONTROL")
    print(
        f"30 seconds: support={control_30.support:.6f} | "
        f"independent="
        f"{control_30.estimated_independent_support_count:.6f} | "
        f"winner={control_30.is_attribute_max_support}"
    )
    print(
        f"60 seconds: support={control_60.support:.6f} | "
        f"independent="
        f"{control_60.estimated_independent_support_count:.6f} | "
        f"winner={control_60.is_attribute_max_support}"
    )

    assert (
        circular_30.estimated_independent_support_count
        < control_30.estimated_independent_support_count
    )

    assert circular_60.support > circular_30.support
    assert circular_60.is_attribute_max_support
    assert not circular_30.is_attribute_max_support

    assert control_30.support == pytest.approx(
        control_60.support
    )
    assert control_30.is_attribute_max_support
    assert control_60.is_attribute_max_support


@pytest.mark.anyio
async def test_cycle_effect():
    from benchmarks.context_evaluation.adversarial.circular_sourcing.cases import (
        acyclic_dependency_chain,
    )

    chain = acyclic_dependency_chain()
    circular = circular_sources()

    chain_result = await evaluate_context(
        _mapped(chain),
        estimator=estimator_config(),
    )
    circular_result = await evaluate_context(
        _mapped(circular),
        estimator=estimator_config(),
    )

    chain_30 = _claim_by_value(chain_result, 30)
    circular_30 = _claim_by_value(circular_result, 30)

    # Captured parent ancestry makes both graphs one exact evidence component.
    # A cycle cannot discount an already fully dependent chain below one source.
    for claim in (chain_30, circular_30):
        assert claim.supporting_source_count == 3
        assert claim.estimated_independent_support_count == pytest.approx(1.0)
        assert [s.independence for s in claim.supporting_sources] == pytest.approx([1 / 3] * 3)


