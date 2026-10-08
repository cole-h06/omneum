"""Checks at the final outbound byte boundary, including bypassed model validation."""
import asyncio
import json

import pytest

from omneum import HTTPSContributionTransport
from omneum.contribution.models import ContributionDependency
from test_contribution import minimal_contribution
from test_client_contribution import run, network
from test_local_persistence import runtime
from test_storage_evaluation import computed


@pytest.mark.parametrize('mutation', [
    lambda p: setattr(p.sources[0], 'source_token', 'https://private.example/source'),
    lambda p: setattr(p.claims[0], 'claim_token', 'private claim value'),
    lambda p: setattr(p.sources[0], 'key_version', True),
    lambda p: setattr(p.sources[0], 'source_kind', 'private-source-identifier'),
    lambda p: setattr(p, 'schema_version', 'publication'),
    lambda p: setattr(p, 'idempotency_key', '/private/context.db'),
    lambda p: setattr(p, 'sources', p.sources * 2001),
    lambda p: setattr(p.sources[0], '__pydantic_extra__', {'identifier': 'private-source'}),
    lambda p: setattr(p, '__pydantic_extra__', {'metadata': {'secret': 'credential'}}),
    lambda p: setattr(p, 'dependencies', (ContributionDependency.model_construct(
        source_low_id='source-1', source_high_id='source-2', dependency_score=0.5,
        signal_components={'private-source-identifier': 0.5}),)),
])
def test_invalid_exact_wire_never_sent(monkeypatch, mutation):
    payload = minimal_contribution()
    mutation(payload)
    monkeypatch.setattr(HTTPSContributionTransport, '_send',
                        lambda *args: pytest.fail('invalid bytes crossed the boundary'))
    with pytest.raises(RuntimeError) as caught:
        asyncio.run(HTTPSContributionTransport('https://example.com/ingest', 'token').submit(payload))
    assert 'private' not in str(caught.value)
    assert 'credential' not in str(caught.value)
    assert caught.value.__suppress_context__


@pytest.mark.parametrize('endpoint', [
    '\nhttps://example.com/ingest', ' https://example.com',
    'https://exam\tple.com/ingest', 'https://example.com/private\npath',
    'https://example.com:invalid', 'https://example.com:65536',
    'https://example.com:0', 'https://example.com/#private',
])
def test_endpoint_does_not_silently_normalize(endpoint):
    with pytest.raises(ValueError) as caught:
        HTTPSContributionTransport(endpoint, 'token')
    assert endpoint not in str(caught.value)


@pytest.mark.parametrize('field', ['receipt_id', 'evaluation_run_id'])
@pytest.mark.parametrize('value', [None, 1, '00000000000000000000000000000001',
    '{00000000-0000-0000-0000-000000000001}', '00000000-0000-0000-0000-00000000000A'])
def test_noncanonical_receipt_fails_closed(monkeypatch, field, value):
    from omneum.contribution import config as module
    response = dict(status=200, code='accepted',
        receipt_id='00000000-0000-0000-0000-000000000001',
        evaluation_run_id='00000000-0000-0000-0000-000000000002')
    response[field] = value
    class Response:
        status = 200
        def read(self, size): return json.dumps(response).encode()
        def __enter__(self): return self
        def __exit__(self, *args): pass
    class Opener:
        def open(self, *args, **kwargs): return Response()
    monkeypatch.setattr(module, 'build_opener', lambda *args: Opener())
    with pytest.raises(RuntimeError, match='acceptance may be uncertain'):
        asyncio.run(HTTPSContributionTransport('https://example.test', 'private-api-key')
                    .submit(minimal_contribution()))


def test_environment_does_not_opt_in(runtime, network, monkeypatch):
    for name in ('OMNEUM_NETWORK_CONTRIBUTION', 'OMNEUM_CONTRIBUTE',
                 'OMNEUM_NETWORK_ENDPOINT', 'OMNEUM_POSTGRES_DSN', 'DATABASE_URL'):
        monkeypatch.setenv(name, 'https://example.com/ingest')
    run(runtime)
    assert network[1:] == ([], [])


def test_builder_exact_allowlist(runtime, network, monkeypatch):
    bodies = []
    monkeypatch.setattr(HTTPSContributionTransport, '_send', lambda self, body: bodies.append(body))
    run(runtime, network_contribution=network[0])
    wire = json.loads(bodies[0])
    assert set(wire) == {'schema_version', 'idempotency_key', 'evaluator_version',
                         'estimator_version', 'sources', 'claims', 'observations',
                         'source_scores', 'claim_scores', 'dependencies'}
    expected = {
        'sources': {'source_id', 'source_token', 'source_kind', 'key_version'},
        'claims': {'claim_id', 'claim_token', 'key_version'},
        'observations': {'source_id', 'claim_id', 'observation_type', 'observed_bucket'},
        'source_scores': {'source_id', 'reliability', 'contribution_score'},
        'claim_scores': {'claim_id', 'support', 'supporting_source_count',
                         'estimated_independent_support_count', 'dependency_cluster_count',
                         'dependency_signal_coverage'},
        'dependencies': {'source_low_id', 'source_high_id', 'dependency_score',
            'upstream_signal', 'citation_signal', 'assertion_lineage_signal',
            'ownership_signal', 'temporal_signal', 'graph_signal', 'retrieval_signal',
            'signal_coverage', 'signal_components', 'source_low_upstream_of_source_high',
            'source_high_upstream_of_source_low', 'source_low_cites_source_high',
            'source_high_cites_source_low', 'source_low_parent_count', 'source_high_parent_count',
            'same_owner', 'matching_claim_count', 'qualifying_time_deltas_seconds'},
    }
    for collection, fields in expected.items():
        assert wire[collection]
        assert all(set(item) == fields for item in wire[collection])
    assert all(s['source_id'] == f's{i:08d}' for i, s in enumerate(wire['sources']))
    assert all(c['claim_id'] == f'c{i:08d}' for i, c in enumerate(wire['claims']))
