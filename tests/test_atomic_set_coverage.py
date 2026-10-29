"""A source-supported conjunction must not become a duplicate credit node."""
import asyncio
from datetime import datetime, timezone
import json

from omneum import Source
from omneum._extraction_verification import extract_verified


def test_pending_atomic_credits_cover_aggregate_without_starving_other_repairs():
    source = 'Mira was born in Rome, acted in Film A and Film B, and studied history.'
    def record(attribute, assertion):
        return dict(claim=dict(entity_namespace='person', entity='Mira', attribute=attribute,
            value=dict(assertion=assertion, scope=None, condition=None, ordering=None, modality='report')),
            evidence=source)
    birth = record('birthplace', 'Mira was born in Rome.')
    credits = [record('acted_in', f'Mira acted in Film {letter}.') for letter in ('A', 'B')]
    aggregate = record('acted_in', 'Mira acted in Film A and Film B.')
    education = record('education', 'Mira studied history.')
    repairs = []

    async def provider(prompt):
        if 'Input JSON:\n' not in prompt:
            assert not repairs
            return {'text': json.dumps([birth, *credits])}
        data = json.loads(prompt.split('Input JSON:\n')[1])
        phase = data['phase']
        if phase == 'missing_verification':
            assert 'UNION of the cited candidate facts' in prompt
            decisions = []
            for proposal in data['proposals']:
                wanted = proposal['claim']['value']
                matching = [o['observation_id'] for o in data['observations'] if o['claim']['value'] == wanted]
                if wanted == aggregate['claim']['value']:
                    matching = [o['observation_id'] for o in data['observations']
                                if o['claim']['value'] in [c['claim']['value'] for c in credits]]
                    if len(matching) != 2:
                        matching = []
                decisions.append(dict(proposal_id=proposal['proposal_id'], supported=True,
                    already_represented=bool(matching), matching_observation_ids=matching, evidence=source, issues=[]))
            return {'text': json.dumps(dict(decisions=decisions))}
        if phase == 'mixed_repair':
            repairs.append(data)
            assert {o['observation_id'] for o in data['observations']} == {'p00:1', 'p00:2'}
            assert data['other_repairs']['missing'] == []
            assert set(r['observation_id'] for r in data['other_repairs']['rejected']) == {'p00:3'}
            return {'text': json.dumps(dict(identities={f'p00:{i+1}':dict(reason='Named work participant',
                identity=dict(entity_namespace='performance_credit',entity=f'Mira | Film {letter}', attribute='performed_in'))
                for i,letter in enumerate(('A','B'))},records={'p00:3':education},additions=[]))}
        if phase == 'identity_verification':
            return {'text': json.dumps(dict(decisions=[dict(group_id=g['group_id'],reason='Different named works',
                supported_partition=True,evidence=source,issues=[]) for g in data['groups']]))}
        assert phase == 'extraction_verification'
        return {'text': json.dumps(dict(decisions=[dict(observation_id=o['observation_id'],entailed=True,
            complete=True,evidence=source,issues=[]) for o in data['observations']],missing=[aggregate,education]))}

    observations,diagnostics = asyncio.run(extract_verified(dict(id='p00',text=source,
        source=Source('web_document','https://fixture.example/atomic-coverage'),
        observed_at=datetime.now(timezone.utc)),provider=provider))
    assert diagnostics['verified'] and diagnostics['retry_count'] == 1 and len(repairs) == 1
    assert {o.observation_id for o in observations} == {'p00:0','p00:1','p00:2','p00:3'}
    assert all(o.claim.value != aggregate['claim']['value'] for o in observations)
    proof = next(r for r in diagnostics['trace'][-1]['verification']['coverage_decisions']
                 if r['proposal']['claim']['value'] == aggregate['claim']['value'])
    assert proof['supported'] and proof['already_represented']
    assert set(proof['matching_observation_ids']) == {'p00:1','p00:2'}
