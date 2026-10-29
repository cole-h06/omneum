"""Automatic client contribution uses separate linkage and a narrow wire contract."""
import asyncio
from pathlib import Path
from uuid import uuid4

import pytest

from omneum import (OmneumClient, NetworkContributionConfig, NetworkLinkageConfig,
    HTTPSContributionTransport, NetworkContributionError,
    LocalPersistenceConfig)
from omneum.ingestion.validation import decode
from omneum.storage import PostgresStorage
from test_local_persistence import runtime
from test_storage_evaluation import computed
from test_adversarial_pipeline import server, SECOND_KEY


@pytest.fixture
def network(tmp_path, monkeypatch):
    network_server = server(tmp_path, SECOND_KEY)
    calls, submitted = [], []

    class Evaluator:
        async def evaluate(self, *, key_version, blinded_element):
            calls.append((key_version, blinded_element))
            return network_server.evaluate(blinded_element)

    def send(self, body):
        submitted.append(decode(body, frozenset({1})))

    monkeypatch.setattr(HTTPSContributionTransport, '_send', send)
    config = NetworkContributionConfig(
        linkage=NetworkLinkageConfig(1, network_server.public_key), evaluator=Evaluator(),
        transport=HTTPSContributionTransport('https://ingestion.example/contributions', 'test-token'))
    return config, calls, submitted


def run(runtime, **kwargs):
    config, evaluator, observations, estimator = runtime
    return asyncio.run(OmneumClient(config, evaluator, **kwargs)._evaluate_context(
        observations, estimator=estimator))


@pytest.mark.parametrize('explicit', [False, True])
def test_default_network_off(runtime, network, monkeypatch, explicit):
    def forbidden(*args, **kwargs):
        pytest.fail('persistence called')
    monkeypatch.setattr(LocalPersistenceConfig, '_persist', forbidden)
    run(runtime, local_persistence=None, **({'network_contribution': None} if explicit else {}))
    assert network[1:] == ([], [])


@pytest.mark.parametrize('contribute', [False, True])
def test_local_independent(runtime, network, monkeypatch, contribute):
    writes = []
    monkeypatch.setattr(LocalPersistenceConfig, '_persist', lambda self, **kw: writes.append(kw))
    local = LocalPersistenceConfig(PostgresStorage(object()), uuid4())
    result = run(runtime, local_persistence=local,
                 network_contribution=network[0] if contribute else None)
    assert writes[0]['evaluation'] is result
    assert len(network[2]) == int(contribute)


def test_pseudonymous_without_storage(runtime, network, monkeypatch, caplog):
    def forbidden(*a, **kw):
        pytest.fail('local persistence invoked')
    monkeypatch.setattr(LocalPersistenceConfig, '_persist', forbidden)
    result = run(runtime, local_persistence=None, network_contribution=network[0])
    payload = network[2][0]
    assert len(network[1]) == 4
    wire = payload.model_dump_json()
    for secret in ('private-', 'https://', 'metadata', 'retrieved_text'):
        assert secret not in wire
        assert secret not in caplog.text
    assert len(payload.source_scores) == len(result.source_reliability)
    assert len(payload.observations) == len(runtime[2])
    assert all(version == 1 and len(blinded) == 32 for version, blinded in network[1])
    for observation in runtime[2]:
        for secret in (observation.source.identifier, observation.claim.entity, observation.claim.value):
            assert secret not in wire
    pair = result.pairwise_dependencies[0]
    dependency = payload.dependencies[0]
    ids = {r.source.identifier: s.source_id for r, s in zip(result.source_reliability, payload.sources)}
    low_is_a = ids[pair.source_a.identifier] == dependency.source_low_id
    assert dependency.source_low_cites_source_high == (
        pair.evidence.source_a_cites_source_b if low_is_a else pair.evidence.source_b_cites_source_a)
    assert dependency.dependency_score == pair.dependency
    assert dependency.same_owner == pair.evidence.same_owner



def test_stable_network_tokens(runtime, network, tmp_path):
    from dataclasses import replace
    from test_client import LocalEvaluator, make_config
    from test_evaluate_context import make_state
    from omneum.tools.evaluate_context import AssertionEvaluationService
    local_server = server(tmp_path, b'\x03' + b'\x00' * 31)
    deployment = 'urn:uuid:00000000-0000-0000-0000-000000000003'
    config = replace(make_config(local_server), deployment_id=deployment)
    service = AssertionEvaluationService(replace(make_state(server=local_server), deployment_id=deployment))
    class Evaluator(LocalEvaluator):
        async def evaluate_voprf(self, request):
            result = await super().evaluate_voprf(request)
            result.structuredContent['deployment_id'] = deployment
            return result
        async def evaluate_context(self, request):
            return await service.evaluate(request)
    try:
        run(runtime, network_contribution=network[0])
        run((config, Evaluator(local_server), runtime[2], runtime[3]), network_contribution=network[0])
    finally:
        service.close()
    first, second = network[2]
    assert {s.source_token for s in first.sources} == {s.source_token for s in second.sources}
    assert {c.claim_token for c in first.claims} == {c.claim_token for c in second.claims}
    assert first.idempotency_key != second.idempotency_key
    from omneum.base64url import encode_unpadded
    local = OmneumClient(runtime[0], runtime[1])
    source = runtime[2][0].source
    token = asyncio.run(local.link_source(source.kind, source.identifier))
    assert encode_unpadded(token.value, expected_length=64) not in {s.source_token for s in first.sources}


def test_failed_submission_preserves_evaluation_and_retry(runtime, network, monkeypatch):
    def fail(self, body):
        raise OSError('secret credential request body')
    monkeypatch.setattr(HTTPSContributionTransport, '_send', fail)
    with pytest.raises(NetworkContributionError) as caught:
        run(runtime, local_persistence=None, network_contribution=network[0])
    assert caught.value.evaluation.claim_support
    assert caught.value.contribution.idempotency_key
    assert not caught.value.local_persistence_succeeded
    assert 'secret' not in str(caught.value)
    assert caught.value.__suppress_context__


@pytest.mark.parametrize('endpoint', ['http://example.com', 'postgresql://example.com/db',
    'https://user:pass@example.com', 'https://example.com?token=secret'])
def test_transport_requires_narrow_https(endpoint):
    with pytest.raises(ValueError):
        HTTPSContributionTransport(endpoint, 'token')


def test_modes_require_explicit_configuration():
    with pytest.raises(TypeError):
        NetworkContributionConfig()
    with pytest.raises(TypeError):
        NetworkContributionConfig(mode='public', transport=HTTPSContributionTransport('https://example.com', 'token'))
    assert 'token' not in repr(HTTPSContributionTransport('https://example.com', 'token'))


def test_client_has_no_production_sql_path():
    for path in (Path('omneum/client.py'), *Path('omneum/contribution').glob('*.py')):
        source = path.read_text()
        assert 'psycopg' not in source
        assert 'connection_factory' not in source
        assert 'omneum.ingestion' not in source


def test_structured_claims(runtime, network):
    from dataclasses import replace
    from omneum import Claim
    observations = tuple(replace(o, claim=Claim(o.claim.entity_namespace, o.claim.entity,
        o.claim.attribute, {'secret': ['private-value', 1]})) for o in runtime[2])
    run((*runtime[:2], observations, runtime[3]), network_contribution=network[0])
    assert 'private-value' not in network[2][0].model_dump_json()


def test_linkage_failure_prevents_upload(runtime, network, monkeypatch):
    async def fail(**kwargs):
        raise ValueError('private input')
    monkeypatch.setattr(network[0].evaluator, 'evaluate', fail)
    with pytest.raises(NetworkContributionError) as caught:
        run(runtime, network_contribution=network[0])
    assert caught.value.reason == 'contribution_preparation_failed'
    assert caught.value.evaluation.claim_support
    assert caught.value.contribution is None
    assert not network[2]


def test_local_failure_prevents_contribution(runtime, network, monkeypatch):
    from omneum import LocalPersistenceError
    def fail(*a, **kw):
        raise ValueError('private database')
    monkeypatch.setattr(LocalPersistenceConfig, '_persist', fail)
    with pytest.raises(LocalPersistenceError) as caught:
        run(runtime, local_persistence=LocalPersistenceConfig(PostgresStorage(object()), uuid4()),
            network_contribution=network[0])
    assert caught.value.evaluation.claim_support
    assert network[1:] == ([], [])


def test_network_key_must_be_separate(runtime, network):
    from dataclasses import replace
    config = replace(network[0], linkage=NetworkLinkageConfig(1, runtime[0].voprf_public_key))
    with pytest.raises(ValueError, match='distinct'):
        OmneumClient(runtime[0], runtime[1], network_contribution=config)


def test_no_driver_required():
    import subprocess
    import sys
    script = '''
import importlib.abc
import sys
class NoPostgres(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, *args):
        if fullname == "psycopg" or fullname.startswith("psycopg."):
            raise ModuleNotFoundError("postgres deliberately unavailable")
sys.meta_path.insert(0, NoPostgres())
import pytest
sys.exit(pytest.main(["-q", "tests/test_client_contribution.py::test_pseudonymous_without_storage"]))
'''
    result = subprocess.run([sys.executable, '-c', script], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr


def test_real_stdio_contribution(tmp_path, computed, network):
    import sys
    from omneum.mcp import StdioServerParameters
    from test_client import DEPLOYMENT_ID, PRIVATE_KEY
    from stdio_state import isolated_deployment_environment
    from omneum import OmneumClientConfig, open_stdio_client
    directory = tmp_path / 'stdio'
    directory.mkdir()
    env, key, _ = isolated_deployment_environment(directory, DEPLOYMENT_ID, PRIVATE_KEY)
    params = StdioServerParameters(command=sys.executable, args=['-m', 'omneum.server'],
                                   cwd=Path(__file__).resolve().parents[1], env=env)
    config = OmneumClientConfig(DEPLOYMENT_ID, 1, 'voprf', 'ristretto255-SHA512', 1, key)
    async def evaluate():
        async with open_stdio_client(config, params, network_contribution=network[0]) as client:
            return await client._evaluate_context(computed[4], estimator=computed[3])
    assert asyncio.run(evaluate()).claim_support
    assert len(network[2]) == 1
    assert 'test-token' not in repr(params)


def test_http_wire_contract(monkeypatch):
    import json
    from omneum.contribution import config as module
    from test_contribution import minimal_contribution
    payload = minimal_contribution()
    requests = []
    class Response:
        status = 200
        def read(self, size):
            assert size == 4097
            return json.dumps(dict(status=200, code='accepted', receipt_id=str(uuid4()),
                                   evaluation_run_id=str(uuid4()))).encode()
        def __enter__(self): return self
        def __exit__(self, *args): pass
    class Opener:
        def open(self, request, *, timeout):
            requests.append(request)
            assert timeout == 10.0
            return Response()
    def opener(*handlers):
        assert handlers[0].proxies == {}
        assert handlers[1].redirect_request(None, None, None, None, None, None) is None
        return Opener()
    monkeypatch.setattr(module, 'build_opener', opener)
    asyncio.run(HTTPSContributionTransport('https://ingestion.example/contributions', 'token').submit(payload))
    request = requests[0]
    assert request.get_method() == 'POST'
    assert request.get_header('Authorization') == 'Bearer token'
    assert request.data == payload.model_dump_json().encode()


@pytest.mark.parametrize('body,status', [(b'{}', 200), (b'x' * 4097, 200),
    (b'not json', 200), (b'{}', 302), (b'{}', 401), (b'{}', 503)])
def test_http_fails_closed(monkeypatch, body, status):
    from omneum.contribution import config as module
    from test_contribution import minimal_contribution
    class Response:
        def read(self, size): return body
        def __enter__(self): return self
        def __exit__(self, *args): pass
    Response.status = status
    class Opener:
        def open(self, *args, **kwargs): return Response()
    monkeypatch.setattr(module, 'build_opener', lambda *args: Opener())
    with pytest.raises(RuntimeError, match='acceptance may be uncertain'):
        asyncio.run(HTTPSContributionTransport('https://example.com', 'token').submit(minimal_contribution()))


from test_storage import db, workspace
from test_ingestion import database, bound


def test_both_with_real_storage(runtime, network, db, workspace):
    run(runtime, local_persistence=LocalPersistenceConfig(PostgresStorage(db), workspace),
        network_contribution=network[0])
    assert len(network[2]) == 1
    assert db.execute('SELECT count(*) FROM public.evaluation_runs WHERE workspace_id=%s',
                      (workspace,)).fetchone()[0] == 1


def test_client_to_ingestion_service(runtime, network, bound, monkeypatch):
    from dataclasses import replace
    db, handler, *_ = bound
    accepted = []
    def send(self, body):
        response = handler.handle(authorization='Bearer ' + self.bearer_token, body=body)
        assert response.status == 200
        accepted.append(response)
    monkeypatch.setattr(HTTPSContributionTransport, '_send', send)
    transport = replace(network[0].transport, bearer_token='test-key')
    config = replace(network[0], transport=transport)
    run(runtime, network_contribution=config)
    assert len(accepted) == 1
    assert db.execute('SELECT count(*) FROM network.evaluation_runs').fetchone()[0] == 1
    assert db.execute('SELECT count(*) FROM network.observations').fetchone()[0] == len(runtime[2])
    assert db.execute('SELECT count(*) FROM public.observations').fetchone()[0] == 0


def test_network_failure_after_local_success_and_retry(runtime, network, monkeypatch, caplog):
    original = HTTPSContributionTransport._send
    def fail(*args, **kwargs):
        raise RuntimeError('private secret request')
    writes = []
    monkeypatch.setattr(LocalPersistenceConfig, '_persist', lambda self, **kw: writes.append(kw))
    monkeypatch.setattr(HTTPSContributionTransport, '_send', fail)
    with pytest.raises(NetworkContributionError) as caught:
        run(runtime, local_persistence=LocalPersistenceConfig(PostgresStorage(object()), uuid4()),
            network_contribution=network[0])
    error = caught.value
    assert error.local_persistence_succeeded
    assert writes[0]['evaluation'] is error.evaluation
    assert 'private secret' not in str(error) + caplog.text
    monkeypatch.setattr(HTTPSContributionTransport, '_send', original)
    asyncio.run(network[0].transport.submit(error.contribution))
    assert network[2][0].idempotency_key == error.contribution.idempotency_key


def test_wrong_network_proof_prevents_upload(runtime, network, monkeypatch):
    async def wrong_key(*, key_version, blinded_element):
        return runtime[1].server.evaluate(blinded_element)
    monkeypatch.setattr(network[0].evaluator, 'evaluate', wrong_key)
    with pytest.raises(NetworkContributionError) as caught:
        run(runtime, network_contribution=network[0])
    assert caught.value.reason == 'contribution_preparation_failed'
    assert not network[2]
