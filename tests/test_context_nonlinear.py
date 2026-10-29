"""Deterministic marginal scoring and SDK boundary tests for nonlinear packing."""
import asyncio
from copy import deepcopy
import json
from math import sqrt

import pytest

from omneum import open_stdio_client
from omneum.context_selection import map_chunks, reconstruct, reconstruct_context, select_chunks
from omneum.mcp import ClientSession
from omneum.query_context import normalize_chunk_relevance
from benchmarks.context_selection.config import estimator_config
from benchmarks.context_selection.deployment import benchmark_deployment
from test_query_context import inputs


def chunk(key, claims, text=None):
    return {'chunk_id': key, 'claim_ids': claims, 'raw_text': key if text is None else text}


def select(chunks, support, relevance=None, budget=1000, **options):
    trace = []
    result = select_chunks(map_chunks(chunks, support), support, budget,
        'coverage_support_nonlinear', count_tokens=options.pop('count_tokens', len),
        chunk_relevance=relevance, selection_trace=trace, **options)
    return result, trace


def candidates(step):
    return {c['chunk_id']: c for c in step['candidates']}


def test_uncovered_covered_and_multiple_iterations():
    chunks = [chunk('a', ['x']), chunk('b', ['x']), chunk('c', ['y']), chunk('d', ['x'])]
    result, trace = select(chunks, {'x': 1, 'y': .4}, dict.fromkeys('abcd', 1), token_cost_exponent=0)
    assert result['selection_order'] == ['a', 'c', 'b', 'd']
    assert candidates(trace[0])['b']['marginal_gain'] == 1
    assert candidates(trace[1])['b']['marginal_gain'] == .25
    assert candidates(trace[2])['b']['marginal_gain'] == .25
    assert candidates(trace[3])['d']['marginal_gain'] == .125
    zero, _ = select(chunks, {'x': 1, 'y': .4}, dict.fromkeys('abcd', 1), covered_claim_credit=0)
    assert zero['selection_order'] == ['a', 'c']


def test_duplicate_text_from_different_sources_does_not_accumulate_credit():
    chunks = [chunk('a', ['x'], 'same'), chunk('b', ['x'], 'same'), chunk('c', ['x'], 'other')]
    sources = {k: {'x': (k, 1)} for k in 'abc'}
    result, trace = select(chunks, {'x': 1}, dict.fromkeys('abc', 1), complementary_sources=sources)
    assert result['selection_order'] == ['a', 'c']
    assert candidates(trace[1])['b']['marginal_gain'] == 0
    assert candidates(trace[1])['c']['marginal_gain'] == pytest.approx(.25 * (sqrt(2) - 1))


def test_same_source_suppression_and_dependency_weights():
    chunks = [chunk(k, ['x']) for k in 'abcd']
    sources = {k: {'x': (source, weight)} for k, source, weight in
               [('a', 'one', 1), ('b', 'one', 1), ('c', 'two', .25), ('d', 'three', 0)]}
    result, trace = select(chunks, {'x': .8}, dict.fromkeys('abcd', 1), complementary_sources=sources)
    assert result['selection_order'] == ['a', 'c']
    second = candidates(trace[1])
    assert second['b']['marginal_gain'] == second['d']['marginal_gain'] == 0
    assert second['c']['marginal_gain'] == pytest.approx(.8 * .25 * (sqrt(1.25) - 1))


def test_distinct_conflicting_values_remain_uncovered_claims():
    from omneum import evaluate
    from omneum.context_selection import claim_id
    evaluation = evaluate([{'url': 'https://a.example', 'value': 'yes'},
                           {'url': 'https://b.example', 'value': 'no'}])
    chunks = [chunk(str(i), [claim_id(c.claim)]) for i, c in enumerate(evaluation.claim_support)]
    result = reconstruct_context(evaluation, chunks, token_budget=100,
        strategy='coverage_support_nonlinear', chunk_relevance={'0': 1, '1': 1})
    assert len(result['covered_claim_ids']) == 2
    support = {claim_id(c.claim): c.support for c in evaluation.claim_support}
    assert [s['marginal_gain'] for s in result['selection_scores']] == [
        support[chunks[int(k)]['claim_ids'][0]] for k in result['selection_order']]


def test_chunk_and_claim_relevance_are_separate():
    chunks = [chunk('a', ['x', 'y']), chunk('b', ['z'])]
    result, trace = select(chunks, {'x': 1, 'y': 1, 'z': 1}, {'a': .1, 'b': .7},
                           claim_relevance={'x': 1, 'y': .2, 'z': 1}, token_cost_exponent=0)
    first = candidates(trace[0])
    assert first['a']['marginal_gain'] == 1.2
    assert first['a']['utility'] == pytest.approx(.12)
    assert result['selection_order'] == ['b', 'a']
    assert select(chunks, {'x': 1, 'y': 1, 'z': 1}, {'a': 0, 'b': 0})[0]['context'] == ''


@pytest.mark.parametrize('scores', [None, {}, {'a': None}, {'a': float('nan')}, {'a': -1}, {'a': 2}])
def test_missing_or_invalid_normalized_scores(scores):
    with pytest.raises(ValueError, match='relevance'):
        select([chunk('a', ['x'])], {'x': 1}, scores)


@pytest.mark.parametrize('alpha', [-1, 2, True, float('nan')])
def test_invalid_alpha(alpha):
    with pytest.raises(ValueError, match='credit'):
        select([], {}, {}, covered_claim_credit=alpha)


@pytest.mark.parametrize('budget', [0, 1, 8, 15, 30, 1000])
def test_exact_nonadditive_budget_density_penalty_and_determinism(budget):
    chunks = [chunk(k, [k], k * size) for k, size in [('a', 3), ('b', 15), ('c', 8)]]
    def count(text):
        return len(text.encode()) - (2 if '\n\n' in text else 0)
    options = dict(count_tokens=count, token_penalty=.001)
    result, trace = select(chunks, dict.fromkeys('abc', 1), dict.fromkeys('abc', 1), budget, **options)
    assert result == select(chunks, dict.fromkeys('abc', 1), dict.fromkeys('abc', 1), budget, **options)[0]
    assert count(result['context']) == result['token_usage'] <= budget
    mapping = map_chunks(chunks, 'abc')
    for step in trace:
        for c in step['candidates']:
            cost = max(1, count(reconstruct(mapping, [c['chunk_id']])))
            assert c['utility'] == pytest.approx(c['marginal_gain'] * cost ** -.8 - .001 * c['incremental_tokens'])
    stopped, _ = select(chunks, dict.fromkeys('abc', 1), dict.fromkeys('abc', 1), token_penalty=1)
    assert stopped['selection_order'] == []


def test_score_scale_semantics():
    assert normalize_chunk_relevance({'a': 0, 'b': 0}, 'ab', 'normalized')[1] == {'a': 0, 'b': 0}
    assert normalize_chunk_relevance({'a': -100, 'b': 50}, 'ab', 'reranker_score')[1] == {'a': 0, 'b': 1}
    assert normalize_chunk_relevance({'a': 2, 'b': 1}, 'ab', 'distance')[1] == {'a': 0, 'b': 1}
    # A constant uncalibrated batch indicates no preference, not absolute irrelevance.
    assert normalize_chunk_relevance({'a': 0, 'b': 0}, 'ab', 'similarity')[1] == {'a': 1, 'b': 1}
    with pytest.raises(ValueError, match='score type'):
        normalize_chunk_relevance({'a': 1}, ['a'], None)


def test_sdk_scores_filter_fallback_schema_and_text_blind_wire(monkeypatch):
    observations, chunks, texts = inputs()
    wire = []
    old_call = ClientSession.call_tool
    async def capture(self, name, arguments=None, *args, **kwargs):
        if name == 'evaluate_context':
            wire.append(deepcopy(arguments))
        return await old_call(self, name, arguments, *args, **kwargs)
    def unavailable_model():
        raise AssertionError('upstream scores and BM25 must not load a model')
    monkeypatch.setattr(ClientSession, 'call_tool', capture)
    monkeypatch.setattr('omneum.query_context._embedding_model', unavailable_model)
    async def run():
        with benchmark_deployment() as (config, server):
            async with open_stdio_client(config, server) as client:
                base = dict(estimator=estimator_config(), token_budget=1000, count_tokens=len)
                baseline = await client.prepare_context(observations, chunks, **base)
                options = dict(base, strategy='coverage_support_nonlinear', user_query='PRIVATE QUERY',
                    chunk_relevance={'a': .1, 'd': 0, 'b': .05}, relevance_score_type='normalized')
                diag = {}
                result = await client.prepare_context(observations, chunks, **options, query_diagnostics=diag)
                assert result.keys() == baseline.keys()
                assert result['evaluation'] == baseline['evaluation']
                assert diag['eligible_chunk_ids'] == ['a', 'd', 'b']  # no implicit cutoff
                assert 'a' in result['packed_chunk_ids']
                assert 'd' not in result['packed_chunk_ids']
                filtered = await client.prepare_context(observations, chunks, **options, relevance_threshold=.075)
                assert filtered['packed_chunk_ids'] == ['a']
                await client.prepare_context(observations, chunks, **options, claim_relevance=dict.fromkeys(texts, 1),
                                             complementary_evidence=True)
                for method in ['bm25', 'minilm']:
                    if method == 'minilm':
                        class Encoder:
                            def encode(self, values, **kwargs):
                                return [[1., 0.] for _ in values]
                        model = Encoder()
                    else:
                        model = None
                    local_diag = {}
                    await client.prepare_context(observations, chunks, **base, strategy='coverage_support_nonlinear',
                        user_query='retention', local_relevance=method, semantic_model=model, query_diagnostics=local_diag)
                    assert local_diag['relevance_source'] == method
                zeros = await client.prepare_context(observations, chunks, **base, strategy='coverage_support_nonlinear',
                    user_query='unmatchedword', local_relevance='bm25')
                assert zeros['context'] == ''
                for kwargs in [{}, {'local_relevance': 'bm25'}, {'chunk_relevance': {'a': 1}}]:
                    with pytest.raises(ValueError):
                        await client.prepare_context(observations, chunks, **base,
                            strategy='coverage_support_nonlinear', **kwargs)
                assert all(request == wire[0] for request in wire)
                assert 'PRIVATE' not in json.dumps(wire)
                json.dumps(result, allow_nan=False)
    asyncio.run(run())
