"""Offline recovery boundaries, crash continuation, accounting and provenance."""
import asyncio
from copy import deepcopy
import fcntl
import json
from pathlib import Path
import socket
from types import SimpleNamespace

import pytest

from . import recover_gemini_generations as recovery


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError('Offline recovery tests cannot contact providers')
    monkeypatch.setattr(socket.socket, 'connect', forbidden)
    monkeypatch.setattr(socket.socket, 'connect_ex', forbidden)


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    # Construct an independent failed replay from retained baseline data. Only
    # fixture hashes are overridden; production pins cannot accept these bytes.
    original = recovery.BASE / 'results/bge-google-low-vs-bge-omneum-20261008'
    rows = [json.loads(l) for l in (original / 'results.jsonl').read_text().splitlines()]
    manifest = json.loads((original / 'manifest.public-v1.json').read_text())
    manifest.update(run_id=recovery.RUN, sole_request_change={'thinking_config': {'thinking_level': 'low'}},
        pricing={'usd_per_million': {'sonnet_input': 2, 'sonnet_output': 10}})
    count = 0
    for row in rows:
        if row['method'] != 'bge_google':
            continue
        if count >= 101:
            request = recovery.request_for(row, json.loads((recovery.BASE / 'cases' / row['case_id'] / 'case.json').read_text()))
            row.update(answer=None, answer_score='generation_failure', generation=None,
                       failure_type='provider_error', generation_request_hash=recovery.digest(request))
            row.pop('end_to_end_latency_seconds', None)
        count += 1
    source = tmp_path / 'source'
    source.mkdir()
    (source / 'manifest.json').write_text(json.dumps(manifest))
    (source / 'results.jsonl').write_bytes(b''.join(recovery.encoded(r) + b'\n' for r in rows))
    (source / 'summary.json').write_text(json.dumps(recovery.summarize(rows)))
    monkeypatch.setattr(recovery, 'SOURCE_HASHES', {n: recovery.file_hash(source / n) for n in recovery.SOURCE_HASHES})
    work = tmp_path / 'staging'
    plan = recovery.prepare(source, work)
    return work, plan, rows


def output(request, **overrides):
    value = {'provider': 'anthropic', 'model': recovery.MODEL, 'provider_message_id': 'msg_offline',
             'text': 'Recovered answer.', 'input_tokens': 250, 'output_tokens': 100,
             'latency_seconds': 1.25, 'response_diagnostics': {'stop_reason': 'end_turn'}}
    value.update(overrides)
    return value


def test_recovery_resume(workspace):
    work, plan, source = workspace
    calls = []
    async def generate(request):
        calls.append(request)
        return output(request)
    rows = asyncio.run(recovery.execute(work, generate=generate))
    assert len(calls) == 139
    assert calls == [t['request'] for t in plan['targets']]
    targets = {t['identity'] for t in plan['targets']}
    for old, new in zip(source, rows):
        assert old['selection'] == new['selection']
        assert old['selection_score'] == new['selection_score']
        if recovery.key(old) not in targets:
            assert old == new
        else:
            assert new['end_to_end_latency_seconds'] == old['selection']['latency_seconds'] + 1.25
            assert new['recovery']['generator_cost_usd'] == pytest.approx(.0015)
    assert asyncio.run(recovery.execute(work, generate=generate)) == rows
    assert len(calls) == 139
    summary = recovery.read_json(work / 'summary.json')
    assert summary['bge_google']['generator_usage']['total_tokens']['n'] == 240
    assert summary['bge_google']['generation_failures'] == 0
    review = recovery.review_template(work)
    assert sum(e['manual_status'] is None for e in review['entries']) == 240
    for entry in review['entries']:
        if entry['manual_status'] is None:
            entry.update(manual_status='correct', reason='Offline synthetic response review.')
    recovery.write_json(work / 'answer_audit.json', review)
    comparison = recovery.validate(work, work / 'answer_audit.json')
    assert comparison['metrics']['bge_google']['accuracy'] == 1
    assert comparison['metrics']['bge_omneum']['accuracy'] == pytest.approx(220 / 240)
    # Validation detects corruption rather than silently regenerating it away.
    damaged = deepcopy(rows)
    damaged[0]['answer'] = 'tampered'
    recovery.atomic(work / 'results.jsonl', b''.join(recovery.encoded(r) + b'\n' for r in damaged))
    with pytest.raises(ValueError, match='Raw recovered records'):
        recovery.validate(work, work / 'answer_audit.json')


def test_ambiguous_recovery(workspace):
    work, plan, _ = workspace
    calls = []
    async def uncertain(request):
        calls.append(request)
        raise KeyboardInterrupt()
    with pytest.raises(KeyboardInterrupt):
        asyncio.run(recovery.execute(work, generate=uncertain))
    assert recovery.read_json(work / 'journal.json')['attempts'][plan['targets'][0]['identity']][-1]['state'] == 'in_flight'
    with pytest.raises(ValueError, match='Uncertain provider outcome'):
        asyncio.run(recovery.execute(work, generate=uncertain))
    assert len(calls) == 1
    # Independently retained, identity-pinned response can reconcile without calls.
    target = plan['targets'][0]
    receipt = {**target, 'source_run_id': recovery.RUN,
        'source_results_sha256': recovery.SOURCE_HASHES['results.jsonl'],
        'generation': output(target['request']), 'started_at_utc': recovery.now(), 'ended_at_utc': recovery.now()}
    recovery.write_json(work / 'response.json', receipt)
    recovery.import_response(work, work / 'response.json')
    assert recovery.read_json(work / 'journal.json')['attempts'][target['identity']][-1]['state'] == 'completed'
    assert len(calls) == 1


def test_projection_write_failure(workspace, monkeypatch):
    work, plan, _ = workspace
    original_materialize = recovery.materialize
    count = 0
    def interrupted(*args, **kwargs):
        nonlocal count
        count += 1
        if count == 2:
            raise KeyboardInterrupt()
        return original_materialize(*args, **kwargs)
    monkeypatch.setattr(recovery, 'materialize', interrupted)
    calls = []
    async def generate(request):
        calls.append(request)
        return output(request)
    with pytest.raises(KeyboardInterrupt):
        asyncio.run(recovery.execute(work, generate=generate))
    monkeypatch.setattr(recovery, 'materialize', original_materialize)
    asyncio.run(recovery.execute(work, generate=generate))
    assert len(calls) == 139  # completed journal response was not called twice


def test_definite_rejection_requires_explicit_retry(workspace):
    work, plan, _ = workspace
    class Rejected(Exception):
        status_code = 400
    async def reject(request):
        raise Rejected()
    with pytest.raises(RuntimeError, match='definite_failure'):
        asyncio.run(recovery.execute(work, generate=reject))
    with pytest.raises(ValueError, match='--retry-failed'):
        asyncio.run(recovery.execute(work, generate=reject))
    assert len(recovery.read_json(work / 'journal.json')['attempts'][plan['targets'][0]['identity']]) == 1


def test_timeout_and_concurrent_execution_cannot_repeat_calls(workspace):
    work, _, _ = workspace
    calls = []
    async def timeout(request):
        calls.append(request)
        raise TimeoutError()
    with (work / '.recovery.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(BlockingIOError):
            asyncio.run(recovery.execute(work, generate=timeout))
    assert not calls
    with pytest.raises(RuntimeError, match='in_flight'):
        asyncio.run(recovery.execute(work, generate=timeout))
    with pytest.raises(ValueError, match='Uncertain provider outcome'):
        asyncio.run(recovery.execute(work, generate=timeout, retry_failed=True))
    assert len(calls) == 1


def test_other_run_receipt_rejected_and_refusal_is_not_success(workspace):
    work, plan, _ = workspace
    target = plan['targets'][0]
    receipt = {**target, 'source_run_id': 'another-run',
        'source_results_sha256': recovery.SOURCE_HASHES['results.jsonl'],
        'generation': output(target['request']), 'started_at_utc': recovery.now(), 'ended_at_utc': recovery.now()}
    recovery.write_json(work / 'response.json', receipt)
    with pytest.raises(ValueError, match='source run/trial/request'):
        recovery.import_response(work, work / 'response.json')
    receipt['source_run_id'] = recovery.RUN
    receipt['generation'] = output(target['request'], text='',
        response_diagnostics={'stop_reason': 'refusal'})
    recovery.write_json(work / 'response.json', receipt)
    rows = recovery.import_response(work, work / 'response.json')
    row = next(r for r in rows if recovery.key(r) == target['identity'])
    assert row['answer_score'] == 'generation_failure' and row['failure_type'] == 'refusal'
    assert row['generation']['input_tokens'] == 250
    with pytest.raises(ValueError, match='Recovery not completed'):
        recovery.review_template(work)


@pytest.mark.parametrize('mutation', ['model', 'usage', 'prompt', 'source', 'receipt'])
def test_configuration_source_and_usage_drift_fail_closed(workspace, mutation):
    work, plan, _ = workspace
    if mutation == 'source':
        (work / 'source_results.jsonl').write_text('{}\n')
    elif mutation == 'prompt':
        saved = recovery.read_json(work / 'manifest.json')
        saved['targets'][0]['request']['prompt'] = 'different'
        recovery.write_json(work / 'manifest.json', saved)
    elif mutation == 'receipt':
        target = plan['targets'][0]
        journal = recovery.read_json(work / 'journal.json')
        journal['attempts'][target['identity']] = [{'identity': target['identity'], 'attempt': 1,
            'request_sha256': 'another request', 'state': 'completed', 'generation': output(target['request'])}]
        recovery.write_json(work / 'journal.json', journal)
    async def generate(request):
        if mutation == 'model':
            return output(request, model='another-model')
        if mutation == 'usage':
            return output(request, input_tokens=None)
        pytest.fail('Invalid workspace must fail before calling a provider')
    with pytest.raises(ValueError):
        asyncio.run(recovery.execute(work, generate=generate))


def test_recovery_request_replay(monkeypatch):
    import anthropic
    observed = []
    class Client:
        def __init__(self, **kwargs):
            observed.append(kwargs)
            self.messages = self
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            pass
        async def create(self, **kwargs):
            observed.append(kwargs)
            return SimpleNamespace(model=recovery.MODEL, id='msg_mock', stop_reason='end_turn',
                content=[SimpleNamespace(type='text', text='mocked')],
                usage=SimpleNamespace(input_tokens=2, output_tokens=3,
                    model_dump=lambda **kw: {'input_tokens': 2, 'output_tokens': 3}))
    monkeypatch.setattr(anthropic, 'AsyncAnthropic', Client)
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'offline-test-value')
    request = {'provider': 'anthropic', 'model': recovery.MODEL, 'prompt': 'frozen prompt',
               'max_tokens': 1024, 'response_schema': None}
    result = asyncio.run(recovery.anthropic_generation(request))
    assert observed == [{'max_retries': 0}, {'model': recovery.MODEL, 'max_tokens': 1024,
                                          'messages': [{'role': 'user', 'content': 'frozen prompt'}]}]
    assert result['provider_message_id'] == 'msg_mock'
    assert result['input_tokens'] == 2 and result['output_tokens'] == 3
