"""Source-only, bounded repair of archived extraction; no downstream generation.

Replays all archived initial extraction outputs through production validation.
Only empty/invalid outputs trigger bounded local repair. All original chunk mappings
remain present; a failed supplemental chunk cannot erase other chunks' facts.
"""
import argparse
import asyncio
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import time

import httpx

from omneum import Claim
from omneum.extraction import _extract_with_repair
from omneum.normalization import align_claim_properties, _align_claim_identities
from .normalization_benchmark import (ROOT, BASELINE, SCHEMA, write_new, load_case,
    build_observations, load_occurrences, observation_json, graph_view, identity_stats,
    _evaluate_context, estimator_config, claim_id)


def _retain_valid_supplemental(anchors, supplemental, group):
    """An invalid supplemental chunk must not erase other chunks' mappings."""
    try:
        _evaluate_context(graph_view((*anchors,*supplemental,*group))[0],estimator=estimator_config())
    except ValueError as error:
        return tuple(supplemental), str(error)
    return (*supplemental,*group), None


async def prepare(args):
    args.output.mkdir(parents=True, exist_ok=False)
    before = {str(f): hashlib.sha256(f.read_bytes()).hexdigest() for folder in
        (BASELINE, ROOT / 'analysis/normalization-v4') for f in folder.rglob('*') if f.is_file()}
    write_new(args.output / 'protected_sha256.json', before)
    parent = ROOT / 'analysis/normalization-v4'
    manifest = json.loads((parent / 'aligned-registered/manifest.json').read_text())
    write_new(args.output / 'manifest.json', {**manifest,
        'parent_prepared': str(parent / 'aligned-registered'),
        'scope': 'Replay archived initial extraction; bounded source-only repair; guarded property alignment. No question or gold.'})
    alias_cache = {}
    for f in (parent / 'aligned-registered').glob('*alias-*.json'):
        d = json.loads(f.read_text());alias_cache[d['prompt']] = (d, str(f))
    extraction_cache = {}
    for name in ('prepared', 'prepared-short', 'prepared-final', 'prepared-catalog'):
        for f in (ROOT / 'analysis/normalization-v5' / name).glob('*alias-*.json'):
            d = json.loads(f.read_text());alias_cache[d['prompt']] = (d, str(f))
        for f in (ROOT / 'analysis/normalization-v5' / name).glob('*-extract-*.json'):
            d = json.loads(f.read_text());extraction_cache[d['prompt']] = (d, str(f))
    async with httpx.AsyncClient(trust_env=False, timeout=240) as http:
        tags = (await http.get('http://127.0.0.1:11434/api/tags')).raise_for_status().json()['models']
        assert any(m['name'] == manifest['model']['name'] and m['digest'] == manifest['model']['digest'] for m in tags)
        info = (await http.post('http://127.0.0.1:11434/api/show', json={'model':manifest['model']['name']})).raise_for_status().json()
        assert not info.get('remote_host') and not info.get('remote_model')
        async def generate(prompt, schema):
            start = time.perf_counter()
            response = (await http.post('http://127.0.0.1:11434/api/generate', json={
                'model': manifest['model']['name'], 'prompt': prompt, 'stream': False, 'format': schema,
                'options': dict(seed=42, temperature=0, num_ctx=8192, num_predict=2048),
                'keep_alive': '30m'})).raise_for_status().json()
            return response, time.perf_counter() - start
        for case_id in manifest['cases']:
            case = load_case(ROOT/'cases'/case_id/'case.json')
            prior = json.loads((parent/'aligned-registered'/(case_id+'-prepared.json')).read_text())
            anchors0, _ = build_observations(case)
            anchors = tuple(replace(o, claim=Claim(c.entity_namespace,c.entity,c.attribute,c.value),
                metadata={**o.metadata,'chunk_id':'chunk-'+c.source_id}) for c,o in zip(case.candidates,anchors0,strict=True))
            old_raw = {o.observation_id:o for o in load_occurrences(case,prior['raw_occurrences'])}
            old_normalized = {o.observation_id:o for o in load_occurrences(case,prior['occurrences'])}
            archive = {json.loads(f.read_text())['chunk_id']: (json.loads(f.read_text()),str(f))
                for f in (parent/'prepared').glob(case_id+'-extract-*.json')}
            statuses=[];facts=[];supplemental=[];fresh_seconds=0
            for c,anchor in zip(case.candidates,anchors,strict=True):
                key='chunk-'+c.source_id; saved,origin=archive[key];calls=[]
                async def provider(prompt):
                    nonlocal fresh_seconds
                    if not calls:
                        response,seconds,reused=saved['response'],saved['seconds'],origin
                    elif prompt in extraction_cache:
                        cached,reused = extraction_cache[prompt]
                        response,seconds = cached['response'],cached['seconds']
                    else:
                        response,seconds=await generate(prompt,SCHEMA);reused=None;fresh_seconds+=seconds
                    record=dict(prompt=prompt,response=response,seconds=seconds,reused_from=reused,chunk_id=key)
                    calls.append(record);write_new(args.output/f'{case_id}-{c.source_id}-extract-{len(calls):02d}.json',record)
                    if not response.get('done') or response.get('done_reason')=='length':
                        raise ValueError('truncated local extraction')
                    return {'text':response['response']}
                extracted,diagnostic=await _extract_with_repair(dict(id=key,text=c.text,source=anchor.source,
                    observed_at=anchor.observed_at),provider=provider)
                group=[]
                for o in extracted:
                    current=replace(anchor,observation_id=o.observation_id,claim=o.claim,metadata=o.metadata)
                    # Reuse verified v4 identity only for the exact same occurrence/assertion.
                    if current.observation_id in old_raw and current.observation_id in old_normalized and claim_id(current.claim)==claim_id(old_raw[current.observation_id].claim):
                        current=replace(current,claim=old_normalized[current.observation_id].claim)
                    group.append(current)
                # Reject only an invalid supplemental chunk; original anchors and
                # all other supplemental chunks remain, with an explicit diagnostic.
                retained, mapping_error = _retain_valid_supplemental(anchors,supplemental,group)
                supplemental = list(retained)
                if mapping_error:
                    diagnostic={**diagnostic,'status':'invalid_with_original_mapping','mapping_error':mapping_error}
                facts.extend(group)
                statuses.append(dict(chunk_id=key,**diagnostic,seconds=sum(r['seconds'] for r in calls),
                    new_seconds=sum(r['seconds'] for r in calls if r['reused_from'] is None),
                    extracted_claims=len(group),previous_status=next(e['status'] for e in prior['extraction_statuses'] if e['chunk_id']==key)))
                if diagnostic['retried']: print('repair',case_id,key,diagnostic['status'],len(group),flush=True)
            raw=(*anchors,*facts);valid=(*anchors,*supplemental);decisions=[]
            texts={'chunk-'+c.source_id:c.text for c in case.candidates}
            async def alias_provider(prompt):
                if prompt in alias_cache:
                    cached,origin=alias_cache[prompt];response,seconds=cached['response'],cached['seconds']
                else:
                    origin=None;response,seconds=await generate(prompt,dict(type='object',properties=dict(equivalent=dict(type='boolean')),required=['equivalent'],additionalProperties=False))
                decisions.append(dict(prompt=prompt,response=response,seconds=seconds,reused_from=origin))
                record_path=args.output/f'{case_id}-alias-{len(decisions):03d}.json'
                write_new(record_path,decisions[-1])
                alias_cache[prompt]=(decisions[-1],str(record_path))
                if not response.get('done') or response.get('done_reason')=='length': raise ValueError('truncated equivalence judgment')
                return {'text':response['response']}
            normalized=await align_claim_properties(valid,provider=alias_provider,chunk_texts=texts,
                canonical_claims=[o.claim for o in anchors])
            normalized=await _align_claim_identities(normalized,provider=alias_provider,chunk_texts=texts,
                canonical_claims=[o.claim for o in anchors])
            graph,aliases=graph_view(normalized);_evaluate_context(graph,estimator=estimator_config())
            status='valid_repaired' if any(e['retried'] for e in statuses) else 'valid_replayed'
            if any(e['status'] in ('failed_after_retry','invalid_with_original_mapping','empty_after_retry') for e in statuses):status='partial_supplemental_failure'
            write_new(args.output/(case_id+'-prepared.json'),dict(case_id=case_id,status=status,error=None,
                occurrences=[observation_json(o) for o in normalized],raw_occurrences=[observation_json(o) for o in raw],
                aliases=aliases,raw_stats=identity_stats(raw),normalized_stats=identity_stats(normalized),
                extraction_statuses=statuses,extraction_seconds=sum(e['seconds'] for e in statuses),
                normalization_seconds=sum(r['seconds'] for r in decisions),new_extraction_seconds=fresh_seconds,
                new_normalization_seconds=sum(r['seconds'] for r in decisions if r['reused_from'] is None),
                prior_normalization_seconds=prior['normalization_seconds'],
                input_sha256=hashlib.sha256((ROOT/'cases'/case_id/'case.json').read_bytes()).hexdigest()))
            print('prepared',case_id,status,len(normalized),len(decisions),'alias checks',flush=True)
    assert all(hashlib.sha256(Path(k).read_bytes()).hexdigest()==v for k,v in before.items())
    print('Protected baseline and v4 hashes match',flush=True)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();asyncio.run(prepare(args))

if __name__=='__main__': main()
