import json
from datetime import datetime
from pathlib import Path

from omneum import Claim, Observation, Source, SourceReference

from .schema import (
    AnswerScoring,
    BenchmarkCase,
    CandidateSpec,
    GroundTruth,
    ProvenanceSpec,
    SourceSpec,
)


def _datetime(value):
    if value is None:
        return None

    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _source(data):
    return SourceSpec(
        kind=data["kind"],
        identifier=data["identifier"],
    )


def _references(values):
    return tuple(_source(value) for value in values)


def load_case(path):
    path = Path(path)
    data = json.loads(path.read_text())

    candidates = []

    for item in data["candidates"]:
        provenance = item["provenance"]

        candidates.append(
            CandidateSpec(
                source_id=item["source_id"],
                source=_source(item["source"]),
                text=item["text"],
                entity_namespace=item["entity_namespace"],
                entity=item["entity"],
                attribute=item["attribute"],
                value=item["value"],
                provenance=ProvenanceSpec(
                    assertion_id=provenance["assertion_id"],
                    observed_at=_datetime(
                        provenance["observed_at"]
                    ),
                    source_modified_at=_datetime(
                        provenance.get("source_modified_at")
                    ),
                    upstream_sources=_references(
                        provenance.get("upstream_sources", [])
                    ),
                    cited_sources=_references(
                        provenance.get("cited_sources", [])
                    ),
                    parent_assertion_ids=tuple(
                        provenance.get(
                            "parent_assertion_ids",
                            [],
                        )
                    ),
                ),
            )
        )

    return BenchmarkCase(
        case_id=data["id"],
        domain=data["domain"],
        question=data["question"],
        context_budget=data["context_budget"],
        candidates=tuple(candidates),
    )


def load_ground_truth(path):
    path = Path(path)
    data = json.loads(path.read_text())

    scoring = data["scoring"]

    return GroundTruth(
        case_id=data["case_id"],
        answer=data["answer"],
        supporting_sources=tuple(
            data["supporting_sources"]
        ),
        scoring=AnswerScoring(
            required=tuple(scoring["required"]),
            forbidden=tuple(scoring.get("forbidden", [])),
        ),
    )


def build_observations(case):
    observations = []
    source_ids = {}

    for candidate in case.candidates:
        source = Source(
            candidate.source.kind,
            candidate.source.identifier,
        )
        source_ids[source] = candidate.source_id

        claim = Claim(
            candidate.entity_namespace,
            candidate.entity,
            candidate.attribute,
            candidate.value,
        )

        provenance = candidate.provenance

        observations.append(
            Observation(
                assertion_id=provenance.assertion_id,
                source=source,
                claim=claim,
                observed_at=provenance.observed_at,
                source_modified_at=(
                    provenance.source_modified_at
                ),
                upstream_sources=tuple(
                    SourceReference(
                        item.kind,
                        item.identifier,
                    )
                    for item in provenance.upstream_sources
                ),
                cited_sources=tuple(
                    SourceReference(
                        item.kind,
                        item.identifier,
                    )
                    for item in provenance.cited_sources
                ),
                parent_assertion_ids=(
                    provenance.parent_assertion_ids
                ),
                retrievals=(),
            )
        )

    return tuple(observations), source_ids


def application_candidates(case):
    return [
        {
            "source": candidate.source_id,
            "text": candidate.text,
        }
        for candidate in case.candidates
    ]
