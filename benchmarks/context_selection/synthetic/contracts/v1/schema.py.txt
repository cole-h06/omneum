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
class CandidateSpec:
    source_id: str
    source: SourceSpec
    text: str
    entity_namespace: str
    entity: str
    attribute: str
    value: Any
    provenance: ProvenanceSpec


@dataclass(frozen=True)
class BenchmarkCase:
    case_id: str
    domain: str
    question: str
    context_budget: int
    candidates: tuple[CandidateSpec, ...]


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
