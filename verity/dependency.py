import math

from dataclasses import dataclass, field
from datetime import timedelta
from itertools import combinations

from .canonicalization import (
    canonicalize_attribute,
    canonicalize_entity,
    canonicalize_source,
    canonicalize_value,
)
from .information import Claim, Observation, Source, SourceReference
from .serialization import (
    serialize_attribute,
    serialize_claim,
    serialize_source,
)


MAX_SOURCES = 64
MAX_ATTRIBUTES = 2_048
MAX_CLAIMS = 4_096
MAX_ASSERTIONS = 4_096
MAX_CONFLICTS = 16_384
SIGNALS = (
    "provenance",
    "lineage",
    "ownership",
    "temporal",
    "structural",
)


class InformationGraphError(ValueError):
    pass


def _number(value, name, *, positive=False, unit=False):
    if type(value) is not float:
        raise TypeError(f"{name} must be a float")
    if not math.isfinite(value):
        raise ValueError(f"{name} must be finite")
    if positive and value <= 0.0:
        raise ValueError(f"{name} must be positive")
    if not positive and value < 0.0:
        raise ValueError(f"{name} must be non-negative")
    if unit and value > 1.0:
        raise ValueError(f"{name} must be in range")


@dataclass(frozen=True, slots=True)
class DependencyEstimatorConfig:
    provenance_weight: float = field(repr=False)
    lineage_weight: float = field(repr=False)
    ownership_weight: float = field(repr=False)
    temporal_weight: float = field(repr=False)
    structural_weight: float = field(repr=False)
    temporal_window_seconds: float = field(repr=False)
    estimator_version: str = field(
        default="dependency-estimator-v1",
        repr=False,
    )
    dependency_cluster_threshold: float | None = field(
        default=None,
        repr=False,
    )

    def __post_init__(self):
        if type(self.estimator_version) is not str:
            raise TypeError("estimator_version must be a string")
        if self.estimator_version != "dependency-estimator-v1":
            raise ValueError("unsupported dependency estimator version")
        for name in SIGNALS:
            _number(getattr(self, f"{name}_weight"), f"{name}_weight")
        total = sum(getattr(self, f"{name}_weight") for name in SIGNALS)
        if not math.isfinite(total) or total <= 0.0:
            raise ValueError("dependency weights must have a positive sum")
        _number(
            self.temporal_window_seconds,
            "temporal_window_seconds",
            positive=True,
        )
        if self.dependency_cluster_threshold is not None:
            _number(
                self.dependency_cluster_threshold,
                "dependency_cluster_threshold",
                unit=True,
            )


@dataclass(frozen=True, slots=True)
class DependencySignalScores:
    provenance: float = field(repr=False)
    lineage: float = field(repr=False)
    ownership: float = field(repr=False)
    temporal: float = field(repr=False)
    structural: float = field(repr=False)
    provenance_observable: bool = field(repr=False)
    lineage_observable: bool = field(repr=False)
    ownership_observable: bool = field(repr=False)
    temporal_observable: bool = field(repr=False)
    structural_observable: bool = field(repr=False)

    def __post_init__(self):
        for name in SIGNALS:
            _number(getattr(self, name), name, unit=True)
            if type(getattr(self, f"{name}_observable")) is not bool:
                raise TypeError(f"{name}_observable must be a bool")


@dataclass(frozen=True, slots=True)
class PairwiseDependencyResult:
    source_a: SourceReference = field(repr=False)
    source_b: SourceReference = field(repr=False)
    signals: DependencySignalScores = field(repr=False)
    dependency: float = field(repr=False)
    weighted_signal_coverage: float = field(repr=False)

    def __post_init__(self):
        if type(self.source_a) is not SourceReference:
            raise TypeError("source_a must be a SourceReference")
        if type(self.source_b) is not SourceReference:
            raise TypeError("source_b must be a SourceReference")
        if type(self.signals) is not DependencySignalScores:
            raise TypeError("signals must be DependencySignalScores")
        _number(self.dependency, "dependency", unit=True)
        _number(
            self.weighted_signal_coverage,
            "weighted_signal_coverage",
            unit=True,
        )
        source_a = _canonical_source(self.source_a)
        source_b = _canonical_source(self.source_b)
        if source_a == source_b:
            raise ValueError("source pair must not be diagonal")
        if serialize_source(*source_a) > serialize_source(*source_b):
            raise ValueError("source pair must be canonically ordered")


@dataclass(frozen=True, slots=True)
class DependencyCluster:
    threshold: float = field(repr=False)
    sources: tuple[SourceReference, ...] = field(repr=False)

    def __post_init__(self):
        _number(self.threshold, "threshold", unit=True)
        if type(self.sources) is not tuple or not self.sources:
            raise TypeError("sources must be a nonempty tuple")
        if any(type(source) is not SourceReference for source in self.sources):
            raise TypeError("sources must contain SourceReference values")
        identities = tuple(_canonical_source(source) for source in self.sources)
        if len(set(identities)) != len(identities):
            raise ValueError("cluster sources must be unique")
        if identities != tuple(
            sorted(identities, key=lambda source: serialize_source(*source))
        ):
            raise ValueError("cluster sources must be canonically ordered")


def _canonical_source(value):
    return (
        value.kind,
        canonicalize_source(value.kind, value.identifier),
    )


def _canonical_claim(value):
    entity = canonicalize_entity(value.entity_namespace, value.entity)
    attribute = canonicalize_attribute(value.attribute)
    claim_value = canonicalize_value(value.value)
    return value.entity_namespace, entity, attribute, claim_value


def _weights(config):
    supplied = tuple(getattr(config, f"{name}_weight") for name in SIGNALS)
    total = sum(supplied)
    return tuple(value / total for value in supplied)


def combine_dependency(signals, config):
    if type(signals) is not DependencySignalScores:
        raise TypeError("signals must be DependencySignalScores")
    if type(config) is not DependencyEstimatorConfig:
        raise TypeError("config must be DependencyEstimatorConfig")
    weights = _weights(config)
    dependency = sum(
        weights[index] * getattr(signals, name)
        for index, name in enumerate(SIGNALS)
    )
    coverage = sum(
        weights[index] * float(getattr(signals, f"{name}_observable"))
        for index, name in enumerate(SIGNALS)
    ) / sum(weights)
    return max(0.0, min(1.0, dependency)), coverage


def estimate_dependencies(sources, observations, config):
    if type(sources) is not tuple or type(observations) is not tuple:
        raise TypeError("sources and observations must be tuples")
    if type(config) is not DependencyEstimatorConfig:
        raise TypeError("config must be DependencyEstimatorConfig")
    if not observations:
        raise InformationGraphError("observation graph must not be empty")
    if len(observations) > MAX_ASSERTIONS:
        raise InformationGraphError("too many observations")

    source_map = {}
    for source in sources:
        if type(source) is not Source:
            raise TypeError("sources must contain Source values")
        key = _canonical_source(source)
        previous = source_map.get(key)
        if previous is not None and previous.owner_id != source.owner_id:
            raise InformationGraphError("canonical source has conflicting owners")
        if previous is not None:
            raise InformationGraphError("duplicate canonical source")
        source_map[key] = source
    if not source_map or len(source_map) > MAX_SOURCES:
        raise InformationGraphError("source count is outside bounds")

    rows = []
    assertion_ids = {}
    triples = set()
    source_attributes = set()
    claim_attributes = {}
    for observation in observations:
        if type(observation) is not Observation:
            raise TypeError("observations must contain Observation values")
        if observation.assertion_id in assertion_ids:
            raise InformationGraphError("duplicate assertion ID")
        source_key = _canonical_source(observation.source)
        if source_key not in source_map:
            raise InformationGraphError("observation source is unknown")
        claim = _canonical_claim(observation.claim)
        property_key = claim[:3]
        claim_bytes = serialize_claim(*claim)
        attribute_bytes = serialize_attribute(*property_key)
        source_bytes = serialize_source(*source_key)
        triple = (source_bytes, attribute_bytes, claim_bytes)
        if triple in triples:
            raise InformationGraphError("duplicate canonical assertion")
        triples.add(triple)
        source_attribute = (source_key, attribute_bytes)
        if source_attribute in source_attributes:
            raise InformationGraphError("source has multiple claims for an attribute")
        source_attributes.add(source_attribute)
        previous = claim_attributes.setdefault(claim_bytes, attribute_bytes)
        if previous != attribute_bytes:
            raise InformationGraphError("claim belongs to multiple attributes")
        row = (observation, source_key, source_bytes, property_key, claim, claim_bytes)
        rows.append(row)
        assertion_ids[observation.assertion_id] = row

    attributes = {row[3] for row in rows}
    claims = {row[5] for row in rows}
    if len(attributes) > MAX_ATTRIBUTES or len(claims) > MAX_CLAIMS:
        raise InformationGraphError("information graph exceeds bounds")
    claim_counts = {}
    for row in rows:
        claim_counts.setdefault(row[3], set()).add(row[5])
    conflicts = sum(len(values) * (len(values) - 1) for values in claim_counts.values())
    if conflicts > MAX_CONFLICTS:
        raise InformationGraphError("information graph exceeds conflict limit")

    for observation, source_key, *_ in rows:
        for cited in observation.cited_sources or ():
            cited_key = _canonical_source(cited)
            if cited_key not in source_map:
                raise InformationGraphError("cited source is unknown")
            if cited_key == source_key:
                raise InformationGraphError("source cannot cite itself")
        for parent_id in observation.parent_assertion_ids or ():
            parent = assertion_ids.get(parent_id)
            if parent is None:
                raise InformationGraphError("parent assertion is unknown")
            if parent[1] == source_key:
                raise InformationGraphError("assertion cannot reference its source")

    ordered_keys = tuple(sorted(source_map, key=lambda key: serialize_source(*key)))
    rows_by_source = {key: [] for key in ordered_keys}
    for row in rows:
        rows_by_source[row[1]].append(row)
    for values in rows_by_source.values():
        values.sort(key=lambda row: (serialize_attribute(*row[3]), row[5]))
        if not values:
            raise InformationGraphError("every source must have an observation")

    results = []
    for source_a, source_b in combinations(ordered_keys, 2):
        signals = _signals(
            source_a,
            source_b,
            source_map,
            rows_by_source,
            assertion_ids,
            config,
        )
        dependency, coverage = combine_dependency(signals, config)
        results.append(PairwiseDependencyResult(
            SourceReference(*source_a),
            SourceReference(*source_b),
            signals,
            dependency,
            coverage,
        ))

    clusters = ()
    if config.dependency_cluster_threshold is not None:
        clusters = _clusters(ordered_keys, results, config.dependency_cluster_threshold)
    return tuple(results), clusters


def _signals(source_a, source_b, source_map, rows_by_source, assertion_ids, config):
    rows_a = rows_by_source[source_a]
    rows_b = rows_by_source[source_b]
    provenance_a = set().union(*(set(row[0].provenance_ids or ()) for row in rows_a))
    provenance_b = set().union(*(set(row[0].provenance_ids or ()) for row in rows_b))
    provenance_observable = all(row[0].provenance_ids is not None for row in rows_a + rows_b)
    union = provenance_a | provenance_b
    provenance = len(provenance_a & provenance_b) / len(union) if provenance_observable and union else 0.0

    direction_a = _lineage(source_b, rows_a, assertion_ids)
    direction_b = _lineage(source_a, rows_b, assertion_ids)
    lineage = max(direction_a, direction_b)
    captured_a = all(row[0].cited_sources is not None and row[0].parent_assertion_ids is not None for row in rows_a)
    captured_b = all(row[0].cited_sources is not None and row[0].parent_assertion_ids is not None for row in rows_b)
    lineage_observable = bool(lineage or (captured_a and captured_b))

    owner_a = source_map[source_a].owner_id
    owner_b = source_map[source_b].owner_id
    ownership_observable = owner_a is not None and owner_b is not None
    ownership = float(ownership_observable and owner_a == owner_b)

    properties_a = {row[3]: row for row in rows_a}
    properties_b = {row[3]: row for row in rows_b}
    matches = tuple(sorted(
        (key for key in properties_a.keys() & properties_b.keys()
         if properties_a[key][4][3] == properties_b[key][4][3]),
        key=lambda key: serialize_attribute(*key),
    ))
    temporal_observable = all(
        properties_a[key][0].source_timestamp is not None
        and properties_b[key][0].source_timestamp is not None
        for key in matches
    )
    temporal = 0.0
    if temporal_observable and matches:
        window = timedelta(seconds=config.temporal_window_seconds)
        qualifying_a = sum(
            timedelta(0) < properties_a[key][0].source_timestamp - properties_b[key][0].source_timestamp <= window
            for key in matches
        )
        qualifying_b = sum(
            timedelta(0) < properties_b[key][0].source_timestamp - properties_a[key][0].source_timestamp <= window
            for key in matches
        )
        temporal = max(qualifying_a, qualifying_b) / len(matches)

    supporters = {}
    for rows in rows_by_source.values():
        for row in rows:
            supporters[row[5]] = supporters.get(row[5], 0) + 1
    if matches:
        inclusion = max(len(matches) / len(rows_b), len(matches) / len(rows_a))
        rarity = sum(1.0 / supporters[properties_a[key][5]] for key in matches) / len(matches)
        structural = inclusion * rarity
    else:
        structural = 0.0

    return DependencySignalScores(
        provenance, lineage, ownership, temporal, structural,
        provenance_observable, lineage_observable, ownership_observable,
        temporal_observable, True,
    )


def _lineage(other_source, rows, assertion_ids):
    for observation, *_ in rows:
        if any(_canonical_source(value) == other_source for value in observation.cited_sources or ()):
            return 1.0
        if any(assertion_ids[value][1] == other_source for value in observation.parent_assertion_ids or ()):
            return 1.0
    return 0.0


def _clusters(source_keys, results, threshold):
    adjacent = {key: set() for key in source_keys}
    for result in results:
        if result.dependency >= threshold:
            a = (result.source_a.kind, result.source_a.identifier)
            b = (result.source_b.kind, result.source_b.identifier)
            adjacent[a].add(b)
            adjacent[b].add(a)
    remaining = set(source_keys)
    components = []
    for start in source_keys:
        if start not in remaining:
            continue
        stack = [start]
        component = []
        remaining.remove(start)
        while stack:
            current = stack.pop()
            component.append(current)
            for value in reversed(source_keys):
                if value in adjacent[current] and value in remaining:
                    remaining.remove(value)
                    stack.append(value)
        ordered = tuple(SourceReference(*key) for key in source_keys if key in component)
        components.append(DependencyCluster(threshold, ordered))
    return tuple(components)
