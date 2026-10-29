"""Full source-only normalization study; never generates downstream answers."""
import argparse
import asyncio
from collections import Counter, defaultdict
from dataclasses import replace
from functools import lru_cache
import hashlib
import json
from pathlib import Path
from statistics import mean, median
import time
import tempfile

import httpx

from omneum import Claim, coalesce_observations, extract_observations, normalize_observations
from omneum.normalization import align_claim_properties
from omneum.client import _evaluate_context
from omneum.context_selection import claim_id, map_chunks, reconstruct_context, reconstruct
from omneum.query_context import normalize_chunk_relevance, source_key
from .atomic_mapping_comparison import SCHEMA, observation_json, write_new
from .investigate_question_release import BASELINE, ROOT, read_rows
from .loader import load_case, load_ground_truth
from .sdk_adapter import build_observations
from .scoring import score_selection
from ..config import estimator_config


def graph_view(occurrences):
    """Keep all occurrence IDs in the registry; coalesce only graph edges."""
    return coalesce_observations(occurrences)


def load_occurrences(case, data):
    source_rows, _ = build_observations(case)
    by_chunk = {'chunk-' + c.source_id: o for c, o in zip(case.candidates, source_rows, strict=True)}
    return tuple(replace(by_chunk[item['metadata']['chunk_id']], observation_id=item['observation_id'],
        claim=Claim(**item['claim']), metadata=item['metadata'],
        parent_observation_ids=None if item['parent_observation_ids'] is None else tuple(item['parent_observation_ids']))
        for item in data)


def chunks_for(case, occurrences):
    original, _ = build_observations(case)
    grouped = defaultdict(set)
    for o in occurrences:
        grouped[o.metadata['chunk_id']].add(claim_id(o.claim))
    chunks = [dict(chunk_id='chunk-' + c.source_id, raw_text=c.text, source=o.source,
                   source_id=c.source_id, claim_ids=sorted(grouped['chunk-' + c.source_id]))
              for c, o in zip(case.candidates, original, strict=True)]
    map_chunks(chunks, {claim_id(o.claim) for o in occurrences})
    return chunks


def identity_stats(occurrences):
    claims = defaultdict(set)
    props = defaultdict(set)
    by_chunk = defaultdict(set)
    for o in occurrences:
        c = o.claim
        claims[claim_id(c)].add(source_key(o.source))
        props[c.entity_namespace, c.entity.casefold().strip(), c.attribute].add(claim_id(c))
        by_chunk[o.metadata['chunk_id']].add(claim_id(c))
    return dict(occurrences=len(occurrences), distinct_claims=len(claims),
        repeated_claim_occurrences=len(occurrences) - len(claims),
        claims_shared_across_sources=sum(len(s) > 1 for s in claims.values()),
        conflicting_properties=sum(len(v) > 1 for v in props.values()),
        occurrence_counts_per_chunk=dict(Counter(o.metadata['chunk_id'] for o in occurrences)),
        claims_per_chunk={k: len(v) for k, v in by_chunk.items()})


async def prepare(args):
    args.output.mkdir(parents=True, exist_ok=False)
    baseline = json.loads((BASELINE / 'manifest.json').read_text())
    async with httpx.AsyncClient(trust_env=False, timeout=300) as http:
        models = (await http.get('http://127.0.0.1:11434/api/tags')).raise_for_status().json()['models']
        model = next(m for m in models if m['name'] == 'qwen2.5:7b')
        assert model['digest'] == baseline['generator']['digest']
        info = (await http.post('http://127.0.0.1:11434/api/show', json={'model': model['name']})).raise_for_status().json()
        assert not info.get('remote_host') and not info.get('remote_model')
        write_new(args.output / 'manifest.json', dict(cases=baseline['cases'], model=model,
            scope='Source-only extraction and batch normalization; no questions, gold or answer generation',
            extraction_options=dict(seed=42, temperature=0, num_ctx=8192, num_predict=768),
            normalization_options=dict(seed=42, temperature=0, num_ctx=8192, num_predict=4096)))
        cache = {}
        for path in (ROOT / 'analysis/atomic-mapping-v1/extraction-v2').glob('*provider-*.json'):
            saved = json.loads(path.read_text())
            cache[saved['prompt']] = (saved, str(path))
        for path in (ROOT / 'analysis/normalization-v1/prepared').glob('*-extract-*.json'):
            saved = json.loads(path.read_text())
            cache[saved['prompt']] = (saved, str(path))
        for path in (ROOT / 'analysis/normalization-v2/prepared').glob('*-extract-*.json'):
            saved = json.loads(path.read_text())
            cache[saved['prompt']] = (saved, str(path))
        for path in (ROOT / 'analysis/normalization-v3/prepared').glob('*-extract-*.json'):
            saved = json.loads(path.read_text())
            cache[saved['prompt']] = (saved, str(path))
        normalization_cache = {}
        for folder in ('normalization-v1', 'normalization-v2'):
            for path in (ROOT / 'analysis' / folder / 'prepared').glob('*normalize-provider*.json'):
                saved = json.loads(path.read_text())
                if 'phase' not in json.loads(saved['prompt'].rsplit('Input JSON:\n', 1)[1]):
                    normalization_cache[saved['prompt']] = (saved, str(path))
        for case_id in baseline['cases']:
            case = load_case(ROOT / 'cases' / case_id / 'case.json')
            original, _ = build_observations(case)
            anchors = tuple(replace(o, claim=Claim(c.entity_namespace, c.entity, c.attribute, c.value),
                metadata={**o.metadata, 'chunk_id': 'chunk-' + c.source_id})
                for c, o in zip(case.candidates, original, strict=True))
            facts = []
            extraction_records = []
            for c, anchor in zip(case.candidates, anchors, strict=True):
                key = 'chunk-' + c.source_id
                async def provider(prompt):
                    started = time.perf_counter()
                    if prompt in cache:
                        saved, origin = cache[prompt]
                        response = saved['response']
                        seconds = saved['seconds']
                    else:
                        origin = None
                        response = (await http.post('http://127.0.0.1:11434/api/generate', json={
                            'model': model['name'], 'prompt': prompt, 'format': SCHEMA, 'stream': False,
                            'options': dict(seed=42, temperature=0, num_ctx=8192, num_predict=768),
                            'keep_alive': '30m'})).raise_for_status().json()
                        seconds = time.perf_counter() - started
                    record = dict(chunk_id=key, prompt=prompt, response=response, seconds=seconds, reused_from=origin)
                    extraction_records.append(record)
                    write_new(args.output / f'{case_id}-extract-{len(extraction_records):02d}.json', record)
                    if not response.get('done') or response.get('done_reason') == 'length':
                        raise ValueError('truncated extraction')
                    return {'text': response['response']}
                try:
                    extracted = await extract_observations([dict(id=key, source=anchor.source, text=c.text,
                        observed_at=anchor.observed_at)], provider=provider)
                    facts.extend(replace(anchor, observation_id=o.observation_id, claim=o.claim, metadata=o.metadata)
                                 for o in extracted)
                    extraction_records[-1]['status'] = 'nonempty' if extracted else 'empty'
                except (ValueError, TypeError) as error:
                    extraction_records[-1]['status'] = 'failure'
                    extraction_records[-1]['error'] = str(error)
                print('extracted', case_id, len(extraction_records), extraction_records[-1]['status'], flush=True)
            raw = (*anchors, *facts)
            texts = {'chunk-' + c.source_id: c.text for c in case.candidates}
            normalization_records = []
            async def normalize_provider(prompt):
                started = time.perf_counter()
                request_data = json.loads(prompt.rsplit('Input JSON:\n', 1)[1])
                n = len(request_data.get('observations', []))
                if request_data.get('phase') == 'verify':
                    schema = dict(type='object', properties=dict(equivalent=dict(type='boolean')),
                                  required=['equivalent'], additionalProperties=False)
                elif request_data.get('phase') == 'assignment':
                    schema = dict(type='object', properties=dict(assignments=dict(type='array',
                        items=dict(type='integer', enum=request_data.get('allowed_indices', list(range(len(request_data['catalog']))))), minItems=n, maxItems=n)),
                        required=['assignments'], additionalProperties=False)
                else:
                    schema = dict(type='object', properties=dict(observations={**SCHEMA, 'minItems': n, 'maxItems': n}),
                                  required=['observations'], additionalProperties=False)
                if prompt in normalization_cache:
                    saved, origin = normalization_cache[prompt]
                    response, seconds = saved['response'], saved['seconds']
                else:
                    origin = None
                    response = (await http.post('http://127.0.0.1:11434/api/generate', json={
                        'model': model['name'], 'prompt': prompt, 'format': schema, 'stream': False,
                        'options': dict(seed=42, temperature=0, num_ctx=8192, num_predict=4096),
                        'keep_alive': '30m'})).raise_for_status().json()
                    seconds = time.perf_counter() - started
                normalization_records.append(dict(prompt=prompt, response=response, seconds=seconds, reused_from=origin))
                write_new(args.output / (case_id + f'-normalize-provider-{len(normalization_records):02d}.json'), normalization_records[-1])
                if not response.get('done') or response.get('done_reason') == 'length':
                    raise ValueError('truncated normalization')
                return {'text': response['response']}
            error = None
            try:
                normalized = await normalize_observations(raw, provider=normalize_provider, chunk_texts=texts)
                graph, aliases = graph_view(normalized)
                _evaluate_context(graph, estimator=estimator_config())
                status = 'normalized'
            except (TypeError, ValueError) as exc:
                error = str(exc)
                normalized = raw
                status = 'normalization_failed_raw_fallback'
                try:
                    graph, aliases = graph_view(normalized)
                    _evaluate_context(graph, estimator=estimator_config())
                except (TypeError, ValueError):
                    normalized = anchors
                    graph, aliases = graph_view(normalized)
                    status = 'normalization_failed_anchor_fallback'
            record = dict(case_id=case_id, status=status, error=error,
                occurrences=[observation_json(o) for o in normalized], aliases=aliases,
                raw_occurrences=[observation_json(o) for o in raw],
                raw_stats=identity_stats(raw), normalized_stats=identity_stats(normalized),
                extraction_statuses=[dict(chunk_id=r['chunk_id'], status=r['status'], error=r.get('error'),
                    seconds=r['seconds'], reused_from=r['reused_from']) for r in extraction_records],
                extraction_seconds=sum(r['seconds'] for r in extraction_records),
                normalization_seconds=sum(r['seconds'] for r in normalization_records),
                input_sha256=hashlib.sha256((ROOT / 'cases' / case_id / 'case.json').read_bytes()).hexdigest())
            write_new(args.output / (case_id + '-prepared.json'), record)
            print('prepared', case_id, status, record['normalized_stats']['distinct_claims'], flush=True)


async def refine(args):
    """Revalidate recorded proposals; repair rejected batches one fact at a time.

    No re-extraction and no fresh catalog-generation calls. All original model
    outputs and prior fallback decisions remain in the parent study directory.
    """
    args.output.mkdir(parents=True, exist_ok=False)
    manifest = json.loads((args.prepared / 'manifest.json').read_text())
    write_new(args.output / 'manifest.json', {**manifest, 'parent_prepared': str(args.prepared),
        'assignment_options': dict(seed=42, temperature=0, num_ctx=8192, num_predict=128)})
    async with httpx.AsyncClient(trust_env=False, timeout=180) as http:
        decision_cache = {}
        for path in (args.prepared.parent / 'refined').glob('*assignment-*.json'):
            saved_decision = json.loads(path.read_text())
            decision_cache[saved_decision['prompt']] = (saved_decision, str(path))
        for case_id in manifest['cases']:
            target = args.prepared / (case_id + '-prepared.json')
            deadline = time.monotonic() + 1200
            while True:
                try:
                    data = json.loads(target.read_text())
                    break
                except (FileNotFoundError, json.JSONDecodeError):
                    if time.monotonic() > deadline:
                        raise TimeoutError(f'Preparation did not finish: {case_id}')
                    await asyncio.sleep(5)
            case = load_case(ROOT / 'cases' / case_id / 'case.json')
            raw = load_occurrences(case, data['raw_occurrences'])
            saved = json.loads((args.prepared / (case_id + '-normalize-provider-01.json')).read_text())
            records = []
            async def provider(prompt):
                request = json.loads(prompt.rsplit('Input JSON:\n', 1)[1])
                phase = request.get('phase')
                if phase not in ('assignment', 'verify'):
                    assert prompt == saved['prompt'], 'Proposal prompt changed; cannot reuse model output'
                    return {'text': saved['response']['response']}
                started = time.perf_counter()
                schema = (dict(type='object', properties=dict(equivalent=dict(type='boolean')),
                    required=['equivalent'], additionalProperties=False) if phase == 'verify' else
                    dict(type='object', properties=dict(assignments=dict(type='array',
                        items=dict(type='integer', enum=request['allowed_indices']), minItems=1, maxItems=1)),
                        required=['assignments'], additionalProperties=False))
                if prompt in decision_cache:
                    saved_decision, origin = decision_cache[prompt]
                    response, seconds = saved_decision['response'], saved_decision['seconds']
                else:
                    origin = None
                    response = (await http.post('http://127.0.0.1:11434/api/generate', json={
                        'model': manifest['model']['name'], 'prompt': prompt, 'format': schema, 'stream': False,
                        'options': dict(seed=42, temperature=0, num_ctx=8192, num_predict=128),
                        'keep_alive': '30m'})).raise_for_status().json()
                    seconds = time.perf_counter() - started
                record = dict(prompt=prompt, phase=phase, response=response, seconds=seconds, reused_from=origin)
                records.append(record)
                write_new(args.output / f'{case_id}-decision-{len(records):03d}.json', record)
                if not response.get('done') or response.get('done_reason') == 'length':
                    raise ValueError('truncated assignment')
                return {'text': response['response']}
            error = None
            try:
                normalized = await normalize_observations(raw, provider=provider,
                    chunk_texts={'chunk-' + c.source_id: c.text for c in case.candidates})
                graph, aliases = graph_view(normalized)
                _evaluate_context(graph, estimator=estimator_config())
                status = ('normalized' if any(claim_id(a.claim) != claim_id(b.claim)
                          for a, b in zip(raw, normalized, strict=True)) else 'identity_passthrough')
            except (ValueError, TypeError) as error_value:
                error = str(error_value)
                normalized = raw
                status = 'normalization_failed_raw_fallback'
                try:
                    graph, aliases = graph_view(normalized)
                    _evaluate_context(graph, estimator=estimator_config())
                except (ValueError, TypeError):
                    original, _ = build_observations(case)
                    normalized = tuple(replace(o, claim=Claim(c.entity_namespace, c.entity, c.attribute, c.value),
                        metadata={**o.metadata, 'chunk_id': 'chunk-' + c.source_id})
                        for c, o in zip(case.candidates, original, strict=True))
                    graph, aliases = graph_view(normalized)
                    status = 'normalization_failed_anchor_fallback'
            write_new(args.output / (case_id + '-prepared.json'), {**data, 'status': status, 'error': error,
                'occurrences': [observation_json(o) for o in normalized], 'aliases': aliases,
                'normalized_stats': identity_stats(normalized),
                'normalization_seconds': saved['seconds'] + sum(r['seconds'] for r in records),
                'assignment_requests': sum(r['phase'] == 'assignment' for r in records),
                'verification_requests': sum(r['phase'] == 'verify' for r in records),
                'verification_rejections': sum(r['phase'] == 'verify' and not json.loads(r['response']['response']).get('equivalent') for r in records),
                'initial_status': data['status']})
            print('refined', case_id, status, 'decisions', len(records), flush=True)


async def align(args):
    args.output.mkdir(parents=True, exist_ok=False)
    manifest = json.loads((args.prepared / 'manifest.json').read_text())
    write_new(args.output / 'manifest.json', {**manifest, 'parent_prepared': str(args.prepared),
        'alignment': 'Equal literal values; lexical candidate blocking; verified property aliases; values unchanged',
        'canonical_registry': 'Existing caller-supplied property identities; no preferred values'})
    async with httpx.AsyncClient(trust_env=False, timeout=180) as http:
        cache = {}
        recorded = args.prepared.parent / 'aligned-final'
        for file in recorded.glob('*alias-*.json'):
            saved = json.loads(file.read_text())
            cache[saved['prompt']] = (saved, str(file))
        for case_id in manifest['cases']:
            data = json.loads((args.prepared / (case_id + '-prepared.json')).read_text())
            case = load_case(ROOT / 'cases' / case_id / 'case.json')
            before = load_occurrences(case, data['occurrences'])
            records = []
            async def provider(prompt):
                started = time.perf_counter()
                if prompt in cache:
                    saved, origin = cache[prompt]
                    response, seconds = saved['response'], saved['seconds']
                else:
                    origin = None
                    response = (await http.post('http://127.0.0.1:11434/api/generate', json={
                        'model': manifest['model']['name'], 'prompt': prompt, 'stream': False,
                        'format': dict(type='object', properties=dict(equivalent=dict(type='boolean')),
                                       required=['equivalent'], additionalProperties=False),
                        'options': dict(seed=42, temperature=0, num_ctx=8192, num_predict=128),
                        'keep_alive': '30m'})).raise_for_status().json()
                    seconds = time.perf_counter() - started
                record = dict(prompt=prompt, response=response, seconds=seconds, reused_from=origin)
                records.append(record)
                write_new(args.output / f'{case_id}-alias-{len(records):03d}.json', record)
                if not response.get('done') or response.get('done_reason') == 'length':
                    raise ValueError('truncated equivalence judgment')
                return {'text': response['response']}
            references = [Claim(c.entity_namespace, c.entity, c.attribute, c.value) for c in case.candidates]
            normalized = await align_claim_properties(before, provider=provider,
                chunk_texts={'chunk-' + c.source_id: c.text for c in case.candidates}, canonical_claims=references)
            error = None
            try:
                graph, aliases = graph_view(normalized)
                _evaluate_context(graph, estimator=estimator_config())
                changed = any(claim_id(a.claim) != claim_id(b.claim) for a, b in zip(before, normalized, strict=True))
                status = 'normalized_aliases' if changed else data['status']
            except ValueError as failure:
                error = str(failure)
                normalized = before
                graph, aliases = graph_view(normalized)
                status = data['status']
            write_new(args.output / (case_id + '-prepared.json'), {**data, 'status': status,
                'parent_status': data['status'], 'alignment_error': error,
                'occurrences': [observation_json(o) for o in normalized], 'aliases': aliases,
                'normalized_stats': identity_stats(normalized), 'alignment_requests': len(records),
                'alignment_approvals': sum(json.loads(r['response']['response']).get('equivalent', False) for r in records),
                'alignment_seconds': sum(r['seconds'] for r in records),
                'normalization_seconds': data['normalization_seconds'] + sum(r['seconds'] for r in records)})
            print('aligned', case_id, status, 'requests', len(records), flush=True)


def aggregate(rows):
    result = {}
    for arm in sorted({r['arm'] for r in rows}):
        result[arm] = {}
        for v in ('baseline', 'coarse', 'raw', 'normalized'):
            subset = [r for r in rows if r['arm'] == arm and r.get(v) is not None]
            result[arm][v] = None if not subset else dict(n=len(subset),
                tokens=mean(r[v]['tokens'] for r in subset),
                utilization=mean(r[v]['tokens'] / r['budget'] for r in subset),
                precision=mean(r[v]['metrics']['precision'] for r in subset),
                recall=mean(r[v]['metrics']['recall'] for r in subset),
                packing_ms_p50=None if v == 'baseline' else median(r[v]['packing_ms'] for r in subset),
                historical_sdk_prepare_ms_p50=median(r[v]['packing_ms'] for r in subset) if v == 'baseline' else None)
    return result


async def verify_sdk(prepared, rows, count):
    from omneum import LocalPersistenceConfig, open_stdio_client
    from omneum.storage import SQLiteStorage
    from benchmarks.context_selection.deployment import benchmark_deployment
    checks = []
    with tempfile.TemporaryDirectory(prefix='omneum-normalization-sdk-') as temporary, benchmark_deployment() as (config, server):
        storage = SQLiteStorage(Path(temporary) / 'sdk.db')
        async with open_stdio_client(config, server, local_persistence=LocalPersistenceConfig(storage)) as client:
            for row in rows:
                if row['arm'] != 'omneum' or row['budget'] != 256:
                    continue
                case = load_case(ROOT / 'cases' / row['case_id'] / 'case.json')
                data = json.loads((prepared / (row['case_id'] + '-prepared.json')).read_text())
                occurrences = load_occurrences(case, data['occurrences'])
                graph, _ = graph_view(occurrences)
                result = await client.prepare_context(graph, chunks_for(case, occurrences), estimator=estimator_config(),
                    question=case.question, token_budget=256, count_tokens=count)
                expected = {claim_id(c.claim): c.support for c in _evaluate_context(graph, estimator=estimator_config()).claim_support}
                checks.append(dict(case_id=row['case_id'],
                    scores_parity=all(abs(result['evaluation']['claim_support'][k] - v) < 1e-12 for k, v in expected.items()),
                    context_parity=result['context'] == row['normalized']['context'],
                    ids_parity=result['packed_chunk_ids'] == row['normalized']['selected'],
                    tokens=result['selection']['selected_tokens']))
    return checks


def compare(args):
    args.output.mkdir(parents=True, exist_ok=False)
    frozen = json.loads((BASELINE / 'manifest.json').read_text())
    hashes = {str(p.relative_to(BASELINE)): hashlib.sha256(p.read_bytes()).hexdigest() for p in BASELINE.rglob('*') if p.is_file()}
    original_rows = read_rows(BASELINE / 'results.jsonl')
    index = {(r['case_id'], r['arm'], r['allocated_budget'], r['trial']): r for r in original_rows}
    rows, diagnostics = [], []
    with httpx.Client(trust_env=False, timeout=30) as http:
        props = http.get(args.tokenizer + '/props').raise_for_status().json()
        blobs = Path.home() / '.ollama/models/blobs'
        model_bytes = (blobs / ('sha256-' + frozen['generator']['digest'])).read_bytes()
        assert hashlib.sha256(model_bytes).hexdigest() == frozen['generator']['digest']
        model_layer = next(x for x in json.loads(model_bytes)['layers'] if x['mediaType'] == 'application/vnd.ollama.image.model')
        with Path(props['model_path']).open('rb') as weights:
            assert 'sha256:' + hashlib.file_digest(weights, 'sha256').hexdigest() == model_layer['digest']
        @lru_cache(maxsize=None)
        def count(text):
            return len(http.post(args.tokenizer + '/tokenize', json=dict(content=text, add_special=False, parse_special=True)).raise_for_status().json()['tokens'])
        for case_id in frozen['cases']:
            data = json.loads((args.prepared / (case_id + '-prepared.json')).read_text())
            case = load_case(ROOT / 'cases' / case_id / 'case.json')
            assert data['input_sha256'] == hashlib.sha256((ROOT / 'cases' / case_id / 'case.json').read_bytes()).hexdigest()
            normalized = load_occurrences(case, data['occurrences'])
            raw_occurrences = load_occurrences(case, data['raw_occurrences'])
            graph, aliases = graph_view(normalized)
            coarse, _ = build_observations(case)
            original_chunks = [dict(chunk_id='chunk-' + c.source_id, source_id=c.source_id, raw_text=c.text,
                source=o.source, claim_ids=[claim_id(o.claim)]) for c, o in zip(case.candidates, coarse, strict=True)]
            rich_chunks = chunks_for(case, normalized)
            start = time.perf_counter()
            rich_eval = _evaluate_context(graph, estimator=estimator_config())
            graph_ms = (time.perf_counter() - start) * 1000
            coarse_eval = _evaluate_context(coarse, estimator=estimator_config())
            def pairs(e):
                return {frozenset((p.source_a.identifier, p.source_b.identifier)): p.dependency for p in e.pairwise_dependencies}
            assert pairs(rich_eval) == pairs(coarse_eval), 'Source provenance changed'
            old_claims = {o.observation_id: claim_id(o.claim) for o in raw_occurrences}
            merged = defaultdict(set)
            for o in normalized:
                merged[claim_id(o.claim)].add(old_claims[o.observation_id])
            raw_graph_error = None
            raw_eval = None
            try:
                raw_eval = _evaluate_context(graph_view(raw_occurrences)[0], estimator=estimator_config())
            except ValueError as error:
                raw_graph_error = str(error)
            diagnostics.append(dict(case_id=case_id, status=data['status'], error=data['error'], raw_graph_error=raw_graph_error,
                raw_stats=identity_stats(raw_occurrences), normalized_stats=identity_stats(normalized),
                changed_claim_occurrences=sum(old_claims[o.observation_id] != claim_id(o.claim) for o in normalized),
                merged_distinct_input_identities={k: sorted(v) for k, v in merged.items() if len(v) > 1},
                fallback_omitted_occurrence_ids=sorted(set(old_claims) - {o.observation_id for o in normalized}),
                extraction_statuses=data['extraction_statuses'], extraction_seconds=data['extraction_seconds'],
                normalization_seconds=data['normalization_seconds'], graph_inference_ms=graph_ms,
                claims=[dict(claim_id=claim_id(c.claim), entity_namespace=c.claim.entity_namespace,
                    entity=c.claim.entity, attribute=c.claim.attribute, value=c.claim.value,
                    support=c.support, sources=c.supporting_source_count) for c in rich_eval.claim_support]))
            retrieval = json.loads((BASELINE / (case_id + '-retrieval.json')).read_text())
            for arm in ('omneum', 'bge_omneum', 'bm25_omneum', 'embedding_omneum'):
                eligible = index[case_id, arm, 256, 1]['diagnostics'].get('eligible_chunk_ids', [c['chunk_id'] for c in original_chunks])
                for budget in frozen['budgets']:
                    old = index[case_id, arm, budget, 1]
                    assert count(old['context']) == old['selected_tokens'] <= budget
                    # The release selector is frozen, not silently recomputed
                    # under the current question-aware policy. Verify its exact
                    # original text, ordering and tokens from the saved IDs.
                    old_mapping = map_chunks(original_chunks, {claim_id(c.claim) for c in coarse_eval.claim_support})
                    old_mapping['retrieval_order'] = old['selected']
                    assert reconstruct(old_mapping, old['selected']) == old['context']
                    assert old['context'] == index[case_id, arm, budget, 2]['context']
                    variants = {}
                    candidates = [('coarse', original_chunks, coarse_eval), ('normalized', rich_chunks, rich_eval)]
                    if raw_eval is not None:
                        candidates.append(('raw', chunks_for(case, raw_occurrences), raw_eval))
                    else:
                        variants['raw'] = None
                    for name, chunks, evaluation in candidates:
                        options = dict(question=case.question) if arm == 'omneum' else {}
                        if arm != 'omneum':
                            raw = retrieval[arm.removesuffix('_omneum')]['raw_scores']
                            _, scores = normalize_chunk_relevance(raw, [c['chunk_id'] for c in chunks], 'reranker_score' if arm == 'bge_omneum' else 'similarity')
                            mapping = map_chunks(chunks, {claim_id(c.claim) for c in evaluation.claim_support})
                            q = {claim: max(scores[k] for k in identifiers) for claim, identifiers in mapping['claim_chunks'].items()}
                            options = dict(strategy='coverage_support_query', claim_relevance=q)
                        selection_chunks = [c for c in chunks if c['chunk_id'] in eligible]
                        trace = []
                        result = reconstruct_context(evaluation, selection_chunks, token_budget=budget, count_tokens=count,
                            _allow_unmapped_claims=True, _selection_trace=trace, **options)
                        # Warm token-counter cache before timing packing separately.
                        start = time.perf_counter()
                        repeated = reconstruct_context(evaluation, selection_chunks, token_budget=budget,
                            count_tokens=count, _allow_unmapped_claims=True, **options)
                        packing_ms = (time.perf_counter() - start) * 1000
                        assert repeated['context'] == result['context']
                        selected = result['selected_chunk_ids']
                        variants[name] = dict(selected=selected, context=result['context'], tokens=result['token_usage'],
                            packing_ms=packing_ms, coverage=result['claim_coverage'],
                            trace=trace)
                    prev, updated = set(old['selected']), set(variants['normalized']['selected'])
                    rows.append(dict(case_id=case_id, domain=case.domain, arm=arm, budget=budget, status=data['status'], eligible=eligible,
                        baseline=dict(selected=old['selected'], context=old['context'], tokens=old['selected_tokens'], metrics=old['selection_score'], packing_ms=old['prepare_seconds'] * 1000),
                        **variants, removed=[k for k in old['selected'] if k not in updated],
                        added=[k for k in variants['normalized']['selected'] if k not in prev],
                        retained=[k for k in variants['normalized']['selected'] if k in prev]))
            print('compared', case_id, flush=True)
        # Freeze every selection before loading evaluation-only gold labels.
        truths = {}
        for row in rows:
            case_id = row['case_id']
            if case_id not in truths:
                truths[case_id] = load_ground_truth(ROOT / 'cases' / case_id / 'ground_truth.json')
            for variant in ('coarse', 'raw', 'normalized'):
                if row[variant] is not None:
                    row[variant]['metrics'] = score_selection(
                        [k.removeprefix('chunk-') for k in row[variant]['selected']], truths[case_id])
        sdk_checks = asyncio.run(verify_sdk(args.prepared, rows, count))
    known = {(r['case_id'], r['trial'], r['context']) for r in original_rows}
    fresh = [dict(case_id=r['case_id'], arm=r['arm'], budget=r['budget'], trial=t, context=r['normalized']['context'])
             for r in rows for t in (1, 2) if (r['case_id'], t, r['normalized']['context']) not in known]
    assert all(hashlib.sha256((BASELINE / k).read_bytes()).hexdigest() == h for k, h in hashes.items())
    statuses = Counter(d['status'] for d in diagnostics)
    ext = Counter(e['status'] for d in diagnostics for e in d['extraction_statuses'])
    sdk_arms = {'omneum', 'bge_omneum', 'bm25_omneum', 'embedding_omneum'}
    def controls(subset):
        return {arm: dict(n=len(ss), precision=mean(r['selection_score']['precision'] for r in ss),
            recall=mean(r['selection_score']['recall'] for r in ss), tokens=mean(r['selected_tokens'] for r in ss),
            utilization=mean(r['selected_tokens'] / r['allocated_budget'] for r in ss) if all(r['allocated_budget'] for r in ss) else None)
            for arm in sorted({r['arm'] for r in subset} - sdk_arms)
            if (ss := [r for r in subset if r['arm'] == arm])}
    summary = dict(baseline_sha256=hashes, cases=len(diagnostics), configurations=len(rows), normalization_statuses=dict(statuses),
        sdk_checks=sdk_checks,
        extraction_statuses=dict(ext), overall=aggregate(rows),
        paired_raw_valid=aggregate([r for r in rows if r['raw'] is not None]),
        frozen_controls_unchanged=controls(original_rows),
        frozen_controls_by_domain={d: controls([r for r in original_rows if r['domain'] == d]) for d in {r['domain'] for r in original_rows}},
        by_domain={domain: aggregate([r for r in rows if r['domain'] == domain]) for domain in {r['domain'] for r in rows}},
        by_budget={str(b): aggregate([r for r in rows if r['budget'] == b]) for b in frozen['budgets']},
        new_generation_keys=len({(r['case_id'], r['trial'], r['context']) for r in fresh}))
    for name, value in [('summary', summary), ('selections', rows), ('diagnostics', diagnostics), ('fresh_generation_inventory', fresh)]:
        write_new(args.output / (name + '.json'), value)
    print(json.dumps({k: v for k, v in summary.items() if k not in (
        'baseline_sha256', 'by_domain', 'by_budget', 'overall', 'sdk_checks', 'paired_raw_valid',
        'frozen_controls_unchanged', 'frozen_controls_by_domain')}, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=['prepare', 'refine', 'align', 'compare'])
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--prepared', type=Path)
    parser.add_argument('--tokenizer')
    args = parser.parse_args()
    if args.mode == 'prepare':
        asyncio.run(prepare(args))
    elif args.mode == 'refine':
        assert args.prepared
        asyncio.run(refine(args))
    elif args.mode == 'align':
        assert args.prepared
        asyncio.run(align(args))
    else:
        assert args.prepared and args.tokenizer
        compare(args)


if __name__ == '__main__':
    main()
