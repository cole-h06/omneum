import asyncio
from copy import deepcopy
import json
from math import log
import subprocess
import sys

import pytest

from omneum import LocalPersistenceConfig, OmneumClient, open_stdio_client
from omneum.context_selection import map_chunks
from omneum.mcp import ClientSession
from omneum.query_context import bm25_scores, discover_chunks, normalize_chunk_relevance
from omneum.storage import SQLiteStorage
from benchmarks.context_selection.config import estimator_config
from benchmarks.context_selection.deployment import benchmark_deployment
from test_query_context import inputs


def test_sdk_and_bm25_do_not_require_semantic_packages():
    script = '''
import builtins
original = builtins.__import__
def blocked(name, *args, **kwargs):
    if name.split('.')[0] in {'sentence_transformers', 'torch', 'numpy'}:
        raise AssertionError('unexpected semantic dependency')
    return original(name, *args, **kwargs)
builtins.__import__ = blocked
from omneum import OmneumClient
from omneum.query_context import bm25_scores, normalize_chunk_relevance
scores = bm25_scores('retention', {'a': 'retention policy', 'b': 'other record'})
assert scores['a'] > scores['b'] == 0
assert normalize_chunk_relevance(scores, ['a', 'b'], 'similarity')[1] == {'a': 1, 'b': 0}
'''
    completed = subprocess.run([sys.executable, '-c', script], capture_output=True, text=True)
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout == completed.stderr == ''


@pytest.mark.parametrize('score_type,scores,expected', [
    ('similarity', {'a': -3, 'b': 2, 'c': 0}, {'a': 0, 'b': 1, 'c': 0.5}),
    ('similarity', {'a': -0.2, 'b': 0.8, 'c': 0.1}, {'a': 0, 'b': 1, 'c': 0.5}),
    ('distance', {'a': 0.1, 'b': 4, 'c': 2}, {'a': 1, 'b': 0, 'c': 0.5}),
    ('rank', {'a': 1, 'b': 3, 'c': 2}, {'a': 1, 'b': 0, 'c': 0.5}),
    ('reranker_score', {'a': -20, 'b': -1, 'c': -5}, {'a': 0, 'b': 1, 'c': 0.5}),
    ('similarity', {'a': -1e308, 'b': 1e308, 'c': 0}, {'a': 0, 'b': 1, 'c': 0.5}),
])
def test_relevance_order_and_raw_values(score_type, scores, expected):
    raw, normalized = normalize_chunk_relevance(scores, ['a', 'b', 'c'], score_type)
    assert raw == scores
    assert normalized == expected
    assert scores == raw


@pytest.mark.parametrize('score_type,scores', [
    ('unknown', {'a': 1}), ('similarity', {}), ('similarity', {'other': 1}),
    ('similarity', {'a': float('nan')}), ('distance', {'a': float('inf')}),
    ('reranker_score', {'a': '2'}), ('similarity', {'a': True}),
    ('rank', {'a': -1}), ('rank', {'a': 1.5}),
])
def test_invalid_or_missing_scores(score_type, scores):
    with pytest.raises(ValueError):
        normalize_chunk_relevance(scores, ['a'], score_type)


def test_bm25_uses_real_corpus_statistics():
    scores = bm25_scores('ALPHA', {'a': 'alpha', 'b': 'beta'})
    assert scores == {'a': pytest.approx(log(2)), 'b': 0}
    assert bm25_scores('alpha', {'a': '', 'b': '   '}) == {'a': 0, 'b': 0}
    assert bm25_scores('alpha', {}) == {}
    assert bm25_scores('', {'a': 'alpha'}) == {'a': 0}
    assert bm25_scores('alpha alpha', {'a': 'alpha'})['a'] == pytest.approx(2 * bm25_scores('alpha', {'a': 'alpha'})['a'])


def test_ties_constant_scores_and_configurable_policies():
    observations, chunks, _ = inputs()
    mapping = map_chunks(chunks, {c for chunk in chunks for c in chunk['claim_ids']})
    scores = {'a': 2, 'd': 1, 'b': 1}
    all_chunks = discover_chunks(observations, mapping, scores, 'similarity', 'all', 1, 2)
    assert all_chunks['eligible_chunk_ids'] == ['a', 'd', 'b']
    top = discover_chunks(observations, mapping, scores, 'similarity', 'top_k', 2, 2)
    assert top['eligible_chunk_ids'] == ['a', 'd', 'b']
    constant = discover_chunks(observations, mapping, dict.fromkeys(scores, -1), 'reranker_score', 'expanded', 1, 2)
    assert constant['eligible_chunk_ids'] == ['a', 'd', 'b']
    assert set(constant['normalized_relevance_scores'].values()) == {1}
    assert discover_chunks(observations, mapping, None, None, 'expanded', 1, 2)['eligible_chunk_ids'] == ['a', 'd', 'b']
    assert normalize_chunk_relevance({}, [], 'similarity') == ({}, {})
    for policy, count, depth in [('unknown', 1, 1), ('all', 0, 1), ('top_k', True, 1), ('expanded', 1, 3)]:
        with pytest.raises(ValueError):
            discover_chunks(observations, mapping, scores, 'similarity', policy, count, depth)


def test_chunk_anchors_preserve_shared_claims_and_connected_exceptions():
    observations, chunks, _ = inputs()
    anchor, exception = chunks[0]['claim_ids']
    chunks[0] = {**chunks[0], 'raw_text': 'Retention 30 days.', 'claim_ids': [anchor]}
    chunks.append({'chunk_id': 'exception', 'raw_text': 'Legal hold overrides expiration.',
                   'claim_ids': [exception], 'source': observations[1].source})
    mapping = map_chunks(chunks, {c for chunk in chunks for c in chunk['claim_ids']})
    scores = {'a': 10, 'd': -1, 'b': -2, 'exception': -3}
    one = discover_chunks(observations, mapping, scores, 'reranker_score', 'expanded', 1, 1)
    two = discover_chunks(observations, mapping, scores, 'reranker_score', 'expanded', 1, 2)
    assert one['eligible_chunk_ids'] == ['a', 'd']
    assert two['eligible_chunk_ids'] == ['a', 'd', 'exception']
    assert two['anchor_chunk_ids'] == ['a']
    assert two['anchor_claim_ids'] == [anchor]
    assert exception in two['expanded_claim_ids']
    assert two == {**discover_chunks(observations, mapping, scores, 'reranker_score', 'expanded', 1, 2),
                   'expansion_latency_ms': two['expansion_latency_ms']}


def test_sdk_precedence_local_options_structural_fallback_and_wire(tmp_path, monkeypatch, capsys):
    observations, chunks, _ = inputs()
    original = deepcopy(chunks)
    calls, evaluations, encodings = [], [], []
    old_call = ClientSession.call_tool
    old_evaluate = OmneumClient._evaluate_context
    async def capture(self, name, arguments=None, *args, **kwargs):
        if name == 'evaluate_context':
            calls.append(deepcopy(arguments))
        return await old_call(self, name, arguments, *args, **kwargs)
    async def evaluate(self, *args, **kwargs):
        value = await old_evaluate(self, *args, **kwargs)
        evaluations.append(value)
        return value
    def unexpected():
        raise AssertionError('local model must not be initialized')
    class Encoder:
        def encode(self, texts, **kwargs):
            encodings.append(texts)
            return [[1, 0] for text in texts]
    monkeypatch.setattr(ClientSession, 'call_tool', capture)
    monkeypatch.setattr(OmneumClient, '_evaluate_context', evaluate)
    monkeypatch.setattr('omneum.query_context._embedding_model', unexpected)
    async def run():
        storage = SQLiteStorage(tmp_path / 'omneum.db')
        with benchmark_deployment() as (config, server):
            async with open_stdio_client(config, server, local_persistence=LocalPersistenceConfig(storage)) as client:
                options = dict(estimator=estimator_config(), token_budget=2000,
                               count_tokens=lambda text: len(text.encode()), strategy='coverage_support_density',
                               token_cost_exponent=1, complementary_evidence=True)
                baseline = await client.prepare_context(observations, chunks, **options)
                for local in (None, 'bm25', 'minilm'):
                    diag = {}
                    result = await client.prepare_context(
                        observations, chunks, **options, chunk_relevance={'a': 3, 'd': -1, 'b': -2},
                        relevance_score_type='reranker_score', candidate_discovery='expanded', candidate_count=1,
                        local_relevance=local, user_query='PRIVATE retention', query_diagnostics=diag,
                    )
                    assert diag['relevance_source'] == 'caller'
                    assert diag['raw_relevance_scores'] == {'a': 3, 'd': -1, 'b': -2}
                    assert diag['initial_eligible_chunk_ids'] == ['a', 'd']
                    assert diag['eligible_chunk_ids'] == ['a', 'd', 'b']
                    assert diag['recovered_chunk_ids'] == []  # Explicit zero rank weight stays zero.
                    assert result['evaluation'] == baseline['evaluation']
                    assert 'Legal hold exception' in result['context']
                    assert result['selection']['input_tokens'] == baseline['selection']['input_tokens']
                    assert result['selection']['selected_tokens'] == len(result['context'].encode()) <= 2000
                    assert diag['reconstructed_context_tokens'] == result['selection']['selected_tokens']
                    assert diag['selection_scores'] and diag['selected_chunk_ids'] == result['packed_chunk_ids']
                    assert 'telemetry' not in result
                    json.dumps(result, allow_nan=False)
                assert not encodings
                for local in (None, 'bm25', 'minilm'):
                    diag = {}
                    result = await client.prepare_context(
                        observations, chunks, **options, candidate_discovery='all', local_relevance=local,
                        user_query='PRIVATE retention', semantic_model=Encoder(), query_diagnostics=diag,
                    )
                    assert result['evaluation'] == baseline['evaluation']
                    if local == 'bm25':
                        assert 'b' not in result['packed_chunk_ids']
                    else:
                        assert result == baseline
                    assert diag['relevance_source'] == (local or 'structural')
                    if local:
                        assert set(diag['raw_relevance_scores']) == {'a', 'b', 'd'}
                    else:
                        assert diag['raw_relevance_scores'] == {}
                assert len(encodings) == 1
                for budget in (0, 1, 40, 90):
                    result = await client.prepare_context(
                        observations, chunks, **{**options, 'token_budget': budget},
                        chunk_relevance={'a': 0.1, 'd': 0.1, 'b': 0.1}, relevance_score_type='distance',
                    )
                    assert len(result['context'].encode()) == result['selection']['selected_tokens'] <= budget
                for local in ('bm25', 'minilm'):
                    diag = {}
                    result = await client.prepare_context(observations, chunks, **options,
                        candidate_discovery='expanded', local_relevance=local, user_query='', query_diagnostics=diag)
                    assert result == baseline and diag['fallback_reason'] == 'empty_query'
                def unavailable():
                    raise ImportError('optional model dependency unavailable')
                monkeypatch.setattr('omneum.query_context._embedding_model', unavailable)
                diag = {}
                result = await client.prepare_context(observations, chunks, **options,
                    local_relevance='minilm', user_query='retention', query_diagnostics=diag)
                assert result == baseline
                assert diag['relevance_source'] == 'structural'
                assert diag['fallback_reason'] == 'local_relevance_unavailable'
                assert diag['raw_relevance_scores'] == {}
                for invalid in (
                    {'chunk_relevance': {'a': 1}, 'relevance_score_type': 'similarity'},
                    {'chunk_relevance': {'a': 1, 'd': 2, 'b': 3}},
                    {'relevance_score_type': 'similarity'},
                    {'local_relevance': 'unknown'},
                    {'candidate_discovery': 'unknown'},
                ):
                    with pytest.raises(ValueError):
                        await client.prepare_context(observations, chunks, **options, **invalid)
        import sqlite3
        with sqlite3.connect(storage.path) as db:
            assert db.execute('SELECT count(*) FROM evaluation_runs').fetchone()[0] == 14
            assert db.execute('SELECT count(*) FROM execution_history').fetchone()[0] == 14
        for result in evaluations[1:]:
            assert result.claim_support == evaluations[0].claim_support
            assert result.source_reliability == evaluations[0].source_reliability
            assert result.pairwise_dependencies == evaluations[0].pairwise_dependencies
    asyncio.run(run())
    assert chunks == original
    assert len(calls) == 14 and all(call == calls[0] for call in calls)
    assert 'PRIVATE' not in json.dumps(calls)
    assert capsys.readouterr() == ('', '')
