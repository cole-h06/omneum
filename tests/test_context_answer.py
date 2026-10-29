import asyncio
from copy import deepcopy
import json

import pytest

from omneum import LocalPersistenceConfig, OmneumClient, open_stdio_client
from omneum.context_selection import map_chunks, reconstruct, select_chunks
from omneum.mcp import ClientSession
from omneum.storage import SQLiteStorage
from omneum.query_context import source_key
from benchmarks.context_selection.config import estimator_config
from benchmarks.context_selection.deployment import benchmark_deployment
from test_query_context import inputs


def select(chunks, values, budget=1000, count=len):
    support = {claim: .5 for c in chunks for claim in c['claim_ids']}
    return select_chunks(map_chunks(chunks, support), support, budget, 'coverage_answer',
                         count_tokens=count, chunk_claim_utility=values)


def test_query_utility_preserves_raw_text_and_orders_by_selected_density():
    chunks = [{'chunk_id': 'a', 'claim_ids': ['x'], 'raw_text': 'status'},
              {'chunk_id': 'b', 'claim_ids': ['x'], 'raw_text': 'POST refresh\r\n😀'},
              {'chunk_id': 'c', 'claim_ids': ['y'], 'raw_text': 'qualification'}]
    values = {'a': {'x': .01}, 'b': {'x': .8}, 'c': {'y': .7}}
    result = select(chunks, values)
    assert result['selected_chunk_ids'] == ['b', 'c']
    assert result['chunks'][0]['raw_text'] == chunks[1]['raw_text']
    assert result['context'] == '[b]\nPOST refresh\r\n😀\n\n[c]\nqualification'
    assert [c['score'] for c in result['chunks']] == sorted([c['score'] for c in result['chunks']], reverse=True)


def test_marginal_gain_only_credits_improvement_and_new_claims():
    chunks = [{'chunk_id': 'a', 'claim_ids': ['x'], 'raw_text': 'a'},
              {'chunk_id': 'b', 'claim_ids': ['x', 'y'], 'raw_text': 'b' * 15},
              {'chunk_id': 'copy', 'claim_ids': ['x'], 'raw_text': 'a'}]
    result = select(chunks, {'a': {'x': .5}, 'b': {'x': .8, 'y': .2}, 'copy': {'x': .5}})
    assert result['selection_order'] == ['a', 'b']
    assert result['selection_scores'][1]['marginal_gain'] == pytest.approx(.5)
    assert 'copy' not in result['selected_chunk_ids']


def test_competing_claim_values_and_multiple_claims_are_complementary():
    chunks = [{'chunk_id': 'wrong', 'claim_ids': ['240'], 'raw_text': 'estimate'},
              {'chunk_id': 'right', 'claim_ids': ['216', 'vacant'], 'raw_text': 'enumeration'}]
    result = select(chunks, {'wrong': {'240': .3}, 'right': {'216': .5, 'vacant': .2}})
    assert set(result['selected_chunk_ids']) == {'wrong', 'right'}
    assert set(result['covered_claim_ids']) == {'240', '216', 'vacant'}


@pytest.mark.parametrize('budget', [0, 1, 15, 30, 100])
def test_exact_budget_ties_and_nonadditive_tokens(budget):
    chunks = [{'chunk_id': k, 'claim_ids': [k], 'raw_text': k * 7} for k in ('a', 'b', 'c')]
    def count(text):
        return len(text.encode()) - (3 if '\n\n' in text else 0)
    result = select(chunks, {k: {k: .5} for k in ('a', 'b', 'c')}, budget, count)
    assert count(result['context']) == result['token_usage'] <= budget
    assert result == select(chunks, {k: {k: .5} for k in ('a', 'b', 'c')}, budget, count)
    if budget == 100:
        assert result['selection_order'] == ['a', 'b', 'c']


def test_zero_gain_does_not_hide_positive_feasible_candidates():
    chunks = [{'chunk_id': k, 'claim_ids': [k], 'raw_text': 'text'} for k in ('a', 'b')]
    assert select(chunks, {'a': {'a': 0}, 'b': {'b': .2}})['selected_chunk_ids'] == ['b']


@pytest.mark.parametrize('bad', [-1, 2, True, float('nan'), float('inf')])
def test_invalid_utilities_are_rejected(bad):
    chunks = [{'chunk_id': 'a', 'claim_ids': ['x'], 'raw_text': 'text'}]
    with pytest.raises(ValueError):
        select(chunks, {'a': {'x': bad}})


def test_missing_utility_is_not_invented():
    with pytest.raises(ValueError):
        select([{'chunk_id': 'a', 'claim_ids': ['x'], 'raw_text': 'text'}], {})


def test_default_coverage_does_not_use_answer_utility():
    chunks = [{'chunk_id': 'a', 'claim_ids': ['x'], 'raw_text': 'text'}]
    mapping = map_chunks(chunks, {'x': .5})
    original = deepcopy(mapping)
    result = select_chunks(mapping, {'x': .5}, 100, 'coverage_support', count_tokens=len)
    assert result['candidate_scores'] == {'a': .5}
    assert result['chunks'][0]['score'] == .5
    assert mapping == original
    with pytest.raises(ValueError):
        select_chunks(mapping, {'x': .5}, 100, 'coverage_support', chunk_claim_utility={'a': {'x': .1}})


def test_real_sdk_final_scores_wire_persistence_and_no_local_model(tmp_path, monkeypatch):
    observations, chunks, _ = inputs()
    original = deepcopy(chunks)
    wire, evaluations = [], []
    old_call, old_eval = ClientSession.call_tool, OmneumClient._evaluate_context
    async def capture(self, name, arguments=None, *args, **kwargs):
        if name == 'evaluate_context':
            wire.append(deepcopy(arguments))
        return await old_call(self, name, arguments, *args, **kwargs)
    async def evaluate(self, *args, **kwargs):
        value = await old_eval(self, *args, **kwargs)
        evaluations.append(value)
        return value
    def no_model():
        raise AssertionError('caller scores must not initialize a semantic model')
    monkeypatch.setattr(ClientSession, 'call_tool', capture)
    monkeypatch.setattr(OmneumClient, '_evaluate_context', evaluate)
    monkeypatch.setattr('omneum.query_context._embedding_model', no_model)
    async def run():
        storage = SQLiteStorage(tmp_path / 'omneum.db')
        with benchmark_deployment() as (config, server):
            async with open_stdio_client(config, server,
                local_persistence=LocalPersistenceConfig(storage)) as client:
                baseline = await client.prepare_context(observations, chunks, estimator=estimator_config(),
                    token_budget=1000, count_tokens=len)
                diag = {}
                result = await client.prepare_context(observations, chunks, estimator=estimator_config(),
                    token_budget=1000, count_tokens=len, strategy='coverage_answer',
                    user_query='PRIVATE QUERY', chunk_relevance={'a': 3, 'd': 2, 'b': 1},
                    relevance_score_type='similarity', candidate_discovery='all', query_diagnostics=diag)
                assert result['evaluation'] == baseline['evaluation']
                assert len(evaluations) == 2
                r = evaluations[-1].source_reliability
                reliability = {source_key(item.source): item.reliability for item in r}
                support = {item.claim.attribute: item.support for item in evaluations[-1].claim_support}
                # The first candidate credits final R and s without independence factors.
                expected = sum((1 + reliability[source_key(chunks[0]['source'])] + support[item.claim.attribute]) / 3
                               for item in evaluations[-1].claim_support if item.claim.attribute in ('retention', 'exception'))
                assert diag['candidate_scores']['a'] == pytest.approx(expected / len(reconstruct(
                    map_chunks(chunks, {c for chunk in chunks for c in chunk['claim_ids']}), ['a'])))
                assert result['selection']['selected_tokens'] == len(result['context']) <= 1000
                assert [c['chunk_id'] for c in result['chunks']] == result['packed_chunk_ids']
                assert 'telemetry' not in result
                json.dumps(result, allow_nan=False)
                with pytest.raises(ValueError, match='requires caller'):
                    await client.prepare_context(observations, chunks, estimator=estimator_config(),
                        token_budget=1000, strategy='coverage_answer')
        import sqlite3
        with sqlite3.connect(storage.path) as db:
            assert db.execute('select count(*) from evaluation_runs').fetchone()[0] == 2
            assert db.execute('select count(*) from execution_history').fetchone()[0] == 2
    asyncio.run(run())
    assert chunks == original
    assert len(wire) == 2
    assert 'PRIVATE' not in json.dumps(wire)


def test_native_ranking_can_override_relevance_order_using_final_reliability():
    from dataclasses import replace
    from omneum import evaluate, reconstruct_context
    from omneum.context_selection import claim_id
    evaluation = evaluate([{'url': 'https://a.example', 'value': 'yes'},
                           {'url': 'https://b.example', 'value': 'no'}])
    reliable = evaluation.claim_support[0].supporting_sources[0].source
    evaluation = replace(evaluation, source_reliability=tuple(
        replace(item, reliability=.9 if item.source == reliable else .1)
        for item in evaluation.source_reliability))
    chunks, relevance = [], {}
    for index, claim in enumerate(evaluation.claim_support):
        chunks.append({'chunk_id': str(index), 'claim_ids': [claim_id(claim.claim)],
                       'raw_text': 'same text', 'source': claim.supporting_sources[0].source})
        relevance[str(index)] = .9 if index == 0 else 1.0
    result = reconstruct_context(evaluation, chunks, token_budget=100,
        strategy='coverage_answer', chunk_relevance=relevance)
    assert result['selected_chunk_ids'][0] == '0'
    assert relevance['0'] < relevance['1']
    assert result['chunks'][0]['score'] > result['chunks'][1]['score']


def test_budgeted_set_keeps_complementary_claim_instead_of_static_runner_up():
    chunks = [{'chunk_id': k, 'claim_ids': [claim], 'raw_text': 'same'}
              for k, claim in [('a', 'rule'), ('b', 'rule'), ('c', 'exception')]]
    values = {'a': {'rule': .9}, 'b': {'rule': .8}, 'c': {'exception': .6}}
    mapping = map_chunks(chunks, ['rule', 'exception'])
    budget = len(reconstruct(mapping, ['a', 'c']))
    result = select(chunks, values, budget)
    assert result['selected_chunk_ids'] == ['a', 'c']
    # Static individual scores would prefer a,b; marginal coverage prefers a,c.
    assert sum(s['marginal_gain'] for s in result['selection_scores']) == pytest.approx(1.5)
    assert len(result['context']) == budget
