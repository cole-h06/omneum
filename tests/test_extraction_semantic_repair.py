"""Deterministic workflow guarantees; live provider fidelity is checked separately."""
import asyncio
from datetime import datetime, timezone
import json

import pytest
from omneum import Source
from omneum.extraction import _extract_with_repair
from omneum._extraction_verification import extract_verified

NOW=datetime(2026,1,1,tzinfo=timezone.utc)
TEXT='On the staging worker, timeout is 8 seconds. Readiness polling is enabled.'


def chunk():return dict(id='original',text=TEXT,source=Source('web_document','https://source.example'),observed_at=NOW,metadata={'request':'preserved'})
def record(attr,value):return dict(claim=dict(entity_namespace='worker',entity='staging worker',attribute=attr,value=value),evidence=TEXT)
def yes(n):return dict(decisions=[dict(entailed=True,complete=True,evidence=TEXT,issues=[]) for _ in range(n)],missing=[])


def test_only_rejected_claim_is_repaired_and_accepted_identity_provenance_stays():
    inputs=chunk();prompts=[];audits=[]
    good=record('polling_enabled',True)
    bad=record('timeout_seconds',{'assertion':'timeout is 8 seconds','scope':None})
    fixed=record('timeout_seconds',{'assertion':'timeout is 8 seconds','scope':'staging worker'})
    async def provider(prompt):
        prompts.append(prompt)
        if 'Input JSON:\n' in prompt:
            data=json.loads(prompt.split('Input JSON:\n')[1]);audits.append(data)
            assert data['source_text']==TEXT
            result=yes(len(data['observations']))
            if len(audits)==1:result['decisions'][0]=dict(entailed=False,complete=False,evidence='',issues=['missing execution scope'])
            return {'text':json.dumps(result)}
        assert json.loads(prompt.split('Source text (JSON string):\n')[1])==TEXT
        if 'Repair request JSON:' in prompt:
            request=json.loads(prompt.split('Repair request JSON:\n')[1].split('\n\n')[0])
            assert request['accepted'][0]['observation_id']=='original:1'
            assert request['rejected'][0]['observation_id']=='original:0'
            return {'text':json.dumps([fixed,good])}  # A repeated accepted claim earns no extra record.
        return {'text':json.dumps([bad,good])}
    values,diag=asyncio.run(_extract_with_repair(inputs,provider=provider,verify_semantics=True))
    assert diag['verified'] and diag['retry_count']==1 and len(prompts)==4
    assert [o.observation_id for o in values]==['original:1','original:2']
    assert values[0].claim.attribute=='polling_enabled' and values[0].claim.value is True
    assert all(o.source is inputs['source'] and o.observed_at==NOW and o.metadata['chunk_id']=='original' for o in values)
    assert all(o.metadata['request']=='preserved' and o.metadata['source_span']['text']==TEXT for o in values)


def test_malformed_semantic_audit_cannot_authorize_observations():
    async def provider(prompt):return {'text':json.dumps({'equivalent':True} if 'Input JSON:\n' in prompt else [record('polling_enabled',True)])}
    values,diag=asyncio.run(extract_verified(chunk(),provider=provider,max_repairs=0))
    assert values==() and not diag['verified']
    assert diag['trace'][0]['verification']['status']=='verification_abstention'


def test_missing_proposal_needs_a_subsequent_independent_verification():
    audits=[]
    async def provider(prompt):
        if 'Input JSON:\n' not in prompt:
            return {'text':json.dumps([record('timeout_seconds',8)] if audits else [record('polling_enabled',True)])}
        data=json.loads(prompt.split('Input JSON:\n')[1])
        if data['phase']=='missing_verification':
            return {'text':json.dumps(dict(decisions=[dict(proposal_id='0',supported=True,
                already_represented=False,matching_observation_ids=[],evidence=TEXT,issues=[])]))}
        audits.append(data);result=yes(len(data['observations']))
        if len(audits)==1:result['missing']=[record('timeout_seconds',8)]
        else:result['decisions'][-1]=dict(entailed=False,complete=False,evidence='',issues=['incorrect units'])
        return {'text':json.dumps(result)}
    values,diag=asyncio.run(extract_verified(chunk(),provider=provider,max_repairs=1))
    assert values==() and not diag['verified'] and len(audits)==2
    assert diag['trace'][0]['accepted_ids']==['original:0']
    assert len(diag['trace'][0]['verification']['missing'])==1


def test_property_collisions_still_fail_even_with_permissive_semantic_provider():
    async def provider(prompt):
        if 'Input JSON:\n' in prompt:
            data=json.loads(prompt.split('Input JSON:\n')[1]);return {'text':json.dumps(yes(len(data['observations'])))}
        return {'text':json.dumps([record('generic_status',True),record('generic_status',False)])}
    values,diag=asyncio.run(extract_verified(chunk(),provider=provider,max_repairs=1))
    assert values==() and not diag['verified']
    assert all(len(t['structural_rejections'])==2 for t in diag['trace'])


def test_contradictory_positive_decision_with_issues_is_not_accepted():
    async def provider(prompt):
        if 'Input JSON:\n' in prompt:
            result=yes(1);result['decisions'][0]['issues']=['unsupported ordering'];return {'text':json.dumps(result)}
        return {'text':json.dumps([record('polling_enabled',True)])}
    values,diag=asyncio.run(extract_verified(chunk(),provider=provider,max_repairs=0))
    assert values==() and not diag['verified']


@pytest.mark.parametrize('budget',[-1,3,True])
def test_retry_work_is_bounded(budget):
    with pytest.raises(ValueError,match='max_repairs'):
        asyncio.run(extract_verified(chunk(),provider=lambda p:None,max_repairs=budget))


def test_semantic_positive_cannot_authorize_overlapping_ambiguous_quote():
    from omneum import Claim, Observation
    from omneum.extraction import _ground_chunk_observations
    o=Observation('a',Source('web_document','https://source.example'),Claim('test','subject','reported','aa'),observed_at=NOW)
    async def provider(prompt):
        return {'text':json.dumps(dict(decisions=[dict(entailed=True,complete=True,evidence='aaa',issues=[])],missing=[]))}
    accepted,audit=asyncio.run(_ground_chunk_observations((o,),source_text='aaaa',provider=provider,strict=True))
    assert not accepted and audit['rejected'][0]['observation_id']=='a'


def test_unsupported_bare_path_requires_source_grounded_repair():
    source = chunk()
    source['text'] = 'Staging worker: readiness probe path is /ready.'
    audits = []
    async def provider(prompt):
        if 'Input JSON:\n' in prompt:
            data = json.loads(prompt.split('Input JSON:\n')[1])
            audits.append(data)
            result = dict(decisions=[dict(entailed=True, complete=True, evidence=source['text'], issues=[])
                                     for _ in data['observations']], missing=[])
            return {'text': json.dumps(result)}
        path = '/ready' if audits else '/health'
        candidate = record('probe_path', {'assertion': 'probe path is ' + path})
        candidate['evidence'] = source['text']
        return {'text': json.dumps([candidate])}
    values, diagnostics = asyncio.run(extract_verified(source, provider=provider, max_repairs=1))
    assert diagnostics['verified'] and diagnostics['retry_count'] == 1
    assert len(values) == 1 and values[0].observation_id == 'original:1'
    assert values[0].claim.value == {'assertion': 'probe path is /ready'}
    assert values[0].source is source['source']
    assert values[0].metadata['source_span']['text'] == source['text']
    assert diagnostics['trace'][0]['structural_rejections'][0]['issues'] == ['method or endpoint absent from evidence']


def test_decisions_bind_to_ids_instead_of_array_positions():
    from omneum.extraction import _parse_extraction_record
    from omneum._extraction_verification import verify_observations
    inputs = chunk()
    good = _parse_extraction_record(inputs, record('timeout_seconds', 8), 0)
    unsupported = _parse_extraction_record(inputs, record('owner', 'invented owner'), 1)
    async def provider(prompt):
        return {'text': json.dumps(dict(decisions=[
            dict(observation_id=unsupported.observation_id, entailed=False, complete=False,
                 evidence='', issues=['no owner stated']),
            dict(observation_id=good.observation_id, entailed=True, complete=True, evidence=TEXT, issues=[]),
        ], missing=[]))}
    accepted, audit = asyncio.run(verify_observations((good, unsupported), source_text=TEXT, provider=provider))
    assert [o.observation_id for o in accepted] == [good.observation_id]
    assert [r['observation_id'] for r in audit['rejected']] == [unsupported.observation_id]


@pytest.mark.parametrize('represented', [False, True])
def test_spurious_missing_requests_do_not_feed_the_repair_loop(represented):
    calls = []
    async def provider(prompt):
        calls.append(prompt)
        if 'Input JSON:\n' not in prompt:
            return {'text': json.dumps([record('timeout_seconds', 8)])}
        data = json.loads(prompt.split('Input JSON:\n')[1])
        if data['phase'] == 'missing_verification':
            return {'text': json.dumps(dict(decisions=[dict(proposal_id='0', supported=represented,
                already_represented=represented, matching_observation_ids=['original:0'] if represented else [],
                evidence=TEXT if represented else '', issues=[] if represented else ['not asserted by source'])]))}
        result = yes(1)
        result['missing'] = [record('timeout_seconds' if represented else 'owner',
                                    8 if represented else 'invented owner')]
        return {'text': json.dumps(result)}
    values, diagnostics = asyncio.run(extract_verified(chunk(), provider=provider))
    assert diagnostics['verified'] and diagnostics['retry_count'] == 0
    assert len(values) == 1 and len(calls) == 3
    proposal = diagnostics['trace'][0]['verification']['missing_proposals'][0]
    assert proposal['already_represented'] == represented
    assert not diagnostics['trace'][0]['verification']['missing']
    assert 'invented owner' not in json.dumps(values[0].claim.value)


def test_supported_missing_fact_repairs_empty_extraction_without_dropping_source():
    calls = []
    async def provider(prompt):
        if 'Input JSON:\n' not in prompt:
            return {'text': json.dumps([record('timeout_seconds', 8)] if calls else [])}
        data = json.loads(prompt.split('Input JSON:\n')[1])
        calls.append(data['phase'])
        if data['phase'] == 'missing_verification':
            return {'text': json.dumps(dict(decisions=[dict(proposal_id='0', supported=True,
                already_represented=False, matching_observation_ids=[], evidence=TEXT, issues=[])]))}
        result = yes(len(data['observations']))
        if not data['observations']:
            result['missing'] = [record('timeout_seconds', 8)]
        return {'text': json.dumps(result)}
    inputs = chunk()
    values, diagnostics = asyncio.run(extract_verified(inputs, provider=provider))
    assert diagnostics['verified'] and diagnostics['retry_count'] == 1
    assert len(values) == 1 and values[0].source is inputs['source']
    assert values[0].metadata['chunk_id'] == 'original'
    assert calls == ['extraction_verification', 'missing_verification', 'extraction_verification']


def test_cached_candidates_are_reverified_and_never_silently_accepted():
    calls = []
    async def provider(prompt):
        calls.append(prompt)
        result = yes(1)
        result['decisions'][0] = dict(entailed=False, complete=False, evidence='', issues=['unsupported assertion'])
        return {'text': json.dumps(result)}
    values, diagnostics = asyncio.run(extract_verified(chunk(), provider=provider, max_repairs=0,
        initial_response={'text': json.dumps([record('owner', 'invented owner')])}))
    assert not diagnostics['verified'] and values == () and len(calls) == 1
    assert diagnostics['trace'][0]['extraction_origin'] == 'cached_candidates'


def test_debug_logging_contains_boundaries_without_source_or_claim_payload(caplog):
    import logging
    async def provider(prompt):
        return {'text': json.dumps(yes(1) if 'Input JSON:\n' in prompt else [record('timeout_seconds', 8)])}
    with caplog.at_level(logging.DEBUG, logger='omneum'):
        values, diagnostics = asyncio.run(extract_verified(chunk(), provider=provider))
    assert values and diagnostics['verified']
    assert 'passage=original stage=extraction' in caplog.text
    assert 'stage=object_construction event=completed' in caplog.text
    assert 'stage=verification event=completed accepted=1' in caplog.text
    assert TEXT not in caplog.text and 'timeout_seconds' not in caplog.text


def test_equivalent_range_dashes_preserve_magnitudes_without_accepting_invented_numbers():
    from decimal import Decimal
    from omneum import Claim
    from omneum._numeric import numeric_literals
    from omneum.extraction import _quote_supports_numbers
    assert numeric_literals('60-90') == numeric_literals('60–90') == frozenset((Decimal(60), Decimal(90)))
    assert numeric_literals('-90--60') == frozenset((Decimal(-90), Decimal(-60)))
    assert numeric_literals('1e-3') == frozenset((Decimal('.001'),))
    good = Claim('plant', 'fixture plant', 'height_cm', {'assertion':'The fixture plant grows to 60–90 cm.'})
    bad = Claim('plant', 'fixture plant', 'height_cm', {'assertion':'The fixture plant grows to 60–95 cm.'})
    assert _quote_supports_numbers(good, 'The fixture plant grows to 60-90 cm.')
    assert not _quote_supports_numbers(bad, 'The fixture plant grows to 60-90 cm.')


def test_unsupported_extra_precision_is_rejected_without_invalidating_complete_supported_facts():
    source = chunk()
    source['text'] = 'The fixture person died in 1781.'
    kept = dict(claim=dict(entity_namespace='person', entity='fixture person', attribute='death_year',
                          value=dict(assertion='The fixture person died in 1781.')),
                evidence=source['text'])
    extra = dict(claim=dict(entity_namespace='person', entity='fixture person', attribute='death_date',
                           value=dict(assertion='The fixture person died on January 13, 1781.')),
                 evidence=source['text'])
    calls = []
    async def provider(prompt):
        calls.append(prompt)
        if 'Input JSON:\n' not in prompt:
            return {'text': json.dumps([kept, extra])}
        data = json.loads(prompt.split('Input JSON:\n')[1])
        if data['phase'] == 'missing_verification':
            return {'text': json.dumps(dict(decisions=[dict(proposal_id='0', supported=False,
                already_represented=False, matching_observation_ids=[], evidence='', issues=['day and month are not stated'])]))}
        return {'text': json.dumps(dict(decisions=[dict(observation_id=o['observation_id'],
            entailed=True, complete=True, evidence=source['text'], issues=[]) for o in data['observations']], missing=[]))}
    values, diag = asyncio.run(extract_verified(source, provider=provider))
    assert diag['verified'] and diag['retry_count'] == 0 and len(values) == 1
    assert values[0].claim.attribute == 'death_year'
    assert len(diag['trace'][0]['rejected_extraction_records']) == 1
    assert diag['trace'][0]['verification']['rejected_extraction_proposals'][0]['supported'] is False
    assert len(calls) == 3


def test_empty_candidate_cache_triggers_fresh_extraction_before_acceptance():
    calls = []
    async def provider(prompt):
        calls.append(prompt)
        if 'Input JSON:\n' in prompt:
            data = json.loads(prompt.split('Input JSON:\n')[1])
            return {'text': json.dumps(yes(len(data['observations'])))}
        assert 'previous extraction was empty' in prompt
        return {'text': json.dumps([record('timeout_seconds', 8)])}
    values, diag = asyncio.run(extract_verified(chunk(), provider=provider, initial_response={'text':'[]'}))
    assert diag['verified'] and diag['retry_count'] == 1 and len(values) == 1
    assert len(calls) == 3


def test_collision_repair_distinguishes_source_relations_and_preserves_subject():
    source = chunk()
    source['text'] = 'Fixturetown has population 12 and area 9 square kilometres.'
    def fact(attribute, assertion):
        return dict(claim=dict(entity_namespace='town', entity='Fixturetown',
                    attribute=attribute, value=dict(assertion=assertion)), evidence=source['text'])
    original = [fact('has', 'Fixturetown has population 12.'),
                fact('has', 'Fixturetown has area 9 square kilometres.')]
    repaired = [fact('population', 'Fixturetown has population 12.'),
                fact('area', 'Fixturetown has area 9 square kilometres.')]
    calls = []
    async def provider(prompt):
        calls.append(prompt)
        if 'Input JSON:\n' not in prompt:
            if 'Repair request JSON:' not in prompt:
                return {'text': json.dumps(original)}
            request = json.loads(prompt.split('Repair request JSON:\n')[1].split('\n\n')[0])
            assert len(request['predicate_collisions']) == 2
            assert {p['attribute'] for p in request['predicate_collisions']} == {'has'}
            assert 'do not copy those labels blindly' in prompt
            return {'text': json.dumps(repaired)}
        data = json.loads(prompt.split('Input JSON:\n')[1])
        if data['phase'] == 'identity_repair':
            return {'text':json.dumps(dict(identities=[dict(observation_id=o['observation_id'],
                entity_namespace='town',entity='Fixturetown',attribute=['population','area'][i])
                for i,o in enumerate(data['observations'])]))}
        if data['phase'] == 'identity_verification':
            return {'text':json.dumps(dict(decisions=[dict(group_id=g['group_id'],distinct=True,
                evidence=source['text'],issues=[]) for g in data['groups']]))}
        if data['phase'] == 'missing_verification':
            return {'text': json.dumps(dict(decisions=[dict(proposal_id=p['proposal_id'],
                supported=True, already_represented=False, matching_observation_ids=[],
                evidence=source['text'], issues=[]) for p in data['proposals']]))}
        return {'text': json.dumps(dict(decisions=[dict(observation_id=o['observation_id'],
            entailed=True, complete=True, evidence=source['text'], issues=[])
            for o in data['observations']], missing=[]))}
    values, diag = asyncio.run(extract_verified(source, provider=provider))
    assert diag['verified'] and diag['retry_count'] == 1
    assert {o.claim.attribute for o in values} == {'population', 'area'}
    assert {o.claim.entity for o in values} == {'Fixturetown'}
    assert {o.metadata['chunk_id'] for o in values} == {'original'}
    assert len(calls) == 6
