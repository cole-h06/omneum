"""Network-only bootstrap policies; no external services or credentials."""
from uuid import uuid4

import pytest

from omneum.network_api import MinuteQuota, setting
from omneum.ingestion.credentials import CredentialAuthenticator, generate
from datetime import datetime, timedelta, timezone


def test_mounted_secret_and_ambiguous_configuration(tmp_path, monkeypatch):
    monkeypatch.delenv('NETWORK_TEST_SECRET', raising=False)
    monkeypatch.delenv('NETWORK_TEST_SECRET_FILE', raising=False)
    with pytest.raises(ValueError, match='exactly one'):
        setting('NETWORK_TEST_SECRET')
    secret = tmp_path / 'secret'
    secret.write_text('disposable-test-secret\n')
    monkeypatch.setenv('NETWORK_TEST_SECRET_FILE', str(secret))
    assert setting('NETWORK_TEST_SECRET') == 'disposable-test-secret'
    monkeypatch.setenv('NETWORK_TEST_SECRET', 'ambiguous')
    with pytest.raises(ValueError, match='exactly one'):
        setting('NETWORK_TEST_SECRET')


def test_malformed_credentials_do_not_access_storage():
    def forbidden():
        pytest.fail('malformed token accessed database')
    auth = CredentialAuthenticator(forbidden)
    for token in ('incorrect', '', 'secret\n', None):
        assert auth.authenticate(token) is None


def test_quota_is_independent_and_shared(bound):
    db, _, connection, _, _ = bound
    from test_ingestion import PRINCIPAL
    first, second = MinuteQuota(2, connection_factory=connection), MinuteQuota(2, connection_factory=connection)
    assert first(PRINCIPAL, '/v1/voprf')
    assert second(PRINCIPAL, '/v1/contributions')
    assert not first(PRINCIPAL, '/v1/voprf')
    db.execute("UPDATE control.network_admission_budgets SET window_start=window_start - interval '1 minute'")
    assert second(PRINCIPAL, '/v1/voprf')
    with pytest.raises(ValueError):
        MinuteQuota(0, connection_factory=connection)


def test_factory_with_disposable_postgres(bound, monkeypatch, tmp_path):
    import json
    import os
    from psycopg.conninfo import make_conninfo
    from omneum.base64url import encode_unpadded
    from omneum.network_api import create_app
    from test_ingestion import PRINCIPAL, payload
    from test_network_http import call, request

    db, _, _, _, _ = bound
    db.execute('ALTER ROLE omneum_ingestion LOGIN')
    from omneum.network_operator import issue
    secret_file = tmp_path / 'credential'
    issue(db, principal=PRINCIPAL, output=secret_file)
    credential = secret_file.read_text().strip()
    with FixtureDaemonContext(b'\x02' + bytes(31)) as remote, FixtureDaemonContext(b'\x03' + bytes(31)) as local:
        values = {
            'OMNEUM_NETWORK_DEPLOYMENT_ID': 'urn:uuid:8d96fc18-f40f-4ec7-8ae8-f3711d88b741',
            'OMNEUM_NETWORK_KEY_VERSION': '1',
            'OMNEUM_NETWORK_PUBLIC_KEY': encode_unpadded(remote.public_key, expected_length=32),
            'OMNEUM_LOCAL_PUBLIC_KEY': encode_unpadded(local.public_key, expected_length=32),
            'OMNEUM_NETWORK_DATABASE_DSN': make_conninfo(db.info.dsn, user='omneum_ingestion'),
            'OMNEUM_DAEMON_SOCKET': str(remote.socket),
            'OMNEUM_DAEMON_UID': str(os.getuid()),
        }
        for name, value in values.items():
            monkeypatch.setenv(name, value)
            monkeypatch.delenv(name + '_FILE', raising=False)
        adapter = create_app()
        headers = [(b'authorization', ('Bearer ' + credential).encode()),
                   (b'content-type', b'application/json')]
        try:
            assert call(adapter, b'{}')[0] == 401
            _, _, value = request(remote)
            assert call(adapter, json.dumps(value).encode(), headers=headers)[0] == 200
            status, receipt = call(adapter, json.dumps(payload()).encode(), '/v1/contributions', headers=headers)
            assert status == 200
            assert db.execute('SELECT count(*) FROM control.ingestion_receipts').fetchone()[0] == 1
            for statement, restore in (
                ('UPDATE control.ingestion_principals SET enabled=false',
                 'UPDATE control.ingestion_principals SET enabled=true'),
                ('UPDATE control.consent_grants SET revoked_at=now()',
                 'UPDATE control.consent_grants SET revoked_at=NULL')):
                db.execute(statement)
                for route in ('/v1/voprf', '/v1/contributions'):
                    assert call(adapter, b'{}', route, headers=headers)[0] == 401
                db.execute(restore)
            assert db.execute('SELECT count(*) FROM control.ingestion_receipts').fetchone()[0] == 1
        finally:
            adapter.close()
        restarted = create_app()
        try:
            assert call(restarted, json.dumps(payload()).encode(), '/v1/contributions', headers=headers) == (status, receipt)
        finally:
            restarted.close()
        exercise_https_entrypoint(tmp_path, values, value, payload(), receipt, credential)


class FixtureDaemonContext:
    def __init__(self, key):
        from daemon_support import FixtureDaemon
        self.daemon = FixtureDaemon(key)

    def __enter__(self):
        return self.daemon

    def __exit__(self, *args):
        self.daemon.close()


# Reuse the existing isolated PostgreSQL fixture and its production migration order.
from test_ingestion import bound, database


def exercise_https_entrypoint(tmp_path, settings, voprf_request, contribution, receipt, credential):
    """Start the shipped entrypoint twice, using only disposable fixtures."""
    import json
    import os
    import socket
    import signal
    import ssl
    import subprocess
    import sys
    import time
    from urllib.error import HTTPError, URLError
    from urllib.request import Request, urlopen

    with socket.socket() as available:
        try:
            available.bind(('127.0.0.1', 8443))
        except OSError:
            pytest.skip('port 8443 is occupied; ASGI factory checks completed')
    cert, key = tmp_path / 'tls.crt', tmp_path / 'tls.key'
    subprocess.run(['openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-days', '1',
        '-subj', '/CN=localhost', '-addext', 'subjectAltName=DNS:localhost',
        '-keyout', str(key), '-out', str(cert)], check=True, capture_output=True)
    environ = {**os.environ, **settings, 'OMNEUM_NETWORK_TLS_CERT': str(cert),
               'OMNEUM_NETWORK_TLS_KEY': str(key)}
    context = ssl.create_default_context(cafile=str(cert))

    def post(path, body, credential):
        request = Request('https://localhost:8443' + path, data=json.dumps(body).encode(),
            headers={'Content-Type': 'application/json', 'Authorization': 'Bearer ' + credential})
        try:
            response = urlopen(request, context=context, timeout=2)
        except HTTPError as error:
            response = error
        with response:
            return response.code, json.loads(response.read())

    for _ in range(2):
        with (tmp_path / 'api.log').open('w') as log:
            process = subprocess.Popen([sys.executable, '-m', 'omneum.network_api'],
                env=environ, stdout=log, stderr=log)
            try:
                for attempt in range(100):
                    assert process.poll() is None, (tmp_path / 'api.log').read_text()
                    try:
                        assert post('/v1/voprf', {}, 'invalid-test-token')[0] == 401
                        break
                    except URLError:
                        time.sleep(.05)
                else:
                    pytest.fail('HTTPS entrypoint startup timed out')
                assert post('/v1/voprf', voprf_request, credential)[0] == 200
                assert post('/v1/contributions', contribution, credential) == (200, receipt)
            finally:
                process.terminate()
                try:
                    # Uvicorn restores and re-raises the captured termination
                    # signal after completing ASGI lifespan shutdown.
                    assert process.wait(timeout=10) in (0, -signal.SIGTERM)
                    assert 'Application shutdown complete' in (tmp_path / 'api.log').read_text()
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
                    pytest.fail('API did not shut down gracefully')


def test_authorization_outage_is_secret_safe():
    def unavailable():
        raise RuntimeError('disposable-secret-database-password')
    auth = CredentialAuthenticator(unavailable)
    token = generate(datetime.now(timezone.utc) + timedelta(days=1)).token
    assert auth.authenticate(token) is None


@pytest.mark.parametrize('config', [
    {'host': 'db.example.com'},
    {'host': 'db.example.com', 'sslmode': 'require'},
    {'host': 'localhost', 'hostaddr': '192.0.2.1', 'sslmode': 'prefer'},
    {'host': 'localhost,db.example.com'},
])
def test_remote_database_requires_verified_tls(config, monkeypatch):
    from omneum.network_api import validate_database_transport
    monkeypatch.delenv('PGSSLMODE', raising=False)
    with pytest.raises(ValueError, match='verify-full'):
        validate_database_transport(config)


@pytest.mark.parametrize('config', [
    {'host': '/tmp/test-postgres'}, {'host': 'localhost'}, {'host': '127.0.0.1'},
    {'host': '::1'}, {'host': 'db.example.com', 'sslmode': 'verify-full'},
])
def test_local_database_and_verified_remote_allowed(config, monkeypatch):
    from omneum.network_api import validate_database_transport
    monkeypatch.delenv('PGHOSTADDR', raising=False)
    validate_database_transport(config)


def test_remote_database_environment_is_checked(monkeypatch):
    from omneum.network_api import validate_database_transport
    monkeypatch.setenv('PGHOST', 'db.example.com')
    monkeypatch.setenv('PGSSLMODE', 'prefer')
    with pytest.raises(ValueError, match='verify-full'):
        validate_database_transport({})


@pytest.mark.parametrize('attribute', ['SUPERUSER', 'CREATEROLE', 'CREATEDB', 'REPLICATION', 'BYPASSRLS'])
def test_elevated_ingestion_role_rejected(bound, attribute):
    from omneum.network_api import validate_database_role
    db, _, connections, _, _ = bound
    db.execute('ALTER ROLE omneum_ingestion ' + attribute)
    try:
        with connections() as connection:
            with pytest.raises(ValueError, match='unsafe privileges'):
                validate_database_role(connection)
    finally:
        db.execute('ALTER ROLE omneum_ingestion NO' + attribute)


def test_role_membership_cannot_bypass_privilege_check(bound):
    from omneum.network_api import validate_database_role
    db, _, connections, _, _ = bound
    db.execute('GRANT omneum_network_operator TO omneum_ingestion')
    db.execute('ALTER ROLE omneum_network_operator CREATEROLE')
    try:
        with connections() as connection:
            with pytest.raises(ValueError, match='unsafe privileges'):
                validate_database_role(connection)
    finally:
        db.execute('REVOKE omneum_network_operator FROM omneum_ingestion')
        db.execute('ALTER ROLE omneum_network_operator NOCREATEROLE')


def test_database_service_cannot_hide_insecure_transport(monkeypatch):
    from omneum.network_api import validate_database_transport
    monkeypatch.setenv('PGSSLMODE', 'verify-full')
    with pytest.raises(ValueError, match='explicit sslmode'):
        validate_database_transport({'service': 'hidden-remote'})


def test_ingestion_schema_ownership_rejected(bound):
    from omneum.network_api import validate_database_role
    db, _, connections, _, _ = bound
    owner = db.execute('SELECT current_user').fetchone()[0]
    from psycopg import sql
    db.execute('ALTER SCHEMA network OWNER TO omneum_ingestion')
    try:
        with connections() as connection:
            with pytest.raises(ValueError, match='unsafe privileges'):
                validate_database_role(connection)
    finally:
        db.execute(sql.SQL('ALTER SCHEMA network OWNER TO {}').format(sql.Identifier(owner)))


def test_operator_mounted_dsn_and_ambiguity(tmp_path, monkeypatch):
    from omneum.network_operator import setting as operator_setting
    path = tmp_path / 'dsn'
    path.write_text('disposable-test-dsn\n')
    monkeypatch.delenv('OMNEUM_NETWORK_OPERATOR_DSN', raising=False)
    monkeypatch.setenv('OMNEUM_NETWORK_OPERATOR_DSN_FILE', str(path))
    assert operator_setting('OMNEUM_NETWORK_OPERATOR_DSN') == 'disposable-test-dsn'
    monkeypatch.setenv('OMNEUM_NETWORK_OPERATOR_DSN', 'ambiguous')
    with pytest.raises(ValueError, match='exactly one'):
        operator_setting('OMNEUM_NETWORK_OPERATOR_DSN')
