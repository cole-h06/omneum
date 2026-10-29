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
from test_local_persistence import runtime
from test_storage_evaluation import computed


@pytest.fixture
def self_service(bound):
    from omneum.enrollment import EnrollmentService
    db, _, _, _, _ = bound
    @contextmanager
    def connection():
        with psycopg.connect(db.info.dsn, autocommit=True) as op:
            op.execute('SET ROLE omneum_enrollment')
            yield op
    return db, EnrollmentService(connection, 'consent-test-1'), bound[2]


def enrollment(action='enroll', installation=None, **changes):
    from omneum.enrollment import EnrollmentRequest
    from uuid import uuid4
    return EnrollmentRequest(action=action, installation_id=str(installation or uuid4()),
        **({'consent': True, 'consent_version': 'consent-test-1'} if action == 'enroll' else {}), **changes)


def test_self_service_lifecycle_and_contribution(self_service):
    from omneum.ingestion.credentials import CredentialAuthenticator
    db, service, connection = self_service
    identity = b'a' * 32
    request = enrollment()
    first = service.handle(identity, request)
    auth = CredentialAuthenticator(connection)
    principal = auth.authenticate(first['api_key'])
    assert principal is not None and first['consent_active']
    assert db.execute('SELECT consent_version FROM control.consent_grants WHERE installation_id=%s',
                      (UUID(first['installation_id']),)).fetchone() == ('consent-test-1',)
    ingest = IngestionService(authenticator=auth, connection_factory=connection, allowed_key_versions=frozenset({1}))
    body = json.dumps(payload()).encode()
    receipt = ingest.handle(authorization='Bearer '+first['api_key'], body=body)
    assert receipt.status == 200
    renewed = service.handle(identity, enrollment('renew', request.installation_id))
    assert auth.authenticate(first['api_key']) is None
    assert auth.authenticate(renewed['api_key']) == principal
    # Replay uses installation history across key rotation.
    assert ingest.handle(authorization='Bearer '+renewed['api_key'], body=body) == receipt
    rotated = service.handle(identity, enrollment('rotate', request.installation_id))
    assert auth.authenticate(renewed['api_key']) is None
    assert auth.authenticate(rotated['api_key']) == principal
    service.handle(identity, enrollment('revoke', request.installation_id))
    assert auth.authenticate(rotated['api_key']) is None
    assert service.handle(identity, enrollment('status', request.installation_id))['consent_active']
    recovered = service.handle(identity, enrollment('renew', request.installation_id))
    service.handle(identity, enrollment('withdraw', request.installation_id))
    assert auth.authenticate(recovered['api_key']) is None
    assert not service.handle(identity, enrollment('status', request.installation_id))['consent_active']
    with pytest.raises(PermissionError):
        service.handle(identity, enrollment('renew', request.installation_id))
    assert db.execute('SELECT count(*) FROM control.ingestion_receipts').fetchone() == (1,)


@pytest.mark.parametrize('action', ['enroll', 'renew', 'rotate', 'revoke', 'withdraw', 'status'])
def test_self_service_cannot_use_another_installation(self_service, action):
    _, service, connection = self_service
    request = enrollment()
    token = service.handle(b'a'*32, request)['api_key']
    with pytest.raises(PermissionError):
        service.handle(b'b'*32, enrollment(action, request.installation_id))
    assert CredentialAuthenticator(connection).authenticate(token) is not None


@pytest.mark.parametrize('consent,version', [(False, 'consent-test-1'), (True, None), (True, 'old')])
def test_self_service_requires_current_explicit_consent(self_service, consent, version):
    from omneum.enrollment import EnrollmentRequest
    from uuid import uuid4
    db, service, _ = self_service
    with pytest.raises(PermissionError):
        service.handle(b'a'*32, EnrollmentRequest(action='enroll', installation_id=str(uuid4()),
                       consent=consent, consent_version=version))
    assert db.execute('SELECT count(*) FROM control.contributor_accounts').fetchone() == (0,)


def test_duplicate_enrollment_and_admission(self_service):
    from concurrent.futures import ThreadPoolExecutor
    db, service, _ = self_service
    request = enrollment()
    def attempt(_):
        try:
            return service.handle(b'a'*32, request)
        except FileExistsError:
            return None
    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(attempt, range(6)))
    assert sum(result is not None for result in results) == 1
    assert db.execute('SELECT count(*) FROM control.account_installations').fetchone() == (1,)
    for _ in range(4):
        service.handle(b'a'*32, enrollment('status', request.installation_id))
    with pytest.raises(OverflowError):
        service.handle(b'a'*32, enrollment('status', request.installation_id))


def test_account_and_admin_installation_suspension(self_service):
    db, service, connection = self_service
    request = enrollment()
    token = service.handle(b'a'*32, request)['api_key']
    db.execute('UPDATE control.contributor_accounts SET enabled=false')
    assert CredentialAuthenticator(connection).authenticate(token) is None
    with pytest.raises(PermissionError):
        service.handle(b'a'*32, enrollment('renew', request.installation_id))
    db.execute('UPDATE control.contributor_accounts SET enabled=true')
    db.execute('UPDATE control.ingestion_principals SET enabled=false WHERE installation_id=%s', (UUID(request.installation_id),))
    with pytest.raises(PermissionError):
        service.handle(b'a'*32, enrollment('rotate', request.installation_id))


def test_expired_credential_can_only_be_recovered_with_account(self_service):
    db, service, connection = self_service
    request = enrollment()
    token = service.handle(b'a'*32, request)['api_key']
    principal = CredentialAuthenticator(connection).authenticate(token)
    expired = generate(datetime.now(timezone.utc) - timedelta(hours=1))
    db.execute('INSERT INTO control.ingestion_credentials(id,principal_id,token_sha256,issued_at,expires_at) VALUES(%s,%s,%s,%s,%s)',
        (expired.id, principal, expired.token_sha256, datetime.now(timezone.utc)-timedelta(hours=2), expired.expires_at))
    assert CredentialAuthenticator(connection).authenticate(expired.token) is None
    renewed = service.handle(b'a'*32, enrollment('renew', request.installation_id))
    assert CredentialAuthenticator(connection).authenticate(renewed['api_key']) == principal


def test_enrollment_role_cannot_write_network_or_rebind(self_service):
    db, service, _ = self_service
    service.handle(b'a'*32, enrollment())
    with service.connection_factory() as op:
        for sql in ('SELECT * FROM network.evaluation_runs',
                    'UPDATE control.contributor_accounts SET enabled=true',
                    'UPDATE control.ingestion_principals SET workspace_id=workspace_id'):
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                op.execute(sql)


def test_self_service_installation_slots_and_immutable_bindings(self_service):
    db, service, _ = self_service
    requests = [enrollment() for _ in range(10)]
    for request in requests:
        service.handle(b'a'*32, request)
    db.execute('DELETE FROM control.enrollment_budgets')
    with pytest.raises(PermissionError, match='installation limit'):
        service.handle(b'a'*32, enrollment())
    # Even administrator SQL must not accidentally reassign report history.
    with pytest.raises(psycopg.errors.RaiseException):
        db.execute('UPDATE control.account_installations SET identity_sha256=%s', (b'b'*32,))


def test_enrollment_factory_privilege_boundary(self_service, oidc, monkeypatch):
    from psycopg.conninfo import make_conninfo
    from omneum.enrollment_api import create_app
    db, _, _ = self_service
    account, _ = oidc
    db.execute('ALTER ROLE omneum_enrollment LOGIN')
    settings = dict(OMNEUM_ENROLLMENT_DATABASE_DSN=make_conninfo(db.info.dsn, user='omneum_enrollment'),
        OMNEUM_ACCOUNT_ISSUER=account.issuer, OMNEUM_ACCOUNT_AUDIENCE=account.audience,
        OMNEUM_ACCOUNT_JWKS=str(account.jwks_path), OMNEUM_NETWORK_CONSENT_VERSION='consent-test-1')
    for key, value in settings.items():
        monkeypatch.setenv(key, value)
        monkeypatch.delenv(key+'_FILE', raising=False)
    assert create_app().service.consent_version == 'consent-test-1'
    db.execute('GRANT SELECT ON network.evaluation_runs TO omneum_enrollment')
    try:
        with pytest.raises(ValueError, match='must not access Network report tables'):
            create_app()
    finally:
        db.execute('REVOKE SELECT ON network.evaluation_runs FROM omneum_enrollment')


@pytest.fixture
def oidc(tmp_path):
    import jwt
    from cryptography.hazmat.primitives.asymmetric import rsa
    from omneum.enrollment import OIDCAuthenticator
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(private.public_key()))
    jwk.update(kid='test-key', use='sig', alg='RS256')
    path = tmp_path / 'account-jwks.json'
    path.write_text(json.dumps({'keys': [jwk]}))
    auth = OIDCAuthenticator(issuer='https://account.example.test', audience='omneum-enrollment', jwks_path=path)
    now = int(datetime.now(timezone.utc).timestamp())
    claims = dict(iss=auth.issuer, aud=auth.audience, sub='account-test', iat=now,
                  nbf=now, exp=now+300, scope='openid omneum:enroll')
    def token(_omit=(), _headers=None, **changes):
        value = {**claims, **changes}
        for name in _omit:
            value.pop(name, None)
        return jwt.encode(value, private, algorithm='RS256', headers={'kid': 'test-key', **(_headers or {})})
    return auth, token


@pytest.mark.parametrize('changes', [{}, {'iss': 'https://attacker.test'}, {'aud': 'other'},
    {'sub': ''}, {'scope': 'openid'}, {'exp': 1}, {'iat': 1, 'exp': 9999999999}, {'nbf': 9999999999}])
def test_account_token_signature_and_claims(oidc, changes):
    auth, token = oidc
    assert (auth.authenticate(token(**changes)) is not None) == (not changes)
    assert auth.authenticate('omn1_wrong') is None


def test_auth0_shaped_access_token_without_optional_nbf(oidc):
    auth, token = oidc
    assert auth.authenticate(token(_omit=('nbf',), aud=[auth.audience, auth.issuer+'userinfo']))
    for name in ('iss', 'sub', 'aud', 'iat', 'exp'):
        assert auth.authenticate(token(_omit=(name, 'nbf'))) is None


@pytest.mark.parametrize('changes', [{'nbf': None}, {'nbf': True}, {'nbf': '0'}, {'nbf': 0.0},
    {'iat': True}, {'exp': '9999999999'}, {'iat': 9999999999}, {'iat': 1, 'exp': 1},
    {'iat': 2, 'exp': 1}])
def test_optional_nbf_does_not_weaken_time_validation(oidc, changes):
    auth, token = oidc
    assert auth.authenticate(token(**changes)) is None


def test_account_rejects_algorithm_and_key_confusion(oidc):
    import jwt
    auth, _ = oidc
    assert auth.authenticate(jwt.encode({'sub': 'account-test'}, 'wrong-secret'*4, algorithm='HS256', headers={'kid':'test-key'})) is None
    assert auth.authenticate(jwt.encode({'sub': 'account-test'}, None, algorithm='none')) is None
    from cryptography.hazmat.primitives.asymmetric import rsa
    attacker = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    assert auth.authenticate(jwt.encode({'sub': 'account-test'}, attacker, algorithm='RS256', headers={'kid':'test-key'})) is None


@pytest.mark.parametrize('headers', [
    {'jku': 'https://attacker.invalid/jwks'},
    {'x5u': 'https://attacker.invalid/certificate'},
    {'crit': ['attacker-extension']},
    {'kid': 'unknown-key'},
])
def test_account_token_key_injection(oidc, headers):
    auth, token = oidc
    assert auth.authenticate(token()) is not None
    assert auth.authenticate(token(_headers=headers)) is None


def test_repeated_account_validation_retains_claim_checks(oidc):
    auth, token = oidc
    # Reuse one authenticator across accepted and rejected calls. This guards
    # against the shared-options claims bypass described by CVE-2026-103001.
    valid = token()
    for changes in ({'exp': 1}, {'aud': 'other'}, {'iss': 'https://attacker.invalid'},
                    {'scope': 'openid'}, {'nbf': 9999999999}):
        assert auth.authenticate(valid) is not None
        assert auth.authenticate(token(**changes)) is None
        assert auth.authenticate(valid) is not None


def test_unknown_or_ambiguous_account_keys_fail_closed(oidc):
    auth, token = oidc
    value = token()
    assert auth.authenticate(value)
    keys = json.loads(auth.jwks_path.read_text())
    keys['keys'].append(keys['keys'][0])
    auth.jwks_path.write_text(json.dumps(keys))
    assert auth.authenticate(value) is None
    auth.jwks_path.write_text('{"keys":[]}')
    assert auth.authenticate(value) is None


def test_authenticated_enrollment_http(self_service, oidc):
    from omneum.enrollment_api import EnrollmentHTTPApp
    from test_network_http import call
    _, service, connection = self_service
    auth, token = oidc
    app = EnrollmentHTTPApp(auth, service)
    headers = [(b'authorization', ('Bearer '+token()).encode()), (b'content-type', b'application/json')]
    request = enrollment()
    status, result = call(app, request.model_dump_json().encode(), '/v1/enrollment', headers=headers)
    assert status == 200 and CredentialAuthenticator(connection).authenticate(result['api_key'])
    assert call(app, request.model_dump_json().encode(), '/v1/enrollment', headers=headers)[0] == 409
    wrong = [(b'authorization', ('Bearer '+result['api_key']).encode()), headers[1]]
    assert call(app, b'{}', '/v1/enrollment', headers=wrong)[0] == 401
    assert call(app, b'{}', '/v1/enrollment', headers=headers+[headers[0]])[0] == 401
    assert call(app, b'{}', '/v1/enrollment', headers=headers+[(b'origin', b'https://attacker.test')])[0] == 415
    body = json.loads(request.model_dump_json())
    body['workspace_id'] = str(UUID(int=1))
    assert call(app, json.dumps(body).encode(), '/v1/enrollment', headers=headers)[0] == 400
    assert call(app, b'{"action":"enroll","action":"rotate"}', '/v1/enrollment', headers=headers)[0] == 400


def test_cli_enrollment_to_real_https_contribution(self_service, oidc, tmp_path, runtime, monkeypatch):
    """Real TLS, account signatures, SQL roles, CLI store, proofs and SDK writes.

    Only the external account provider is simulated. No production credentials,
    privileged installation, or caller endpoint override exists in product code.
    """
    import asyncio
    import socket
    import ssl
    import subprocess
    import threading
    import time
    import uvicorn
    from urllib.request import HTTPSHandler, build_opener
    from omneum import OmneumClient, onboarding
    from omneum.contributor import network_configuration
    from omneum.contribution import network as network_module, config as config_module
    from omneum.enrollment_api import EnrollmentHTTPApp
    from omneum.transport.network import NetworkHTTPApp
    from omneum.oprf import VOPRFServer
    from test_network_bootstrap import FixtureDaemonContext
    from test_evaluate_context import make_state
    db, service, connection = self_service
    account, account_token = oidc
    monkeypatch.setenv('OMNEUM_CONFIG_DIR', str(tmp_path / 'user-config'))
    monkeypatch.setenv('OMNEUM_NETWORK_CONTRIBUTION', 'true')
    monkeypatch.delenv('OMNEUM_API_KEY', raising=False)
    cert, key = tmp_path / 'tls.crt', tmp_path / 'tls.key'
    subprocess.run(['openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-days', '1',
        '-subj', '/CN=localhost', '-addext', 'subjectAltName=DNS:localhost',
        '-keyout', str(key), '-out', str(cert)], check=True, capture_output=True)
    listener = socket.socket()
    listener.bind(('127.0.0.1', 0))
    base = 'https://localhost:' + str(listener.getsockname()[1])
    context = ssl.create_default_context(cafile=str(cert))
    def trusted_opener(*handlers):
        return build_opener(*handlers, HTTPSHandler(context=context))
    for module in (onboarding, network_module, config_module):
        monkeypatch.setattr(module, 'build_opener', trusted_opener)
    auth = CredentialAuthenticator(connection)
    ingestion = IngestionService(authenticator=auth, connection_factory=connection, allowed_key_versions=frozenset({1}))
    with FixtureDaemonContext(b'\x02'+bytes(31)) as remote:
        state = make_state(server=VOPRFServer(remote.context))
        network = NetworkHTTPApp(network_state=state, local_public_key=runtime[0].voprf_public_key,
            authenticator=auth, ingestion=ingestion, rate_limiter=MinuteQuota(600, connection_factory=connection))
        enrollment_app = EnrollmentHTTPApp(account, service)
        async def app(scope, receive, send):
            if scope['type'] != 'http':
                return await network(scope, receive, send)
            if scope['path'] == '/device':
                return await NetworkHTTPApp._reply(send, 200, dict(verification_uri=base+'/verify',
                    user_code='ABCD-EFGH', device_code='disposable-device-secret', expires_in=300, interval=1))
            if scope['path'] == '/token':
                return await NetworkHTTPApp._reply(send, 200, dict(access_token=account_token(), token_type='Bearer'))
            return await (enrollment_app if scope['path'] == '/v1/enrollment' else network)(scope, receive, send)
        server = uvicorn.Server(uvicorn.Config(app, ssl_certfile=str(cert), ssl_keyfile=str(key),
            access_log=False, proxy_headers=False, log_level='error', timeout_graceful_shutdown=1))
        thread = threading.Thread(target=lambda: server.run(sockets=[listener]), daemon=True)
        thread.start()
        try:
            for _ in range(200):
                if server.started:
                    break
                time.sleep(.01)
            assert server.started
            monkeypatch.setattr(network_module, '_PRODUCTION_NETWORK', network_module._ProductionNetwork(
                base+'/v1/contributions', base+'/v1/voprf', state.deployment_id, 1, remote.public_key))
            monkeypatch.setattr(onboarding, '_PRODUCTION_ONBOARDING', onboarding.OnboardingPins(
                base+'/v1/enrollment', base+'/device', base+'/token', base+'/verify', 'test-client',
                'openid omneum:enroll', base+'/consent', 'consent-test-1', 'omneum-enrollment'))
            output = []
            onboarding.manage('enroll', output.append, lambda text: True)
            first = onboarding.stored_credential()
            client = OmneumClient(*runtime[:2], network_contribution=network_configuration())
            result = asyncio.run(client._evaluate_context(runtime[2], estimator=runtime[3]))
            assert result.claim_support
            assert db.execute('SELECT count(*) FROM control.ingestion_receipts').fetchone() == (1,)
            assert db.execute('SELECT count(*) FROM network.assertion_observations').fetchone() == (len(runtime[2]),)
            onboarding.manage('rotate', output.append, lambda text: True)
            assert auth.authenticate(first) is None
            assert auth.authenticate(onboarding.stored_credential())
            onboarding.manage('withdraw', output.append, lambda text: True)
            assert onboarding.stored_credential() is None
            assert first not in '\n'.join(output) and 'disposable-device-secret' not in '\n'.join(output)
            # Existing client retains the revoked key, yet local work/persistence
            # succeeds and only the optional contribution raises a recoverable error.
            from omneum.client import NetworkContributionError
            with pytest.raises(NetworkContributionError) as failed:
                asyncio.run(client._evaluate_context(runtime[2], estimator=runtime[3]))
            assert failed.value.evaluation.claim_support and failed.value.local_persistence_succeeded
            assert db.execute('SELECT count(*) FROM control.ingestion_receipts').fetchone() == (1,)
        finally:
            server.should_exit = True
            thread.join(timeout=10)
            listener.close()
            assert not thread.is_alive()


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


def test_revocation_scope(enrolled):
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
    db, connection, _, rows = enrolled
    principal = UUID(rows[0][0]['principal_id'])
    quotas = [MinuteQuota(5, connection_factory=connection) for _ in range(12)]
    with ThreadPoolExecutor(max_workers=12) as pool:
        admitted = list(pool.map(lambda quota: quota(principal, '/v1/voprf'), quotas))
    # Requests can legitimately straddle a UTC minute boundary. Verify atomic
    # admission against each persisted window rather than assuming one window.
    budgets = db.execute('SELECT requests FROM control.network_admission_budgets WHERE principal_id=%s',
                         (principal,)).fetchall()
    assert budgets and all(1 <= row[0] <= 5 for row in budgets)
    assert sum(admitted) == sum(row[0] for row in budgets)
    assert sum(admitted) >= 5


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
