#!/usr/bin/env python3
"""Offline activation controller. prepare is local-only; check is read-only.

apply requires root and explicit authorization. Never provisions keys, migrates,
generates DSNs, changes DB passwords, or publishes. Missing prerequisites block.
"""
import argparse
import ast
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
import time
from contextlib import contextmanager

SOURCE_ROOT = Path(__file__).resolve().parents[3]
BUNDLE = SOURCE_ROOT / 'activation'
# A root invocation must never import caller-writable prospective modules.
# Artifact authenticity is additionally established by the operator's bundle
# SHA-256 and complete FILES.sha256 manifest before invoking this script.
if __name__ == '__main__' and os.geteuid() == 0:
    for path in [SOURCE_ROOT, *SOURCE_ROOT.parents,
                 *sorted((SOURCE_ROOT / 'omneum').rglob('*'))]:
        info = path.lstat()
        if (info.st_uid != 0 or info.st_mode & 0o022 or
                not (stat.S_ISREG(info.st_mode) or stat.S_ISDIR(info.st_mode))):
            raise SystemExit('BLOCKED: prospective source tree is not root-controlled')
sys.path.insert(0, str(SOURCE_ROOT))
from omneum import network_deploy as d

PYTHON = '/opt/omneum-network/venv/bin/python'
SITE = Path('/opt/omneum-network/venv/lib/python3.12/site-packages')
STATE = Path('/root/omneum-network-activation-state')
NGINX = Path('/etc/nginx')
SYSTEMD = Path('/etc/systemd/system')
MODULE_DIGEST = 'c1ba6b282d40cd152fe93550510aa281de555d97474bda1f272520137145b949'
WHEEL_DIGEST = '7a3742debf6b879e912dbb9819ceec1594be812452b78c5f2e2dfc56564954f8'
UNITS = ['omneum-network-' + kind + '.service' for kind in ('evaluator', 'ingestion', 'enrollment')]

def run(*args):
    # Suppress arbitrary libpq/provider/pip diagnostics in the shared output.
    return subprocess.run(args, check=True, capture_output=True, text=True,
                          timeout=120).stdout

def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def verify_bundle():
    for name, expected in [('network_deploy.py', MODULE_DIGEST),
                           ('pyjwt-2.15.0-py3-none-any.whl', WHEEL_DIGEST)]:
        d.require(digest(BUNDLE / name) == expected, 'artifact checksum mismatch: ' + name)
    d.require(digest(SOURCE_ROOT / 'omneum/network_deploy.py') == MODULE_DIGEST,
              'prospective deployment module differs from verified artifact')

def config(path):
    from omneum.contribution.validation import _object
    c = json.loads(Path(path).read_text(), object_pairs_hook=_object)
    missing = sorted(k for k in d.FIELDS if c.get(k) is None or c.get(k) == '')
    d.require(not missing, 'missing public settings/file paths: ' + ', '.join(missing))
    d.validate_config(c)
    # Certificate/JWKS helpers replace these files. Confine their write targets
    # so a malformed operator configuration cannot overwrite scalar/runtime/DSNs.
    for field in ('tls_certificate', 'tls_private_key', 'oidc_jwks_file'):
        d.require(Path(c[field]).parent == d.ROOT / 'secrets',
                  'mutable credential copy must remain under secrets: ' + field)
    return c

def pin_sources(c):
    base = 'https://' + c['domain']
    network = ('_PRODUCTION_NETWORK: _ProductionNetwork | None = _ProductionNetwork(\n'
               f'    ingestion_endpoint={base + "/v1/contributions"!r},\n'
               f'    voprf_endpoint={base + "/v1/voprf"!r},\n'
               f'    deployment_id={c["deployment_id"]!r}, key_version={c["network_key_version"]!r},\n'
               f'    public_key=decode_unpadded({c["network_public_key"]!r}, expected_length=32),\n)')
    account = ('_PRODUCTION_ONBOARDING: OnboardingPins | None = OnboardingPins(\n' +
               ',\n'.join('    ' + name + '=' + repr(value) for name, value in {
                   'enrollment_endpoint': base + '/v1/enrollment',
                   'device_endpoint': c['oidc_device_endpoint'], 'token_endpoint': c['oidc_token_endpoint'],
                   'verification_uri': c['oidc_verification_uri'], 'client_id': c['oidc_client_id'],
                   'scope': 'omneum:enroll', 'consent_url': c['consent_url'],
                   'consent_version': c['consent_version'], 'audience': c['oidc_audience']}.items()) + '\n)')
    result = {}
    for name, marker, replacement in [
        ('contribution/network.py', '_PRODUCTION_NETWORK: _ProductionNetwork | None = None', network),
        ('onboarding.py', '_PRODUCTION_ONBOARDING: OnboardingPins | None = None', account)]:
        source = (SOURCE_ROOT / 'omneum' / name).read_text()
        d.require(source.count(marker) == 1, 'pin source baseline differs: ' + name)
        result[name] = source.replace(marker, replacement)
        ast.parse(result[name])
    return result

def prepare(c, output):
    # Writes only the explicitly selected local output directory, never source.
    output = Path(output).absolute()
    d.require(not output.is_symlink(), 'symlink preparation directory')
    d.require(not (output == SOURCE_ROOT / 'omneum' or
                   SOURCE_ROOT / 'omneum' in output.parents), 'preparation would overwrite source')
    output.mkdir(mode=0o700, parents=True, exist_ok=True)
    info = output.lstat()
    d.require(info.st_uid == os.geteuid() and stat.S_IMODE(info.st_mode) == 0o700,
              'preparation directory must be private and owned by caller')
    outputs = {name: source.encode() for name, source in pin_sources(c).items()}
    outputs['production.json'] = (json.dumps(c, indent=2) + '\n').encode()
    # Reject all conflicting/symlink files before writing any output.
    for name, value in outputs.items():
        target = output / name
        d.require(not target.parent.is_symlink() and not target.is_symlink(), 'symlink preparation target')
        if target.exists():
            info = target.lstat()
            d.require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and
                      info.st_uid == os.geteuid() and stat.S_IMODE(info.st_mode) == 0o600 and
                      target.read_bytes() == value, 'preparation output differs: ' + name)
    for name, value in outputs.items():
        target = output / name
        target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        info = target.parent.lstat()
        d.require(stat.S_ISDIR(info.st_mode) and info.st_uid == os.geteuid() and
                  stat.S_IMODE(info.st_mode) == 0o700, 'unsafe preparation parent')
        if not target.exists():
            fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            with os.fdopen(fd, 'wb') as stream:
                stream.write(value)
                stream.flush()
                os.fsync(stream.fileno())
    print('PASS prepared literal public pins; no release or production files changed')

def check(c, admin):
    import psycopg
    d.identities()
    d.validate_runtime_tree()
    actual_site = run(PYTHON, '-I', '-B', '-c',
                      'import sysconfig; print(sysconfig.get_path("purelib"))').strip()
    d.require(Path(actual_site) == SITE, 'runtime Python layout differs from approved target')
    d.require(run('/opt/omneum-network/libexec/omneumd', 'capabilities').strip() ==
              'protected-voprf-v1', 'unprotected evaluator')
    users = d.identities()
    d.safe_path(d.KEY_DIR, uid=users[2].pw_uid, mode=0o700, directory=True)
    d.safe_path(d.KEY_DIR / 'voprf.key', uid=users[2].pw_uid, mode=0o600)
    d.require((d.KEY_DIR / 'voprf.key').stat().st_size == 32, 'scalar missing/partial')
    for field in ('database_ca', 'ingestion_dsn_file', 'enrollment_dsn_file'):
        d.safe_path(c[field], mode=0o600 if field.endswith('dsn_file') else None)
    with psycopg.connect(d.database_settings(c, admin), autocommit=True) as db:
        with db.transaction():
            db.execute('SET TRANSACTION READ ONLY')
            db.execute("SET LOCAL statement_timeout='5s'")
            d.require(db.execute('SELECT ssl FROM pg_stat_ssl WHERE pid=pg_backend_pid()').fetchone() == (True,), 'DB TLS required')
            d.require(db.execute("SELECT to_regclass('omneum_deploy.migrations') IS NOT NULL").fetchone()[0], 'migration ledger missing; operator reconciliation required')
            rows = dict(db.execute('SELECT name,sha256 FROM omneum_deploy.migrations').fetchall())
            d.require(set(rows) == set(d.MIGRATIONS), 'unexpected/incomplete migration ledger')
            for name in d.MIGRATIONS:
                d.require(rows.get(name) == digest(SOURCE_ROOT / 'migrations' / name), 'missing/mismatched migration: ' + name)
    for field, role in [('ingestion_dsn_file', 'omneum_ingestion'), ('enrollment_dsn_file', 'omneum_enrollment')]:
        d.check_database(c, c[field], role)
    d.validate_jwks(d.provider_settings(c))
    site = NGINX / 'sites-available/omneum-network'
    d.safe_path(site, mode=0o644)
    enabled = NGINX / 'sites-enabled/omneum-network'
    d.require(enabled.is_symlink() and enabled.lstat().st_uid == 0 and enabled.resolve() == site,
              'unexpected enabled site')
    d.require(not (NGINX / 'conf.d/omneum-network.conf').exists(), 'overlapping standalone ingress')
    options = d.CERTBOT_OPTIONS
    d.safe_path(options)
    import re, ssl
    protocols = re.findall(r'^\s*ssl_protocols\s+([^;]+);', options.read_text(), re.M)
    d.require(len(protocols) == 1 and set(protocols[0].split()) == {'TLSv1.2', 'TLSv1.3'}, 'TLS protocol floor')
    lineage = Path('/etc/letsencrypt/live') / c['domain']
    ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER).load_cert_chain(str(lineage / 'fullchain.pem'), str(lineage / 'privkey.pem'))
    for field in ('tls_certificate', 'tls_private_key', 'oidc_jwks_file'):
        d.safe_path(Path(c[field]).parent, mode=0o700, directory=True)
    run('nginx', '-t')
    print('PASS read-only prerequisites; no DB or service mutation')

def install(source, target, mode):
    target = Path(target)
    d.safe_path(target.parent, directory=True)
    if target.exists() or target.is_symlink(): d.safe_path(target)
    if target.exists() and target.read_bytes() == Path(source).read_bytes():
        d.safe_path(target, mode=mode)
        return
    fd, name = tempfile.mkstemp(prefix='.omneum-activation-', dir=target.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(Path(source).read_bytes())
            os.fchmod(stream.fileno(), mode)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, target)
        sync_directory(target.parent)
    finally:
        Path(name).unlink(missing_ok=True)

def sync_directory(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try: os.fsync(fd)
    finally: os.close(fd)

@contextmanager
def mutation_lock():
    import fcntl
    path = STATE.parent / '.omneum-network-activation.lock'
    d.safe_path(path.parent, directory=True)
    if path.exists() or path.is_symlink(): d.safe_path(path, mode=0o600)
    fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        info = os.fstat(fd)
        d.require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and
                  info.st_uid == 0 and stat.S_IMODE(info.st_mode) == 0o600,
                  'unsafe activation lock')
        try: fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError: raise ValueError('another activation/rollback is running') from None
        yield
    finally: os.close(fd)

def rollback():
    d.safe_path(STATE, mode=0o700, directory=True)
    record = json.loads(d.private_read(STATE / 'rollback.json'))
    if (STATE / 'rolled-back').exists():
        print('PASS already rolled back; no changes')
        return
    for entry in record['files']:
        if entry['backup']:
            path = STATE / entry['backup']
            d.safe_path(path, mode=0o600)
            d.require(digest(path) == entry['sha256'], 'rollback backup checksum mismatch')
    if (STATE / 'pyjwt-snapshot-complete').exists():
        expected = json.loads(d.private_read(STATE / 'pyjwt-before.json'))
        actual = {str(path.relative_to(STATE / 'pyjwt-before'))
                  for path in (STATE / 'pyjwt-before').rglob('*') if path.is_file()}
        d.require(actual == set(expected), 'dependency backup inventory mismatch')
        for name, checksum in expected.items():
            path = STATE / 'pyjwt-before' / name
            d.safe_path(path)
            d.require(digest(path) == checksum, 'dependency backup checksum mismatch')
    # Close public intake before stopping/restoring APIs. Even a subsequent
    # service-stop failure leaves the original maintenance ingress in place.
    ingress = {str(NGINX / 'sites-available/omneum-network'),
               str(NGINX / 'conf.d/omneum-network-limits.conf')}
    for entry in record['files']:
        if entry['target'] not in ingress: continue
        if entry['backup']: install(STATE / entry['backup'], entry['target'], entry['mode'])
        else: Path(entry['target']).unlink(missing_ok=True)
    if any(entry['target'] in ingress for entry in record['files']):
        run('nginx', '-t')
        run('systemctl', 'reload', 'nginx')
    for unit in reversed(UNITS):
        if run('systemctl', 'show', unit, '--property=LoadState', '--value').strip() != 'not-found':
            run('systemctl', 'stop', unit)
    # Restore files only; no database rollback or scalar/credential rotation.
    for entry in record['files']:
        target = Path(entry['target'])
        if entry['backup']:
            install(STATE / entry['backup'], target, entry['mode'])
        else:
            target.unlink(missing_ok=True)
    if (STATE / 'pyjwt-snapshot-complete').exists():
        for path in [SITE / 'jwt', *SITE.glob('PyJWT-*.dist-info'), *SITE.glob('pyjwt-*.dist-info')]:
            if path.exists(): shutil.rmtree(path)
        for path in (STATE / 'pyjwt-before').iterdir():
            shutil.copytree(path, SITE / path.name)
    run('systemctl', 'daemon-reload')
    run('nginx', '-t')
    run('systemctl', 'reload', 'nginx')
    for unit in UNITS:
        if record['active'][unit]:
            run('systemctl', 'start', unit)
    (STATE / 'complete').unlink(missing_ok=True)
    (STATE / 'rolled-back').write_text('restored original file and service state\n')
    (STATE / 'rolled-back').chmod(0o600)
    print('PASS rollback; DB, scalar and installation credentials preserved')

def apply(c, admin):
    check(c, admin)  # all missing DB/key inputs block before writes
    config_hash = hashlib.sha256(json.dumps(c, sort_keys=True).encode()).hexdigest()
    source_hashes = {name: hashlib.sha256(source.encode()).hexdigest()
                     for name, source in pin_sources(c).items()}
    if STATE.exists():
        d.safe_path(STATE, mode=0o700, directory=True)
        if (STATE / 'rolled-back').exists():
            STATE.rename(STATE.with_name(STATE.name + '-rolled-back-' + str(time.time_ns())))
            return apply(c, admin)
        previous = json.loads(d.private_read(STATE / 'rollback.json'))
        d.require(previous['config_hash'] == config_hash, 'activation already staged with different configuration')
        d.require(previous.get('source_hashes') == source_hashes,
                  'activation bundle changed; explicit upgrade review required')
        if (STATE / 'complete').exists():
            run(PYTHON, '-I', '-B', '-m', 'omneum.network_deploy', 'preflight')
            print('PASS already activated; no changes')
            return
        raise ValueError('incomplete prior activation; run rollback and inspect before retry')
    for unit in UNITS[1:]:
        status = subprocess.run(['systemctl', 'is-active', '--quiet', unit],
                                capture_output=True, timeout=30).returncode
        d.require(status in (3, 4), 'initial activation requires inactive APIs; use reviewed upgrade procedure')
    import re
    site = NGINX / 'sites-available/omneum-network'
    d.require(re.search(r'location\s+/\s*\{\s*return\s+503;\s*\}', site.read_text()),
              'initial activation requires the existing maintenance ingress')
    # Construct a complete rollback journal before publishing the state or
    # changing runtime files. Preparation failure leaves no ambiguous state.
    staging = Path(tempfile.mkdtemp(prefix='.omneum-activation-stage-', dir=STATE.parent))
    prepared = staging / 'prepared'
    prepare(c, prepared)
    rendered = staging / 'rendered'
    rendered.mkdir(mode=0o700)
    d.render(c, rendered, nginx_layout='certbot')
    targets = [(BUNDLE / 'network_deploy.py', SITE / 'omneum/network_deploy.py', 0o644),
               (prepared / 'contribution/network.py', SITE / 'omneum/contribution/network.py', 0o644),
               (prepared / 'onboarding.py', SITE / 'omneum/onboarding.py', 0o644),
               (prepared / 'production.json', d.ROOT / 'production.json', 0o600),
               (rendered / 'public.env', d.ROOT / 'public.env', 0o600),
               (rendered / 'nginx-site.conf', NGINX / 'sites-available/omneum-network', 0o644),
               (rendered / 'nginx-limits.conf', NGINX / 'conf.d/omneum-network-limits.conf', 0o600)]
    targets += [(rendered / unit, SYSTEMD / unit, 0o644) for unit in UNITS]
    # Include files replaced by TLS/JWKS helpers in the rollback journal.
    all_targets = [(str(t), mode) for _, t, mode in targets]
    all_targets += [(c[field], 0o600) for field in ('tls_certificate', 'tls_private_key', 'oidc_jwks_file')]
    records = []
    for index, (target, mode) in enumerate(all_targets):
        path = Path(target)
        backup = None
        if path.exists() or path.is_symlink():
            d.safe_path(path)
            mode = path.stat().st_mode & 0o777
            backup = f'backup-{index}'
            shutil.copyfile(path, staging / backup)
            (staging / backup).chmod(0o600)
        records.append(dict(target=target, mode=mode, backup=backup,
                            sha256=digest(staging / backup) if backup else None))
    active = {unit: subprocess.run(['systemctl', 'is-active', '--quiet', unit]).returncode == 0 for unit in UNITS}
    journal = staging / 'rollback.json'
    journal.write_text(json.dumps(dict(files=records, active=active,
                                       config_hash=config_hash, source_hashes=source_hashes)))
    journal.chmod(0o600)
    # Snapshot dependency files so rollback does not invoke pip/network.
    dependency = staging / 'pyjwt-before'
    dependency.mkdir(mode=0o700)
    for path in [SITE / 'jwt', *SITE.glob('PyJWT-*.dist-info'), *SITE.glob('pyjwt-*.dist-info')]:
        if path.exists(): shutil.copytree(path, dependency / path.name)
    checksums = {str(path.relative_to(dependency)): digest(path)
                 for path in dependency.rglob('*') if path.is_file()}
    (staging / 'pyjwt-before.json').write_text(json.dumps(checksums))
    (staging / 'pyjwt-before.json').chmod(0o600)
    (staging / 'pyjwt-snapshot-complete').write_text('complete\n')
    (staging / 'pyjwt-snapshot-complete').chmod(0o600)
    for path in staging.rglob('*'):
        if path.is_file():
            with path.open('rb') as stream: os.fsync(stream.fileno())
    sync_directory(staging)
    staging.rename(STATE)
    sync_directory(STATE.parent)
    # Relocate prepared sources following the atomic state-directory rename.
    targets = [(STATE / source.relative_to(staging) if staging in source.parents else source,
                target, mode) for source, target, mode in targets]
    try:
        # Install runtime/public configuration first; ingress is last.
        for source, target, mode in targets[:5] + targets[7:]: install(source, target, mode)
        run(PYTHON, '-I', '-B', '-m', 'pip', 'install', '--no-index', '--no-deps', str(BUNDLE / 'pyjwt-2.15.0-py3-none-any.whl'))
        run(PYTHON, '-I', '-B', '-m', 'pip', 'check')
        run(PYTHON, '-I', '-B', '-m', 'omneum.network_release', '--require-provisioned')
        run(PYTHON, '-I', '-B', '-m', 'omneum.network_deploy', 'install-certificates')
        run(PYTHON, '-I', '-B', '-m', 'omneum.network_deploy', 'refresh-jwks')
        run('systemctl', 'daemon-reload')
        for unit in UNITS: run('systemctl', 'restart', unit)
        for source, target, mode in targets[5:7]: install(source, target, mode)
        run('nginx', '-t')
        run('systemctl', 'reload', 'nginx')
        run(PYTHON, '-I', '-B', '-m', 'omneum.network_deploy', 'preflight')
        (STATE / 'complete').write_text('preflight passed; real-user acceptance pending\n')
        (STATE / 'complete').chmod(0o600)
        print('PASS activated; real-user acceptance still required')
    except BaseException:
        rollback()
        raise

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('command', choices=['prepare', 'check', 'apply', 'rollback'])
    p.add_argument('--config', default=str(BUNDLE / 'production.pending.json'))
    p.add_argument('--output')
    p.add_argument('--admin-dsn-file', default='/root/network-admin.dsn')
    p.add_argument('--authorize-production-mutations', action='store_true')
    args = p.parse_args()
    verify_bundle()
    if args.command == 'prepare':
        d.require(args.output, 'prepare requires --output')
        prepare(config(args.config), args.output)
        return
    d.require(os.geteuid() == 0, 'operator root authorization required')
    d.safe_path(BUNDLE, mode=0o700, directory=True)
    if args.command in ('apply', 'rollback'):
        d.require(args.authorize_production_mutations, 'explicit production mutation authorization required')
    if args.command == 'rollback':
        # Recovery must remain available if activation damaged the runtime tree.
        with mutation_lock(): rollback()
    else:
        d.safe_path(args.config, mode=0o600)
        c = config(args.config)
        if args.command == 'check': check(c, args.admin_dsn_file)
        else:
            with mutation_lock(): apply(c, args.admin_dsn_file)

if __name__ == '__main__':
    try: main()
    except Exception as error:
        message = str(error) if type(error) is ValueError else 'dependency failed; inspect privately; no readiness claim'
        sys.exit('BLOCKED: ' + message)
