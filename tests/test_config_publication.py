"""Atomic public-key pin publication; only disposable configuration files."""
from concurrent.futures import ThreadPoolExecutor
import os
from threading import Event

import pytest

from omneum import deployment


def configuration():
    return deployment.DeploymentConfig('urn:uuid:8d96fc18-f40f-4ec7-8ae8-f3711d88b741', 1, 'public-pin')


def test_failed_flush_does_not_publish_partial_pin(tmp_path, monkeypatch):
    monkeypatch.setenv('OMNEUM_CONFIG_DIR', str(tmp_path))
    def fail(_):
        raise OSError('injected disk failure')
    monkeypatch.setattr(deployment.os, 'fsync', fail)
    with pytest.raises(OSError, match='injected'):
        deployment.save_config(configuration())
    assert list(tmp_path.iterdir()) == []


def test_unfinished_write_is_invisible_then_complete(tmp_path, monkeypatch):
    monkeypatch.setenv('OMNEUM_CONFIG_DIR', str(tmp_path))
    flushed, publish = Event(), Event()
    original = os.fsync
    def wait(fd):
        original(fd)
        flushed.set()
        assert publish.wait(5)
    monkeypatch.setattr(deployment.os, 'fsync', wait)
    with ThreadPoolExecutor(max_workers=1) as pool:
        writer = pool.submit(deployment.save_config, configuration())
        try:
            assert flushed.wait(5)
            assert not (tmp_path / 'config.toml').exists()
        finally:
            publish.set()
        writer.result()
    assert deployment.load_config() == configuration()
    assert (tmp_path / 'config.toml').stat().st_mode & 0o777 == 0o600
    assert sorted(p.name for p in tmp_path.iterdir()) == ['config.toml']


def test_concurrent_publication_has_one_winner(tmp_path, monkeypatch):
    monkeypatch.setenv('OMNEUM_CONFIG_DIR', str(tmp_path))
    def write(_):
        try:
            deployment.save_config(configuration())
            return True
        except FileExistsError:
            return False
    with ThreadPoolExecutor(max_workers=8) as pool:
        assert sum(pool.map(write, range(16))) == 1
    assert deployment.load_config() == configuration()
    assert sorted(p.name for p in tmp_path.iterdir()) == ['config.toml']


def test_existing_symlink_is_not_followed_or_replaced(tmp_path, monkeypatch):
    monkeypatch.setenv('OMNEUM_CONFIG_DIR', str(tmp_path))
    original = tmp_path / 'original'
    original.write_bytes(b'existing pin')
    (tmp_path / 'config.toml').symlink_to(original)
    with pytest.raises(FileExistsError):
        deployment.save_config(configuration())
    assert original.read_bytes() == b'existing pin'
    assert (tmp_path / 'config.toml').is_symlink()
