"""An opaque action clause cannot repair a generic property collision."""
import asyncio
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path

from omneum import Claim, Observation, Source
from omneum._extraction_verification import verify_identity_partition


FIXTURE = json.loads((Path(__file__).parent/'fixtures/hotpotqa_category_identity_collision.json').read_text())


def test_recorded_category_bucket_proposal_has_actionable_failure_reason():
    async def provider(prompt):
        raise AssertionError('The unchanged generic predicate needs correction before semantic review')
    reviews = []
    rejected = asyncio.run(verify_identity_partition(FIXTURE['targets'],
        {'text': json.dumps(FIXTURE['records'])}, FIXTURE['source_text'], provider, diagnostics=reviews))
    assert rejected == set(FIXTURE['targets'])
    assert any('category bucket' in issue for r in reviews for issue in r['decision']['issues'])


def test_distinct_actual_relations_keep_original_subject_and_assertion_values():
    records = deepcopy(FIXTURE['records'])
    for record in records:
        original = FIXTURE['targets'][record['observation_id']]['claim']
        record['claim'].update(entity_namespace=original['entity_namespace'], entity=original['entity'],
            attribute={'p03:6': 'responded_to_advertisement', 'p03:8': 'moved_to'}[record['observation_id']])
    calls = []

    async def provider(prompt):
        data = json.loads(prompt.split('Input JSON:\n')[1]); calls.append(data)
        assert all('proposed_entity_components' in o for g in data['groups'] for o in g['assertions'])
        return {'text': json.dumps(dict(decisions=[dict(group_id=g['group_id'], distinct=True,
            evidence=FIXTURE['source_text'], issues=[]) for g in data['groups']]))}

    rejected = asyncio.run(verify_identity_partition(FIXTURE['targets'],
        {'text': json.dumps(records)}, FIXTURE['source_text'], provider))
    assert not rejected and len(calls) == 1
    assert all(r['claim']['value'] == FIXTURE['targets'][r['observation_id']]['claim']['value'] for r in records)


def test_repair_validation_keeps_immutable_accepted_anchor_in_pair_review():
    source = 'Mira answered an advertisement. Mira moved to Paris.'
    span = dict(start=0, end=len(source), text=source)
    anchor = Observation('p00:0', Source('web_document', 'https://fixture.example/actions'),
        Claim('person', 'Mira', 'action', dict(assertion='Mira answered an advertisement.')),
        observed_at=datetime.now(timezone.utc), metadata=dict(chunk_id='p00', source_span=span))
    original = dict(entity_namespace='person', entity='Mira', attribute='action',
                    value=dict(assertion='Mira moved to Paris.'))
    target = dict(observation_id='p00:1', claim=original, source_span=span)
    proposed = dict(observation_id='p00:1', claim=dict(original, attribute='moved_to'))

    async def provider(prompt):
        data = json.loads(prompt.split('Input JSON:\n')[1])
        assert {o['observation_id'] for g in data['groups'] for o in g['assertions']} == {'p00:0', 'p00:1'}
        return {'text': json.dumps(dict(decisions=[dict(group_id='0', distinct=True, evidence=source, issues=[])]))}

    assert not asyncio.run(verify_identity_partition({'p00:1': target},
        {'text': json.dumps([proposed])}, source, provider, anchors=[anchor]))
    assert anchor.claim.attribute == 'action'
