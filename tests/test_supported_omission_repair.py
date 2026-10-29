"""Supported missing relations and rejected extras share one bounded repair."""
import asyncio
from datetime import datetime, timezone
import json

from omneum import Source
from omneum._extraction_verification import extract_verified


def test_missing_multivalued_relations_do_not_wait_until_final_retry():
    text = 'Mira was born in 1950. Mira was a composer and painter.'
    def record(attribute, assertion):
        return dict(claim=dict(entity_namespace='person', entity='Mira', attribute=attribute,
                               value=dict(assertion=assertion)), evidence=text)
    birth = record('birth_year', 'Mira was born in 1950.')
    unsupported = record('occupation', 'Mira was an astronaut.')
    roles = [record('occupation', f'Mira was a {role}.') for role in ('composer', 'painter')]
    repairs = []

    async def provider(prompt):
        if 'Input JSON:\n' not in prompt:
            assert not repairs
            return {'text': json.dumps([birth, unsupported])}
        data = json.loads(prompt.split('Input JSON:\n')[1])
        phase = data['phase']
        if phase == 'mixed_repair':
            repairs.append(data)
            assert {o['observation_id'] for o in data['observations']} == {'p00:2', 'p00:3'}
            assert data['other_repairs']['missing'] == []
            return {'text': json.dumps(dict(identities={f'p00:{i+2}': dict(
                reason='Explicit non-exclusive role participant', identity=dict(
                    entity_namespace='occupation', entity=f'Mira | {role}', attribute='has_role'))
                for i, role in enumerate(('composer', 'painter'))}, records={'p00:1': None}, additions=[]))}
        if phase == 'identity_verification':
            return {'text': json.dumps(dict(decisions=[dict(group_id=g['group_id'], distinct=True,
                evidence=text, issues=[]) for g in data['groups']]))}
        if phase == 'missing_verification':
            return {'text': json.dumps(dict(decisions=[dict(proposal_id=p['proposal_id'], supported=True,
                already_represented=False, matching_observation_ids=[], evidence=text, issues=[])
                for p in data['proposals']]))}
        return {'text': json.dumps(dict(decisions=[dict(observation_id=o['observation_id'],
            entailed=o['claim']['value'] != unsupported['claim']['value'], complete=True,
            evidence=text, issues=['Not in source'] if o['claim']['value'] == unsupported['claim']['value'] else [])
            for o in data['observations']], missing=[] if repairs else roles))}

    source = Source('web_document', 'https://fixture.example/roles')
    observations, diagnostics = asyncio.run(extract_verified(dict(id='p00', text=text,
        source=source, observed_at=datetime.now(timezone.utc)), provider=provider))
    assert diagnostics['verified'] and diagnostics['retry_count'] == 1 and len(repairs) == 1
    assert {o.observation_id for o in observations} == {'p00:0', 'p00:2', 'p00:3'}
    assert {o.claim.value['assertion'] for o in observations} == {
        r['claim']['value']['assertion'] for r in [birth, *roles]}
    assert all(o.source == source and o.metadata['chunk_id'] == 'p00' for o in observations)
