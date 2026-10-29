"""Checkpoint replay cannot reset bounded retries or admit failed observations."""
import asyncio
from datetime import datetime, timezone
import hashlib
import json
from types import SimpleNamespace

import pytest

from benchmarks.context_selection.public_datasets.preprocessing import verified_passages
from benchmarks.context_selection.public_datasets.run_benchmark import (
    EXTRACTION_CONTRACT, prepare_claims, verification_source_hash,
)


def fixture(tmp_path, *, changed_code=False, observations=None):
    text = 'A source assertion that remains unresolved.'
    case = dict(dataset='hotpotqa', case_id='unit-only', chunks=[dict(
        chunk_id='p00', document_id='source', raw_text=text)])
    metadata = dict(cases_sha256='unit-dataset')
    generator = SimpleNamespace(identity=dict(digest='unit-model'), options={})
    (tmp_path/'manifest.json').write_text(json.dumps(dict(extraction_contract=EXTRACTION_CONTRACT,
        datasets=metadata, generator=generator.identity, generator_options={},
        passage_verification_sha256='different' if changed_code else verification_source_hash(False))))
    receipt = tmp_path/'receipt.json'; receipt.write_text('{}')
    path = tmp_path/'unit-only-p00-failed.json'
    path.write_text(json.dumps(dict(source_sha256=hashlib.sha256(text.encode()).hexdigest(),
        observations=observations or [], call_sha256={receipt.name: hashlib.sha256(receipt.read_bytes()).hexdigest()},
        diagnostics=dict(verified=False, status='failed_after_retry', retry_count=2,
            error='source verification unresolved', trace=[dict(attempt=i) for i in range(3)]))))
    return case, metadata, generator, path


@pytest.mark.parametrize('changed_code', [False, True])
def test_failed_cache_replays_only_under_exact_source_verifier(tmp_path, changed_code):
    case, metadata, generator, path = fixture(tmp_path, changed_code=changed_code)
    before = path.read_bytes()
    cached = asyncio.run(verified_passages(tmp_path, case, metadata, generator))
    assert bool(cached) is not changed_code
    assert path.read_bytes() == before
    if changed_code:
        return
    assert cached['p00'][0] == () and not cached['p00'][1]['verified']
    assert cached['p00'][1]['retry_count'] == 2

    async def provider(prompt):
        pytest.fail('A bounded failure cannot repeat model requests under unchanged code')

    timings = {}
    with pytest.raises(ValueError, match='semantic extraction failed for p00'):
        asyncio.run(prepare_claims(case, provider, datetime.now(timezone.utc), timings,
                                  verified_passages=cached))
    assert timings['extraction_diagnostics'][0]['replayed_failed_passage']
    assert timings['extraction_diagnostics'][0]['replayed_verified_passage'] is False
    assert 'normalization_seconds' not in timings


def test_failed_checkpoint_cannot_carry_observations_into_inference(tmp_path):
    case, metadata, generator, _ = fixture(tmp_path, observations=[{'fabricated': True}])
    with pytest.raises(ValueError, match='invalid bounded passage failure checkpoint'):
        asyncio.run(verified_passages(tmp_path, case, metadata, generator))
