from dataclasses import dataclass

from omneum import ContextEvaluation

from .policy import REQUIRED_ATTRIBUTES, RoutingPolicy


@dataclass(frozen=True)
class SelectedClaim:
    attribute: str
    value: str
    support: float
    independent_support: float


def select_context(
    evaluation: ContextEvaluation,
    *,
    policy: RoutingPolicy = RoutingPolicy(),
) -> tuple[SelectedClaim, ...]:
    selected = []

    for attribute in REQUIRED_ATTRIBUTES:
        candidates = sorted(
            (
                result
                for result in evaluation.claim_support
                if result.claim.attribute == attribute
            ),
            key=lambda result: result.support,
            reverse=True,
        )

        if not candidates:
            continue

        best = candidates[0]

        if best.estimated_independent_support_count < policy.min_independent_support:
            continue

        if len(candidates) > 1:
            runner_up = candidates[1]
            if (
                runner_up.support > 0
                and best.support / runner_up.support < policy.min_support_ratio
            ):
                continue

        selected.append(
            SelectedClaim(
                attribute=attribute,
                value=best.claim.value,
                support=best.support,
                independent_support=best.estimated_independent_support_count,
            )
        )

    return tuple(selected)
