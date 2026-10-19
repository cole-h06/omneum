from collections.abc import Mapping, Sequence
from uuid import UUID, uuid5

from omneum import (
    Claim,
    DependencyEstimatorConfig,
    Observation,
    Retrieval,
    Source,
    SourceReference,
)

from ..experiments.applied.agent_dataset.extraction.schema import Observation as ResearchObservation
from ..experiments.applied.agent_dataset.extraction.schema import SourceMetadata


SOURCE_SCOPE = UUID("57f5ab8e-a430-4be9-a7d0-5f12872d0a29")


def source_identifier(source_id: str) -> str:
    return f"v1:{SOURCE_SCOPE}:{uuid5(SOURCE_SCOPE, source_id)}"


def estimator(weights: Mapping[str, float]) -> DependencyEstimatorConfig:
    return DependencyEstimatorConfig(
        upstream_weight=float(weights["upstream"]),
        citation_weight=float(weights["citation"]),
        assertion_lineage_weight=float(weights["assertion_lineage"]),
        ownership_weight=float(weights["ownership"]),
        temporal_weight=float(weights["temporal"]),
        graph_weight=float(weights["graph"]),
        retrieval_weight=float(weights.get("retrieval", 0.0)),
        temporal_window_seconds=7200.0,
    )


def to_observations(
    sources: Sequence[SourceMetadata],
    observations: Sequence[ResearchObservation],
) -> tuple[Observation, ...]:
    source_objects = {
        source.source_id: Source(
            "internal_resource", source_identifier(source.source_id), source.owner_id,
        )
        for source in sources
    }
    if len(source_objects) != len(sources):
        raise ValueError("source IDs must be unique")

    def references(values):
        return None if values is None else tuple(
            SourceReference("internal_resource", source_identifier(value))
            for value in values
        )

    return tuple(
        Observation(
            observation_id=item.assertion_id,
            source=source_objects[item.source_id],
            claim=Claim(item.entity_namespace, item.entity, item.attribute, item.value),
            observed_at=item.observed_at,
            source_modified_at=item.source_modified_at,
            upstream_sources=references(item.upstream_source_ids),
            cited_sources=references(item.cited_source_ids),
            parent_observation_ids=item.parent_assertion_ids,
            retrievals=tuple(
                Retrieval(
                    value.retrieval_id, value.kind, value.resource_id,
                    value.retrieved_at, dict(value.fields),
                )
                for value in item.retrievals
            ),
            metadata=dict(item.metadata),
            dependency_signals=dict(item.dependency_signals),
        )
        for item in observations
    )
