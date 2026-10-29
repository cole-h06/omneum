import argparse
import asyncio
from contextlib import closing
from dataclasses import asdict
from functools import lru_cache
import json
from pathlib import Path
import sqlite3
from statistics import mean, median
import time

from omneum import LocalPersistenceConfig, open_stdio_client
from omneum.context_selection import claim_id
from omneum.query_context import _embedding_model
from omneum.storage import SQLiteStorage
from . import prepare_benchmark as base
from .sdk_adapter import observation_chunk_pairs
from .artifacts import checkpoint, write_json
from .checkpoint import TrialCheckpoint, implementation_hash
from .scoring import score_answer
from .selection_frontier import BUDGETS, cache_key, read_rows


METHODS = ('full', 'bge', 'coverage', 'packed', 'query_local', 'query_complement', 'query_full')
ABLATIONS = ('query_density', 'query_anchor1', 'query_anchor5', 'query_depth2',
             'query_no_dependency', 'query_complement_gamma0')
PRIOR = base.RESULTS_DIR / 'prepare-context-v1'
WEIGHTED_PILOT_CASES = (
    'coding_config_conflict', 'coding_package_fix_lineage',
    'research_independent_false_consensus', 'research_conflicting_reports',
    'support_resolution_conflict', 'support_stale_runbook',
)
WEIGHTED_METHODS = ('coverage', 'query_weighted', 'query_weighted_anchors', 'bge')
GATE_METHODS = ('query_gate_none', 'query_gate_threshold', 'query_gate_anchors', 'query_complement', 'bge')
NATIVE_METHODS = ('query_minilm_complement', 'query_bm25_complement', 'query_embedding_complement',
                  'query_bge_complement', 'bm25', 'embedding', 'bge')
RETRIEVERS = {'query_bm25_complement': 'bm25', 'query_embedding_complement': 'embedding',
              'query_bge_complement': 'bge'}


def options(method):
    result = {'strategy': 'coverage_support_packed'}
    if method == 'coverage':
        result['strategy'] = 'coverage_support'
    if method.startswith('query'):
        result.update(anchor_count=3, expansion_depth=1, query_evaluation='local')
        if method == 'query_full':
            result['query_evaluation'] = 'full'
        if method in ('query_complement', 'query_density', 'query_complement_gamma0'):
            result.update(strategy='coverage_support_density', token_cost_exponent=1.0)
        if method in ('query_complement', 'query_complement_gamma0'):
            result['complementary_evidence'] = True
        if method == 'query_complement_gamma0':
            result['token_cost_exponent'] = 0.0
        if method == 'query_anchor1':
            result['anchor_count'] = 1
        if method == 'query_anchor5':
            result['anchor_count'] = 5
        if method == 'query_depth2':
            result['expansion_depth'] = 2
        if method in ('query_weighted', 'query_weighted_anchors'):
            result.update(strategy='coverage_support_query', query_evaluation='full',
                          query_anchoring=method == 'query_weighted_anchors')
        if method in GATE_METHODS and method.startswith('query_gate'):
            result.update(strategy='coverage_support_density', token_cost_exponent=1.0,
                          complementary_evidence=True, query_evaluation='full',
                          query_anchoring=method == 'query_gate_anchors', expansion_depth=2)
            if method == 'query_gate_threshold':
                result['relevance_threshold'] = 0.15
        if method in NATIVE_METHODS:
            result.update(strategy='coverage_support_density', token_cost_exponent=1.0,
                          complementary_evidence=True, query_evaluation='full', expansion_depth=2)
            if method in RETRIEVERS:
                result.update(candidate_discovery='expanded', candidate_count=3)
    return result


def methods_for(args, budget):
    if getattr(args, 'retriever_native', False):
        return list(NATIVE_METHODS)
    if getattr(args, 'gate_ablation', False):
        return list(GATE_METHODS)
    if args.weighted_pilot:
        return list(WEIGHTED_METHODS)
    return [*METHODS, *(ABLATIONS if args.ablations and budget == 128 else ())]


def standalone(method):
    return method in ('full', 'bm25', 'embedding', 'bge')


def inputs(case):
    from .schema import candidate_claims
    observations, chunks = base.mapped_chunks(case)
    by_id = {o.observation_id: o for o in observations}
    texts = {}
    for candidate, chunk in zip(case.candidates, chunks, strict=True):
        specs = candidate_claims(candidate)
        chunk['source'] = by_id[specs[0].observation_id].source
        # Use only the claim's available entity, predicate and value. Gold labels,
        # provenance, document bodies and expected answers do not enter relevance.
        for spec in specs:
            observation = by_id[spec.observation_id]
            texts[claim_id(observation.claim)] = (spec.entity + ' ' + observation.claim.attribute + ': ' +
                                                json.dumps(observation.claim.value, ensure_ascii=False))
    return observations, chunks, texts


@lru_cache(maxsize=None)
def rendered_prompt(generator, prompt):
    return generator.request(generator.tokenizer, '/apply-template', {
        'messages': [{'role': 'user', 'content': prompt}],
    })['prompt']


def history(path):
    with closing(sqlite3.connect(path)) as db:
        db.row_factory = sqlite3.Row
        row = dict(db.execute('SELECT * FROM execution_history ORDER BY rowid DESC LIMIT 1').fetchone())
        independent = db.execute('SELECT o.local_observation_id, cs.independence FROM assertion_observation_envelopes o '
            'JOIN claim_support_sources cs ON o.evaluation_run_id=cs.evaluation_run_id '
            'AND o.source_id=cs.source_id AND o.claim_id=cs.claim_id WHERE o.evaluation_run_id=?',
            (row['evaluation_run_id'],)).fetchall()
    return row, {r['local_observation_id']:r['independence'] for r in independent}


def paired(rows, left, right):
    by_key = {(r['case_id'],r['trial'],r.get('allocated_budget'),r['arm']):r for r in rows}
    differences = []
    for row in rows:
        other = by_key.get((row['case_id'],row['trial'],row.get('allocated_budget'),right))
        if row['arm'] == left and other and row['answer_score'] != 'generation_failure' and other['answer_score'] != 'generation_failure':
            differences.append(int(row['answer_score']=='correct')-int(other['answer_score']=='correct'))
    return {'wins':differences.count(1),'losses':differences.count(-1),'ties':differences.count(0)}


def summarize(rows):
    result = {}
    for budget in sorted({r['allocated_budget'] for r in rows}):
        subset = [r for r in rows if r['allocated_budget']==budget]
        groups = base.aggregate([{**r,'method':r['arm']} for r in subset])
        for arm, values in groups.items():
            selected = [r for r in subset if r['arm']==arm]
            values['median_evidence_tokens'] = median(r['selected_tokens'] for r in selected)
            values['fresh_generations'] = sum(r.get('generation_origin')=='fresh' for r in selected)
            values['all_annotated_supporters_retained'] = mean(r['all_annotated_supporters_retained'] for r in selected)
            for name in ('anchor_recall','expansion_recall','semantic_latency_ms','expansion_latency_ms',
                         'expanded_sources','expanded_claims','expanded_edges','support_max_absolute_change'):
                samples = [r['diagnostics'][name] for r in selected if name in r['diagnostics']]
                values[name] = mean(samples) if samples else None
            for name in ('evaluation_latency_ms','mcp_roundtrip_latency_ms','chunk_selection_latency_ms',
                         'context_reconstruction_latency_ms','local_inference_latency_ms'):
                samples = [r['execution_history'][name] for r in selected if r.get('execution_history') and r['execution_history'].get(name) is not None]
                values[name] = mean(samples) if samples else None
            for name in ('prepare_seconds', 'end_to_end_seconds'):
                samples = sorted(r[name] for r in selected if r.get(name) is not None)
                values[name + '_p50'] = median(samples) if samples else None
                values[name + '_p95'] = samples[max(0, (95 * len(samples) + 99) // 100 - 1)] if samples else None
            values['vs_coverage'] = paired(subset, arm, 'coverage')
            values['vs_packed'] = paired(subset, arm, 'packed')
            values['vs_bge'] = paired(subset, arm, 'bge')
        result[str(budget)] = groups
    return result


async def run(args):
    cases = base.discover_cases(getattr(args, 'cases_dir', base.CASES_DIR))
    if args.weighted_pilot:
        cases = [entry for entry in cases if entry[2].case_id in WEIGHTED_PILOT_CASES]
        if {entry[2].case_id for entry in cases} != set(WEIGHTED_PILOT_CASES):
            raise ValueError('weighted pilot cases are missing')
    cases = cases[:args.limit]
    generator = base.LocalGenerator('qwen2.5:7b')
    count = lru_cache(maxsize=None)(generator.count)
    old_manifest = json.loads((PRIOR/'manifest.json').read_text())
    assert generator.identity['digest'] == old_manifest['generator']['digest']
    assert generator.options == old_manifest['options']
    assert generator.tokenizer_identity['template'] == old_manifest['tokenizer']['template']
    model = _embedding_model()
    schedule = []
    for _,_,case,_ in cases:
        for trial in range(1,args.trials+1):
            for budget in args.budgets:
                methods = methods_for(args, budget)
                # Alternate execution order without changing seeds or prompts.
                if (trial + budget//32) % 2:
                    methods.reverse()
                schedule.extend((case.case_id,f'{method}@{budget}',trial) for method in methods)
    contract = {'implementation':implementation_hash(),'budgets':args.budgets,'trials':args.trials,
                'ablations':args.ablations,'weighted_pilot':args.weighted_pilot,
                'gate_ablation':args.gate_ablation,
                'retriever_native':args.retriever_native,
                'cases':[c.case_id for _,_,c,_ in cases],
                'model':generator.identity,'options':generator.options,'reuse':[str(p) for p in args.reuse]}
    cache = {}
    for origin in [PRIOR,*args.reuse]:
        saved = json.loads((origin/'manifest.json').read_text())
        assert saved['checkpoint_contract']['model']['digest'] == generator.identity['digest']
        assert saved['checkpoint_contract']['options'] == generator.options
        for row in read_rows(origin/'results.jsonl'):
            if row.get('answer_score') in ('correct','incorrect','unscored'):
                case = next((c for _,_,c,_ in cases if c.case_id==row['case_id']),None)
                if case and row.get('generator_options') == generator.options:
                    prompt = base.answer_prompt(case.question, row['context'])
                    if row.get('generator_prompt') != rendered_prompt(generator, prompt):
                        continue
                    key = cache_key(generator.identity['digest'],generator.options,case.question,row['context'],row['trial'])
                    cache.setdefault(key,(row,str(origin/'results.jsonl')))
    with TrialCheckpoint(args.output,contract,schedule) as progress:
        write_json(args.output/'manifest.json',{'checkpoint_contract':contract,'tokenizer':generator.tokenizer_identity,
            'frozen_inputs':{str(p):base.sha256_file(p) for entry in cases for p in entry[:2]},
            'methods':{m:options(m) for m in (NATIVE_METHODS if args.retriever_native else GATE_METHODS if args.gate_ablation else WEIGHTED_METHODS if args.weighted_pilot else (*METHODS,*ABLATIONS))},
            'semantic_model':'sentence-transformers/all-MiniLM-L6-v2; cached 1110a243fdf4706b3f48f1d95db1a4f5529b4d41; CPU',
            'semantic_scores':('MiniLM control: raw claim-text cosine. Native retrievers: raw chunk-text scores; dense ranks condition candidate discovery only, never structural utility.'
                               if args.retriever_native else 'Positive cosine max(0, min(1, cosine)); complete claim mapping; gamma=1, lambda=0; full-graph evaluation.'
                               if args.weighted_pilot else 'Raw normalized cosine; rank descending, ties claim ID; no gold or document body input.'),
            'token_penalty':0.0,'token_counter':'Resident consuming-model tokenizer, exact texts memoized, headers included.',
            'reuse':('Weighted pilot generates both experimental arms fresh; baselines reuse exact model, options, question, context and trial.'
                     if args.weighted_pilot else 'Exact model digest, options, question, context, trial. Reused latency is historical; end-to-end null.'),
            'scope':'Development comparison on previously evaluated frozen cases, not fresh held-out validation.',
            'retriever_protocol': ({'candidate_discovery': 'Top three chunks plus boundary ties; existing bounded depth-two expansion.',
                'normalization': 'Dense ranks of distinct raw scores; higher is better; best=1, worst=0, constant=1.',
                'bm25': 'SDK Okapi BM25 k1=1.5 b=0.75, positive Robertson IDF, Unicode casefolded word tokens.',
                'embedding': 'Existing all-MiniLM-L6-v2 document adapter, raw cosine.',
                'bge': 'Existing BAAI/bge-reranker-v2-m3 adapter, raw cross-encoder score.',
                'minilm_control': 'Existing claim-level semantic anchors; three unique claims, not three chunks.',
                'retrieval_timing': 'One fresh computation per case/provider saved in case retrieval files; reused across all budgets, trials and paired arms.',
                'standalone_packing': 'Whole-chunk first-fit descending relevance; skip candidates that do not fit; exact reconstructed token count.'}
                if args.retriever_native else None),
            'limitations':['Each fixture chunk has one claim and each source asserts one claim; bounded expansion cannot bridge disconnected claims.',
                'Ground truth has supporting-source sets, not independently annotated multi-hop chains or exception passages.',
                'Frozen substring scorer can accept hedged answers or miss correct inflections; raw outputs retained.',
                'Repeated trials use the established same seed42; they are not independent random samples.',
                'Exact-token BGE matching is secondary exhaustive subset selection for these <=10-chunk pools.']})
        storage = SQLiteStorage(args.output/'local'/'omneum.db')
        prepared = {}
        retrieval_cache = {}
        with base.benchmark_deployment() as (config,server):
            async with open_stdio_client(config,server,local_persistence=LocalPersistenceConfig(storage)) as client:
                async def prepare(case, method, budget):
                    observations,chunks,texts = inputs(case)
                    diag = {}
                    settings = options(method)
                    if method.startswith('query'):
                        settings.update(user_query=case.question,claim_texts=texts,semantic_model=model,query_diagnostics=diag)
                    if method in RETRIEVERS:
                        provider = RETRIEVERS[method]
                        ranked, _ = retrieval_cache[(case.case_id, provider)]
                        settings.update(chunk_relevance={c['chunk_id']: c['relevance'] for c in ranked},
                                        relevance_score_type='reranker_score' if provider == 'bge' else 'similarity')
                    started = time.perf_counter()
                    sdk = await client.prepare_context(observations,chunks,
                        estimator=base.no_dependency_estimator() if method=='query_no_dependency' else base.estimator_config(),
                        token_budget=budget,count_tokens=count,token_counter_name='resident Qwen2.5 tokenizer; memoized exact texts',
                        **settings)
                    seconds = time.perf_counter()-started
                    json.dumps(sdk,allow_nan=False)
                    by_id = {c['chunk_id']:c for c in chunks}
                    selected = [by_id[k] for k in sdk['packed_chunk_ids']]
                    assert sdk['context'] == base.render(selected)
                    assert count(sdk['context']) == sdk['selection']['selected_tokens'] <= budget
                    record,weights = history(storage.path)
                    return sdk, selected, seconds, diag, record, weights

                # Freeze all candidate graphs and selections before generating
                # answers. Gold annotations evaluate recall; they never seed it.
                for _,_,case,truth in cases:
                    observations,chunks,texts = inputs(case)
                    write_json(args.output/(case.case_id+'-inputs.json'),{'case':asdict(case),'truth':asdict(truth),
                        'assertion_observations':[asdict(o) for o in observations],
                        'chunks':[{k:v for k,v in c.items() if k!='source'} for c in chunks],'claim_texts':texts})
                    required = {claim for c in chunks if c['source_id'] in truth.supporting_sources for claim in c['claim_ids']}
                    ranked,rank_seconds = base.rank(case,chunks,'bge')
                    retrieval_cache[(case.case_id, 'bge')] = (ranked, rank_seconds)
                    if args.retriever_native:
                        measurements = {}
                        for provider in ('bm25', 'embedding', 'bge'):
                            if provider != 'bge':
                                retrieval_cache[(case.case_id, provider)] = base.rank(case, chunks, provider)
                            ranking, seconds = retrieval_cache[(case.case_id, provider)]
                            measurements[provider] = {'raw_scores': {c['chunk_id']: c['relevance'] for c in ranking},
                                'ranking': [c['chunk_id'] for c in ranking], 'fresh_retrieval_seconds': seconds,
                                'scope': 'One actual scoring computation on the complete case pool; shared across budgets, trials and arms.'}
                        write_json(args.output/(case.case_id+'-retrieval.json'), measurements)
                    full_support = None
                    full_evaluation = None
                    full_weights = None
                    for trial in range(1,args.trials+1):
                        for budget in args.budgets:
                            methods = methods_for(args, budget)
                            for method in methods:
                                diag,record,sdk,weights = {},None,None,{}
                                if standalone(method):
                                    started = time.perf_counter()
                                    ranking = retrieval_cache[(case.case_id, method)][0] if method != 'full' else chunks
                                    selected = chunks if method=='full' else base.pack(ranking,budget,count)
                                    context = base.render(selected)
                                    seconds = time.perf_counter()-started
                                    if not args.retriever_native and method == 'bge':
                                        seconds += rank_seconds
                                else:
                                    sdk,selected,seconds,diag,record,weights = await prepare(case,method,budget)
                                    context = sdk['context']
                                    if method in ('coverage', 'query_gate_none', 'query_minilm_complement'):
                                        full_support = sdk['evaluation']['claim_support']
                                        full_evaluation = sdk['evaluation']
                                        full_weights = weights
                                    if method.startswith('query_gate') or method in RETRIEVERS:
                                        assert diag['fallback_reason'] is None
                                        assert sdk['evaluation'] == full_evaluation
                                        assert weights == full_weights
                                    if method.startswith('query'):
                                        diag['anchor_recall'] = len(required & set(diag['anchor_claim_ids']))/len(required)
                                        diag['expansion_recall'] = len(required & set(diag['expanded_claim_ids']))/len(required)
                                        support = sdk['evaluation']['claim_support']
                                        diag['support_max_absolute_change'] = max((abs(v-full_support[k]) for k,v in support.items()),default=0)
                                original_tokens,selected_tokens = count(base.render(chunks)),count(context)
                                row = {'case_id':case.case_id,'method':f'{method}@{budget}','arm':method,'trial':trial,
                                    'allocated_budget':budget,'input_tokens':original_tokens,'selected_tokens':selected_tokens,
                                    'context':context,'selected':[c['chunk_id'] for c in selected],
                                    'selected_chunks':[{k:v for k,v in c.items() if k!='source'} for c in selected],
                                    'prepare_seconds':seconds,'diagnostics':diag,'execution_history':record,'sdk_result':sdk,
                                    'reduction_ratio':(original_tokens-selected_tokens)/original_tokens,
                                    'budget_utilization':selected_tokens/budget if method!='full' else None,
                                    'represented_independence_mass':sum(weights.get(o.observation_id,0) for o,c in observation_chunk_pairs(observations, chunks, case) if c['chunk_id'] in {x['chunk_id'] for x in selected}) if record else None,
                                    **base.evidence_metrics(case,truth,chunks,selected)}
                                if args.gate_ablation or args.retriever_native:
                                    selected_ids = set(row['selected'])
                                    supporter_ids = {c['chunk_id'] for c in chunks if c['source_id'] in truth.supporting_sources}
                                    retained = selected_ids & supporter_ids
                                    # An annotation maps a claim to a passage, not every
                                    # instruction needed to act on it. Keep passage IDs
                                    # separately so raw-text sufficiency can be inspected.
                                    row['annotated_supporter_passages_retained'] = sorted(retained)
                                    row['annotated_supporter_passages_missing'] = sorted(supporter_ids - retained)
                                    row['annotated_supporter_text_fraction'] = len(retained) / len(supporter_ids)
                                    assert all(by['raw_text'] in context for by in chunks if by['chunk_id'] in retained)
                                    reference_weights = full_weights
                                    row['independence_by_observation'] = reference_weights
                                    row['independence_reference'] = 'query_minilm_complement' if args.retriever_native else 'query_gate_none'
                                    total_mass = 0.0
                                    retained_mass = 0.0
                                    for observation, chunk in observation_chunk_pairs(observations, chunks, case):
                                        if chunk['chunk_id'] in supporter_ids:
                                            weight = reference_weights[observation.observation_id]
                                            total_mass += weight
                                            if chunk['chunk_id'] in retained:
                                                retained_mass += weight
                                    row['annotated_supporter_independence_coverage'] = retained_mass / total_mass
                                if args.retriever_native:
                                    provider = RETRIEVERS.get(method, method if standalone(method) else None)
                                    row['relevance_origin'] = 'cached_case_retrieval' if provider else 'sdk_local_minilm_claims'
                                    row['retrieval_computation_id'] = case.case_id + ':' + provider if provider else None
                                    row['fresh_retrieval_seconds'] = 0.0
                                    row['end_to_end_scope'] = 'cached relevance, preparation, prompt validation and generation'
                                prepared[(case.case_id,row['method'],trial)] = row
                            # Compare BGE at exactly the query-local consumption
                            # when whole original chunks permit that token total.
                            if args.weighted_pilot or args.gate_ablation or args.retriever_native:
                                continue
                            target = prepared[(case.case_id,f'query_local@{budget}',trial)]['selected_tokens']
                            matched_started = time.perf_counter()
                            match = base.exact_match(ranked,target,count)
                            matched_seconds = time.perf_counter()-matched_started+rank_seconds
                            if match is not None:
                                template = prepared[(case.case_id,f'bge@{budget}',trial)]
                                matched = {**template,'method':f'bge_matched@{budget}','arm':'bge_matched',
                                    'context':base.render(match),'selected':[c['chunk_id'] for c in match],
                                    'selected_chunks':[{k:v for k,v in c.items() if k!='source'} for c in match],
                                    'selected_tokens':target,'reduction_ratio':(original_tokens-target)/original_tokens,
                                    'budget_utilization':target/budget,'matched_target':'query_local','prepare_seconds':matched_seconds,
                                    **base.evidence_metrics(case,truth,chunks,match)}
                                prepared[(case.case_id,matched['method'],trial)] = matched
                    print('selected',case.case_id,flush=True)
                checkpoint(args.output/'selections.jsonl',list(prepared.values()))
                write_json(args.output/'selection_summary.json',{'sha256':base.sha256_file(args.output/'selections.jsonl'),
                    'frozen_before_generation':True,'tokenizer_cache':count.cache_info()._asdict(),
                    'matched_bge_available':sum(r['arm']=='bge_matched' for r in prepared.values())})
                # Matched comparisons run as a separate schedule to keep the
                # primary seven-arm checkpoint and its continuation unambiguous.
                generation_rows = []
                for key in schedule:
                    row = prepared[key]
                    case,truth = next((c,t) for _,_,c,t in cases if c.case_id==row['case_id'])
                    key_digest = cache_key(generator.identity['digest'],generator.options,case.question,row['context'],row['trial'])
                    cached = cache.get(key_digest)
                    if args.weighted_pilot and row['arm'].startswith('query'):
                        # Fresh experimental responses provide contiguous SDK-to-
                        # generation timing; baseline reuse stays explicitly marked.
                        cached = None
                    started = time.perf_counter()
                    try:
                        # Fresh wall time includes recomputed preparation; the
                        # resulting context must match the frozen selection.
                        if standalone(row['arm']):
                            _,chunks,_ = inputs(case)
                            if row['arm']!='full':
                                if args.retriever_native:
                                    ranked,_ = retrieval_cache[(case.case_id, row['arm'])]
                                else:
                                    ranked,_ = base.rank(case,chunks,row['arm'])
                                selected = base.pack(ranked,row['allocated_budget'],count)
                            else:
                                selected = chunks
                            assert base.render(selected)==row['context']
                            row['prepare_seconds'] = time.perf_counter()-started
                        else:
                            sdk,selected,seconds,diag,record,_ = await prepare(case,row['arm'],row['allocated_budget'])
                            assert sdk == row['sdk_result']
                            row.update(prepare_seconds=seconds,execution_history=record)
                        if cached:
                            original,origin = cached
                            row.update({k:original[k] for k in ('answer','generator_input_tokens','generator_output_tokens',
                                'generation_seconds','generator_prompt','generator_options','generator_metadata')})
                            row.update(generation_origin='reused',reused_from={'path':origin,'method':original['method'],
                                'case_id':original['case_id'],'trial':original['trial']},end_to_end_seconds=None)
                        else:
                            generation = generator.generate(base.answer_prompt(case.question,row['context']))
                            response = generation['response']
                            row.update(answer=response['response'],generator_input_tokens=response['prompt_eval_count'],
                                generator_output_tokens=response['eval_count'],generation_seconds=generation['seconds'],
                                generator_prompt=generation['request']['prompt'],generator_options=generation['request']['options'],
                                generator_metadata={k:v for k,v in response.items() if k!='response'},generation_origin='fresh',
                                end_to_end_seconds=time.perf_counter()-started)
                            cache[key_digest] = (dict(row),str(args.output/'results.jsonl'))
                        row['answer_score'] = score_answer(row['answer'],truth)
                    except Exception as error:
                        row.update(answer_score='generation_failure',failure_type='generation_failure',
                                   failure_diagnostics=base.provider_error_diagnostics(error))
                    progress.commit(row)
                    generation_rows.append(row)
                    print(row['case_id'],row['method'],row['trial'],row['answer_score'],row.get('generation_origin'),flush=True)
                matched_rows = []
                for row in prepared.values():
                    if row['arm']!='bge_matched':continue
                    case,truth = next((c,t) for _,_,c,t in cases if c.case_id==row['case_id'])
                    key_digest = cache_key(generator.identity['digest'],generator.options,case.question,row['context'],row['trial'])
                    cached = cache.get(key_digest)
                    try:
                        if cached:
                            original,origin = cached
                            row.update({k:original[k] for k in ('answer','generator_input_tokens','generator_output_tokens',
                                'generation_seconds','generator_prompt','generator_options','generator_metadata')})
                            row.update(generation_origin='reused',reused_from=origin,end_to_end_seconds=None)
                        else:
                            generation = generator.generate(base.answer_prompt(case.question,row['context']))
                            response = generation['response']
                            row.update(answer=response['response'],generator_input_tokens=response['prompt_eval_count'],
                                generator_output_tokens=response['eval_count'],generation_seconds=generation['seconds'],
                                generator_prompt=generation['request']['prompt'],generator_options=generation['request']['options'],
                                generator_metadata={k:v for k,v in response.items() if k!='response'},generation_origin='fresh',
                                end_to_end_seconds=None,
                                preparation_plus_generation_seconds=row['prepare_seconds']+generation['seconds'])
                            cache[key_digest] = (dict(row),str(args.output/'matched.jsonl'))
                        row['answer_score'] = score_answer(row['answer'],truth)
                    except Exception as error:
                        row.update(answer_score='generation_failure',failure_diagnostics=base.provider_error_diagnostics(error))
                    matched_rows.append(row)
                    checkpoint(args.output/'matched.jsonl',matched_rows)
                write_json(args.output/'summary.json',summarize([*generation_rows,*matched_rows]))
    generator.http.close()


async def run_matched(args):
    source = args.matched_from
    retriever = args.matched_retriever
    source_manifest = json.loads((source/'manifest.json').read_text())
    generator = base.LocalGenerator('qwen2.5:7b')
    assert generator.identity['digest'] == source_manifest['checkpoint_contract']['model']['digest']
    assert generator.options == source_manifest['checkpoint_contract']['options']
    assert generator.tokenizer_identity['template'] == source_manifest['tokenizer']['template']
    count = lru_cache(maxsize=None)(generator.count)
    cases = {c.case_id:(c,t) for _,_,c,t in base.discover_cases(getattr(args, 'cases_dir', base.CASES_DIR))}
    targets = [r for r in read_rows(source/'selections.jsonl') if r['arm'] in args.matched_arms]
    if not targets or {r['arm'] for r in targets} != set(args.matched_arms):
        raise ValueError('requested matching arms are missing')
    for row in targets:
        row['matched_arm'] = retriever + '_matched' if args.matched_arms == ['query_complement'] else retriever + '_matched_' + row['arm']
    schedule = [(r['case_id'],f"{r['matched_arm']}@{r['allocated_budget']}",r['trial']) for r in targets]
    cache = {}
    paths = [source/'results.jsonl', source/'matched.jsonl', PRIOR/'results.jsonl']
    for origin in args.reuse:
        saved = json.loads((origin/'manifest.json').read_text())
        assert saved['checkpoint_contract']['model']['digest'] == generator.identity['digest']
        assert saved['checkpoint_contract']['options'] == generator.options
        paths.append(origin/'results.jsonl')
    for path in paths:
        if not path.exists():
            continue
        for row in read_rows(path):
            case,_ = cases[row['case_id']]
            if row.get('generator_options') != generator.options or row.get('generator_prompt') != rendered_prompt(generator, base.answer_prompt(case.question, row['context'])):
                continue
            key = cache_key(generator.identity['digest'],generator.options,case.question,row['context'],row['trial'])
            cache.setdefault(key,(row,str(path)))
    contract = {'implementation':implementation_hash(),'parent':str(source),
                'target':args.matched_arms, 'retriever':retriever, 'reuse':[str(p) for p in args.reuse],
                'model':generator.identity,'options':generator.options}
    with TrialCheckpoint(args.output,contract,schedule) as progress:
        write_json(args.output/'manifest.json',{'checkpoint_contract':contract,
            'parent_implementation':source_manifest['checkpoint_contract']['implementation'],
            'tokenizer':generator.tokenizer_identity,'frozen_inputs':source_manifest['frozen_inputs'],
            'production_sha256':{str(p):base.sha256_file(p) for p in (Path('omneum/client.py'),Path('omneum/context_selection.py'),Path('omneum/query_context.py'))},
            'control':f'Additional exact-token {retriever} comparison; original chunks in relevance order, maximum total relevance at the exact target token count. No ground truth used.'})
        prepared = []
        retrieval_measurements = {}
        for case_id in dict.fromkeys(r['case_id'] for r in targets):
            case,truth = cases[case_id]
            _,chunks,_ = inputs(case)
            ranking_path = source / (case_id + '-retrieval.json')
            if ranking_path.is_file():
                saved = json.loads(ranking_path.read_text())[retriever]
                by_id = {chunk['chunk_id']: chunk for chunk in chunks}
                assert set(saved['ranking']) == set(saved['raw_scores']) == set(by_id)
                ranked = [{**by_id[key], 'relevance': saved['raw_scores'][key]} for key in saved['ranking']]
                retrieval_measurements[case_id] = {'origin': str(ranking_path), 'fresh_retrieval_seconds': 0.0}
            else:
                ranked,ranking_seconds = base.rank(case,chunks,retriever)
                retrieval_measurements[case_id] = {'origin': 'fresh_case_scoring', 'fresh_retrieval_seconds': ranking_seconds}
            for target in targets:
                if target['case_id']!=case_id:continue
                started = time.perf_counter()
                selected = base.exact_match(ranked,target['selected_tokens'],count)
                if selected is None:
                    prepared.append({'case_id':case_id,'method':f"{target['matched_arm']}@{target['allocated_budget']}",
                        'arm':target['matched_arm'],'trial':target['trial'],'allocated_budget':target['allocated_budget'],
                        'matched_target':target['arm'],
                        'answer_score':'not_matched','requested_evidence_tokens':target['selected_tokens'],
                        'reason':f'No exact whole-chunk subset in {retriever} rendering order.'})
                    continue
                context = base.render(selected)
                prepared.append({'case_id':case_id,'method':f"{target['matched_arm']}@{target['allocated_budget']}",
                    'arm':target['matched_arm'],'trial':target['trial'],'allocated_budget':target['allocated_budget'],
                    'matched_target':target['arm'],'selected_tokens':count(context),'input_tokens':target['input_tokens'],
                    'selected':[c['chunk_id'] for c in selected],'context':context,
                    'selected_chunks':[{k:v for k,v in c.items() if k!='source'} for c in selected],
                    'prepare_seconds':time.perf_counter()-started,
                    'preparation_scope':'Exact-token packing only; case scoring is recorded once in retrieval_measurements.json.',
                    'relevance_origin':'shared_case_scores', 'fresh_retrieval_seconds':0.0,
                    'budget_utilization':count(context)/target['allocated_budget'],
                    'reduction_ratio':(target['input_tokens']-count(context))/target['input_tokens'],
                    'diagnostics':{},'execution_history':None,**base.evidence_metrics(case,truth,chunks,selected)})
        write_json(args.output/'retrieval_measurements.json',retrieval_measurements)
        checkpoint(args.output/'selections.jsonl',prepared)
        write_json(args.output/'selection_summary.json',{'sha256':base.sha256_file(args.output/'selections.jsonl'),
                   'frozen_before_generation':True,'exact_matches':sum(r.get('answer_score')!='not_matched' for r in prepared)})
        for row in prepared:
            if row.get('answer_score')=='not_matched':
                progress.commit(row)
                print(row['case_id'],row['method'],row['trial'],'not_matched',flush=True)
                continue
            case,truth = cases[row['case_id']]
            key = cache_key(generator.identity['digest'],generator.options,case.question,row['context'],row['trial'])
            cached = cache.get(key)
            try:
                if cached:
                    original,origin = cached
                    row.update({k:original[k] for k in ('answer','generator_input_tokens','generator_output_tokens',
                        'generation_seconds','generator_prompt','generator_options','generator_metadata')})
                    row.update(generation_origin='reused',reused_from=origin,end_to_end_seconds=None)
                else:
                    generation = generator.generate(base.answer_prompt(case.question,row['context']))
                    response = generation['response']
                    row.update(answer=response['response'],generator_input_tokens=response['prompt_eval_count'],
                        generator_output_tokens=response['eval_count'],generation_seconds=generation['seconds'],
                        generator_prompt=generation['request']['prompt'],generator_options=generation['request']['options'],
                        generator_metadata={k:v for k,v in response.items() if k!='response'},generation_origin='fresh',
                        end_to_end_seconds=None)
                    cache[key] = (dict(row),str(args.output/'results.jsonl'))
                row['answer_score'] = score_answer(row['answer'],truth)
                row['preparation_plus_generation_seconds'] = row['prepare_seconds']+row['generation_seconds']
            except Exception as error:
                row.update(answer_score='generation_failure',failure_diagnostics=base.provider_error_diagnostics(error))
            progress.commit(row)
            print(row['case_id'],row['method'],row['trial'],row['answer_score'],row.get('generation_origin'),flush=True)
        write_json(args.output/'summary.json',{
            'executed':summarize([r for r in progress.records if r['answer_score']!='not_matched']),
            'not_matched':[r for r in progress.records if r['answer_score']=='not_matched']})
    generator.http.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--cases-dir', type=Path, default=base.CASES_DIR)
    parser.add_argument('--budgets',type=int,nargs='+',default=list(BUDGETS))
    parser.add_argument('--limit',type=int,default=24)
    parser.add_argument('--trials',type=int,default=2)
    parser.add_argument('--ablations',action='store_true')
    parser.add_argument('--weighted-pilot',action='store_true')
    parser.add_argument('--gate-ablation',action='store_true')
    parser.add_argument('--retriever-native',action='store_true')
    parser.add_argument('--matched-from',type=Path)
    parser.add_argument('--matched-arms',nargs='+',default=['query_complement'])
    parser.add_argument('--matched-retriever',choices=('bm25', 'embedding', 'bge'),default='bge')
    parser.add_argument('--reuse',type=Path,nargs='*',default=[])
    args = parser.parse_args()
    if args.trials<1 or args.limit<1 or any(b<=0 for b in args.budgets):parser.error('positive limits required')
    if args.gate_ablation and (args.weighted_pilot or args.ablations):
        parser.error('gate ablation must run separately')
    if args.retriever_native and (args.gate_ablation or args.weighted_pilot or args.ablations):
        parser.error('retriever comparison must run separately')
    asyncio.run(run_matched(args) if args.matched_from else run(args))


if __name__=='__main__':main()
