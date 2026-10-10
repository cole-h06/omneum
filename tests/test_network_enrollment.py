"""Operator enrollment and the single production authority, against disposable PostgreSQL."""
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import stat
from uuid import UUID

import pytest
import psycopg

from omneum.ingestion.credentials import CredentialAuthenticator, generate, digest
from omneum.ingestion.service import IngestionService
from omneum.ingestion.limits import IngestionLimits
from omneum.network_api import MinuteQuota
from omneum.network_operator import create_workspace, issue, revoke
from test_ingestion import database, bound, payload


@pytest.fixture
def enrolled(bound, tmp_path):
    db, _, connection, _, workspace = bound
    # Use the least privileged operator role, not superuser table privileges.
    @contextmanager
    def operator():
        with psycopg.connect(db.info.dsn, autocommit=True) as op:
            op.execute('SET ROLE omneum_network_operator')
            yield op
    rows = []
    for number in (1, 2):
        path = tmp_path / f'token-{number}'
        with operator() as op:
            metadata = issue(op, principal=None, output=path, enroll_workspace=workspace,
                             consent_version='test-explicit-consent-1', confirm_consent=True)
        rows.append((metadata, path.read_text().strip(), path))
    return db, connection, operator, rows


def test_independent_credentials_principals_and_hashed_storage(enrolled):
    db, connection, _, rows = enrolled
    auth = CredentialAuthenticator(connection)
    assert rows[0][1] != rows[1][1]
    assert rows[0][0]['principal_id'] != rows[1][0]['principal_id']
    for metadata, token, path in rows:
        assert auth.authenticate(token) == UUID(metadata['principal_id'])
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
        stored = db.execute('SELECT token_sha256 FROM control.ingestion_credentials WHERE id=%s',
                            (UUID(metadata['credential_id']),)).fetchone()[0]
        assert bytes(stored) == digest(token)
        assert token.encode() not in bytes(stored)
        assert token not in json.dumps(metadata)
        assert token not in repr(generate(datetime.now(timezone.utc) + timedelta(days=1)))
    # A selector from contributor A plus contributor B's secret never authenticates.
    a, b = rows[0][1], rows[1][1]
    assert auth.authenticate(a[:38] + b[38:]) is None
    assert auth.authenticate(a[:-1] + ('A' if a[-1] != 'A' else 'B')) is None


def test_cross_principal_receipts_and_budgets(enrolled):
    db, connection, _, rows = enrolled
    auth = CredentialAuthenticator(connection)
    service = IngestionService(authenticator=auth, connection_factory=connection,
        allowed_key_versions=frozenset({1}), limits=IngestionLimits(contributions=1))
    body = json.dumps(payload()).encode()
    receipts = [service.handle(authorization='Bearer ' + token, body=body) for _, token, _ in rows]
    assert all(row.status == 200 for row in receipts)
    assert receipts[0].receipt_id != receipts[1].receipt_id
    assert receipts[0].evaluation_run_id != receipts[1].evaluation_run_id
    for (metadata, token, _), receipt in zip(rows, receipts):
        installation = db.execute('SELECT installation_id FROM control.ingestion_receipts WHERE id=%s',
                                  (receipt.receipt_id,)).fetchone()[0]
        assert str(installation) == metadata['installation_id']
        # Replay remains scoped to its own installation.
        assert service.handle(authorization='Bearer ' + token, body=body) == receipt
        new = payload()
        new['idempotency_key'] = 'second'
        assert service.handle(authorization='Bearer ' + token, body=json.dumps(new).encode()).status == 429
    forbidden = payload()
    forbidden['principal_id'] = rows[1][0]['principal_id']
    assert service.handle(authorization='Bearer ' + rows[0][1], body=json.dumps(forbidden).encode()).status == 400


def test_revocation_isolated_and_contributor_revocation_terminal(enrolled):
    db, connection, operator, rows = enrolled
    auth = CredentialAuthenticator(connection)
    first, second = rows
    with operator() as op:
        revoke(op, credential_id=UUID(first[0]['credential_id']))
    assert auth.authenticate(first[1]) is None
    assert auth.authenticate(second[1]) == UUID(second[0]['principal_id'])
    with operator() as op:
        revoke(op, principal=UUID(second[0]['principal_id']))
        revoke(op, principal=UUID(second[0]['principal_id']))  # idempotent
    assert auth.authenticate(second[1]) is None
    with operator() as op, pytest.raises(PermissionError):
        issue(op, principal=UUID(second[0]['principal_id']), output=second[2].parent / 'revoked-new-token')
    with pytest.raises(psycopg.errors.RaiseException):
        db.execute('UPDATE control.ingestion_credentials SET revoked_at=NULL WHERE id=%s',
                   (UUID(first[0]['credential_id']),))


def test_rotation_does_not_reset_shared_admission_quota(enrolled):
    _, connection, operator, rows = enrolled
    metadata, token, path = rows[0]
    principal = UUID(metadata['principal_id'])
    with operator() as op:
        new = issue(op, principal=principal, output=path.parent / 'rotated')
    auth = CredentialAuthenticator(connection)
    assert auth.authenticate((path.parent / 'rotated').read_text().strip()) == principal
    first = MinuteQuota(2, connection_factory=connection)
    restarted = MinuteQuota(2, connection_factory=connection)
    assert first(principal, '/v1/voprf')
    assert restarted(principal, '/v1/contributions')
    assert not restarted(principal, '/v1/voprf')
    assert first(UUID(rows[1][0]['principal_id']), '/v1/voprf')
    with operator() as op:
        revoke(op, credential_id=UUID(metadata['credential_id']))
    assert auth.authenticate(token) is None
    assert auth.authenticate((path.parent / 'rotated').read_text().strip()) == principal


def test_missing_revoked_consent_and_disabled_principal(enrolled):
    db, connection, _, rows = enrolled
    auth = CredentialAuthenticator(connection)
    metadata, token, _ = rows[0]
    db.execute('UPDATE control.consent_grants SET revoked_at=now() WHERE installation_id=%s',
               (UUID(metadata['installation_id']),))
    assert auth.authenticate(token) is None
    assert auth.authenticate(rows[1][1]) is not None
    db.execute('DELETE FROM control.consent_grants WHERE installation_id=%s',
               (UUID(metadata['installation_id']),))
    assert auth.authenticate(token) is None
    db.execute('UPDATE control.ingestion_principals SET enabled=false WHERE principal_id=%s',
               (UUID(rows[1][0]['principal_id']),))
    assert auth.authenticate(rows[1][1]) is None


def test_expired_credentials_are_rejected(enrolled):
    db, connection, _, rows = enrolled
    metadata = rows[0][0]
    # Backdated fixture simulates expiry without changing an issued credential.
    credential = generate(datetime.now(timezone.utc) - timedelta(days=1))
    db.execute("INSERT INTO control.ingestion_credentials(id,principal_id,token_sha256,issued_at,expires_at) VALUES (%s,%s,%s,clock_timestamp()-interval '2 days',%s)",
               (credential.id, UUID(metadata['principal_id']), credential.token_sha256, credential.expires_at))
    assert CredentialAuthenticator(connection).authenticate(credential.token) is None


def test_operator_permissions_consent_and_output_safety(enrolled):
    db, connection, operator, rows = enrolled
    directory = rows[0][2].parent
    workspace = db.execute('SELECT workspace_id FROM control.ingestion_principals WHERE principal_id=%s',
                           (UUID(rows[0][0]['principal_id']),)).fetchone()[0]
    with operator() as op, pytest.raises(ValueError):
        issue(op, principal=None, output=directory / 'no-consent', enroll_workspace=workspace,
              consent_version='test', confirm_consent=False)
    assert not (directory / 'no-consent').exists()
    with operator() as op, pytest.raises(FileExistsError):
        issue(op, principal=UUID(rows[0][0]['principal_id']), output=rows[0][2])
    target = directory / 'symlink'
    target.symlink_to(rows[0][2])
    with operator() as op, pytest.raises(FileExistsError):
        issue(op, principal=UUID(rows[0][0]['principal_id']), output=target)
    public = directory / 'public'
    public.mkdir(mode=0o755)
    with operator() as op, pytest.raises(PermissionError):
        issue(op, principal=UUID(rows[0][0]['principal_id']), output=public / 'token')
    with connection() as api:
        with pytest.raises(PermissionError):
            create_workspace(api)
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            api.execute('UPDATE control.ingestion_credentials SET revoked_at=clock_timestamp()')
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            api.execute('UPDATE control.ingestion_principals SET enabled=true')


def test_credential_revocation_while_ingestion_waits(enrolled):
    from concurrent.futures import ThreadPoolExecutor
    import time
    db, connection, _, rows = enrolled
    metadata, token, _ = rows[0]
    installation = UUID(metadata['installation_id'])
    lock = int.from_bytes(installation.bytes[:8], 'big', signed=True)
    service = IngestionService(authenticator=CredentialAuthenticator(connection),
        connection_factory=connection, allowed_key_versions=frozenset({1}))
    db.execute('SELECT pg_advisory_lock(%s)', (lock,))
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(service.handle, authorization='Bearer ' + token, body=json.dumps(payload()).encode())
        try:
            deadline = time.monotonic() + 3
            while not db.execute("""SELECT EXISTS (SELECT 1 FROM pg_locks WHERE locktype='advisory'
                    AND NOT granted AND classid=%s AND objid=%s)""",
                    ((lock >> 32) & 0xffffffff, lock & 0xffffffff)).fetchone()[0]:
                assert time.monotonic() < deadline
                time.sleep(.01)
            # Simulate the control plane's committed revocation while this
            # request still holds its earlier authenticated principal.
            db.execute('UPDATE control.ingestion_credentials SET revoked_at=clock_timestamp() WHERE id=%s',
                       (UUID(metadata['credential_id']),))
        finally:
            db.execute('SELECT pg_advisory_unlock(%s)', (lock,))
        assert future.result(timeout=5).status == 401
    assert db.execute('SELECT count(*) FROM control.ingestion_receipts').fetchone()[0] == 0


def test_atomic_admission_across_connections(enrolled):
    from concurrent.futures import ThreadPoolExecutor
    _, connection, _, rows = enrolled
    principal = UUID(rows[0][0]['principal_id'])
    quotas = [MinuteQuota(5, connection_factory=connection) for _ in range(12)]
    with ThreadPoolExecutor(max_workers=12) as pool:
        admitted = list(pool.map(lambda quota: quota(principal, '/v1/voprf'), quotas))
    assert sum(admitted) == 5


def test_operator_cli_issuance_revocation_and_cleanup(enrolled, tmp_path):
    import os
    import subprocess
    import sys
    db, connection, _, _ = enrolled
    # Role-scoped DSN proves exact CLI commands need only operator privileges.
    from psycopg.conninfo import make_conninfo
    dsn_file = tmp_path / 'operator-dsn'
    dsn_file.write_text(make_conninfo(db.info.dsn, options='-c role=omneum_network_operator'))
    dsn_file.chmod(0o600)
    environment = {**os.environ, 'OMNEUM_NETWORK_OPERATOR_DSN_FILE': str(dsn_file)}
    environment.pop('OMNEUM_NETWORK_OPERATOR_DSN', None)
    def run(*args, success=True):
        result = subprocess.run([sys.executable, '-m', 'omneum.network_operator', *args],
                                env=environment, capture_output=True, text=True)
        assert (result.returncode == 0) == success, result.stderr
        return result
    workspace = json.loads(run('create-workspace').stdout)['workspace_id']
    token_file = tmp_path / 'issued-token'
    result = run('enroll', '--workspace-id', workspace, '--consent-version', 'explicit-test-1',
                 '--confirm-consent', '--expires-days', '30', '--output', str(token_file))
    metadata = json.loads(result.stdout)
    token = token_file.read_text().strip()
    assert token not in result.stdout + result.stderr
    assert CredentialAuthenticator(connection).authenticate(token) == UUID(metadata['principal_id'])
    rotated = tmp_path / 'rotated-token'
    rotation = json.loads(run('issue', '--principal-id', metadata['principal_id'],
                             '--output', str(rotated)).stdout)
    run('revoke-credential', '--credential-id', metadata['credential_id'])
    assert CredentialAuthenticator(connection).authenticate(token) is None
    assert CredentialAuthenticator(connection).authenticate(rotated.read_text().strip()) == UUID(metadata['principal_id'])
    run('revoke-contributor', '--principal-id', metadata['principal_id'])
    assert CredentialAuthenticator(connection).authenticate(rotated.read_text().strip()) is None
    assert json.loads(run('prune-quotas', '--retention-days', '2').stdout) == {'deleted': 0}
    error = run('enroll', '--workspace-id', workspace, '--consent-version', 'explicit-test-1',
                '--output', str(tmp_path / 'missing-consent'), success=False)
    assert not (tmp_path / 'missing-consent').exists()
    error = run('issue', '--principal-id', token, '--output', str(tmp_path / 'bad'), success=False)
    assert token not in error.stdout + error.stderr


def test_http_identity_and_revocation_on_both_routes(enrolled):
    from omneum.transport.network import NetworkHTTPApp
    from omneum.oprf import VOPRFServer
    from test_network_bootstrap import FixtureDaemonContext
    from test_evaluate_context import make_state
    from test_network_http import call, request
    db, connection, operator, rows = enrolled
    auth = CredentialAuthenticator(connection)
    service = IngestionService(authenticator=auth, connection_factory=connection,
                               allowed_key_versions=frozenset({1}))
    with FixtureDaemonContext(b'\x02' + bytes(31)) as remote, FixtureDaemonContext(b'\x03' + bytes(31)) as local:
        app = NetworkHTTPApp(network_state=make_state(server=VOPRFServer(remote.context)),
            local_public_key=local.public_key, authenticator=auth, ingestion=service,
            rate_limiter=MinuteQuota(600, connection_factory=connection))
        def headers(token, claimed_principal):
            return [(b'authorization', ('Bearer ' + token).encode()),
                    (b'content-type', b'application/json'),
                    (b'x-principal-id', claimed_principal.encode())]
        try:
            for index, (metadata, token, _) in enumerate(rows):
                status, result = call(app, json.dumps(payload()).encode(), '/v1/contributions',
                                      headers=headers(token, rows[1-index][0]['principal_id']))
                assert status == 200
                installation = db.execute('SELECT installation_id FROM control.ingestion_receipts WHERE id=%s',
                                          (UUID(result['receipt_id']),)).fetchone()[0]
                assert str(installation) == metadata['installation_id']
            with operator() as op:
                revoke(op, credential_id=UUID(rows[0][0]['credential_id']))
            for route in ('/v1/voprf', '/v1/contributions'):
                assert call(app, b'{}', route, headers=headers(rows[0][1], rows[1][0]['principal_id']))[0] == 401
            _, _, value = request(remote)
            assert call(app, json.dumps(value).encode(), headers=headers(rows[1][1], rows[0][0]['principal_id']))[0] == 200
            assert call(app, json.dumps(payload()).encode(), '/v1/contributions',
                        headers=headers(rows[1][1], rows[0][0]['principal_id']))[0] == 200
        finally:
            app.close()
