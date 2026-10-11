"""Server-only single-VM render, migration, preflight and provider checks.

This module never changes contributor pins or provisions infrastructure.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import ssl
import stat
import subprocess
from urllib.parse import urlsplit
from urllib.request import Request, ProxyHandler, HTTPSHandler, build_opener

from .base64url import decode_unpadded
from .contribution.config import _NoRedirect
from .contribution.validation import _object
from .config import _validate_deployment_id
from .oprf import VOPRFClient

ROOT = Path('/etc/omneum-network')
RUNTIME = Path('/opt/omneum-network')
SOCKET = Path('/run/omneum-network/eval.sock')
KEY_DIR = Path('/var/lib/omneum-network-crypto')
ACCOUNTS = ('omneum-network-api', 'omneum-enrollment', 'omneum-network-crypto')
MIGRATIONS = (
    'production_001.sql', 'production_002_ingestion.sql',
    'production_003_dependency_evidence.sql', 'production_003_observation_subtypes.sql',
    'production_004_assertion_subtype_integrity.sql', 'production_004_retrieval_signal.sql',
    'production_005_contribution_reports.sql', 'production_006_credentials.sql',
    'production_007_self_service.sql',
)
FIELDS = frozenset(('domain', 'deployment_id', 'network_key_version', 'network_public_key',
    'local_public_key', 'database_host', 'database_port', 'database_name', 'database_ca',
    'ingestion_dsn_file', 'enrollment_dsn_file', 'tls_certificate', 'tls_private_key',
    'oidc_issuer', 'oidc_audience', 'oidc_jwks_uri', 'oidc_jwks_file',
    'oidc_device_endpoint', 'oidc_token_endpoint', 'oidc_verification_uri', 'oidc_client_id',
    'consent_url', 'consent_version'))
PATHS = ('database_ca', 'ingestion_dsn_file', 'enrollment_dsn_file',
         'tls_certificate', 'tls_private_key', 'oidc_jwks_file')


def require(condition, message):
    if not condition:
        raise ValueError(message)


def hostname(value):
    require(type(value) is str and len(value) <= 253 and
        re.fullmatch(r'[a-z0-9]+(?:[a-z0-9-]*[a-z0-9])?(?:\.[a-z0-9]+(?:[a-z0-9-]*[a-z0-9])?)+', value),
        'configure a canonical public DNS hostname')
    require(not any(x in value.split('.') for x in ('example', 'invalid', 'test', 'localhost', 'local')),
            'reserved/placeholder DNS names cannot be production configuration')
    import ipaddress
    try:
        ipaddress.ip_address(value)
    except ValueError:
        return
    raise ValueError('require DNS hostname, not IP address')


def https_url(value):
    require(type(value) is str and not any(c.isspace() for c in value), 'invalid HTTPS URL')
    u = urlsplit(value)
    require(u.scheme == 'https' and u.hostname and not u.username and not u.password
            and not u.query and not u.fragment and u.port in (None, 443), 'require canonical HTTPS port 443 URL')
    hostname(u.hostname)
    return u


def validate_config(c):
    require(type(c) is dict and set(c) == FIELDS, 'configuration fields must match production.json')
    for name in FIELDS - {'network_key_version', 'database_port'}:
        require(type(c[name]) is str and bool(c[name]) and '\x00' not in c[name]
                and '\n' not in c[name] and '\r' not in c[name], 'missing or malformed setting: ' + name)
    hostname(c['domain'])
    hostname(c['database_host'])
    _validate_deployment_id(c['deployment_id'])
    require(type(c['network_key_version']) is int and 1 <= c['network_key_version'] < 2**32,
            'configure positive Network key version')
    require(type(c['database_port']) is int and 1 <= c['database_port'] <= 65535, 'invalid database port')
    require(re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{0,62}', c['database_name']), 'invalid database name')
    require(re.fullmatch(r'[A-Za-z0-9._-]{1,128}', c['consent_version']), 'invalid consent version')
    require(re.fullmatch(r'[A-Za-z0-9_-]{1,256}', c['oidc_client_id']), 'invalid public client ID')
    keys = [decode_unpadded(c[n], expected_length=32) for n in ('network_public_key', 'local_public_key')]
    for key in keys:
        VOPRFClient(key)
    require(keys[0] != keys[1], 'Network and local public keys must differ')
    issuer = https_url(c['oidc_issuer'])
    require(c['oidc_issuer'].endswith('/'), 'OIDC issuer must retain provider trailing slash')
    for name in ('oidc_jwks_uri', 'oidc_device_endpoint', 'oidc_token_endpoint', 'oidc_verification_uri'):
        require(https_url(c[name]).hostname == issuer.hostname, 'OIDC destinations must share configured issuer host')
    https_url(c['consent_url'])
    for name in PATHS:
        require(re.fullmatch(r'/[A-Za-z0-9_./-]+', c[name]) and '..' not in Path(c[name]).parts
                and '//' not in c[name], 'invalid absolute path: ' + name)
    require(len({c[n] for n in PATHS}) == len(PATHS), 'configuration files must be distinct')
    return c


def safe_path(path, *, uid=0, mode=None, directory=False):
    """Check root-controlled ancestors; no symlinks, ACL grants or writable ancestors."""
    from .storage.filesystem import require_safe_acl
    path = Path(path)
    require(path.is_absolute() and '..' not in path.parts, 'unsafe filesystem path')
    for ancestor in reversed(path.parents):
        info = ancestor.lstat()
        require(stat.S_ISDIR(info.st_mode) and info.st_uid in (0, uid) and info.st_mode & 0o022 == 0,
                'unsafe ancestor permissions: ' + str(ancestor))
        fd = os.open(ancestor, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            require_safe_acl(fd, ancestor=True)
        finally:
            os.close(fd)
    info = path.lstat()
    require(info.st_uid == uid and (stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode)),
            'incorrect file type/owner: ' + str(path))
    require(directory or info.st_nlink == 1, 'hard-linked configuration file: ' + str(path))
    require(stat.S_IMODE(info.st_mode) == mode if mode is not None else info.st_mode & 0o022 == 0,
            'incorrect permissions: ' + str(path))
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        require_safe_acl(fd)
    finally:
        os.close(fd)


def private_read(path):
    safe_path(path, mode=0o600)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, 'rb') as stream:
        info = os.fstat(stream.fileno())
        require(stat.S_ISREG(info.st_mode) and info.st_uid == 0 and info.st_nlink == 1
                and stat.S_IMODE(info.st_mode) == 0o600, 'unsafe private file')
        raw = stream.read(65537)
    require(len(raw) <= 65536, 'configuration file too large')
    return raw


def load(path):
    return validate_config(json.loads(private_read(path), object_pairs_hook=_object))


def identities():
    import pwd
    users = [pwd.getpwnam(name) for name in ACCOUNTS]
    require(len({u.pw_uid for u in users}) == 3 and all(u.pw_uid > 0 for u in users), 'three distinct non-root service identities required')
    require(users[0].pw_gid == users[2].pw_gid != users[1].pw_gid, 'incorrect evaluator IPC group separation')
    require(all(u.pw_shell in ('/usr/sbin/nologin', '/sbin/nologin') for u in users), 'service login shells must be disabled')
    import grp
    allowed = {users[0].pw_name, users[2].pw_name}
    require(set(grp.getgrgid(users[0].pw_gid).gr_mem) <= allowed
        and {u.pw_name for u in pwd.getpwall() if u.pw_gid == users[0].pw_gid} == allowed,
        'reserved IPC group has unrelated members')
    return users


def public_environment(c, uid):
    return '\n'.join((
        'OMNEUM_NETWORK_BIND_HOST=127.0.0.1',
        'OMNEUM_NETWORK_DEPLOYMENT_ID=' + c['deployment_id'],
        'OMNEUM_NETWORK_KEY_VERSION=' + str(c['network_key_version']),
        'OMNEUM_NETWORK_PUBLIC_KEY=' + c['network_public_key'],
        'OMNEUM_LOCAL_PUBLIC_KEY=' + c['local_public_key'],
        'OMNEUM_DAEMON_SOCKET=' + str(SOCKET), 'OMNEUM_DAEMON_UID=' + str(uid),
        'OMNEUM_ACCOUNT_ISSUER=' + c['oidc_issuer'], 'OMNEUM_ACCOUNT_AUDIENCE=' + c['oidc_audience'],
        'OMNEUM_NETWORK_CONSENT_VERSION=' + c['consent_version'],
    )) + '\n'


def service_unit(c, kind, api_uid):
    crypto = kind == 'evaluator'
    enrollment = kind == 'enrollment'
    user = ACCOUNTS[2 if crypto else 1 if enrollment else 0]
    group = 'omneum-network-ipc' if not enrollment else user
    unit = '[Unit]\nDescription=Omneum Network ' + kind + '\nAfter=network-online.target\n'
    if kind == 'ingestion':
        unit += 'Requires=omneum-network-evaluator.service\nAfter=omneum-network-evaluator.service\n'
    unit += ('\n[Service]\nType=exec\nUser=' + user + '\nGroup=' + group +
        '\nUMask=0077\nNoNewPrivileges=yes\nCapabilityBoundingSet=\nAmbientCapabilities=\n'
        'ProtectSystem=strict\nProtectHome=yes\nPrivateTmp=yes\nPrivateDevices=yes\nPrivateIPC=yes\n'
        'ProtectProc=invisible\nProtectKernelTunables=yes\nProtectKernelModules=yes\n'
        'ProtectControlGroups=yes\nRestrictSUIDSGID=yes\nRestrictRealtime=yes\nLockPersonality=yes\n'
        'SystemCallArchitectures=native\nLimitCORE=0\nLimitNOFILE=256\nRestart=on-failure\n'
        'RestartSec=3\nTimeoutStopSec=35\nKillMode=control-group\nStandardOutput=journal\nStandardError=journal\n')
    if crypto:
        unit += ('PrivateNetwork=yes\nRestrictAddressFamilies=AF_UNIX\nTasksMax=4\nMemoryMax=256M\n'
            'RuntimeDirectory=omneum-network\nRuntimeDirectoryMode=0750\nReadOnlyPaths=' + str(KEY_DIR) +
            '\nReadWritePaths=/run/omneum-network\nExecStart=' + str(RUNTIME) +
            '/libexec/omneumd serve --key-dir ' + str(KEY_DIR) + ' --socket ' + str(SOCKET) +
            ' --client-uid ' + str(api_uid) + '\n')
    else:
        dsn = c['enrollment_dsn_file' if enrollment else 'ingestion_dsn_file']
        module = 'enrollment_api' if enrollment else 'network_api'
        unit += ('RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6\nTasksMax=64\nMemoryMax=512M\n'
            'EnvironmentFile=' + str(ROOT) + '/public.env\n'
            'Environment=PYTHONUNBUFFERED=1\n'
            'LoadCredential=database.dsn:' + dsn + '\nLoadCredential=database-ca.pem:' + c['database_ca'] +
            '\nLoadCredential=tls.crt:' + c['tls_certificate'] + '\nLoadCredential=tls.key:' + c['tls_private_key'] +
            '\nEnvironment=OMNEUM_' + ('ENROLLMENT' if enrollment else 'NETWORK') + '_DATABASE_DSN_FILE=%d/database.dsn\n'
            'Environment=PGSSLROOTCERT=%d/database-ca.pem\nEnvironment=OMNEUM_NETWORK_TLS_CERT=%d/tls.crt\n'
            'Environment=OMNEUM_NETWORK_TLS_KEY=%d/tls.key\n')
        if enrollment:
            unit += ('LoadCredential=account-jwks.json:' + c['oidc_jwks_file'] +
                     '\nEnvironment=OMNEUM_ACCOUNT_JWKS=%d/account-jwks.json\nInaccessiblePaths=' + str(KEY_DIR) + ' /run/omneum-network\n')
        else:
            unit += 'InaccessiblePaths=' + str(KEY_DIR) + '\n'
        unit += 'ExecStart=' + str(RUNTIME) + '/venv/bin/python -I -B -m omneum.' + module + '\n'
    return unit + '\n[Install]\nWantedBy=multi-user.target\n'


def nginx_config(c):
    # Root-owned configuration, canonical DNS/path values only, no forwarded auth.
    domain = c['domain']
    result = '''limit_req_zone $binary_remote_addr zone=omneum_ingest:1m rate=10r/s;
limit_req_zone $binary_remote_addr zone=omneum_enroll:1m rate=6r/m;
limit_conn_zone $binary_remote_addr zone=omneum_conn:1m;
server {
    listen 80;
    server_name DOMAIN;
    access_log off;
    location ^~ /.well-known/acme-challenge/ { root /var/lib/omneum-acme; }
    location / { return 404; }
}
server {
    listen 443 ssl;
    server_name DOMAIN;
    ssl_certificate CERT;
    ssl_certificate_key KEY;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_session_tickets off;
    access_log off;
    error_log /var/log/nginx/omneum-error.log crit;
    add_header Strict-Transport-Security "max-age=31536000" always;
    client_header_timeout 10s;
    client_body_timeout 10s;
    send_timeout 15s;
    keepalive_timeout 10s;
    client_header_buffer_size 1k;
    large_client_header_buffers 2 8k;
    limit_conn omneum_conn 4;
    limit_conn_status 429;
    limit_req_status 429;
    proxy_connect_timeout 3s;
    proxy_send_timeout 15s;
    proxy_read_timeout 20s;
    proxy_ssl_verify on;
    proxy_ssl_verify_depth 4;
    proxy_ssl_trusted_certificate /etc/ssl/certs/ca-certificates.crt;
    proxy_ssl_server_name on;
    proxy_ssl_name DOMAIN;
    proxy_set_header Host DOMAIN;
    proxy_set_header X-Forwarded-For "";
    proxy_set_header X-Forwarded-Proto "";
    proxy_set_header Forwarded "";
    proxy_set_header Connection "";
    proxy_http_version 1.1;
    proxy_request_buffering on;
    proxy_buffering on;
    location = /v1/voprf {
        limit_except POST { deny all; }
        limit_req zone=omneum_ingest burst=20 nodelay;
        client_max_body_size 4k;
        proxy_pass https://127.0.0.1:8443;
    }
    location = /v1/contributions {
        limit_except POST { deny all; }
        limit_req zone=omneum_ingest burst=20 nodelay;
        client_max_body_size 1m;
        proxy_pass https://127.0.0.1:8443;
    }
    location = /v1/enrollment {
        limit_except POST { deny all; }
        limit_req zone=omneum_enroll burst=10 nodelay;
        client_max_body_size 4k;
        proxy_pass https://127.0.0.1:8444;
    }
    location / { return 404; }
}
'''
    return result.replace('DOMAIN', domain).replace('CERT', c['tls_certificate']).replace('KEY', c['tls_private_key'])


def render(c, output):
    users = identities()
    output = Path(output)
    safe_path(output, mode=0o700, directory=True)
    files = {'public.env': public_environment(c, users[2].pw_uid), 'nginx.conf': nginx_config(c)}
    for kind in ('ingestion', 'enrollment', 'evaluator'):
        files['omneum-network-' + kind + '.service'] = service_unit(c, kind, users[0].pw_uid)
    for name, contents in files.items():
        # Exclusive creation prevents accidentally replacing an active deployment.
        fd = os.open(output / name, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'w') as stream:
            stream.write(contents)


def pins_match(c):
    from .network_release import validate_release
    from .contribution.network import _PRODUCTION_NETWORK as net
    from .onboarding import _PRODUCTION_ONBOARDING as account
    validate_release(require_provisioned=True)
    base = 'https://' + c['domain']
    require((net.ingestion_endpoint, net.voprf_endpoint, net.deployment_id, net.key_version, net.public_key) ==
        (base + '/v1/contributions', base + '/v1/voprf', c['deployment_id'], c['network_key_version'],
         decode_unpadded(c['network_public_key'], expected_length=32)), 'Network release pins mismatch')
    require((account.enrollment_endpoint, account.device_endpoint, account.token_endpoint,
             account.verification_uri, account.client_id, account.audience, account.scope,
             account.consent_url, account.consent_version) ==
        (base + '/v1/enrollment', c['oidc_device_endpoint'], c['oidc_token_endpoint'],
         c['oidc_verification_uri'], c['oidc_client_id'], c['oidc_audience'], 'omneum:enroll',
         c['consent_url'], c['consent_version']), 'account release pins mismatch')


def database_settings(c, filename, role=None):
    from psycopg.conninfo import conninfo_to_dict, make_conninfo
    raw = private_read(filename).decode().strip()
    settings = conninfo_to_dict(raw)
    require(set(settings) <= {'host', 'port', 'dbname', 'user', 'password', 'sslmode', 'connect_timeout'},
            'DSN must contain only host/port/dbname/user/password/sslmode/connect_timeout; CA supplied separately')
    require(settings.get('host') == c['database_host'] and settings.get('port') == str(c['database_port'])
            and settings.get('dbname') == c['database_name'] and settings.get('sslmode') == 'verify-full'
            and bool(settings.get('password')), 'DSN requires configured DB hostname, port, name, password and sslmode=verify-full')
    if role:
        require(settings.get('user') == role, 'dedicated database runtime role required: ' + role)
    else:
        require(settings.get('user') not in ('omneum_ingestion', 'omneum_enrollment'), 'migration/verification requires separate administrative identity')
    return make_conninfo(raw, sslrootcert=c['database_ca'], connect_timeout=5)


def check_database(c, filename, role):
    import psycopg
    from .network_api import validate_database_role
    with psycopg.connect(database_settings(c, filename, role), autocommit=True) as db:
        db.execute("SET statement_timeout='5s'")
        validate_database_role(db, expected_role=role)
        require(db.execute('SELECT ssl FROM pg_stat_ssl WHERE pid=pg_backend_pid()').fetchone() == (True,),
                'database session must negotiate TLS')
        require(db.execute("SELECT to_regclass('control.account_installations') IS NOT NULL").fetchone()[0],
                'apply production_007_self_service.sql')
        require(db.execute("SELECT to_regclass('control.enrollment_budgets') IS NOT NULL").fetchone()[0],
                'apply migration 007 enrollment budgets')
        require(db.execute("SELECT count(*) FROM pg_trigger WHERE tgname IN ('immutable_account_binding', 'immutable_account_installation') AND NOT tgisinternal").fetchone()[0] == 2,
                'migration 007 immutable bindings missing')
        require(not db.execute("SELECT has_schema_privilege(current_user,'public','CREATE') OR has_schema_privilege(current_user,'control','CREATE') OR has_schema_privilege(current_user,'network','CREATE')").fetchone()[0],
                'runtime schema CREATE privilege forbidden')
        if role == 'omneum_enrollment':
            require(not db.execute("""SELECT EXISTS(SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
                WHERE n.nspname='network' AND c.relkind IN ('r','v','m','p')
                AND has_table_privilege(current_user,c.oid,'SELECT,INSERT,UPDATE,DELETE,TRUNCATE,TRIGGER'))""").fetchone()[0],
                'enrollment must not access Network tables')
            for table in ('contributor_accounts', 'account_installations', 'ingestion_credentials', 'consent_grants', 'enrollment_budgets'):
                # Identifiers are a fixed server-owned list.
                db.execute('SELECT 1 FROM control.' + table + ' LIMIT 0')
            require(db.execute("SELECT has_column_privilege(current_user,'control.ingestion_credentials','revoked_at','UPDATE')").fetchone()[0], 'enrollment revocation grant missing')
        else:
            require(not db.execute("SELECT has_table_privilege(current_user,'control.ingestion_credentials','INSERT,UPDATE,DELETE') OR has_column_privilege(current_user,'control.ingestion_credentials','revoked_at','UPDATE')").fetchone()[0], 'ingestion must not issue or revoke credentials')
            for table in ('ingestion_credentials', 'ingestion_principals', 'consent_grants', 'network_admission_budgets'):
                db.execute('SELECT 1 FROM control.' + table + ' LIMIT 0')
            require(db.execute("SELECT has_table_privilege(current_user,'network.assertion_observations','INSERT') AND has_table_privilege(current_user,'network.evaluation_runs','INSERT')").fetchone()[0], 'ingestion report grants missing')


def validate_runtime_grants(db, role):
    allowed = ({('control', 'network_admission_budgets', 'requests'),
                ('network', 'sources', 'last_seen_at'), ('network', 'claims', 'last_seen_at')}
        if role == 'omneum_ingestion' else {
            ('control', 'ingestion_principals', 'enabled'), ('control', 'consent_grants', 'revoked_at'),
            ('control', 'ingestion_credentials', 'revoked_at'), ('control', 'account_installations', 'withdrawn_at'),
            ('control', 'enrollment_budgets', 'requests')})
    updates = set(db.execute("""SELECT n.nspname,c.relname,a.attname FROM pg_class c
        JOIN pg_namespace n ON n.oid=c.relnamespace JOIN pg_attribute a ON a.attrelid=c.oid
        WHERE n.nspname IN ('control','network','private','public') AND c.relkind IN ('r','p','v','m')
        AND a.attnum>0 AND NOT a.attisdropped AND has_column_privilege(current_user,c.oid,a.attnum,'UPDATE')""").fetchall())
    require(updates <= allowed, 'runtime has unauthorized UPDATE grants; remove binding/account reactivation privileges')
    require(not db.execute("""SELECT EXISTS(SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
        WHERE n.nspname IN ('control','network','private','public') AND c.relkind IN ('r','p','v','m')
        AND has_table_privilege(current_user,c.oid,'DELETE,TRUNCATE,REFERENCES,TRIGGER'))""").fetchone()[0],
        'runtime DELETE/TRUNCATE/REFERENCES/TRIGGER privileges forbidden')


def fetch_json(url):
    https_url(url)
    with build_opener(ProxyHandler({}), _NoRedirect(), HTTPSHandler(context=ssl.create_default_context())).open(
            Request(url, headers={'Accept': 'application/json'}), timeout=10) as response:
        raw = response.read(65537)
        require(response.status == 200 and len(raw) <= 65536, 'invalid provider response')
    return json.loads(raw, object_pairs_hook=_object)


def provider_settings(c):
    d = fetch_json(c['oidc_issuer'] + '.well-known/openid-configuration')
    require(d.get('issuer') == c['oidc_issuer'] and d.get('jwks_uri') == c['oidc_jwks_uri']
            and d.get('token_endpoint') == c['oidc_token_endpoint']
            and d.get('device_authorization_endpoint') == c['oidc_device_endpoint'], 'OIDC discovery mismatch')
    require('RS256' in d.get('id_token_signing_alg_values_supported', []), 'provider RS256 support missing')
    require('urn:ietf:params:oauth:grant-type:device_code' in d.get('grant_types_supported', []), 'provider device grant support missing')
    return fetch_json(c['oidc_jwks_uri'])


def validate_jwks(jwks):
    import jwt
    require(type(jwks) is dict and set(jwks) == {'keys'} and type(jwks['keys']) is list,
            'invalid public JWKS')
    ids = set()
    require(1 <= len(jwks['keys']) <= 32, 'invalid JWKS size')
    for key in jwks['keys']:
        require(type(key) is dict and not set(key) & {'d', 'p', 'q', 'dp', 'dq', 'qi', 'k'}, 'JWKS must contain public keys only')
        require(type(key.get('kid')) is str and key['kid'] not in ids, 'missing or duplicate JWKS key ID')
        ids.add(key['kid'])
        require(key.get('kty') == 'RSA' and key.get('alg', 'RS256') == 'RS256' and key.get('use', 'sig') == 'sig'
                and jwt.PyJWK.from_dict(key, algorithm='RS256').key.key_size >= 2048, 'require RSA >=2048 RS256 signing keys')


def refresh_jwks(c):
    keys = provider_settings(c)
    validate_jwks(keys)
    target = Path(c['oidc_jwks_file'])
    safe_path(target.parent, mode=0o700, directory=True)
    if target.exists() or target.is_symlink():
        safe_path(target, mode=0o600)
        if json.loads(private_read(target), object_pairs_hook=_object) == keys:
            return
    temporary = target.with_name(target.name + '.new')
    fd = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(fd, 'w') as stream:
            json.dump(keys, stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    # LoadCredential snapshots files at service start. Reload by restart, not
    # by bypassing root-owned credential mounts with a user-writable JWKS path.
    subprocess.run(['systemctl', 'try-restart', 'omneum-network-enrollment.service'], check=True)


def install_certificates(c):
    """Allow only certbot's root-controlled lineage symlinks, then copy privately."""
    archive = Path('/etc/letsencrypt/archive') / c['domain']
    lineage = Path('/etc/letsencrypt/live') / c['domain']
    paths = []
    for name in ('fullchain.pem', 'privkey.pem'):
        source = (lineage / name).resolve(strict=True)
        require(source.parent == archive, 'certificate must come from configured certbot archive')
        safe_path(source, mode=0o600 if name == 'privkey.pem' else None)
        paths.append(source)
    ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER).load_cert_chain(*map(str, paths))
    for source, field in zip(paths, ('tls_certificate', 'tls_private_key')):
        target = Path(c[field])
        safe_path(target.parent, mode=0o700, directory=True)
        if target.exists() or target.is_symlink():
            safe_path(target, mode=0o600)
        temporary = target.with_name(target.name + '.new')
        fd = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
        try:
            with os.fdopen(fd, 'wb') as stream:
                stream.write(source.read_bytes())
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)


def generate_dsns(c):
    import secrets
    from psycopg.conninfo import make_conninfo
    for field, role in (('ingestion_dsn_file', 'omneum_ingestion'), ('enrollment_dsn_file', 'omneum_enrollment')):
        target = Path(c[field])
        safe_path(target.parent, mode=0o700, directory=True)
        raw = make_conninfo(host=c['database_host'], port=c['database_port'], dbname=c['database_name'],
            user=role, password=secrets.token_urlsafe(32), sslmode='verify-full')
        fd = os.open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'w') as stream:
            stream.write(raw + '\n')
            stream.flush()
            os.fsync(stream.fileno())


def scram_verifier(password):
    """Send a salted SCRAM verifier, not a cleartext password, in ALTER ROLE."""
    import base64
    import hmac
    import secrets
    require(password.isascii(), 'runtime passwords must be ASCII; use generate-dsns')
    salt = secrets.token_bytes(16)
    salted = hashlib.pbkdf2_hmac('sha256', password.encode(), salt, 4096)
    stored = hashlib.sha256(hmac.digest(salted, b'Client Key', 'sha256')).digest()
    server = hmac.digest(salted, b'Server Key', 'sha256')
    encode = lambda value: base64.b64encode(value).decode()
    return 'SCRAM-SHA-256$4096:' + encode(salt) + '$' + encode(stored) + ':' + encode(server)


def migrate(c, admin_file, directory):
    import psycopg
    from psycopg import sql
    with psycopg.connect(database_settings(c, admin_file), autocommit=True) as db:
        require(db.execute('SELECT ssl FROM pg_stat_ssl WHERE pid=pg_backend_pid()').fetchone() == (True,), 'migration session must use TLS')
        require(db.execute('SELECT pg_try_advisory_lock(1936876917)').fetchone()[0], 'another migration runner is active')
        exists = db.execute("SELECT to_regclass('omneum_deploy.migrations') IS NOT NULL").fetchone()[0]
        if not exists:
            require(not db.execute("SELECT EXISTS(SELECT 1 FROM pg_namespace WHERE nspname IN ('control','network'))").fetchone()[0],
                    'existing database has no migration ledger; reconcile migrations administratively before using this runner')
            # Ledger uses its own administrative schema so migration 001 can
            # create control. Runtime identities receive no access.
        db.execute('CREATE SCHEMA IF NOT EXISTS omneum_deploy')
        db.execute('REVOKE ALL ON SCHEMA omneum_deploy FROM PUBLIC')
        db.execute('CREATE TABLE IF NOT EXISTS omneum_deploy.migrations(name text PRIMARY KEY, sha256 text NOT NULL)')
        for name in MIGRATIONS:
            path = Path(directory) / name
            safe_path(path)
            raw = path.read_bytes()
            checksum = hashlib.sha256(raw).hexdigest()
            previous = db.execute('SELECT sha256 FROM omneum_deploy.migrations WHERE name=%s', (name,)).fetchone()
            if previous:
                require(previous[0] == checksum, 'applied migration checksum mismatch: ' + name)
                continue
            text = re.sub(r'\A(?:\s|--[^\n]*(?:\n|\Z))*', '', raw.decode()).strip()
            require(text.startswith('BEGIN;') and text.endswith('COMMIT;'), 'migration must be transaction-wrapped: ' + name)
            with db.transaction():
                # Only checked, administrator-owned repository migration files.
                db.execute(text[len('BEGIN;'):-len('COMMIT;')], prepare=False)
                db.execute('INSERT INTO omneum_deploy.migrations VALUES(%s,%s)', (name, checksum))
        # Supplied passwords remain in private DSN files and bind parameters.
        for role, field in (('omneum_ingestion', 'ingestion_dsn_file'), ('omneum_enrollment', 'enrollment_dsn_file')):
            from psycopg.conninfo import conninfo_to_dict
            settings = conninfo_to_dict(database_settings(c, c[field], role))
            db.execute(sql.SQL('ALTER ROLE {} LOGIN PASSWORD {}').format(sql.Identifier(role), sql.Literal(scram_verifier(settings['password']))))
        db.execute('REVOKE CREATE ON SCHEMA public FROM PUBLIC')


def validate_runtime_tree():
    safe_path(RUNTIME, directory=True)
    for directory, children, files in os.walk(RUNTIME, followlinks=False):
        for name in children + files:
            path = Path(directory) / name
            if path.is_symlink():
                python_link = path.parent == RUNTIME / 'venv/bin' and re.fullmatch(r'python(?:3(?:\.[0-9]+)?)?', name)
                library_link = path == RUNTIME / 'venv/lib64' and os.readlink(path) == 'lib'
                require(python_link or library_link, 'unverified runtime symlink')
                safe_path(path.resolve(strict=True), directory=library_link)
            else:
                safe_path(path, directory=path.is_dir())


def service_checks(c):
    users = identities()
    safe_path(ROOT, mode=0o700, directory=True)
    safe_path(ROOT / 'public.env', mode=0o600)
    require((ROOT / 'public.env').read_text() == public_environment(c, users[2].pw_uid), 'installed public environment differs from configuration; render again')
    ingress = Path('/etc/nginx/conf.d/omneum-network.conf')
    safe_path(ingress, mode=0o600)
    require(ingress.read_text() == nginx_config(c), 'installed ingress differs from configuration')
    validate_runtime_tree()
    require(subprocess.run([str(RUNTIME / 'libexec/omneumd'), 'capabilities'], check=True,
        capture_output=True, text=True).stdout.strip() == 'protected-voprf-v1', 'fixture daemon cannot serve production')
    subprocess.run(['nginx', '-t'], capture_output=True, check=True)
    safe_path(KEY_DIR, uid=users[2].pw_uid, mode=0o700, directory=True)
    # Its parent is root-owned; private_directory in the evaluator rejects
    # symlink/ownership/permission changes again when actually opening the key.
    safe_path(KEY_DIR / 'voprf.key', uid=users[2].pw_uid, mode=0o600)
    require((KEY_DIR / 'voprf.key').stat().st_size == 32, 'evaluator scalar must be exactly 32 bytes')
    for index, kind in enumerate(('ingestion', 'enrollment', 'evaluator')):
        unit = 'omneum-network-' + kind + '.service'
        target = Path('/etc/systemd/system') / unit
        safe_path(target)
        require(target.read_text() == service_unit(c, kind, users[0].pw_uid), 'installed unit differs from generated configuration: ' + unit)
        result = subprocess.run(['systemctl', 'show', unit, '--property=MainPID,ActiveState,User,Group,DropInPaths'],
                                capture_output=True, text=True, check=True)
        values = dict(line.split('=', 1) for line in result.stdout.splitlines())
        require(values.get('ActiveState') == 'active' and not values.get('DropInPaths'), 'service inactive or has unverified overrides: ' + unit)
        require(values.get('User') == users[index].pw_name, 'unexpected service identity: ' + unit)
        require(values.get('Group') == ('omneum-network-ipc' if kind != 'enrollment' else ACCOUNTS[1]),
                'unexpected service group: ' + unit)
        pid = int(values['MainPID'])
        status = Path('/proc') / str(pid) / 'status'
        uid_line = next(line for line in status.read_text().splitlines() if line.startswith('Uid:'))
        require(set(map(int, uid_line.split()[1:])) == {users[index].pw_uid}, 'service process UID mismatch: ' + unit)
        gid_line = next(line for line in status.read_text().splitlines() if line.startswith('Gid:'))
        require(set(map(int, gid_line.split()[1:])) == {users[index].pw_gid}, 'service process GID mismatch: ' + unit)
        if kind == 'evaluator':
            net = Path('/proc') / str(pid) / 'ns/net'
            require(net.stat().st_ino != Path('/proc/self/ns/net').stat().st_ino,
                    'evaluator must use its private network namespace')
            for family in ('tcp', 'tcp6'):
                entries = Path('/proc') / str(pid) / 'net' / family
                require(all(line.split()[3] != '0A' for line in entries.read_text().splitlines()[1:]),
                        'evaluator has an unintended TCP listener')
    safe_path(SOCKET.parent, uid=users[2].pw_uid, mode=0o750, directory=True)
    info = SOCKET.lstat()
    require(stat.S_ISSOCK(info.st_mode) and info.st_uid == users[2].pw_uid and info.st_gid == users[0].pw_gid
            and stat.S_IMODE(info.st_mode) == 0o660, 'incorrect evaluator socket permissions')
    result = subprocess.run(['runuser', '-u', ACCOUNTS[0], '--', str(RUNTIME / 'venv/bin/python'), '-I', '-B',
        '-m', 'omneum.network_deploy', 'evaluator-check', '--uid', str(users[2].pw_uid), '--public-key', c['network_public_key']],
        capture_output=True, check=False)
    require(result.returncode == 0, 'evaluator peer identity/public-key/proof check failed')


def preflight(c, *, online=True, services=True):
    pins_match(c)
    for name in PATHS:
        safe_path(c[name], mode=0o600 if name not in ('database_ca', 'tls_certificate') else None)
    validate_jwks(json.loads(private_read(c['oidc_jwks_file']), object_pairs_hook=_object))
    # Validates private-key/certificate pairing without exposing either.
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(c['tls_certificate'], c['tls_private_key'])
    ssl.create_default_context(cafile=c['database_ca'])
    check_database(c, c['ingestion_dsn_file'], 'omneum_ingestion')
    check_database(c, c['enrollment_dsn_file'], 'omneum_enrollment')
    if online:
        remote = provider_settings(c)
        validate_jwks(remote)
        local = json.loads(private_read(c['oidc_jwks_file']))
        require(local == remote, 'mounted JWKS differs from provider; run refresh-jwks')
        opener = build_opener(ProxyHandler({}), _NoRedirect(), HTTPSHandler(context=ssl.create_default_context()))
        from urllib.error import HTTPError
        for route in ('voprf', 'contributions', 'enrollment'):
            try:
                with opener.open(Request('https://' + c['domain'] + '/v1/' + route, data=b'{}',
                    headers={'Content-Type': 'application/json'}), timeout=10):
                    raise ValueError('unauthenticated route unexpectedly accepted')
            except HTTPError as error:
                require(error.code == 401, 'public HTTPS route must reject unauthenticated requests: ' + route)
                error.close()
    if services:
        service_checks(c)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('render', 'migrate', 'preflight', 'generate-dsns', 'refresh-jwks', 'install-certificates', 'provider-token', 'evaluator-check'))
    parser.add_argument('--config', default=str(ROOT / 'production.json'))
    parser.add_argument('--output')
    parser.add_argument('--admin-dsn-file')
    parser.add_argument('--migrations')
    parser.add_argument('--uid', type=int)
    parser.add_argument('--public-key')
    args = parser.parse_args()
    try:
        if args.command == 'evaluator-check':
            from .daemon import DaemonServerContext
            require(args.uid is not None and args.public_key, 'evaluator arguments required')
            key = decode_unpadded(args.public_key, expected_length=32)
            context = DaemonServerContext(SOCKET, args.uid, key)
            try:
                client = VOPRFClient(key)
                blind = client.blind(b'OMNEUM-DEPLOYMENT-PREFLIGHT-V1')
                evaluation = context.evaluate(blind.blinded_element)
                client.finalize(input_data=b'OMNEUM-DEPLOYMENT-PREFLIGHT-V1', client_state=blind.client_state, evaluation=evaluation)
            finally:
                context.close()
        else:
            require(os.geteuid() == 0, 'server deployment commands require root')
            c = load(args.config)
            if args.command == 'render':
                require(args.output, 'render requires private --output directory')
                render(c, args.output)
            elif args.command == 'migrate':
                require(args.admin_dsn_file and args.migrations, 'migrate requires --admin-dsn-file and --migrations')
                migrate(c, args.admin_dsn_file, args.migrations)
            elif args.command == 'refresh-jwks':
                refresh_jwks(c)
            elif args.command == 'install-certificates':
                install_certificates(c)
            elif args.command == 'generate-dsns':
                generate_dsns(c)
            elif args.command == 'provider-token':
                from .enrollment import OIDCAuthenticator
                from .onboarding import account_token, OnboardingPins
                pins_match(c)
                pins = OnboardingPins('https://' + c['domain'] + '/v1/enrollment', c['oidc_device_endpoint'],
                    c['oidc_token_endpoint'], c['oidc_verification_uri'], c['oidc_client_id'],
                    'omneum:enroll', c['consent_url'], c['consent_version'], c['oidc_audience'])
                token = account_token(pins, print)
                require(OIDCAuthenticator(issuer=c['oidc_issuer'], audience=c['oidc_audience'],
                    jwks_path=c['oidc_jwks_file']).authenticate(token) is not None, 'provider-issued token failed enrollment validation')
            else:
                preflight(c)
    except Exception as error:
        # Never print arbitrary TLS/libpq/HTTP/provider exception messages.
        message = str(error) if type(error) is ValueError else 'dependency check failed; check configuration, permissions, connectivity and service journal'
        parser.exit(1, 'FAIL: ' + message + '\n')
    print('PASS: ' + args.command + '; live acceptance is still required' if args.command != 'provider-token'
          else 'PASS: real device-provider token signature and claims verified; token not retained')


if __name__ == '__main__':
    main()
