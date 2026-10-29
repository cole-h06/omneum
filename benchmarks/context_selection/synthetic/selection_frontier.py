import argparse
import asyncio
from collections import Counter
from contextlib import closing
from dataclasses import asdict
from functools import lru_cache
import hashlib
from itertools import combinations
import json
from math import sqrt
from pathlib import Path
import sqlite3
from statistics import mean
import time

from omneum import LocalPersistenceConfig, open_stdio_client
from omneum.context_selection import map_chunks, reconstruct, select_chunks
from omneum.storage import SQLiteStorage
from . import prepare_benchmark as base
from .sdk_adapter import observation_chunk_pairs
from .artifacts import checkpoint, write_json
from .checkpoint import TrialCheckpoint, implementation_hash
from .scoring import score_answer


BUDGETS = (64, 96, 128, 160, 192, 256)
VARIANTS = ('packing', 'qualifications', 'complementary', 'mapped_expansion',
            'complementary_packing', 'packing_expansion')
PRIOR = base.RESULTS_DIR / 'prepare-context-v1'


def read_rows(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


def graph_record(path, run_id, observations, chunks, case=None):
    with closing(sqlite3.connect(path)) as db:
        db.row_factory = sqlite3.Row
        rows = db.execute('SELECT local_observation_id, source_id FROM observations WHERE evaluation_run_id=?', (run_id,)).fetchall()
        by_observation = {r['local_observation_id']: r['source_id'] for r in rows}
        if case is None:
            # Older callers passed singleton observations in input order.
            if len(observations) != len(chunks):
                raise ValueError('multi-claim graph_record requires case membership')
            pairs = zip(observations, chunks, strict=True)
        else:
            pairs = observation_chunk_pairs(observations, chunks, case)
        by_source = {by_observation[o.observation_id]: c['chunk_id'] for o, c in pairs}
        independent = {by_source[r['source_id']]: r['independence'] for r in db.execute(
            'SELECT source_id, independence FROM claim_support_sources WHERE evaluation_run_id=?', (run_id,))}
        reliability = {by_source[r['source_id']]: r['reliability_score'] for r in db.execute(
            'SELECT source_id, reliability_score FROM source_scores WHERE evaluation_run_id=?', (run_id,))}
        dependencies = [{'a': by_source[r['source_a_id']], 'b': by_source[r['source_b_id']],
                         'dependency': r['dependency_score']} for r in db.execute(
            'SELECT * FROM source_dependencies WHERE evaluation_run_id=?', (run_id,))]
        history = dict(db.execute('SELECT * FROM execution_history WHERE evaluation_run_id=?', (run_id,)).fetchone())
    return {'independence': independent, 'reliability': reliability,
            'dependencies': dependencies, 'history': history}


def diagnose(chunks, support, budget, count):
    mapping = map_chunks(chunks, support)
    selection = select_chunks(mapping, support, budget, 'coverage_support', count_tokens=count)
    ordered = sorted(mapping['retrieval_order'], key=lambda k: -selection['candidate_scores'][k])
    rendering = {**mapping, 'retrieval_order': ordered}
    chosen, covered, trace = [], set(), []
    for entry in selection['selection_scores']:
        key = entry['chunk_id']
        new = set(mapping['chunk_claims'][key]) - covered
        before = count(reconstruct(rendering, chosen))
        chosen.append(key)
        trace.append({'chunk_id': key, 'new_claims': sorted(new), 'marginal_support': entry['score'],
                      'incremental_cost': count(reconstruct(rendering, chosen)) - before})
        covered.update(new)
    remaining = []
    for c in chunks:
        if c['chunk_id'] not in chosen:
            new = set(c['claim_ids']) - covered
            tokens = count(reconstruct(rendering, [*chosen, c['chunk_id']]))
            remaining.append({'chunk_id': c['chunk_id'], 'new_claims': sorted(new),
                              'marginal_support': sum(support[x] for x in new),
                              'proposed_size': tokens, 'feasible': tokens <= budget})
    feasible = [c for c in remaining if c['feasible']]
    assert not any(c['marginal_support'] > 0 for c in feasible)
    reason = 'candidate_exhaustion' if not remaining else (
        'zero_marginal_coverage' if feasible else 'no_feasible_chunk')
    return {'final_size': selection['token_usage'], 'selection': selection, 'trace': trace, 'remaining': remaining, 'stop_reason': reason}


def objective(selected, support, independence=None, repeated=False):
    mass = {}
    seen = set()
    for chunk in selected:
        # A source contributes at most once per claim. Full-graph independence
        # weights are fixed inference outputs, never recomputed on this subset.
        for claim in set(chunk['claim_ids']):
            key = (chunk['source_id'], claim)
            if key not in seen:
                seen.add(key)
                weight = independence[chunk['chunk_id']] if independence is not None else 1.0
                mass[claim] = mass.get(claim, 0.0) + weight
    if repeated:
        # Concavity permits complementary same-claim passages with diminishing
        # returns. This is a selection hypothesis, not proof of novel information.
        return sum(support[c] * sqrt(mass[c]) for c in sorted(mass))
    return sum(support[c] for c in sorted(mass))


def experiment(chunks, support, budget, count, method, independence, production_ids):
    order = sorted(chunks, key=lambda c: -sum(support[x] for x in set(c['claim_ids'])))
    repeated = method in ('qualifications', 'complementary', 'complementary_packing')
    weights = independence if method.startswith('complementary') else None

    def ordered(items):
        keys = {c['chunk_id'] for c in items}
        return [c for c in order if c['chunk_id'] in keys]

    def value(items):
        return objective(items, support, weights, repeated)

    if method in ('packing', 'packing_expansion', 'complementary_packing'):
        selected, best = [], (0.0, 0)
        # Exact subsets are practical only for these frozen pools (<=10 chunks).
        # Maximize utility; ties prefer fewer tokens, then enumeration order.
        for size in range(len(order) + 1):
            for subset in combinations(order, size):
                tokens = count(base.render(subset))
                score = (value(subset), -tokens)
                if tokens <= budget and score > best:
                    selected, best = list(subset), score
    elif method == 'mapped_expansion':
        selected = [c for c in order if c['chunk_id'] in production_ids]
    else:
        selected, remaining = [], list(order)
        while remaining:
            utilities = {}
            for i, chunk in enumerate(remaining):
                proposal = ordered([*selected, chunk])
                if count(base.render(proposal)) <= budget:
                    utilities[i] = value(proposal) - value(selected)
            if not utilities:
                break
            i = max(utilities, key=utilities.get)
            if utilities[i] <= 0:
                break
            selected = ordered([*selected, remaining.pop(i)])
    if method in ('mapped_expansion', 'packing_expansion'):
        covered = {c for chunk in selected for c in chunk['claim_ids']}
        positions = {c['chunk_id']: i for i, c in enumerate(chunks)}
        # No fixture has adjacent segments from one original document. Expand
        # mapped claims across complete passages instead; never invent neighbors.
        anchors = [positions[c['chunk_id']] for c in selected]
        neighbors = sorted(chunks, key=lambda c: min((abs(positions[c['chunk_id']]-i) for i in anchors), default=len(chunks)))
        for chunk in neighbors:
            if chunk in selected or not covered.intersection(chunk['claim_ids']):
                continue
            proposal = ordered([*selected, chunk])
            if count(base.render(proposal)) <= budget:
                selected = proposal
    context = base.render(selected)
    assert count(context) <= budget
    return selected, context, {'objective': value(selected), 'independence_weighted': weights is not None,
                              'repeated_claim_utility': repeated}


def cache_key(model, options, question, context, trial):
    payload = [model, options, base.answer_prompt(question, context), trial]
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def summarize(rows):
    result = {}
    for budget in sorted({r['allocated_budget'] for r in rows}):
        subset = [{**r, 'method': r['arm']} for r in rows if r['allocated_budget'] == budget]
        groups = base.aggregate(subset)
        for arm, metrics in groups.items():
            selected = [r for r in subset if r['method'] == arm]
            metrics['fresh_generations'] = sum(r.get('generation_origin') == 'fresh' for r in selected)
            metrics['no_exact_match'] = sum(r['answer_score'] == 'not_matched' for r in selected)
            metrics['represented_independence_mass'] = mean(r['represented_independence_mass'] for r in selected if 'represented_independence_mass' in r) if any('represented_independence_mass' in r for r in selected) else None
        result[str(budget)] = groups
    return result


async def run(args):
    cases = base.discover_cases(base.CASES_DIR)[:args.limit]
    generator = base.LocalGenerator('qwen2.5:7b')
    count = lru_cache(maxsize=None)(generator.count)
    prior_manifest = json.loads((PRIOR / 'manifest.json').read_text())
    assert generator.identity['digest'] == prior_manifest['generator']['digest']
    assert generator.options == prior_manifest['options']
    assert generator.tokenizer_identity['template'] == prior_manifest['tokenizer']['template']
    prior = read_rows(PRIOR / 'results.jsonl')
    schedules = []
    for _, _, case, _ in cases:
        for trial in range(1, args.trials + 1):
            for budget in args.budgets:
                arms = ['omneum', 'bge_matched']
                if budget == 128 and args.variants:
                    arms.extend(VARIANTS)
                if (trial + len(schedules)) % 2:
                    arms = list(reversed(arms))
                for arm in arms:
                    schedules.append((case.case_id, f'{arm}@{budget}', trial))
    contract = {'implementation': implementation_hash(), 'budgets': args.budgets, 'variants': args.variants,
                'trials': args.trials, 'strategy': args.strategy, 'reuse': [str(p) for p in args.reuse], 'cases': [c.case_id for _, _, c, _ in cases],
                'model': generator.identity, 'options': generator.options}
    generation_cache = {}
    for origin in [PRIOR, *args.reuse]:
        cached_manifest = json.loads((origin / 'manifest.json').read_text())
        assert cached_manifest['checkpoint_contract']['model']['digest'] == generator.identity['digest']
        assert cached_manifest['checkpoint_contract']['options'] == generator.options
        for row in read_rows(origin / 'results.jsonl'):
            if row.get('answer_score') in ('correct', 'incorrect', 'unscored'):
                case = next((c for _, _, c, _ in cases if c.case_id == row['case_id']), None)
                if case:
                    key = cache_key(generator.identity['digest'], generator.options, case.question, row['context'], row['trial'])
                    generation_cache.setdefault(key, (row, str(origin / 'results.jsonl')))
    with TrialCheckpoint(args.output, contract, schedules) as progress:
        write_json(args.output / 'manifest.json', {'checkpoint_contract': contract,
            'tokenizer': generator.tokenizer_identity, 'reuse': 'Exact model digest, options, question, context and trial. Reused model latency is historical; no new measured end-to-end latency.',
            'token_counter_cache': 'Exact model tokenizer memoized by complete text, shared by every selector; cache hits are included in preparation time.',
            'variants': {'packing': 'max distinct-claim support; ties minimum tokens',
                         'qualifications': 'greedy sum s_c sqrt(number of distinct supporting sources)',
                         'complementary': 'greedy sum s_c sqrt(sum full-graph source independence)',
                         'complementary_packing': 'exact subset maximization of complementary objective',
                         'mapped_expansion': 'production plus feasible same-claim passages by retrieval distance',
                         'packing_expansion': 'exact distinct coverage plus same-claim expansion'},
            'frozen_inputs': {str(p): base.sha256_file(p) for entry in cases for p in entry[:2]},
            'limitations': ['Development comparison on previously evaluated cases, not new held-out validation.',
                           'No within-document adjacency or omitted text is available; true document-local expansion is not measurable.',
                           'Canonical claim coverage does not certify retention of qualifications.',
                           'Exact enumeration scales exponentially and is research-only.'],
            'controls': {'prompt': 'Existing frozen benchmark answer prompt', 'token_penalty': 0.0,
                         'semantic_relevance': False, 'dataset_changes': False, 'strategy': args.strategy}})
        storage = SQLiteStorage(args.output / 'local' / 'omneum.db')
        prepared, diagnostics = {}, []
        with base.benchmark_deployment() as (config, server):
            async with open_stdio_client(config, server, local_persistence=LocalPersistenceConfig(storage)) as client:
                # Finish all selection diagnostics before any new model answers.
                for _, _, case, truth in cases:
                    observations, chunks = base.mapped_chunks(case)
                    original_tokens = count(base.render(chunks))
                    write_json(args.output / (case.case_id + '-inputs.json'), {'case': asdict(case), 'truth': asdict(truth),
                        'chunks': chunks, 'assertion_observations': [asdict(o) for o in observations]})
                    baseline_row = next(r for r in prior if r['case_id'] == case.case_id and r['method'] == 'omneum')
                    audit = diagnose(chunks, baseline_row['sdk_result']['evaluation']['claim_support'], 128, count)
                    assert audit['selection']['context'] == baseline_row['context']
                    diagnostics.append({'case_id': case.case_id, **audit,
                        'graph': graph_record(PRIOR / 'local' / 'omneum.db', baseline_row['execution_history']['evaluation_run_id'], observations, chunks, case),
                        'historical_answer': baseline_row['answer'], 'historical_score': baseline_row['answer_score']})
                    ranked, ranking_seconds = base.rank(case, chunks, 'bge')
                    for trial in range(1, args.trials + 1):
                        for budget in args.budgets:
                            started = time.perf_counter()
                            sdk = await client.prepare_context(observations, chunks, estimator=base.estimator_config(),
                                token_budget=budget, strategy=args.strategy, count_tokens=count, token_counter_name='resident Qwen2.5 tokenizer; memoized exact texts')
                            preparation = time.perf_counter() - started
                            with closing(sqlite3.connect(storage.path)) as db:
                                run_id = db.execute('SELECT evaluation_run_id FROM execution_history ORDER BY rowid DESC LIMIT 1').fetchone()[0]
                            graph = graph_record(storage.path, run_id, observations, chunks, case)
                            support = sdk['evaluation']['claim_support']
                            assert support == baseline_row['sdk_result']['evaluation']['claim_support']
                            by_id = {c['chunk_id']: c for c in chunks}
                            methods = ['omneum', 'bge_matched'] + (list(VARIANTS) if budget == 128 and args.variants else [])
                            for arm in methods:
                                started = time.perf_counter()
                                details = {}
                                if arm == 'omneum':
                                    selected = [by_id[k] for k in sdk['packed_chunk_ids']]
                                    context = sdk['context']
                                    seconds = preparation
                                elif arm == 'bge_matched':
                                    selected = base.exact_match(ranked, sdk['selection']['selected_tokens'], count)
                                    if selected is None:
                                        prepared[(case.case_id, f'{arm}@{budget}', trial)] = {'case_id': case.case_id,
                                            'method': f'{arm}@{budget}', 'arm': arm, 'trial': trial, 'allocated_budget': budget,
                                            'answer_score': 'not_matched', 'reason': 'No exact whole-passage BGE subset'}
                                        continue
                                    context = base.render(selected)
                                    seconds = time.perf_counter() - started + ranking_seconds
                                    details['matched_target'] = sdk['selection']['selected_tokens']
                                else:
                                    selected, context, details = experiment(chunks, support, budget, count, arm,
                                        graph['independence'], sdk['packed_chunk_ids'])
                                    seconds = time.perf_counter() - started + preparation
                                assert context == base.render(selected)
                                row = {'case_id': case.case_id, 'method': f'{arm}@{budget}', 'arm': arm, 'trial': trial,
                                    'allocated_budget': budget, 'selected_tokens': count(context), 'input_tokens': original_tokens,
                                    'graph_support': support, 'context': context, 'selected': [c['chunk_id'] for c in selected], 'selected_chunks': selected,
                                    'prepare_seconds': seconds, 'details': details, 'graph': graph,
                                    'reduction_ratio': (original_tokens-count(context))/original_tokens,
                                    'budget_utilization': count(context)/budget,
                                    'represented_independence_mass': sum(graph['independence'][c['chunk_id']] for c in selected),
                                    'execution_history': graph['history'], 'sdk_result': sdk if arm == 'omneum' else None,
                                    **base.evidence_metrics(case, truth, chunks, selected)}
                                assert row['selected_tokens'] <= budget
                                prepared[(case.case_id, f'{arm}@{budget}', trial)] = row
                    print('selected', case.case_id, flush=True)
                checkpoint(args.output / 'diagnostics.jsonl', diagnostics)
                checkpoint(args.output / 'selections.jsonl', list(prepared.values()))
                write_json(args.output / 'selection_summary.json', {
                    'stop_reasons_at_128': dict(Counter(r['stop_reason'] for r in diagnostics)),
                    'selected_mean_at_128': mean(r['selection']['token_usage'] for r in diagnostics),
                    'selection_hash': base.sha256_file(args.output / 'selections.jsonl'),
                    'frozen_before_generation': True, 'tokenizer_cache': count.cache_info()._asdict()})
                print('Selection diagnostics frozen; beginning generations', flush=True)
                by_case = {c.case_id: (c, t) for _, _, c, t in cases}
                for key in schedules:
                    row = prepared[key]
                    if row.get('answer_score') == 'not_matched':
                        progress.commit(row)
                        continue
                    case, truth = by_case[row['case_id']]
                    key_digest = cache_key(generator.identity['digest'], generator.options, case.question, row['context'], row['trial'])
                    cached = generation_cache.get(key_digest)
                    started = time.perf_counter()
                    try:
                        observations, chunks = base.mapped_chunks(case)
                        if row['arm'] == 'bge_matched':
                            ranked, _ = base.rank(case, chunks, 'bge')
                            selected = base.exact_match(ranked, row['selected_tokens'], count)
                            context = base.render(selected)
                        else:
                            sdk = await client.prepare_context(observations, chunks, estimator=base.estimator_config(),
                                token_budget=row['allocated_budget'], strategy=args.strategy, count_tokens=count,
                                token_counter_name='resident Qwen2.5 tokenizer; memoized exact texts')
                            assert sdk['evaluation']['claim_support'] == row['graph_support']
                            if row['arm'] == 'omneum':
                                by_id = {c['chunk_id']: c for c in chunks}
                                selected = [by_id[k] for k in sdk['packed_chunk_ids']]
                                context = sdk['context']
                                row['sdk_result'] = sdk
                            else:
                                selected, context, _ = experiment(chunks, row['graph_support'], row['allocated_budget'],
                                    count, row['arm'], row['graph']['independence'], sdk['packed_chunk_ids'])
                            with closing(sqlite3.connect(storage.path)) as db:
                                run_id = db.execute('SELECT evaluation_run_id FROM execution_history ORDER BY rowid DESC LIMIT 1').fetchone()[0]
                            row['execution_history'] = graph_record(storage.path, run_id, observations, chunks, case)['history']
                        assert context == row['context']
                        assert [c['chunk_id'] for c in selected] == row['selected']
                        row['prepare_seconds'] = time.perf_counter() - started
                        if cached:
                            original, origin = cached
                            row.update({k: original[k] for k in ('answer', 'generator_input_tokens', 'generator_output_tokens',
                                'generation_seconds', 'generator_prompt', 'generator_options', 'generator_metadata')})
                            row.update(generation_origin='reused', reused_from={'path': origin, 'case_id': original['case_id'],
                                'method': original['method'], 'trial': original['trial']}, end_to_end_seconds=None)
                        else:
                            generation = generator.generate(base.answer_prompt(case.question, row['context']))
                            response = generation['response']
                            row.update(answer=response['response'], generator_input_tokens=response['prompt_eval_count'],
                                generator_output_tokens=response['eval_count'], generation_seconds=generation['seconds'],
                                generator_prompt=generation['request']['prompt'], generator_options=generation['request']['options'],
                                generator_metadata={k: v for k, v in response.items() if k != 'response'},
                                generation_origin='fresh', end_to_end_seconds=time.perf_counter()-started,
                                measured_preparation_plus_generation_seconds=row['prepare_seconds'] + generation['seconds'])
                            generation_cache[key_digest] = (dict(row), str(args.output / 'results.jsonl'))
                        row['answer_score'] = score_answer(row['answer'], truth)
                    except Exception as error:
                        row.update(answer_score='generation_failure', failure_type='generation_failure',
                                   failure_diagnostics=base.provider_error_diagnostics(error))
                    progress.commit(row)
                    print(row['case_id'], row['method'], row['trial'], row['answer_score'], row.get('generation_origin'), flush=True)
                write_json(args.output / 'summary.json', summarize(progress.records))
    generator.http.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--budgets', type=int, nargs='+', default=list(BUDGETS))
    parser.add_argument('--trials', type=int, default=2)
    parser.add_argument('--limit', type=int, default=24)
    parser.add_argument('--variants', action='store_true')
    parser.add_argument('--strategy', choices=('coverage_support','coverage_support_packed'), default='coverage_support')
    parser.add_argument('--reuse', type=Path, nargs='*', default=[])
    args = parser.parse_args()
    if args.trials < 1 or args.limit < 1 or any(b <= 0 for b in args.budgets):
        parser.error('trials, limit and budgets must be positive')
    asyncio.run(run(args))


if __name__ == '__main__':
    main()
