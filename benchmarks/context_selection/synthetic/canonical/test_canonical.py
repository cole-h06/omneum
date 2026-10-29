"""Dataset and adapter contract checks only; no benchmark/inference run."""
from collections import defaultdict
from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest

from omneum.context_selection import claim_id,reconstruct
from omneum.canonicalization import canonicalize_source
from omneum.engine_graph import AssertionTriple,SourcePair,build_graph
from omneum.dependency import estimate_dependencies
from benchmarks.context_selection.config import estimator_config
from benchmarks.context_selection.synthetic.loader import load_case,build_observations
from benchmarks.context_selection.synthetic.prepare_benchmark import mapped_chunks
from benchmarks.context_selection.synthetic.query_benchmark import inputs
from benchmarks.context_selection.synthetic.schema import candidate_claims
from benchmarks.context_selection.synthetic.sdk_adapter import build_observations as sdk_observations

HERE=Path(__file__).resolve().parent
OLD=HERE.parent/'cases'
FROZEN=HERE.parent/'results/question-aware-release-v1'
PATHS=sorted((HERE/'cases').glob('*/case.json'))
FIELDS=('entity_namespace','entity','attribute','value')


def raw(cid):return json.loads((HERE/'cases'/cid/'case.json').read_text())
def facts(cid,sid):return next(c['claims'] for c in raw(cid)['candidates'] if c['source_id']==sid)
def fact(cid,sid,attr):return next(c for c in facts(cid,sid) if c['attribute']==attr)


@pytest.mark.parametrize('path',PATHS,ids=lambda p:p.parent.name)
def test_original_nonclaim_fields_pools_and_labels_preserved(path):
    before=json.loads((OLD/path.parent.name/'case.json').read_text());after=json.loads(path.read_text())
    assert {k:v for k,v in before.items() if k!='candidates'}=={k:v for k,v in after.items() if k!='candidates'}
    assert len(before['candidates'])==len(after['candidates'])
    for a,b in zip(before['candidates'],after['candidates'],strict=True):
        assert {k:v for k,v in a.items() if k not in FIELDS}=={k:v for k,v in b.items() if k!='claims'}
        assert b['claims']
        for c in b['claims']:
            assert not any(k in b for k in FIELDS)
            encoded=json.dumps({k:c[k] for k in FIELDS},sort_keys=True,separators=(',',':'),ensure_ascii=False)
            assert c['claim_id']=='sha256:'+hashlib.sha256(encoded.encode()).hexdigest()
            for e in c['evidence']:
                assert e['source_id']==b['source_id'] and b['text'][e['start']:e['end']]==e['text']
    assert (path.parent/'ground_truth.json').read_bytes()==(OLD/path.parent.name/'ground_truth.json').read_bytes()


@pytest.mark.parametrize('path',PATHS,ids=lambda p:p.parent.name)
def test_multi_claims_flatten_to_native_observations_with_provenance_and_no_pool_growth(path):
    case=load_case(path);observations,source_ids=sdk_observations(case)
    assert (observations,source_ids)==build_observations(case)
    assert len(observations)==sum(len(c.claims) for c in case.candidates)
    assert len(source_ids)==len(case.candidates)
    by_id={o.observation_id:o for o in observations};assert len(by_id)==len(observations)
    for c in case.candidates:
        assert c.entity_namespace is None and c.entity is None and c.attribute is None and c.value is None
        assert c.claims[0].observation_id==c.provenance.assertion_id
        for spec in c.claims:
            o=by_id[spec.observation_id]
            assert o.source.identifier==c.source.identifier
            assert source_ids[o.source]==c.source_id and o.claim.value==spec.value
            assert o.observed_at==c.provenance.observed_at and o.source_modified_at==c.provenance.source_modified_at
            assert o.parent_observation_ids==c.provenance.parent_assertion_ids
            assert all(p in by_id for p in o.parent_observation_ids)
            assert o.metadata['canonical_claim_id']==spec.claim_id
            assert o.metadata['evidence']==list(spec.evidence)
            for field in ('upstream_sources','cited_sources'):
                assert [x.identifier for x in getattr(o,field)]==[x.identifier for x in getattr(c.provenance,field)]
    mapped,chunks=mapped_chunks(case);assert mapped==observations and len(chunks)==len(case.candidates)
    for c,chunk in zip(case.candidates,chunks,strict=True):
        assert chunk['raw_text']==c.text and chunk['source_id']==c.source_id
        assert chunk['claim_ids']==[claim_id(by_id[a.observation_id].claim) for a in c.claims]
    qobs,qchunks,texts=inputs(case);assert qobs==observations
    assert {claim_id(o.claim) for o in observations}==set(texts)
    assert all(c['source'].identifier==candidate.source.identifier for c,candidate in zip(qchunks,case.candidates,strict=True))
    triples=[AssertionTriple(canonicalize_source(o.source.kind,o.source.identifier),json.dumps([o.claim.entity_namespace,o.claim.entity,o.claim.attribute]),claim_id(o.claim)) for o in observations]
    # Structural input validation only. Deliberately do not invoke infer().
    pairs,_=estimate_dependencies(tuple(source_ids),observations,estimator_config())
    graph=build_graph(triples,[SourcePair(p.source_a.identifier,p.source_b.identifier,p.dependency,p.weighted_signal_coverage) for p in pairs])
    assert graph.assertion_count==len(observations)
    mapping={'chunk_text':{c['chunk_id']:c['raw_text'] for c in chunks},'retrieval_order':[c['chunk_id'] for c in chunks]}
    assert reconstruct(mapping,mapping['retrieval_order'])=='\n\n'.join('[chunk-'+c.source_id+']\n'+c.text for c in case.candidates)


def test_total_delivered_returned_and_misleading_transformation_are_separate():
    cid='analytics_incomplete_lineage'
    table=facts(cid,'source_table')
    assert {c['attribute']:c['value'] for c in table}=={'delivered_parcel_count':487,'returned_parcel_count':33,'total_parcel_id_count':520}
    transform=facts(cid,'transformation')
    misleading=fact(cid,'transformation','delivered_parcel_count')
    calculation=fact(cid,'transformation','calculated_dispatch_row_count')
    assert misleading['value']==520 and calculation['value']=={'aggregation':'COUNT(*)','count':520,'population':'dispatch cohort'}
    assert misleading['claim_id']!=calculation['claim_id']
    assert misleading['claim_id']==fact(cid,'dashboard','delivered_parcel_count')['claim_id']
    assert misleading['claim_id']!=fact(cid,'source_table','delivered_parcel_count')['claim_id']
    assert fact(cid,'source_table_2','returned_parcel_count')['claim_id']==fact(cid,'source_table','returned_parcel_count')['claim_id']


def test_execution_scopes_and_sql_ordering_remain_explicit():
    cid='coding_config_conflict'
    assert 'direct-binary' in facts(cid,'readme')[0]['entity']
    assert 'CI unit job' in facts(cid,'ci_config')[0]['entity']
    assert 'prod.yaml' in facts(cid,'deployment_config')[0]['entity']
    assert fact(cid,'deployment_config','readiness_port')['claim_id']==fact(cid,'test_output','readiness_port')['claim_id']
    assert fact(cid,'source_code','listener_port_rule')['value']['default_when_unset']==8080
    sql=facts('coding_clean_dependency','example')[0]['value']
    assert sql['condition']=='a row was returned' and sql['action']=='update balances' and sql['ordering']=='update balances before COMMIT'


def test_state_instruction_version_and_factual_conflicts_remain_distinct():
    cid='support_stale_runbook'
    state=facts(cid,'service_state');instruction=facts(cid,'current_runbook')[0]
    assert all('/admin/keys/refresh' not in json.dumps(c['value']) for c in state)
    assert fact(cid,'service_state','refresh_endpoint_enabled')['value'] is True
    assert instruction['value']['action']=={'method':'POST','endpoint':'/admin/keys/refresh'}
    assert instruction['value']['verification']=='confirm loaded key ID'
    assert facts(cid,'old_runbook')[0]['entity']=='Nimbus v3 key rotation'
    assert instruction['entity']=='Nimbus v5'
    q='research_independent_false_consensus'
    false=fact(q,'report','occupied_home_count');correct=fact(q,'dataset','occupied_home_count')
    assert [false[k] for k in FIELDS[:3]]==[correct[k] for k in FIELDS[:3]]
    assert false['value']==240 and correct['value']==216 and false['claim_id']!=correct['claim_id']


def test_planned_dates_temporal_revisions_and_different_metrics_not_merged():
    c='multi_agent_repeated_subagent'
    planned=fact(c,'web_result','planned_dispatch_date')
    assert planned['claim_id']==fact(c,'database_result','planned_dispatch_date')['claim_id']==fact(c,'analyst_agent_2','planned_dispatch_date')['claim_id']
    assert planned['claim_id']!=fact(c,'researcher_agent','dispatch_date')['claim_id']
    assert fact(c,'tool_result','dispatch_date')['claim_id']==fact(c,'verifier_agent','dispatch_date')['claim_id']
    assert fact('analytics_stale_dashboard','dashboard_snapshot','paid_seat_count')['entity']!=fact('analytics_stale_dashboard','current_query','paid_seat_count')['entity']
    a='analytics_metric_definition_conflict'
    assert fact(a,'semantic_layer','retention_percentage_including_expansion')['claim_id']==fact(a,'transformation','retention_percentage_including_expansion')['claim_id']
    assert fact(a,'semantic_layer','retention_percentage_including_expansion')['claim_id']!=fact(a,'metric_docs','retention_percentage_excluding_expansion')['claim_id']


def test_raw_relevance_artifacts_are_identical():
    paths=list((HERE/'retrieval').glob('*-retrieval.json'));assert len(paths)==24
    for p in paths:assert p.read_bytes()==(FROZEN/p.name).read_bytes()


@pytest.mark.parametrize('change', ['mixed','empty','duplicate_id','bad_span','bad_catalog'])
def test_invalid_multi_claim_data_is_rejected(tmp_path,change):
    d=raw('analytics_incomplete_lineage');c=d['candidates'][0]
    if change=='mixed':c['value']=487
    elif change=='empty':c['claims']=[]
    elif change=='duplicate_id':c['claims'][1]['observation_id']=c['claims'][0]['observation_id']
    elif change=='bad_span':c['claims'][0]['evidence'][0]['text']='Not in passage'
    elif change=='bad_catalog':c['claims'][0]['claim_id']='sha256:forged'
    p=tmp_path/'case.json';p.write_text(json.dumps(d))
    with pytest.raises(ValueError):load_case(p)


@pytest.mark.parametrize('path',sorted(OLD.glob('*/case.json')),ids=lambda p:p.parent.name)
def test_legacy_frozen_claim_tokens_and_chunk_mapping_are_unchanged(path):
    case=load_case(path);observations,chunks=mapped_chunks(case)
    assert len(observations)==len(case.candidates) and all(not c.claims for c in case.candidates)
    frozen=json.loads((FROZEN/(case.case_id+'-inputs.json')).read_text())
    assert [{k:c[k] for k in ('chunk_id','source_id','raw_text','claim_ids')} for c in chunks]==[{k:c[k] for k in ('chunk_id','source_id','raw_text','claim_ids')} for c in frozen['chunks']]
    assert all(o.metadata=={} for o in observations)


@pytest.mark.parametrize('path', PATHS, ids=lambda p:p.parent.name)
def test_diagnostic_occurrence_join_and_all_claim_metrics(path):
    from dataclasses import asdict
    from benchmarks.context_selection.synthetic.sdk_adapter import observation_chunk_pairs
    from benchmarks.context_selection.synthetic.loader import load_ground_truth
    from benchmarks.context_selection.synthetic.prepare_benchmark import evidence_metrics
    case = load_case(path)
    observations, chunks = mapped_chunks(case)
    joined = observation_chunk_pairs(observations, chunks, case)
    assert len(joined) == len(observations)
    assert {o.observation_id for o, c in joined} == {o.observation_id for o in observations}
    saved = observation_chunk_pairs([asdict(o) for o in observations], chunks, asdict(case))
    assert [(o['observation_id'], c['chunk_id']) for o,c in saved] == [(o.observation_id,c['chunk_id']) for o,c in joined]
    truth = load_ground_truth(path.with_name('ground_truth.json'))
    assert evidence_metrics(case, truth, chunks, chunks)['required_claim_coverage'] == 1
    supporters = [c for c in chunks if c['source_id'] in truth.supporting_sources]
    all_required = {v for c in supporters for v in c['claim_ids']}
    one = chunks[:1]
    expected = len(all_required & set(one[0]['claim_ids'])) / len(all_required)
    assert evidence_metrics(case, truth, chunks, one)['required_claim_coverage'] == expected


def test_off_task_control_requires_every_claim_to_be_off_task():
    from types import SimpleNamespace
    from benchmarks.context_selection.synthetic.prepare_benchmark import controlled_chunks
    case = load_case(HERE/'cases/analytics_incomplete_lineage/case.json')
    observations, chunks = mapped_chunks(case)
    source = next(c for c in chunks if c['source_id'] == 'source_table')
    # The first claim alone cannot decide whether a mixed passage is unrelated.
    other = next(c for c in chunks if set(c['claim_ids']) - set(source['claim_ids']))
    mixed = {**other, 'claim_ids': [next(iter(set(other['claim_ids']) - set(source['claim_ids']))), source['claim_ids'][0]]}
    result = controlled_chunks([source,mixed], observations, SimpleNamespace(supporting_sources=['source_table']), 2, 'end')
    assert len(result) == 2
