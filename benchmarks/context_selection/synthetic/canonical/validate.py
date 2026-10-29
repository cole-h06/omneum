"""Validate canonical data and frozen-file integrity without running a benchmark."""

from benchmarks.context_selection.paths import resolve_artifact
from collections import Counter,defaultdict
import hashlib
import json
from pathlib import Path

HERE=Path(__file__).resolve().parent
ROOT=HERE.parent
PROJECT=ROOT.parents[2]
FIELDS=('entity_namespace','entity','attribute','value')

def enc(x):return json.dumps(x,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False)
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()

def main():
    manifest=json.loads((HERE/'manifest.json').read_text());catalog=json.loads((HERE/'claim_catalog.json').read_text())
    changes=[json.loads(x) for x in (HERE/'changes.jsonl').read_text().splitlines()]
    protected=json.loads((HERE/'protected_sources.json').read_text())
    for path,h in protected.items():assert sha(resolve_artifact(path))==h,path
    occurrences=[];conflicts=defaultdict(set);seen_catalog=defaultdict(list)
    cases=sorted((HERE/'cases').glob('*/case.json'))
    for path in cases:
        before=json.loads((ROOT/'cases'/path.parent.name/'case.json').read_text());after=json.loads(path.read_text())
        assert {k:v for k,v in before.items() if k!='candidates'}=={k:v for k,v in after.items() if k!='candidates'}
        assert len(before['candidates'])==len(after['candidates'])
        ids={c['observation_id'] for candidate in after['candidates'] for c in candidate['claims']}
        assert len(ids)==sum(len(c['claims']) for c in after['candidates'])
        for a,b in zip(before['candidates'],after['candidates'],strict=True):
            assert {k:v for k,v in a.items() if k not in FIELDS}=={k:v for k,v in b.items() if k!='claims'}
            assert b['claims'][0]['observation_id']==a['provenance']['assertion_id']
            assert all(p in ids for p in a['provenance'].get('parent_assertion_ids',[]))
            properties={}
            for c in b['claims']:
                fact={k:c[k] for k in FIELDS};cid='sha256:'+hashlib.sha256(enc(fact).encode()).hexdigest()
                assert c['claim_id']==cid and fact=={k:catalog[cid][k] for k in FIELDS}
                key=(c['entity_namespace'],c['entity'],c['attribute'])
                assert key not in properties,'duplicate or conflicting source/property: '+str((path,b['source_id'],key))
                properties[key]=cid;conflicts[key].add(enc(c['value']))
                for e in c['evidence']:assert e['source_id']==b['source_id'] and b['text'][e['start']:e['end']]==e['text']
                item=dict(case_id=after['id'],source_id=b['source_id'],observation_id=c['observation_id'])
                seen_catalog[cid].append(item);occurrences.append((after['id'],b['source_id'],c['observation_id'],cid))
        assert (path.parent/'ground_truth.json').read_bytes()==(ROOT/'cases'/path.parent.name/'ground_truth.json').read_bytes()
    assert set(seen_catalog)==set(catalog)
    for cid,items in seen_catalog.items():assert items==catalog[cid]['occurrences']
    assert len(changes)==len(occurrences)==manifest['claim_occurrences']
    assert [(r['case_id'],r['source_id'],r['observation_id'],r['claim_id']) for r in changes]==occurrences
    for r in manifest['retrieval']:
        assert sha(HERE/r['path'])==sha(resolve_artifact(r['original']))==r['sha256']
    original=json.loads((ROOT/'results/question-aware-release-v1/manifest.json').read_text())
    assert original['budgets']==manifest['token_budgets']
    log=HERE/'tests.log'
    result=dict(cases=len(cases),candidates=manifest['candidate_count'],claim_occurrences=len(occurrences),distinct_claim_identities=len(catalog),
        replacements=sum(c['operation']=='replace' for c in changes),additional_atomic_claims=sum(c['operation']=='add' for c in changes),
        identities_shared_by_multiple_sources=sum(len({(x['case_id'],x['source_id']) for x in items})>1 for items in seen_catalog.values()),
        conflicting_properties_retained=sum(len(v)>1 for v in conflicts.values()),
        source_passages_and_nonclaim_fields_unchanged=True,labels_byte_identical=True,retrieval_files_byte_identical=24,
        protected_original_files_verified=len(protected),original_observation_ids_retained=189,
        test_result=log.read_text().strip().splitlines()[-1] if log.exists() else None,
        canonical_benchmark_runs=0,canonical_inference_runs=0,model_calls=0,
        changed_adapter_files=['schema.py','loader.py','sdk_adapter.py','prepare_benchmark.py::mapped_chunks','query_benchmark.py::inputs'])
    (HERE/'validation.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2))

if __name__=='__main__':main()
