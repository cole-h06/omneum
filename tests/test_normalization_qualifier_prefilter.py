import asyncio,json
from dataclasses import replace
from datetime import datetime,timezone
import pytest
from omneum import Claim,Observation,Source
from omneum.context_selection import claim_id
from omneum.normalization import _align_atomic_claims

def observation(i,value):
    return Observation(str(i),Source('web_document',f'https://fixture.example/{i}'),
        # Schema aliases carry no numeric scope; quantity guards have separate fixtures.
        Claim('service','worker',f'timeout_alias_{chr(97+i//26)}{chr(97+i%26)}',value),observed_at=datetime(2026,1,1,tzinfo=timezone.utc),
        parent_observation_ids=(),metadata=dict(chunk_id=str(i)))

@pytest.mark.parametrize('field',['scope','condition','ordering','modality','method','endpoint','exception','exceptions','unit','units'])
def test_protected_qualifier_mismatch_cannot_trigger_model_call(field):
    values=[observation(0,dict(assertion='The worker timeout is 8.',**{field:'alpha'})),
            observation(1,dict(assertion='The worker timeout is 8.',**{field:'beta'}))]
    async def unexpected(prompt):raise AssertionError('A deterministic rejection must not call the model')
    result=asyncio.run(_align_atomic_claims(values,provider=unexpected))
    assert result==tuple(values)

def test_nested_qualifiers_are_not_lost_by_candidate_filtering():
    values=[observation(0,dict(assertion='The worker timeout is 8.',details=dict(condition='startup'))),
            observation(1,dict(assertion='The worker timeout is 8.',details=dict(condition='shutdown')))]
    async def unexpected(prompt):raise AssertionError('Nested qualifier mismatch must be filtered')
    assert asyncio.run(_align_atomic_claims(values,provider=unexpected))==tuple(values)

def test_transitive_unions_preserve_qualifier_groups_and_provenance():
    values=[observation(i,dict(assertion='The worker timeout is 8.',scope=['alpha','beta','gamma','delta'][i%4],
                             modality='reported_state')) for i in range(28)]
    calls=[]
    async def provider(prompt):
        data=json.loads(prompt.split('Input JSON:\n')[1]);calls.append(data)
        if data['phase']=='atomic_equivalence':
            assert all(pair['left']['value']['scope']==pair['right']['value']['scope'] for pair in data['pairs'])
            return {'text':json.dumps(dict(equivalent=[True]*len(data['pairs'])))}
        return {'text':json.dumps(dict(equivalent=True))}
    result=asyncio.run(_align_atomic_claims(values,provider=provider,
        chunk_texts={o.observation_id:'The worker timeout is 8.' for o in values}))
    assert len({claim_id(o.claim) for o in result})==4
    for before,after in zip(values,result,strict=True):
        assert replace(after,claim=before.claim)==before
        assert after.claim.value['scope']==before.claim.value['scope']
    assert all(len(c['pairs'])<=12 for c in calls if c['phase']=='atomic_equivalence')

def test_schema_only_lexical_overlap_does_not_remove_an_eligible_semantic_alias():
    a=Observation('a',Source('web_document','https://fixture.example/a'),Claim('material','water','freezes',dict(assertion='Water freezes.',modality='reported_state')),observed_at=datetime.now(timezone.utc),metadata=dict(chunk_id='a'))
    b=Observation('b',Source('web_document','https://fixture.example/b'),Claim('compound','aqua','solidifies',dict(assertion='Aqua solidifies.',modality='reported_state')),observed_at=datetime.now(timezone.utc),metadata=dict(chunk_id='b'))
    phases=[]
    async def provider(prompt):
        data=json.loads(prompt.split('Input JSON:\n')[1]);phases.append(data['phase'])
        return {'text':json.dumps(dict(equivalent=[True]*len(data['pairs']) if data['phase']=='atomic_equivalence' else True))}
    result=asyncio.run(_align_atomic_claims([a,b],provider=provider,chunk_texts=dict(a='Water is aqua. It freezes.',b='Aqua is water. It solidifies.')))
    assert len({claim_id(o.claim) for o in result})==1
    assert 'atomic_equivalence' in phases and 'verify' in phases


def test_missing_and_null_qualifiers_remain_compatible():
    values=[observation(0,dict(assertion='The worker timeout is 8.',scope=None)),
            observation(1,dict(assertion='The worker timeout is 8.'))]
    async def provider(prompt):
        data=json.loads(prompt.split('Input JSON:\n')[1])
        return {'text':json.dumps(dict(equivalent=[True]*len(data['pairs']) if data['phase']=='atomic_equivalence' else True))}
    result=asyncio.run(_align_atomic_claims(values,provider=provider,
        chunk_texts={o.observation_id:'The worker timeout is 8.' for o in values}))
    assert len({claim_id(o.claim) for o in result})==1


def test_malformed_discovery_decisions_do_not_authorize_merges():
    values=[observation(i,dict(assertion='The worker timeout is 8.',scope='alpha')) for i in range(13)]
    async def provider(prompt):return {'text':json.dumps(dict(equivalent=[True]))}
    assert asyncio.run(_align_atomic_claims(values,provider=provider))==tuple(values)
