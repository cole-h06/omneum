import math

from dataclasses import dataclass, field
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
    "upstream",
    "citation",
    "assertion_lineage",
    "ownership",
    "temporal",
    "graph",
    "retrieval",
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
    upstream_weight: float = field(repr=False)
    citation_weight: float = field(repr=False)
    assertion_lineage_weight: float = field(repr=False)
    ownership_weight: float = field(repr=False)
    temporal_weight: float = field(repr=False)
    graph_weight: float = field(repr=False)
    temporal_window_seconds: float = field(repr=False)
    retrieval_weight: float = field(
        default=0.0,
        repr=False,
    )
    estimator_version: str = field(
        default="dependency-estimator-v4",
        repr=False,
    )
    dependency_cluster_threshold: float | None = field(
        default=None,
        repr=False,
    )

    def __post_init__(self):
        if type(self.estimator_version) is not str:
            raise TypeError("estimator_version must be a string")

        if self.estimator_version != "dependency-estimator-v4":
            raise ValueError("unsupported dependency estimator version")

        for name in SIGNALS:
            _number(
                getattr(self, f"{name}_weight"),
                f"{name}_weight",
            )

        total = sum(
            getattr(self, f"{name}_weight")
            for name in SIGNALS
        )

        if not math.isfinite(total) or total <= 0.0:
            raise ValueError(
                "dependency weights must have a positive sum"
            )

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
class DependencySignal:
    value: float
    observable: bool

    def __post_init__(self):
        _number(
            self.value,
            "value",
            unit=True,
        )

        if type(self.observable) is not bool:
            raise TypeError(
                "observable must be a bool"
            )


@dataclass(frozen=True, slots=True)
class DependencySignalScores:
    upstream: float = field(repr=False)
    citation: float = field(repr=False)
    assertion_lineage: float = field(repr=False)
    ownership: float = field(repr=False)
    temporal: float = field(repr=False)
    graph: float = field(repr=False)

    upstream_observable: bool = field(repr=False)
    citation_observable: bool = field(repr=False)
    assertion_lineage_observable: bool = field(repr=False)
    ownership_observable: bool = field(repr=False)
    temporal_observable: bool = field(repr=False)
    graph_observable: bool = field(repr=False)

    retrieval: float = field(default=0.0, repr=False)
    retrieval_observable: bool = field(default=False, repr=False)

    def __post_init__(self):
        for name in SIGNALS:
            _number(
                getattr(self, name),
                name,
                unit=True,
            )

            if type(
                getattr(self, f"{name}_observable")
            ) is not bool:
                raise TypeError(
                    f"{name}_observable must be a bool"
                )


@dataclass(frozen=True, slots=True)
class DependencyEvidence:
    source_a_upstream_of_source_b: bool = field(repr=False)
    source_b_upstream_of_source_a: bool = field(repr=False)

    source_a_cites_source_b: bool = field(repr=False)
    source_b_cites_source_a: bool = field(repr=False)

    source_a_parent_count: int = field(repr=False)
    source_b_parent_count: int = field(repr=False)

    same_owner: bool = field(repr=False)

    matching_claim_count: int = field(repr=False)

    qualifying_time_deltas_seconds: tuple[float, ...] = field(
        repr=False
    )

    def __post_init__(self):
        for name in (
            "source_a_upstream_of_source_b",
            "source_b_upstream_of_source_a",
            "source_a_cites_source_b",
            "source_b_cites_source_a",
            "same_owner",
        ):
            if type(getattr(self, name)) is not bool:
                raise TypeError(f"{name} must be a bool")

        for name in (
            "source_a_parent_count",
            "source_b_parent_count",
            "matching_claim_count",
        ):
            value = getattr(self, name)

            if type(value) is not int:
                raise TypeError(f"{name} must be an int")

            if value < 0:
                raise ValueError(f"{name} must be non-negative")

        if type(self.qualifying_time_deltas_seconds) is not tuple:
            raise TypeError(
                "qualifying_time_deltas_seconds must be a tuple"
            )

        for value in self.qualifying_time_deltas_seconds:
            if type(value) is not float:
                raise TypeError(
                    "qualifying time deltas must be floats"
                )

            if not math.isfinite(value) or value < 0.0:
                raise ValueError(
                    "qualifying time deltas must be non-negative"
                )


@dataclass(frozen=True, slots=True)
class PairwiseDependencyResult:
    source_a: SourceReference = field(repr=False)
    source_b: SourceReference = field(repr=False)
    signals: DependencySignalScores = field(repr=False)
    dependency: float = field(repr=False)
    weighted_signal_coverage: float = field(repr=False)
    evidence: DependencyEvidence | None = field(
        default=None,
        repr=False,
    )

    def __post_init__(self):
        if type(self.source_a) is not SourceReference:
            raise TypeError(
                "source_a must be a SourceReference"
            )

        if type(self.source_b) is not SourceReference:
            raise TypeError(
                "source_b must be a SourceReference"
            )

        if type(self.signals) is not DependencySignalScores:
            raise TypeError(
                "signals must be DependencySignalScores"
            )

        if (
            self.evidence is not None
            and type(self.evidence) is not DependencyEvidence
        ):
            raise TypeError(
                "evidence must be DependencyEvidence or None"
            )

        _number(
            self.dependency,
            "dependency",
            unit=True,
        )

        _number(
            self.weighted_signal_coverage,
            "weighted_signal_coverage",
            unit=True,
        )

        source_a = _canonical_source(self.source_a)
        source_b = _canonical_source(self.source_b)

        if source_a == source_b:
            raise ValueError(
                "source pair must not be diagonal"
            )

        if (
            serialize_source(*source_a)
            > serialize_source(*source_b)
        ):
            raise ValueError(
                "source pair must be canonically ordered"
            )


@dataclass(frozen=True, slots=True)
class DependencyCluster:
    threshold: float = field(repr=False)
    sources: tuple[SourceReference, ...] = field(repr=False)

    def __post_init__(self):
        _number(
            self.threshold,
            "threshold",
            unit=True,
        )

        if type(self.sources) is not tuple or not self.sources:
            raise TypeError(
                "sources must be a nonempty tuple"
            )

        if any(
            type(source) is not SourceReference
            for source in self.sources
        ):
            raise TypeError(
                "sources must contain SourceReference values"
            )

        identities = tuple(
            _canonical_source(source)
            for source in self.sources
        )

        if len(set(identities)) != len(identities):
            raise ValueError(
                "cluster sources must be unique"
            )

        if identities != tuple(
            sorted(
                identities,
                key=lambda source: serialize_source(*source),
            )
        ):
            raise ValueError(
                "cluster sources must be canonically ordered"
            )


def _canonical_source(value):
    return (
        value.kind,
        canonicalize_source(
            value.kind,
            value.identifier,
        ),
    )


def _canonical_claim(value):
    entity = canonicalize_entity(
        value.entity_namespace,
        value.entity,
    )

    attribute = canonicalize_attribute(
        value.attribute
    )

    claim_value = canonicalize_value(
        value.value
    )

    return (
        value.entity_namespace,
        entity,
        attribute,
        claim_value,
    )


def _weights(config):
    supplied = tuple(
        getattr(config, f"{name}_weight")
        for name in SIGNALS
    )

    total = sum(supplied)

    return tuple(
        value / total
        for value in supplied
    )


def combine_dependency(
    signals,
    config,
    *,
    excluded_signals=(),
):
    if type(signals) is not DependencySignalScores:
        raise TypeError(
            "signals must be DependencySignalScores"
        )

    if type(config) is not DependencyEstimatorConfig:
        raise TypeError(
            "config must be DependencyEstimatorConfig"
        )

    base_weights = _weights(config)

    observed_weights = tuple(
        base_weights[index]
        for index, name in enumerate(SIGNALS)
        if (
            name not in excluded_signals
            and getattr(signals, f"{name}_observable")
        )
    )

    observed_total = sum(observed_weights)

    if observed_total == 0.0:
        return 0.0, 0.0

    direct_signals = (
        "upstream",
        "citation",
        "assertion_lineage",
    )

    direct_dependency = max(
        (
            getattr(signals, name)
            for index, name in enumerate(SIGNALS)
            if (
                name in direct_signals
                and name not in excluded_signals
                and base_weights[index] > 0.0
                and getattr(signals, f"{name}_observable")
            )
        ),
        default=0.0,
    )

    contextual_dependency = sum(
        base_weights[index] * getattr(signals, name)
        for index, name in enumerate(SIGNALS)
        if (
            name not in direct_signals
            and name not in excluded_signals
            and getattr(signals, f"{name}_observable")
        )
    )

    dependency = max(
        direct_dependency,
        contextual_dependency,
    )

    coverage = observed_total

    return (
        max(0.0, min(1.0, dependency)),
        coverage,
    )


def estimate_dependencies(
    sources,
    observations,
    config,
):
    if (
        type(sources) is not tuple
        or type(observations) is not tuple
    ):
        raise TypeError(
            "sources and observations must be tuples"
        )

    if type(config) is not DependencyEstimatorConfig:
        raise TypeError(
            "config must be DependencyEstimatorConfig"
        )

    if not observations:
        raise InformationGraphError(
            "observation graph must not be empty"
        )

    if len(observations) > MAX_ASSERTIONS:
        raise InformationGraphError(
            "too many observations"
        )

    source_map = {}

    for source in sources:
        if type(source) is not Source:
            raise TypeError(
                "sources must contain Source values"
            )

        key = _canonical_source(source)
        previous = source_map.get(key)

        if (
            previous is not None
            and previous.owner_id != source.owner_id
        ):
            raise InformationGraphError(
                "canonical source has conflicting owners"
            )

        if previous is not None:
            raise InformationGraphError(
                "duplicate canonical source"
            )

        source_map[key] = source

    if (
        not source_map
        or len(source_map) > MAX_SOURCES
    ):
        raise InformationGraphError(
            "source count is outside bounds"
        )

    rows = []
    observation_ids = {}
    triples = set()
    source_attributes = set()
    claim_attributes = {}

    for observation in observations:
        if type(observation) is not Observation:
            raise TypeError(
                "observations must contain Observation values"
            )

        if observation.observation_id in observation_ids:
            raise InformationGraphError(
                "duplicate observation ID"
            )

        source_key = _canonical_source(
            observation.source
        )

        if source_key not in source_map:
            raise InformationGraphError(
                "observation source is unknown"
            )

        claim = _canonical_claim(
            observation.claim
        )

        property_key = claim[:3]

        claim_bytes = serialize_claim(
            *claim
        )

        attribute_bytes = serialize_attribute(
            *property_key
        )

        source_bytes = serialize_source(
            *source_key
        )

        triple = (
            source_bytes,
            attribute_bytes,
            claim_bytes,
        )

        if triple in triples:
            raise InformationGraphError(
                "duplicate canonical assertion"
            )

        triples.add(triple)

        source_attribute = (
            source_key,
            attribute_bytes,
        )

        if source_attribute in source_attributes:
            raise InformationGraphError(
                "source has multiple claims for an attribute"
            )

        source_attributes.add(source_attribute)

        previous = claim_attributes.setdefault(
            claim_bytes,
            attribute_bytes,
        )

        if previous != attribute_bytes:
            raise InformationGraphError(
                "claim belongs to multiple attributes"
            )

        row = (
            observation,
            source_key,
            source_bytes,
            property_key,
            claim,
            claim_bytes,
        )

        rows.append(row)

        observation_ids[
            observation.observation_id
        ] = row

    attributes = {
        row[3]
        for row in rows
    }

    claims = {
        row[5]
        for row in rows
    }

    if (
        len(attributes) > MAX_ATTRIBUTES
        or len(claims) > MAX_CLAIMS
    ):
        raise InformationGraphError(
            "information graph exceeds bounds"
        )

    claim_counts = {}

    for row in rows:
        claim_counts.setdefault(
            row[3],
            set(),
        ).add(row[5])

    conflicts = sum(
        len(values) * (len(values) - 1)
        for values in claim_counts.values()
    )

    if conflicts > MAX_CONFLICTS:
        raise InformationGraphError(
            "information graph exceeds conflict limit"
        )

    for observation, source_key, *_ in rows:

        for upstream in (
            observation.upstream_sources
            or ()
        ):
            upstream_key = _canonical_source(
                upstream
            )

            if upstream_key == source_key:
                raise InformationGraphError(
                    "source cannot reference itself as upstream"
                )

        for cited in (
            observation.cited_sources
            or ()
        ):
            cited_key = _canonical_source(
                cited
            )

            if cited_key not in source_map:
                raise InformationGraphError(
                    "cited source is unknown"
                )

            if cited_key == source_key:
                raise InformationGraphError(
                    "source cannot cite itself"
                )

        for parent_id in (
            observation.parent_observation_ids
            or ()
        ):
            parent = observation_ids.get(
                parent_id
            )

            if parent is None:
                raise InformationGraphError(
                    "parent observation is unknown"
                )

            if parent[1] == source_key:
                raise InformationGraphError(
                    "observation cannot reference its source"
                )

    ordered_keys = tuple(
        sorted(
            source_map,
            key=lambda key: serialize_source(*key),
        )
    )

    rows_by_source = {
        key: []
        for key in ordered_keys
    }

    for row in rows:
        rows_by_source[
            row[1]
        ].append(row)

    for values in rows_by_source.values():
        values.sort(
            key=lambda row: (
                serialize_attribute(*row[3]),
                row[5],
            )
        )

        if not values:
            raise InformationGraphError(
                "every source must have an observation"
            )

    known_owners = {
        source.owner_id
        for source in source_map.values()
        if source.owner_id is not None
    }
    ownership_is_universal = (
        len(known_owners) == 1
        and all(
            source.owner_id is not None
            for source in source_map.values()
        )
    )
    excluded_signals = (
        ("ownership",)
        if ownership_is_universal
        else ()
    )

    results = []

    for source_a, source_b in combinations(
        ordered_keys,
        2,
    ):
        signals, evidence = _signals(
            source_a,
            source_b,
            source_map,
            rows_by_source,
            observation_ids,
            config,
        )

        dependency, coverage = combine_dependency(
            signals,
            config,
            excluded_signals=excluded_signals,
        )

        results.append(
            PairwiseDependencyResult(
                SourceReference(*source_a),
                SourceReference(*source_b),
                signals,
                dependency,
                coverage,
                evidence,
            )
        )

    clusters = ()

    if (
        config.dependency_cluster_threshold
        is not None
    ):
        clusters = _clusters(
            ordered_keys,
            results,
            config.dependency_cluster_threshold,
        )

    return (
        tuple(results),
        clusters,
    )


def _signals(
    source_a,
    source_b,
    source_map,
    rows_by_source,
    observation_ids,
    config,
):
    rows_a = rows_by_source[source_a]
    rows_b = rows_by_source[source_b]

    upstream_a = _upstream(
        source_b,
        rows_a,
    )

    upstream_b = _upstream(
        source_a,
        rows_b,
    )

    upstream_sources_a = _upstream_sources(
        rows_a
    )

    upstream_sources_b = _upstream_sources(
        rows_b
    )

    shared_upstream = bool(
        upstream_sources_a
        & upstream_sources_b
    )

    upstream = float(
        upstream_a
        or upstream_b
        or shared_upstream
    )

    upstream_capture_a = all(
        row[0].upstream_sources is not None
        for row in rows_a
    )

    upstream_capture_b = all(
        row[0].upstream_sources is not None
        for row in rows_b
    )

    upstream_observable = bool(
        upstream
        or (
            upstream_capture_a
            and upstream_capture_b
        )
    )

    citation_a = _citation(
        source_b,
        rows_a,
    )

    citation_b = _citation(
        source_a,
        rows_b,
    )

    citation = float(
        citation_a
        or citation_b
    )

    citation_capture_a = all(
        row[0].cited_sources is not None
        for row in rows_a
    )

    citation_capture_b = all(
        row[0].cited_sources is not None
        for row in rows_b
    )

    citation_observable = bool(
        citation
        or (
            citation_capture_a
            and citation_capture_b
        )
    )

    parents_a = _parent_count(
        source_b,
        rows_a,
        observation_ids,
    )

    parents_b = _parent_count(
        source_a,
        rows_b,
        observation_ids,
    )

    ancestry_a = _parent_ancestry(
        rows_a,
        observation_ids,
    )

    ancestry_b = _parent_ancestry(
        rows_b,
        observation_ids,
    )

    assertion_lineage = float(
        source_b in ancestry_a
        or source_a in ancestry_b
        or bool(ancestry_a & ancestry_b)
    )

    lineage_capture_a = all(
        row[0].parent_observation_ids
        is not None
        for row in rows_a
    )

    lineage_capture_b = all(
        row[0].parent_observation_ids
        is not None
        for row in rows_b
    )

    assertion_lineage_observable = bool(
        assertion_lineage
        or (
            lineage_capture_a
            and lineage_capture_b
        )
    )

    owner_a = source_map[
        source_a
    ].owner_id

    owner_b = source_map[
        source_b
    ].owner_id

    ownership_observable = (
        owner_a is not None
        and owner_b is not None
    )

    ownership = float(
        ownership_observable
        and owner_a == owner_b
    )

    properties_a = {
        row[3]: row
        for row in rows_a
    }

    properties_b = {
        row[3]: row
        for row in rows_b
    }

    matches = tuple(
        sorted(
            (
                key
                for key in (
                    properties_a.keys()
                    & properties_b.keys()
                )
                if (
                    properties_a[key][4][3]
                    == properties_b[key][4][3]
                )
            ),
            key=lambda key: serialize_attribute(
                *key
            ),
        )
    )

    shared_retrieval_matches = sum(
        bool(
            _retrieval_resources(properties_a[key])
            & _retrieval_resources(properties_b[key])
        )
        for key in matches
    )

    retrieval = (
        shared_retrieval_matches / len(matches)
        if matches
        else 0.0
    )

    retrieval_observable = bool(
        matches
        and any(
            properties_a[key][0].retrievals
            or properties_b[key][0].retrievals
            for key in matches
        )
    )

    temporal_observable = bool(
        matches
        and all(
            properties_a[
                key
            ][0].source_modified_at
            is not None
            and properties_b[
                key
            ][0].source_modified_at
            is not None
            for key in matches
        )
    )

    temporal = 0.0
    time_deltas = ()

    if temporal_observable:
        temporal = sum(
            max(
                0.0,
                1.0
                - (
                    abs(
                        (
                            properties_a[key][0].source_modified_at
                            - properties_b[key][0].source_modified_at
                        ).total_seconds()
                    )
                    / config.temporal_window_seconds
                ),
            )
            for key in matches
        ) / len(matches)

        time_deltas = tuple(
            abs(
                (
                    properties_a[
                        key
                    ][0].source_modified_at
                    - properties_b[
                        key
                    ][0].source_modified_at
                ).total_seconds()
            )
            for key in matches
            if (
                0.0
                <= abs(
                    (
                        properties_a[
                            key
                        ][0].source_modified_at
                        - properties_b[
                            key
                        ][0].source_modified_at
                    ).total_seconds()
                )
                <= config.temporal_window_seconds
            )
        )

    graph = 0.0
    graph_observable = False

    signals = DependencySignalScores(
        upstream=upstream,
        citation=citation,
        assertion_lineage=assertion_lineage,
        ownership=ownership,
        temporal=temporal,
        graph=graph,
        retrieval=retrieval,
        upstream_observable=upstream_observable,
        citation_observable=citation_observable,
        assertion_lineage_observable=(
            assertion_lineage_observable
        ),
        ownership_observable=ownership_observable,
        temporal_observable=temporal_observable,
        graph_observable=graph_observable,
        retrieval_observable=retrieval_observable,
    )

    evidence = DependencyEvidence(
        source_a_upstream_of_source_b=upstream_b,
        source_b_upstream_of_source_a=upstream_a,
        source_a_cites_source_b=citation_a,
        source_b_cites_source_a=citation_b,
        source_a_parent_count=parents_a,
        source_b_parent_count=parents_b,
        same_owner=bool(ownership),
        matching_claim_count=len(matches),
        qualifying_time_deltas_seconds=time_deltas,
    )

    return (
        signals,
        evidence,
    )


def _retrieval_resources(row):
    observation = row[0]

    return {
        (
            value.kind,
            value.resource_id,
        )
        for value in (
            observation.retrievals
            or ()
        )
    }


def _upstream(
    other_source,
    rows,
):
    return any(
        _canonical_source(value)
        == other_source
        for observation, *_ in rows
        for value in (
            observation.upstream_sources
            or ()
        )
    )


def _upstream_sources(rows):
    return {
        _canonical_source(value)
        for observation, *_ in rows
        for value in (
            observation.upstream_sources
            or ()
        )
    }


def _citation(
    other_source,
    rows,
):
    return any(
        _canonical_source(value)
        == other_source
        for observation, *_ in rows
        for value in (
            observation.cited_sources
            or ()
        )
    )


def _parent_ancestry(
    rows,
    observation_ids,
):
    pending = [
        parent_id
        for observation, *_ in rows
        for parent_id in (
            observation.parent_observation_ids
            or ()
        )
    ]
    visited = set()
    sources = set()

    while pending:
        parent_id = pending.pop()

        if parent_id in visited:
            continue

        visited.add(parent_id)
        parent = observation_ids[parent_id]
        sources.add(parent[1])

        pending.extend(
            parent[0].parent_observation_ids
            or ()
        )

    return sources


def _parent_count(
    other_source,
    rows,
    observation_ids,
):
    count = 0

    for observation, *_ in rows:
        count += sum(
            observation_ids[
                parent_id
            ][1]
            == other_source
            for parent_id in (
                observation.parent_observation_ids
                or ()
            )
        )

    return count


def _clusters(
    source_keys,
    results,
    threshold,
):
    adjacent = {
        key: set()
        for key in source_keys
    }

    for result in results:
        if result.dependency >= threshold:
            source_a = (
                result.source_a.kind,
                result.source_a.identifier,
            )

            source_b = (
                result.source_b.kind,
                result.source_b.identifier,
            )

            adjacent[
                source_a
            ].add(source_b)

            adjacent[
                source_b
            ].add(source_a)

    remaining = set(
        source_keys
    )

    components = []

    for start in source_keys:
        if start not in remaining:
            continue

        stack = [
            start
        ]

        component = []

        remaining.remove(
            start
        )

        while stack:
            current = stack.pop()

            component.append(
                current
            )

            for value in reversed(
                source_keys
            ):
                if (
                    value
                    in adjacent[current]
                    and value in remaining
                ):
                    remaining.remove(
                        value
                    )

                    stack.append(
                        value
                    )

        ordered = tuple(
            SourceReference(
                *key
            )
            for key in source_keys
            if key in component
        )

        components.append(
            DependencyCluster(
                threshold,
                ordered,
            )
        )

    return tuple(
        components
    )
