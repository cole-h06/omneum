import argparse
import asyncio
from contextlib import closing
from dataclasses import asdict, replace
from itertools import combinations
import json
import os
from pathlib import Path
import sqlite3
from statistics import mean
import time

# The two existing semantic models must already be cached; never pull weights.
os.environ.setdefault('HF_HUB_OFFLINE', '1')
os.environ.setdefault('TRANSFORMERS_OFFLINE', '1')

from omneum import LocalPersistenceConfig, open_stdio_client
from omneum.context_selection import claim_id
from omneum.metrics import _peak_process_memory_bytes
from omneum.storage import SQLiteStorage
from benchmarks.context_selection.application_comparison import select_vector, select_bge, provider_error_diagnostics
from benchmarks.context_selection.config import estimator_config
from benchmarks.context_selection.deployment import benchmark_deployment
from benchmarks.context_selection.reproducibility import manifest, write_manifest, sha256_file
from research.experiments.applied.agent_dataset.enterprise.local_generator import LocalGenerator
from .artifacts import checkpoint, write_json
from .checkpoint import TrialCheckpoint, implementation_hash, record_key
from .run_benchmark import CASES_DIR, RESULTS_DIR, discover_cases
from .scoring import score_answer, score_selection
from .sdk_adapter import build_observations
from .schema import candidate_claims


ARMS = ('full', 'embedding', 'bge', 'relevance_budgeted', 'omneum', 'omneum_no_dependency')
CONTROL_CASES = ('enterprise_semantic_distractors', 'multi_agent_relevant_wrong_task')


def answer_prompt(query, context):
    # Keep the published prompt unchanged while passing SDK context verbatim.
    return f"""Answer the question using only the sources below.

Question:

{query}

Sources:

{context}

Give a concise answer and identify which sources support it.
"""


def render(chunks):
    return '\n\n'.join(f"[{item['chunk_id']}]\n{item['raw_text']}" for item in chunks)


def mapped_chunks(case):
    observations, _ = build_observations(case)
    by_id = {o.observation_id: o for o in observations}
    chunks = []
    for candidate in case.candidates:
        chunks.append({'chunk_id': 'chunk-' + candidate.source_id,
                       'source_id': candidate.source_id, 'raw_text': candidate.text,
                       'claim_ids': list(dict.fromkeys(claim_id(by_id[spec.observation_id].claim)
                                            for spec in candidate_claims(candidate)))})
    return observations, chunks


def controlled_chunks(chunks, observations, truth, copies, position):
    required = {claim for c in chunks if c['source_id'] in truth.supporting_sources for claim in c['claim_ids']}
    scope = {(o.claim.entity_namespace, o.claim.entity, o.claim.attribute)
             for o in observations if claim_id(o.claim) in required}
    unrelated = {claim_id(o.claim) for o in observations
                 if (o.claim.entity_namespace, o.claim.entity, o.claim.attribute) not in scope}
    rest = [c for c in chunks if c['source_id'] not in truth.supporting_sources]
    # Repeat existing off-task retrieval passages, without inventing observations
    # or independent sources. Only chunk IDs and their positions change.
    for repeat in range(copies):
        for chunk in chunks:
            if set(chunk['claim_ids']) <= unrelated:
                rest.append({**chunk, 'chunk_id': f"{chunk['chunk_id']}-copy-{repeat}"})
    essential = [c for c in chunks if c['source_id'] in truth.supporting_sources]
    offset = {'beginning': 0, 'middle': len(rest) // 2, 'end': len(rest)}[position]
    return rest[:offset] + essential + rest[offset:]


def pack(ranked, budget, count):
    selected = []
    # Whole-chunk first-fit packing in descending relevance order. Oversized
    # chunks are skipped; headers and separators are counted in every proposal.
    for chunk in ranked:
        if count(render([*selected, chunk])) <= budget:
            selected.append(chunk)
    return selected


def density_pack(ranked, budget, count):
    selected, remaining = [], list(ranked)
    while remaining:
        current = count(render(selected))
        utilities = {}
        for index, chunk in enumerate(remaining):
            tokens = count(render([*selected, chunk]))
            if tokens <= budget:
                # This baseline maximizes relevance per exact incremental token.
                # A nonpositive cost gets denominator one; no additivity is assumed.
                utilities[index] = chunk['relevance'] / max(1, tokens - current)
        if not utilities:
            break
        index = max(utilities, key=utilities.get)
        if utilities[index] <= 0:
            break
        selected.append(remaining.pop(index))
    return selected


def exact_match(ranked, target, count):
    best, best_score = None, float('-inf')
    # Frozen pools contain at most ten passages. Exhaustive subsets make this
    # secondary comparison exactly token-matched, rather than merely cap-matched.
    for size in range(len(ranked) + 1):
        for subset in combinations(ranked, size):
            if count(render(subset)) == target:
                score = sum(c['relevance'] for c in subset)
                if score > best_score:
                    best, best_score = list(subset), score
    return best


def rank(case, chunks, method):
    if method == 'bm25':
        from omneum.query_context import bm25_scores

        started = time.perf_counter()
        scores = bm25_scores(case.question, {c['chunk_id']: c['raw_text'] for c in chunks})
        ranked = sorted(chunks, key=lambda c: -scores[c['chunk_id']])
        return [{**c, 'relevance': scores[c['chunk_id']]} for c in ranked], time.perf_counter() - started
    candidates = [{'source': c['chunk_id'], 'text': c['raw_text']} for c in chunks]
    function = select_bge if method == 'bge' else select_vector
    result = function(case.question, candidates, top_n=len(candidates))
    by_id = {c['chunk_id']: c for c in chunks}
    ranked = [{**by_id[c['source']], 'relevance': c.get('reranker_score', c.get('score'))}
              for c in result['selected']]
    return ranked, result['latency_seconds']


def no_dependency_estimator():
    # The supported graph channel is currently unobserved and always zero.
    # Assigning weight only to it disables adjustment without changing the graph.
    return replace(estimator_config(), upstream_weight=0.0, citation_weight=0.0,
                   assertion_lineage_weight=0.0, ownership_weight=0.0,
                   temporal_weight=0.0, graph_weight=1.0, retrieval_weight=0.0)


def evidence_metrics(case, truth, chunks, selected):
    observations, original = mapped_chunks(case)
    claims = [claim for c in selected for claim in c['claim_ids']]
    required = {claim for c in original if c['source_id'] in truth.supporting_sources for claim in c['claim_ids']}
    scope = {(o.claim.entity_namespace, o.claim.entity, o.claim.attribute)
             for o in observations if claim_id(o.claim) in required}
    conflicts = {claim_id(o.claim) for o in observations
                 if (o.claim.entity_namespace, o.claim.entity, o.claim.attribute) in scope
                 and claim_id(o.claim) not in required}
    sources = {c['source_id'] for c in selected}
    return {
        'required_claim_coverage': len(set(claims) & required) / len(required),
        'redundant_claim_occurrences': len(claims) - len(set(claims)),
        'conflicting_chunks': sum(bool(set(c['claim_ids']) & conflicts) for c in selected),
        'off_task_claim_chunks': sum(not (set(c['claim_ids']) & (required | conflicts)) for c in selected),
        'all_annotated_supporters_retained': set(truth.supporting_sources) <= sources,
        'complete_multi_hop_chain': None, 'necessary_exception_retention': None,
        'selection_score': score_selection(sources, truth),
    }


def aggregate(rows):
    groups = {}
    metrics = ('input_tokens', 'selected_tokens', 'reduction_ratio', 'budget_utilization',
               'required_claim_coverage', 'redundant_claim_occurrences', 'conflicting_chunks',
               'off_task_claim_chunks', 'prepare_seconds', 'end_to_end_seconds',
               'generator_input_tokens', 'generator_output_tokens', 'generation_seconds',
               'harness_selection_cpu_ms')
    for method in dict.fromkeys(r['method'] for r in rows):
        selected = [r for r in rows if r['method'] == method]
        completed = [r for r in selected if r['answer_score'] in ('correct', 'incorrect', 'unscored')]
        values = {'trials': len(selected), 'generated': len(completed),
                  'correct': sum(r['answer_score'] == 'correct' for r in selected),
                  'incorrect': sum(r['answer_score'] == 'incorrect' for r in selected),
                  'unscored': sum(r['answer_score'] == 'unscored' for r in selected),
                  'failures': sum(r['answer_score'].endswith('failure') for r in selected),
                  'not_matched': sum(r['answer_score'] == 'not_matched' for r in selected)}
        values['accuracy'] = values['correct'] / len(selected)
        for key in metrics:
            samples = [r[key] for r in completed if r.get(key) is not None]
            values[key] = mean(samples) if samples else None
        history = [r['execution_history'] for r in completed if r.get('execution_history')]
        values['sdk_cpu_time_ms'] = mean(h['cpu_time_ms'] for h in history) if history else None
        values['sdk_peak_rss_bytes'] = max(h['peak_memory_bytes'] for h in history) if history else None
        values['estimated_cost_usd'] = None
        pairs = []
        for row in completed:
            reference = next((r for r in rows if r['case_id'] == row['case_id'] and r['trial'] == row['trial']
                              and r['method'] == 'omneum' and r['answer_score'] in ('correct', 'incorrect', 'unscored')), None)
            if reference:
                pairs.append(int(reference['answer_score'] == 'correct') - int(row['answer_score'] == 'correct'))
        values['omneum_vs_method'] = {'wins': pairs.count(1), 'losses': pairs.count(-1), 'ties': pairs.count(0)}
        groups[method] = values
    return groups


async def run(args):
    discovered = discover_cases(getattr(args, 'cases_dir', CASES_DIR))
    if args.limit:
        discovered = discovered[:args.limit]
    if args.controls:
        discovered = [v for v in discovered if v[2].case_id in CONTROL_CASES]
    jobs = []
    for case_path, truth_path, case, truth in discovered:
        observations, chunks = mapped_chunks(case)
        variants = [('native', chunks)]
        if args.controls:
            variants = [(p, controlled_chunks(chunks, observations, truth, args.copies, p))
                        for p in ('beginning', 'middle', 'end')]
        for position, original in variants:
            identifier = case.case_id if position == 'native' else f'{case.case_id}--{position}'
            jobs.append((identifier, case, truth, observations, original, position))
    methods = (*ARMS, 'bge_matched') if not args.controls else ARMS
    schedule = []
    for index, (identifier, *_) in enumerate(jobs):
        for trial in range(1, args.trials + 1):
            offset = (index + trial - 1) % len(ARMS)
            for method in (*ARMS[offset:], *ARMS[:offset], *methods[len(ARMS):]):
                schedule.append((identifier, method, trial))
    generator = LocalGenerator(args.model)
    first = jobs[0]
    rank(first[1], first[4], 'embedding')
    rank(first[1], first[4], 'bge')
    inputs = [p.resolve() for entry in discovered for p in entry[:2]]
    metadata = manifest(benchmark='production-prepare-context', track='token-budget', trials=args.trials,
                        context_budget=args.budget, inputs=inputs,
                        models={'generator': args.model, 'embedding': 'all-MiniLM-L6-v2', 'bge': 'BAAI/bge-reranker-v2-m3'},
                        identifier=args.output.name)
    from huggingface_hub.constants import HF_HUB_CACHE
    revisions = {}
    for snapshot in sorted(Path(HF_HUB_CACHE).glob('models--*/snapshots/*')):
        if (snapshot / 'config.json').exists():
            revisions[snapshot.parent.parent.name] = {'revision': snapshot.name,
                'config_sha256': sha256_file(snapshot / 'config.json')}
    contract = {'implementation': implementation_hash(), 'inputs': metadata['inputs'],
                'model': generator.identity, 'options': generator.options, 'budget': args.budget,
                'trials': args.trials, 'controls': args.controls, 'copies': args.copies}
    metadata.update(checkpoint_contract=contract, semantic_model_revisions=revisions, tokenizer=generator.tokenizer_identity,
        generator=generator.identity, options=generator.options,
        estimator_ablation=asdict(no_dependency_estimator()),
        omneum_selection={'strategy': 'coverage_support', 'token_penalty': 0.0, 'semantic_shortlist': False},
        packing='Whole original chunks with [chunk_id] headers; relevance/BGE first-fit descending score; density baseline uses relevance / exact incremental tokens. Ties retain retrieval order.',
        matched='BGE maximum summed relevance among whole-chunk subsets with exactly Omneum actual evidence tokens; unavailable matches are recorded, never approximated.',
        unsupported_annotations=['multi-hop chains', 'necessary exceptions', 'task-completion tools'],
        cost='Local generation; API billing and energy/hardware cost not measured.',
        cache='Models warmed; generator prompt cache uncontrolled. No selection/result reuse across trials. Arm order rotates. Seed 42 and temperature 0.',
        scopes='SDK resources from automatic execution_history; CPU evaluation-only, lifetime process RSS includes loaded baseline models. Harness selection CPU includes all process work. Startup and answer scoring excluded; harness token/evidence checks included in end-to-end.',
        adapter_sha256=sha256_file(Path('research/experiments/applied/agent_dataset/enterprise/local_generator.py')))
    with TrialCheckpoint(args.output, contract, schedule, resume=False) as progress:
        write_manifest(args.output / 'manifest.json', metadata)
        for identifier, case, truth, observations, chunks, position in jobs:
            # Reject overflowing full contexts before either condition executes.
            full = render(chunks)
            templated = generator.request(generator.tokenizer, '/apply-template', {
                'messages': [{'role': 'user', 'content': answer_prompt(case.question, full)}]})['prompt']
            if generator.count(templated) + generator.options['num_predict'] > generator.options['num_ctx']:
                raise ValueError('Full context does not fit; no silent truncation is permitted')
            write_json(args.output / (identifier + '-inputs.json'), {
                'case': asdict(case), 'truth': asdict(truth), 'chunks': chunks,
                'assertion_observations': [asdict(o) for o in observations], 'position': position,
                'context': full, 'input_tokens': generator.count(full)})
        storage = SQLiteStorage(args.output / 'local' / 'omneum.db')
        with benchmark_deployment() as (config, server):
            async with open_stdio_client(config, server, local_persistence=LocalPersistenceConfig(storage)) as client:
                by_id = {j[0]: j for j in jobs}
                for identifier, method, trial in schedule:
                    _, case, truth, observations, chunks, position = by_id[identifier]
                    row = {'case_id': identifier, 'original_case_id': case.case_id, 'domain': case.domain,
                           'position': position, 'method': method, 'trial': trial, 'allocated_budget': None if method == 'full' else args.budget,
                           'estimated_cost_usd': None}
                    started, cpu_started = time.perf_counter(), time.process_time()
                    try:
                        sdk = None
                        if method.startswith('omneum'):
                            sdk = await client.prepare_context(observations, chunks,
                                estimator=no_dependency_estimator() if method.endswith('no_dependency') else estimator_config(),
                                token_budget=args.budget, count_tokens=generator.count,
                                token_counter_name='resident Qwen2.5 tokenizer')
                            context = sdk['context']
                            selected_ids = sdk['packed_chunk_ids']
                            by_chunk = {c['chunk_id']: c for c in chunks}
                            selected = [by_chunk[c] for c in selected_ids]
                            json.dumps(sdk, allow_nan=False)
                            with closing(sqlite3.connect(storage.path)) as db:
                                db.row_factory = sqlite3.Row
                                row['execution_history'] = dict(db.execute('SELECT * FROM execution_history ORDER BY rowid DESC LIMIT 1').fetchone())
                                run_id = row['execution_history']['evaluation_run_id']
                                row['dependency_summary'] = dict(db.execute('SELECT count(*) AS pairs, max(dependency_score) AS max_dependency FROM source_dependencies WHERE evaluation_run_id=?', (run_id,)).fetchone())
                            row['sdk_result'] = sdk
                        elif method == 'full':
                            selected, context = chunks, render(chunks)
                        else:
                            ranking_method = 'bge' if method.startswith('bge') else 'embedding'
                            ranked, ranking_seconds = rank(case, chunks, ranking_method)
                            row['ranked_chunks'] = ranked
                            if method == 'bge_matched':
                                reference = next(r for r in progress.records if r['case_id'] == identifier and r['trial'] == trial and r['method'] == 'omneum')
                                target = reference['selected_tokens']
                                row['allocated_budget'] = target
                                selected = exact_match(ranked, target, generator.count)
                                if selected is None:
                                    row.update(answer_score='not_matched', reason='No whole-chunk subset has exactly the target evidence-token count')
                                    progress.commit(row)
                                    continue
                            elif method == 'relevance_budgeted':
                                selected = density_pack(ranked, args.budget, generator.count)
                            else:
                                selected = pack(ranked, args.budget, generator.count)
                            context = render(selected)
                        row['prepare_seconds'] = time.perf_counter() - started
                        row['harness_selection_cpu_ms'] = (time.process_time() - cpu_started) * 1000
                        row['harness_lifetime_peak_rss_bytes'] = _peak_process_memory_bytes()
                        original_tokens, selected_tokens = generator.count(render(chunks)), generator.count(context)
                        if method != 'full' and selected_tokens > row['allocated_budget']:
                            raise ValueError('Selection exceeded its allocated budget')
                        row.update(context=context, selected=[c['chunk_id'] for c in selected],
                            selected_chunks=selected, input_tokens=original_tokens, selected_tokens=selected_tokens,
                            reduction_ratio=(original_tokens-selected_tokens)/original_tokens if original_tokens else 0,
                            budget_utilization=selected_tokens / row['allocated_budget'] if row['allocated_budget'] else None,
                            **evidence_metrics(case, truth, chunks, selected))
                    except Exception as error:
                        row.update(answer_score='selection_failure', failure_type='selection_failure',
                                   failure_diagnostics=provider_error_diagnostics(error))
                        progress.commit(row)
                        print(identifier, trial, method, row['answer_score'], flush=True)
                        continue
                    try:
                        prompt = answer_prompt(case.question, context)
                        generation = generator.generate(prompt)
                        completed_at = time.perf_counter()
                        response = generation['response']
                        row.update(answer=response['response'], answer_score=score_answer(response['response'], truth),
                            generator_prompt=generation['request']['prompt'], generator_options=generation['request']['options'],
                            generator_input_tokens=response['prompt_eval_count'], generator_output_tokens=response['eval_count'],
                            generation_seconds=generation['seconds'], generator_metadata={k:v for k,v in response.items() if k != 'response'},
                            end_to_end_seconds=completed_at-started)
                    except Exception as error:
                        row.update(answer_score='generation_failure', failure_type='generation_failure',
                                   failure_diagnostics=provider_error_diagnostics(error))
                    progress.commit(row)
                    print(identifier, trial, method, row['answer_score'], flush=True)
        checkpoint(args.output / 'summary.json', [aggregate(progress.records)])
    generator.http.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--cases-dir', type=Path, default=CASES_DIR)
    parser.add_argument('--model', default='qwen2.5:7b')
    parser.add_argument('--budget', type=int, default=128)
    parser.add_argument('--trials', type=int, default=2)
    parser.add_argument('--limit', type=int)
    parser.add_argument('--controls', action='store_true')
    parser.add_argument('--copies', type=int, default=12)
    args = parser.parse_args()
    if args.budget < 0 or args.trials < 1 or args.copies < 0:
        parser.error('budgets/copies must be nonnegative and trials positive')
    asyncio.run(run(args))


if __name__ == '__main__':
    main()
