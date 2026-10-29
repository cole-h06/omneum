"""Grounded provider protocols survive invalid-output retries without text loss."""
import asyncio
from datetime import datetime,timezone
import json
import pytest
from jsonschema import validate, ValidationError
from omneum import Source
from omneum.extraction import _grounded_response_schema, _extract_with_repair


def test_grounded_schema_rejects_null_identity_and_nonliteral_evidence():
    source='In the test harness, PATCH /jobs and verify the receipt before shutdown.'
    schema=_grounded_response_schema(source)
    record=dict(claim=dict(entity_namespace='service',entity='worker',attribute='shutdown_rule',
        value=dict(assertion=source,scope='test harness',condition=None,
                   ordering='PATCH /jobs and verify before shutdown',modality='instruction')),evidence=source)
    validate([record],schema)
    for broken in [dict(record, evidence='invented quote'),
                   dict(record,claim=dict(record['claim'],entity_namespace=None)),
                   dict(record,claim=dict(record['claim'],entity=''))]:
        with pytest.raises(ValidationError):validate([broken],schema)
    validate([],_grounded_response_schema('   '))
    with pytest.raises(ValidationError):validate([record],_grounded_response_schema('   '))


def test_repair_keeps_grounding_contract_and_original_source_for_constrained_provider():
    source='Test harness: if validation succeeds, PATCH /jobs and verify the receipt before shutdown.'
    prompts=[]
    async def provider(prompt):
        prompts.append(prompt)
        # A production structured provider must be able to use one decoder for
        # both attempts. Validation diagnostics must never replace the source.
        text=json.loads(prompt.split('Source text (JSON string):\n',1)[1])
        assert text==source
        schema=_grounded_response_schema(text)
        if len(prompts)==1:return {'text':'[{"invalid":true}]'}
        record=dict(claim=dict(entity_namespace='service',entity='test worker',attribute='shutdown_rule',
            value=dict(assertion=source,scope='test harness',condition='validation succeeds => PATCH /jobs and verify receipt',
                       ordering='PATCH /jobs and verify receipt before shutdown',modality='instruction')),evidence=source)
        validate([record],schema)
        return {'text':json.dumps([record])}
    chunk=dict(id='original',text=source,source=Source('web_document','https://source.example'),observed_at=datetime.now(timezone.utc))
    observations,diagnostics=asyncio.run(_extract_with_repair(chunk,provider=provider))
    assert len(prompts)==2 and diagnostics['status']=='repaired'
    assert observations[0].metadata['chunk_id']=='original'
    span=observations[0].metadata['source_span']
    assert source[span['start']:span['end']]==source
    assert observations[0].source is chunk['source']
