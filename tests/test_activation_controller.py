"""Activation gates and rollback tested entirely with disposable local files."""
import ast
import importlib.util
import json
from pathlib import Path
import sys

import pytest
from test_network_deploy import configuration

PATH = Path(__file__).parents[1] / 'deploy/network/vm/activate.py'
spec = importlib.util.spec_from_file_location('activation_controller', PATH)
a = importlib.util.module_from_spec(spec)
spec.loader.exec_module(a)


@pytest.fixture
def artifact_bundle(tmp_path, monkeypatch):
    import hashlib
    source = a.SOURCE_ROOT / 'omneum/network_deploy.py'
    (tmp_path / 'network_deploy.py').write_bytes(source.read_bytes())
    wheel = tmp_path / 'pyjwt-2.15.0-py3-none-any.whl'
    wheel.write_bytes(b'disposable verification fixture, never installed')
    monkeypatch.setattr(a, 'BUNDLE', tmp_path)
    monkeypatch.setattr(a, 'MODULE_DIGEST', a.digest(source))
    monkeypatch.setattr(a, 'WHEEL_DIGEST', a.digest(wheel))
    return tmp_path


def test_verified_artifacts_and_missing_inputs(artifact_bundle):
    a.verify_bundle()
    with pytest.raises(ValueError, match='missing public settings'):
        a.config(a.SOURCE_ROOT / 'deploy/network/vm/production.json')


def test_release_pins(configuration, tmp_path, monkeypatch):
    from omneum.contribution import network
    from omneum import onboarding
    from omneum.network_release import validate_release
    before = {name: (a.SOURCE_ROOT / 'omneum' / name).read_bytes()
              for name in ('contribution/network.py', 'onboarding.py')}
    a.prepare(configuration, tmp_path)
    for name, module, constant in [('contribution/network.py', network, '_PRODUCTION_NETWORK'),
                                    ('onboarding.py', onboarding, '_PRODUCTION_ONBOARDING')]:
        tree = ast.parse((tmp_path / name).read_text())
        assignment = next(node for node in tree.body if isinstance(node, ast.AnnAssign)
                          and isinstance(node.target, ast.Name) and node.target.id == constant)
        value = eval(compile(ast.Expression(assignment.value), '<prepared-public-pins>', 'eval'), vars(module))
        monkeypatch.setattr(module, constant, value)
        assert before[name] == (a.SOURCE_ROOT / 'omneum' / name).read_bytes()
    assert validate_release(require_provisioned=True)
    a.d.pins_match(configuration)


def test_artifact_tampering_is_rejected(tmp_path, monkeypatch):
    monkeypatch.setattr(a, 'BUNDLE', tmp_path)
    (tmp_path / 'network_deploy.py').write_text('tampered')
    with pytest.raises(ValueError, match='checksum mismatch'):
        a.verify_bundle()


@pytest.mark.parametrize('command', ['apply', 'rollback'])
def test_mutations_require_explicit_authorization(monkeypatch, command, artifact_bundle):
    monkeypatch.setattr(a.os, 'geteuid', lambda: 0)
    monkeypatch.setattr(a.d, 'safe_path', lambda *args, **kwargs: None)
    monkeypatch.setattr(a.d, 'validate_runtime_tree', lambda: None)
    monkeypatch.setattr(sys, 'argv', ['activate.py', command])
    with pytest.raises(ValueError, match='explicit production mutation authorization'):
        a.main()


def test_rollback_state(tmp_path, monkeypatch):
    state = tmp_path / 'state'
    state.mkdir()
    site = tmp_path / 'site-packages'
    site.mkdir()
    (site / 'jwt').mkdir()
    (site / 'jwt/version').write_text('new')
    backup = state / 'pyjwt-before/jwt'
    backup.mkdir(parents=True)
    (backup / 'version').write_text('original')
    (state / 'pyjwt-snapshot-complete').touch()
    (state / 'pyjwt-before.json').write_text(json.dumps({'jwt/version': a.digest(backup / 'version')}))
    original = tmp_path / 'nginx-site'
    original.write_text('new routing')
    (state / 'backup-0').write_text('maintenance 503')
    created = tmp_path / 'new-unit'
    created.write_text('generated')
    (state / 'rollback.json').write_text(json.dumps(dict(
        files=[dict(target=str(original), mode=0o644, backup='backup-0', sha256=a.digest(state / 'backup-0')),
               dict(target=str(created), mode=0o644, backup=None)],
        active={unit: False for unit in a.UNITS})))
    (state / 'complete').touch()
    monkeypatch.setattr(a, 'STATE', state)
    monkeypatch.setattr(a, 'SITE', site)
    monkeypatch.setattr(a.d, 'safe_path', lambda *args, **kwargs: None)
    monkeypatch.setattr(a.d, 'private_read', lambda path: Path(path).read_bytes())
    calls = []
    def run(*args):
        calls.append(args)
        return 'not-found\n' if '--property=LoadState' in args else ''
    monkeypatch.setattr(a, 'run', run)
    monkeypatch.setattr(a, 'install', lambda src, dst, mode: Path(dst).write_bytes(Path(src).read_bytes()))
    a.rollback()
    assert original.read_text() == 'maintenance 503'
    assert not created.exists()
    assert (site / 'jwt/version').read_text() == 'original'
    assert not (state / 'complete').exists()
    assert not any(call[:2] == ('systemctl', 'start') for call in calls)
    before = len(calls)
    a.rollback()
    assert len(calls) == before


def test_apply_prerequisites(configuration, tmp_path, monkeypatch):
    monkeypatch.setattr(a, 'STATE', tmp_path / 'state')
    def missing(*args):
        raise ValueError('migration ledger missing')
    monkeypatch.setattr(a, 'check', missing)
    with pytest.raises(ValueError, match='migration ledger missing'):
        a.apply(configuration, '/not-used')
    assert not a.STATE.exists()


def test_completed_apply_is_idempotent(configuration, tmp_path, monkeypatch):
    import hashlib
    state = tmp_path / 'state'
    state.mkdir()
    fingerprint = hashlib.sha256(json.dumps(configuration, sort_keys=True).encode()).hexdigest()
    hashes = {name: hashlib.sha256(source.encode()).hexdigest()
              for name, source in a.pin_sources(configuration).items()}
    (state / 'rollback.json').write_text(json.dumps(dict(config_hash=fingerprint, source_hashes=hashes)))
    (state / 'complete').touch()
    monkeypatch.setattr(a, 'STATE', state)
    monkeypatch.setattr(a, 'check', lambda *args: None)
    monkeypatch.setattr(a.d, 'safe_path', lambda *args, **kwargs: None)
    monkeypatch.setattr(a.d, 'private_read', lambda path: Path(path).read_bytes())
    calls = []
    monkeypatch.setattr(a, 'run', lambda *args: calls.append(args) or '')
    a.apply(configuration, '/not-used')
    assert calls == [(a.PYTHON, '-I', '-B', '-m', 'omneum.network_deploy', 'preflight')]


def test_wheel_pin_isolation(configuration, tmp_path):
    # Diagnostic copy only. The public build must originate from reviewed source.
    import base64
    import csv
    import hashlib
    import io
    import zipfile
    import os
    sys.path.insert(0, str(a.SOURCE_ROOT / 'tools'))
    import release_wheels
    if os.environ.get('OMNEUM_ACTIVATION_TEST_WHEEL'):
        source = Path(os.environ['OMNEUM_ACTIVATION_TEST_WHEEL'])
    else:
        # Self-contained release-contract fixture keeps this regression portable.
        from test_release_wheels import WheelReleaseTests
        fixture = WheelReleaseTests()
        fixture.wheels = tmp_path / 'fixture-wheels'
        fixture.wheels.mkdir()
        source = fixture.wheel('cp311', 'macos-x86_64')
        with zipfile.ZipFile(source, 'a') as archive:
            for name in ('contribution/network.py', 'onboarding.py', 'installation.py'):
                archive.writestr('omneum/' + name, (a.SOURCE_ROOT / 'omneum' / name).read_bytes())
            archive.writestr('omneum_oprf.so', b'disposable native marker')
            archive.writestr('omneum-1.0.3.dist-info/RECORD', '')
    original_hash = a.digest(source)
    with zipfile.ZipFile(source) as archive:
        original = {info.filename: archive.read(info.filename) for info in archive.infolist()}
    variant = dict(original)
    for name, content in a.pin_sources(configuration).items():
        variant['omneum/' + name] = content.encode()
    record = next(name for name in variant if name.endswith('.dist-info/RECORD'))
    output = io.StringIO(newline='')
    writer = csv.writer(output, lineterminator='\n')
    for name, content in sorted(variant.items()):
        if name != record:
            checksum = base64.urlsafe_b64encode(hashlib.sha256(content).digest()).decode().rstrip('=')
            writer.writerow([name, 'sha256=' + checksum, len(content)])
    writer.writerow([record, '', ''])
    variant[record] = output.getvalue().encode()
    target = tmp_path / source.name
    with zipfile.ZipFile(target, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        for name, content in variant.items(): archive.writestr(name, content)
    assert release_wheels.inspect_wheel(target, '1.0.3') == ('cp311', 'macos-x86_64')
    changed = {name for name in original if original[name] != variant[name]}
    assert changed == {'omneum/contribution/network.py', 'omneum/onboarding.py', record}
    assert a.digest(source) == original_hash
    with zipfile.ZipFile(target) as archive:
        for name, checksum, length in csv.reader(io.StringIO(archive.read(record).decode())):
            if name == record: continue
            content = archive.read(name)
            assert int(length) == len(content)
            assert checksum == 'sha256=' + base64.urlsafe_b64encode(hashlib.sha256(content).digest()).decode().rstrip('=')


def test_prepare_symlinks(configuration, tmp_path):
    output = tmp_path / 'pins'
    a.prepare(configuration, output)
    content = (output / 'onboarding.py').read_bytes()
    before = (output / 'onboarding.py').stat().st_mtime_ns
    a.prepare(configuration, output)
    assert (output / 'onboarding.py').stat().st_mtime_ns == before
    with pytest.raises(ValueError, match='differs'):
        a.prepare({**configuration, 'consent_version': 'another-version'}, output)
    assert (output / 'onboarding.py').read_bytes() == content
    linked = tmp_path / 'linked'
    linked.symlink_to(output, target_is_directory=True)
    with pytest.raises(ValueError, match='symlink'):
        a.prepare(configuration, linked)
    with pytest.raises(ValueError, match='overwrite source'):
        a.prepare(configuration, a.SOURCE_ROOT / 'omneum')


def test_invalid_config_paths(configuration, tmp_path):
    path = tmp_path / 'configuration.json'
    path.write_text('{"domain":"first","domain":"second"}')
    with pytest.raises(ValueError): a.config(path)
    path.write_text(json.dumps({**configuration, 'tls_private_key': '/var/lib/omneum-network-crypto/voprf.key'}))
    with pytest.raises(ValueError, match='under secrets'): a.config(path)


@pytest.fixture
def apply_environment(configuration, tmp_path, monkeypatch, artifact_bundle):
    from types import SimpleNamespace
    site, root, nginx, systemd = [tmp_path / name for name in ('site-packages', 'config', 'nginx', 'systemd')]
    for path in (site / 'omneum/contribution', root / 'secrets', nginx / 'sites-available', nginx / 'conf.d', systemd):
        path.mkdir(parents=True)
    original = {
        site / 'omneum/network_deploy.py': 'old deployment module',
        site / 'omneum/contribution/network.py': 'old network pins',
        site / 'omneum/onboarding.py': 'old onboarding',
        root / 'production.json': 'old configuration',
        root / 'public.env': 'old environment',
        nginx / 'sites-available/omneum-network': 'server { location / { return 503; } }',
        root / 'secrets/tls.crt': 'old certificate',
        root / 'secrets/tls.key': 'old TLS key',
        root / 'secrets/jwks.json': 'old public JWKS',
    }
    for path, content in original.items(): path.write_text(content)
    (site / 'jwt').mkdir()
    (site / 'jwt/version').write_text('old PyJWT')
    c = dict(configuration)
    for field in ('database_ca', 'ingestion_dsn_file', 'enrollment_dsn_file',
                  'tls_certificate', 'tls_private_key', 'oidc_jwks_file'):
        c[field] = str(root / 'secrets' / Path(c[field]).name)
    monkeypatch.setattr(a, 'SITE', site)
    monkeypatch.setattr(a, 'STATE', tmp_path / 'state')
    monkeypatch.setattr(a, 'NGINX', nginx)
    monkeypatch.setattr(a, 'SYSTEMD', systemd)
    monkeypatch.setattr(a.d, 'ROOT', root)
    monkeypatch.setattr(a.d, 'safe_path', lambda *args, **kwargs: None)
    monkeypatch.setattr(a.d, 'private_read', lambda path: Path(path).read_bytes())
    monkeypatch.setattr(a.d, 'identities', lambda: [SimpleNamespace(pw_uid=uid) for uid in (986, 985, 984)])
    monkeypatch.setattr(a, 'check', lambda *args: None)
    monkeypatch.setattr(a.subprocess, 'run', lambda *args, **kwargs: SimpleNamespace(returncode=3))
    # Source fixture used solely to detect forbidden scalar/DSN changes.
    scalar = tmp_path / 'scalar'
    scalar.write_bytes(b'preserved-fixture-scalar')
    dsn = root / 'secrets/ingestion.dsn'
    dsn.write_text('preserved-fixture-DSN')
    calls = []
    state = {'fail': None, 'failed': False}
    def run(*args):
        calls.append(args)
        if args[:3] == ('systemctl', 'show', a.UNITS[0]) or '--property=LoadState' in args:
            return 'loaded\n'
        if 'pip' in args and 'install' in args:
            (site / 'jwt/version').write_text('new PyJWT')
        if args[-1] == 'install-certificates':
            for field in ('tls_certificate', 'tls_private_key'): Path(c[field]).write_text('new TLS copy')
        if args[-1] == 'refresh-jwks': Path(c['oidc_jwks_file']).write_text('new public JWKS')
        if state['fail'] and state['fail'] in args and not state['failed']:
            state['failed'] = True
            raise RuntimeError('simulated mutation-stage failure')
        return ''
    monkeypatch.setattr(a, 'run', run)
    return c, original, scalar, dsn, calls, state


@pytest.mark.parametrize('failure', ['pip', 'check', 'network_release', 'install-certificates',
                                    'refresh-jwks', 'daemon-reload', 'restart', '-t', 'reload', 'preflight'])
def test_apply_rollback(apply_environment, failure):
    c, original, scalar, dsn, calls, state = apply_environment
    # network_release is passed as qualified module name.
    state['fail'] = 'omneum.network_release' if failure == 'network_release' else failure
    with pytest.raises(RuntimeError, match='simulated'): a.apply(c, '/not-used')
    assert state['failed']
    for path, value in original.items(): assert path.read_text() == value
    assert (a.SITE / 'jwt/version').read_text() == 'old PyJWT'
    assert scalar.read_bytes() == b'preserved-fixture-scalar'
    assert dsn.read_text() == 'preserved-fixture-DSN'
    assert not list(a.SYSTEMD.iterdir())
    assert not list((a.NGINX / 'conf.d').iterdir())
    assert (a.STATE / 'rolled-back').exists()
    assert not (a.STATE / 'complete').exists()
    assert not any('migrate' in call or 'generate-dsns' in call for call in calls)


def test_apply_preserves_credentials(apply_environment):
    c, original, scalar, dsn, calls, state = apply_environment
    a.apply(c, '/not-used')
    assert (a.STATE / 'complete').exists()
    before = {path: path.read_bytes() for path in original}
    calls.clear()
    a.apply(c, '/not-used')
    assert calls == [(a.PYTHON, '-I', '-B', '-m', 'omneum.network_deploy', 'preflight')]
    assert {path: path.read_bytes() for path in original} == before
    assert scalar.read_bytes() == b'preserved-fixture-scalar'
    assert dsn.read_text() == 'preserved-fixture-DSN'


def test_tampered_rollback_backup_stops_before_service_changes(apply_environment):
    c, original, scalar, dsn, calls, state = apply_environment
    a.apply(c, '/not-used')
    (a.STATE / 'backup-0').write_text('tampered')
    calls.clear()
    with pytest.raises(ValueError, match='checksum mismatch'): a.rollback()
    assert not calls


def test_mutation_lock_blocks_concurrent_controller(tmp_path, monkeypatch):
    monkeypatch.setattr(a, 'STATE', tmp_path / 'state')
    monkeypatch.setattr(a.d, 'safe_path', lambda *args, **kwargs: None)
    original = a.os.fstat
    def root_stat(fd):
        info = list(original(fd))
        info[4] = 0  # Simulated owner only; real local flock exercises exclusion.
        return a.os.stat_result(info)
    monkeypatch.setattr(a.os, 'fstat', root_stat)
    with a.mutation_lock():
        with pytest.raises(ValueError, match='another activation'):
            with a.mutation_lock(): pytest.fail('concurrent lock acquired')
    with a.mutation_lock(): pass


def test_render_failure(apply_environment, monkeypatch):
    c, original, scalar, dsn, calls, state = apply_environment
    def fail(*args, **kwargs): raise ValueError('rendering failed')
    monkeypatch.setattr(a.d, 'render', fail)
    with pytest.raises(ValueError, match='rendering failed'): a.apply(c, '/not-used')
    assert not a.STATE.exists()
    assert not calls
    for path, value in original.items(): assert path.read_text() == value


def test_incomplete_activation_cannot_be_applied_again(apply_environment):
    c, original, scalar, dsn, calls, state = apply_environment
    a.apply(c, '/not-used')
    (a.STATE / 'complete').unlink()
    calls.clear()
    with pytest.raises(ValueError, match='incomplete prior activation'): a.apply(c, '/not-used')
    assert not calls


def test_apply_after_rollback(apply_environment):
    c, original, scalar, dsn, calls, state = apply_environment
    a.apply(c, '/not-used')
    a.rollback()
    a.apply(c, '/not-used')
    assert (a.STATE / 'complete').exists()
    assert list(a.STATE.parent.glob('state-rolled-back-*'))
    a.rollback()
    for path, value in original.items(): assert path.read_text() == value


def test_rollback_stop_failure(apply_environment, monkeypatch):
    c, original, scalar, dsn, calls, state = apply_environment
    a.apply(c, '/not-used')
    calls.clear()
    original_run = a.run
    def fail_stop(*args):
        if args[:2] == ('systemctl', 'stop'):
            raise RuntimeError('simulated stop failure')
        return original_run(*args)
    monkeypatch.setattr(a, 'run', fail_stop)
    with pytest.raises(RuntimeError, match='stop failure'): a.rollback()
    site = a.NGINX / 'sites-available/omneum-network'
    assert site.read_text() == original[site]
    assert calls[:2] == [('nginx', '-t'), ('systemctl', 'reload', 'nginx')]
    assert not (a.STATE / 'rolled-back').exists()
    monkeypatch.setattr(a, 'run', original_run)
    a.rollback()
    for path, value in original.items(): assert path.read_text() == value


def test_initial_activation_refuses_running_apis(apply_environment, monkeypatch):
    from types import SimpleNamespace
    c, original, scalar, dsn, calls, state = apply_environment
    monkeypatch.setattr(a.subprocess, 'run', lambda *args, **kwargs: SimpleNamespace(returncode=0))
    with pytest.raises(ValueError, match='inactive APIs'): a.apply(c, '/not-used')
    assert not a.STATE.exists()
    for path, value in original.items(): assert path.read_text() == value


def test_rollback_rejects_added_dependency_backup_files(apply_environment):
    c, original, scalar, dsn, calls, state = apply_environment
    a.apply(c, '/not-used')
    (a.STATE / 'pyjwt-before/jwt/unexpected.py').write_text('unexpected')
    calls.clear()
    with pytest.raises(ValueError, match='inventory mismatch'): a.rollback()
    assert not calls


def test_deployment_digest():
    assert a.digest(a.SOURCE_ROOT / 'omneum/network_deploy.py') == a.MODULE_DIGEST
