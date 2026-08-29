from dataclasses import dataclass
from math import isfinite

from .engine_graph import InferenceGraph


ALGORITHM_VERSION = "omneum-v1"
CONVERGENCE_TOLERANCE = 1e-8
MAX_ITERATIONS = 1000


class InferenceError(RuntimeError):
    """Reliability propagation could not be completed."""


@dataclass(frozen=True, slots=True)
class SourceReliability:
    source_id: str
    reliability: float


@dataclass(frozen=True, slots=True)
class SupportingSource:
    source_id: str
    independence: float
    contribution: float


@dataclass(frozen=True, slots=True)
class ConflictingClaim:
    claim_id: str
    support: float


@dataclass(frozen=True, slots=True)
class ClaimSupport:
    attribute_id: str
    claim_id: str
    support: float
    agreement_weight: float
    is_attribute_max_support: bool
    supporting_source_count: int
    estimated_independent_support_count: float
    dependency_signal_coverage: float | None
    supporting_sources: tuple[SupportingSource, ...]
    conflicting_claims: tuple[ConflictingClaim, ...]


@dataclass(frozen=True, slots=True)
class InferenceMetadata:
    algorithm_version: str
    iterations: int
    converged: bool
    convergence_tolerance: float
    convergence_delta: float


@dataclass(frozen=True, slots=True)
class InferenceSummary:
    source_count: int
    claim_count: int
    assertion_count: int


@dataclass(frozen=True, slots=True)
class InferenceResult:
    summary: InferenceSummary
    source_reliability: tuple[SourceReliability, ...]
    claim_support: tuple[ClaimSupport, ...]
    metadata: InferenceMetadata


def _finite(value: float) -> float:
    if not isfinite(value):
        raise InferenceError("inference produced a nonfinite value")
    return value


def _pair(graph: InferenceGraph, source_a_id: str, source_b_id: str):
    if source_a_id > source_b_id:
        source_a_id, source_b_id = source_b_id, source_a_id
    return graph.source_pairs[(source_a_id, source_b_id)]


def _agreement(graph: InferenceGraph) -> dict[str, float]:
    attribute_sources = {
        attribute_id: tuple(sorted({
            source_id
            for claim_id in graph.attribute_to_claims[attribute_id]
            for source_id in graph.claim_to_sources[claim_id]
        }))
        for attribute_id in graph.attributes
    }
    return {
        claim_id: _finite(
            len(graph.claim_to_sources[claim_id])
            / len(attribute_sources[graph.claim_to_attribute[claim_id]])
        )
        for claim_id in graph.claims
    }


def _independence(
    graph: InferenceGraph,
) -> dict[str, dict[str, float]]:
    result = {}
    for claim_id in graph.claims:
        source_ids = graph.claim_to_sources[claim_id]
        if len(source_ids) == 1:
            result[claim_id] = {source_ids[0]: 1.0}
            continue

        claim_values = {}
        divisor = len(source_ids) - 1
        for source_id in source_ids:
            dependency = 0.0
            for other_id in source_ids:
                if other_id != source_id:
                    dependency += _pair(
                        graph,
                        source_id,
                        other_id,
                    ).dependency
            claim_values[source_id] = _finite(
                1.0 - dependency / divisor
            )
        result[claim_id] = claim_values
    return result


def _claim_scores(
    graph: InferenceGraph,
    reliability: dict[str, float],
    agreement: dict[str, float],
    independence: dict[str, dict[str, float]],
) -> tuple[dict[str, float], dict[str, dict[str, float]]]:
    support = {}
    contributions = {}
    for claim_id in graph.claims:
        claim_contributions = {}
        total = 0.0
        for source_id in graph.claim_to_sources[claim_id]:
            contribution = _finite(
                reliability[source_id]
                * agreement[claim_id]
                * independence[claim_id][source_id]
                / graph.source_degree[source_id]
            )
            claim_contributions[source_id] = contribution
            total = _finite(total + contribution)
        contributions[claim_id] = claim_contributions
        support[claim_id] = total
    return support, contributions


def _source_update(
    graph: InferenceGraph,
    support: dict[str, float],
) -> dict[str, float]:
    unscaled = {}
    total = 0.0

    for source_id in graph.sources:
        score = 0.0

        for attribute_id in graph.attributes:
            claims = graph.attribute_to_claims[attribute_id]
            attribute_total = sum(
                support[claim_id]
                for claim_id in claims
            )

            if attribute_total == 0.0:
                continue

            source_claims = (
                claim_id
                for claim_id in graph.source_to_claims[source_id]
                if graph.claim_to_attribute[claim_id] == attribute_id
            )

            for claim_id in source_claims:
                score += support[claim_id] / attribute_total

        unscaled[source_id] = _finite(score)
        total = _finite(total + score)

    if total == 0.0:
        raise InferenceError("inference propagation total is zero")

    return {
        source_id: _finite(unscaled[source_id] / total)
        for source_id in graph.sources
    }


def _telemetry(
    graph: InferenceGraph,
    claim_id: str,
) -> tuple[int, float, float | None]:
    source_ids = graph.claim_to_sources[claim_id]
    count = len(source_ids)
    if count == 1:
        return 1, 1.0, None

    dependency = 0.0
    coverage = 0.0
    for index, source_a_id in enumerate(source_ids):
        for source_b_id in source_ids[index + 1:]:
            pair = _pair(graph, source_a_id, source_b_id)
            dependency = _finite(dependency + pair.dependency)
            coverage = _finite(
                coverage + pair.weighted_signal_coverage
            )

    pair_count = count * (count - 1) / 2
    effective_count = _finite(
        count**2 / (count + 2 * dependency)
    )
    confidence = _finite(coverage / pair_count)
    return count, effective_count, confidence


def _claim_results(
    graph: InferenceGraph,
    support: dict[str, float],
    contributions: dict[str, dict[str, float]],
    agreement: dict[str, float],
    independence: dict[str, dict[str, float]],
) -> tuple[ClaimSupport, ...]:
    maxima = {
        attribute_id: max(
            support[claim_id]
            for claim_id in graph.attribute_to_claims[attribute_id]
        )
        for attribute_id in graph.attributes
    }
    results = []
    for claim_id in graph.claims:
        attribute_id = graph.claim_to_attribute[claim_id]
        count, effective_count, confidence = _telemetry(
            graph,
            claim_id,
        )
        supporting_sources = tuple(sorted(
            (
                SupportingSource(
                    source_id=source_id,
                    independence=independence[claim_id][source_id],
                    contribution=contributions[claim_id][source_id],
                )
                for source_id in graph.claim_to_sources[claim_id]
            ),
            key=lambda item: (-item.contribution, item.source_id),
        ))
        conflicts = tuple(sorted(
            (
                ConflictingClaim(
                    claim_id=other_id,
                    support=support[other_id],
                )
                for other_id in graph.attribute_to_claims[attribute_id]
                if other_id != claim_id
            ),
            key=lambda item: (-item.support, item.claim_id),
        ))
        results.append(ClaimSupport(
            attribute_id=attribute_id,
            claim_id=claim_id,
            support=support[claim_id],
            agreement_weight=agreement[claim_id],
            is_attribute_max_support=(
                support[claim_id] == maxima[attribute_id]
            ),
            supporting_source_count=count,
            estimated_independent_support_count=effective_count,
            dependency_signal_coverage=confidence,
            supporting_sources=supporting_sources,
            conflicting_claims=conflicts,
        ))
    return tuple(sorted(
        results,
        key=lambda item: (
            item.attribute_id,
            -item.support,
            item.claim_id,
        ),
    ))


def infer(graph: InferenceGraph) -> InferenceResult:
    """Run deterministic version-1 reliability propagation."""

    if not graph.sources:
        raise InferenceError("inference graph has no sources")

    reliability = {
        source_id: 1.0 / len(graph.sources)
        for source_id in graph.sources
    }
    agreement = _agreement(graph)
    independence = _independence(graph)
    maximum_delta = 0.0

    for iteration in range(1, MAX_ITERATIONS + 1):
        support, _ = _claim_scores(
            graph,
            reliability,
            agreement,
            independence,
        )
        updated = _source_update(graph, support)
        maximum_delta = max(
            _finite(abs(updated[source_id] - reliability[source_id]))
            for source_id in graph.sources
        )
        reliability = updated
        if maximum_delta < CONVERGENCE_TOLERANCE:
            break
    else:
        raise InferenceError("inference did not converge")

    support, contributions = _claim_scores(
        graph,
        reliability,
        agreement,
        independence,
    )
    source_reliability = tuple(sorted(
        (
            SourceReliability(source_id, reliability[source_id])
            for source_id in graph.sources
        ),
        key=lambda item: (-item.reliability, item.source_id),
    ))

    return InferenceResult(
        summary=InferenceSummary(
            source_count=len(graph.sources),
            claim_count=len(graph.claims),
            assertion_count=graph.assertion_count,
        ),
        source_reliability=source_reliability,
        claim_support=_claim_results(
            graph,
            support,
            contributions,
            agreement,
            independence,
        ),
        metadata=InferenceMetadata(
            algorithm_version=ALGORITHM_VERSION,
            iterations=iteration,
            converged=True,
            convergence_tolerance=CONVERGENCE_TOLERANCE,
            convergence_delta=maximum_delta,
        ),
    )
