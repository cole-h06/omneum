import json
from types import SimpleNamespace

import pytest

from . import release_benchmark as release
from . import prepare_benchmark as base


def test_primary_omneum_arm_uses_production_question_aware_default():
    assert release.prepare_options('omneum', 'question', [], {}) == {'question': 'question'}


def test_recheck_and_primary_share_the_same_hybrid_options():
    common = {'strategy': 'coverage_support_density', 'complementary_evidence': True,
              'token_cost_exponent': 1}
    for method in ('bm25_omneum', 'embedding_omneum', 'bge_omneum'):
        diagnostics = {}
        settings = release.prepare_options(method, 'question', [{'chunk_id': 'a', 'relevance': -2}], diagnostics)
        assert settings == {**common, 'user_query': 'question', 'chunk_relevance': {'a': -2},
            'relevance_score_type': 'reranker_score' if method == 'bge_omneum' else 'similarity',
            'candidate_discovery': 'expanded', 'candidate_count': 3, 'expansion_depth': 2,
            'query_diagnostics': diagnostics}


def test_judge_ranking_preserves_identifiers_and_rejects_missing_or_duplicate_ids():
    chunks = [{'chunk_id': 'a'}, {'chunk_id': 'b'}]
    assert release.validate_ranking('{"selected_ids":["b","a"]}', chunks) == ['b', 'a']
    for identifiers in (['a'], ['a', 'a'], ['a', 'unknown'], [1, 'b']):
        with pytest.raises(ValueError):
            release.validate_ranking(json.dumps({'selected_ids': identifiers}), chunks)


@pytest.mark.parametrize('method', ['claude', 'gpt', 'gemini'])
def test_judges_use_identical_schema_and_full_pool_without_gold(monkeypatch, method):
    import asyncio

    calls = []
    async def generate(prompt, model, maximum, **kwargs):
        calls.append((prompt, model, maximum, kwargs))
        return {'text': '{"selected_ids":["b","a"]}', 'latency_seconds': 1,
                'response_diagnostics': {'usage_metadata': {}}, 'input_tokens': 10, 'output_tokens': 5}
    function = {'claude': '_generate_anthropic', 'gpt': '_generate_openai',
                'gemini': '_generate_google'}[method]
    monkeypatch.setattr(release, function, generate)
    chunks = [{'chunk_id': 'a', 'raw_text': 'original A'}, {'chunk_id': 'b', 'raw_text': 'original B'}]
    result = asyncio.run(release.judge(SimpleNamespace(question='question', case_id='fixture'), chunks, method))
    assert result['ranking'] == ['b', 'a']
    assert base.render(chunks) in calls[0][0]
    assert calls[0][1] == release.MODELS[method]
    assert calls[0][2] == (8192 if method == 'gemini' else 2048)
    assert calls[0][3]['response_schema']['required'] == ['selected_ids']
    effort_field = {'claude': 'effort', 'gpt': 'reasoning_effort', 'gemini': 'thinking_level'}[method]
    assert calls[0][3][effort_field] == 'low'
    assert calls[0][3][{'claude': 'max_retries', 'gpt': 'max_retries',
                         'gemini': 'retry_attempts'}[method]] in (0, 1)
    assert calls[0][3]['timeout'] == 120
    assert result['raw_output'] == '{"selected_ids":["b","a"]}'


def test_common_packing_counts_complete_rendering_and_skips_oversized_chunks():
    chunks = [{'chunk_id': 'a', 'raw_text': 'unchanged text'}, {'chunk_id': 'b', 'raw_text': 'B'}]
    budget = len(base.render(chunks[1:]))
    assert base.pack(chunks, budget, len) == chunks[1:]
    assert len(base.render(base.pack(chunks, budget, len))) <= budget


def test_summary_retains_failures_in_accuracy_denominator_and_budget_pairs():
    rows = []
    for method, score in [('bge', 'correct'), ('omneum', 'unscored')]:
        rows.append(dict(case_id='a', trial=1, allocated_budget=64, arm=method,
                         answer_score=score, selection_score={'precision': 1, 'recall': 1}))
    rows.append(dict(case_id='b', trial=1, allocated_budget=64, arm='omneum', answer_score='selection_failure'))
    summary = release.summarize(rows)
    assert summary['omneum']['accuracy'] == 0
    assert summary['omneum']['failures'] == 1
    assert summary['omneum']['vs_bge'] == {'wins': 0, 'losses': 1, 'ties': 0}


def test_cohere_search_unit_preflight_is_conservative():
    assert release.cohere_search_units('q', [{'raw_text': 'short'}]) == 1
    with pytest.raises(release.UnpricedProviderError, match='100 documents'):
        release.cohere_search_units('q', [{'raw_text': 'x'}] * 101)
    with pytest.raises(release.UnpricedProviderError, match='500-token'):
        release.cohere_search_units('q', [{'raw_text': 'x' * 500}])


def test_full_cohere_request_inventory_is_checked_before_dispatch():
    cases = base.discover_cases(base.CASES_DIR)
    inventory = release.preflight_cohere(cases)
    assert len(inventory) == 24
    assert sum(row['search_units'] for row in inventory) == 24
    assert sum(row['documents'] for row in inventory) == 189
    assert max(row['documents'] for row in inventory) == 10


def test_full_paid_run_stops_before_output_or_provider_dispatch(monkeypatch, tmp_path):
    import asyncio

    ledger = tmp_path / 'ledger.sqlite3'
    monkeypatch.setattr(release, 'SPENDING_LEDGER', ledger)
    args = SimpleNamespace(output=tmp_path / 'must-not-exist')
    monkeypatch.setattr(release, 'COHERE_USD_PER_SEARCH', None)
    with pytest.raises(release.UnpricedProviderError, match='Cohere direct API'):
        asyncio.run(release.run(args))
    assert not args.output.exists()
    assert not ledger.exists()


def test_evaluation_inventory_and_provider_configuration_are_frozen():
    from .selection_frontier import BUDGETS

    cases = base.discover_cases(base.CASES_DIR)
    assert len(cases) == 24
    assert tuple(BUDGETS) == (64, 96, 128, 160, 192, 256)
    assert release.MODELS == {'claude': 'claude-sonnet-5-5', 'gpt': 'gpt-6-astra',
                              'gemini': 'gemini-3.8-flash'}
    assert len(release.METHODS) == 11
    assert release.METHODS[:8] == ('bm25', 'embedding', 'bge', 'cohere', 'claude',
                                   'gpt', 'gemini', 'omneum')
    assert release.COHERE_USD_PER_SEARCH == 0.0025
    assert 'provisional' in release.COHERE_PRICING_BASIS
