from dataclasses import dataclass
from math import fsum, isfinite

from .engine_graph import AssertionTriple, InferenceGraph, SourcePair, build_graph


ALGORITHM_VERSION = "omneum-v2"
CONVERGENCE_TOLERANCE = 1e-8
MAX_ITERATIONS = 1000
PROPAGATION_WEIGHT = 0.70


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


def _agreement(
    graph: InferenceGraph,
    independence: dict[str, dict[str, float]],
) -> dict[str, float]:
    effective_support = {
        claim_id: _finite(sum(independence[claim_id].values()))
        for claim_id in graph.claims
    }
    attribute_support = {
        attribute_id: _finite(sum(
            effective_support[claim_id]
            for claim_id in graph.attribute_to_claims[attribute_id]
        ))
        for attribute_id in graph.attributes
    }
    return {
        claim_id: _finite(
            effective_support[claim_id]
            / attribute_support[graph.claim_to_attribute[claim_id]]
        )
        for claim_id in graph.claims
    }


def _equivalence_graph(
    graph: InferenceGraph,
) -> tuple[InferenceGraph, dict[str, tuple[str, ...]]]:
    """Collapse homogeneous exact-equivalence components before any evidence accounting.

    The quotient is defined only when members have identical claim profiles
    and every cross-component dependency block is constant. Coverage is not a
    scoring input; diagnostics continue to use the original source pairs.
    """
    neighbors = {source: set() for source in graph.sources}
    for (a, b), pair in graph.source_pairs.items():
        if pair.exact_equivalence:
            neighbors[a].add(b)
            neighbors[b].add(a)
    members = {}
    seen = set()
    for source in graph.sources:
        if source in seen:
            continue
        component = set()
        stack = [source]
        while stack:
            current = stack.pop()
            if current in component:
                continue
            component.add(current)
            stack.extend(neighbors[current] - component)
        seen.update(component)
        members[source] = tuple(sorted(component))

    if len(members) == len(graph.sources):
        return graph, members

    for representative, sources in members.items():
        if any(graph.source_to_claims[source]
               != graph.source_to_claims[representative] for source in sources):
            raise InferenceError("heterogeneous exact equivalence claim profiles are undefined")

    pairs = []
    representatives = tuple(members)
    for index, a in enumerate(representatives):
        for b in representatives[index + 1:]:
            dependency = _finite(_pair(graph, a, b).dependency)
            if any(_finite(_pair(graph, source_a, source_b).dependency) != dependency
                   for source_a in members[a] for source_b in members[b]):
                raise InferenceError("heterogeneous exact equivalence dependencies are undefined")
            pairs.append(SourcePair(a, b, dependency, 0.0))
    assertions = [
        AssertionTriple(source, graph.claim_to_attribute[claim], claim)
        for source in representatives for claim in graph.source_to_claims[source]
    ]
    return build_graph(assertions, pairs), members


def _reciprocal_independence(
    graph: InferenceGraph,
) -> dict[str, dict[str, float]]:
    # Each source in this graph is one evidence component. In particular,
    # singleton components retain the original reciprocal dependency rule.
    result = {}
    for claim in graph.claims:
        values = {}
        for source in graph.claim_to_sources[claim]:
            dependency = 0.0
            for other in graph.claim_to_sources[claim]:
                if other != source:
                    dependency += _pair(graph, source, other).dependency
            values[source] = _finite(1.0 / (1.0 + dependency))
        result[claim] = values
    return result


def _member_shares(
    values: dict[str, float],
    members: dict[str, tuple[str, ...]],
) -> dict[str, float]:
    return {
        source: value / len(members[representative])
        for representative, value in values.items()
        for source in members[representative]
    }


def _independence(
    graph: InferenceGraph,
) -> dict[str, dict[str, float]]:
    component_graph, members = _equivalence_graph(graph)
    return {
        claim: _member_shares(values, members)
        for claim, values in _reciprocal_independence(component_graph).items()
    }


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
    """Normalize one propagation score per evidence component."""
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
    independence: dict[str, float],
) -> tuple[int, float, float | None]:
    source_ids = graph.claim_to_sources[claim_id]
    count = len(source_ids)
    if count == 1:
        return 1, 1.0, None

    coverage = 0.0
    for index, source_a_id in enumerate(source_ids):
        for source_b_id in source_ids[index + 1:]:
            pair = _pair(graph, source_a_id, source_b_id)
            coverage = _finite(
                coverage + pair.weighted_signal_coverage
            )

    pair_count = count * (count - 1) / 2
    # Report the same evidence mass used by agreement and claim scoring,
    # including transitive exact lineage, rather than a raw-pair estimate.
    # Each component Q >= 1/component_count, so their sum (also the
    # sum of member shares) is >= 1. Clamp roundoff at this boundary.
    effective_count = max(1.0, _finite(fsum(independence.values())))
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
            independence[claim_id],
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


def infer(
    graph: InferenceGraph,
    propagation_weight: float = PROPAGATION_WEIGHT,
) -> InferenceResult:
    """Propagate on homogeneous exact-equivalence components, then allocate to members.

    Reported member reliability, independence and contribution are each shares
    of their component totals. They must not be multiplied together again:
    claim scoring applies the reciprocal rule once, before allocating shares.
    """

    if not graph.sources:
        raise InferenceError("inference graph has no sources")

    original_graph = graph
    graph, members = _equivalence_graph(graph)
    reliability = {
        source_id: 1.0 / len(graph.sources)
        for source_id in graph.sources
    }
    independence = _reciprocal_independence(graph)
    agreement = _agreement(graph, independence)
    maximum_delta = 0.0

    for iteration in range(1, MAX_ITERATIONS + 1):
        support, _ = _claim_scores(
            graph,
            reliability,
            agreement,
            independence,
        )
        propagated = _source_update(graph, support)

        prior = 1.0 / len(graph.sources)
        updated = {
            source_id: _finite(
                propagation_weight * propagated[source_id]
                + (1.0 - propagation_weight) * prior
            )
            for source_id in graph.sources
        }

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
    if graph is not original_graph:
        reliability = _member_shares(reliability, members)
        independence = {
            claim: _member_shares(values, members)
            for claim, values in independence.items()
        }
        contributions = {
            claim: _member_shares(values, members)
            for claim, values in contributions.items()
        }
        # Keep component scores (including exact ties) and canonical contribution
        # totals identical. Allocate division/summation roundoff to the final
        # positive contributor, rather than feeding it back into inference.
        for claim, values in contributions.items():
            if support[claim] == 0.0:
                continue
            sources = original_graph.claim_to_sources[claim]
            last = next(source for source in reversed(sources) if values[source] > 0)
            prefix = 0.0
            for source in sources:
                if source == last:
                    values[source] = support[claim] - prefix
                    break
                prefix += values[source]
        graph = original_graph

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
