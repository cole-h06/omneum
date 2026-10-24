import argparse
import asyncio
from dataclasses import asdict
from functools import lru_cache
import json
from pathlib import Path
from statistics import mean, median
import time

from omneum import LocalPersistenceConfig, open_stdio_client
from omneum.storage import SQLiteStorage
from benchmarks.context_evaluation.clients import _generate_anthropic, _generate_google, _generate_openai
from benchmarks.context_evaluation.semantic_reranker import rerank_cohere
from .spending import SpendingLedger, conservative_token_cost, request_fingerprint, UnpricedProviderError
from . import prepare_benchmark as base
from . import query_benchmark as query
from .artifacts import checkpoint, write_json
from .checkpoint import implementation_hash
from .scoring import score_answer
from .selection_frontier import BUDGETS, cache_key, read_rows


NATIVE = base.RESULTS_DIR / 'retriever-native-v1'
MODELS = {'claude': 'claude-sonnet-5-5', 'gpt': 'gpt-6-astra', 'gemini': 'gemini-3.8-flash'}
METHODS = ('bm25', 'embedding', 'bge', 'cohere', 'claude', 'gpt', 'gemini',
           'omneum', 'bm25_omneum', 'embedding_omneum', 'bge_omneum')
SPENDING_LEDGER = Path(__file__).parent / 'results' / '.release-spending.sqlite3'
COHERE_USD_PER_SEARCH = None  # Set only from applicable first-party billing terms.


def cohere_search_units(question, chunks):
    # Cohere defines one unit as a query with <=100 documents. The documented
    # 500-token auto-chunk boundary is proven not to apply only when each
    # query/document byte bound is <=500; otherwise fail closed.
    if len(chunks) > 100:
        raise UnpricedProviderError('Cohere request has over 100 documents; unit count is unresolved')
    if any(len((question + '\n' + c['raw_text']).encode('utf-8')) > 500 for c in chunks):
        raise UnpricedProviderError('Cohere document may exceed its 500-token chunk boundary')
    return 1
GENERATION_FIELDS = ('answer', 'generator_input_tokens', 'generator_output_tokens',
                     'generation_seconds', 'generator_prompt', 'generator_options', 'generator_metadata')


def prepare_options(method, question, ranked, diagnostics):
    if method == 'omneum':
        # Exercise the promoted production path: nonempty questions select via
        # finalized claim support weighted by local claim relevance.
        return {'question': question}
    settings = dict(strategy='coverage_support_density', complementary_evidence=True, token_cost_exponent=1)
    settings.update(user_query=question, chunk_relevance={c['chunk_id']: c['relevance'] for c in ranked},
        relevance_score_type='reranker_score' if method == 'bge_omneum' else 'similarity',
        candidate_discovery='expanded', candidate_count=3, expansion_depth=2,
        query_diagnostics=diagnostics)
    return settings


def validate_ranking(text, chunks):
    identifiers = json.loads(text)['selected_ids']
    expected = [c['chunk_id'] for c in chunks]
    if not isinstance(identifiers, list) or len(identifiers) != len(expected):
        raise ValueError('selector must rank the complete candidate pool')
    if any(type(value) is not str for value in identifiers) or set(identifiers) != set(expected):
        raise ValueError('selector returned duplicated or unknown chunk IDs')
    return identifiers


async def judge(case, chunks, method, *, ledger=None, trial=1):
    # Rank the complete pool once per trial. All rankers then use the same
    # exact-token first-fit packer; the judge does not generate passage text.
    prompt = ('Rank ALL passages for answering the question, best first. Consider conflicting, '
              'outdated and complementary evidence. Return only JSON {"selected_ids":[...]} '
              'containing every chunk ID exactly once. Do not answer the question.\n\nQuestion:\n' +
              case.question + '\n\nPassages:\n' + base.render(chunks))
    schema = {'type': 'object', 'properties': {'selected_ids': {
        'type': 'array', 'items': {'type': 'string'}}}, 'required': ['selected_ids'],
        'additionalProperties': False}
    max_output = 8192 if method == 'gemini' else 2048
    request = {'prompt': prompt, 'max_output_tokens': max_output, 'schema': schema,
               'effort': 'low'}
    identity = {'case_id': case.case_id, 'trial': trial}
    fingerprint = request_fingerprint(method, MODELS[method], request, identity)

    async def call():
        if method == 'claude':
            return await _generate_anthropic(prompt, MODELS[method], max_output,
                response_schema=schema, effort='low', max_retries=0, timeout=120)
        if method == 'gpt':
            return await _generate_openai(prompt, MODELS[method], max_output,
                response_schema=schema, reasoning_effort='low', max_retries=0, timeout=120)
        return await _generate_google(prompt, MODELS[method], max_output,
            response_schema=schema, thinking_level='low', retry_attempts=1, timeout=120)

    if ledger is None:
        response = await call()
        cache_hit = False
    else:
        reserve = conservative_token_cost(method, prompt, max_output)
        response, cache_hit = await ledger.dispatch_async(fingerprint=fingerprint, provider=method,
            model=MODELS[method], identity=identity, reserve_usd=reserve, call=call)
    identifiers = validate_ranking(response['text'], chunks)
    return {'ranking': identifiers, 'prompt': prompt, 'raw_output': response['text'],
            'model': MODELS[method], 'seconds': response['latency_seconds'],
            'cache_hit': cache_hit,
            'usage_metadata': response['response_diagnostics']['usage_metadata'],
            'input_tokens': response['input_tokens'], 'output_tokens': response['output_tokens']}


def generation_cache(generator, cases, directories):
    cache = {}
    by_id = {c.case_id: c for _, _, c, _ in cases}
    for directory in directories:
        manifest = json.loads((directory / 'manifest.json').read_text())
        contract = manifest.get('checkpoint_contract', {})
        if contract.get('model', {}).get('digest') != generator.identity['digest'] or contract.get('options') != generator.options:
            continue
        for row in read_rows(directory / 'results.jsonl'):
            case = by_id.get(row['case_id'])
            if not case or row.get('generator_options') != generator.options or not all(k in row for k in GENERATION_FIELDS):
                continue
            prompt = query.rendered_prompt(generator, base.answer_prompt(case.question, row['context']))
            if row['generator_prompt'] != prompt:
                continue
            key = cache_key(generator.identity['digest'], generator.options, case.question, row['context'], row['trial'])
            cache.setdefault(key, (row, str(directory / 'results.jsonl')))
    return cache


def summarize(rows):
    result = {}
    for method in sorted({r['arm'] for r in rows}):
        subset = [r for r in rows if r['arm'] == method]
        valid = [r for r in subset if r['answer_score'] not in ('selection_failure', 'generation_failure')]
        values = {'attempts': len(subset), 'correct': sum(r['answer_score'] == 'correct' for r in subset),
                  'accuracy': mean(r['answer_score'] == 'correct' for r in subset),
                  'failures': len(subset) - len(valid),
                  'fresh_generations': sum(r.get('generation_origin') == 'fresh' for r in subset)}
        for field in ('selected_tokens', 'input_tokens', 'required_claim_coverage', 'redundant_claim_occurrences',
                      'conflicting_chunks', 'generator_input_tokens', 'generator_output_tokens', 'generation_seconds'):
            samples = [r[field] for r in valid if r.get(field) is not None]
            values[field] = mean(samples) if samples else None
        for field in ('precision', 'recall'):
            values[field] = mean(r['selection_score'][field] for r in valid) if valid else None
        for field in ('prepare_seconds', 'selection_seconds', 'end_to_end_seconds', 'component_sum_seconds'):
            samples = [r[field] for r in valid if r.get(field) is not None]
            values[field + '_p50'] = median(samples) if samples else None
            values[field + '_n'] = len(samples)
        values['vs_bge'] = query.paired(rows, method, 'bge')
        result[method] = values
    return result


async def run(args):
    if COHERE_USD_PER_SEARCH is None:
        raise UnpricedProviderError(
            'Cohere direct API USD/search pricing for rerank-v4.0-pro is not published; '
            'the complete paid run is blocked before any provider dispatch'
        )
    ledger = SpendingLedger(SPENDING_LEDGER)
    cases = base.discover_cases(base.CASES_DIR)[:args.limit]
    generator = base.LocalGenerator('qwen2.5:7b')
    count = lru_cache(maxsize=None)(generator.count)
    prior = json.loads((NATIVE / 'manifest.json').read_text())
    assert generator.identity['digest'] == prior['checkpoint_contract']['model']['digest']
    assert generator.options == prior['checkpoint_contract']['options']
    assert generator.tokenizer_identity['template'] == prior['tokenizer']['template']
    for path, digest in prior['frozen_inputs'].items():
        assert base.sha256_file(Path(path)) == digest
    snapshot = json.loads((NATIVE / 'source_snapshot.json').read_text())
    reference_matches = {path: Path(path).read_text() == content
                         for path, content in snapshot.items() if path.startswith('omneum/')}
    args.output.mkdir(parents=True, exist_ok=False)
    manifest = {'implementation': implementation_hash(), 'generator': generator.identity,
        'checkpoint_contract': {'implementation': implementation_hash(), 'model': generator.identity,
                                'options': generator.options},
        'options': generator.options, 'tokenizer': generator.tokenizer_identity,
        'frozen_inputs': prior['frozen_inputs'], 'budgets': args.budgets, 'trials': args.trials,
        'cases': [c.case_id for _, _, c, _ in cases], 'models': MODELS,
        'spending': {'ledger': str(SPENDING_LEDGER), 'estimated_cap_usd': 30.0,
                     'cohere_price_usd_per_search': COHERE_USD_PER_SEARCH,
                     'retry_policy': 'no provider SDK retries; uncertain calls remain reserved'},
        'production_matches_reference': reference_matches,
        'methods': list(METHODS), 'full_context': 'Unbudgeted control, once per case/trial.',
        'ranking': 'Complete pool ranked once per case/trial; deterministic whole-chunk first-fit for every budget.',
        'reranker': {'cohere': {'model': 'rerank-v4.0-pro', 'api': 'ClientV2.rerank',
                                'document_chunking': 'Cohere default; preflight rejects >500-token candidates',
                                'max_retries': 0, 'timeout_seconds': 120}},
        'frontier_judges': {'claude': {'model': MODELS['claude'], 'effort': 'low',
                                      'thinking': 'adaptive provider default', 'max_output_tokens': 2048},
                            'gpt': {'model': MODELS['gpt'], 'reasoning_effort': 'low',
                                    'reasoning_mode': 'standard provider default', 'max_output_tokens': 2048},
                            'gemini': {'model': MODELS['gemini'], 'thinking_level': 'low',
                                       'max_output_tokens': 8192},
                            'temperature': 'provider default; omitted', 'timeout_seconds': 120,
                            'provider_retries': 0},
        'omneum': {'strategy': 'coverage_support_query', 'question': 'case question; passed to production prepare_context'},
        'hybrids': 'Caller raw scores, top three chunk seeds plus ties, depth-two expansion; full-graph evaluation.',
        'reuse': [str(p) for p in args.reuse], 'command': args.command,
        'latency': 'selection_seconds adds measured ranker duration to packing/SDK duration; cached ranker duration is historical. '
                   'component_sum_seconds adds recorded generation time, not contiguous wall time. '
                   'end_to_end_seconds measures fresh generation with current preparation, excludes shared cached ranking.',
        'cost': 'Local generator has no measured dollar rate. Judge list-price estimates separate from unknown local and Cohere costs.',
        'scope': 'Previously evaluated 24 synthetic cases; development/release regression, not fresh held-out validation.'}
    write_json(args.output / 'manifest.json', manifest)
    cache = generation_cache(generator, cases, args.reuse)
    storage = SQLiteStorage(args.output / 'local' / 'omneum.db')
    prepared, ranks, providers, failures = [], {}, [], []
    with base.benchmark_deployment() as (config, server):
        async with open_stdio_client(config, server, local_persistence=LocalPersistenceConfig(storage)) as client:
            for _, _, case, truth in cases:
                observations, chunks, texts = query.inputs(case)
                write_json(args.output / (case.case_id + '-inputs.json'), {
                    'case': asdict(case), 'truth': asdict(truth),
                    'assertion_observations': [asdict(o) for o in observations],
                    'chunks': [{k: v for k, v in c.items() if k != 'source'} for c in chunks]})
                retrieval = json.loads((NATIVE / (case.case_id + '-retrieval.json')).read_text())
                write_json(args.output / (case.case_id + '-retrieval.json'), retrieval)
                by_id = {c['chunk_id']: c for c in chunks}
                for method in ('bm25', 'embedding', 'bge'):
                    entry = retrieval[method]
                    ordered_ids = validate_ranking(json.dumps({'selected_ids': entry['ranking']}), chunks)
                    ranking = [{**by_id[k], 'relevance': entry['raw_scores'][k]} for k in ordered_ids]
                    ranks[(case.case_id, method, 0)] = (ranking, entry['fresh_retrieval_seconds'])
                try:
                    documents = [{'source': c['chunk_id'], 'text': c['raw_text']} for c in chunks]
                    units = cohere_search_units(case.question, chunks)
                    request = {'query': case.question, 'documents': documents,
                               'top_n': len(chunks), 'model': 'rerank-v4.0-pro'}
                    fingerprint = request_fingerprint('cohere', 'rerank-v4.0-pro', request,
                                                      {'case_id': case.case_id, 'trial': 0})
                    def rerank_compact():
                        result = rerank_cohere(case.question, documents, top_n=len(chunks),
                                               max_retries=0, timeout=120)
                        return {**{key: result[key] for key in ('model', 'latency_seconds', 'billed_search_units',
                                    'input_tokens', 'output_tokens') if key in result},
                                'selected': [{'source': item['source'],
                                              'reranker_score': item['reranker_score']}
                                             for item in result['selected']]}
                    compact, cache_hit = ledger.dispatch(fingerprint=fingerprint, provider='cohere',
                        model='rerank-v4.0-pro', identity={'case_id': case.case_id, 'trial': 0},
                        reserve_usd=units * COHERE_USD_PER_SEARCH,
                        call=rerank_compact)
                    response = {**compact, 'cache_hit': cache_hit}
                    ranking = [{**by_id[c['source']], 'relevance': c['reranker_score']} for c in response['selected']]
                    assert len(ranking) == len(chunks) and {c['chunk_id'] for c in ranking} == set(by_id)
                    ranks[(case.case_id, 'cohere', 0)] = (ranking, response['latency_seconds'])
                    providers.append({'case_id': case.case_id, 'method': 'cohere', 'trial': 0, **response})
                except Exception as error:
                    failures.append({'case_id': case.case_id, 'method': 'cohere', **base.provider_error_diagnostics(error)})
                for trial in range(1, args.trials + 1):
                    for method in ('claude', 'gpt', 'gemini'):
                        try:
                            response = await judge(case, chunks, method, ledger=ledger, trial=trial)
                            ranks[(case.case_id, method, trial)] = ([by_id[k] for k in response['ranking']], response['seconds'])
                            providers.append({'case_id': case.case_id, 'method': method, 'trial': trial, **response})
                        except Exception as error:
                            failures.append({'case_id': case.case_id, 'method': method, 'trial': trial,
                                             **base.provider_error_diagnostics(error)})
                    checkpoint(args.output / 'provider_results.jsonl', providers)
                    for budget in args.budgets:
                        for method in METHODS:
                            diag, sdk, record = {}, None, None
                            ranking_method = method.removesuffix('_omneum')
                            ranking = ranks.get((case.case_id, ranking_method, trial if method in MODELS else 0))
                            if method != 'omneum' and ranking is None:
                                prepared.append({'case_id': case.case_id, 'domain': case.domain, 'arm': method,
                                    'method': f'{method}@{budget}', 'trial': trial, 'allocated_budget': budget,
                                    'answer_score': 'selection_failure'})
                                continue
                            started = time.perf_counter()
                            if method == 'omneum' or method.endswith('_omneum'):
                                settings = prepare_options(method, case.question, ranking[0] if ranking else [], diag)
                                sdk = await client.prepare_context(observations, chunks, estimator=base.estimator_config(),
                                    token_budget=budget, count_tokens=count, token_counter_name='resident Qwen2.5 tokenizer', **settings)
                                json.dumps(sdk, allow_nan=False)
                                selected = [by_id[k] for k in sdk['packed_chunk_ids']]
                                context = sdk['context']
                                record, _ = query.history(storage.path)
                            else:
                                selected = base.pack(ranking[0], budget, count)
                                context = base.render(selected)
                            seconds = time.perf_counter() - started
                            assert context == base.render(selected)
                            tokens = count(context)
                            assert tokens <= budget
                            rank_seconds = ranking[1] if ranking else 0.0
                            prepared.append({'case_id': case.case_id, 'domain': case.domain, 'arm': method,
                                'method': f'{method}@{budget}', 'trial': trial, 'allocated_budget': budget,
                                'context': context, 'selected': [c['chunk_id'] for c in selected],
                                'selected_chunks': [{k: v for k, v in c.items() if k != 'source'} for c in selected],
                                'excluded': diag.get('excluded_chunks', []), 'diagnostics': diag,
                                'sdk_result': sdk, 'execution_history': record,
                                'input_tokens': count(base.render(chunks)), 'selected_tokens': tokens,
                                'prepare_seconds': seconds, 'rank_seconds': rank_seconds,
                                'selection_seconds': rank_seconds + seconds,
                                **base.evidence_metrics(case, truth, chunks, selected)})
                    prepared.append({'case_id': case.case_id, 'domain': case.domain, 'arm': 'full',
                        'method': 'full', 'trial': trial, 'allocated_budget': None,
                        'context': base.render(chunks), 'selected': list(by_id),
                        'input_tokens': count(base.render(chunks)), 'selected_tokens': count(base.render(chunks)),
                        'prepare_seconds': 0.0, 'rank_seconds': 0.0, 'selection_seconds': 0.0,
                        **base.evidence_metrics(case, truth, chunks, chunks)})
                checkpoint(args.output / 'selections.jsonl', prepared)
                print('selected', case.case_id, flush=True)
    write_json(args.output / 'provider_failures.json', failures)
    # All selections are frozen before answers. Alternating arm order reduces
    # systematic execution-order effects without changing trial seeds.
    rows = []
    for case_id in manifest['cases']:
        case, truth = next((c, t) for _, _, c, t in cases if c.case_id == case_id)
        subset = [r for r in prepared if r['case_id'] == case_id]
        subset.sort(key=lambda r: (r['trial'], r['allocated_budget'] or 0,
                                   METHODS.index(r['arm']) * (-1 if r['trial'] % 2 else 1) if r['arm'] != 'full' else -100))
        for row in subset:
            if row.get('answer_score') == 'selection_failure':
                rows.append(row)
                continue
            key = cache_key(generator.identity['digest'], generator.options, case.question, row['context'], row['trial'])
            cached = cache.get(key)
            started = time.perf_counter()
            try:
                if cached:
                    original, origin = cached
                    row.update({k: original[k] for k in GENERATION_FIELDS})
                    row.update(generation_origin='reused', reused_from=origin, end_to_end_seconds=None)
                else:
                    generation = generator.generate(base.answer_prompt(case.question, row['context']))
                    response = generation['response']
                    row.update(answer=response['response'], generator_input_tokens=response['prompt_eval_count'],
                        generator_output_tokens=response['eval_count'], generation_seconds=generation['seconds'],
                        generator_prompt=generation['request']['prompt'], generator_options=generation['request']['options'],
                        generator_metadata={k: v for k, v in response.items() if k != 'response'},
                        generation_origin='fresh', end_to_end_seconds=None)
                    # Selection is staged; no contiguous end-to-end latency is invented.
                    cache[key] = (dict(row), str(args.output / 'results.jsonl'))
                row['answer_score'] = score_answer(row['answer'], truth)
                row['component_sum_seconds'] = row['selection_seconds'] + row['generation_seconds']
            except Exception as error:
                row.update(answer_score='generation_failure', failure_diagnostics=base.provider_error_diagnostics(error))
            rows.append(row)
            checkpoint(args.output / 'results.jsonl', rows)
        print('generated', case_id, len(rows), 'fresh', sum(r.get('generation_origin') == 'fresh' for r in rows), flush=True)
    generator.http.close()
    write_json(args.output / 'summary.json', {'overall': summarize(rows),
        'by_budget': {str(b): summarize([r for r in rows if r['allocated_budget'] == b]) for b in args.budgets},
        'by_domain': {d: summarize([r for r in rows if r['domain'] == d]) for d in sorted({r['domain'] for r in rows})}})


async def recheck(args):
    source = args.recheck_from
    manifest = json.loads((source / 'manifest.json').read_text())
    targets = [r for r in read_rows(source / 'results.jsonl') if r.get('sdk_result')]
    cases = {c.case_id: c for _, _, c, _ in base.discover_cases(base.CASES_DIR)}
    generator = base.LocalGenerator('qwen2.5:7b')
    assert generator.identity['digest'] == manifest['generator']['digest']
    assert generator.options == manifest['options']
    count = lru_cache(maxsize=None)(generator.count)
    paths = ('omneum/client.py', 'omneum/agent_result.py', 'omneum/context_selection.py',
             'omneum/inference.py', 'omneum/dependency.py', 'omneum/query_context.py')
    snapshot = {path: Path(path).read_text() for path in paths}
    args.output.mkdir(parents=True, exist_ok=False)
    write_json(args.output / 'source_snapshot.json', snapshot)
    write_json(args.output / 'manifest.json', {'parent': str(source), 'command': args.command,
        'generator': generator.identity, 'options': generator.options,
        'frozen_inputs': manifest['frozen_inputs'], 'scope': 'Fresh current SDK; exact context and graph-score parity; no answer generations.'})
    for path, digest in manifest['frozen_inputs'].items():
        assert base.sha256_file(Path(path)) == digest
    storage = SQLiteStorage(args.output / 'local' / 'omneum.db')
    rows, additions = [], set()
    with base.benchmark_deployment() as (config, server):
        async with open_stdio_client(config, server, local_persistence=LocalPersistenceConfig(storage)) as client:
            for case_id in dict.fromkeys(r['case_id'] for r in targets):
                case = cases[case_id]
                observations, chunks, _ = query.inputs(case)
                by_id = {c['chunk_id']: c for c in chunks}
                retrieval = json.loads((source / (case_id + '-retrieval.json')).read_text())
                for old in targets:
                    if old['case_id'] != case_id:
                        continue
                    method = old['arm']
                    ranking = []
                    if method != 'omneum':
                        scores = retrieval[method.removesuffix('_omneum')]
                        ranking = [{**by_id[k], 'relevance': scores['raw_scores'][k]} for k in scores['ranking']]
                    settings = prepare_options(method, case.question, ranking, {})
                    started = time.perf_counter()
                    result = await client.prepare_context(observations, chunks, estimator=base.estimator_config(),
                        token_budget=old['allocated_budget'], count_tokens=count,
                        token_counter_name='resident Qwen2.5 tokenizer', **settings)
                    seconds = time.perf_counter() - started
                    json.dumps(result, allow_nan=False)
                    for name in ('evaluation', 'packed_chunk_ids', 'chunks', 'context'):
                        assert result[name] == old['sdk_result'][name]
                    for name, value in old['sdk_result']['selection'].items():
                        assert result['selection'][name] == value
                    additions.update(set(result['selection']) - set(old['sdk_result']['selection']))
                    assert count(result['context']) == old['selected_tokens'] <= old['allocated_budget']
                    record, _ = query.history(storage.path)
                    rows.append({'case_id': case_id, 'arm': method, 'trial': old['trial'],
                        'allocated_budget': old['allocated_budget'], 'prepare_seconds': seconds,
                        'sdk_result': result, 'execution_history': record})
                checkpoint(args.output / 'results.jsonl', rows)
                print('verified current SDK', case_id, len(rows), flush=True)
    assert all(Path(path).read_text() == text for path, text in snapshot.items())
    write_json(args.output / 'summary.json', {'records': len(rows), 'exact_context_and_score_parity': True,
        'added_selection_fields': sorted(additions), 'sources_stable_during_recheck': True,
        'prepare_p50_ms': {m: median(r['prepare_seconds'] * 1000 for r in rows if r['arm'] == m)
                           for m in sorted({r['arm'] for r in rows})}})
    generator.http.close()


if __name__ == '__main__':
    import sys
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--recheck-from', type=Path)
    parser.add_argument('--limit', type=int, default=24)
    parser.add_argument('--trials', type=int, default=2)
    parser.add_argument('--budgets', nargs='+', type=int, default=list(BUDGETS))
    parser.add_argument('--reuse', nargs='+', type=Path, default=[NATIVE,
        base.RESULTS_DIR / 'relevance-gate-v1', base.RESULTS_DIR / 'query-expansion-v2',
        base.RESULTS_DIR / 'prepare-context-v1', base.RESULTS_DIR / 'retriever-native-bge-matched-v1'])
    args = parser.parse_args()
    args.command = ' '.join(sys.argv)
    asyncio.run(recheck(args) if args.recheck_from else run(args))
