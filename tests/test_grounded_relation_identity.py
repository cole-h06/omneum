"""Recorded lexical and route predicates retain source-grounded identities."""
from copy import deepcopy
import json
from pathlib import Path

from omneum._extraction_verification import grounded_relation_identity, identity_records, source_qualifications


FIXTURES = json.loads((Path(__file__).parent/'fixtures/hotpotqa_grounded_relation_identities.json').read_text())


def test_recorded_route_and_word_identities_preserve_facts_and_original_ids():
    before = deepcopy(FIXTURES)
    for fixture in FIXTURES:
        result = identity_records({'text': json.dumps(dict(identities=fixture['identities']))}, fixture['targets'])
        records = json.loads(result['text'])
        assert {r['observation_id'] for r in records} == set(fixture['targets'])
        for record in records:
            original = fixture['targets'][record['observation_id']]
            assert record['claim']['value'] == original['claim']['value']
            assert record['evidence'] == original['source_span']['text']
            assert record['claim']['attribute'] == ('course' if fixture['case_id'].startswith('5ab4') else 'means')
        if fixture['case_id'].startswith('5ab4'):
            assert {r['claim']['entity'].split(' | ')[1] for r in records} == {
                'Paterno', 'Tramutola, Viggiano, and Grumento Nova',
                "Armento, Missanello, Aliano, and Sant'Arcangelo"}
    assert FIXTURES == before


def test_route_direction_outcomes_cannot_create_different_segment_identities():
    source = 'Agri flows north near Paterno. Agri flows south near Paterno.'
    identities = []
    for direction in ('north', 'south'):
        original = dict(claim=dict(entity_namespace='river', entity='Agri', attribute='flow_path',
            value=dict(assertion=f'The river flows {direction} near Paterno.')), source_span=dict(text=source))
        identities.append(grounded_relation_identity(original, dict(entity_namespace='flow_path',
            entity=f'Agri | {direction} near Paterno', attribute='flow_path')))
    assert identities[0] == identities[1] == dict(entity_namespace='river_course_segment',
        entity='Agri | Paterno', attribute='course')


def test_unattested_place_is_not_silently_added_as_a_segment_participant():
    original = dict(claim=dict(entity_namespace='river', entity='Agri', attribute='flow_path',
        value=dict(assertion='The river flows north near Inventedville.')),
        source_span=dict(text='The river flows near Paterno.'))
    proposed = dict(entity_namespace='river', entity='Agri', attribute='flow_path')
    assert grounded_relation_identity(original, proposed) == proposed


def test_source_local_position_antecedents_and_compressed_range_endpoints():
    source = ('Mira is Deputy Clerk. That position has been hers since April 2000. '
              'She served in another office from February 2–24, 2009.')
    prompt = source_qualifications('Verify the source.\n\nInput JSON:\n{}', source)
    assert 'Resolve unambiguous source-local pronouns' in prompt
    assert 'explicitly states both\nendpoints' in prompt
    assert 'If the antecedent is ambiguous, reject' in prompt
    assert 'do not compute unstated calendar dates' in prompt
