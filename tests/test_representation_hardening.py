"""Concrete upstream guards; semantic validation is recorded separately live."""
import asyncio
from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal
import json

import pytest
from omneum import Claim, Observation, Source
from omneum.extraction import _quote_supports_numbers
from omneum.normalization import _numeric_literals, _verify_changes, _source_conflict_pairs


@pytest.mark.parametrize('value,quote,expected', [
    ('POST /jobs', 'GET /jobs; POST /receipts.', False),
    ('POST /jobs', 'POST /jobs-old', False),
    ('POST /jobs', 'POST /jobs.json', False),
    ('POST /jobs', 'POST /jobs. Then check the receipt.', True),
    ('POST /jobs', 'POST /jobs and check the receipt.', True),
    ({'method':'POST','endpoint':'/jobs'}, 'GET /jobs; POST /receipts.', False),
    ({'method':'POST','endpoint':'/jobs'}, 'POST /jobs after validation.', True),
    ({'method':'POST','endpoint':'/jobs'}, '{"method":"POST","endpoint":"/jobs"}', True),
    ({'endpoint':'/jobs'}, 'GET /jobs-old', False),
    ({'endpoint':'/jobs'}, 'GET /old/jobs', False),
    ({'endpoint':'/jobs'}, 'GET /jobs', True),
])
def test_action_grounding_keeps_method_and_complete_endpoint_together(value, quote, expected):
    from omneum.extraction import _quote_supports_actions
    assert _quote_supports_actions(value, quote) is expected


@pytest.mark.parametrize('field,value', [
    ('assertion', True), ('assertion', ''), ('assertion', '   '),
    ('scope', ['staging']), ('scope', ''), ('condition', True),
    ('ordering', 8), ('modality', {}),
])
def test_grounded_structured_fields_obey_the_existing_protocol(field, value):
    from omneum.extraction import _parse_extraction_record
    text = 'Staging worker: timeout is 8 seconds.'
    chunk = dict(id='original', text=text, source=Source('web_document','https://example.org'),
                 observed_at=datetime(2026,1,1,tzinfo=timezone.utc))
    structured = dict(assertion='timeout is 8 seconds', scope='staging worker',
                      condition=None, ordering=None, modality='report')
    structured[field] = value
    record = dict(claim=dict(entity_namespace='worker', entity='staging worker',
                            attribute='timeout', value=structured), evidence=text)
    with pytest.raises(ValueError):
        _parse_extraction_record(chunk, record, 0)


def test_grounded_legacy_json_is_not_reinterpreted_as_the_structured_protocol():
    from omneum.extraction import _parse_extraction_record
    text = 'The assertion flag is true.'
    chunk = dict(id='original',text=text,source=Source('web_document','https://example.org'),
                 observed_at=datetime(2026,1,1,tzinfo=timezone.utc))
    record = dict(claim=dict(entity_namespace='worker',entity='worker',attribute='flags',
                            value={'assertion':True}),evidence=text)
    assert _parse_extraction_record(chunk,record,0).claim.value=={'assertion':True}


@pytest.mark.parametrize('before,after', [
    ('POST /jobs', 'GET /jobs'), ('POST /jobs', 'POST /jobs-old'),
    ('POST /jobs', 'POST /jobs.json'), ('POST /jobs', 'jobs available'),
    ('jobs available', 'POST /jobs'),
])
def test_normalization_cannot_change_http_action_inside_assertion(before, after):
    source = Source('web_document','https://example.org/rule')
    original = Observation('a',source,Claim('worker','staging worker','rule',
                           {'assertion':before, 'scope':'staging', 'condition':None}),
                           observed_at=datetime(2026,1,1,tzinfo=timezone.utc),metadata={'chunk_id':'a'})
    proposed = replace(original, claim=Claim('worker','staging worker','rule',
                        {'assertion':after, 'scope':'staging', 'condition':None}))
    async def approve(prompt):
        raise AssertionError('changed literal actions must be rejected before semantic approval')
    assert asyncio.run(_verify_changes((original,),(proposed,),approve,{'a':before})) == (original,)


def test_normalization_preserves_unchanged_structured_action_and_qualifications():
    source = Source('web_document','https://example.org/rule')
    original = Observation('a',source,Claim('worker','worker','rule',{
        'action':{'method':'POST','endpoint':'/jobs'}, 'scope':'staging',
        'condition':'after validation', 'ordering':'before shutdown'}),
        observed_at=datetime(2026,1,1,tzinfo=timezone.utc),metadata={'chunk_id':'a'})
    proposed = replace(original,claim=Claim('worker','worker','rule_alias',original.claim.value))
    async def approve(prompt):
        return {'text':'{"equivalent":true}'}
    assert asyncio.run(_verify_changes((original,),(proposed,),approve,
                     {'a':'Staging: POST /jobs after validation, before shutdown.'})) == (proposed,)


def test_legacy_grounding_inventoried_fact_gets_its_own_span():
    from omneum.extraction import _ground_chunk_observations
    first, second = 'Worker is in staging.', 'POST /jobs after validation.'
    text = first + ' ' + second
    source = Source('web_document','https://example.org/rule')
    original = Observation('a',source,Claim('worker','worker','scope','staging'),
        observed_at=datetime(2026,1,1,tzinfo=timezone.utc),metadata={
            'chunk_id':'original', 'request':'keep',
            'source_span':{'start':0, 'end':len(first), 'text':first}})
    async def provider(prompt):
        return {'text':json.dumps(dict(decisions=[dict(entailed=True,evidence=first)],missing=[
            dict(claim=dict(entity_namespace='worker',entity='worker',attribute='instruction',
                            value={'assertion':'POST /jobs after validation', 'condition':'validation => POST /jobs'}),
                 evidence=second)]))}
    values, diagnostics = asyncio.run(_ground_chunk_observations((original,),source_text=text,provider=provider))
    assert diagnostics['status']=='grounded' and len(values)==2
    assert values[0].metadata['source_span']==original.metadata['source_span']
    new = values[1]
    assert new.metadata['source_span']==dict(start=len(first)+1,end=len(text),text=second)
    assert new.observation_id=='a:grounded:0'
    assert new.source is original.source and new.observed_at==original.observed_at
    assert new.metadata['chunk_id']=='original' and new.metadata['request']=='keep'


def test_legacy_grounding_cannot_authorize_a_detached_http_action():
    from omneum.extraction import _ground_chunk_observations
    text = 'GET /jobs; POST /receipts.'
    original = Observation('a',Source('web_document','https://example.org/rule'),
        Claim('worker','worker','instruction','POST /jobs'),
        observed_at=datetime(2026,1,1,tzinfo=timezone.utc))
    async def provider(prompt):
        return {'text':json.dumps(dict(decisions=[dict(entailed=True,evidence=text)],missing=[]))}
    values, diagnostics = asyncio.run(_ground_chunk_observations((original,),source_text=text,provider=provider))
    # Legacy audit explicitly abstains and retains the input; it must never
    # report successful grounding for the mismatched action.
    assert values==(original,) and diagnostics['status']=='grounding_abstention'
    assert 'method or endpoint' in diagnostics['error']


def test_explicit_parcel_metrics_parse_without_source_property_collisions():
    from omneum.extraction import _parse_extraction_record, _validate_chunk_properties
    from omneum.client import _evaluate_context
    from benchmarks.context_selection.config import estimator_config
    text = ('Dispatch source table: August 16 cohort contains 520 parcel IDs. '
            'Reconciliation records 487 delivered and 33 returned.')
    chunk = dict(id='original',text=text,source=Source('web_document','https://example.org/reconciliation'),
                 observed_at=datetime(2026,1,1,tzinfo=timezone.utc))
    values = []
    for attr, assertion in [('total_parcels','520 parcel IDs'), ('delivered_parcels','487 delivered'),
                            ('returned_parcels','33 returned')]:
        record = dict(claim=dict(entity_namespace='cohort',entity='August 16 dispatch cohort',
            attribute=attr,value=dict(assertion=assertion,scope='August 16 dispatch cohort',
                                      condition=None,ordering=None,modality='report')),evidence=text)
        values.append(_parse_extraction_record(chunk,record,len(values)))
    _validate_chunk_properties(values)
    assert len(_evaluate_context(values,estimator=estimator_config()).claim_support)==3
    assert all(o.metadata['chunk_id']=='original' and o.metadata['source_span']['text']==text for o in values)


@pytest.mark.parametrize('text,expected', [
    ('.12 seconds', {Decimal('.12')}), ('12 seconds', {Decimal(12)}),
    ('1,200 items', {Decimal(1200)}), ('1,2', {Decimal(1), Decimal(2)}),
    ('1.2e2 seconds', {Decimal(120)}), ('−.5', {Decimal('-.5')}),
    ({'count': 120, 'enabled': True}, {Decimal(120)}),
])
def test_numeric_guard_preserves_complete_literals(text, expected):
    assert _numeric_literals(text) == expected


def test_leading_decimal_cannot_be_grounded_by_an_integer():
    assert not _quote_supports_numbers(Claim('api', 'header', 'delay_seconds', '.12'), 'wait 12 seconds')
    assert _quote_supports_numbers(Claim('api', 'header', 'delay_seconds', '.12'), 'wait .12 seconds')


def test_partial_verification_cannot_create_source_property_conflicts():
    source = Source('web_document', 'https://example.org/config')
    def obs(k, attr, value):
        return Observation(k, source, Claim('service', 'worker', attr, value),
                           observed_at=datetime(2026, 1, 1, tzinfo=timezone.utc), metadata={'chunk_id': k})
    original = (obs('a', 'primary', 80), obs('b', 'secondary', 90))
    proposed = (replace(original[0], claim=Claim('service', 'worker', 'secondary', 80)),
                replace(original[1], claim=Claim('service', 'worker', 'primary', 90)))
    async def provider(prompt):
        data = json.loads(prompt.split('Input JSON:\n')[1])
        return {'text': json.dumps({'equivalent': data['original_chunk_id'] == 'a'})}
    result = asyncio.run(_verify_changes(original, proposed, provider, {'a': 'Primary 80.', 'b': 'Secondary 90.'}))
    assert result == original
    assert not _source_conflict_pairs(result)


@pytest.mark.parametrize('field,old,new', [
    ('unit','seconds','milliseconds'), ('units','kg','lb'),
    ('exception','during self-test',None), ('exceptions',['legal hold'],[]),
])
def test_normalization_cannot_erase_explicit_units_or_exceptions(field,old,new):
    source = Source('web_document','https://example.org/rule')
    before = Observation('a',source,Claim('system','worker','rule',{'amount':120,field:old}),
                         observed_at=datetime(2026,1,1,tzinfo=timezone.utc),metadata={'chunk_id':'a'})
    after = replace(before,claim=Claim('system','worker','rule_alias',{'amount':120,field:new}))
    async def approve(prompt):
        raise AssertionError('explicit qualifier changes must be rejected before semantic approval')
    assert asyncio.run(_verify_changes((before,),(after,),approve,{'a':'Original rule.'})) == (before,)


@pytest.mark.parametrize('entity,attribute', [
    ('August 12 2049 cohort', 'count'),
    ('August 12 cohort', 'count_for_2049'),
])
def test_grounded_identity_cannot_invent_numeric_scope(entity, attribute):
    from omneum.extraction import _parse_extraction_record
    text = 'August 12 cohort: 216 addresses.'
    chunk = dict(id='source', text=text, source=Source('web_document', 'https://example.org/cohort'),
                 observed_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
    record = dict(claim=dict(entity_namespace='cohort', entity=entity, attribute=attribute,
                            value=216), evidence=text)
    with pytest.raises(ValueError, match='literal quantity'):
        _parse_extraction_record(chunk, record, 0)


@pytest.mark.parametrize('field,old,new', [
    ('entity', 'worker v2', 'worker v3'),
    ('entity', 'August 12 cohort', 'August cohort'),
    ('attribute', 'latency_p95', 'latency_p99'),
])
def test_normalization_preserves_numeric_identity_scope(field, old, new):
    before_fields = dict(entity_namespace='system', entity='worker', attribute='timeout', value=8)
    before_fields[field] = old
    before = Observation('a', Source('web_document', 'https://example.org/worker'), Claim(**before_fields),
                         observed_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
    after = replace(before, claim=Claim(**{**before_fields, field: new}))
    async def approve(prompt):
        raise AssertionError('numeric identity changes must fail before semantic approval')
    assert asyncio.run(_verify_changes((before,), (after,), approve, None)) == (before,)


@pytest.mark.parametrize('value,quote,expected', [
    ('POST /jobs.', 'POST /jobs and verify the receipt.', True),
    ('POST /jobs! Then verify.', 'POST /jobs and verify the receipt.', True),
    ('readiness path is /health', 'readinessProbe.httpGet.path=/ready', False),
    ('path is /ready', 'readinessProbe.httpGet.path=/ready', True),
    ('path is /ready', 'readinessProbe.httpGet.path=/ready-old', False),
    ('path is /ready', 'readinessProbe.httpGet.path=/ready.json', False),
    ('Call POST /jobs.', 'GET /jobs; POST /receipts.', False),
    ('Use /jobs.', 'Use /jobs and verify.', True),
    ('Use /jobs', 'Use (/jobs).', True),
])
def test_literal_paths_and_sentence_punctuation(value, quote, expected):
    from omneum.extraction import _quote_supports_actions
    assert _quote_supports_actions({'assertion': value}, quote) is expected


@pytest.mark.parametrize('entity,value', [
    ('August 12 2049 cohort', 216),
    ('August 12 cohort', {'assertion': 'path is /health'}),
])
def test_strict_verification_cannot_approve_unsupported_identity_or_path(entity, value):
    from omneum.extraction import _ground_chunk_observations
    text = 'August 12 cohort: 216 addresses. Readiness path is /ready.'
    original = Observation('a', Source('web_document', 'https://example.org/cohort'),
                           Claim('cohort', entity, 'reported', value),
                           observed_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
    async def provider(prompt):
        return {'text': json.dumps(dict(decisions=[dict(entailed=True, complete=True,
            evidence=text, issues=[])], missing=[]))}
    accepted, audit = asyncio.run(_ground_chunk_observations(
        (original,), source_text=text, provider=provider, strict=True))
    assert accepted == ()
    assert audit['rejected'][0]['observation_id'] == 'a'
