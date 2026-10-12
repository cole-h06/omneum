"""Distribution checks use synthetic bundles; never network or sudo."""

import gzip
import hashlib
import io
from pathlib import Path
import subprocess
import tarfile
from unittest.mock import Mock
from urllib.request import Request

import pytest

from omneum import installation as install


@pytest.mark.parametrize('system,machine,target', [
    ('Darwin', 'arm64', 'macos-aarch64'),
    ('Darwin', 'aarch64', 'macos-aarch64'),
    ('Darwin', 'x86_64', 'macos-x86_64'),
    ('Linux', 'x86_64', 'linux-x86_64'),
])
def test_platform(monkeypatch, system, machine, target):
    monkeypatch.setattr(install.platform, 'system', lambda: system)
    monkeypatch.setattr(install.platform, 'machine', lambda: machine)
    assert install.detect_platform() == target


@pytest.mark.parametrize('system,machine', [('Windows', 'AMD64'), ('Linux', 'aarch64'), ('FreeBSD', 'x86_64')])
def test_unsupported(monkeypatch, system, machine):
    monkeypatch.setattr(install.platform, 'system', lambda: system)
    monkeypatch.setattr(install.platform, 'machine', lambda: machine)
    with pytest.raises(install.InstallError, match='not supported'):
        install.detect_platform()


def test_exact_urls():
    assert install.release_assets('1.0.3', 'macos-aarch64') == (
        'omneum-daemon-1.0.3-macos-aarch64.tar.gz',
        'https://github.com/cole-h06/omneum/releases/download/v1.0.3/SHA256SUMS',
        'https://github.com/cole-h06/omneum/releases/download/v1.0.3/omneum-daemon-1.0.3-macos-aarch64.tar.gz',
    )
    for version in ['latest', '../1.0.3', '1.0.3/evil', '1.0.3\n']:
        with pytest.raises(install.InstallError):
            install.release_assets(version, 'macos-aarch64')


def manifest(data=b'archive'):
    digest = hashlib.sha256(data).hexdigest()
    return ''.join(f'{digest}  omneum-daemon-1.0.3-{p}.tar.gz\n' for p in install.PLATFORMS).encode()


def test_valid_checksum():
    install.verify_checksum(manifest(), b'archive', '1.0.3', 'macos-aarch64')


@pytest.mark.parametrize('data', [
    b'', b'garbage\n', b'\xff\n', manifest().replace(b'  ', b' '),
    b'\n'.join(manifest().splitlines()[1:]) + b'\n',
    manifest() + manifest().splitlines()[1] + b'\n',
    manifest(b'wrong'), manifest().replace(b'1.0.3', b'1.0.4'),
    manifest().replace(b'omneum-daemon', b'../omneum-daemon'),
])
def test_reject_checksum(data):
    with pytest.raises(install.InstallError):
        install.verify_checksum(data, b'archive', '1.0.3', 'macos-aarch64')


def archive(target='macos-aarch64', mutate=lambda members: members):
    members = []
    for name, mode in sorted(install.bundle_layout(target).items()):
        item = tarfile.TarInfo(name)
        item.mode = mode
        if name in {'systemd', 'sysusers.d', 'launchd'}:
            item.type = tarfile.DIRTYPE
        else:
            item.size = len(runtime_fixture()) if name == 'runtime.tar.gz' else len(name.encode())
        members.append(item)
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode='w', format=tarfile.USTAR_FORMAT) as output:
        for item in mutate(members):
            output.addfile(item, io.BytesIO(runtime_fixture() if item.name == 'runtime.tar.gz' else item.name.encode()) if item.isfile() else None)
    return gzip.compress(buffer.getvalue())


@pytest.mark.parametrize('target', install.PLATFORMS)
def test_layout_and_permissions(tmp_path, target):
    destination = tmp_path / 'bundle'
    install.extract_bundle(archive(target), destination, target, '1.0.3')
    assert {p.relative_to(destination).as_posix() for p in destination.rglob('*')} == install.bundle_layout(target).keys()
    assert (destination / 'omneumd').read_bytes() == b'omneumd'
    assert (destination / 'omneumd').stat().st_mode & 0o777 == 0o755


@pytest.mark.parametrize('name', ['../escape', '/tmp/escape', 'launchd/../../escape', './omneumd', 'launchd//evil', 'C:\\evil'])
def test_traversal(tmp_path, name):
    def mutate(items):
        item = tarfile.TarInfo(name)
        return items + [item]
    with pytest.raises(install.InstallError):
        install.extract_bundle(archive(mutate=mutate), tmp_path / 'bundle', 'macos-aarch64')
    assert not (tmp_path / 'bundle').exists()


@pytest.mark.parametrize('kind', [tarfile.SYMTYPE, tarfile.LNKTYPE, tarfile.FIFOTYPE, tarfile.CHRTYPE, tarfile.BLKTYPE])
def test_links_and_special_files(tmp_path, kind):
    def mutate(items):
        items[-1].type = kind
        items[-1].linkname = '/etc/passwd'
        return items
    with pytest.raises(install.InstallError):
        install.extract_bundle(archive(mutate=mutate), tmp_path / 'bundle', 'macos-aarch64')
    assert not (tmp_path / 'bundle').exists()


@pytest.mark.parametrize('change', ['missing', 'duplicate', 'mode', 'owner'])
def test_bad_layout(tmp_path, change):
    def mutate(items):
        if change == 'missing':
            return items[:-1]
        if change == 'duplicate':
            return items + items[-1:]
        if change == 'mode':
            items[-1].mode = 0o777
        if change == 'owner':
            items[-1].uid = 501
        return items
    with pytest.raises(install.InstallError):
        install.extract_bundle(archive(mutate=mutate), tmp_path / 'bundle', 'macos-aarch64')


def test_limits(tmp_path, monkeypatch):
    monkeypatch.setattr(install, 'MAX_EXPANDED', 100)
    with pytest.raises(install.InstallError, match='size limit'):
        install.extract_bundle(archive(), tmp_path / 'bundle', 'macos-aarch64')


@pytest.mark.parametrize('url', ['http://github.com/file', 'https://evil.example/file',
    'https://github.com.evil.example/file', 'https://user@github.com/file', 'file:///tmp/file'])
def test_reject_redirect(url):
    with pytest.raises(install.InstallError):
        install.ReleaseRedirects().redirect_request(Request(install.RELEASE_BASE), None, 302, '', {}, url)


def test_github_https_redirect():
    url = 'https://release-assets.githubusercontent.com/asset?signature=abc'
    request = install.ReleaseRedirects().redirect_request(Request(install.RELEASE_BASE), None, 302, '', {}, url)
    assert request.full_url == url


def test_download_uses_bounded_https_request(monkeypatch):
    url = install.release_assets('1.0.3', 'macos-aarch64')[1]
    response = Mock()
    response.geturl.return_value = url
    response.read.return_value = b'contents'
    response.__enter__ = Mock(return_value=response)
    response.__exit__ = Mock(return_value=False)
    opener = Mock()
    opener.open.return_value = response
    monkeypatch.setattr(install, 'build_opener', lambda *args: opener)
    assert install.download(url, 100) == b'contents'
    response.read.assert_called_once_with(101)
    assert opener.open.call_args.kwargs['timeout'] == 30


def test_correct_installer():
    root = Path('/private/bundle')
    assert install.installer_command(root, 'macos-aarch64', 501, systemd=False) == [
        '/bin/sh', str(root / 'install-macos.sh'), str(root / 'omneumd'), '501']
    assert install.installer_command(root, 'linux-x86_64', 1000, systemd=True) == [
        '/bin/sh', str(root / 'install.sh'), str(root / 'omneumd')]
    with pytest.raises(install.InstallError, match='persistent'):
        install.installer_command(root, 'linux-x86_64', 1000, systemd=False)


def test_installer_failure(monkeypatch, tmp_path):
    monkeypatch.setattr(install.os, 'getuid', lambda: 501)
    monkeypatch.setattr(install.subprocess, 'run', Mock(side_effect=[
        subprocess.CompletedProcess([], 0),
        subprocess.CompletedProcess([], 1, '', 'install-macos: daemon failed to start\n')]))
    with pytest.raises(install.InstallError, match='daemon failed to start'):
        install.deploy_bundle(tmp_path, 'macos-aarch64')
    args = install.subprocess.run.call_args.args[0]
    assert args[:4] == ['/usr/bin/sudo', '-n', '--', '/bin/sh']


def test_probe_uses_existing_pin_and_real_voprf(example_daemon):
    install.verify_connection()


def test_release_flow_and_cleanup(monkeypatch):
    data = archive()
    seen = []
    monkeypatch.setattr(install, 'package_version', lambda name: '1.0.3')
    network = Mock(side_effect=[manifest(data), data])
    monkeypatch.setattr(install, 'download', network)
    def deploy(bundle, target):
        assert target == 'macos-aarch64'
        assert (bundle / 'omneumd').read_bytes() == b'omneumd'
        seen.append(bundle)
    monkeypatch.setattr(install, 'deploy_bundle', deploy)
    progress = Mock()
    install.install_release('macos-aarch64', progress)
    assert all('v1.0.3/' in call.args[0] for call in network.call_args_list)
    assert len(seen) == 1 and not seen[0].parent.exists()


def test_unverified_archive_never_extracted_or_executed(monkeypatch):
    monkeypatch.setattr(install, 'package_version', lambda name: '1.0.3')
    monkeypatch.setattr(install, 'download', Mock(side_effect=[manifest(), b'wrong']))
    extract = Mock()
    deploy = Mock()
    monkeypatch.setattr(install, 'extract_bundle', extract)
    monkeypatch.setattr(install, 'deploy_bundle', deploy)
    with pytest.raises(install.InstallError, match='checksum mismatch'):
        install.install_release('macos-aarch64', Mock())
    extract.assert_not_called()
    deploy.assert_not_called()


def test_failed_deployment_cleans_temporary_artifacts(monkeypatch):
    data = archive()
    seen = []
    monkeypatch.setattr(install, 'package_version', lambda name: '1.0.3')
    monkeypatch.setattr(install, 'download', Mock(side_effect=[manifest(data), data]))
    def fail(bundle, target):
        seen.append(bundle)
        raise install.InstallError('installer failed')
    monkeypatch.setattr(install, 'deploy_bundle', fail)
    with pytest.raises(install.InstallError, match='installer failed'):
        install.install_release('macos-aarch64', Mock())
    assert not seen[0].parent.exists()


@pytest.mark.parametrize('stage', ['initialize', 'verify'])
def test_finish_failure_never_reports_ready(stage):
    initialize, verify, progress = Mock(), Mock(), Mock()
    (initialize if stage == 'initialize' else verify).side_effect = ValueError('failure')
    with pytest.raises(install.InstallError):
        install.finish_install(initialize, verify, progress)
    assert 'Omneum is ready.' not in [call.args[0] for call in progress.call_args_list]
    if stage == 'initialize':
        verify.assert_not_called()


def test_finish_success():
    initialize, verify, progress = Mock(), Mock(), Mock()
    install.finish_install(initialize, verify, progress)
    initialize.assert_called_once_with()
    verify.assert_called_once_with()
    assert progress.call_args.args == ('Omneum is ready.',)


@pytest.fixture
def mac_install(monkeypatch):
    from omneum import initialization
    monkeypatch.setattr(install, 'detect_platform', lambda: 'macos-aarch64')
    monkeypatch.setattr(install.os, 'geteuid', lambda: 501)
    monkeypatch.setattr(install.os, 'getuid', lambda: 501)
    monkeypatch.delenv('OMNEUM_DAEMON_UID', raising=False)
    monkeypatch.delenv('OMNEUM_DAEMON_SOCKET', raising=False)
    monkeypatch.setattr(install, 'package_version', lambda name: '1.0.3')
    data = archive()
    monkeypatch.setattr(install, 'download', Mock(side_effect=[manifest(data), data]))
    monkeypatch.setattr(install, 'deploy_bundle', Mock())
    monkeypatch.setattr(initialization, 'initialize', Mock())
    monkeypatch.setattr(install, 'verify_connection', Mock())
    return initialization


def test_cli_end_to_end(mac_install):
    from typer.testing import CliRunner
    from omneum.cli import app
    result = CliRunner().invoke(app, ['install'])
    assert result.exit_code == 0, result.output
    assert result.output.splitlines() == [
        'Detecting platform... macOS arm64', 'Downloading Omneum daemon 1.0.3...',
        'Verifying release...', 'Installing protected daemon...',
        'Initializing Omneum...', 'Verifying connection...', 'Omneum is ready.',
    ]
    mac_install.initialize.assert_called_once_with()
    install.verify_connection.assert_called_once_with()
    bundle = install.deploy_bundle.call_args.args[0]
    assert not bundle.parent.exists()


@pytest.mark.parametrize('stage', ['deploy', 'initialize', 'verify'])
def test_cli_failure(mac_install, stage):
    from typer.testing import CliRunner
    from omneum.cli import app
    boundary = {'deploy': install.deploy_bundle, 'initialize': mac_install.initialize,
                'verify': install.verify_connection}[stage]
    boundary.side_effect = install.InstallError('synthetic failure')
    result = CliRunner().invoke(app, ['install'])
    assert result.exit_code == 1
    assert 'Installation failed:' in result.output
    assert 'Omneum is ready.' not in result.output
    if stage == 'deploy':
        mac_install.initialize.assert_not_called()
    if stage != 'verify':
        install.verify_connection.assert_not_called()


@pytest.mark.parametrize('variable', ['OMNEUM_DAEMON_UID', 'OMNEUM_DAEMON_SOCKET'])
def test_install_rejects_endpoint_overrides(mac_install, monkeypatch, variable):
    monkeypatch.setenv(variable, 'override')
    with pytest.raises(install.InstallError, match='Unset'):
        install.run_install(Mock())
    install.download.assert_not_called()


def test_install_rejects_root(mac_install, monkeypatch):
    monkeypatch.setattr(install.os, 'geteuid', lambda: 0)
    with pytest.raises(install.InstallError, match='normal login user'):
        install.run_install(Mock())
    install.download.assert_not_called()


def test_missing_release_actionable(monkeypatch):
    from urllib.error import HTTPError
    url = install.release_assets('1.0.3', 'macos-aarch64')[1]
    opener = Mock()
    opener.open.side_effect = HTTPError(url, 404, '', {}, None)
    monkeypatch.setattr(install, 'build_opener', lambda *args: opener)
    with pytest.raises(install.InstallError, match='exact Omneum version'):
        install.download(url, install.MAX_MANIFEST)


def test_download_rejects_arbitrary_asset(monkeypatch):
    opener = Mock()
    monkeypatch.setattr(install, 'build_opener', opener)
    for url in ['https://evil.example/file', install.RELEASE_BASE + '/v1.0.3/evil.sh',
                install.RELEASE_BASE + '/latest/SHA256SUMS']:
        with pytest.raises(install.InstallError):
            install.download(url, 100)
    opener.assert_not_called()


@pytest.mark.parametrize('systemd', [False])
def test_linux_prerequisite_fails_before_changes(monkeypatch, systemd):
    monkeypatch.setattr(install, 'detect_platform', lambda: 'linux-x86_64')
    original = Path.is_dir
    monkeypatch.setattr(Path, 'is_dir', lambda path: systemd if str(path) == '/run/systemd/system' else original(path))
    network, deployment = Mock(), Mock()
    monkeypatch.setattr(install, 'download', network)
    monkeypatch.setattr(install, 'deploy_bundle', deployment)
    with pytest.raises(install.InstallError, match='administrator-managed' if systemd else 'persistent'):
        install.run_install(Mock())
    network.assert_not_called()
    deployment.assert_not_called()


def test_layout_matches_committed_release_contract():
    import runpy
    contract = runpy.run_path(Path(__file__).resolve().parents[1] / 'tools/release_daemon.py')
    assert install.PLATFORMS == contract['PLATFORMS']
    for target in install.PLATFORMS:
        assert install.bundle_layout(target) == contract['layout'](target)
        assert install.release_assets('1.0.3', target)[0] == contract['archive_name']('1.0.3', target)


def runtime_fixture():
    import json
    data = io.BytesIO()
    with tarfile.open(fileobj=data, mode='w') as tar:
        for name in ('.venv', '.venv/bin', '.venv/bin/python', '.venv/pyvenv.cfg', 'python', 'runtime.json'):
            item = tarfile.TarInfo(name)
            item.mode = 0o755
            if name in ('.venv', '.venv/bin', 'python'):
                item.type = tarfile.DIRTYPE
                tar.addfile(item)
            else:
                value = json.dumps({'format': 1, 'version': '1.0.3', 'prefix': '/opt/omneum'}).encode() if name == 'runtime.json' else b'fixture'
                item.size = len(value)
                tar.addfile(item, io.BytesIO(value))
    return gzip.compress(data.getvalue(), mtime=0)

@pytest.mark.parametrize('interactive,approved', [(False, True), (True, True), (True, False)])
def test_sudo_command_authorization_and_prompt(monkeypatch, tmp_path, interactive, approved):
    monkeypatch.setattr(install.os, 'getuid', lambda: 501)
    results = [subprocess.CompletedProcess([], int(interactive))]
    if interactive:
        results.append(subprocess.CompletedProcess([], int(not approved)))
    if approved:
        results.append(subprocess.CompletedProcess([], 0, '', ''))
    run = Mock(side_effect=results)
    monkeypatch.setattr(install.subprocess, 'run', run)
    if approved:
        install.deploy_bundle(tmp_path, 'macos-aarch64')
        assert run.call_args.args[0][:3] == ['/usr/bin/sudo', '-n', '--']
    else:
        with pytest.raises(install.InstallError, match='Administrator authorization failed'):
            install.deploy_bundle(tmp_path, 'macos-aarch64')
        assert run.call_count == 2
    assert run.call_args_list[0].args[0] == ['/usr/bin/sudo', '-n', '--', '/usr/bin/true']
    if interactive:
        args, kwargs = run.call_args_list[1]
        assert args[0] == ['/usr/bin/sudo', '-v']
        assert not kwargs.get('capture_output')


@pytest.mark.parametrize('target', ['linux-x86_64', 'macos-aarch64', 'macos-x86_64'])
def test_install_automatically_creates_private_user_graph(monkeypatch, target):
    from omneum.paths import get_context_db_path
    import sqlite3
    monkeypatch.setattr(install, 'detect_platform', lambda: target)
    monkeypatch.setattr(install.os, 'geteuid', lambda: 501)
    monkeypatch.setattr(install, 'install_release', Mock())
    monkeypatch.setattr(install, 'installer_command', Mock())
    monkeypatch.setattr(install, 'verify_managed_connection', Mock())
    monkeypatch.setattr(install, 'finish_install', Mock())
    for name in ('OMNEUM_DAEMON_SOCKET', 'OMNEUM_DAEMON_UID'):
        monkeypatch.delenv(name, raising=False)
    path = get_context_db_path()
    assert not path.exists()
    install.run_install(Mock())
    assert path.is_file() and path.stat().st_mode & 0o777 == 0o600
    assert path.parent.stat().st_mode & 0o777 == 0o700
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT version FROM schema_migrations ORDER BY version').fetchall() == [(1,), (2,), (3,)]
        assert db.execute('SELECT count(*) FROM evaluation_runs').fetchone() == (0,)
    install.run_install(Mock())
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT count(*) FROM evaluation_runs').fetchone() == (0,)
