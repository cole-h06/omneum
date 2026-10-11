"""Single-VM configuration and acceptance security regressions; no live accounts."""
import asyncio
from contextlib import asynccontextmanager, closing
import json
from pathlib import Path
import re
import sys
from types import SimpleNamespace

import pytest

from omneum import network_deploy as deploy
from omneum.base64url import encode_unpadded
from daemon_support import FixtureDaemon


@pytest.fixture
def configuration():
    # These are synthetic public configuration values, not proposed release pins.
    with closing(FixtureDaemon(b'\x01' + b'\0'*31)) as a, closing(FixtureDaemon(b'\x02' + b'\0'*31)) as b:
        yield dict(domain='network.fixture-audit.net', deployment_id='urn:uuid:8d96fc18-f40f-4ec7-8ae8-f3711d88b741',
            network_key_version=1, network_public_key=encode_unpadded(b.public_key, expected_length=32),
            local_public_key=encode_unpadded(a.public_key, expected_length=32), database_host='db.fixture-audit.net',
            database_port=25060, database_name='omneum_prod', database_ca='/etc/omneum-network/secrets/database-ca.pem',
            ingestion_dsn_file='/etc/omneum-network/secrets/ingestion.dsn', enrollment_dsn_file='/etc/omneum-network/secrets/enrollment.dsn',
            tls_certificate='/etc/omneum-network/secrets/tls.crt', tls_private_key='/etc/omneum-network/secrets/tls.key',
            oidc_issuer='https://identity.fixture-audit.net/', oidc_audience='omneum-enrollment',
            oidc_jwks_uri='https://identity.fixture-audit.net/.well-known/jwks.json', oidc_jwks_file='/etc/omneum-network/secrets/jwks.json',
            oidc_device_endpoint='https://identity.fixture-audit.net/oauth/device/code',
            oidc_token_endpoint='https://identity.fixture-audit.net/oauth/token', oidc_verification_uri='https://identity.fixture-audit.net/activate',
            oidc_client_id='public-client', consent_url='https://network.fixture-audit.net/consent', consent_version='audit-v1')


def test_template_never_validates():
    template = json.loads((Path(__file__).parents[1] / 'deploy/network/vm/production.json').read_text())
    assert set(template) == deploy.FIELDS
    assert template['database_name'] == 'omneum_prod'
    with pytest.raises(ValueError):
        deploy.validate_config(template)


def test_hosted_migrations_are_relational_and_match_docker():
    root = Path(__file__).parents[1]
    # Both deployment paths must work without installing AGE or the local schema.
    assert 'production_002_context_graph.sql' not in deploy.MIGRATIONS
    statements = '\n'.join((root / 'migrations' / name).read_text()
                           for name in deploy.MIGRATIONS)
    extensions = re.findall(r'CREATE EXTENSION(?: IF NOT EXISTS)?\s+(\w+)', statements, re.I)
    assert set(extensions) == {'pgcrypto'}
    assert not re.search(r"LOAD\s+'age'|ag_catalog\.", statements, re.I)
    docker = (root / 'deploy/network/init-postgres.sh').read_text()
    assert tuple(re.findall(r'production_\w+\.sql', docker)) == deploy.MIGRATIONS


def test_generated_runtime_dsns_share_production_database(configuration, tmp_path, monkeypatch):
    from psycopg.conninfo import conninfo_to_dict
    c = {**configuration,
         'ingestion_dsn_file': str(tmp_path / 'ingestion.dsn'),
         'enrollment_dsn_file': str(tmp_path / 'enrollment.dsn')}
    # File generation needs no administrator ownership checks or DB connection.
    monkeypatch.setattr(deploy, 'safe_path', lambda *args, **kwargs: None)
    deploy.generate_dsns(c)
    passwords = set()
    for field, role in (('ingestion_dsn_file', 'omneum_ingestion'),
                        ('enrollment_dsn_file', 'omneum_enrollment')):
        path = Path(c[field])
        settings = conninfo_to_dict(path.read_text())
        assert settings['dbname'] == 'omneum_prod'
        assert settings['user'] == role
        assert settings['sslmode'] == 'verify-full'
        assert path.stat().st_mode & 0o777 == 0o600
        passwords.add(settings['password'])
        monkeypatch.setattr(deploy, 'private_read', lambda filename: Path(filename).read_bytes())
        assert conninfo_to_dict(deploy.database_settings(c, str(path), role))['dbname'] == 'omneum_prod'
    assert len(passwords) == 2


@pytest.mark.parametrize('field,value', [('domain', 'example.com'), ('domain', 'network.localhost'),
    ('domain', 'domain.net;\ninclude evil;'), ('database_host', '127.0.0.1'), ('network_key_version', True),
    ('database_port', 0), ('database_name', 'x; DROP TABLE control.installations;'),
    ('oidc_token_endpoint', 'http://identity.fixture-audit.net/token'),
    ('oidc_device_endpoint', 'https://attacker.fixture-audit.net/device'),
    ('oidc_issuer', 'https://identity.fixture-audit.net/'), ('ingestion_dsn_file', '/etc/../tmp/key'),
    ('consent_version', 'a b'), ('oidc_client_id', 'client$HOME'), ('network_public_key', 'A'*43)])
def test_configuration_rejects_injection_and_placeholders(configuration, field, value):
    if field == 'oidc_issuer':
        value = 'https://identity.fixture-audit.net'
    with pytest.raises(Exception):
        deploy.validate_config({**configuration, field: value})


def test_units_and_ingress_preserve_boundaries(configuration):
    deploy.validate_config(configuration)
    ingestion = deploy.service_unit(configuration, 'ingestion', 31001)
    enrollment = deploy.service_unit(configuration, 'enrollment', 31001)
    evaluator = deploy.service_unit(configuration, 'evaluator', 31001)
    assert 'User=omneum-network-api' in ingestion
    assert 'User=omneum-enrollment' in enrollment
    assert 'User=omneum-network-crypto' in evaluator
    assert '--client-uid 31001' in evaluator and '--session-gid' not in evaluator
    assert 'PrivateNetwork=yes' in evaluator and 'RestrictAddressFamilies=AF_UNIX\n' in evaluator
    assert 'LoadCredential=database.dsn:' + configuration['enrollment_dsn_file'] in enrollment
    assert configuration['ingestion_dsn_file'] not in enrollment
    assert configuration['enrollment_dsn_file'] not in ingestion
    assert 'LoadCredential=account-jwks' not in ingestion
    assert 'InaccessiblePaths=/var/lib/omneum-network-crypto /run/omneum-network' in enrollment
    assert 'ReadOnlyPaths=/var/lib/omneum-network-crypto' in evaluator
    assert 'PASSWORD' not in ingestion + enrollment + evaluator
    nginx = deploy.nginx_config(configuration)
    assert 'proxy_ssl_verify on' in nginx and 'https://127.0.0.1:8444' in nginx
    assert 'client_max_body_size 1m' in nginx and 'client_max_body_size 4k' in nginx
    assert 'access_log off' in nginx and 'error.log crit' in nginx
    assert 'limit_req zone=omneum_enroll' in nginx and 'limit_conn omneum_conn 4' in nginx
    assert 'X-Forwarded-Proto ""' in nginx


def test_release_pins_fail_closed(configuration):
    with pytest.raises(ValueError, match='provisioned'):
        deploy.pins_match(configuration)


def test_matching_and_mismatched_release(configuration, monkeypatch):
    from omneum.contribution import network
    from omneum import onboarding
    from omneum.base64url import decode_unpadded
    c = configuration
    base = 'https://' + c['domain']
    monkeypatch.setattr(network, '_PRODUCTION_NETWORK', network._ProductionNetwork(base+'/v1/contributions',
        base+'/v1/voprf', c['deployment_id'], 1, decode_unpadded(c['network_public_key'], expected_length=32)))
    monkeypatch.setattr(onboarding, '_PRODUCTION_ONBOARDING', onboarding.OnboardingPins(base+'/v1/enrollment',
        c['oidc_device_endpoint'], c['oidc_token_endpoint'], c['oidc_verification_uri'], c['oidc_client_id'],
        'omneum:enroll', c['consent_url'], c['consent_version'], c['oidc_audience']))
    deploy.pins_match(c)
    with pytest.raises(ValueError, match='mismatch'):
        deploy.pins_match({**c, 'oidc_audience': 'other'})


@pytest.mark.parametrize('change', [{'sslmode': 'require'}, {'user': 'admin'}, {'host': 'attacker.net'},
    {'dbname': 'omneum_network'}, {'service': 'redirect'}, {'sslrootcert': '/tmp/untrusted'}, {'options': '-c role=admin'}])
def test_database_dsn_cannot_override_trust(configuration, monkeypatch, change):
    from psycopg.conninfo import make_conninfo
    c = configuration
    settings = dict(host=c['database_host'], port=c['database_port'], dbname=c['database_name'],
                    user='omneum_ingestion', password='private-test-password', sslmode='verify-full')
    monkeypatch.setattr(deploy, 'private_read', lambda path: make_conninfo(**{**settings, **change}).encode())
    with pytest.raises(ValueError):
        deploy.database_settings(c, c['ingestion_dsn_file'], 'omneum_ingestion')


def test_provider_discovery_must_match(configuration, monkeypatch):
    c = configuration
    discovery = dict(issuer=c['oidc_issuer'], jwks_uri=c['oidc_jwks_uri'], token_endpoint=c['oidc_token_endpoint'],
        device_authorization_endpoint=c['oidc_device_endpoint'], id_token_signing_alg_values_supported=['RS256'],
        grant_types_supported=['urn:ietf:params:oauth:grant-type:device_code'])
    monkeypatch.setattr(deploy, 'fetch_json', lambda url: discovery)
    assert deploy.provider_settings(c) == discovery
    discovery['issuer'] = 'https://attacker.net/'
    with pytest.raises(ValueError, match='discovery'):
        deploy.provider_settings(c)


def test_acceptance_payload_uses_real_domain_separation_and_proofs(configuration, monkeypatch):
    from omneum.network_acceptance import proof_payload
    from omneum.contribution.network import HTTPSNetworkEvaluator
    from omneum.contribution.validation import decode
    from omneum.base64url import decode_unpadded
    with closing(FixtureDaemon(b'\x02' + b'\0'*31)) as remote:
        async def evaluation(self, **kwargs):
            return remote.context.evaluate(kwargs['blinded_element'])
        monkeypatch.setattr(HTTPSNetworkEvaluator, 'evaluate', evaluation)
        result = asyncio.run(proof_payload(configuration, 'private-test-token', remote.public_key))
        decode(json.dumps(result).encode())
        assert 'acceptance.invalid' not in json.dumps(result)
        assert len(decode_unpadded(result['sources'][0]['source_token'], expected_length=64)) == 64


def test_local_outage_acceptance_uses_real_mcp_sqlite(example_daemon, monkeypatch):
    import omneum
    from omneum import onboarding
    from omneum.network_acceptance import local_outage
    from omneum.contribution import network
    from mcp import StdioServerParameters
    original = omneum.open_stdio_client
    @asynccontextmanager
    async def direct(config, parameters, **kwargs):
        async with original(config, StdioServerParameters(command=sys.executable, args=['-m', 'omneum.server'],
            env=parameters.env), **kwargs) as client:
            yield client
    monkeypatch.setattr(omneum, 'open_stdio_client', direct)
    monkeypatch.setattr(onboarding, 'stored_credential', lambda: 'private-test-token')
    with closing(FixtureDaemon(b'\x02' + b'\0'*31)) as remote:
        monkeypatch.setattr(network, '_PRODUCTION_NETWORK', network._ProductionNetwork(
            'https://network.example.test/v1/contributions', 'https://network.example.test/v1/voprf',
            'urn:uuid:8d96fc18-f40f-4ec7-8ae8-f3711d88b741', 1, remote.public_key))
        asyncio.run(local_outage())
