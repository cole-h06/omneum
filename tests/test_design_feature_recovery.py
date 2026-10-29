import asyncio,json
from copy import deepcopy
from datetime import datetime,timezone
from pathlib import Path
from omneum import Source
from omneum._extraction_verification import extract_verified,identity_prompt
fixture=next(f for f in json.loads((Path(__file__).parent/'fixtures/hotpotqa_identity_repairs.json').read_text())
             if f['case_id']=='5abc089b5542993f40c73c57')
source=fixture['source_text']
records=[dict(record,observation_id=f'p00:{i}',source_span=dict(text=record['evidence']))
         for i,record in enumerate(fixture['initial_records'])]

def test_design_goal_and_construction_keep_original_subject_values_and_ids():
    original=deepcopy(records);generations=[]
    async def provider(prompt):
        if 'Input JSON:\n' not in prompt:
            return {'text':json.dumps([dict(claim=r['claim'],evidence=r['source_span']['text']) for r in records])}
        d=json.loads(prompt.split('Input JSON:\n')[1]);phase=d['phase']
        if phase=='identity_repair':
            generations.append(d)
            assert 'A design goal/intended use, physical construction, and component membership' in prompt
            return {'text':json.dumps(dict(identities={o['observation_id']:dict(reason='Explicit design objective versus physical construction',identity=dict(entity_namespace=o['claim']['entity_namespace'],entity=o['claim']['entity'],attribute={'p00:1':'design_goal','p00:2':'case_construction'}[o['observation_id']])) for o in d['observations']}))}
        if phase=='identity_verification':
            assert 'THREE ALTERNATIVE grounds' in prompt
            return {'text':json.dumps(dict(decisions=[dict(group_id=g['group_id'],distinct=True,evidence=source,issues=[]) for g in d['groups']]))}
        if phase=='missing_verification':
            return {'text':json.dumps(dict(decisions=[dict(proposal_id=p['proposal_id'],supported=True,already_represented=False,matching_observation_ids=[],evidence=source,issues=[]) for p in d['proposals']]))}
        return {'text':json.dumps(dict(decisions=[dict(observation_id=o['observation_id'],entailed=True,complete=True,evidence=source,issues=[]) for o in d['observations']],missing=[]))}
    src=Source('web_document','https://fixture.example/recorded-product')
    observations,diag=asyncio.run(extract_verified(dict(id='p00',text=source,source=src,observed_at=datetime.now(timezone.utc)),provider=provider))
    assert diag['verified'] and diag['retry_count']==1 and len(generations)==1
    assert len(observations)==5 and {o.observation_id for o in observations}=={r['observation_id'] for r in records}
    assert all(o.claim.value==records[int(o.observation_id.split(':')[1])]['claim']['value'] for o in observations)
    assert all(o.source is src and o.metadata['chunk_id']=='p00' for o in observations)
    assert {o.claim.entity for o in observations if o.observation_id in ('p00:1','p00:2')}=={'LanSlide Gaming PCs'}
    assert records==original
