"""Changed source-verifier requests revalidate saved objects, not extraction."""
import asyncio
from datetime import datetime, timezone
import hashlib
import json
from types import SimpleNamespace

import pytest

from omneum import Claim, Observation, Source
from benchmarks.context_selection.public_datasets.preprocessing import verified_passages
from benchmarks.context_selection.public_datasets.run_benchmark import EXTRACTION_CONTRACT, observation_record


@pytest.mark.parametrize('supported', [True, False])
def test_live_checkpoint_audit_preserves_ids_time_and_values_or_rejects(tmp_path, supported):
    text = 'FixtureCity is a city.'
    case = dict(case_id='unit-only', chunks=[dict(chunk_id='p00', raw_text=text)])
    metadata = dict(cases_sha256='unit-dataset')
    generator = SimpleNamespace(identity=dict(digest='unit-model'), options={})
    span = dict(start=0, end=len(text), text=text)
    observation = Observation('p00:0', Source('web_document','https://fixture.example/city'),
        Claim('place','FixtureCity','kind',dict(assertion=text)),
        observed_at=datetime(2020,1,1,tzinfo=timezone.utc), metadata=dict(chunk_id='p00',source_span=span))
    claim = dict(entity_namespace='place',entity='FixtureCity',attribute='kind',value=observation.claim.value)
    (tmp_path/'manifest.json').write_text(json.dumps(dict(extraction_contract=EXTRACTION_CONTRACT,
        datasets=metadata,generator=generator.identity,generator_options={},passage_verification_sha256='old-verifier')))
    path = tmp_path/'unit-only-p00-verified.json'
    path.write_text(json.dumps(dict(source_sha256=hashlib.sha256(text.encode()).hexdigest(),
        observations=[observation_record(observation)],call_sha256={},diagnostics=dict(verified=True,
            trace=[dict(proposed=[dict(observation_id='p00:0',claim=claim,source_span=span)],accepted_ids=['p00:0'],
                structural_rejections=[],verification={})])),default=str))
    before = path.read_bytes()
    calls = []

    async def provider(prompt):
        data = json.loads(prompt.split('Input JSON:\n')[1]);calls.append(data)
        assert data['phase'] == 'extraction_verification'
        return {'text':json.dumps(dict(decisions=[dict(observation_id='p00:0',entailed=supported,complete=True,
            evidence=text if supported else '',issues=[] if supported else ['Unsupported by current audit'])],missing=[]))}

    cached = asyncio.run(verified_passages(tmp_path,case,metadata,generator,provider=provider))
    assert len(calls) == 1 and path.read_bytes() == before
    assert bool(cached) is supported
    if supported:
        restored,diagnostics = cached['p00']
        assert restored == (observation,)
        assert diagnostics['revalidation_history'][-1]['fresh_requests'] == 1
