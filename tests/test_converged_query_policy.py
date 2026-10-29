"""Converged support is authoritative; no second source adjustment in query coverage."""
from collections import Counter
import asyncio

import pytest

from omneum.context_selection import map_chunks, reconstruct, select_chunks


def test_converged_scores_and_marginal_query_coverage_use_no_source_multiplier():
    chunks = [
        dict(chunk_id="a", raw_text="original A", claim_ids=["x", "y"]),
        dict(chunk_id="copy", raw_text="copied A", claim_ids=["x", "y"]),
        dict(chunk_id="b", raw_text="original B", claim_ids=["y", "z"]),
    ]
    support = {"x": .8, "y": .4, "z": .2}
    relevance = {"x": 1., "y": .5, "z": 1.}
    mapping = map_chunks(chunks, support)
    trace = []
    result = select_chunks(mapping, support, 1000, "coverage_support_query",
                           claim_relevance=relevance, count_tokens=len, selection_trace=trace)
    first = {c["chunk_id"]: c for c in trace[0]["candidates"]}
    assert first["a"]["marginal_gain"] == pytest.approx(.8 + .4 * .5)
    assert first["a"]["utility"] == pytest.approx(1 / len(reconstruct(mapping, ["a"])))
    assert result["selection_order"] == ["a", "b"]
    second = {c["chunk_id"]: c for c in trace[1]["candidates"]}
    assert second["copy"]["marginal_gain"] == 0
    assert second["b"]["marginal_gain"] == .2
    assert result["context"] == reconstruct(mapping, result["selected_chunk_ids"])
    assert result["token_usage"] == len(result["context"]) <= 1000


def test_zero_converged_support_cannot_be_rescued_by_relevance():
    mapping = map_chunks([dict(chunk_id="a", raw_text="relevant", claim_ids=["x"])], ["x"])
    result = select_chunks(mapping, {"x": 0.}, 1000, "coverage_support_query",
                           claim_relevance={"x": 1.})
    assert result["selected_chunk_ids"] == []


def test_singleton_denominators_are_cached_while_whole_proposals_are_counted():
    chunks = [dict(chunk_id=k, raw_text=k, claim_ids=[k]) for k in ("a", "b", "c", "d")]
    mapping = map_chunks(chunks, list("abcd"))
    calls = Counter()
    def count(text):
        calls[text] += 1
        return len(text)
    result = select_chunks(mapping, dict.fromkeys("abcd", 1.), 1000, "coverage_support_query",
                           claim_relevance=dict.fromkeys("abcd", 1.), count_tokens=count)
    # Each singleton is counted for its first proposal and once for its fixed
    # denominator, regardless of the number of greedy rounds it remains in.
    assert all(calls[reconstruct(mapping, [k])] == 2 for k in "abcd")
    assert calls[result["context"]] >= 1
    assert result["selected_chunk_ids"] == list("abcd")
    assert result == select_chunks(mapping, dict.fromkeys("abcd", 1.), 1000,
        "coverage_support_query", claim_relevance=dict.fromkeys("abcd", 1.), count_tokens=len)


def test_sdk_explicit_query_weights_use_converged_dependency_adjusted_scores(monkeypatch):
    from dataclasses import replace
    from omneum import open_stdio_client
    from omneum.client import _evaluate_context
    from omneum.context_selection import claim_id, _inferred_coverage_terms
    from benchmarks.context_selection.config import estimator_config
    from benchmarks.context_selection.deployment import benchmark_deployment
    from test_query_context import inputs

    observations, chunks, _ = inputs()
    independent = tuple(replace(o, parent_observation_ids=(), upstream_sources=(),
                                cited_sources=(), source_modified_at=None) for o in observations)
    relevance = {claim_id(o.claim): .75 for o in observations}
    def no_model():
        raise AssertionError("Explicit upstream query relevance must not load a model")
    monkeypatch.setattr('omneum.query_context._embedding_model', no_model)

    async def run():
        evaluations = []
        with benchmark_deployment() as (config, server):
            async with open_stdio_client(config, server) as client:
                for values in (observations, independent):
                    expected = _evaluate_context(values, estimator=estimator_config())
                    support = {claim_id(c.claim): c.support for c in expected.claim_support}
                    diagnostics = {}
                    result = await client.prepare_context(values, chunks, estimator=estimator_config(),
                        token_budget=1000, count_tokens=len, strategy='coverage_support_query',
                        claim_relevance=relevance, query_anchoring=False, query_diagnostics=diagnostics)
                    assert result['evaluation']['claim_support'] == pytest.approx(support)
                    evaluations.append(support)
                    first = {c['chunk_id']: c for c in diagnostics['utility_trace'][0]['candidates']}
                    for chunk in chunks:
                        terms = _inferred_coverage_terms(expected, chunks)
                        gain = sum(terms[chunk['chunk_id']][c][1] * relevance[c] for c in chunk['claim_ids'])
                        assert first[chunk['chunk_id']]['marginal_gain'] == pytest.approx(gain)
                    assert result['selection']['selected_tokens'] == len(result['context']) <= 1000
        assert evaluations[0] != evaluations[1]
    asyncio.run(run())


def test_question_coverage_preserves_conflicting_values_without_changing_inference():
    from datetime import datetime, timezone
    from omneum import Claim, Observation, Source
    from omneum.client import _evaluate_context
    from omneum.context_selection import claim_id, reconstruct_context
    from benchmarks.context_selection.config import estimator_config
    observations = [Observation(k, Source('web_document', 'https://' + k + '.example'),
        Claim('device', 'pump', 'pressure_rating', value),
        observed_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
        for k,value in [('a', 200), ('b', 200), ('c', 250)]]
    evaluation = _evaluate_context(observations, estimator=estimator_config())
    chunks = [dict(chunk_id=o.observation_id, raw_text='Pressure reported ' + str(o.claim.value),
        source=o.source, claim_ids=[claim_id(o.claim)]) for o in observations]
    support = {claim_id(c.claim):c.support for c in evaluation.claim_support}
    trace = []
    result = reconstruct_context(evaluation, chunks, token_budget=1000,
        strategy='coverage_support_query',claim_relevance=dict.fromkeys(support, 1.),_selection_trace=trace)
    assert result['selected_chunk_ids'] == ['a', 'b', 'c']
    assert all(s > 0 for s in support.values())
    assert result['claim_coverage'] == {'covered':2,'total':2}
    after = {c['chunk_id']:c for c in trace[1]['candidates']}
    assert after['c']['marginal_gain'] > 0
    independent = reconstruct_context(evaluation, chunks, token_budget=1000)
    assert independent['claim_coverage'] == {'covered':2,'total':2}


def test_property_marginal_gain_is_improvement_and_preserves_qualifications():
    chunks=[dict(chunk_id='cheap',raw_text='x',claim_ids=['weak']),
            dict(chunk_id='strong',raw_text='y'*100,claim_ids=['strong','condition']),
            dict(chunk_id='repeat',raw_text='z'*120,claim_ids=['weak'])]
    support={'weak':.3,'strong':.9,'condition':.2};q={'weak':1.,'strong':.5,'condition':1.}
    mapping=map_chunks(chunks,support)
    mapping['claim_properties']={'weak':('device','pump','pressure'),
        'strong':('device','pump','pressure'),'condition':('device','pump','interlock')}
    trace=[]
    result=select_chunks(mapping,support,1000,'coverage_support_query',count_tokens=len,claim_relevance=q,selection_trace=trace)
    assert result['selection_order']==['cheap','strong']
    second={c['chunk_id']:c for c in trace[1]['candidates']}
    assert second['strong']['marginal_gain']==pytest.approx(.9*.5-.3+.2)
    assert second['repeat']['marginal_gain']==0
    assert result['token_usage']==len(result['context'])<=1000


def test_structured_conditions_are_not_mistaken_for_competing_scalar_values():
    from omneum import evaluate
    from omneum.context_selection import claim_id, reconstruct_context
    evaluation=evaluate([dict(url='https://a.example',claim=dict(entity_namespace='device',entity='pump',attribute='stop_rule'),
        value={'condition':'pressure below threshold','consequence':'stop'}),
        dict(url='https://b.example',claim=dict(entity_namespace='device',entity='pump',attribute='stop_rule'),
        value={'condition':'temperature above threshold','consequence':'stop'})])
    chunks=[dict(chunk_id=str(i),raw_text='Original condition '+str(i),claim_ids=[claim_id(c.claim)]) for i,c in enumerate(evaluation.claim_support)]
    q={claim_id(c.claim):1. for c in evaluation.claim_support}
    result=reconstruct_context(evaluation,chunks,token_budget=1000,strategy='coverage_support_query',claim_relevance=q)
    assert result['claim_coverage']=={'covered':2,'total':2}
    assert len(result['selected_chunk_ids'])==2
