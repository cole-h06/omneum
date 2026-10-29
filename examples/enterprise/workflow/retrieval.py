from collections.abc import Sequence
from pathlib import Path
from typing import TypedDict

from omneum import Observation, Source
from omneum.context_selection import claim_id, map_chunks

from ..agents.common import (
    BRIEF_SOURCE,
    GATEWAY_SOURCE,
    POLICY_SOURCE,
    REGISTRY_SOURCE,
    RUNBOOK_SOURCE,
    VENDOR_SOURCE,
)


class RetrievedChunk(TypedDict):
    chunk_id: str
    raw_text: str
    source: Source
    observation_ids: list[str]
    claim_ids: list[str]


DATA = Path(__file__).parents[1] / "data"
SOURCE_FILES = (
    (POLICY_SOURCE, "ai_data_governance_policy.json"),
    (RUNBOOK_SOURCE, "copilot_deployment_runbook.json"),
    (BRIEF_SOURCE, "copilot_readiness_brief.json"),
    (REGISTRY_SOURCE, "model_registry.json"),
    (GATEWAY_SOURCE, "ai_gateway.json"),
    (VENDOR_SOURCE, "vendor_data_controls.json"),
)


def collect_chunks(observations: Sequence[Observation]) -> list[RetrievedChunk]:
    # Each fixture is one original retrieved record supporting several observations.
    chunks: list[RetrievedChunk] = [
        {
            "chunk_id": Path(filename).stem,
            "raw_text": (DATA / filename).read_text(encoding="utf-8"),
            "source": source,
            "observation_ids": [
                item.observation_id for item in observations if item.source == source
            ],
            "claim_ids": sorted({
                claim_id(item.claim) for item in observations if item.source == source
            }),
        }
        for source, filename in SOURCE_FILES
    ]
    validate_chunks(observations, chunks)
    return chunks


def validate_chunks(
    observations: Sequence[Observation], chunks: Sequence[RetrievedChunk],
) -> None:
    by_id = {item.observation_id: item for item in observations}
    if len(by_id) != len(observations):
        raise ValueError("duplicate observation ID")
    claims = {claim_id(item.claim) for item in observations}
    map_chunks(chunks, claims)
    mapped = set()
    for chunk in chunks:
        if not {"source", "observation_ids"} <= chunk.keys():
            raise ValueError("chunk requires source and observation_ids")
        identifiers = chunk["observation_ids"]
        if not isinstance(identifiers, Sequence) or isinstance(identifiers, (str, bytes)):
            raise TypeError("observation_ids must be a sequence of strings")
        if any(not isinstance(identifier, str) or not identifier for identifier in identifiers):
            raise ValueError("observation IDs must be nonempty strings")
        if not identifiers or len(identifiers) != len(set(identifiers)):
            raise ValueError("chunk requires distinct observation IDs")
        if not set(identifiers) <= by_id.keys():
            raise ValueError("chunk references an unknown observation")
        associated = [by_id[identifier] for identifier in identifiers]
        if any(item.source != chunk["source"] for item in associated):
            raise ValueError("chunk source disagrees with its observations")
        if {claim_id(item.claim) for item in associated} != set(chunk["claim_ids"]):
            raise ValueError("chunk claims disagree with its observations")
        mapped.update(identifiers)
    if mapped != by_id.keys():
        raise ValueError("observation has no chunk mapping")
