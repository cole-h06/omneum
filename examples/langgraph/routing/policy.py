from dataclasses import dataclass
from typing import Literal

from omneum import ContextEvaluation


Route = Literal[
    "generate",
    "retrieve_support",
    "resolve_conflicts",
    "diversify_sources",
    "escalate",
]

REQUIRED_ATTRIBUTES = (
    "input_data_policy",
    "provider_retention",
    "processing_region",
)


@dataclass(frozen=True)
class RoutingPolicy:
    min_independent_support: float = 1.9
    min_support_ratio: float = 2.0
    max_retries: int = 2


@dataclass(frozen=True)
class RoutingDecision:
    route: Route
    attributes: tuple[str, ...]
    reason: str


def assess_context(
    evaluation: ContextEvaluation,
    *,
    retries: int = 0,
    policy: RoutingPolicy = RoutingPolicy(),
) -> RoutingDecision:
    groups = {}

    for result in evaluation.claim_support:
        groups.setdefault(result.claim.attribute, []).append(result)

    missing = tuple(
        attribute
        for attribute in REQUIRED_ATTRIBUTES
        if not groups.get(attribute)
    )

    if missing:
        decision = RoutingDecision(
            "retrieve_support",
            missing,
            "Required attributes have no supporting observations.",
        )
    else:
        conflicts = []
        dependent = []
        weak = []

        for attribute in REQUIRED_ATTRIBUTES:
            candidates = sorted(
                groups[attribute],
                key=lambda item: item.support,
                reverse=True,
            )
            best = candidates[0]

            if len(candidates) > 1:
                runner_up = candidates[1]
                if (
                    runner_up.support > 0
                    and best.support / runner_up.support
                    < policy.min_support_ratio
                ):
                    conflicts.append(attribute)
                    continue

            if (
                best.estimated_independent_support_count
                < policy.min_independent_support
            ):
                if best.supporting_source_count > 1:
                    dependent.append(attribute)
                else:
                    weak.append(attribute)

        if conflicts:
            decision = RoutingDecision(
                "resolve_conflicts",
                tuple(conflicts),
                "Competing values have insufficient support separation.",
            )
        elif weak:
            decision = RoutingDecision(
                "retrieve_support",
                tuple(dict.fromkeys((*weak, *dependent))),
                "Required attributes have insufficient supporting evidence.",
            )
        elif dependent:
            decision = RoutingDecision(
                "diversify_sources",
                tuple(dependent),
                "Supporting sources provide insufficient independent support.",
            )
        else:
            decision = RoutingDecision(
                "generate",
                (),
                "Evidence meets the application routing policy.",
            )

    if decision.route != "generate" and retries >= policy.max_retries:
        return RoutingDecision(
            "escalate",
            decision.attributes,
            f"Retry limit reached: {decision.reason}",
        )

    return decision
