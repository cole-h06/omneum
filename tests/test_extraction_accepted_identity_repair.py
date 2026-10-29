"""Supported repairs must retain their IDs and be checked against accepted facts."""
import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path

import pytest

from omneum import Source
from omneum._extraction_verification import _candidates, extract_verified


def test_recorded_accepted_property_collision_keeps_constructed_claim_and_span():
    fixture = json.loads((Path(__file__).parent/'fixtures/hotpotqa_accepted_property_collision.json').read_text())
    chunk = dict(id='p00', text=fixture['source_text'], source=Source('web_document', 'https://fixture.example/recorded'),
                 observed_at=datetime.now(timezone.utc))
    anchor = fixture['accepted']
    accepted, rejected, _ = _candidates(chunk, {'text': json.dumps([
        dict(claim=anchor['claim'], evidence=anchor['source_span']['text'])])}, [], 0)
    assert len(accepted) == 1 and not rejected
    target = fixture['rejected']
    identifier = target['observation_id']
    pending, rejected, _ = _candidates(chunk, {'text': json.dumps([
        dict(target['record'], observation_id=identifier)])}, accepted, 1, {identifier: target})
    assert not pending and len(rejected) == 1
    assert rejected[0]['observation_id'] == identifier
    assert rejected[0]['claim']['value'] == target['record']['claim']['value']
    assert rejected[0]['source_span']['text'] == target['record']['evidence']


@pytest.mark.parametrize('distinct_scope', [False, True])
def test_missing_fact_identity_repair_checks_immutable_accepted_anchor(distinct_scope):
    source = ('The staging worker timeout is 8. The production worker timeout is 9.' if distinct_scope else
              'The staging worker timeout is 8. A contradictory statement says the staging worker timeout is 9.')
    def record(number):
        scope = 'production' if distinct_scope and number == 9 else 'staging'
        return dict(claim=dict(entity_namespace='service', entity='worker', attribute='timeout_seconds',
            value=dict(assertion=f'The {scope} worker timeout is {number}.', scope=scope)), evidence=source)
    first, missing = record(8), record(9)
    phases = []
    async def provider(prompt):
        if 'Input JSON:\n' not in prompt:
            return {'text': json.dumps([missing] if 'Repair request JSON:' in prompt else [first])}
        data = json.loads(prompt.split('Input JSON:\n')[1])
        phase = data['phase']; phases.append(phase)
        if phase == 'identity_repair':
            assert [o['observation_id'] for o in data['observations']] == ['p00:1']
            return {'text': json.dumps(dict(identities={'p00:1': dict(reason='Explicit source scope', identity=dict(
                entity_namespace='service', entity='worker | production' if distinct_scope else 'worker',
                attribute='timeout_seconds' if distinct_scope else 'timeout_nine'))}))}
        if phase == 'identity_verification':
            assert {o['observation_id'] for g in data['groups'] for o in g['assertions']} == {'p00:0', 'p00:1'}
            return {'text': json.dumps(dict(decisions=[dict(group_id=g['group_id'], distinct=distinct_scope,
                evidence=source, issues=[] if distinct_scope else ['Competing values of one scoped property'])
                for g in data['groups']]))}
        if phase == 'missing_verification':
            return {'text': json.dumps(dict(decisions=[dict(proposal_id=p['proposal_id'], supported=True,
                already_represented=False, matching_observation_ids=[], evidence=source, issues=[])
                for p in data['proposals']]))}
        represented = any(o['claim']['value'] == missing['claim']['value'] for o in data['observations'])
        return {'text': json.dumps(dict(decisions=[dict(observation_id=o['observation_id'], entailed=True,
            complete=True, evidence=source, issues=[]) for o in data['observations']],
            missing=[] if represented else [missing]))}
    observations, diagnostics = asyncio.run(extract_verified(dict(id='p00', text=source,
        source=Source('web_document', 'https://fixture.example/scoped'), observed_at=datetime.now(timezone.utc)),
        provider=provider))
    assert diagnostics['retry_count'] == (1 if distinct_scope else 2)
    assert 'identity_verification' in phases
    assert diagnostics['verified'] is distinct_scope
    if distinct_scope:
        assert {o.observation_id for o in observations} == {'p00:0', 'p00:1'}
        assert {json.dumps(o.claim.value, sort_keys=True) for o in observations} == {
            json.dumps(r['claim']['value'], sort_keys=True) for r in (first, missing)}
    else:
        assert not observations
