"""Installer trust checks without requiring a root-owned Linux filesystem."""
from pathlib import Path
import runpy
import stat
import subprocess
from types import SimpleNamespace
from unittest.mock import Mock

import pytest


trusted = runpy.run_path(Path(__file__).resolve().parents[1]/'deploy/install_server.py')['trusted']
verify = trusted.__globals__['unprivileged_python']


@pytest.fixture
def verification(monkeypatch):
    scope = verify.__globals__
    monkeypatch.setattr(scope['sys'], 'platform', 'linux')
    monkeypatch.setattr(scope['os'], 'geteuid', lambda: 0)
    monkeypatch.setattr(scope['pwd'], 'getpwnam', lambda name: SimpleNamespace(pw_uid=1234, pw_gid=1235))
    monkeypatch.setitem(scope, 'trusted', Mock())
    monkeypatch.setattr(Path, 'resolve', lambda self, **kwargs: self)
    monkeypatch.setattr(Path, 'stat', lambda self: SimpleNamespace(st_mode=stat.S_IFREG | 0o755))
    call = Mock(return_value=SimpleNamespace(stdout='[]'))
    monkeypatch.setattr(scope['subprocess'], 'run', call)
    return scope, call


def test_verification_drops_credentials_before_interpreter(verification):
    _, call = verification
    verify('-c', 'import omneum, omneum_oprf')
    args, options = call.call_args
    assert args[0] == [
        '/usr/bin/setpriv', '--reuid', '1234', '--regid', '1235',
        '--clear-groups', '--no-new-privs', '--bounding-set=-all',
        '--inh-caps=-all', '--ambient-caps=-all', '--',
        '/opt/omneum/.venv/bin/python', '-I', '-B', '-c', 'import omneum, omneum_oprf',
    ]
    assert options['env'] == {'PATH': '/usr/bin:/bin', 'HOME': '/nonexistent'}
    assert options['close_fds'] and options['check']
    assert options['stdin'] == subprocess.DEVNULL


def test_missing_verification_identity_fails_closed(verification, monkeypatch):
    scope, call = verification
    def missing(name):
        assert name == 'omneum-mcp'
        raise KeyError(name)
    monkeypatch.setattr(scope['pwd'], 'getpwnam', missing)
    with pytest.raises(KeyError):
        verify('-c', 'import omneum')
    call.assert_not_called()


@pytest.mark.parametrize('failure', [OSError('exec failed'), subprocess.CalledProcessError(1, 'setpriv')])
def test_transition_failure_never_retries_as_root(verification, failure):
    _, call = verification
    call.side_effect = failure
    with pytest.raises(type(failure)):
        verify('-c', 'import omneum')
    assert call.call_count == 1


def test_filesystem_inspection_never_executes_python(verification, monkeypatch):
    scope, call = verification
    monkeypatch.setattr(scope['os'], 'walk', lambda path: [])
    scope['inspect_runtime']()
    call.assert_not_called()


@pytest.mark.parametrize('parent', ['/usr/local/bin', '/usr/local', '/usr', '/'])
@pytest.mark.parametrize('uid, mode', [
    (1000, stat.S_IFDIR | 0o755),
    (0, stat.S_IFDIR | 0o775),
    (0, stat.S_IFDIR | 0o757),
    (0, stat.S_IFDIR | 0o777),
    (0, stat.S_IFLNK | 0o755),
])
def test_proxy_rejects_untrusted_parent(monkeypatch, parent, uid, mode):
    def metadata(path):
        if path == Path(parent):
            return SimpleNamespace(st_uid=uid, st_mode=mode)
        return SimpleNamespace(st_uid=0, st_mode=stat.S_IFDIR | 0o755)
    monkeypatch.setattr(Path, 'lstat', metadata)
    with pytest.raises(ValueError, match=f'untrusted installation path: {parent}$'):
        trusted(Path('/usr/local/bin/omneum-server'))


def test_proxy_accepts_trusted_parents(monkeypatch):
    monkeypatch.setattr(Path, 'lstat', lambda path: SimpleNamespace(
        st_uid=0, st_mode=(stat.S_IFREG if path.name == 'omneum-server' else stat.S_IFDIR) | 0o755))
    trusted(Path('/usr/local/bin/omneum-server'))
