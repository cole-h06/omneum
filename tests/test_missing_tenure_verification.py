"""A missing-fact proposal must preserve source tense and tenure boundaries."""
import asyncio
import json

import pytest

from omneum._extraction_verification import _verify_missing


@pytest.mark.parametrize('ongoing', [False, True])
def test_continuing_tenure_requires_source_support(ongoing):
    source = ('The officer has been in office since February 2, 2009.' if ongoing else
              'The officer served from February 2–24, 2009, then stepped down.')
    record = dict(claim=dict(entity_namespace='person', entity='officer', attribute='tenure',
        value=dict(assertion='The officer has been in office since February 2, 2009.')), evidence=source)

    async def provider(prompt):
        data = json.loads(prompt.split('Input JSON:\n')[1])
        assert data['source_text'] == source and data['proposals'][0]['claim']['value'] == record['claim']['value']
        if data['phase'] == 'continuity_verification':
            assert 'Another later term does not erase a stated gap' in prompt
            return {'text': json.dumps(dict(decisions=[dict(proposal_id='0', supported=ongoing,
                reason='The source explicitly supports continued tenure.' if ongoing else 'The stated term ended.',
                evidence=source)]))}
        assert 'including its tense and any end boundary' in prompt
        # Reproduce the recorded first judge's false positive on the ended term.
        return {'text': json.dumps(dict(decisions=[dict(proposal_id='0', supported=True,
            already_represented=False, matching_observation_ids=[], evidence=source,
            issues=[])]))}

    missing, reviews = asyncio.run(_verify_missing([record], [], source, provider, 'p00'))
    assert bool(missing) is ongoing and reviews[0]['supported'] is ongoing
    assert reviews[0]['continuity_review']['supported'] is ongoing
