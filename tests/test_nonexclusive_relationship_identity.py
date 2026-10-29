"""Explicit role/name participants are distinct relations of the same subject."""
import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path

import pytest

from omneum import Source
from omneum._extraction_verification import extract_verified


FIXTURES = json.loads((Path(__file__).parent / 'fixtures/hotpotqa_nonexclusive_relationships.json').read_text())


@pytest.mark.parametrize('fixture', FIXTURES, ids=lambda f: f['case_id'])
def test_recorded_nonexclusive_relationships_preserve_values_and_ids(fixture):
    text, pid = fixture['source_text'], fixture['passage_id']

    async def provider(prompt):
        if 'Input JSON:\n' not in prompt:
            return {'text': json.dumps(fixture['records'])}
        data = json.loads(prompt.split('Input JSON:\n')[1])
        phase = data['phase']
        if phase == 'identity_repair':
            return {'text': json.dumps(dict(identities={i: dict(
                reason='Source-listed non-exclusive relationship participant', identity=identity)
                for i, identity in fixture['identities'].items()}))}
        if phase == 'identity_verification':
            assert 'Multiple explicitly\n   listed common names' in prompt
            assert 'Concurrent roles do not have to be mutually exclusive' in prompt
            return {'text': json.dumps(dict(decisions=[dict(group_id=g['group_id'], distinct=True,
                evidence=text, issues=[]) for g in data['groups']]))}
        if phase == 'missing_verification':
            return {'text': json.dumps(dict(decisions=[dict(proposal_id=p['proposal_id'], supported=True,
                already_represented=False, matching_observation_ids=[], evidence=text, issues=[])
                for p in data['proposals']]))}
        return {'text': json.dumps(dict(decisions=[dict(observation_id=o['observation_id'], entailed=True,
            complete=True, evidence=text, issues=[]) for o in data['observations']], missing=[]))}

    observations, diagnostics = asyncio.run(extract_verified(dict(id=pid, text=text,
        source=Source('web_document', 'https://fixture.example/nonexclusive'),
        observed_at=datetime.now(timezone.utc)), provider=provider))
    assert diagnostics['verified'] and diagnostics['retry_count'] == 1
    assert len(observations) == len(fixture['records'])
    assert {o.observation_id for o in observations} == {f'{pid}:{i}' for i in range(len(observations))}
    assert all(o.claim.value == fixture['records'][int(o.observation_id.split(':')[1])]['claim']['value']
               for o in observations)
