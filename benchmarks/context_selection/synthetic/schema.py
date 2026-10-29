from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class SourceSpec:
    kind: str
    identifier: str


@dataclass(frozen=True)
class ProvenanceSpec:
    assertion_id: str
    observed_at: datetime
    source_modified_at: datetime | None
    upstream_sources: tuple[SourceSpec, ...]
    cited_sources: tuple[SourceSpec, ...]
    parent_assertion_ids: tuple[str, ...]


@dataclass(frozen=True)
class ClaimSpec:
    entity_namespace: str
    entity: str
    attribute: str
    value: Any
    observation_id: str
    claim_id: str | None = None
    evidence: tuple[dict[str, Any], ...] = ()


@dataclass(frozen=True)
class CandidateSpec:
    source_id: str
    source: SourceSpec
    text: str
    entity_namespace: str | None
    entity: str | None
    attribute: str | None
    value: Any
    provenance: ProvenanceSpec
    claims: tuple[ClaimSpec, ...] = ()


def candidate_claims(candidate):
    """All facts, or the unchanged legacy singleton; never a primary projection."""
    if candidate.claims:
        return candidate.claims
    return (ClaimSpec(candidate.entity_namespace, candidate.entity,
                      candidate.attribute, candidate.value,
                      candidate.provenance.assertion_id),)


@dataclass(frozen=True)
class BenchmarkCase:
    case_id: str
    domain: str
    question: str
    context_budget: int
    candidates: tuple[CandidateSpec, ...]
    category: str | None = None
    adversarial_category: str | None = None


@dataclass(frozen=True)
class AnswerScoring:
    required: tuple[str, ...]
    forbidden: tuple[str, ...]


@dataclass(frozen=True)
class GroundTruth:
    case_id: str
    answer: Any
    supporting_sources: tuple[str, ...]
    scoring: AnswerScoring
