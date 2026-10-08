"""Linux installation and runtime checks use synthetic bundles; never network or sudo."""
from contextlib import asynccontextmanager
import gzip
import importlib.util
import io
import json
import os
from pathlib import Path
import tarfile
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from omneum import installation, proxy, runtime_bundle
from test_install import archive, manifest, runtime_fixture

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('linux_installer', ROOT / 'deploy/install-linux.py')
root_install = importlib.util.module_from_spec(spec)
spec.loader.exec_module(root_install)


@pytest.mark.parametrize('connection_fails', [False, True])
def test_linux_cli_end_to_end(monkeypatch, connection_fails):
    from omneum.cli import app
    from typer.testing import CliRunner
    monkeypatch.setattr(installation, 'detect_platform', lambda: 'linux-x86_64')
    monkeypatch.setattr(installation.os, 'geteuid', lambda: 1000)
    monkeypatch.setattr(installation.Path, 'is_dir', lambda self: True)
    monkeypatch.delenv('OMNEUM_DAEMON_UID', raising=False)
    monkeypatch.delenv('OMNEUM_DAEMON_SOCKET', raising=False)
    monkeypatch.setattr(installation, 'package_version', lambda name: '1.0.3')
    data = archive('linux-x86_64')
    monkeypatch.setattr(installation, 'download', Mock(side_effect=[manifest(data), data]))
    deploy, verify = Mock(), Mock()
    monkeypatch.setattr(installation, 'deploy_bundle', deploy)
    monkeypatch.setattr(installation, 'verify_managed_connection', verify)
    if connection_fails:
        verify.side_effect = ValueError('connection failed')
    result = CliRunner().invoke(app, ['install'])
    if connection_fails:
        assert result.exit_code == 1
        assert 'Omneum is ready.' not in result.output
    else:
        assert result.exit_code == 0, result.output
        assert result.output.endswith('Verifying connection...\nOmneum is ready.\n')
    deploy.assert_called_once()
    verify.assert_called_once()
    assert not deploy.call_args.args[0].parent.exists()


def test_linux_escalates_system_python_only(monkeypatch, tmp_path):
    monkeypatch.setattr(installation.os, 'getuid', lambda: 1000)
    monkeypatch.setattr(installation.Path, 'is_dir', lambda self: True)
    monkeypatch.setattr(installation.Path, 'is_file', lambda self: True)
    monkeypatch.setattr(installation, 'package_version', lambda name: '1.0.3')
    run = Mock(return_value=SimpleNamespace(returncode=0))
    monkeypatch.setattr(installation.subprocess, 'run', run)
    installation.deploy_bundle(tmp_path, 'linux-x86_64')
    assert run.call_args.args[0] == ['/usr/bin/sudo', '-n', '--', '/usr/bin/python3', '-I', '-B',
        str(tmp_path / 'install-linux.py'), str(tmp_path), '1000', '1.0.3']


@pytest.mark.parametrize('failure', [None, 'runtime', 'daemon', 'server', 'frontend'])
def test_privileged_stack_order_and_failures(monkeypatch, tmp_path, failure):
    calls = []
    def operation(name):
        def invoke(*args):
            calls.append(name)
            if name == failure:
                raise ValueError('failure')
        return invoke
    for function, stage in [('provision_runtime', 'runtime'), ('run', 'daemon'),
                            ('initialize_and_install_server', 'server'), ('grant_frontend', 'frontend')]:
        monkeypatch.setattr(root_install, function, operation(stage))
    if failure:
        with pytest.raises(ValueError):
            root_install.install_stack(tmp_path, '1.0.3', Mock())
        assert calls == ['runtime', 'daemon', 'server', 'frontend'][:calls.index(failure)+1]
    else:
        root_install.install_stack(tmp_path, '1.0.3', Mock())
        assert calls == ['runtime', 'daemon', 'server', 'frontend']


def test_authorized_init_uses_managed_runtime_and_existing_installer(monkeypatch, tmp_path):
    run = Mock()
    monkeypatch.setattr(root_install, 'run', run)
    monkeypatch.setattr(root_install.Path, 'exists', lambda path: False)
    validator = Mock()
    monkeypatch.setattr(root_install, 'load_module', Mock(return_value=validator))
    root_install.initialize_and_install_server(tmp_path, '1.0.3')
    commands = [call.args for call in run.call_args_list]
    validator.runtime.assert_called_once_with()
    validator.unprivileged_python.assert_called_once()
    assert commands[0][:5] == ('/usr/sbin/runuser', '-u', 'omneum-mcp', '--', '/usr/bin/env')
    assert '/opt/omneum/.venv/bin/python' in commands[0]
    assert commands[0][-5:] == ('-I', '-B', '-m', 'omneum.cli', 'init')
    assert commands[1][0:2] == ('/bin/sh', str(tmp_path / 'install-server.sh'))


def test_frontend_grants_only_public_group(monkeypatch):
    monkeypatch.setattr(root_install.os, 'getgrouplist', lambda *args: [1000])
    monkeypatch.setattr(root_install.grp, 'getgrnam', lambda name: SimpleNamespace(gr_gid=2000 if name == 'omneum-ipc' else 2001))
    run = Mock()
    monkeypatch.setattr(root_install, 'run', run)
    root_install.grant_frontend(SimpleNamespace(pw_name='alice', pw_gid=1000))
    run.assert_called_once_with('/usr/sbin/usermod', '-a', '-G', 'omneum-client', 'alice')
    monkeypatch.setattr(root_install.os, 'getgrouplist', lambda *args: [1000, 2000])
    with pytest.raises(ValueError, match='protected daemon'):
        root_install.grant_frontend(SimpleNamespace(pw_name='alice', pw_gid=1000))


def test_snapshot_rejects_symlink(tmp_path, monkeypatch):
    source, destination = tmp_path / 'source', tmp_path / 'destination'
    source.mkdir(); destination.mkdir()
    (source / 'omneumd').symlink_to('/etc/passwd')
    with pytest.raises(OSError):
        root_install.snapshot(source, destination, os.getuid())
    assert list(destination.iterdir()) == []


def test_runtime_extract_and_version(tmp_path):
    runtime_bundle.unpack(io.BytesIO(runtime_fixture()), tmp_path / 'runtime', '1.0.3')
    assert (tmp_path / 'runtime/.venv/bin/python').is_file()
    with pytest.raises(ValueError, match='version mismatch'):
        runtime_bundle.unpack(io.BytesIO(runtime_fixture()), version='1.0.4')


@pytest.mark.parametrize('name,kind', [('../escape', tarfile.REGTYPE), ('/escape', tarfile.REGTYPE),
    ('.venv/../../escape', tarfile.REGTYPE), ('other', tarfile.REGTYPE),
    ('.venv', tarfile.SYMTYPE), ('.venv', tarfile.LNKTYPE), ('.venv', tarfile.FIFOTYPE)])
def test_malicious_runtime(name, kind):
    data = io.BytesIO()
    with tarfile.open(fileobj=data, mode='w') as tar:
        item = tarfile.TarInfo(name); item.type = kind; item.mode = 0o755
        tar.addfile(item)
    with pytest.raises(ValueError):
        runtime_bundle.unpack(io.BytesIO(gzip.compress(data.getvalue())), version='1.0.3')


def test_runtime_limits(monkeypatch):
    monkeypatch.setattr(runtime_bundle, 'MAX_RUNTIME', 100)
    with pytest.raises(ValueError, match='limit'):
        runtime_bundle.unpack(io.BytesIO(runtime_fixture()), version='1.0.3')


@pytest.mark.parametrize('active,member', [(True, True), (False, True), (False, False)])
def test_proxy_group_refresh(monkeypatch, active, member):
    import grp, pwd
    monkeypatch.setattr(proxy.Path, 'is_file', lambda self: True)
    monkeypatch.setattr(grp, 'getgrnam', lambda name: SimpleNamespace(gr_gid=54321, gr_mem=['alice'] if member else []))
    monkeypatch.setattr(pwd, 'getpwuid', lambda uid: SimpleNamespace(pw_name='alice'))
    monkeypatch.setattr(os, 'getgroups', lambda: [54321] if active else [])
    if active:
        assert proxy.linux_command() == [proxy.PROXY]
    elif member:
        assert proxy.linux_command() == ['/usr/bin/sg', 'omneum-client', '-c', 'exec /usr/local/bin/omneum-server']
    else:
        with pytest.raises(RuntimeError, match='not authorized'):
            proxy.linux_command()


def test_end_user_probe_uses_proxy_and_sdk(monkeypatch):
    import omneum.client as client
    monkeypatch.setattr(proxy, 'linux_command', lambda: [proxy.PROXY])
    monkeypatch.setattr(client.OmneumClientConfig, 'from_local_deployment', Mock(return_value='config'))
    link = AsyncMock()
    @asynccontextmanager
    async def open_client(config, server):
        assert config == 'config' and server.command == proxy.PROXY
        yield SimpleNamespace(link_claim=link)
    monkeypatch.setattr(client, 'open_stdio_client', open_client)
    installation.verify_managed_connection()
    link.assert_awaited_once_with('service', 'omneum', 'connection', 'verified')
