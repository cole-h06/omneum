"""Checkpoint real source-only preprocessing for the existing public runner."""
from datetime import datetime, timezone
from dataclasses import replace
import hashlib
import json
import logging
from pathlib import Path
from time import perf_counter

from jsonschema import validate
from omneum._extraction_verification import (semantic_request, disputed_coverage,
                                            supported_history, check_coverage, identity_issues)

from benchmarks.context_selection.reproducibility import sha256_file
from benchmarks.context_selection.synthetic.artifacts import write_json
from .mapping import PublicGenerator, generate_mapping, response_schema
from .run_benchmark import (EXTRACTION_CONTRACT, observation_record, observations_from_records,
                            prepare_claims, verification_source_hash)

logger = logging.getLogger(__name__)


def prompt_key(prompt):
    """Keep instructions and array order exact; JSON object key order is immaterial."""
    for marker in ('Input JSON:\n', 'Source text (JSON string):\n'):
        if marker in prompt:
            header, data = prompt.split(marker, 1)
            data = json.loads(data)
            if isinstance(data,dict) and data.get('phase') in ('extraction_verification','missing_verification'):
                data = semantic_request(data)
            prompt = header + marker + json.dumps(data, sort_keys=True, ensure_ascii=False)
            break
    return hashlib.sha256(prompt.encode()).hexdigest()


def cacheable_mapping(prompt):
    """A failed repair proposal is not a checkpoint or an independent decision."""
    if 'Repair request JSON:\n' in prompt:
        return False
    if 'Input JSON:\n' in prompt:
        data = json.loads(prompt.split('Input JSON:\n', 1)[1])
        return data.get('phase') not in ('identity_repair', 'mixed_repair')
    return True


def mapping_cache(directory, generator, *, repair_candidates=False):
    if directory is None:
        return {}
    manifest = json.loads((directory/'manifest.json').read_text())
    if (manifest['generator']['digest'] != generator.identity['digest'] or
            manifest['generator_options'] != generator.options):
        raise ValueError('mapping response cache model/settings mismatch')
    result = {}
    paths = set(directory.glob('mapping-call-*.json'))
    for checkpoint in directory.glob('*-verified.json'):
        for name, digest in json.loads(checkpoint.read_text())['call_sha256'].items():
            path = directory/name
            if sha256_file(path) != digest:
                raise ValueError('cached verification response changed')
            paths.add(path)
    for path in sorted(paths):
        call = json.loads(path.read_text())
        if (call['request'].get('model') != generator.identity['name'] or
                not call['response'].get('done') or call['response'].get('done_reason') == 'length'):
            continue
        validate(json.loads(call['response']['response']), response_schema(call['prompt']))
        if not cacheable_mapping(call['prompt']) and not repair_candidates:
            continue
        result.setdefault(prompt_key(call['prompt']), (call, path, sha256_file(path)))
    return result


def extraction_seeds(directory, case, metadata):
    """Old model output is a candidate input only; all verification runs again."""
    if directory is None:
        return {}
    previous = json.loads((directory/'manifest.json').read_text())
    dataset_hashes = {previous.get('datasets', {}).get('cases_sha256')}
    dataset_hashes.update(digest for name, digest in previous.get('source_sha256', {}).items()
                          if Path(name).name == 'cases.jsonl')
    if metadata['cases_sha256'] not in dataset_hashes:
        raise ValueError('candidate seed dataset mismatch')
    by_text = {c['raw_text']: c['chunk_id'] for c in case['chunks']}
    result = {}
    paths = sorted(directory.glob(f"{case['case_id']}-trial1-mapping-*.json"),
                   key=lambda p: int(p.stem.rsplit('-', 1)[1]))
    if not paths:
        paths = sorted(directory.glob('mapping-call-*.json'))
    # Replayed passages can point to an earlier initial extraction rather than
    # copying that model call into this run. Keep its immutable provenance.
    for pattern in (f"{case['case_id']}-*-verified.json", f"{case['case_id']}-*-failed.json"):
        for checkpoint in sorted(directory.glob(pattern)):
            seed = json.loads(checkpoint.read_text()).get('diagnostics', {}).get('candidate_seed')
            if seed:
                path = Path(seed['path'])
                if (seed['model_digest'] != previous['generator']['digest']
                        or sha256_file(path) != seed['sha256']):
                    raise ValueError('candidate seed provenance mismatch')
                paths.append(path)
    for path in paths:
        record = json.loads(path.read_text())
        prompt = record['prompt']
        if 'Source text (JSON string):\n' not in prompt or 'Repair request JSON:' in prompt:
            continue
        text = json.loads(prompt.split('Source text (JSON string):\n', 1)[1])
        identifier = by_text.get(text)
        if identifier is None or identifier in result:
            continue
        response = record['response']
        if (not response.get('done') or response.get('done_reason') == 'length'
                or record['request']['model'] != previous['generator']['name']):
            raise ValueError('incompatible candidate seed model/response')
        validate(json.loads(response['response']), response_schema(prompt))
        result[identifier] = dict(response_text=response['response'], path=str(path), sha256=sha256_file(path),
                                  model_digest=previous['generator']['digest'], seconds=record['seconds'])
    return result


async def verified_passages(directory, case, metadata, generator, responses=None, *, provider=None):
    if directory is None:
        return {}
    previous = json.loads((directory/'manifest.json').read_text())
    if (previous.get('extraction_contract') != EXTRACTION_CONTRACT or
            previous['datasets']['cases_sha256'] != metadata['cases_sha256'] or
            previous['generator']['digest'] != generator.identity['digest'] or
            previous['generator_options'] != generator.options):
        raise ValueError('verified passage cache contract mismatch')
    result = {}
    for chunk in case['chunks']:
        path = directory/f"{case['case_id']}-{chunk['chunk_id']}-verified.json"
        failed = not path.exists()
        if failed:
            path = directory/f"{case['case_id']}-{chunk['chunk_id']}-failed.json"
            if (not path.exists() or previous.get('passage_verification_sha256') !=
                    verification_source_hash(include_normalization=False)):
                continue
        saved = json.loads(path.read_text())
        if saved['source_sha256'] != hashlib.sha256(chunk['raw_text'].encode()).hexdigest():
            raise ValueError('verified passage text changed')
        diagnostics = saved['diagnostics']
        if failed:
            if (diagnostics.get('verified') is not False or saved.get('observations') != []
                    or diagnostics.get('status') != 'failed_after_retry' or diagnostics.get('retry_count') != 2
                    or [t.get('attempt') for t in diagnostics.get('trace', [])] != [0,1,2]
                    or not saved.get('call_sha256')):
                raise ValueError('invalid bounded passage failure checkpoint')
            for name,digest in saved['call_sha256'].items():
                if sha256_file(directory/name) != digest:
                    raise ValueError('failed passage call artifact changed')
            result[chunk['chunk_id']] = (), {**diagnostics,'replayed_failed_passage':True,
                'cached_call_sha256': {str((directory/name).resolve()):digest
                                      for name,digest in saved['call_sha256'].items()}}
            continue
        if not diagnostics.get('verified'):
            raise ValueError('unverified passage cache')
        if disputed_coverage([dict(diagnostics, chunk_id=chunk['chunk_id'])]):
            logger.debug('passage=%s stage=cache event=skipped reason=disputed_coverage', chunk['chunk_id'])
            continue
        observations = observations_from_records(saved['observations'])
        repaired_ids = {r['observation_id'] for t in diagnostics.get('trace', [])
                        for r in t['structural_rejections'] if 'observation_id' in r
                        and any('source/property' in issue for issue in r.get('issues', []))}
        if any(o.observation_id in repaired_ids and identity_issues(
                dict(entity_namespace=o.claim.entity_namespace,entity=o.claim.entity,
                     attribute=o.claim.attribute),chunk['raw_text']) for o in observations):
            logger.debug('passage=%s stage=cache event=skipped reason=invalid_repaired_identity', chunk['chunk_id'])
            continue
        if not observations:
            logger.debug('passage=%s stage=cache event=skipped reason=empty_observations', chunk['chunk_id'])
            continue
        if any(o.metadata['chunk_id'] != chunk['chunk_id'] for o in observations):
            raise ValueError('invalid cached passage associations')
        # The immutable raw call artifacts remain the evidence for this proof.
        for name, digest in saved['call_sha256'].items():
            if sha256_file(directory/name) != digest:
                raise ValueError('verified passage call artifact changed')
        if previous.get('passage_verification_sha256') != verification_source_hash(include_normalization=False):
            # A repair-only change does not invalidate an unchanged final audit.
            # Reconstruct its original inputs and rerun today's verifier using
            # only actual responses to identical semantic requests/model controls.
            from omneum._extraction_verification import verify_observations
            indexed = {o.observation_id: o for o in observations}
            registry = [replace(indexed[p['observation_id']], metadata={
                **indexed[p['observation_id']].metadata, 'source_span': p['source_span']})
                for p in diagnostics['trace'][-1]['proposed']]
            fresh_requests = 0
            async def replay(prompt):
                nonlocal fresh_requests
                cached = (responses or {}).get(prompt_key(prompt))
                if cached is not None:
                    return {'text': cached[0]['response']['response']}
                if provider is None:
                    raise ValueError('cached verification request changed')
                fresh_requests += 1
                return await provider(prompt)
            checked, audit = await verify_observations(registry, source_text=chunk['raw_text'],
                                                       provider=replay, passage_id=chunk['chunk_id'])
            if (audit['status'] != 'verified' or audit['rejected'] or audit['missing'] or
                    {o.observation_id for o in checked} != set(indexed)):
                logger.debug('passage=%s stage=cache event=skipped reason=verification_changed', chunk['chunk_id'])
                continue
            try:
                missing, coverage = await check_coverage(supported_history(diagnostics), checked,
                                                  chunk['raw_text'], replay, chunk['chunk_id'])
            except (KeyError,TypeError,ValueError):
                missing = [True]
            if missing:
                logger.debug('passage=%s stage=cache event=skipped reason=unproved_coverage',chunk['chunk_id'])
                continue
            observations = checked
            diagnostics = {**diagnostics, 'current_verifier_replayed': True,
                'revalidation_history': [*diagnostics.get('revalidation_history',[]), dict(
                    contract_sha256=verification_source_hash(False),fresh_requests=fresh_requests,
                    verification=audit,coverage_decisions=coverage)]}
        diagnostics = {**diagnostics, 'cached_call_sha256': {
            str((directory/name).resolve()): digest for name, digest in saved['call_sha256'].items()}}
        result[chunk['chunk_id']] = observations, diagnostics
    return result


async def run_preprocessing(args, cases, metadata):
    """Run the production extractor/normalizer, without ranking or generation."""
    seeds_by_case = {case['case_id']: extraction_seeds(args.extraction_from, case, metadata) for case in cases}
    generator = PublicGenerator(args.mapping_model)
    directories = args.verified_passages_from or []
    if isinstance(directories,Path):
        directories = [directories]
    responses = {}
    for directory in directories:
        previous = json.loads((directory/'manifest.json').read_text())
        changed_verifier = previous.get('passage_verification_sha256') != verification_source_hash(False)
        for key,value in mapping_cache(directory,generator,repair_candidates=changed_verifier).items():
            responses.setdefault(key,value)
    args.output.mkdir(parents=True, exist_ok=False)
    inputs = [args.prepared/'cases.jsonl', args.prepared/'manifest.json', Path(__file__),
              Path(__file__).with_name('mapping.py'), Path(__file__).with_name('run_benchmark.py')]
    inputs += [Path(__file__).resolve().parents[3]/'omneum'/name
               for name in ('extraction.py', '_extraction_verification.py', '_numeric.py', 'normalization.py', 'observations.py', 'information.py')]
    if args.extraction_from:
        inputs.append(args.extraction_from/'manifest.json')
    inputs.extend(directory/'manifest.json' for directory in directories)
    manifest = dict(benchmark='public-hotpotqa-preprocessing', extraction_contract=EXTRACTION_CONTRACT,
        semantic_verification_sha256=verification_source_hash(), datasets=metadata,
        passage_verification_sha256=verification_source_hash(include_normalization=False),
        generator=generator.identity, generator_options=generator.options, tokenizer=generator.tokenizer_identity,
        cases=[c['case_id'] for c in cases], source_sha256={str(p): sha256_file(p) for p in inputs},
        extraction_from=str(args.extraction_from) if args.extraction_from else None,
        verified_passages_from=[str(d) for d in directories],
        source_only=True, downstream_generation=False, current_paid_api_spend_usd=0.0)
    write_json(args.output/'manifest.json', manifest)
    calls, rows = [], []
    started = perf_counter()
    try:
        with (args.output/'results.jsonl').open('x') as stream:
            for case in cases:
                timings = dict(stage='extraction', extraction_seconds=None, normalization_seconds=None)
                start_call = len(calls)
                async def provider(prompt):
                    cacheable = cacheable_mapping(prompt)
                    cached = responses.get(prompt_key(prompt)) if cacheable else None
                    replay_started = perf_counter()
                    if cached:
                        saved, origin, digest = cached
                        call = {**{k:v for k,v in saved.items() if k != 'prompt'},
                                'historical_seconds': saved.get('historical_seconds', saved['seconds']),
                                'replayed_from': str(origin), 'replayed_sha256': digest,
                                'seconds': perf_counter()-replay_started}
                    else:
                        call = generate_mapping(generator, prompt)
                    path = args.output/f'mapping-call-{len(calls):06d}.json'
                    write_json(path, dict(prompt=prompt, **call))
                    if cacheable:
                        responses.setdefault(prompt_key(prompt), (dict(prompt=prompt, **call), path, sha256_file(path)))
                    calls.append(dict(path=path.name, seconds=call['seconds'],
                        input_tokens=call['response']['prompt_eval_count'], output_tokens=call['response']['eval_count'],
                        cached=bool(cached), historical_seconds=call.get('historical_seconds')))
                    return {'text': call['response']['response']}
                seeds = seeds_by_case[case['case_id']]
                cached = {}
                for directory in directories:
                    outcomes = await verified_passages(directory,case,metadata,generator,responses,provider=provider)
                    for identifier,outcome in outcomes.items():
                        if identifier not in cached or outcome[1].get('verified'):
                            cached[identifier] = outcome
                def record_passage(chunk, observations, diagnostics):
                    suffix = 'verified' if diagnostics.get('verified') else 'failed'
                    write_json(args.output/f"{case['case_id']}-{chunk['id']}-{suffix}.json", dict(
                        source_sha256=hashlib.sha256(chunk['text'].encode()).hexdigest(), diagnostics=diagnostics,
                        observations=[observation_record(o) for o in observations],
                        call_sha256={**diagnostics.get('cached_call_sha256', {}),
                            **{c['path']: sha256_file(args.output/c['path']) for c in calls[start_call:]}}))
                row = dict(dataset=case['dataset'], case_id=case['case_id'], method='omneum',
                           preprocessing_failure_stage=None, answer_score='unscored')
                try:
                    observations, chunks = await prepare_claims(case, provider, datetime.now(timezone.utc), timings,
                        extraction_seeds=seeds, verified_passages=cached, record_passage=record_passage)
                    write_json(args.output/f"hotpotqa-{case['case_id']}-trial1-claims.json",
                               dict(observations=[observation_record(o) for o in observations]))
                    row.update(observation_count=len(observations), mapped_passages=len(chunks))
                    logger.info('case=%s stage=preprocessing event=completed passages=%d observations=%d',
                                case['case_id'], len(chunks), len(observations))
                except (ValueError, TypeError, RuntimeError) as error:
                    row.update(preprocessing_failure_stage=timings['stage'], error=f'{type(error).__name__}: {error}')
                    if timings['stage'] == 'extraction':
                        for diagnostic in timings.get('extraction_diagnostics',[]):
                            if diagnostic.get('verified') is False and diagnostic.get('retry_count') == 2:
                                raw = next(c for c in case['chunks'] if c['chunk_id'] == diagnostic['chunk_id'])
                                record_passage(dict(id=raw['chunk_id'],text=raw['raw_text']),(),diagnostic)
                    write_json(args.output/f"{case['case_id']}-preprocessing-error.json", dict(**row, timings=timings))
                    logger.info('case=%s stage=%s event=failed error_type=%s',
                                case['case_id'], timings['stage'], type(error).__name__)
                row.update(**timings, mapping_usage=calls[start_call:])
                stream.write(json.dumps(row, allow_nan=False, default=str)+'\n')
                stream.flush()
                rows.append(row)
        changed = [p for p, digest in manifest['source_sha256'].items()
                   if not Path(p).is_file() or sha256_file(Path(p)) != digest]
        write_json(args.output/'completion.json', dict(cases=len(rows),
            verified_cases=sum(r['preprocessing_failure_stage'] is None for r in rows),
            changed_inputs=changed, complete=not changed and all(r['preprocessing_failure_stage'] is None for r in rows),
            wall_seconds=perf_counter()-started, calls=len(calls), current_paid_api_spend_usd=0.0))
    finally:
        generator.http.close()
