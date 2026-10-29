import asyncio
from copy import deepcopy
import json
from math import sqrt

import pytest

from omneum import LocalPersistenceConfig, OmneumClient, open_stdio_client
from omneum.context_selection import map_chunks, reconstruct, select_chunks
from omneum.mcp import ClientSession
from omneum.storage import SQLiteStorage
from benchmarks.context_selection.config import estimator_config
from benchmarks.context_selection.deployment import benchmark_deployment
from test_query_context import inputs


def selection(relevance=None, budget=1000, gamma=1):
    chunks = [{'chunk_id': k, 'claim_ids': [claim], 'raw_text': 'original\r\n' + k}
              for k, claim in [('a', 'x'), ('b', 'x'), ('c', 'y'), ('d', 'x')]]
    mapping = map_chunks(chunks, ['x', 'y'])
    sources = {'a': {'x': ('one', 1)}, 'b': {'x': ('two', 1)},
               'c': {'y': ('three', 1)}, 'd': {'x': ('one', 1)}}
    trace = []
    result = select_chunks(mapping, {'x': .8, 'y': .4}, budget,
        'coverage_support_density', count_tokens=len, token_cost_exponent=gamma,
        complementary_sources=sources, chunk_relevance=relevance, selection_trace=trace)
    return result, trace, mapping


@pytest.mark.parametrize('gamma', [0, 1, 2])
def test_equation_recalculation_and_same_source_duplicates(gamma):
    relevance = {'a': 1, 'b': 1, 'c': 1, 'd': 1}
    result, trace, mapping = selection(relevance, gamma=gamma)
    baseline, _, _ = selection(gamma=gamma)
    assert result == baseline
    assert result['selection_order'] == ['a', 'c', 'b']
    second = {c['chunk_id']: c for c in trace[1]['candidates']}
    assert second['b']['marginal_gain'] == pytest.approx(.8 * (sqrt(2) - 1))
    assert second['d']['marginal_gain'] == 0
    for step in trace:
        for candidate in step['candidates']:
            identifier = candidate['chunk_id']
            cost = len(reconstruct(mapping, [identifier]))
            assert candidate['utility'] == pytest.approx(
                candidate['marginal_gain'] * relevance[identifier] / cost ** gamma)
    assert result['context'] == reconstruct(mapping, result['selected_chunk_ids'])


def test_relevance_changes_selection_without_changing_raw_gain_or_rendering():
    result, trace, _ = selection({'a': 0, 'b': .1, 'c': 1, 'd': 0})
    assert result['selection_order'] == ['c', 'b']
    assert result['selected_chunk_ids'] == ['b', 'c']
    initial = {c['chunk_id']: c for c in trace[0]['candidates']}
    assert initial['a']['marginal_gain'] == .8
    assert initial['a']['utility'] == 0
    assert result['chunks'][0]['raw_text'] == 'original\r\nb'


@pytest.mark.parametrize('budget', [0, 1, 20, 38, 100])
def test_exact_budget_and_deterministic_stopping(budget):
    relevance = {'a': 0, 'b': 1, 'c': 1, 'd': 0}
    result, _, _ = selection(relevance, budget)
    assert len(result['context']) == result['token_usage'] <= budget
    assert result == selection(relevance, budget)[0]
    assert not {'a', 'd'} & set(result['selected_chunk_ids'])


@pytest.mark.parametrize('value', [-1, 2, True, float('nan'), float('inf')])
def test_invalid_relevance(value):
    with pytest.raises(ValueError):
        selection({'a': value, 'b': 1, 'c': 1, 'd': 1})


def test_missing_relevance_is_rejected():
    with pytest.raises(ValueError, match='every candidate'):
        selection({'a': 1})


def test_real_sdk_scores_wire_json_and_persistence(tmp_path, monkeypatch):
    observations, chunks, _ = inputs()
    wire = []
    original = ClientSession.call_tool
    async def capture(self, name, arguments=None, *args, **kwargs):
        if name == 'evaluate_context':
            wire.append(deepcopy(arguments))
        return await original(self, name, arguments, *args, **kwargs)
    def no_model():
        raise AssertionError('caller relevance must not initialize a local model')
    monkeypatch.setattr(ClientSession, 'call_tool', capture)
    monkeypatch.setattr('omneum.query_context._embedding_model', no_model)
    async def run():
        storage = SQLiteStorage(tmp_path / 'omneum.db')
        with benchmark_deployment() as (config, server):
            async with open_stdio_client(config, server, local_persistence=LocalPersistenceConfig(storage)) as client:
                options = dict(estimator=estimator_config(), token_budget=1000, count_tokens=len,
                    strategy='coverage_support_density', complementary_evidence=True, token_cost_exponent=1,
                    user_query='PRIVATE QUERY', chunk_relevance={'a': 3, 'd': 2, 'b': 1},
                    relevance_score_type='similarity', candidate_discovery='all')
                baseline = await client.prepare_context(observations, chunks, **options)
                diag = {}
                result = await client.prepare_context(observations, chunks, **options,
                    query_conditioned_utility=True, query_diagnostics=diag)
                assert result['evaluation'] == baseline['evaluation']
                assert len(wire) == 2 and wire[0] == wire[1]
                assert 'PRIVATE' not in json.dumps(wire)
                json.dumps(result, allow_nan=False)
                assert 'telemetry' not in result
                assert result['selection']['selected_tokens'] == len(result['context']) <= 1000
                assert result['packed_chunk_ids'] == [c['chunk_id'] for c in result['chunks']]
                by_id = {c['chunk_id']: c for c in chunks}
                assert all(c['raw_text'] == by_id[c['chunk_id']]['raw_text'] for c in result['chunks'])
                assert diag['utility_trace']
                with pytest.raises(ValueError, match='requires complementary'):
                    await client.prepare_context(observations, chunks, estimator=estimator_config(), token_budget=100,
                        query_conditioned_utility=True)
        import sqlite3
        with sqlite3.connect(storage.path) as db:
            assert db.execute('select count(*) from execution_history').fetchone()[0] == 2
    asyncio.run(run())
