"""CLI-only device authorization and private installation credential storage.

All remote destinations are release-owned. No account tokens are retained.
"""
from dataclasses import dataclass
import json
import os
from pathlib import Path
import stat
import time
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, ProxyHandler, build_opener
from uuid import UUID, uuid4

from platformdirs import user_config_path

from .contribution.config import HTTPSContributionTransport, _NoRedirect, _validate_credential
from .contribution.validation import _object
from .storage.filesystem import private_directory, require_safe_acl


@dataclass(frozen=True)
class OnboardingPins:
    enrollment_endpoint: str
    device_endpoint: str
    token_endpoint: str
    verification_uri: str
    client_id: str
    scope: str
    consent_url: str
    consent_version: str
    audience: str = ''

    def __post_init__(self):
        for endpoint in (self.enrollment_endpoint, self.device_endpoint, self.token_endpoint,
                         self.verification_uri, self.consent_url):
            HTTPSContributionTransport(endpoint, 'validation')
        if not self.client_id or 'omneum:enroll' not in self.scope.split():
            raise ValueError('invalid release account configuration')


# Provision and verify alongside _PRODUCTION_NETWORK. Never populate from env.
_PRODUCTION_ONBOARDING: OnboardingPins | None = None


def credential_directory():
    override = os.environ.get('OMNEUM_CONFIG_DIR')
    base = Path(override).expanduser() if override else user_config_path('Omneum')
    return base.absolute() / 'network'


def read_state():
    directory = credential_directory()
    # An absent store is normal; an unsafe store must not be followed.
    try:
        with private_directory(directory) as (path, fd):
            flags = os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0)
            file = os.open('credential.json' if fd is not None else path / 'credential.json', flags,
                           **({'dir_fd': fd} if fd is not None else {}))
            with os.fdopen(file, 'r') as stream:
                info = os.fstat(stream.fileno())
                if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                    raise ValueError('unsafe credential file')
                if os.name == 'posix':
                    if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o600:
                        raise ValueError('unsafe credential permissions')
                    require_safe_acl(stream.fileno())
                raw = stream.read(4097)
                if len(raw) > 4096:
                    raise ValueError('invalid credential store')
                result = json.loads(raw, object_pairs_hook=_object)
                if set(result) - {'installation_id', 'api_key', 'expires_at'}:
                    raise ValueError('invalid credential store')
                if str(UUID(result['installation_id'])) != result['installation_id']:
                    raise ValueError('invalid installation')
                if 'api_key' in result:
                    _validate_credential(result['api_key'])
                return result
    except FileNotFoundError:
        return None


def write_state(state):
    with private_directory(credential_directory(), create=True) as (path, fd):
        # Validate an existing store before replacing it, including ACLs/links.
        read_state()
        name = '.credential-' + uuid4().hex
        temporary = path / name
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0)
        file = os.open(name if fd is not None else temporary, flags, 0o600,
                       **({'dir_fd': fd} if fd is not None else {}))
        try:
            with os.fdopen(file, 'w') as stream:
                require_safe_acl(stream.fileno())
                if os.name == 'posix':
                    os.fchmod(stream.fileno(), 0o600)
                stream.write(json.dumps(state, separators=(',', ':')))
                stream.flush()
                os.fsync(stream.fileno())
            if fd is None:
                os.replace(temporary, path / 'credential.json')
            else:
                os.rename(name, 'credential.json', src_dir_fd=fd, dst_dir_fd=fd)
                os.fsync(fd)
        finally:
            try:
                os.unlink(name if fd is not None else temporary, **({'dir_fd': fd} if fd is not None else {}))
            except FileNotFoundError:
                pass


def stored_credential():
    state = read_state()
    return None if state is None else state.get('api_key')


def post(endpoint, body, *, token=None, form=False):
    # Pinned callers only. TLS verification uses the system CA store.
    headers = {'Content-Type': 'application/x-www-form-urlencoded' if form else 'application/json'}
    if token is not None:
        _validate_credential(token)
        headers['Authorization'] = 'Bearer ' + token
    data = urlencode(body).encode() if form else json.dumps(body).encode()
    request = Request(endpoint, data=data, headers=headers, method='POST')
    error_status = None
    try:
        response = build_opener(ProxyHandler({}), _NoRedirect()).open(request, timeout=10)
    except HTTPError as error:
        # OAuth device polling returns specific non-success JSON errors.
        if not form or error.code not in (400, 403, 429):
            error.close()
            raise RuntimeError('Network account request failed') from None
        response = error
        error_status = error.code
    with response:
        raw = response.read(16385)
        if len(raw) > 16384:
            raise ValueError('account response too large')
        result = json.loads(raw, object_pairs_hook=_object)
        if type(result) is not dict:
            raise ValueError('invalid account response')
        if error_status is not None:
            # Auth0 returns pending/denied as 403 and slow_down as 429;
            # RFC 8628 providers normally use 400. Error HTTP responses must
            # never be interpreted as successful token issuance.
            allowed = {
                400: {'authorization_pending', 'slow_down', 'access_denied',
                      'expired_token', 'invalid_request', 'invalid_client',
                      'invalid_grant', 'unauthorized_client',
                      'unsupported_grant_type', 'invalid_scope'},
                403: {'authorization_pending', 'access_denied', 'expired_token'},
                429: {'slow_down'},
            }
            code = result.get('error')
            if type(code) is not str or code not in allowed[error_status] or 'access_token' in result:
                raise ValueError('invalid account error response')
            # Provider descriptions/URLs are not needed by the polling state.
            return {'error': code}
        return result


def account_token(pins, echo):
    if not pins.audience:
        raise ValueError('release account audience required')
    start = post(pins.device_endpoint, {'client_id': pins.client_id, 'scope': pins.scope,
                                      'audience': pins.audience}, form=True)
    # Never display a provider-selected URL, JWT, device_code or complete URI.
    if start.get('verification_uri') != pins.verification_uri:
        raise ValueError('account destination mismatch')
    code = start.get('user_code')
    import re
    if type(code) is not str or not re.fullmatch(r'[A-Z0-9-]{4,32}', code):
        raise ValueError('invalid account code')
    if type(start.get('device_code')) is not str or not 1 <= len(start['device_code']) <= 1024:
        raise ValueError('invalid device response')
    expires, interval = start.get('expires_in'), start.get('interval', 5)
    if type(expires) is not int or not 1 <= expires <= 900 or type(interval) is not int or not 1 <= interval <= 30:
        raise ValueError('invalid device deadline')
    echo(f'Open {pins.verification_uri} and enter code {code}.')
    deadline = time.monotonic() + expires
    while time.monotonic() < deadline:
        time.sleep(min(interval, max(0, deadline-time.monotonic())))
        if time.monotonic() >= deadline:
            break
        result = post(pins.token_endpoint, {'client_id': pins.client_id,
            'grant_type': 'urn:ietf:params:oauth:grant-type:device_code',
            'device_code': start['device_code']}, form=True)
        if result.get('error') == 'authorization_pending':
            continue
        if result.get('error') == 'slow_down':
            interval += 5
            continue
        if result.get('error'):
            raise RuntimeError('account authorization declined or expired')
        token = result.get('access_token')
        if result.get('token_type', '').lower() != 'bearer':
            raise ValueError('invalid account token')
        _validate_credential(token)
        return token
    raise RuntimeError('account authorization expired')


def manage(action, echo, confirm):
    # Concurrent CLI rotations must not replace a fresh key with an older one.
    # No lock is held by the MCP adapter and no background service is required.
    with private_directory(credential_directory(), create=True) as (path, fd):
        if os.name != 'posix':
            raise RuntimeError('Network onboarding currently requires macOS or Linux.')
        import fcntl
        lock = os.open('.lifecycle.lock', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK,
                       0o600, dir_fd=fd)
        try:
            info = os.fstat(lock)
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                    or info.st_nlink != 1 or stat.S_IMODE(info.st_mode) != 0o600):
                raise ValueError('unsafe lifecycle lock')
            require_safe_acl(lock)
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return _manage(action, echo, confirm)
        finally:
            os.close(lock)


def _manage(action, echo, confirm):
    pins = _PRODUCTION_ONBOARDING
    from .contribution.network import _PRODUCTION_NETWORK
    if pins is None or _PRODUCTION_NETWORK is None:
        raise RuntimeError('Production Network onboarding is not provisioned in this release.')
    state = read_state()
    if state is None:
        if action != 'enroll':
            raise RuntimeError('Enroll this installation first.')
        state = {'installation_id': str(uuid4())}
        # Retain installation identity if a response or local write is uncertain.
        write_state(state)
    request = {'action': action, 'installation_id': state['installation_id']}
    if action == 'enroll':
        echo('Contribution shares pseudonymous structural reports for research_context_graph. '
             'Source/claim tokens and relationships are linkable. Raw assertions and history stay local.')
        echo(f'Consent terms ({pins.consent_version}): {pins.consent_url}')
        if not confirm('Grant explicit research_context_graph consent?'):
            raise RuntimeError('Consent declined; no enrollment request was sent.')
        request.update(consent=True, consent_version=pins.consent_version)
    token = account_token(pins, echo)
    result = post(pins.enrollment_endpoint, request, token=token)
    if result.get('installation_id') != state['installation_id'] or type(result.get('consent_active')) is not bool:
        raise ValueError('invalid enrollment response')
    if action in ('enroll', 'renew', 'rotate'):
        from .ingestion.credentials import _TOKEN
        from datetime import datetime, timezone
        credential = result.get('api_key')
        if type(credential) is not str or _TOKEN.fullmatch(credential) is None:
            raise ValueError('invalid contribution credential')
        expiry = datetime.fromisoformat(result['expires_at'])
        if expiry <= datetime.now(timezone.utc):
            raise ValueError('invalid contribution expiry')
        write_state({'installation_id': state['installation_id'], 'api_key': credential,
                     'expires_at': result['expires_at']})
        echo(f'Credential saved privately; expires {result["expires_at"]}. Restart your MCP connection.')
    elif action in ('withdraw', 'revoke'):
        write_state({'installation_id': state['installation_id']})
        echo('Contribution credentials revoked. Restart your MCP connection.')
    else:
        echo('Consent active.' if result['consent_active'] else 'Consent inactive.')
