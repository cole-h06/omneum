"""Narrow HTTPS boundaries and release-owned Network pins."""
import asyncio
import json
from uuid import uuid4

import pytest

from omneum import OmneumNetwork, HTTPSNetworkEvaluator, HTTPSContributionTransport
from omneum.base64url import encode_unpadded
from omneum.contribution import network as module
from omneum.transport.network import NetworkHTTPApp
from omneum.ingestion.service import IngestionResponse
from test_adversarial_pipeline import server, SECOND_KEY
from test_evaluate_context import make_state
from test_client_contribution import run
from test_local_persistence import runtime
from test_storage_evaluation import computed
from test_ingestion import service, payload, bound, database, PRINCIPAL


@pytest.fixture
def app(tmp_path):
    remote = server(tmp_path, SECOND_KEY)
    local = server(tmp_path, b'\x03' + b'\x00' * 31)
    class Auth:
        def authenticate(self, token):
            return PRINCIPAL if token == 'test-key' else None
    auth = Auth()
    result = NetworkHTTPApp(network_state=make_state(server=remote),
        local_public_key=local.public_key, authenticator=auth,
        ingestion=service(auth=auth), rate_limiter=lambda principal, path: True)
    yield result, remote, local
    result.close()


def call(app, body, path='/v1/voprf', **changes):
    scope = dict(type='http', scheme='https', path=path, method='POST', query_string=b'',
                 headers=[(b'authorization', b'Bearer test-key'), (b'content-type', b'application/json')])
    scope.update(changes)
    events = []
    chunks = body if isinstance(body, list) else [body]
    async def receive():
        return dict(type='http.request', body=chunks.pop(0), more_body=bool(chunks))
    async def send(event):
        events.append(event)
    asyncio.run(app(scope, receive, send))
    return events[0]['status'], json.loads(events[1]['body'])


def request(remote):
    blind = module.VOPRFClient(remote.public_key).blind(b'private-source')
    evaluator = HTTPSNetworkEvaluator('https://example.test/v1/voprf', 'test-key',
                                     make_state(server=remote).deployment_id, 1)
    value = dict(protocol_version='v1', deployment_id=evaluator.deployment_id,
                 voprf_key_version=1, voprf_mode='voprf',
                 voprf_ciphersuite='ristretto255-SHA512', linkage_encoding_version=1,
                 blinded_element=encode_unpadded(blind.blinded_element, expected_length=32))
    return evaluator, blind, value


def test_factory_pending_and_secret_safe(monkeypatch):
    monkeypatch.setattr(module, '_PRODUCTION_NETWORK', None)
    with pytest.raises(RuntimeError) as error:
        OmneumNetwork.pseudonymous(api_key='private-api-key')
    assert 'private-api-key' not in str(error.value)
    for secret in ('private-key\n', '', None):
        with pytest.raises(ValueError) as error:
            OmneumNetwork.pseudonymous(api_key=secret)
        assert 'private-key' not in str(error.value)


def test_factory_constructs_pinned_dependencies(app, monkeypatch):
    remote = app[1]
    pins = module._ProductionNetwork('https://example.test/v1/contributions',
        'https://example.test/v1/voprf', make_state(server=remote).deployment_id, 1, remote.public_key)
    monkeypatch.setattr(module, '_PRODUCTION_NETWORK', pins)
    monkeypatch.setenv('OMNEUM_NETWORK_ENDPOINT', 'https://attacker.test')
    config = OmneumNetwork.pseudonymous(api_key='private-api-key')
    assert config.linkage.public_key == remote.public_key
    assert config.transport.endpoint == pins.ingestion_endpoint
    assert config.evaluator.endpoint == pins.voprf_endpoint
    assert config.evaluator.key_version == 1
    assert 'private-api-key' not in repr(config) + repr(config.evaluator) + repr(config.transport)


@pytest.mark.parametrize('override', ['endpoint', 'public_key', 'key_version', 'evaluator', 'transport'])
def test_factory_rejects_overrides(override):
    with pytest.raises(TypeError):
        OmneumNetwork.pseudonymous(api_key='key', **{override: 'override'})


def test_round_trip_proof(app, monkeypatch):
    adapter, remote, _ = app
    evaluator, blind, value = request(remote)
    def send(self, body):
        status, response = call(adapter, body)
        assert status == 200
        return json.dumps(response).encode()
    monkeypatch.setattr(HTTPSNetworkEvaluator, '_send', send)
    evaluation = asyncio.run(evaluator.evaluate(key_version=1, blinded_element=blind.blinded_element))
    assert len(module.VOPRFClient(remote.public_key).finalize(input_data=b'private-source',
        client_state=blind.client_state, evaluation=evaluation)) == 64


@pytest.mark.parametrize('mutation', [
    lambda v: v.update(metadata='private'), lambda v: v.update(voprf_key_version=True),
    lambda v: v.update(voprf_key_version=2), lambda v: v.update(voprf_mode='oprf'),
    lambda v: v.update(linkage_encoding_version=2), lambda v: v.update(protocol_version='v2'),
    lambda v: v.update(deployment_id='urn:uuid:00000000-0000-0000-0000-000000000099'),
    lambda v: v.update(blinded_element='bad'),
    lambda v: v.update(blinded_element=encode_unpadded(b'\0'*32, expected_length=32)),
])
def test_strict_voprf_request(app, mutation):
    _, _, value = request(app[1])
    mutation(value)
    status, response = call(app[0], json.dumps(value).encode())
    assert status == 400
    assert 'private' not in json.dumps(response)


@pytest.mark.parametrize('body', [b'{', b'[]', b'{"a":1,"a":2}', b'[' * 4096])
def test_bad_json(app, body):
    assert call(app[0], body)[0] == 400


@pytest.mark.parametrize('changes,status', [({'scheme': 'http'}, 400),
    ({'method': 'GET'}, 405), ({'path': '/v1/voprf/'}, 404),
    ({'query_string': b'key=secret'}, 404),
    ({'headers': [(b'authorization', b'Bearer test-key')]*2}, 401),
    ({'headers': [(b'authorization', b'Bearer wrong')]}, 401),
    ({'headers': [(b'authorization', b'Bearer test-key'), (b'content-type', b'text/plain')]}, 415),
    ({'headers': [(b'x', b'a'*16385)]}, 431)])
def test_http_envelope(app, changes, status):
    assert call(app[0], b'{}', **changes)[0] == status


def test_stream_bounded_before_core(app):
    assert call(app[0], [b'x'*4096, b'x'])[0] == 413
    assert call(app[0], [b'x'*1048576, b'x'], '/v1/contributions')[0] == 413


@pytest.mark.parametrize('policy', [lambda *a: False, lambda *a: 1])
def test_rate_limit_fails_closed(app, policy):
    app[0]._rate_limiter = policy
    assert call(app[0], b'{}')[0] == 429


def test_ingestion_adapter(app, monkeypatch):
    accepted = IngestionResponse(200, 'accepted', uuid4(), uuid4())
    calls = []
    def handle(**kw):
        calls.append(kw)
        return accepted
    monkeypatch.setattr(app[0]._ingestion, 'handle', handle)
    body = json.dumps(payload()).encode()
    status, result = call(app[0], body, '/v1/contributions')
    assert status == 200 and result['receipt_id'] == str(accepted.receipt_id)
    assert calls == [dict(authorization='Bearer test-key', body=body)]


def test_ingestion_adapter_core_errors(app):
    assert call(app[0], b'{}', '/v1/contributions') == (400, dict(
        status=400, code='invalid_contribution', receipt_id=None, evaluation_run_id=None))


def test_adapter_to_real_persist(app, bound):
    db, ingestion, *_ = bound
    app[0]._ingestion = ingestion
    assert call(app[0], json.dumps(payload()).encode(), '/v1/contributions')[0] == 200
    assert db.execute('SELECT count(*) FROM network.evaluation_runs').fetchone()[0] == 1


def test_server_key_distinct(app):
    with pytest.raises(ValueError, match='distinct'):
        NetworkHTTPApp(network_state=make_state(server=app[1]), local_public_key=app[1].public_key,
            authenticator=object(), ingestion=service(), rate_limiter=lambda *a: True)


def test_server_requires_shared_credential_authority(app):
    ingestion = service()
    with pytest.raises(ValueError, match='credential authority'):
        NetworkHTTPApp(network_state=make_state(server=app[1]),
            local_public_key=app[2].public_key, authenticator=object(),
            ingestion=ingestion, rate_limiter=lambda *a: True)


def test_server_requires_ingestable_key_version(app):
    from dataclasses import replace
    ingestion = service()
    with pytest.raises(ValueError, match='key version'):
        NetworkHTTPApp(network_state=replace(make_state(server=app[1]), voprf_key_version=2),
            local_public_key=app[2].public_key, authenticator=ingestion.authenticator,
            ingestion=ingestion, rate_limiter=lambda *a: True)


@pytest.mark.parametrize('path', ['/v1/voprf', '/v1/contributions'])
def test_core_exception_is_secret_safe(app, monkeypatch, path):
    def broken(**kwargs):
        raise RuntimeError('private-api-key private-database-credential')
    async def broken_evaluation(request):
        return broken()
    monkeypatch.setattr(app[0]._ingestion, 'handle', broken)
    monkeypatch.setattr(app[0]._evaluation, 'evaluate', broken_evaluation)
    _, _, value = request(app[1])
    status, response = call(app[0], json.dumps(value).encode(), path)
    assert status == 503
    assert response == {'code': 'evaluation_unavailable' if path == '/v1/voprf'
                        else 'ingestion_unavailable'}


@pytest.mark.parametrize('mutation', [lambda v: v.update(proof='bad'),
    lambda v: v.update(evaluated_element='bad'), lambda v: v.update(voprf_key_version=True),
    lambda v: v.update(voprf_key_version=2), lambda v: v.update(protocol_version='v2'),
    lambda v: v.update(metadata='private-api-key'), lambda v: v.update(voprf_ciphersuite='bad'),
    lambda v: v.update(linkage_encoding_version=2), lambda v: v.update(voprf_mode='oprf'),
    lambda v: v.update(deployment_id='urn:uuid:00000000-0000-0000-0000-000000000099')])
def test_strict_voprf_response(app, monkeypatch, mutation):
    evaluator, blind, value = request(app[1])
    _, response = call(app[0], json.dumps(value).encode())
    mutation(response)
    monkeypatch.setattr(HTTPSNetworkEvaluator, '_send', lambda *a: json.dumps(response).encode())
    with pytest.raises(RuntimeError) as error:
        asyncio.run(evaluator.evaluate(key_version=1, blinded_element=blind.blinded_element))
    assert 'private-api-key' not in str(error.value)
    assert error.value.__suppress_context__


def test_client_http_no_redirects_proxies(app, monkeypatch):
    evaluator, blind, value = request(app[1])
    _, response = call(app[0], json.dumps(value).encode())
    class Response:
        status = 200
        def read(self, size):
            assert size == 4097
            return json.dumps(response).encode()
        def __enter__(self): return self
        def __exit__(self, *a): pass
    class Opener:
        def open(self, req, *, timeout):
            assert req.get_header('Authorization') == 'Bearer test-key'
            assert set(json.loads(req.data)) == set(value)
            return Response()
    def opener(*handlers):
        assert handlers[0].proxies == {}
        assert handlers[1].redirect_request(None, None, None, None, None, None) is None
        return Opener()
    monkeypatch.setattr(module, 'build_opener', opener)
    asyncio.run(evaluator.evaluate(key_version=1, blinded_element=blind.blinded_element))


@pytest.mark.parametrize('raw,status', [(b'{}', 302), (b'{}', 401), (b'{}', 503),
                                       (b'x'*4097, 200), (b'{"proof":1,"proof":2}', 200)])
def test_client_response_boundary(app, monkeypatch, raw, status):
    evaluator, blind, _ = request(app[1])
    class Response:
        def read(self, size): return raw
        def __enter__(self): return self
        def __exit__(self, *a): pass
    Response.status = status
    class Opener:
        def open(self, *a, **kw): return Response()
    monkeypatch.setattr(module, 'build_opener', lambda *a: Opener())
    with pytest.raises(RuntimeError):
        asyncio.run(evaluator.evaluate(key_version=1, blinded_element=blind.blinded_element))


@pytest.mark.parametrize('version,element', [(True, b'x'*32), (2, b'x'*32), (1, b'x'*33),
                                          (1, 'private-source')])
def test_invalid_client_input_never_sent(app, monkeypatch, version, element):
    evaluator, *_ = request(app[1])
    monkeypatch.setattr(HTTPSNetworkEvaluator, '_send', lambda *a: pytest.fail('sent invalid input'))
    with pytest.raises(RuntimeError):
        asyncio.run(evaluator.evaluate(key_version=version, blinded_element=element))


def test_factory_contributes_through_both_http_boundaries(app, runtime, monkeypatch):
    adapter, remote, _ = app
    pins = module._ProductionNetwork('https://example.test/v1/contributions',
        'https://example.test/v1/voprf', make_state(server=remote).deployment_id, 1, remote.public_key)
    monkeypatch.setattr(module, '_PRODUCTION_NETWORK', pins)
    monkeypatch.setenv('OMNEUM_API_KEY', 'test-key')
    monkeypatch.setenv('OMNEUM_NETWORK_CONTRIBUTION', 'true')
    evaluations, contributions = [], []
    def evaluate(self, body):
        evaluations.append(body)
        status, response = call(adapter, body)
        assert status == 200
        return json.dumps(response).encode()
    def ingest(self, body):
        contributions.append(body)
        status, response = call(adapter, body, '/v1/contributions')
        assert status == 200
    from omneum.ingestion.validation import decode
    def handle(**kw):
        decode(kw['body'], frozenset({1}))
        return IngestionResponse(200, 'accepted', uuid4(), uuid4())
    monkeypatch.setattr(HTTPSNetworkEvaluator, '_send', evaluate)
    monkeypatch.setattr(HTTPSContributionTransport, '_send', ingest)
    monkeypatch.setattr(adapter._ingestion, 'handle', handle)
    run(runtime, local_persistence=None)
    assert not evaluations and not contributions
    run(runtime, local_persistence=None,
        network_contribution=OmneumNetwork.pseudonymous(api_key='test-key'))
    assert len(evaluations) == 4 and len(contributions) == 1
    for observation in runtime[2]:
        assert observation.source.identifier.encode() not in b''.join(evaluations + contributions)
        assert observation.claim.value.encode() not in b''.join(evaluations + contributions)


def test_rate_limiter_exception_secret_safe(app):
    def broken(*a):
        raise RuntimeError('private-api-key')
    app[0]._rate_limiter = broken
    assert call(app[0], b'{}') == (429, {'code': 'rate_limited'})


@pytest.mark.parametrize('endpoint', ['http://example.test', 'https://user:private@example.test',
    'https://example.test?key=private', 'https://exam\tple.test', 'https://example.test:0'])
def test_network_evaluator_endpoint_hardening(endpoint):
    with pytest.raises(ValueError) as error:
        HTTPSNetworkEvaluator(endpoint, 'private-api-key',
            'urn:uuid:00000000-0000-0000-0000-000000000001', 1)
    assert 'private' not in str(error.value)


def test_ingestion_cancellation_retains_capacity_until_worker_finishes(app, monkeypatch):
    import threading
    entered, release = threading.Event(), threading.Event()
    def handle(**kw):
        entered.set()
        assert release.wait(5)
        return IngestionResponse(503, 'ingestion_unavailable')
    monkeypatch.setattr(app[0]._ingestion, 'handle', handle)
    async def exercise():
        scope = dict(type='http', scheme='https', path='/v1/contributions', method='POST',
            headers=[(b'authorization', b'Bearer test-key'), (b'content-type', b'application/json')])
        async def receive(): return dict(type='http.request', body=b'{}')
        async def send(event): pass
        task = asyncio.create_task(app[0](scope, receive, send))
        try:
            assert await asyncio.to_thread(entered.wait, 5)
            task.cancel()
            await asyncio.sleep(0)
            assert app[0]._active == 1 and not task.done()
            task.cancel()
            await asyncio.sleep(0)
            assert app[0]._active == 1 and not task.done()
        finally:
            release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert app[0]._active == 0
    asyncio.run(exercise())
