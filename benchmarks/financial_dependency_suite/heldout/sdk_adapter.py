"""Translate the frozen benchmark provenance schema into the public SDK.

The frozen loader and its manifest retain their original occurrence field
names. Keep this application boundary outside the frozen input artifacts.
"""
from omneum import Claim, Observation, Source, SourceReference

from .loader import _omneum_entity, _omneum_source


def build_observations(case):
    observations = []
    source_ids = {}

    for candidate in case.candidates:
        source = _omneum_source(candidate.source, Source)
        source_ids[source] = candidate.source_id

        entity_namespace, entity = _omneum_entity(
            candidate.entity_namespace, candidate.entity,
        )
        claim = Claim(
            entity_namespace,
            entity,
            candidate.attribute,
            candidate.value,
        )

        provenance = candidate.provenance

        observations.append(
            Observation(
                observation_id=provenance.assertion_id,
                source=source,
                claim=claim,
                observed_at=provenance.observed_at,
                source_modified_at=(
                    provenance.source_modified_at
                ),
                upstream_sources=tuple(
                    _omneum_source(item, SourceReference)
                    for item in provenance.upstream_sources
                ),
                cited_sources=tuple(
                    _omneum_source(item, SourceReference)
                    for item in provenance.cited_sources
                ),
                parent_observation_ids=(
                    provenance.parent_assertion_ids
                ),
                retrievals=(),
            )
        )

    return tuple(observations), source_ids

