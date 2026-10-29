"""Upstream atomic predicates use the existing observations/chunk contracts."""
import asyncio
from copy import deepcopy
from datetime import datetime, timezone
import json

import pytest

from omneum import Source, extract_observations, open_stdio_client
from omneum.client import _evaluate_context
from omneum.context_selection import claim_id, map_chunks, reconstruct_context, token_count
from omneum.dependency import InformationGraphError
from benchmarks.context_selection.config import estimator_config
from benchmarks.context_selection.deployment import benchmark_deployment


def atomic_inputs():
    base = dict(entity_namespace="service", entity="worker", attribute="deduplication", value="event key")
    detail = dict(entity_namespace="service", entity="worker", attribute="commit_boundary",
                  value="event key and update in one transaction")
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    inputs = [dict(id=k, source=Source("web_document", f"https://{k}.example"), text=text,
                   observed_at=now, parent_observation_ids=parents)
              for k, text, parents in (
                  ("short", "Check event key.", ()),
                  ("detail", "Check the event key and commit its write together with the update in one transaction.", ()),
                  ("copy", "Check event key (copied guidance).", ("short:0",)),
              )]
    responses = iter([[base], [base, detail], [base]])
    async def provider(prompt):
        assert "atomic" in prompt and "Do not infer" in prompt
        return {"text": json.dumps(next(responses))}
    observations = asyncio.run(extract_observations(inputs, provider=provider))
    chunks = [dict(chunk_id=c["id"], source=c["source"], raw_text=c["text"],
                   claim_ids=sorted({claim_id(o.claim) for o in observations if o.metadata["chunk_id"] == c["id"]}))
              for c in inputs]
    return observations, chunks


def test_multiple_atomic_claims_add_qualification_without_repeat_credit():
    observations, chunks = atomic_inputs()
    evaluation = _evaluate_context(observations, estimator=estimator_config())
    support = {claim_id(c.claim): c.support for c in evaluation.claim_support}
    assert len(observations) == 4 and len(support) == 2
    assert len(chunks[1]["claim_ids"]) == 2
    trace = []
    result = reconstruct_context(evaluation, chunks, token_budget=1000,
        strategy="coverage_support_query", claim_relevance=dict.fromkeys(support, 1.), _selection_trace=trace)
    assert result["selection_order"] == ["short", "detail"]
    second = {c["chunk_id"]: c for c in trace[1]["candidates"]}
    detail = next(c for c in evaluation.claim_support if c.claim.attribute == "commit_boundary")
    assert second["detail"]["marginal_gain"] > detail.support
    assert sum(s["marginal_gain"] for s in result["selection_scores"]) == pytest.approx(sum(support.values()))
    assert second["copy"]["marginal_gain"] == 0
    assert result["token_usage"] == token_count(result["context"]) <= 1000
    assert result["claim_coverage"] == {"covered": 2, "total": 2}
    assert any(p.dependency > 0 for p in evaluation.pairwise_dependencies)


def test_repeated_passages_can_share_a_single_source_claim_observation():
    observations, chunks = atomic_inputs()
    repeated = {**chunks[0], "chunk_id": "second-passage", "raw_text": "Another rendering of the same event-key check."}
    evaluation = _evaluate_context(observations, estimator=estimator_config())
    mapping = map_chunks([*chunks, repeated], [claim_id(c.claim) for c in evaluation.claim_support])
    assert mapping["chunk_claims"]["short"] == mapping["chunk_claims"]["second-passage"]
    result = reconstruct_context(evaluation, [*chunks, repeated], token_budget=1000,
        strategy="coverage_support_query", claim_relevance={claim_id(c.claim): 1. for c in evaluation.claim_support})
    assert "second-passage" not in result["selected_chunk_ids"]


def test_payload_changes_cannot_change_structural_inference(monkeypatch):
    import omneum.client as client_module
    observations, chunks = atomic_inputs()
    before = deepcopy(chunks)
    infer = client_module.infer
    def check_graph(graph):
        assert all(c['raw_text'] not in repr(graph) for c in chunks)
        return infer(graph)
    monkeypatch.setattr(client_module, 'infer', check_graph)
    evaluation = _evaluate_context(observations, estimator=estimator_config())
    altered = [{**c, "raw_text": "Entirely different text; the supplied atomic claims remain authoritative."} for c in chunks]
    other = _evaluate_context(observations, estimator=estimator_config())
    assert other.claim_support == evaluation.claim_support
    assert other.source_reliability == evaluation.source_reliability
    relevance = {claim_id(c.claim): 1. for c in evaluation.claim_support}
    for values in (chunks, altered):
        result = reconstruct_context(evaluation, values, strategy="coverage_support_query",
                                     token_budget=1000, claim_relevance=relevance)
        by_id = {c["chunk_id"]: c["raw_text"] for c in values}
        assert all(c["raw_text"] == by_id[c["chunk_id"]] for c in result["chunks"])
    assert chunks == before


def test_duplicate_occurrences_are_not_fake_independent_assertions():
    from dataclasses import replace
    observations, _ = atomic_inputs()
    duplicate = replace(observations[0], observation_id="second-occurrence")
    with pytest.raises(InformationGraphError, match="duplicate canonical assertion"):
        _evaluate_context([*observations, duplicate], estimator=estimator_config())


def test_upstream_augmentation_coalesces_source_claim_repeats_and_preserves_lineage():
    from dataclasses import replace
    from benchmarks.context_selection.synthetic.atomic_mapping_comparison import _augment_observations
    observations, _ = atomic_inputs()
    anchors = (observations[0], observations[-1])
    duplicate = replace(observations[0], observation_id="short:repeat")
    qualification = replace(observations[2], observation_id="copy:qualifier", source=observations[-1].source,
        metadata={"chunk_id": "copy"}, parent_observation_ids=())
    merged = _augment_observations(anchors, [duplicate, qualification])
    assert len(merged) == 3
    assert merged[-1].parent_observation_ids == observations[-1].parent_observation_ids
    evaluation = _evaluate_context(merged, estimator=estimator_config())
    assert len(evaluation.claim_support) == 2


def test_coalescing_graph_occurrences_preserves_every_passage_membership():
    from dataclasses import replace
    from benchmarks.context_selection.synthetic.atomic_mapping_comparison import _augment_observations, _claim_ids_by_chunk
    observations, _ = atomic_inputs()
    anchor = observations[0]
    other = replace(observations[2], observation_id="other-anchor", source=anchor.source,
                    metadata={"chunk_id": "other-passage"})
    repetition = replace(anchor, observation_id="other-repeat", metadata={"chunk_id": "other-passage"})
    values = _augment_observations([anchor, other], [repetition])
    memberships = _claim_ids_by_chunk([anchor, other], [repetition])
    assert len(values) == 2  # A single graph edge for each of the two claims.
    assert claim_id(anchor.claim) in memberships['other-passage']
    assert claim_id(anchor.claim) in memberships['short']
    evaluation = _evaluate_context(values, estimator=estimator_config())
    assert len(evaluation.claim_support) == 2


def test_atomic_mapping_through_sdk_preserves_query_utility_and_original_context():
    observations, chunks = atomic_inputs()
    expected = _evaluate_context(observations, estimator=estimator_config())
    support = {claim_id(c.claim): c.support for c in expected.claim_support}
    async def run():
        with benchmark_deployment() as (config, server):
            async with open_stdio_client(config, server) as client:
                diagnostics = {}
                result = await client.prepare_context(observations, chunks, estimator=estimator_config(),
                    token_budget=1000, strategy="coverage_support_query", claim_relevance=dict.fromkeys(support, 1.),
                    query_anchoring=False, query_diagnostics=diagnostics)
                assert result["evaluation"]["claim_support"] == pytest.approx(support)
                assert result["packed_chunk_ids"] == ["detail", "short"]
                assert result["selection"]["selected_tokens"] == token_count(result["context"]) <= 1000
                first = {c["chunk_id"]: c for c in diagnostics["utility_trace"][0]["candidates"]}
                from omneum.canonicalization import canonicalize_source
                detail_source = chunks[1]['source']
                mass = sum(s.contribution for c in expected.claim_support for s in c.supporting_sources if (s.source.kind, s.source.identifier) == (detail_source.kind, canonicalize_source(detail_source.kind, detail_source.identifier)))
                assert first["detail"]["marginal_gain"] == pytest.approx(mass)
                assert diagnostics["selection_order"] == ["short", "detail"]
    asyncio.run(run())
