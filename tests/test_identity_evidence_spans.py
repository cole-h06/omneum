"""An identity group's evidence must cover every source-supported assertion."""
import asyncio
from copy import deepcopy
import json
from pathlib import Path

import pytest
from jsonschema import ValidationError, validate

from omneum._extraction_verification import verify_identity_partition
from benchmarks.context_selection.public_datasets.mapping import response_schema


FIXTURES = json.loads((Path(__file__).parent / 'fixtures/hotpotqa_identity_evidence_spans.json').read_text())


@pytest.mark.parametrize('fixture', FIXTURES, ids=lambda f: f['case_id'])
@pytest.mark.parametrize('complete_evidence', [False, True])
def test_recorded_multi_event_identity_evidence(fixture, complete_evidence):
    before = json.dumps(fixture, sort_keys=True)

    async def provider(prompt):
        assert 'EVERY assertion' in prompt
        assert 'ENTIRE\noriginal source verbatim' in prompt
        data = json.loads(prompt.split('Input JSON:\n')[1])
        assert data['source_text'] == fixture['source_text']
        decisions = [dict(d, evidence=fixture['source_text']) if complete_evidence else dict(d)
                     for d in fixture['decisions']]
        return {'text': json.dumps({'decisions': decisions})}

    records = deepcopy(fixture['records'])
    for record in records:
        # The recorded repair also inferred 1985 from 1935 + 50 years.
        # Isolate the evidence-span regression using the actual relative scope.
        record['claim']['entity'] = record['claim']['entity'].replace(' | 1985', ' | 50 years later')
    rejected = asyncio.run(verify_identity_partition(fixture['targets'],
        {'text': json.dumps(records)}, fixture['source_text'], provider))
    assert rejected == (set() if complete_evidence else set(fixture['targets']))
    assert json.dumps(fixture, sort_keys=True) == before


def test_recorded_computed_event_year_is_rejected_before_model_call():
    fixture = next(f for f in FIXTURES if f['case_id'] == '5a8a5c0d554299515336137b')
    assert '1985' not in fixture['source_text']
    reviews = []

    async def provider(prompt):
        pytest.fail('An identity with an unstated computed year cannot reach the model audit')

    rejected = asyncio.run(verify_identity_partition(fixture['targets'],
        {'text': json.dumps(fixture['records'])}, fixture['source_text'], provider, diagnostics=reviews))
    assert rejected == set(fixture['targets'])
    assert any('absent from the source' in issue for review in reviews for issue in review['decision']['issues'])


@pytest.mark.parametrize('fixture', FIXTURES, ids=lambda f: f['case_id'])
def test_versioned_identity_schema_requires_full_source_preserves_old_receipts(fixture):
    data = dict(phase='identity_verification', source_text=fixture['source_text'],
                groups=[dict(group_id=d['group_id']) for d in fixture['decisions']])
    def prompt():
        return 'Input JSON:\n' + json.dumps(data)
    original = dict(decisions=fixture['decisions'])
    validate(original, response_schema(prompt()))
    data['evidence_scope'] = 'whole_source_v1'
    with pytest.raises(ValidationError):
        validate(original, response_schema(prompt()))
    validate(dict(decisions=[dict(d, evidence=fixture['source_text'])
                             for d in fixture['decisions']]), response_schema(prompt()))
