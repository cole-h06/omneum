"""Initial pin discovery waits for transport readiness, never authentication failures."""

import os
from pathlib import Path
import socket
import tempfile
import time
from threading import Thread
from unittest.mock import Mock

import pytest

from omneum import initialization
from omneum.daemon import DaemonServerContext, DaemonTransportError, DaemonUnavailableError
from omneum.deployment import load_config
from omneum.keys import encode_public_key
from omneum.oprf import OPRFProtocolError


PUBLIC_KEY = bytes.fromhex('e2f2ae0a6abc4e71a884a961c500515f58e30b6aa582dd8db6a65945e08d2d76')


def test_initialization_waits_for_stale_socket(monkeypatch):
    # launchctl kickstart can leave a socket visible before the replacement is
    # listening. Use a real refused connection, then an authenticated OS peer.
    with tempfile.TemporaryDirectory(prefix='oi-') as directory:
        root = Path(directory).resolve()
        endpoint = root / 'eval.sock'
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as stale:
            stale.bind(str(endpoint))
        assert endpoint.is_socket()
        monkeypatch.setenv('OMNEUM_CONFIG_DIR', str(root / 'config'))
        monkeypatch.setenv('OMNEUM_DAEMON_SOCKET', str(endpoint))
        monkeypatch.setenv('OMNEUM_DAEMON_UID', str(os.getuid()))
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as listener:
            listener.settimeout(3)
            requests = []

            def serve():
                with listener.accept()[0] as stream:
                    stream.settimeout(3)
                    requests.append(stream.recv(4))
                    stream.sendall(b'\x01\x00\x00\x20' + PUBLIC_KEY)

            worker = Thread(target=serve)

            def ready(delay):
                assert delay == .25
                assert not (root / 'config/config.toml').exists()
                endpoint.unlink()
                listener.bind(str(endpoint))
                listener.listen()
                worker.start()

            wait = Mock(side_effect=ready)
            monkeypatch.setattr(time, 'sleep', wait)
            try:
                config = initialization.initialize()
            finally:
                if worker.ident is not None:
                    worker.join(4)
            assert not worker.is_alive()
            wait.assert_called_once_with(.25)
            assert requests == [b'\x01\x01\x00\x00']
            assert load_config() == config
            assert config.voprf_public_key == encode_public_key(PUBLIC_KEY)


@pytest.mark.parametrize('failure', [
    DaemonUnavailableError('identity verification failed'),
    OPRFProtocolError('malformed response'),
    TimeoutError('uncertain request'),
    ValueError('invalid public key'),
])
def test_initialization_does_not_retry_security_or_uncertain_failures(monkeypatch, tmp_path, failure):
    monkeypatch.setenv('OMNEUM_CONFIG_DIR', str(tmp_path / 'config'))
    fetch, wait = Mock(side_effect=failure), Mock()
    monkeypatch.setattr(initialization, 'get_daemon_uid', lambda: os.getuid())
    monkeypatch.setattr(DaemonServerContext, 'fetch_public_key', fetch)
    monkeypatch.setattr(time, 'sleep', wait)
    with pytest.raises(initialization.InitializationError) as result:
        initialization.initialize()
    assert result.value.__cause__ is failure
    fetch.assert_called_once()
    wait.assert_not_called()
    assert not (tmp_path / 'config/config.toml').exists()


def test_initialization_readiness_is_bounded(monkeypatch, tmp_path):
    monkeypatch.setenv('OMNEUM_CONFIG_DIR', str(tmp_path / 'config'))
    failure = DaemonTransportError('not ready')
    fetch, wait = Mock(side_effect=failure), Mock()
    monkeypatch.setattr(initialization, 'get_daemon_uid', lambda: os.getuid())
    monkeypatch.setattr(DaemonServerContext, 'fetch_public_key', fetch)
    monkeypatch.setattr(time, 'sleep', wait)
    with pytest.raises(initialization.InitializationError) as result:
        initialization.initialize()
    assert result.value.__cause__ is failure
    assert fetch.call_count == 21
    assert wait.call_count == 20
    assert not (tmp_path / 'config/config.toml').exists()


def test_existing_pin_is_never_replaced_or_contacted(monkeypatch, tmp_path):
    monkeypatch.setenv('OMNEUM_CONFIG_DIR', str(tmp_path))
    pin = tmp_path / 'config.toml'
    pin.write_text('existing pin')
    fetch = Mock(side_effect=AssertionError('must not contact daemon'))
    monkeypatch.setattr(DaemonServerContext, 'fetch_public_key', fetch)
    assert initialization.initialize() is None
    assert pin.read_text() == 'existing pin'
    fetch.assert_not_called()
