from dataclasses import dataclass
from math import isfinite
from types import MappingProxyType
from typing import Mapping, Sequence


class GraphError(ValueError):
    """The supplied inference graph is invalid."""


@dataclass(frozen=True, slots=True)
class AssertionTriple:
    source_id: str
    attribute_id: str
    claim_id: str


@dataclass(frozen=True, slots=True)
class SourcePair:
    source_a_id: str
    source_b_id: str
    dependency: float
    weighted_signal_coverage: float
    exact_equivalence: bool = False


@dataclass(frozen=True, slots=True)
class PairValues:
    dependency: float
    weighted_signal_coverage: float
    exact_equivalence: bool = False


@dataclass(frozen=True, slots=True)
class InferenceGraph:
    sources: tuple[str, ...]
    attributes: tuple[str, ...]
    claims: tuple[str, ...]
    source_to_claims: Mapping[str, tuple[str, ...]]
    claim_to_sources: Mapping[str, tuple[str, ...]]
    claim_to_attribute: Mapping[str, str]
    attribute_to_claims: Mapping[str, tuple[str, ...]]
    source_degree: Mapping[str, int]
    source_pairs: Mapping[tuple[str, str], PairValues]
    assertion_count: int


def _identifier(value: object) -> str:
    if not isinstance(value, str) or not value:
        raise GraphError("graph identifiers must be nonempty strings")
    return value


def _pair_value(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise GraphError("source-pair values must be numbers")
    result = float(value)
    if not isfinite(result) or not 0.0 <= result <= 1.0:
        raise GraphError("source-pair values must be finite and in range")
    return result


def _mapping(values: dict) -> Mapping:
    return MappingProxyType(values)


def build_graph(
    assertions: Sequence[AssertionTriple],
    source_pairs: Sequence[SourcePair],
) -> InferenceGraph:
    """Build the canonical graph consumed by the inference engine."""

    if not assertions:
        raise GraphError("assertion graph must not be empty")

    triples = []
    seen = set()
    for assertion in assertions:
        triple = (
            _identifier(assertion.source_id),
            _identifier(assertion.attribute_id),
            _identifier(assertion.claim_id),
        )
        if triple in seen:
            raise GraphError("duplicate assertion")
        seen.add(triple)
        triples.append(triple)
    triples.sort()

    source_claims: dict[str, list[str]] = {}
    claim_sources: dict[str, list[str]] = {}
    claim_attribute: dict[str, str] = {}
    attribute_claims: dict[str, set[str]] = {}
    source_attributes: set[tuple[str, str]] = set()

    for source_id, attribute_id, claim_id in triples:
        previous = claim_attribute.setdefault(claim_id, attribute_id)
        if previous != attribute_id:
            raise GraphError("claim belongs to multiple attributes")

        source_attribute = (source_id, attribute_id)
        if source_attribute in source_attributes:
            raise GraphError("source has multiple claims for an attribute")
        source_attributes.add(source_attribute)

        source_claims.setdefault(source_id, []).append(claim_id)
        claim_sources.setdefault(claim_id, []).append(source_id)
        attribute_claims.setdefault(attribute_id, set()).add(claim_id)

    sources = tuple(sorted(source_claims))
    attributes = tuple(sorted(attribute_claims))
    claims = tuple(sorted(claim_sources))
    source_set = set(sources)

    pairs: dict[tuple[str, str], PairValues] = {}
    for pair in source_pairs:
        source_a_id = _identifier(pair.source_a_id)
        source_b_id = _identifier(pair.source_b_id)
        if source_a_id not in source_set or source_b_id not in source_set:
            raise GraphError("source pair contains an unknown source")
        if source_a_id == source_b_id:
            raise GraphError("source pair must not be diagonal")
        if source_a_id > source_b_id:
            raise GraphError("source pair must use canonical order")

        key = (source_a_id, source_b_id)
        if key in pairs:
            raise GraphError("duplicate source pair")
        if not isinstance(pair.exact_equivalence, bool):
            raise GraphError("source-pair exact_equivalence must be a boolean")
        pairs[key] = PairValues(
            dependency=_pair_value(pair.dependency),
            weighted_signal_coverage=_pair_value(
                pair.weighted_signal_coverage
            ),
            exact_equivalence=pair.exact_equivalence,
        )

    expected_pairs = {
        (source_a_id, source_b_id)
        for index, source_a_id in enumerate(sources)
        for source_b_id in sources[index + 1:]
    }
    if set(pairs) != expected_pairs:
        raise GraphError("source-pair matrix must be complete")

    ordered_source_claims = {
        source_id: tuple(sorted(source_claims[source_id]))
        for source_id in sources
    }
    ordered_claim_sources = {
        claim_id: tuple(sorted(claim_sources[claim_id]))
        for claim_id in claims
    }
    ordered_claim_attribute = {
        claim_id: claim_attribute[claim_id]
        for claim_id in claims
    }
    ordered_attribute_claims = {
        attribute_id: tuple(sorted(attribute_claims[attribute_id]))
        for attribute_id in attributes
    }
    source_degree = {
        source_id: len(ordered_source_claims[source_id])
        for source_id in sources
    }
    ordered_pairs = {
        key: pairs[key]
        for key in sorted(pairs)
    }

    return InferenceGraph(
        sources=sources,
        attributes=attributes,
        claims=claims,
        source_to_claims=_mapping(ordered_source_claims),
        claim_to_sources=_mapping(ordered_claim_sources),
        claim_to_attribute=_mapping(ordered_claim_attribute),
        attribute_to_claims=_mapping(ordered_attribute_claims),
        source_degree=_mapping(source_degree),
        source_pairs=_mapping(ordered_pairs),
        assertion_count=len(triples),
    )
