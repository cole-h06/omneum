"""Full preprocessing persists exhausted failures for exact-code continuation."""
import asyncio
import hashlib
import json
from types import SimpleNamespace

from benchmarks.context_selection.public_datasets import preprocessing


def test_full_preprocessor_journals_empty_bounded_failure(tmp_path, monkeypatch):
    text = 'FixtureCity is a city.'
    case = dict(dataset='hotpotqa',case_id='unit-only',chunks=[dict(chunk_id='p00',document_id='one',raw_text=text)])
    prepared = tmp_path/'prepared';prepared.mkdir()
    (prepared/'cases.jsonl').write_text(json.dumps(case)+'\n')
    metadata = dict(cases_sha256=hashlib.sha256((prepared/'cases.jsonl').read_bytes()).hexdigest())
    (prepared/'manifest.json').write_text(json.dumps(metadata))
    class Generator:
        def __init__(self, model):
            self.identity=dict(name=model,digest='unit-model');self.options={}
            self.tokenizer_identity=dict(name='unit-only');self.http=SimpleNamespace(close=lambda:None)
    def generate(generator,prompt):
        return dict(request=dict(model=generator.identity['name'],options={}),seconds=.01,
            response=dict(response='[]',done=True,done_reason='stop',prompt_eval_count=1,eval_count=1))
    async def fail(case,provider,observed_at,timings,**kwargs):
        await provider('Source text (JSON string):\n'+json.dumps(text))
        timings['extraction_diagnostics']=[dict(chunk_id='p00',verified=False,status='failed_after_retry',retry_count=2,
            error='Unresolved source assertions',trace=[dict(attempt=i) for i in range(3)])]
        raise ValueError('Unresolved source assertions')
    monkeypatch.setattr(preprocessing,'PublicGenerator',Generator)
    monkeypatch.setattr(preprocessing,'generate_mapping',generate)
    monkeypatch.setattr(preprocessing,'prepare_claims',fail)
    args=SimpleNamespace(prepared=prepared,output=tmp_path/'output',mapping_model='unit-model',
                         extraction_from=None,verified_passages_from=[])
    asyncio.run(preprocessing.run_preprocessing(args,[case],metadata))
    path=args.output/'unit-only-p00-failed.json'
    checkpoint=json.loads(path.read_text())
    assert checkpoint['observations']==[] and checkpoint['diagnostics']['retry_count']==2
    assert checkpoint['call_sha256']
    assert not (args.output/'hotpotqa-unit-only-trial1-claims.json').exists()
    cached=asyncio.run(preprocessing.verified_passages(args.output,case,metadata,Generator('unit-model')))
    assert cached['p00'][0]==() and cached['p00'][1]['verified'] is False
