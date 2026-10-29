"""Old checkpoints with invalid reified identities require targeted revalidation."""
import asyncio
from datetime import datetime, timezone
import hashlib
import json
from types import SimpleNamespace

from omneum import Claim, Observation, Source
from benchmarks.context_selection.public_datasets.preprocessing import verified_passages
from benchmarks.context_selection.public_datasets.run_benchmark import (
    EXTRACTION_CONTRACT, observation_record, verification_source_hash,
)


def test_unstated_computed_identity_year_invalidates_only_affected_checkpoint(tmp_path):
    text = 'Mira participated in 1935. Fifty years later, she participated again.'
    case = dict(case_id='unit-fixture', chunks=[dict(chunk_id='p00', raw_text=text)])
    metadata = dict(cases_sha256='unit-fixture')
    generator = SimpleNamespace(identity=dict(digest='unit-model'), options={})
    (tmp_path/'manifest.json').write_text(json.dumps(dict(extraction_contract=EXTRACTION_CONTRACT,
        datasets=metadata, generator=generator.identity, generator_options={},
        passage_verification_sha256=verification_source_hash(False))))
    observation = Observation('p00:1', Source('web_document', 'https://fixture.example/events'),
        Claim('event', 'Mira | 1985', 'participated', dict(assertion='Fifty years later, Mira participated again.')),
        observed_at=datetime.now(timezone.utc), metadata=dict(chunk_id='p00'))
    path = tmp_path/'unit-fixture-p00-verified.json'
    path.write_text(json.dumps(dict(source_sha256=hashlib.sha256(text.encode()).hexdigest(),
        observations=[observation_record(observation)], call_sha256={}, diagnostics=dict(verified=True,
            trace=[dict(proposed=[], accepted_ids=[], verification={}, structural_rejections=[dict(
                observation_id='p00:1', issues=['multiple values for source/property'])])])), default=str))
    before = path.read_bytes()
    assert asyncio.run(verified_passages(tmp_path, case, metadata, generator)) == {}
    assert path.read_bytes() == before
