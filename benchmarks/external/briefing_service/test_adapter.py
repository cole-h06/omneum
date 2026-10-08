from copy import deepcopy
import json

import pytest

from benchmarks.external.briefing_service.adapter import (
    DEFAULT_DATASET, adapt_dataset, load_dataset, mapping_audit,
    normalize_point, observations_for_candidate,
)


@pytest.fixture
def raw():
    return json.loads(DEFAULT_DATASET.read_text())


def test_world_coverage_and_determinism(raw):
    before = deepcopy(raw)
    first = adapt_dataset(raw)
    assert first == adapt_dataset(raw)
    assert raw == before
    assert first["dataset"] == raw
    assert [c["record"] for c in first["candidates"]] == raw["items"]
    audit = mapping_audit(first)
    assert audit == mapping_audit(load_dataset())
    assert audit["candidate_count"] == 75
    assert len(audit["eligible_candidate_ids"]) == 15
    assert len(audit["ineligible_candidates"]) == 60
    assert audit["usable_assertion_count"] == audit["eligible_assertion_count"] == 48
    assert all(c["issues"] == ["missing_points_isolated"] for c in audit["ineligible_candidates"])
    assert len(audit["duplicate_pairs"]) == 5
    assert all(p["both_eligible"] and p["target_present"] for p in audit["duplicate_pairs"])
    assert all(p["matching_normalized_assertions"] == [] for p in audit["duplicate_pairs"])
    assert audit["cross_candidate_exact_matches"] == {}


def test_candidate_and_point_identity(raw):
    mapped = adapt_dataset(raw)
    all_ids = []
    for c in mapped["candidates"]:
        if not c["eligible"]:
            with pytest.raises(ValueError, match="ineligible"):
                observations_for_candidate(mapped, c["candidate_id"])
            continue
        observations = observations_for_candidate(mapped, c["candidate_id"])
        assert observations == observations_for_candidate(mapped, c["candidate_id"])
        for a, o in zip(c["assertions"], observations, strict=True):
            assert o.source.identifier == c["record"]["canonical_link"]
            assert o.metadata["candidate_id"] == c["record"]["id"]
            assert o.metadata["original_text"] == c["record"]["points_isolated"][a["point_indexes"][0]]
            assert o.claim.value == a["normalized_text"]
            assert o.observed_at.isoformat() == raw["generated_at"]
            all_ids.append(o.observation_id)
    assert len(set(all_ids)) == len(all_ids) == 48


def test_baseline_cannot_leak_into_observations(raw):
    original = adapt_dataset(raw)
    changed = deepcopy(raw)
    for record in changed["items"]:
        record["duplicate_of"] = "nonexistent-label"
        record["dup_rule"] = "changed"
        record["dup_score"] = 999
        record["also_in"] = ["unverified publisher"]
        record["source"] = "unverified owner"
    altered = adapt_dataset(changed)
    assert original["baseline"] != altered["baseline"]
    assert not all(p["target_present"] for p in mapping_audit(altered)["duplicate_pairs"])
    for c in original["candidates"]:
        if c["eligible"]:
            assert observations_for_candidate(original, c["candidate_id"]) == observations_for_candidate(altered, c["candidate_id"])


def test_all_provenance_remains_unknown():
    mapped = load_dataset()
    for c in mapped["candidates"]:
        if c["eligible"]:
            for o in observations_for_candidate(mapped, c["candidate_id"]):
                assert o.source.owner_id is None
                assert o.source_modified_at is None
                assert o.upstream_sources is None
                assert o.cited_sources is None
                assert o.parent_observation_ids is None
                assert o.retrievals is None
                assert o.dependency_signals == {}


@pytest.mark.parametrize("points", [None, [], "not a list", [None, "", "   ", 42]])
def test_unusable_points_do_not_remove_candidate_or_create_assertions(raw, points):
    raw["items"][0]["points_isolated"] = points
    mapped = adapt_dataset(raw)
    c = mapped["candidates"][0]
    assert len(mapped["candidates"]) == 75
    assert c["assertions"] == []
    assert not c["eligible"]
    assert c["issues"]


@pytest.mark.parametrize("field", ["canonical_link", "generated_at"])
def test_missing_required_mapping_fields_are_explicit(raw, field):
    record = next(r for r in raw["items"] if r.get("points_isolated"))
    del (raw if field == "generated_at" else record)[field]
    mapped = adapt_dataset(raw)
    c = next(c for c in mapped["candidates"] if c["candidate_id"] == record["id"])
    assert c["assertions"]  # Points retained even when observation cannot be built.
    assert not c["eligible"]
    assert "missing_or_invalid_" + field in c["issues"]


def test_missing_published_is_not_fabricated(raw):
    record = next(r for r in raw["items"] if r.get("points_isolated"))
    del record["published"]
    mapped = adapt_dataset(raw)
    assert "published" not in next(c["record"] for c in mapped["candidates"] if c["candidate_id"] == record["id"])
    assert observations_for_candidate(mapped, record["id"])[0].source_modified_at is None


def test_alignment_is_text_based_not_duplicate_group_based(raw):
    # Synthetic text variations exercise the adapter; they never alter the dataset.
    rows = [r for r in raw["items"] if r.get("points_isolated")][:2]
    raw["items"] = rows
    rows[0]["points_isolated"] = ["The Houthis deny targeting Mecca."]
    rows[1]["points_isolated"] = ["  THE Houthis deny targeting Mecca  "]
    mapped = adapt_dataset(raw)
    left = observations_for_candidate(mapped, rows[0]["id"])[0]
    right = observations_for_candidate(mapped, rows[1]["id"])[0]
    assert left.claim == right.claim
    assert left.observation_id != right.observation_id
    assert left.source != right.source
    assert len(mapping_audit(mapped)["cross_candidate_exact_matches"]) == 1
    rows[1]["duplicate_of"] = rows[0]["id"]
    rows[1]["points_isolated"] = ["The Houthis denied that a drone was shot down."]
    audit = mapping_audit(adapt_dataset(raw))
    assert audit["duplicate_pairs"][0]["matching_normalized_assertions"] == []
    assert normalize_point("The Houthis did not attack Mecca.") != normalize_point("The Houthis attacked Mecca.")


def test_repeated_points_preserve_occurrences_without_duplicate_observations(raw):
    raw["items"][0]["points_isolated"] = ["A fact.", " A FACT "]
    mapped = adapt_dataset(raw)
    c = mapped["candidates"][0]
    assert c["record"]["points_isolated"] == ["A fact.", " A FACT "]
    assert c["assertions"][0]["point_indexes"] == [0, 1]
    assert len(observations_for_candidate(mapped, c["candidate_id"])) == 1


def test_duplicate_candidate_ids_fail_without_silent_overwrite(raw):
    raw["items"][1]["id"] = raw["items"][0]["id"]
    with pytest.raises(ValueError, match="unique"):
        adapt_dataset(raw)


def test_focused_estimator_contract_for_unknown_signals(raw):
    # Two real candidates only: verifies adapter compatibility, not benchmark scoring.
    from omneum.dependency import DependencyEstimatorConfig, SIGNALS, estimate_dependencies

    mapped = adapt_dataset(raw)
    observations = tuple(o for cid in ("982758730c73", "3fa3005b12c1")
                         for o in observations_for_candidate(mapped, cid))
    sources = tuple(dict.fromkeys(o.source for o in observations))
    config = DependencyEstimatorConfig(
        upstream_weight=25.0, citation_weight=20.0, assertion_lineage_weight=20.0,
        ownership_weight=10.0, temporal_weight=10.0, graph_weight=15.0,
        temporal_window_seconds=7200.0,
    )
    pairs, _ = estimate_dependencies(sources, observations, config)
    assert len(pairs) == 1
    assert all(not getattr(pairs[0].signals, f"{signal}_observable") for signal in SIGNALS)
