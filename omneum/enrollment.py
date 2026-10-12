"""Account-authenticated control plane, separate from ingestion privileges.

Contribution bearer tokens cannot enroll, renew or choose workspace bindings.
The account provider must authorize the configured audience and enrollment scope.
"""
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
import time
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field
from typing import Literal

from .ingestion.credentials import generate
from .network_operator import lock_installation
from .contribution.validation import _object


class EnrollmentRequest(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    action: Literal['enroll', 'renew', 'rotate', 'revoke', 'withdraw', 'status']
    installation_id: str
    consent: bool = False
    consent_version: str | None = None
    expires_days: int = Field(default=90, ge=1, le=365)

    def installation(self):
        value = UUID(self.installation_id)
        if str(value) != self.installation_id or value.int in (0, 2**128-1):
            raise ValueError('noncanonical installation')
        return value


class OIDCAuthenticator:
    """Offline signature validation using operator-mounted public JWKS.

    Never follow JWT jku/x5u URLs or choose issuer/audience from claims. Only
    RS256 access tokens bearing enrollment scope are accepted. Keys reload on
    each request so provider key rotation does not require a restart.
    """
    def __init__(self, *, issuer, audience, jwks_path, scope='omneum:enroll'):
        from ._crypto import require_crypto
        require_crypto()
        from .contribution.config import HTTPSContributionTransport
        HTTPSContributionTransport(issuer, 'validation')
        if not audience or not scope:
            raise ValueError('account audience and scope required')
        self.issuer, self.audience, self.jwks_path, self.scope = issuer, audience, jwks_path, scope

    def authenticate(self, token):
        try:
            import jwt
            from pathlib import Path
            if type(token) is not str or not 1 <= len(token) <= 8192:
                return None
            header = jwt.get_unverified_header(token)
            if header.get('alg') != 'RS256' or not isinstance(header.get('kid'), str):
                return None
            if header.get('crit') or 'jku' in header or 'x5u' in header:
                return None
            raw = Path(self.jwks_path).read_bytes()
            if len(raw) > 65536:
                return None
            keys = json.loads(raw, object_pairs_hook=_object)['keys']
            selected = [k for k in keys if k.get('kid') == header['kid']
                        and k.get('kty') == 'RSA' and k.get('use', 'sig') == 'sig'
                        and k.get('alg', 'RS256') == 'RS256']
            if len(selected) != 1:
                return None
            key = jwt.PyJWK.from_dict(selected[0], algorithm='RS256').key
            if key.key_size < 2048:
                return None
            claims = jwt.decode(token, key, algorithms=['RS256'], issuer=self.issuer,
                audience=self.audience, options={'require': ['iss', 'sub', 'aud', 'exp', 'iat']})
            subject = claims['sub']
            if type(subject) is not str or not 1 <= len(subject) <= 256:
                return None
            if type(claims.get('scope')) is not str or self.scope not in claims['scope'].split():
                return None
            # Auth0 access tokens normally omit optional RFC 7519 nbf. PyJWT
            # verifies it when supplied; never synthesize or ignore a future nbf.
            if any(type(claims[name]) is not int for name in ('exp', 'iat')):
                return None
            if 'nbf' in claims and type(claims['nbf']) is not int:
                return None
            # Bound account-token lifetime, independently of contribution keys.
            if not 0 < claims['exp'] - claims['iat'] <= 3600 or claims['iat'] > time.time():
                return None
            return sha256(b'OMNEUM-ACCOUNT-V1\0' + self.issuer.encode() + b'\0' + subject.encode()).digest()
        except Exception:
            return None


@dataclass
class EnrollmentService:
    connection_factory: object
    consent_version: str

    def handle(self, identity, request):
        if type(identity) is not bytes or len(identity) != 32:
            raise PermissionError('account authorization required')
        installation = request.installation()
        # Budget transaction is committed even for rejected requests.
        with self.connection_factory() as db:
            db.execute("SET statement_timeout='10s'")
            admitted = db.execute('''INSERT INTO control.enrollment_budgets VALUES
                (%s,date_trunc('minute',clock_timestamp()),1)
                ON CONFLICT(identity_sha256,window_start) DO UPDATE SET
                requests=control.enrollment_budgets.requests+1
                WHERE control.enrollment_budgets.requests<10 RETURNING requests''', (identity,)).fetchone()
        if admitted is None:
            raise OverflowError('enrollment budget exhausted')
        with self.connection_factory() as db, db.transaction():
            db.execute("SET LOCAL statement_timeout='10s'")
            db.execute("SET LOCAL lock_timeout='5s'")
            # Account lock serializes duplicate enrollments and installation caps.
            db.execute('SELECT pg_advisory_xact_lock(%s)', (int.from_bytes(identity[:8], 'big', signed=True),))
            lock_installation(db, installation)
            account = db.execute('SELECT workspace_id,enabled FROM control.contributor_accounts WHERE identity_sha256=%s', (identity,)).fetchone()
            if account is not None and not account[1]:
                raise PermissionError('account disabled')
            binding = db.execute('''SELECT a.identity_sha256,p.principal_id,p.enabled,a.withdrawn_at
                FROM control.account_installations a JOIN control.ingestion_principals p
                ON p.installation_id=a.installation_id WHERE a.installation_id=%s''', (installation,)).fetchone()
            if binding is not None and bytes(binding[0]) != identity:
                raise PermissionError('installation unauthorized')
            if request.action == 'enroll':
                if request.consent is not True or request.consent_version != self.consent_version:
                    raise PermissionError('explicit current consent required')
                if binding is not None:
                    raise FileExistsError('already enrolled; use account-authenticated renewal')
                if db.execute('SELECT 1 FROM control.installations WHERE id=%s', (installation,)).fetchone():
                    raise PermissionError('installation unauthorized')
                if db.execute('SELECT count(*) FROM control.account_installations WHERE identity_sha256=%s', (identity,)).fetchone()[0] >= 10:
                    raise PermissionError('installation limit reached')
                if account is None:
                    organization, workspace = uuid4(), uuid4()
                    db.execute('INSERT INTO control.organizations(id) VALUES(%s)', (organization,))
                    db.execute('INSERT INTO control.workspaces(id,organization_id) VALUES(%s,%s)', (workspace, organization))
                    db.execute('INSERT INTO control.contributor_accounts VALUES(%s,%s,true)', (identity, workspace))
                else:
                    workspace = account[0]
                principal = uuid4()
                db.execute('INSERT INTO control.installations(id) VALUES(%s)', (installation,))
                db.execute('INSERT INTO control.ingestion_principals VALUES(%s,%s,%s,true)', (principal, installation, workspace))
                db.execute('INSERT INTO control.account_installations(installation_id,identity_sha256) VALUES(%s,%s)', (installation, identity))
                db.execute("INSERT INTO control.consent_grants(installation_id,scope,consent_version) VALUES(%s,'research_context_graph',%s)", (installation, self.consent_version))
            else:
                if binding is None:
                    raise PermissionError('installation unauthorized')
                principal = binding[1]
            if request.action == 'withdraw':
                db.execute('UPDATE control.consent_grants SET revoked_at=COALESCE(revoked_at,clock_timestamp()) WHERE installation_id=%s', (installation,))
                db.execute('UPDATE control.ingestion_principals SET enabled=false WHERE principal_id=%s', (principal,))
                db.execute('UPDATE control.account_installations SET withdrawn_at=COALESCE(withdrawn_at,clock_timestamp()) WHERE installation_id=%s', (installation,))
            active = db.execute("SELECT EXISTS(SELECT 1 FROM control.consent_grants WHERE installation_id=%s AND scope='research_context_graph' AND revoked_at IS NULL)", (installation,)).fetchone()[0]
            if request.action in ('renew', 'rotate') and (not binding[2] or binding[3] is not None or not active):
                raise PermissionError('enabled installation and active consent required')
            if request.action in ('enroll', 'renew', 'rotate', 'revoke', 'withdraw'):
                # A new key invalidates all old installation keys atomically.
                db.execute('UPDATE control.ingestion_credentials SET revoked_at=COALESCE(revoked_at,clock_timestamp()) WHERE principal_id=%s', (principal,))
            result = dict(installation_id=str(installation), consent_active=bool(active))
            if request.action in ('enroll', 'renew', 'rotate'):
                credential = generate(datetime.now(timezone.utc) + timedelta(days=request.expires_days))
                db.execute('INSERT INTO control.ingestion_credentials(id,principal_id,token_sha256,expires_at) VALUES(%s,%s,%s,%s)',
                    (credential.id, principal, credential.token_sha256, credential.expires_at))
                result.update(api_key=credential.token, expires_at=credential.expires_at.isoformat())
            return result
