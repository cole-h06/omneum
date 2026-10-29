"""Graph-property partition decisions must not ask whether people are distinct."""
import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from jsonschema import validate

from omneum._extraction_verification import verify_identity_partition
from benchmarks.context_selection.public_datasets.mapping import response_schema
from benchmarks.context_selection.public_datasets.preprocessing import mapping_cache


FIXTURE = next(f for f in json.loads((Path(__file__).parent/'fixtures/hotpotqa_nonexclusive_relationships.json').read_text())
               if f['case_id'] == '5abfcdb55542993fe9a41e7b')


@pytest.mark.parametrize('supported', [True, False])
def test_source_listed_roles_use_explicit_partition_verdict(supported):
    targets = {}
    records = []
    for identifier, identity in FIXTURE['identities'].items():
        original = FIXTURE['records'][int(identifier.split(':')[1])]
        targets[identifier] = dict(observation_id=identifier, claim=original['claim'],
                                  source_span=dict(text=original['evidence']))
        records.append(dict(observation_id=identifier, claim={**original['claim'], **identity}))

    async def provider(prompt):
        data = json.loads(prompt.split('Input JSON:\n')[1])
        assert data['decision_contract'] == 'property_partition_v2'
        schema = response_schema(prompt)
        properties = list(schema['properties']['decisions']['items']['properties'])
        assert properties.index('reason') < properties.index('supported_partition')
        assert 'distinct' not in properties
        reply = dict(decisions=[dict(group_id=g['group_id'],
            reason='The source explicitly lists concurrent roles of the same person.',
            supported_partition=supported, evidence=FIXTURE['source_text'], issues=[])
            for g in data['groups']])
        validate(reply, schema)
        return {'text': json.dumps(reply)}

    rejected = asyncio.run(verify_identity_partition(targets, {'text': json.dumps(records)},
                                                      FIXTURE['source_text'], provider))
    # A negative verdict stays rejected even if its reason describes valid roles.
    assert rejected == (set() if supported else set(targets))


def test_repair_candidates_require_explicit_opt_in_and_remain_unverified(tmp_path):
    generator = SimpleNamespace(identity=dict(name='unit-model', digest='unit-digest'), options={})
    (tmp_path/'manifest.json').write_text(json.dumps(dict(generator=generator.identity, generator_options={})))
    prompt = 'Input JSON:\n' + json.dumps(dict(phase='identity_repair', identity_format='target_slots_v1',
        observations=[dict(observation_id='p00:0')]))
    proposal = dict(identities={'p00:0':dict(reason='Untrusted candidate', identity=dict(
        entity_namespace='person', entity='Mira', attribute='has_role'))})
    path = tmp_path/'mapping-call-000000.json'
    path.write_text(json.dumps(dict(prompt=prompt,request=dict(model='unit-model'),seconds=1.0,
        response=dict(done=True,done_reason='stop',response=json.dumps(proposal)))))
    before = path.read_bytes()
    assert not mapping_cache(tmp_path, generator)
    candidates = mapping_cache(tmp_path, generator, repair_candidates=True)
    assert len(candidates) == 1
    assert json.loads(next(iter(candidates.values()))[0]['response']['response']) == proposal
    assert 'verified' not in next(iter(candidates.values()))[0]
    assert path.read_bytes() == before
