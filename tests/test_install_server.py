"""Installer trust checks without requiring a root-owned Linux filesystem."""
from pathlib import Path
import runpy
import stat
from types import SimpleNamespace

import pytest


trusted = runpy.run_path(Path(__file__).resolve().parents[1]/'deploy/install_server.py')['trusted']


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
