"""Materialize the single audited dataset. No SDK, models, inference or scoring.

Usage: python benchmarks/context_selection/synthetic/canonical/build.py
Refuses to replace existing dataset outputs. Annotations are in curation.py.
"""
from collections import Counter,defaultdict
from copy import deepcopy
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import shutil

from curation import CLAIMS

HERE=Path(__file__).resolve().parent
HELDOUT=HERE.parent
PROJECT=HELDOUT.parents[2]
FROZEN=HELDOUT/'results/question-aware-release-v1'
FIELDS=('entity_namespace','entity','attribute','value')


def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def encoded(value):return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False)
def identity(claim):return 'sha256:'+hashlib.sha256(encoded({k:claim[k] for k in FIELDS}).encode()).hexdigest()
def put(path,obj):
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('x') as f:f.write(json.dumps(obj,ensure_ascii=False,indent=2,allow_nan=False)+'\n')


def build():
    if (HERE/'manifest.json').exists():raise ValueError('Canonical dataset already materialized; do not overwrite it')
    original_paths=list((HELDOUT/'cases').rglob('*.json'))+list(FROZEN.rglob('*'))+list((PROJECT/'omneum').rglob('*.py'))
    protected={str(p.relative_to(PROJECT)):digest(p) for p in original_paths if p.is_file() and '__pycache__' not in p.parts}
    put(HERE/'protected_sources.json',protected)
    legacy_manifest=json.loads((HELDOUT/'dataset_manifest.json').read_text())
    # Verify the old cases are still the frozen originals, not merely whatever
    # happened to be present at the start of this curation task.
    for key,h in legacy_manifest.items():
        if key.startswith('cases/'):
            assert digest(HELDOUT/key)==h,key
    cases=sorted((HELDOUT/'cases').glob('*/case.json'))
    assert set(CLAIMS)=={p.parent.name for p in cases} and len(cases)==24
    changes=[];catalog={};summary=[];all_occurrences=[]
    for path in cases:
        before=json.loads(path.read_text());cid=before['id'];after=deepcopy(before)
        assert set(CLAIMS[cid])=={c['source_id'] for c in before['candidates']},cid
        total=0
        for candidate in after['candidates']:
            sid=candidate['source_id'];old={k:candidate.pop(k) for k in FIELDS};raw=candidate['text']
            candidate['claims']=[]
            for index,spec in enumerate(CLAIMS[cid][sid]):
                assert set(spec)==set(FIELDS)
                assert all(isinstance(spec[k],str) and spec[k].strip() for k in FIELDS[:3])
                ck=identity(spec);catalog.setdefault(ck,{**spec,'occurrences':[]})
                assert {k:catalog[ck][k] for k in FIELDS}==spec
                oid=candidate['provenance']['assertion_id']+('' if index==0 else ':claim:'+str(index+1))
                record={**spec,'claim_id':ck,'observation_id':oid,
                    'evidence':[{'source_id':sid,'start':0,'end':len(raw),'text':raw}]}
                candidate['claims'].append(record);catalog[ck]['occurrences'].append({'case_id':cid,'source_id':sid,'observation_id':oid})
                all_occurrences.append((cid,sid,oid,ck))
                changes.append(dict(case_id=cid,source_id=sid,operation='replace' if index==0 else 'add',
                    original=old if index==0 else None,original_candidate_claim=old,
                    corrected=spec,claim_id=ck,observation_id=oid,supporting_passage=raw,
                    evidence_span={'start':0,'end':len(raw)},
                    reason='Canonicalize the source assertion and retain its scope, predicate, modality and qualifications.' if index==0 else 'Separate explicit additional facts from the original single-claim mapping.'))
                total+=1
            assert candidate['claims']
        put(HERE/'cases'/cid/'case.json',after)
        # Exact byte copies; never use gold labels to declare annotations.
        truth=path.with_name('ground_truth.json');out=HERE/'cases'/cid/'ground_truth.json'
        assert not out.exists();shutil.copyfile(truth,out)
        summary.append(dict(case_id=cid,candidates=len(before['candidates']),original_claims=len(before['candidates']),canonical_claim_occurrences=total))
    retrieval=[]
    for p in sorted(FROZEN.glob('*-retrieval.json')):
        out=HERE/'retrieval'/p.name;out.parent.mkdir(exist_ok=True);assert not out.exists();shutil.copyfile(p,out)
        retrieval.append({'path':str(out.relative_to(HERE)),'sha256':digest(out),'original':str(p.relative_to(PROJECT))})
    assert len(retrieval)==24
    put(HERE/'claim_catalog.json',catalog)
    with (HERE/'changes.jsonl').open('x') as f:
        for c in changes:f.write(json.dumps(c,ensure_ascii=False,allow_nan=False)+'\n')
    # Unit/scope resolutions that need more than a literal token match.
    put(HERE/'identity_notes.json',dict(
        rules=[
          'Identical canonical namespace/entity/attribute/value tuples share one ID. Evidence, source identities, provenance and observations never enter a claim ID.',
          'Assertions made by a passage are retained even when they conflict with other passages; no expected-answer or source-authority filtering is used.',
          'Instruction, available operation, observed effect, historical incident and proposed workaround are different predicates. Scope in entities/values is used only where stated or unambiguously resolved by the case context.',
          'Abbreviated subjects inherit the original case topic; case-level aliases do not add unstated counts, deployment states, dates, or applicability.',
          'Partial dates retain their stated precision. Observation/publication timestamps are not substituted for the date of an asserted event.',
          'Range membership and an aggregate count are not identical assertions; the Riverton register retains its literal vehicle ID ranges rather than inventing a count by arithmetic.',
          'Default retention durations do not assert that exceptions expire: legal-hold exceptions are represented separately where stated.',
          'A mislabeled or differently defined metric is preserved with its actual computation and output label, rather than silently treated as the board metric.',
        ],
        contextual_resolutions=[
          {'case_id':'analytics_metric_definition_conflict','sources':['dashboard','exported_report'],'context_sources':['semantic_layer','transformation'],'resolution':'The dashboard explicitly uses the semantic-layer field; its export copies the dashboard. Their metric includes expansion as stated by that field definition.'},
          {'case_id':'analytics_stale_dashboard','sources':['exported_report'],'context_sources':['dashboard_snapshot'],'resolution':'The export explicitly names the August 2 dashboard image. That image explicitly identifies run B02.'},
          {'case_id':'coding_api_version_change','sources':['test_output'],'context_sources':['package_metadata','current_api_docs'],'resolution':'The smoke test explicitly uses the lockfile environment; the lockfile identifies LedgerKit 3.0.0. The call is the 3.0 CSV API with its exact test arguments preserved separately.'},
          {'case_id':'support_stale_runbook','sources':['ticket'],'context_sources':['kb_article','old_runbook'],'resolution':'The ticket explicitly copies the v3 KB. Its restart instruction is scoped to v3, not relabeled as v5.'},
        ],
        unit_normalizations=[{'case_id':'analytics_metric_definition_conflict','source_id':'transformation','attribute':'retention_percentage_including_expansion','source_literal':1.12,'source_unit':'dimensionless ratio','canonical_value':112,'canonical_unit':'percent','validation':'Decimal("1.12") * 100 == Decimal("112")'}]))
    manifest=json.loads((FROZEN/'manifest.json').read_text())
    put(HERE/'manifest.json',dict(schema='canonical-multi-claim-dataset-v1',purpose='One manually audited canonical dataset; not a benchmark result',
        original_cases='benchmarks/context_selection/synthetic/cases',frozen_reference=str(FROZEN.relative_to(PROJECT)),
        original_case_fields_preserved='All except four legacy single-claim fields, replaced by candidate.claims[]',
        claim_identity='sha256 of UTF-8 canonical JSON (sorted keys, compact separators) of exactly entity_namespace, entity, attribute, value',
        observation_identity='Original assertion_id retained by the first claim; additional claims append :claim:<one-based index>',
        provenance='Candidate source/provenance unchanged; every claim occurrence inherits it. Parent assertion IDs still refer to retained original IDs.',
        evidence='Exact original full-passage spans; these are source attestations, not entailment probabilities.',
        loader_boundary='Benchmark loader and SDK adapter support claims[] as existing SDK observations while retaining unchanged legacy singleton behavior. Multi-claim candidates have no legacy primary projection; historical singleton-only analysis scripts remain unsupported for canonical inputs.',
        cases=summary,token_budgets=manifest['budgets'],retrieval=retrieval,
        case_count=24,candidate_count=sum(x['candidates'] for x in summary),claim_occurrences=len(changes),distinct_claims=len(catalog),
        benchmark_runs=0,model_calls=0,canonical_inference_runs=0))
    assert Decimal('1.12')*100==Decimal(112)
    for p,h in protected.items():assert digest(PROJECT/p)==h,p
    print('Materialized',len(cases),'cases;',len(changes),'claim occurrences;',len(catalog),'identities')

if __name__=='__main__':build()
