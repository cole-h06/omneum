"""Source-only local atomic extraction and a separate frozen-selection comparison.

No gold files are read during extraction. No downstream answers are generated.
All output directories must be new; original fixtures and results are read-only.
"""
import argparse
import asyncio
from dataclasses import asdict, replace
from functools import lru_cache
import hashlib
import json
from pathlib import Path
from statistics import mean
import time

import httpx

from omneum import Claim, Observation, Source, extract_observations
from omneum.client import _evaluate_context
from omneum.context_selection import claim_id, map_chunks, reconstruct_context
from omneum.query_context import normalize_chunk_relevance, source_key
from .investigate_question_release import BASELINE, ROOT, read_rows
from .loader import load_case, load_ground_truth
from .scoring import score_selection
from .sdk_adapter import build_observations
from ..config import estimator_config


SCHEMA = {'type': 'array', 'items': {'type': 'object', 'properties': {
    'entity_namespace': {'type': 'string'}, 'entity': {'type': 'string'},
    'attribute': {'type': 'string'}, 'value': {}},
    'required': ['entity_namespace', 'entity', 'attribute', 'value'], 'additionalProperties': False}}


def write_new(path, value):
    with path.open('x') as file:
        json.dump(value, file, indent=2, ensure_ascii=False)
        file.write('\n')


def mapped_chunks(case, observations, explicit_claim_ids=None):
    """Use extraction's existing chunk_id metadata; never zip chunks to claims."""
    original, _ = build_observations(case)
    by_chunk = {'chunk-' + c.source_id: [] for c in case.candidates}
    for o in observations:
        by_chunk[o.metadata['chunk_id']].append(o)
    chunks = []
    for candidate, source_observation in zip(case.candidates, original, strict=True):
        key = 'chunk-' + candidate.source_id
        assert by_chunk[key], 'No assertions extracted; cannot silently omit a frozen candidate'
        assert all(o.source == source_observation.source for o in by_chunk[key])
        identifiers = ({claim_id(o.claim) for o in by_chunk[key]} if explicit_claim_ids is None
                       else set(explicit_claim_ids[key]))
        chunks.append(dict(chunk_id=key, source=source_observation.source, source_id=candidate.source_id,
            raw_text=candidate.text, claim_ids=sorted(identifiers)))
    map_chunks(chunks, {claim_id(o.claim) for o in observations})
    return chunks


def observation_json(o):
    return dict(observation_id=o.observation_id, source=asdict(o.source),
        claim=dict(entity_namespace=o.claim.entity_namespace, entity=o.claim.entity,
                   attribute=o.claim.attribute, value=o.claim.value),
        metadata=o.metadata, parent_observation_ids=o.parent_observation_ids)


def _augment_observations(original, extracted):
    """Merge upstream facts, preserving original provenance and canonical edges.

    Both inputs already carry chunk_id metadata. Empty extraction is allowed
    because it does not erase caller-supplied structured evidence. No semantic
    normalization, predicate renaming or conflict resolution happens here.
    """
    by_chunk = {o.metadata['chunk_id']: o for o in original}
    values = list(original)
    seen = {(source_key(o.source), claim_id(o.claim)) for o in original}
    for atomic in extracted:
        provenance = by_chunk[atomic.metadata['chunk_id']]
        assert source_key(atomic.source) == source_key(provenance.source)
        key = source_key(atomic.source), claim_id(atomic.claim)
        if key in seen:
            continue
        seen.add(key)
        values.append(replace(provenance, observation_id=atomic.observation_id,
                              claim=atomic.claim, metadata=atomic.metadata))
    return tuple(values)


def _claim_ids_by_chunk(original, extracted):
    # Preserve associations before coalescing graph occurrences: several chunks
    # may reference one source/claim observation. Graph identity and passage
    # membership are different relations in the existing public contract.
    result = {}
    for o in (*original, *extracted):
        result.setdefault(o.metadata['chunk_id'], set()).add(claim_id(o.claim))
    return {k: sorted(v) for k, v in result.items()}


def augment(args):
    args.output.mkdir(parents=True, exist_ok=False)
    manifest = json.loads((args.extraction / 'manifest.json').read_text())
    write_new(args.output / 'manifest.json', {**manifest, 'parent_extraction': str(args.extraction),
        'mapping': 'Original supplied assertions plus extracted atomic predicates; canonical source/claim deduplication'})
    for case_id in manifest['cases']:
        data = json.loads((args.extraction / (case_id + '-atomic.json')).read_text())
        case = load_case(ROOT / 'cases' / case_id / 'case.json')
        original, _ = build_observations(case)
        original = tuple(replace(o, metadata={**o.metadata, 'chunk_id': 'chunk-' + c.source_id})
                         for c, o in zip(case.candidates, original, strict=True))
        by_chunk = {o.metadata['chunk_id']: o for o in original}
        extracted = [replace(by_chunk[item['metadata']['chunk_id']], observation_id=item['observation_id'],
                            claim=Claim(**item['claim']), metadata=item['metadata']) for item in data['observations']]
        values = _augment_observations(original, extracted)
        chunk_claim_ids = _claim_ids_by_chunk(original, extracted)
        record = dict(case_id=case_id, input_sha256=data['input_sha256'],
            observations=[observation_json(o) for o in values],
            chunk_claim_ids=chunk_claim_ids,
            anchor_observation_ids=[o.observation_id for o in original],
            chunks_without_supplemental_facts=sorted(set(by_chunk) - {o.metadata['chunk_id'] for o in extracted}))
        try:
            mapped_chunks(case, values, chunk_claim_ids)
            evaluation = _evaluate_context(values, estimator=estimator_config())
            record.update(status='valid', claims=len(evaluation.claim_support), sources=len(evaluation.source_reliability))
        except (AssertionError, TypeError, ValueError) as error:
            record.update(status='invalid', error_type=type(error).__name__, error=str(error))
        write_new(args.output / (case_id + '-atomic.json'), record)
        print('augmented', case_id, record['status'], 'observations', len(values), flush=True)


async def extract(args):
    args.output.mkdir(parents=True, exist_ok=False)
    async with httpx.AsyncClient(trust_env=False, timeout=180) as http:
        models = (await http.get('http://127.0.0.1:11434/api/tags')).raise_for_status().json()['models']
        model = next(m for m in models if m['name'] == args.model)
        info = (await http.post('http://127.0.0.1:11434/api/show', json={'model': args.model})).raise_for_status().json()
        assert not info.get('remote_host') and not info.get('remote_model')
        manifest = dict(model=model, cases=args.cases, scope='Source-only upstream extraction; no gold/question/answers',
            extraction_source_sha256=hashlib.sha256(Path('omneum/extraction.py').read_bytes()).hexdigest(),
            options=dict(seed=42, temperature=0, num_ctx=8192, num_predict=768), schema=SCHEMA)
        write_new(args.output / 'manifest.json', manifest)
        for case_id in args.cases:
            case = load_case(ROOT / 'cases' / case_id / 'case.json')
            original, _ = build_observations(case)
            chunks = []
            for c, o in zip(case.candidates, original, strict=True):
                chunks.append(dict(id='chunk-' + c.source_id, source=o.source, text=c.text,
                    observed_at=o.observed_at, source_modified_at=o.source_modified_at,
                    upstream_sources=o.upstream_sources, cited_sources=o.cited_sources,
                    parent_observation_ids=o.parent_observation_ids, retrievals=o.retrievals))
            records = []
            async def provider(prompt):
                started = time.perf_counter()
                response = (await http.post('http://127.0.0.1:11434/api/generate', json={
                    'model': args.model, 'prompt': prompt, 'format': SCHEMA, 'stream': False,
                    'options': manifest['options'], 'keep_alive': '10m'})).raise_for_status().json()
                assert response.get('done') and response.get('done_reason') != 'length', 'Truncated extraction'
                records.append(dict(prompt=prompt, response=response, seconds=time.perf_counter() - started))
                write_new(args.output / f'{case_id}-provider-{len(records):02d}.json', records[-1])
                print('extracted', case_id, len(records), flush=True)
                return {'text': response['response']}
            extracted = await extract_observations(chunks, provider=provider)
            # Source-document lineage originally names a coarse occurrence.
            # Preserve that ancestry by expanding its occurrence group to the
            # extracted atomic observations. No semantic relationship is guessed.
            replacement = {o.observation_id: [e.observation_id for e in extracted
                if e.metadata['chunk_id'] == c['id']] for o, c in zip(original, chunks, strict=True)}
            for o in extracted:
                for parent in o.parent_observation_ids or ():
                    assert parent in replacement and replacement[parent], 'Unresolvable original parent group'
            atomic = tuple(replace(o, parent_observation_ids=None if o.parent_observation_ids is None else
                tuple(parent for old in o.parent_observation_ids for parent in replacement[old])) for o in extracted)
            # Never repair conflicting/duplicate model claims by inventing new
            # predicates, suffixes or entity identities. Retain invalid outputs.
            record = dict(case_id=case_id, observations=[observation_json(o) for o in atomic],
                lineage_expansion=replacement,
                input_sha256=hashlib.sha256((ROOT / 'cases' / case_id / 'case.json').read_bytes()).hexdigest())
            try:
                mapped_chunks(case, atomic)
                evaluation = _evaluate_context(atomic, estimator=estimator_config())
                record.update(status='valid', claims=len(evaluation.claim_support), sources=len(evaluation.source_reliability))
            except (AssertionError, TypeError, ValueError) as error:
                record.update(status='invalid', error_type=type(error).__name__, error=str(error))
            write_new(args.output / (case_id + '-atomic.json'), record)
            print('validated', case_id, record['status'], flush=True)


def read_atomic(case, path):
    data = json.loads(path.read_text())
    assert data['status'] == 'valid', data
    assert data['input_sha256'] == hashlib.sha256((ROOT / 'cases' / case.case_id / 'case.json').read_bytes()).hexdigest()
    original, _ = build_observations(case)
    originals = {'chunk-' + c.source_id: o for c, o in zip(case.candidates, original, strict=True)}
    values = []
    for item in data['observations']:
        o = originals[item['metadata']['chunk_id']]
        values.append(replace(o, observation_id=item['observation_id'], claim=Claim(**item['claim']),
            metadata=item['metadata'], parent_observation_ids=None if item['parent_observation_ids'] is None
            else tuple(item['parent_observation_ids'])))
    return tuple(values)


def compare(args):
    args.output.mkdir(parents=True, exist_ok=False)
    original_hashes = {str(p.relative_to(BASELINE)): hashlib.sha256(p.read_bytes()).hexdigest()
                       for p in BASELINE.rglob('*') if p.is_file()}
    frozen = json.loads((BASELINE / 'manifest.json').read_text())
    extraction = json.loads((args.extraction / 'manifest.json').read_text())
    assert extraction['model']['digest'] == frozen['generator']['digest']
    rows = read_rows(BASELINE / 'results.jsonl')
    index = {(r['case_id'], r['arm'], r['allocated_budget'], r['trial']): r for r in rows}
    output = []
    with httpx.Client(trust_env=False, timeout=30) as http:
        blobs = Path.home() / '.ollama/models/blobs'
        model_bytes = (blobs / ('sha256-' + frozen['generator']['digest'])).read_bytes()
        assert hashlib.sha256(model_bytes).hexdigest() == frozen['generator']['digest']
        layer = next(x for x in json.loads(model_bytes)['layers'] if x['mediaType'] == 'application/vnd.ollama.image.model')
        props = http.get(args.tokenizer + '/props').raise_for_status().json()
        with Path(props['model_path']).open('rb') as weights:
            assert 'sha256:' + hashlib.file_digest(weights, 'sha256').hexdigest() == layer['digest']
        @lru_cache(maxsize=None)
        def count(text):
            response = http.post(args.tokenizer + '/tokenize', json={
                'content': text, 'add_special': False, 'parse_special': True})
            return len(response.raise_for_status().json()['tokens'])
        for case_id in extraction['cases']:
            case = load_case(ROOT / 'cases' / case_id / 'case.json')
            atomic = read_atomic(case, args.extraction / (case_id + '-atomic.json'))
            coarse, _ = build_observations(case)
            coarse_chunks = [dict(chunk_id='chunk-' + c.source_id, source=o.source, source_id=c.source_id,
                raw_text=c.text, claim_ids=[claim_id(o.claim)]) for c, o in zip(case.candidates, coarse, strict=True)]
            atomic_data = json.loads((args.extraction / (case_id + '-atomic.json')).read_text())
            atomic_chunks = mapped_chunks(case, atomic, atomic_data.get('chunk_claim_ids'))
            evaluations = {name: _evaluate_context(values, estimator=estimator_config())
                           for name, values in [('coarse', coarse), ('atomic', atomic)]}
            def dependencies(evaluation):
                return {frozenset((p.source_a.identifier, p.source_b.identifier)): p.dependency
                        for p in evaluation.pairwise_dependencies}
            assert dependencies(evaluations['coarse']) == dependencies(evaluations['atomic'])
            retrieval = json.loads((BASELINE / (case_id + '-retrieval.json')).read_text())
            # Selection never reads the truth; load it only for output metrics.
            truth = load_ground_truth(ROOT / 'cases' / case_id / 'ground_truth.json')
            for arm in ('omneum', 'bge_omneum', 'bm25_omneum', 'embedding_omneum'):
                eligible = index[case_id, arm, 256, 1]['diagnostics'].get('eligible_chunk_ids', [c['chunk_id'] for c in coarse_chunks])
                for budget in frozen['budgets']:
                    old = index[case_id, arm, budget, 1]
                    assert count(old['context']) == old['selected_tokens'] <= budget
                    original_options = (dict(question=case.question) if arm == 'omneum' else
                        dict(strategy='coverage_support_density', complementary_evidence=True, token_cost_exponent=1))
                    original_result = reconstruct_context(evaluations['coarse'],
                        [c for c in coarse_chunks if c['chunk_id'] in eligible], token_budget=budget,
                        count_tokens=count, _allow_unmapped_claims=True, **original_options)
                    assert original_result['context'] == old['context']
                    assert original_result['selected_chunk_ids'] == old['selected']
                    variants = {}
                    for name, chunks in [('coarse', coarse_chunks), ('atomic', atomic_chunks)]:
                        options = dict(question=case.question) if arm == 'omneum' else {}
                        if arm != 'omneum':
                            raw = retrieval[arm.removesuffix('_omneum')]['raw_scores']
                            _, scores = normalize_chunk_relevance(raw, [c['chunk_id'] for c in chunks],
                                'reranker_score' if arm == 'bge_omneum' else 'similarity')
                            mapping = map_chunks(chunks, {claim_id(c.claim) for c in evaluations[name].claim_support})
                            q = {claim: max(scores[k] for k in identifiers) for claim, identifiers in mapping['claim_chunks'].items()}
                            options = dict(strategy='coverage_support_query', claim_relevance=q)
                        trace = []
                        result = reconstruct_context(evaluations[name], [c for c in chunks if c['chunk_id'] in eligible],
                            token_budget=budget, count_tokens=count, _allow_unmapped_claims=True,
                            _selection_trace=trace, **options)
                        selected = result['selected_chunk_ids']
                        variants[name] = dict(selected=selected, tokens=result['token_usage'], context=result['context'],
                            metrics=score_selection([k.removeprefix('chunk-') for k in selected], truth),
                            selection_scores=result['selection_scores'], trace=trace,
                            covered_claims=result['claim_coverage'])
                        if name == 'coarse' and arm == 'omneum':
                            assert selected == old['selected'] and result['context'] == old['context']
                    previous, updated = set(old['selected']), set(variants['atomic']['selected'])
                    output.append(dict(case_id=case_id, arm=arm, budget=budget, eligible=eligible,
                        baseline=dict(selected=old['selected'], tokens=old['selected_tokens'], context=old['context'], metrics=old['selection_score']),
                        **variants, retained=[k for k in variants['atomic']['selected'] if k in previous],
                        removed=[k for k in old['selected'] if k not in updated],
                        added=[k for k in variants['atomic']['selected'] if k not in previous]))
    summary = dict(scope='Targeted source-only upstream atomic extraction; no downstream answer generations',
        original_baseline_sha256=original_hashes, cases=extraction['cases'], comparisons=len(output),
        by_arm={arm: {version: dict(tokens=mean(r[version]['tokens'] for r in output if r['arm'] == arm),
            precision=mean(r[version]['metrics']['precision'] for r in output if r['arm'] == arm),
            recall=mean(r[version]['metrics']['recall'] for r in output if r['arm'] == arm))
            for version in ('baseline', 'coarse', 'atomic')} for arm in {r['arm'] for r in output}})
    assert all(hashlib.sha256((BASELINE / p).read_bytes()).hexdigest() == h for p, h in original_hashes.items())
    write_new(args.output / 'summary.json', summary)
    write_new(args.output / 'selections.json', output)
    print(json.dumps(summary['by_arm'], indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=['extract', 'augment', 'compare'])
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--cases', nargs='+', default=['coding_clean_dependency', 'coding_package_fix_lineage'])
    parser.add_argument('--model', default='qwen2.5:7b')
    parser.add_argument('--extraction', type=Path)
    parser.add_argument('--tokenizer')
    args = parser.parse_args()
    if args.mode == 'extract':
        asyncio.run(extract(args))
    elif args.mode == 'augment':
        assert args.extraction
        augment(args)
    else:
        assert args.extraction and args.tokenizer
        compare(args)


if __name__ == '__main__':
    main()
