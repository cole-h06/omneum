"""Recorded HotpotQA relation collisions and semantic coverage regressions."""
import asyncio
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path

import pytest
from omneum import Claim, Observation, Source
from omneum._extraction_verification import (extract_verified, verify_observations, _verify_missing,
                                            verify_identity_partition, semantic_claim)

FIXTURES = json.loads((Path(__file__).parent/'fixtures/hotpotqa_identity_repairs.json').read_text())


def response(value):
    return {'text':json.dumps(value)}


def positive(data):
    return dict(decisions=[dict(observation_id=o['observation_id'],entailed=True,complete=True,
                               evidence=data['source_text'],issues=[]) for o in data['observations']],missing=[])


@pytest.mark.parametrize('slot_format',[False,True])
@pytest.mark.parametrize('fixture',FIXTURES,ids=lambda f:f['case_id']+'/'+f['passage_id'])
def test_recorded_collisions_repair_identities_without_changing_values_or_occurrences(fixture,slot_format):
    calls=[]
    originals={json.dumps(r['claim']['value'],sort_keys=True):i for i,r in enumerate(fixture['records'])}
    async def provider(prompt):
        calls.append(prompt)
        if 'Input JSON:\n' not in prompt:
            return response([dict(claim=r['claim'],evidence=fixture['source_text']) for r in fixture['records']])
        data=json.loads(prompt.split('Input JSON:\n')[1]);phase=data['phase']
        if phase=='identity_repair':
            identities=[]
            for o in data['observations']:
                index=originals[json.dumps(o['claim']['value'],sort_keys=True)]
                identities.append(dict(fixture['identities'][index],observation_id=o['observation_id']))
            if slot_format:
                identities={i['observation_id']:dict(reason='Explicit source relation',
                    identity={k:v for k,v in i.items() if k!='observation_id'}) for i in identities}
            return response(dict(identities=identities))
        if phase=='identity_verification':
            return response(dict(decisions=[dict(group_id=g['group_id'],distinct=True,
                evidence=data['source_text'],issues=[]) for g in data['groups']]))
        if phase=='missing_verification':
            return response(dict(decisions=[dict(proposal_id=p['proposal_id'],supported=True,
                already_represented=False,matching_observation_ids=[],evidence=data['source_text'],issues=[])
                for p in data['proposals']]))
        return response(positive(data))
    source=Source('web_document','https://fixture.example/'+fixture['case_id'])
    chunk=dict(id=fixture['passage_id'],text=fixture['source_text'],source=source,
               observed_at=datetime.now(timezone.utc))
    observations,diagnostics=asyncio.run(extract_verified(chunk,provider=provider))
    assert diagnostics['verified'] and diagnostics['retry_count']==1
    assert {o.observation_id for o in observations}=={f"{chunk['id']}:{i}" for i in range(len(originals))}
    assert {json.dumps(o.claim.value,sort_keys=True) for o in observations}==set(originals)
    assert len({(o.claim.entity_namespace,o.claim.entity,o.claim.attribute) for o in observations})==len(originals)
    assert all(o.source is source and o.metadata['chunk_id']==chunk['id'] for o in observations)
    assert len(calls)==6  # extraction, source review, gap review, identities, partition review, final source review


def test_predicate_formatting_changes_neither_verification_input_nor_acceptance():
    source='Fixture Actor voiced Fixture Character.'
    prompts=[]
    async def provider(prompt):
        prompts.append(prompt);data=json.loads(prompt.split('Input JSON:\n')[1])
        assert '"attribute":"voiced_character"' not in prompt
        if data['phase']=='missing_verification':
            return response(dict(decisions=[dict(proposal_id='0',supported=True,already_represented=False,
                matching_observation_ids=[],evidence=source,issues=[])]))
        return response(positive(data))
    for attribute in ['voiced character','voiced_character']:
        claim=Claim('person','Fixture Actor',attribute,dict(assertion=source))
        obs=Observation('p05:0',Source('web_document','https://fixture.example/test'),claim,
            observed_at=datetime.now(timezone.utc),metadata=dict(chunk_id='p05'))
        accepted,audit=asyncio.run(verify_observations([obs],source_text=source,provider=provider))
        assert audit['status']=='verified' and accepted[0].claim.attribute==claim.attribute
        records=[dict(claim=dict(entity_namespace='person',entity='Fixture Actor',attribute=attribute,
                                  value=dict(assertion=source)),evidence=source)]
        missing,_=asyncio.run(_verify_missing(records,[],source,provider,'p05'))
        assert len(missing)==1 and missing[0]['claim']['attribute']==attribute
    assert prompts[0]==prompts[2] and prompts[1]==prompts[3]


def test_missing_verifier_finds_its_own_evidence_without_stale_proposal_span():
    fixture=FIXTURES[-1];record=deepcopy(fixture['records'][0])
    record['evidence']=fixture['source_text'][:30]
    original=deepcopy(record)
    async def provider(prompt):
        data=json.loads(prompt.split('Input JSON:\n')[1])
        assert data['source_text']==fixture['source_text']
        assert data['proposals']==[dict(proposal_id='0',claim=semantic_claim(original['claim']))]
        return response(dict(decisions=[dict(proposal_id='0',supported=True,already_represented=False,
            matching_observation_ids=[],evidence=fixture['source_text'],issues=[])]))
    gaps,reviews=asyncio.run(_verify_missing([record],[],fixture['source_text'],provider,'p08'))
    assert record==original and gaps[0]['claim']==original['claim']
    assert gaps[0]['evidence']==fixture['source_text'] and reviews[0]['supported']


def test_identity_audit_is_not_bound_to_provisional_predicate_labels():
    fixture=FIXTURES[-1];prompts=[]
    async def provider(prompt):
        prompts.append(prompt);data=json.loads(prompt.split('Input JSON:\n')[1])
        assert all('original' not in a and 'original_value' in a
                   for g in data['groups'] for a in g['assertions'])
        return response(dict(decisions=[dict(group_id=g['group_id'],distinct=True,
            evidence=data['source_text'],issues=[]) for g in data['groups']]))
    for label in ('cultivation_use','cultivation use','provisional_broad_property'):
        targets={f'p06:{i}':dict(claim={**r['claim'],'attribute':label})
                 for i,r in enumerate(fixture['records'])}
        fixed=response([dict(observation_id=i,claim={**r['claim'],**identity})
            for (i,r),identity in zip(targets.items(),fixture['identities'])])
        assert not asyncio.run(verify_identity_partition(targets,fixed,fixture['source_text'],provider))
    assert prompts[0]==prompts[1]==prompts[2]


@pytest.mark.parametrize('later_negative',[False,True])
def test_rejected_identity_feedback_preserves_proposal_and_verifier_reason(later_negative):
    fixture=FIXTURES[-1];repairs=[];audits=[];missing_reviews=[]
    async def provider(prompt):
        if 'Input JSON:\n' not in prompt:
            return response(fixture['records'])
        data=json.loads(prompt.split('Input JSON:\n')[1]);phase=data['phase']
        if phase=='identity_repair':
            repairs.append(data)
            if len(repairs)==2:
                failed=data['previous_failure']['structural_rejections']
                assert [r['observation_id'] for r in failed]==['p08:0','p08:1']
                assert {r['identity_proposal']['attribute'] for r in failed}=={
                    i['attribute'] for i in fixture['identities']}
                assert all(r['identity_reviews'][0]['issues']==['Relation scope unverified'] for r in failed)
            return response(dict(identities={o['observation_id']:dict(reason='Source-specific relation',
                identity=fixture['identities'][int(o['observation_id'].split(':')[1])])
                for o in data['observations']}))
        if phase=='identity_verification':
            audits.append(data);ok=len(audits)==2
            return response(dict(decisions=[dict(group_id=g['group_id'],distinct=ok,
                evidence=data['source_text'],issues=[] if ok else ['Relation scope unverified'])
                for g in data['groups']]))
        if phase=='missing_verification':
            missing_reviews.append(data)
            negative=later_negative and len(missing_reviews)==2
            return response(dict(decisions=[dict(proposal_id=p['proposal_id'],supported=not negative,
                already_represented=False,matching_observation_ids=[],evidence=data['source_text'],
                issues=['Provisional predicate mismatch'] if negative else [])
                for p in data['proposals']]))
        return response(positive(data))
    chunk=dict(id='p08',text=fixture['source_text'],source=Source('web_document','https://fixture.example/larvae'),
               observed_at=datetime.now(timezone.utc))
    observations,diagnostics=asyncio.run(extract_verified(chunk,provider=provider))
    assert diagnostics['verified'] and diagnostics['retry_count']==2
    assert len(repairs)==len(audits)==2 and len(observations)==2
    assert [o.claim.value for o in observations]==[r['claim']['value'] for r in fixture['records']]


@pytest.mark.parametrize('resolve',[True,False])
def test_recorded_cultivation_noop_gets_feedback_within_two_retries(resolve):
    fixture=next(f for f in FIXTURES if f['case_id']=='5a75d9b4554299109176e5a7' and f['passage_id']=='p06')
    repairs=[]
    async def provider(prompt):
        if 'Input JSON:\n' not in prompt:
            return response(fixture['records'])
        data=json.loads(prompt.split('Input JSON:\n')[1])
        if data['phase']=='identity_repair':
            repairs.append(data)
            assert 'Non-exclusive uses/purposes' in prompt
            if len(repairs)==2:
                assert data['previous_failure']['attempt']==1
                assert len(data['previous_failure']['structural_rejections'])==2
            return response(dict(identities={o['observation_id']:dict(reason='Source-stated purpose',
                identity=fixture['identities'][i] if resolve and len(repairs)==2 else
                {k:o['claim'][k] for k in ('entity_namespace','entity','attribute')})
                for i,o in enumerate(data['observations'])}))
        if data['phase']=='identity_verification':
            assert 'Explicit non-exclusive uses are also relations' in prompt
            assert 'two different\nheights, populations, or timeouts for the SAME scope still conflict' in prompt
            return response(dict(decisions=[dict(group_id=g['group_id'],distinct=True,
                evidence=data['source_text'],issues=[]) for g in data['groups']]))
        if data['phase']=='missing_verification':
            return response(dict(decisions=[dict(proposal_id=p['proposal_id'],supported=True,
                already_represented=False,matching_observation_ids=[],evidence=data['source_text'],issues=[])
                for p in data['proposals']]))
        return response(positive(data))
    chunk=dict(id='p06',text=fixture['source_text'],source=Source('web_document','https://fixture.example/malus'),
               observed_at=datetime.now(timezone.utc))
    observations,diagnostics=asyncio.run(extract_verified(chunk,provider=provider))
    assert len(repairs)==2 and diagnostics['retry_count']==2
    assert diagnostics['verified'] is resolve
    if resolve:
        assert {o.observation_id for o in observations}=={'p06:0','p06:1'}
        assert [o.claim.value for o in observations]==[r['claim']['value'] for r in fixture['records']]
        assert all(o.metadata['chunk_id']=='p06' for o in observations)
    else:
        assert not observations


def test_later_negative_cannot_clear_a_supported_missing_fact():
    source='Fixture City is a city. It has population 12.'
    a=dict(claim=dict(entity_namespace='place',entity='Fixture City',attribute='kind',
                     value=dict(assertion='Fixture City is a city.')),evidence=source)
    b=dict(claim=dict(entity_namespace='place',entity='Fixture City',attribute='population',
                     value=dict(assertion='Fixture City has population 12.')),evidence=source)
    extractions=0;reviews=0
    async def provider(prompt):
        nonlocal extractions,reviews
        if 'Input JSON:\n' not in prompt:
            extractions+=1;return response([a] if extractions==1 else [])
        data=json.loads(prompt.split('Input JSON:\n')[1])
        if data['phase']=='missing_verification':
            reviews+=1
            return response(dict(decisions=[dict(proposal_id=p['proposal_id'],supported=reviews==1,
                already_represented=False,matching_observation_ids=[],evidence=source if reviews==1 else '',
                issues=[] if reviews==1 else ['inconsistent abstention']) for p in data['proposals']]))
        result=positive(data)
        if extractions==1:result['missing']=[b]
        return response(result)
    obs,diag=asyncio.run(extract_verified(dict(id='p05',text=source,source=Source('web_document','https://fixture.example/test'),
        observed_at=datetime.now(timezone.utc)),provider=provider))
    assert obs==() and not diag['verified'] and diag['retry_count']==2 and extractions==3
    assert all(any(r['claim']['attribute']=='population' for r in t['supported_obligations']) for t in diag['trace'])
    assert diag['trace'][-1]['verification']['missing']


def test_identity_partition_rejects_disguised_competing_values():
    fixture=deepcopy(FIXTURES[0]);source=fixture['source_text'];identity_calls=0
    async def provider(prompt):
        nonlocal identity_calls
        if 'Input JSON:\n' not in prompt:
            return response([dict(claim=r['claim'],evidence=source) for r in fixture['records']])
        data=json.loads(prompt.split('Input JSON:\n')[1])
        if data['phase']=='identity_repair':
            identity_calls+=1
            return response(dict(identities=[dict(observation_id=o['observation_id'],entity_namespace='person',
                entity=o['claim']['entity'],attribute='arbitrary_'+str(i)) for i,o in enumerate(data['observations'])]))
        if data['phase']=='identity_verification':
            return response(dict(decisions=[dict(group_id=g['group_id'],distinct=False,evidence='',
                issues=['No source-attested distinction in these labels']) for g in data['groups']]))
        if data['phase']=='missing_verification':
            return response(dict(decisions=[dict(proposal_id=p['proposal_id'],supported=True,
                already_represented=False,matching_observation_ids=[],evidence=source,issues=[]) for p in data['proposals']]))
        return response(positive(data))
    obs,diag=asyncio.run(extract_verified(dict(id='p06',text=source,source=Source('web_document','https://fixture.example/test'),
        observed_at=datetime.now(timezone.utc)),provider=provider))
    assert not obs and not diag['verified'] and identity_calls==2 and diag['retry_count']==2


@pytest.mark.parametrize('slot_format',[False,True])
@pytest.mark.parametrize('kind',['semantic','structural'])
@pytest.mark.parametrize('reject_first_identity',[False,True])
def test_mixed_repairs_do_not_starve_identity_or_other_obligations(kind,reject_first_identity,slot_format):
    source='Fixturetown has population 12 and area 9. In staging the timeout is 8.'
    def fact(attribute,assertion,evidence=source):
        return dict(claim=dict(entity_namespace='town',entity='Fixturetown',attribute=attribute,
            value=dict(assertion=assertion)),evidence=evidence)
    initial=[fact('has','Fixturetown has population 12.'),fact('has','Fixturetown has area 9.'),
             fact('timeout_seconds','The staging timeout is 8.' if kind=='structural' else 'The timeout is 8.',
                  evidence='not in the source' if kind=='structural' else source)]
    generations=[];partitions=0;fixed_third=False
    async def provider(prompt):
        nonlocal partitions,fixed_third
        if 'Input JSON:\n' not in prompt:
            generations.append('extraction');return response(initial)
        data=json.loads(prompt.split('Input JSON:\n')[1]);phase=data['phase']
        if phase in ('identity_repair','mixed_repair'):
            generations.append(phase)
            result=dict(identities=[dict(observation_id=o['observation_id'],entity_namespace='town',
                entity='Fixturetown',attribute=['population','area'][i]) for i,o in enumerate(data['observations'])])
            if phase=='mixed_repair':
                assert data['other_repairs']['rejected']
                result['records']=[dict(fact('timeout_seconds','The staging timeout is 8.'),observation_id='p00:2')]
                fixed_third=True
            if slot_format:
                result['identities']={i['observation_id']:dict(reason='Distinct source-stated relation',
                    identity={k:v for k,v in i.items() if k!='observation_id'}) for i in result['identities']}
                if phase=='mixed_repair':
                    result['records']={'p00:2':{k:v for k,v in result['records'][0].items() if k!='observation_id'}}
                    result['additions']=[]
            return response(result)
        if phase=='identity_verification':
            partitions+=1;ok=not reject_first_identity or partitions>1
            return response(dict(decisions=[dict(group_id=g['group_id'],distinct=ok,evidence=source if ok else '',
                issues=[] if ok else ['identity distinction uncertain']) for g in data['groups']]))
        if phase=='missing_verification':
            return response(dict(decisions=[dict(proposal_id=p['proposal_id'],supported=True,
                already_represented=False,matching_observation_ids=[],evidence=source,issues=[]) for p in data['proposals']]))
        result=positive(data)
        if not fixed_third:
            for decision,o in zip(result['decisions'],data['observations'],strict=True):
                if o['claim']['attribute']=='timeout seconds':
                    decision.update(entailed=False,complete=False,evidence='',issues=['missing staging scope'])
        return response(result)
    source_object=Source('web_document','https://fixture.example/test')
    values,diag=asyncio.run(extract_verified(dict(id='p00',text=source,source=source_object,
        observed_at=datetime.now(timezone.utc)),provider=provider))
    assert diag['verified'] and diag['retry_count']==(2 if reject_first_identity else 1)
    assert len(values)==3 and {o.observation_id for o in values}=={'p00:0','p00:1','p00:2'}
    assert generations==(['extraction','mixed_repair','identity_repair'] if reject_first_identity else ['extraction','mixed_repair'])
    assert all(o.source is source_object and o.metadata['chunk_id']=='p00' for o in values)
    repaired=next(o for o in values if o.observation_id=='p00:2')
    assert repaired.claim.value['assertion']=='The staging timeout is 8.'


def test_true_contradictions_remain_one_conflicting_property():
    from omneum.normalization import _source_conflict_pairs
    source='The staging timeout is 8. A contradictory statement says the staging timeout is 9.'
    records=[dict(claim=dict(entity_namespace='service',entity='staging worker',attribute='timeout_seconds',
        value=dict(assertion=f'The staging timeout is {n}.',scope='staging')),
        evidence=source) for n in (8,9)]
    calls=0
    async def provider(prompt):
        nonlocal calls
        if 'Input JSON:\n' not in prompt:return response(records)
        data=json.loads(prompt.split('Input JSON:\n')[1])
        if data['phase']=='identity_repair':
            calls+=1
            return response(dict(identities=[dict(observation_id=o['observation_id'],entity_namespace='service',
                entity='staging worker',attribute='timeout_'+str(i)) for i,o in enumerate(data['observations'])]))
        if data['phase']=='identity_verification':
            return response(dict(decisions=[dict(group_id=g['group_id'],distinct=False,evidence=source,
                issues=['Same scoped property; values conflict']) for g in data['groups']]))
        if data['phase']=='missing_verification':
            return response(dict(decisions=[dict(proposal_id=p['proposal_id'],supported=True,
                already_represented=False,matching_observation_ids=[],evidence=source,issues=[]) for p in data['proposals']]))
        return response(positive(data))
    src=Source('web_document','https://fixture.example/test');now=datetime.now(timezone.utc)
    original=[Observation(str(i),src,Claim(**r['claim']),observed_at=now) for i,r in enumerate(records)]
    assert len(_source_conflict_pairs(original))==1
    values,diag=asyncio.run(extract_verified(dict(id='p00',text=source,source=src,observed_at=now),provider=provider))
    assert not values and not diag['verified'] and calls==2 and diag['retry_count']==2


def test_one_ungrounded_positive_does_not_poison_other_missing_decisions():
    source='A fixture has population 12. Its area is 9.'
    records=[dict(claim=dict(entity_namespace='town',entity='fixture',attribute=attribute,
        value=dict(assertion=assertion)),evidence=source) for attribute,assertion in
        [('population','The fixture has population 12.'),('area','Its area is 9.')]]
    async def provider(prompt):
        data=json.loads(prompt.split('Input JSON:\n')[1])
        return response(dict(decisions=[dict(proposal_id=p['proposal_id'],supported=True,already_represented=False,
            matching_observation_ids=[],evidence='A fixture has population 12.',issues=[]) for p in data['proposals']]))
    missing,reviews=asyncio.run(_verify_missing(records,[],source,provider,'p00'))
    assert len(missing)==1 and missing[0]['claim']['attribute']=='population'
    assert reviews[0]['supported'] and not reviews[1]['supported']
    assert reviews[1]['verification_abstained'] and reviews[1]['model_decision']['supported']


def test_insufficient_quote_is_widened_without_changing_fact_or_losing_original_span():
    source='A fixture opened. Its opening year was 2010.';quote='A fixture opened.'
    record=dict(claim=dict(entity_namespace='place',entity='fixture',attribute='opening_year',
        value=dict(assertion='The fixture opened in 2010.')),evidence=quote)
    async def provider(prompt):
        if 'Input JSON:\n' not in prompt:return response([record])
        data=json.loads(prompt.split('Input JSON:\n')[1]);return response(positive(data))
    values,diag=asyncio.run(extract_verified(dict(id='p00',text=source,
        source=Source('web_document','https://fixture.example/test'),observed_at=datetime.now(timezone.utc)),provider=provider))
    assert diag['verified'] and diag['retry_count']==0
    assert values[0].claim.value==record['claim']['value'] and values[0].observation_id=='p00:0'
    assert values[0].metadata['source_span']['text']==source
    assert values[0].metadata['extraction_source_span']==dict(start=0,end=len(quote),text=quote)


def test_parenthetical_role_rule_is_consistent_in_both_verifiers():
    source='Fixture Jr. was the son of Fixture Sr. (judge).'
    claim=Claim('person','Fixture Sr.','profession',dict(assertion='Fixture Sr. was a judge.'))
    prompts=[]
    async def provider(prompt):
        prompts.append(prompt);assert 'parenthetical descriptors are source assertions' in prompt
        data=json.loads(prompt.split('Input JSON:\n')[1])
        if data['phase']=='missing_verification':
            return response(dict(decisions=[dict(proposal_id='0',supported=True,already_represented=False,
                matching_observation_ids=[],evidence=source,issues=[])]))
        return response(positive(data))
    observation=Observation('p00:0',Source('web_document','https://fixture.example/test'),claim,
        observed_at=datetime.now(timezone.utc),metadata={})
    checked,audit=asyncio.run(verify_observations([observation],source_text=source,provider=provider))
    assert checked and audit['status']=='verified'
    missing,_=asyncio.run(_verify_missing([dict(claim=dict(entity_namespace='person',entity='Fixture Sr.',
        attribute='profession',value=claim.value),evidence=source)],[],source,provider,'p00'))
    assert len(missing)==1 and len(prompts)==2
