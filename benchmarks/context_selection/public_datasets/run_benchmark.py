"""Run public pools through the held-out selectors and production raw-claim pipeline."""

import argparse
import asyncio
from dataclasses import asdict
from datetime import datetime, timezone
from importlib.metadata import version
import json
import logging
from jsonschema import validate
from pathlib import Path
from time import perf_counter
from types import SimpleNamespace
from unittest.mock import patch
from uuid import NAMESPACE_URL, uuid5

from omneum import Claim, LocalPersistenceConfig, Observation, Source, coalesce_observations, extract_observations, normalize_observations, open_stdio_client
from omneum.context_selection import claim_id
from omneum.extraction import _extract_with_repair
from omneum.storage import SQLiteStorage
from benchmarks.context_selection import deployment
from benchmarks.context_selection.config import estimator_config
from benchmarks.context_selection.synthetic import prepare_benchmark as base
from benchmarks.context_selection.synthetic.artifacts import checkpoint, write_json
from benchmarks.context_selection.synthetic.checkpoint import implementation_hash
from benchmarks.context_selection.synthetic.release_benchmark import prepare_options
from benchmarks.context_selection.synthetic.selection_frontier import BUDGETS
from benchmarks.context_selection.reproducibility import manifest, sha256_file, write_manifest
from .hotpotqa import score_answer
from .ingestion import ROOT, read_prepared
from .mapping import MAPPING_OUTPUT, PublicGenerator, generate_mapping, response_schema


logger = logging.getLogger(__name__)

EXTRACTION_CONTRACT = 'source-semantic-verified-v2'


def verification_source_hash(include_normalization=True):
    import hashlib
    names = ('extraction.py', '_extraction_verification.py', '_numeric.py')
    if include_normalization:
        names += ('normalization.py',)
    paths = [Path(__file__).resolve().parents[3]/'omneum'/name for name in names]
    return hashlib.sha256(b''.join(p.read_bytes() for p in paths)).hexdigest()


SCIFACT_BUDGETS = (*BUDGETS, 512, 1024)


def budgets_for(dataset, requested=None):
    allowed = SCIFACT_BUDGETS if dataset == 'scifact' else BUDGETS
    return tuple(v for v in (allowed if requested is None else requested) if v in allowed)


METHODS = ('bge', 'bm25', 'embedding', 'omneum', 'bge_omneum', 'bm25_omneum', 'embedding_omneum')


def observation_record(observation):
    # Claim.value is exposed as a property; dataclasses.asdict stores its private bytes.
    return {**asdict(observation), 'claim': {key: getattr(observation.claim, key) for key in
            ('entity_namespace', 'entity', 'attribute', 'value')}}


def observations_from_records(records):
    observations = []
    for saved in records:
        record = dict(saved)
        if any(record[k] is not None for k in ('cited_sources', 'upstream_sources', 'retrievals', 'parent_observation_ids')):
            raise ValueError('saved public observations have unexpected provenance references')
        record['source'] = Source(**record['source'])
        record['claim'] = Claim(**{k: record['claim'][k] for k in ('entity_namespace', 'entity', 'attribute', 'value')})
        for key in ('observed_at', 'source_modified_at'):
            if record[key] is not None:
                record[key] = datetime.fromisoformat(record[key])
        observations.append(Observation(**record))
    return tuple(observations)


def mapped_chunks(case, observations):
    by_chunk = {c['chunk_id']: [] for c in case['chunks']}
    for observation in observations:
        by_chunk[observation.metadata['chunk_id']].append(observation)
    if any(not values for values in by_chunk.values()):
        logger.debug('case=%s stage=mapping event=failed reason=unmapped_passage', case.get('case_id', 'unknown'))
        raise ValueError('production extraction left an unmappable candidate passage')
    logger.debug('case=%s stage=mapping event=completed passages=%d observations=%d',
                 case.get('case_id', 'unknown'), len(by_chunk), len(observations))
    return [dict(chunk_id=c['chunk_id'], document_id=c['document_id'], raw_text=c['raw_text'], source=by_chunk[c['chunk_id']][0].source,
                 claim_ids=sorted({claim_id(o.claim) for o in by_chunk[c['chunk_id']]})) for c in case['chunks']]


def read_preprocessing(directory, case, metadata, generator):
    """Replay real observations with identical inputs/model and valid current schemas."""
    previous = json.loads((directory / 'manifest.json').read_text())
    if (previous.get('extraction_contract') != EXTRACTION_CONTRACT or
            previous.get('semantic_verification_sha256') != verification_source_hash()):
        raise ValueError('saved preprocessing lacks current source-semantic verification')
    if (previous['datasets']['cases_sha256'] != metadata['cases_sha256']
            or previous['generator']['digest'] != generator.identity['digest']
            or previous['generator_options'] != generator.options):
        raise ValueError('saved preprocessing input/model contract mismatch')
    for path in directory.glob('mapping-call-*.json'):
        call = json.loads(path.read_text())
        validate(json.loads(call['response']['response']), response_schema(call['prompt']))
    path = directory / f"{case['dataset']}-{case['case_id']}-trial1-claims.json"
    observations = observations_from_records(json.loads(path.read_text())['observations'])
    rows = [json.loads(line) for line in (directory / 'results.jsonl').read_text().splitlines()]
    original = next(r for r in rows if r['dataset'] == case['dataset'] and r['case_id'] == case['case_id']
                    and r['method'] == 'omneum' and r['preprocessing_failure_stage'] is None)
    diagnostics = original.get('extraction_diagnostics', [])
    if len(diagnostics) != len(case['chunks']) or not all(d.get('verified') for d in diagnostics):
        raise ValueError('saved preprocessing has unverified candidate passages')
    timings = {k: original[k] for k in ('extraction_seconds', 'normalization_seconds')}
    timings.update(stage='mapping', extraction_diagnostics=diagnostics, extraction_validation_retries=original.get('extraction_validation_retries', []),
                   mapping_usage=original['mapping_usage'])
    return tuple(observations), mapped_chunks(case, observations), timings


def semantic_model_revisions():
    from huggingface_hub.constants import HF_HUB_CACHE
    result = {}
    for model in ('BAAI/bge-reranker-v2-m3', 'sentence-transformers/all-MiniLM-L6-v2'):
        cache = Path(HF_HUB_CACHE) / ('models--' + model.replace('/', '--'))
        revision = (cache / 'refs/main').read_text().strip()
        result[model] = dict(revision=revision,
                             config_sha256=sha256_file(cache / 'snapshots' / revision / 'config.json'))
    return result


async def prepare_claims(case, provider, observed_at, timings, extraction_seeds=None,
                         verified_passages=None, record_passage=None):
    """Only public source text and dataset record identity enter extraction."""
    scope = uuid5(NAMESPACE_URL, case['dataset'])
    raw = [dict(id=c['chunk_id'], text=c['raw_text'],
                source=Source('internal_resource', f"v1:{scope}:{uuid5(scope, c['document_id'])}"),
                observed_at=observed_at) for c in case['chunks']]
    started = perf_counter()
    try:
        observations = []
        for chunk in raw:
            logger.debug('passage=%s stage=source_construction event=completed', chunk['id'])
            seed = (extraction_seeds or {}).get(chunk['id'])
            cached = (verified_passages or {}).get(chunk['id'])
            if cached:
                extracted, diagnostics = cached
                diagnostics = {**diagnostics, 'replayed_verified_passage': bool(diagnostics.get('verified'))}
                if any(o.source != chunk['source'] or o.metadata['chunk_id'] != chunk['id'] for o in extracted):
                    raise ValueError('verified passage source association mismatch')
            else:
                extracted, diagnostics = await _extract_with_repair(chunk, provider=provider, verify_semantics=True,
                    **({'initial_response': {'text': seed['response_text']}} if seed else {}))
            if seed:
                diagnostics['candidate_seed'] = {k: v for k, v in seed.items() if k != 'response_text'}
            timings.setdefault('extraction_diagnostics', []).append(dict(chunk_id=chunk['id'], **diagnostics))
            if not diagnostics.get('verified'):
                raise ValueError(f"semantic extraction failed for {chunk['id']}: {diagnostics.get('error')}")
            if not extracted:
                timings['stage'] = 'mapping'
                raise ValueError(f"verified empty extraction cannot map candidate passage {chunk['id']}")
            if record_passage is not None:
                record_passage(chunk, extracted, diagnostics)
            observations.extend(extracted)
        observations = tuple(observations)
    finally:
        timings['extraction_seconds'] = perf_counter() - started
    timings['stage'] = 'normalization'
    original = {o.observation_id: (o.source, o.metadata['chunk_id']) for o in observations}
    started = perf_counter()
    try:
        observations = await normalize_observations(
            observations, provider=provider, chunk_texts={v['id']: v['text'] for v in raw})
        if (len(observations) != len(original) or
                {o.observation_id: (o.source, o.metadata['chunk_id']) for o in observations} != original):
            raise ValueError('normalization changed observation IDs, sources or passage associations')
        timings['observation_count'] = len(observations)
        timings['canonical_claim_count'] = len({claim_id(o.claim) for o in observations})
    finally:
        timings['normalization_seconds'] = perf_counter() - started
    timings['stage'] = 'mapping'
    # The SDK requires at least one mapping per chunk. Never drop unclaimed
    # passages or invent a pseudo-claim to make the selection look successful.
    return observations, mapped_chunks(case, observations)


async def select(case, chunks, observations, client, method, budget, count):
    started = perf_counter()
    ranking_seconds = 0.0
    ranking = chunks
    if method != 'omneum':
        ranking, ranking_seconds = base.rank(SimpleNamespace(question=case['question']), chunks,
                                              method.removesuffix('_omneum'))
    sdk = None
    aliases = None
    if method == 'omneum' or method.endswith('_omneum'):
        graph_observations, aliases = coalesce_observations(observations)
        sdk = await client.prepare_context(
            graph_observations, chunks, estimator=estimator_config(), token_budget=budget,
            count_tokens=count, token_counter_name='resident Qwen2.5 tokenizer',
            include_telemetry=True, include_dependencies=True,
            **prepare_options(method, case['question'], ranking, {}))
        ids = sdk['packed_chunk_ids']
        by_id = {c['chunk_id']: c for c in chunks}
        selected = [by_id[k] for k in ids]
        context = sdk['context']
        if context != base.render(selected):
            raise ValueError('SDK reconstruction changed original passage text or order')
    else:
        selected = base.pack(ranking, budget, count)
        context = base.render(selected)
    if count(context) > budget:
        raise ValueError('selected context exceeds token budget')
    return dict(selected=selected, context=context, sdk_result=sdk,
                graph_observation_aliases=aliases,
                rank_seconds=ranking_seconds, prepare_seconds=perf_counter() - started)


def evidence_metrics(case, selected):
    gold = set(case['relevant_document_ids'])
    retained = {v['document_id'] for v in selected}
    pool = {v['document_id'] for v in case['chunks']}
    return dict(precision=len(retained & gold) / len(retained) if retained else 0.0,
                recall=len(retained & gold) / len(gold),
                pool_recall=len(pool & gold) / len(gold),
                # SciFact qrels are incomplete: unjudged does not mean irrelevant.
                basis='annotated supporting documents; unjudged counted nonrelevant')


def answer_prompt(question, context):
    # Retain the heldout source-only template, adapting only the output format
    # so the official span scorer can grade the entire response.
    return base.answer_prompt(question, context).replace(
        'Give a concise answer and identify which sources support it.',
        'Return only the short answer span (or yes/no). Do not include explanations or source citations.')


async def run(args):
    if not args.output.resolve().is_relative_to(ROOT):
        raise ValueError('run artifacts must remain under public_datasets/')
    if args.trials < 1 or (args.budgets is not None and (not args.budgets or
            len(set(args.budgets)) != len(args.budgets) or any(v not in SCIFACT_BUDGETS for v in args.budgets))):
        raise ValueError('positive trials and published token budgets are required')
    if args.output.exists():
        raise FileExistsError(args.output)
    cases, dataset_manifest = read_prepared(args.prepared)
    cases = [case for case in cases if case['dataset'] in args.datasets]
    if args.preprocessing_from is not None and args.trials != 1:
        raise ValueError('saved preprocessing replay supports one recorded trial only')
    if args.limit_per_dataset:
        cases = [c for name in ('hotpotqa', 'scifact')
                 for c in [v for v in cases if v['dataset'] == name][:args.limit_per_dataset]]
    # Constructing this existing adapter warms Ollama. It runs only on explicit CLI invocation.
    generator = PublicGenerator(args.model)
    observed_at = datetime.now(timezone.utc)
    inputs = [args.prepared / 'cases.jsonl', args.prepared / 'manifest.json']
    if args.preprocessing_from:
        inputs += [args.preprocessing_from / 'manifest.json', args.preprocessing_from / 'results.jsonl']
        inputs += [path for c in cases if (path := args.preprocessing_from /
                   f"{c['dataset']}-{c['case_id']}-trial1-claims.json").is_file()]
    metadata = manifest(benchmark='public-dataset-context-evaluation', track='authentic',
                        trials=args.trials, inputs=inputs,
                        models=dict(generator=args.model, bge='BAAI/bge-reranker-v2-m3',
                                    embedding='all-MiniLM-L6-v2'), identifier=args.output.name)
    metadata.update(extraction_contract=EXTRACTION_CONTRACT, semantic_verification_sha256=verification_source_hash(),
                    datasets=dataset_manifest, methods=METHODS, budgets={name: budgets_for(name, args.budgets) for name in ('hotpotqa', 'scifact')},
                    questions=[(c['dataset'], c['case_id']) for c in cases],
                    implementation=implementation_hash(), daemon_sha256=sha256_file(args.daemon_binary),
                    generator=generator.identity, generator_options=generator.options.copy(),
                    tokenizer=generator.tokenizer_identity, observation_time=observed_at.isoformat(),
                    observation_time_basis='benchmark acquisition time; not source publication time',
                    extraction_options={**generator.options, 'num_predict': MAPPING_OUTPUT,
                                        'format': 'production phase-specific JSON schema'},
                    source_priors=None, dependency_edges='none supplied; provenance unavailable',
                    preprocessing_from=str(args.preprocessing_from) if args.preprocessing_from else None,
                    reuse='Extraction/normalization once per question/trial, shared across Omneum arms/budgets; no gold input.',
                    timing='Selection includes shared extraction/normalization plus rank and SDK/packing. End-to-end adds frozen retrieval and generation. Shared costs charged to each consuming arm.',
                    cost='Local inference; API cost 0 USD; energy/hardware cost not measured',
                    ollama=generator.request(generator.endpoint, '/api/version'),
                    pyarrow_version=version('pyarrow'),
                    grading='HotpotQA v1 normalized EM and token F1; SciFact retrieval-only',
                    sdk_source_ids='UUIDv5 dataset/document adapters, internal_resource kind; not original source URLs or ownership claims',
                    prompt=answer_prompt('{question}', '{context}'))
    metadata['semantic_model_revisions'] = semantic_model_revisions()
    args.output.mkdir(parents=True)
    write_manifest(args.output / 'manifest.json', metadata)
    rows = []

    async def provider(prompt):
        result = generate_mapping(generator, prompt)
        write_json(args.output / f'mapping-call-{len(mapping_calls):06d}.json', dict(prompt=prompt, **result))
        mapping_calls.append(dict(seconds=result['seconds'], input_tokens=result['response']['prompt_eval_count'],
                                  output_tokens=result['response']['eval_count']))
        if result['response'].get('done_reason') == 'length':
            raise ValueError('mapping response exhausted its output-token limit')
        return {'text': result['response']['response']}

    mapping_calls = []
    # Reuse the disposable deployment without its shared target/ Cargo build.
    # This override is scoped to this process; the supplied binary is only read.
    with patch.object(deployment, '_build_daemon', return_value=args.daemon_binary.resolve()):
        with deployment.benchmark_deployment() as (config, server):
            persistence = LocalPersistenceConfig(SQLiteStorage(args.output / 'local' / 'omneum.db'))
            async with open_stdio_client(config, server, local_persistence=persistence) as client:
                for index, case in enumerate(cases):
                    for trial in range(1, args.trials + 1):
                        timings = dict(stage='extraction', extraction_seconds=None, normalization_seconds=None)
                        call_start = len(mapping_calls)
                        error = None
                        reused = bool(args.preprocessing_from and (args.preprocessing_from /
                                      f"{case['dataset']}-{case['case_id']}-trial1-claims.json").is_file())
                        try:
                            if reused:
                                observations, mapped, timings = read_preprocessing(
                                    args.preprocessing_from, case, dataset_manifest, generator)
                            else:
                                observations, mapped = await prepare_claims(case, provider, observed_at, timings)
                        except Exception as exc:
                            chain = []
                            cause = exc
                            while cause is not None:
                                chain.append(f'{type(cause).__name__}: {cause}')
                                cause = cause.__cause__
                            error = ' <- '.join(chain)
                            observations, mapped = (), case['chunks']
                        else:
                            write_json(args.output / f"{case['dataset']}-{case['case_id']}-trial{trial}-claims.json",
                                       dict(observations=[observation_record(v) for v in observations]))
                        offset = (index + trial - 1) % len(METHODS)
                        for budget in budgets_for(case['dataset'], args.budgets):
                            for method in (*METHODS[offset:], *METHODS[:offset]):
                                uses_claims = method == 'omneum' or method.endswith('_omneum')
                                row = dict(dataset=case['dataset'], domain=case['domain'],
                                           case_id=case['case_id'], trial=trial, method=method,
                                           allocated_budget=budget, answer_score='unscored', answer=None,
                                           extraction_seconds=timings['extraction_seconds'] if uses_claims else 0.0,
                                           normalization_seconds=timings['normalization_seconds'] if uses_claims else 0.0,
                                           preprocessing_failure_stage=timings['stage'] if uses_claims and error else None,
                                           extraction_validation_retries=timings.get('extraction_validation_retries', []) if uses_claims else [],
                                           estimated_cost_usd=0.0, retrieval_seconds=case['retrieval_seconds'],
                                           candidate_pool=[v['chunk_id'] for v in case['chunks']],
                                           mapping_usage=mapping_calls[call_start:] if uses_claims else [],
                                           extraction_diagnostics=timings.get('extraction_diagnostics', []) if uses_claims else [])
                                if reused:
                                    row['preprocessing_from'] = str(args.preprocessing_from)
                                    if uses_claims:
                                        row['mapping_usage'] = timings.get('mapping_usage', [])
                                selection_started = perf_counter()
                                try:
                                    if uses_claims and error:
                                        raise ValueError(error)
                                    result = await select(case, mapped if uses_claims else case['chunks'],
                                                          observations, client, method, budget, generator.count)
                                    row.update({k: v for k, v in result.items() if k != 'selected'})
                                    row.update(selected_chunk_ids=[v['chunk_id'] for v in result['selected']],
                                               selected_tokens=generator.count(result['context']),
                                               input_tokens=generator.count(base.render(case['chunks'])),
                                               selection_score=evidence_metrics(case, result['selected']))
                                    row['budget_utilization'] = row['selected_tokens'] / budget
                                    row['selection_seconds'] = row['prepare_seconds'] + row['extraction_seconds'] + row['normalization_seconds']
                                except Exception as exc:
                                    row.update(answer_score='selection_failure', error=f'{type(exc).__name__}: {exc}',
                                               prepare_seconds=perf_counter() - selection_started)
                                    row['selection_seconds'] = row['prepare_seconds'] + sum(
                                        row[v] or 0.0 for v in ('extraction_seconds', 'normalization_seconds'))
                                else:
                                    if case['answer'] is not None:
                                        generation_started = perf_counter()
                                        try:
                                            generated = generator.generate(answer_prompt(case['question'], row['context']))
                                            answer = generated['response']['response']
                                            if not answer.strip():
                                                raise ValueError('empty generator response')
                                            metrics = score_answer(answer, case['answer'])
                                            row.update(answer=answer, answer_metrics=metrics,
                                                       answer_score='correct' if metrics['em'] else 'incorrect',
                                                       generator_input_tokens=generated['response']['prompt_eval_count'],
                                                       generator_output_tokens=generated['response']['eval_count'],
                                                       generation_seconds=generated['seconds'], generation=generated)
                                        except Exception as exc:
                                            row.update(answer_score='generation_failure', error=f'{type(exc).__name__}: {exc}',
                                                       generation_seconds=perf_counter() - generation_started)
                                row['end_to_end_seconds'] = row['retrieval_seconds'] + row['selection_seconds'] + row.get('generation_seconds', 0.0)
                                rows.append(row)
                                checkpoint(args.output / 'results.jsonl', rows)
    from .analysis import summarize
    write_json(args.output / 'summary.json', summarize(rows))
    final_implementation = implementation_hash()
    write_json(args.output / 'completion.json', dict(
        rows=len(rows), implementation=final_implementation,
        implementation_unchanged=final_implementation == metadata['implementation'],
        valid_for_comparison=final_implementation == metadata['implementation'] and args.preprocessing_from is None))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prepared', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--daemon-binary', type=Path, required=True)
    parser.add_argument('--model', default='qwen2.5:7b')
    parser.add_argument('--budgets', nargs='+', type=int, default=None)
    parser.add_argument('--trials', type=int, default=1)
    parser.add_argument('--limit-per-dataset', type=int)
    parser.add_argument('--datasets', nargs='+', choices=('hotpotqa', 'scifact'), default=('hotpotqa', 'scifact'))
    parser.add_argument('--preprocessing-from', type=Path,
                        help='Replay available saved real observations; missing cases run live; original preprocessing latency is charged')
    asyncio.run(run(parser.parse_args()))


if __name__ == '__main__':
    main()
