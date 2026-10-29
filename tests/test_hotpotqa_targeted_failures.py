"""Regressions from recorded public passages; providers below are unit doubles."""
import asyncio
from datetime import datetime, timezone
import json
import hashlib
from pathlib import Path

import pytest
from jsonschema import validate

from omneum import Claim, Observation, Source
from omneum._extraction_verification import (
    _candidates, _incomplete_estimate, _verify_missing, extract_verified,
    verify_observations,
)
from benchmarks.context_selection.public_datasets.mapping import response_schema
from benchmarks.context_selection.public_datasets.preprocessing import extraction_seeds


FIXTURES = json.loads((Path(__file__).parent / 'fixtures/hotpotqa_targeted_failures_20261028.json').read_text())


def chunk(name):
    f = FIXTURES[name]
    return dict(id=f['passage_id'], text=f['source'],
                source=Source('web_document', 'https://fixture.example/' + name),
                observed_at=datetime(2020, 1, 1, tzinfo=timezone.utc))


def response(data):
    return {'text': json.dumps(data)}


@pytest.mark.parametrize('supported', [True, False])
def test_hugler_full_later_interval_reason_before_verdict(supported):
    f = FIXTURES['hugler']
    record = next(r for r in f['initial'] if 'January 20, 2017' in r['claim']['value']['assertion'])
    o = Observation('p00:5', chunk('hugler')['source'], Claim(**record['claim']),
        observed_at=chunk('hugler')['observed_at'], metadata=dict(chunk_id='p00',
        source_span=dict(start=0, end=len(f['source']), text=f['source'])))

    async def provider(prompt):
        data = json.loads(prompt.split('Input JSON:\n')[1])
        assert data['decision_contract'] == 'source_support_v2'
        assert data['source_text'] == f['source']
        assert 'Read EVERY stated service interval' in prompt
        assert 'departure-date assertion' in prompt
        schema = response_schema(prompt)['properties']['decisions']['items']
        assert list(schema['properties'])[0] == 'reason'
        assert 'reason' in schema['required']
        if data['phase'] == 'missing_verification':
            verdict = dict(proposal_id='0', reason='The full source explicitly reports this later interval.',
                supported=supported, already_represented=supported,
                matching_observation_ids=['p00:5'] if supported else [],
                evidence=f['source'] if supported else '', issues=[] if supported else ['Rejected test verdict'])
            result = dict(decisions=[verdict])
        else:
            result = dict(decisions=[dict(observation_id='p00:5',
                reason='The full source explicitly reports this later interval.',
                entailed=supported, complete=True, evidence=f['source'] if supported else '',
                issues=[] if supported else ['Rejected test verdict'])], missing=[])
        validate(result, response_schema(prompt))
        return response(result)

    accepted, audit = asyncio.run(verify_observations([o], source_text=f['source'], provider=provider))
    assert bool(accepted) is supported  # Positive reasoning never overrides a negative verdict.
    missing, reviews = asyncio.run(_verify_missing([record], [o], f['source'], provider, 'p00'))
    assert not missing and reviews[0]['supported'] is supported
    assert audit['status'] == 'verified'


def test_jirisan_positive_source_review_regrounds_before_identity_freezes_quote():
    f = FIXTURES['jirisan']; c = chunk('jirisan'); calls = []
    original = f['initial'][0]['evidence']
    assert len(original) == 68

    async def provider(prompt):
        if 'Input JSON:\n' not in prompt:
            return response(f['initial'])
        data = json.loads(prompt.split('Input JSON:\n')[1]); calls.append(data['phase'])
        if data['phase'] == 'missing_verification':
            return response(dict(decisions=[dict(proposal_id=p['proposal_id'], supported=True,
                already_represented=False, matching_observation_ids=[], evidence=f['source'], issues=[])
                for p in data['proposals']]))
        if data['phase'] == 'identity_repair':
            assert data['observations'][0]['source_span']['text'] == f['source']
            return response(dict(identities={o['observation_id']: dict(reason='Explicit ranking territory',
                identity=dict(entity_namespace='mountain_ranking', entity=o['claim']['entity'] +
                    (' | mainland South Korea' if 'mainland' in o['claim']['value']['assertion'] else ' | South Korea'),
                    attribute='position_in_ranking')) for o in data['observations']}))
        if data['phase'] == 'identity_verification':
            return response(dict(decisions=[dict(group_id=g['group_id'], reason='Distinct explicit territories',
                supported_partition=True, evidence=f['source'], issues=[]) for g in data['groups']]))
        for o in data['observations']:
            assert "second-tallest mountain in South Korea after Jeju Island's Hallasan" in o['source_span']['text']
        return response(dict(decisions=[dict(observation_id=o['observation_id'], entailed=True, complete=True,
            evidence=f['source'], issues=[]) for o in data['observations']], missing=[]))

    values, diag = asyncio.run(extract_verified(c, provider=provider))
    assert diag['verified'] and diag['retry_count'] == 1
    assert {o.observation_id for o in values} == {f'p09:{i}' for i in range(4)}
    assert [o.claim.value for o in values] == [r['claim']['value'] for r in f['initial']]
    first = next(o for o in values if o.observation_id == 'p09:0')
    assert first.metadata['source_span']['text'] == f['source']
    assert first.metadata['extraction_source_span']['text'] == original
    assert diag['trace'][0]['verification']['evidence_regrounding'][0]['observation_id'] == 'p09:0'
    assert calls.count('identity_repair') == 1


def test_hugler_two_service_terms_survive_one_identity_repair_without_departure_fact():
    f = FIXTURES['hugler']; repaired = []

    async def provider(prompt):
        if 'Input JSON:\n' not in prompt:
            return response(f['initial'])
        data = json.loads(prompt.split('Input JSON:\n')[1])
        if data['phase'] == 'missing_verification':
            return response(dict(decisions=[dict(proposal_id=p['proposal_id'], reason='Explicit dated term',
                supported=True, already_represented=False, matching_observation_ids=[],
                evidence=f['source'], issues=[]) for p in data['proposals']]))
        if data['phase'] == 'identity_repair':
            repaired.append(data)
            return response(dict(identities={o['observation_id']:dict(reason='Different stated term start',
                identity=dict(entity_namespace='service_term', entity=o['claim']['entity'] +
                    (' | Acting Secretary of Labor | February 2, 2009' if o['observation_id']=='p00:3'
                     else ' | Acting Secretary of Labor | January 20, 2017'),
                    attribute='served_as')) for o in data['observations']}))
        if data['phase'] == 'identity_verification':
            return response(dict(decisions=[dict(group_id=g['group_id'], reason='Explicit separate term scopes',
                supported_partition=True, evidence=f['source'], issues=[]) for g in data['groups']]))
        return response(dict(decisions=[dict(observation_id=o['observation_id'], reason='Explicit source fact',
            entailed=True, complete=True, evidence=f['source'], issues=[]) for o in data['observations']], missing=[]))

    observations, diag = asyncio.run(extract_verified(chunk('hugler'), provider=provider))
    assert diag['verified'] and diag['retry_count']==1 and len(repaired)==1
    assert {o.observation_id for o in observations} == {f'p00:{i}' for i in range(6)}
    assert {json.dumps(o.claim.value,sort_keys=True) for o in observations} == {
        json.dumps(r['claim']['value'],sort_keys=True) for r in f['initial']}
    assert not any('left the position' in o.claim.value['assertion'] for o in observations)


def test_javan_truncated_estimate_keeps_five_complete_assertions():
    f = FIXTURES['leopard']; c = chunk('leopard'); repairs = []

    async def provider(prompt):
        if 'Input JSON:\n' not in prompt:
            assert 'Repair request JSON:' not in prompt
            return response(f['initial'])
        data = json.loads(prompt.split('Input JSON:\n')[1]); repairs.append(data)
        assert data['phase'] == 'extraction_verification'
        assert len(data['observations']) == 5
        return response(dict(decisions=[dict(observation_id=o['observation_id'], entailed=True,
            complete=True, evidence=f['source'], issues=[]) for o in data['observations']], missing=[]))

    values, diag = asyncio.run(extract_verified(c, provider=provider))
    assert diag['verified'] and diag['retry_count'] == 0 and len(repairs) == 1
    assert {o.observation_id for o in values} == {f'p07:{i}' for i in range(5)}
    assert [o.claim.value for o in values] == [r['claim']['value'] for r in f['initial'][:5]]
    excluded = diag['trace'][0]['rejected_extraction_records']
    assert len(excluded) == 1 and excluded[0]['observation_id'] == 'p07:5'
    assert excluded[0]['record'] == f['initial'][5]
    assert all(o.source == c['source'] and o.metadata['chunk_id'] == 'p07' for o in values)


def test_missing_estimate_positive_cannot_manufacture_an_obligation():
    f = FIXTURES['leopard']; record = f['initial'][5]

    async def provider(prompt):
        return response(dict(decisions=[dict(proposal_id='0', supported=True, already_represented=False,
            matching_observation_ids=[], evidence=f['source'], issues=[])]))

    missing, reviews = asyncio.run(_verify_missing([record], [], f['source'], provider, 'p07'))
    assert not missing and not reviews[0]['supported']
    assert reviews[0]['model_decision']['supported'] is True


def test_complete_source_range_is_repaired_not_discarded():
    record = json.loads(json.dumps(FIXTURES['leopard']['initial'][5]))
    source = FIXTURES['leopard']['source'].replace('2267.9 to .', '2267.9 to 3500 square kilometers.')
    record['evidence'] = source
    assert not _incomplete_estimate(record, source)
    candidates, errors, _ = _candidates(dict(chunk('leopard'), text=source), response([record]), [], 0)
    assert len(candidates) == 1 and not errors  # Semantic audit must resolve the omitted upper bound.


def test_invented_upper_bound_still_fails_literal_grounding():
    f = FIXTURES['leopard']; record = json.loads(json.dumps(f['initial'][5]))
    record['claim']['value']['assertion'] += ' 3500 square kilometers'
    candidates, errors, _ = _candidates(chunk('leopard'), response([record]), [], 0)
    assert not candidates and errors[0]['issues'] == ['literal quantity absent from evidence']


@pytest.mark.parametrize('tamper', [False, True])
def test_checkpoint_candidate_reference_reuses_original_call_with_hash_check(tmp_path, tamper):
    f = FIXTURES['hugler']; case = dict(case_id=f['case_id'], chunks=[dict(chunk_id='p00',raw_text=f['source'])])
    text = json.dumps(f['initial'])
    origin = tmp_path/'original-call.json'
    origin.write_text(json.dumps(dict(prompt='Extract.\nSource text (JSON string):\n'+json.dumps(f['source']),
        response=dict(done=True,done_reason='stop',response=text),request=dict(model='source-model'),seconds=100)))
    cache = tmp_path/'cache'; cache.mkdir()
    (cache/'manifest.json').write_text(json.dumps(dict(datasets=dict(cases_sha256='dataset'),
        generator=dict(name='source-model',digest='model-digest'))))
    seed = dict(path=str(origin),sha256=hashlib.sha256(origin.read_bytes()).hexdigest(),model_digest='model-digest')
    (cache/f"{f['case_id']}-p00-failed.json").write_text(json.dumps(dict(diagnostics=dict(candidate_seed=seed))))
    if tamper:
        origin.write_text(origin.read_text()+' ')
        with pytest.raises(ValueError,match='candidate seed provenance mismatch'):
            extraction_seeds(cache,case,dict(cases_sha256='dataset'))
    else:
        result = extraction_seeds(cache,case,dict(cases_sha256='dataset'))
        assert result['p00']['response_text']==text and result['p00']['path']==str(origin)
