import json
from dataclasses import replace
from pathlib import Path

import pytest

from omneum import Claim
from omneum.canonicalization import canonicalize_source
from .schema import SourceSpec

from benchmarks.context_selection.synthetic.loader import (
    application_candidates,
    build_observations,
    load_case,
    load_ground_truth,
)


def test_case_loader(tmp_path):
    case_path = tmp_path / "case.json"
    case_path.write_text(json.dumps({
        "id": "test_case",
        "domain": "test",
        "question": "What happened?",
        "context_budget": 1,
        "candidates": [
            {
                "source_id": "source_a",
                "source": {
                    "kind": "web_document",
                    "identifier": "https://example.com/a",
                },
                "text": "Candidate text.",
                "entity_namespace": "test",
                "entity": "example",
                "attribute": "value",
                "value": 42,
                "provenance": {
                    "assertion_id": "assertion-a",
                    "observed_at": "2026-09-11T00:00:00Z",
                    "source_modified_at": "2026-09-10T00:00:00Z",
                    "upstream_sources": [],
                    "cited_sources": [],
                    "parent_assertion_ids": [],
                },
            }
        ],
    }))

    case = load_case(case_path)
    observations, source_ids = build_observations(case)
    candidates = application_candidates(case)

    assert case.case_id == "test_case"
    assert case.context_budget == 1
    assert len(observations) == 1
    assert next(iter(source_ids.values())) == "source_a"
    assert candidates == [
        {
            "source": "source_a",
            "text": "Candidate text.",
        }
    ]


def test_ground_truth_separate(tmp_path):
    case_path = tmp_path / "case.json"
    truth_path = tmp_path / "ground_truth.json"

    case_path.write_text(json.dumps({
        "id": "test_case",
        "domain": "test",
        "question": "What happened?",
        "context_budget": 1,
        "candidates": [],
    }))

    truth_path.write_text(json.dumps({
        "case_id": "test_case",
        "answer": "secret answer",
        "supporting_sources": ["source_a"],
        "scoring": {
            "required": ["secret answer"],
            "forbidden": ["wrong answer"],
        },
    }))

    case = load_case(case_path)
    truth = load_ground_truth(truth_path)

    assert case.case_id == truth.case_id
    assert not hasattr(case, "answer")
    assert not hasattr(case, "supporting_sources")
    assert truth.answer == "secret answer"


# Exercise the production canonicalizer without starting a daemon or providers.
CASE_PATHS = sorted((Path(__file__).parent / "cases").glob("*/case.json"))


@pytest.mark.parametrize("path", CASE_PATHS, ids=lambda path: path.parent.name)
def test_all_heldout_sources_and_provenance_are_sdk_compatible(path):
    case = load_case(path)
    observations, source_ids = build_observations(case)
    assert len(CASE_PATHS) == 24
    assert build_observations(case) == (observations, source_ids)
    assert len(source_ids) == len(case.candidates)
    original_ids = {candidate.source: candidate.source_id for candidate in case.candidates}
    adapted_ids = {
        (source.kind, canonicalize_source(source.kind, source.identifier)): source_id
        for source, source_id in source_ids.items()
    }
    assert len(adapted_ids) == len(original_ids)
    for candidate, observation in zip(case.candidates, observations, strict=True):
        assert observation.source.kind == "web_document"
        assert observation.source.identifier == candidate.source.identifier
        assert source_ids[observation.source] == candidate.source_id
        assert observation.claim.attribute == Claim(
            candidate.entity_namespace, candidate.entity,
            candidate.attribute, candidate.value,
        ).attribute
        assert observation.claim.value == candidate.value
        assert observation.observation_id == candidate.provenance.assertion_id
        assert observation.observed_at == candidate.provenance.observed_at
        assert observation.source_modified_at == candidate.provenance.source_modified_at
        assert observation.parent_observation_ids == candidate.provenance.parent_assertion_ids
        for field in ("upstream_sources", "cited_sources"):
            original = getattr(candidate.provenance, field)
            adapted = getattr(observation, field)
            assert [ref.identifier for ref in adapted] == [ref.identifier for ref in original]
            assert [
                adapted_ids[(ref.kind, canonicalize_source(ref.kind, ref.identifier))]
                for ref in adapted
            ] == [original_ids[ref] for ref in original]
    # Loading and adapting must not rewrite the role metadata or application pool.
    assert case == load_case(path)
    assert application_candidates(case) == [
        {"source": candidate.source_id, "text": candidate.text}
        for candidate in case.candidates
    ]


def test_analytics_derived_metric_cycle_regression():
    case = load_case(Path(__file__).parent / "cases/analytics_derived_metric_cycle/case.json")
    assert case.candidates[0].source.kind == "derived_table"
    with pytest.raises(ValueError, match="unknown source kind"):
        canonicalize_source(case.candidates[0].source.kind, case.candidates[0].source.identifier)
    observations, _ = build_observations(case)
    assert observations[0].source.kind == "web_document"
    # The exact three-node repair cycle survives the boundary mapping.
    assert observations[0].upstream_sources[0].identifier == observations[2].source.identifier
    assert observations[1].upstream_sources[0].identifier == observations[0].source.identifier
    assert observations[2].upstream_sources[0].identifier == observations[1].source.identifier
    assert all(ref.kind == "web_document" for obs in observations for ref in obs.upstream_sources)


@pytest.mark.parametrize("spec, error", [
    (SourceSpec("unrecognized_role", "https://example.com/a"), "unknown source kind"),
    (SourceSpec("derived_table", "not-a-url"), "invalid web document identifier"),
])
def test_invalid_adapter_identity(spec, error):
    case = load_case(CASE_PATHS[0])
    case = replace(case, candidates=(replace(case.candidates[0], source=spec),))
    with pytest.raises(ValueError, match=error):
        build_observations(case)


def decode_benchmark_entity(claim):
    assert claim.entity_namespace == "service"
    prefix = "heldout-entity-v1:"
    assert claim.entity.startswith(prefix)
    return tuple(json.loads(bytes.fromhex(claim.entity[len(prefix):]).decode("ascii")))


@pytest.mark.parametrize("path", CASE_PATHS, ids=lambda path: path.parent.name)
def test_complete_client_snapshot_for_every_heldout_case(path):
    from omneum.client import _snapshot_observations

    case = load_case(path)
    observations, _ = build_observations(case)
    snapshots = _snapshot_observations(observations)
    assert len(snapshots) == len(case.candidates)
    assert _snapshot_observations(snapshots) == snapshots
    for candidate, observation, snapshot in zip(case.candidates, observations, snapshots, strict=True):
        assert decode_benchmark_entity(snapshot.claim) == (
            candidate.entity_namespace, candidate.entity,
        )
        # Source URLs may undergo the SDK's existing URL normalization.
        assert snapshot.source.identifier == canonicalize_source(
            observation.source.kind, observation.source.identifier,
        )
        assert snapshot == replace(observation, source=snapshot.source)


def test_analytics_namespace_regression():
    from omneum.canonicalization import canonicalize_entity
    from omneum.client import _snapshot_observations

    case = load_case(Path(__file__).parent / "cases/analytics_derived_metric_cycle/case.json")
    candidate = case.candidates[0]
    assert candidate.entity_namespace == "analytics"
    assert canonicalize_entity(candidate.entity_namespace, candidate.entity) == (
        candidate.entity.lower()
    )
    snapshots = _snapshot_observations(build_observations(case)[0])
    assert len({(o.claim.entity_namespace, o.claim.entity) for o in snapshots}) == 1
    assert decode_benchmark_entity(snapshots[0].claim) == (
        "analytics", "Solis August 17 daily active accounts",
    )


def test_dataset_identity_partitions():
    from omneum.client import _snapshot_observations

    original_to_adapted = {}
    adapted_to_original = {}
    original_claims = {}
    adapted_claims = {}
    for path in CASE_PATHS:
        case = load_case(path)
        snapshots = _snapshot_observations(build_observations(case)[0])
        for c, o in zip(case.candidates, snapshots, strict=True):
            original = (c.entity_namespace, c.entity)
            adapted = (o.claim.entity_namespace, o.claim.entity)
            assert original_to_adapted.setdefault(original, adapted) == adapted
            assert adapted_to_original.setdefault(adapted, original) == original
            original_claim = Claim(c.entity_namespace, c.entity, c.attribute, c.value)
            assert original_claims.setdefault(original_claim, o.claim) == o.claim
            assert adapted_claims.setdefault(o.claim, original_claim) == original_claim
    assert len(original_to_adapted) == len(adapted_to_original) == 36


def test_entity_encoding_collisions():
    from omneum.canonicalization import canonicalize_entity
    from .loader import _omneum_entity

    identities = [
        ("analytics", "same"), ("software", "same"),
        ("analytics", "Same"), ("analytics", " same "),
        ("analytics", "é"), ("analytics", "e\u0301"),
        ("analytics", 'a:b["c"]'), ("analytics:a", 'b["c"]'),
        ("analytics", "heldout-entity-v1:6162"),
    ]
    adapted = [_omneum_entity(*identity) for identity in identities]
    assert len(set(adapted)) == len(identities)
    for identity, (namespace, entity) in zip(identities, adapted, strict=True):
        assert canonicalize_entity(namespace, entity) == entity
        assert decode_benchmark_entity(Claim(namespace, entity, "value", 1)) == identity
