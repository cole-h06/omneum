"""Platform mount checks reject known remote storage without changing paths."""
import os
from pathlib import Path, PureWindowsPath
import sys

import pytest

from omneum.storage import SQLiteStorage
from omneum.storage import filesystem


def mountinfo(monkeypatch, rows):
    read = Path.read_text
    def mounted(self, *args, **kwargs):
        if self == Path('/proc/self/mountinfo'):
            return rows
        return read(self, *args, **kwargs)
    monkeypatch.setattr(Path, 'read_text', mounted)


@pytest.mark.skipif(os.name != 'posix', reason='POSIX mount paths')
@pytest.mark.parametrize('kind', ['nfs', 'nfs4', 'cifs', 'fuse.sshfs'])
def test_linux_remote_mount_rejected_before_database_creation(tmp_path, monkeypatch, kind):
    monkeypatch.setattr(filesystem.sys, 'platform', 'linux')
    directory = tmp_path / 'graph'
    directory.mkdir(mode=0o700)
    mountinfo(monkeypatch, f'1 0 0:1 / / rw - ext4 /dev/root rw\n2 1 0:2 / {directory} rw - {kind} remote rw\n')
    with pytest.raises(ValueError, match='network mounts'):
        with SQLiteStorage(directory / 'context.db').transaction():
            pass
    assert not (directory / 'context.db').exists()


@pytest.mark.skipif(os.name != 'posix', reason='POSIX mount paths')
def test_linux_nested_local_mount_and_mountpoint_escaping(monkeypatch):
    mountinfo(monkeypatch, '1 0 0:1 / / rw - ext4 /dev/root rw\n'
        '2 1 0:2 / /data rw shared:3 - nfs remote rw\n'
        '3 2 0:3 / /data/local\\040graph rw - ext4 /dev/local rw\n')
    assert filesystem._linux_filesystem_type(Path('/data/remote/graph')) == 'nfs'
    assert filesystem._linux_filesystem_type(Path('/data/local graph/context.db')) == 'ext4'
    assert filesystem._linux_filesystem_type(Path('/data-other/graph')) == 'ext4'


@pytest.mark.skipif(os.name != 'posix', reason='POSIX mount paths')
def test_unknown_mount_locality(monkeypatch):
    read = Path.read_text
    def unavailable(self, *args, **kwargs):
        if self == Path('/proc/self/mountinfo'):
            raise PermissionError('restricted proc')
        return read(self, *args, **kwargs)
    monkeypatch.setattr(Path, 'read_text', unavailable)
    assert filesystem._linux_filesystem_type(Path('/data/graph')) is None


@pytest.mark.parametrize('platform,helper,result,path', [
    ('darwin', '_darwin_is_local', False, Path('/Volumes/shared/graph')),
    ('win32', '_windows_drive_type', 4, PureWindowsPath('Z:/graph')),
])
def test_platform_remote_volume_rejected(monkeypatch, platform, helper, result, path):
    monkeypatch.setattr(filesystem.sys, 'platform', platform)
    monkeypatch.setattr(filesystem, helper, lambda argument: result)
    with pytest.raises(ValueError, match='network mounts'):
        filesystem.require_local_filesystem(path)


@pytest.mark.skipif(sys.platform != 'darwin', reason='native macOS mount API')
def test_native_macos_local_volume(tmp_path):
    assert filesystem._darwin_is_local(tmp_path)
