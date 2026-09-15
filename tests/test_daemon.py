"""Daemon functional tests. Cross-UID tests live in security/linux_isolation.py."""

import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import socket
import struct
import subprocess
import sys
import time

import pytest

from daemon_support import BINARY, FixtureDaemon
from omneum.daemon import (
    DaemonBusyError,
    DaemonKeyMismatchError,
    DaemonServerContext,
    DaemonUnavailableError,
)
from omneum.oprf import OPRFProtocolError, VOPRFClient


KEY = b"\x01" + b"\0" * 31


@pytest.fixture
def daemon():
    d = FixtureDaemon(KEY)
    yield d
    d.close()


def connect(d):
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(2)
    s.connect(str(d.socket))
    return s


def response(s):
    header = DaemonServerContext._read(s, 4, time.monotonic() + 2)
    version, status, length = struct.unpack("!BBH", header)
    payload = DaemonServerContext._read(s, length, time.monotonic() + 2)
    return version, status, payload


def response_from_public(d):
    with connect(d) as s:
        s.sendall(b"\x01\x01\0\0")
        return response(s)[2]


@pytest.mark.parametrize(
    "frame",
    [
        b"\x02\x01\0\0",
        b"\x01\xff\0\0",
        b"\x01\x01\0\x01",
        b"\x01\x02\0\x1f",
        b"\x01\x02\xff\xff",
    ],
)
def test_bad_header(daemon, frame):
    with connect(daemon) as s:
        s.sendall(frame)
        assert response(s) == (1, 1, b"")
        assert s.recv(1) == b""


@pytest.mark.parametrize("frame", [b"\x01", b"\x01\x02\0\x20x"])
def test_partial_frame_timeout(daemon, frame):
    with connect(daemon) as s:
        s.sendall(frame)
        assert s.recv(1) == b""


def test_invalid_element_recovery(daemon):
    with connect(daemon) as s:
        s.sendall(b"\x01\x02\0\x20" + b"\0" * 32)
        assert response(s) == (1, 2, b"")

        s.sendall(b"\x01\x01\0\0")
        assert response(s) == (1, 0, daemon.public_key)


def test_truncated_frame(daemon):
    with connect(daemon) as s:
        s.sendall(b"\x01\x02\0\x20x")
        s.shutdown(socket.SHUT_WR)
        assert s.recv(1) == b""


def test_wrong_uid(daemon):
    with pytest.raises(DaemonUnavailableError):
        DaemonServerContext(
            daemon.socket,
            os.getuid() + 1,
            daemon.public_key,
        )


def test_wrong_public_key(daemon):
    other = FixtureDaemon(b"\x02" + b"\0" * 31)
    try:
        with pytest.raises(DaemonKeyMismatchError):
            DaemonServerContext(
                daemon.socket,
                os.getuid(),
                other.public_key,
            )
    finally:
        other.close()


def test_restart(daemon):
    client = VOPRFClient(daemon.public_key)
    blinded = client.blind(b"restart")
    before = daemon.context.evaluate(blinded.blinded_element)

    daemon.process.kill()
    daemon.process.wait(timeout=3)

    with pytest.raises(DaemonUnavailableError):
        daemon.context.evaluate(blinded.blinded_element)

    daemon.process = subprocess.Popen(
        daemon.command,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    try:
        for _ in range(200):
            try:
                after = daemon.context.evaluate(blinded.blinded_element)
                break
            except DaemonUnavailableError:
                time.sleep(0.01)
        else:
            pytest.fail("daemon restart failed")

        assert before.evaluated_element == after.evaluated_element

        assert client.finalize(
            input_data=b"restart",
            client_state=blinded.client_state,
            evaluation=before,
        ) == client.finalize(
            input_data=b"restart",
            client_state=blinded.client_state,
            evaluation=after,
        )
    finally:
        daemon.process.terminate()
        daemon.process.wait(timeout=3)

    assert not daemon.socket.exists()


def test_active_socket_collision(daemon):
    result = subprocess.run(
        daemon.command,
        capture_output=True,
        timeout=3,
    )

    assert result.returncode != 0
    assert response_from_public(daemon) == daemon.public_key


def test_concurrent_evaluations(daemon):
    client = VOPRFClient(daemon.public_key)

    def run(i):
        value = str(i).encode()
        blinded = client.blind(value)
        evaluated = daemon.context.evaluate(blinded.blinded_element)

        return client.finalize(
            input_data=value,
            client_state=blinded.client_state,
            evaluation=evaluated,
        )

    with ThreadPoolExecutor(max_workers=8) as executor:
        outputs = list(executor.map(run, range(40)))

    assert len(set(outputs)) == 40


def test_global_rate_limit():
    d = FixtureDaemon(KEY, options=("--rate", "1", "--burst", "3"))

    try:
        # Fixture discovery + pin handshake consume two. Remaining token is shared.
        assert response_from_public(d) == d.public_key

        with connect(d) as s:
            s.sendall(b"\x01\x01\0\0")
            assert response(s) == (1, 3, b"")

        time.sleep(1.05)
        assert response_from_public(d) == d.public_key
    finally:
        d.close()


def test_connection_limit():
    d = FixtureDaemon(
        KEY,
        options=("--connections", "2", "--idle-ms", "150"),
    )
    sockets = []

    try:
        time.sleep(0.02)
        sockets = [connect(d), connect(d)]
        time.sleep(0.04)

        with connect(d) as s:
            assert s.recv(1) == b""

        time.sleep(0.2)
        assert response_from_public(d) == d.public_key
    finally:
        for s in sockets:
            s.close()
        d.close()


@pytest.mark.parametrize(
    "mutation",
    [
        "symlink",
        "parent_symlink",
        "fifo",
        "directory",
        "short",
        "long",
        "zero",
        "noncanonical",
        "mode",
        "hardlink",
    ],
)
def test_key_rejections(daemon, mutation):
    daemon.process.terminate()
    daemon.process.wait(timeout=3)

    key = daemon.key_file

    if mutation == "symlink":
        key.rename(key.with_suffix(".other"))
        key.symlink_to(key.with_suffix(".other"))
    elif mutation == "parent_symlink":
        daemon.key_dir.rename(daemon.root / "other")
        daemon.key_dir.symlink_to(daemon.root / "other")
    elif mutation == "fifo":
        key.unlink()
        os.mkfifo(key, 0o600)
    elif mutation == "directory":
        key.unlink()
        key.mkdir()
    elif mutation == "mode":
        key.chmod(0o640)
    elif mutation == "hardlink":
        os.link(key, daemon.root / "link")
    else:
        key.write_bytes(
            {
                "short": b"x" * 31,
                "long": b"x" * 33,
                "zero": b"\0" * 32,
                "noncanonical": b"\xff" * 32,
            }[mutation]
        )

    result = subprocess.run(
        daemon.command,
        capture_output=True,
        timeout=3,
    )

    assert result.returncode != 0
    assert result.stderr == b"omneumd: startup or service failure\n"



def test_help_without_install():
    result = subprocess.run(
        [str(BINARY), "--help"],
        capture_output=True,
        timeout=3,
    )

    assert result.returncode == 0
    assert result.stdout == b"Usage: omneumd <provision|serve> [options]\n"
    assert result.stderr == b""


def test_provision(daemon):
    daemon.process.terminate()
    daemon.process.wait(timeout=3)
    daemon.key_file.unlink()

    command = [
        str(BINARY),
        "provision",
        "--test-mode",
        "--key-dir",
        str(daemon.key_dir),
    ]

    first = subprocess.run(
        command,
        capture_output=True,
        timeout=3,
    )

    assert first.returncode == 0
    assert len(bytes.fromhex(first.stdout.decode().strip())) == 32
    assert len(daemon.key_file.read_bytes()) == 32
    assert daemon.key_file.stat().st_mode & 0o777 == 0o600

    key = daemon.key_file.read_bytes()

    second = subprocess.run(
        command,
        capture_output=True,
        timeout=3,
    )

    assert second.returncode != 0
    assert second.stdout == b""
    assert daemon.key_file.read_bytes() == key


@pytest.mark.skipif(sys.platform != "darwin", reason="Darwin extended ACL")
def test_macos_extended_acl_is_rejected(daemon):
    daemon.process.terminate()
    daemon.process.wait(timeout=3)

    subprocess.run(
        ["chmod", "+a", "everyone allow read", str(daemon.key_file)],
        check=True,
    )

    result = subprocess.run(
        daemon.command,
        capture_output=True,
        timeout=3,
    )

    assert result.returncode != 0


@pytest.mark.parametrize(
    "header",
    [
        b"\x02\0\0\x20",
        b"\x01\0\xff\xff",
        b"\x01\x05\0\0",
        b"\x01\x03\0\x01",
    ],
)
def test_response_lengths(daemon, header):
    # Use a socket pair to test parsing independently of peer authentication.
    a, b = socket.socketpair()

    try:
        b.sendall(header)

        with pytest.raises(OPRFProtocolError):
            DaemonServerContext._request(
                a,
                1,
                b"",
                32,
                time.monotonic() + 0.2,
            )
    finally:
        a.close()
        b.close()


def test_client_total_response_deadline():
    a, b = socket.socketpair()

    try:
        b.sendall(b"\x01")

        with pytest.raises(TimeoutError):
            DaemonServerContext._request(
                a,
                1,
                b"",
                32,
                time.monotonic() + 0.05,
            )
    finally:
        a.close()
        b.close()


def test_default_limits():
    d = FixtureDaemon(
        KEY,
        options=("--rate", "128", "--burst", "64"),
    )

    try:
        client = VOPRFClient(d.public_key)

        for n in range(20):
            value = f"enterprise-source-{n}".encode()
            blinded = client.blind(value)
            evaluated = d.context.evaluate(blinded.blinded_element)

            assert (
                len(
                    client.finalize(
                        input_data=value,
                        client_state=blinded.client_state,
                        evaluation=evaluated,
                    )
                )
                == 64
            )
    finally:
        d.close()


def test_init_config(daemon, tmp_path, monkeypatch):
    import tomllib

    from typer.testing import CliRunner

    from omneum.cli import app

    monkeypatch.setenv("OMNEUM_CONFIG_DIR", str(tmp_path))
    monkeypatch.setenv("OMNEUM_DAEMON_SOCKET", str(daemon.socket))
    monkeypatch.setenv("OMNEUM_DAEMON_UID", str(os.getuid()))

    result = CliRunner().invoke(
        app,
        ["init", "--public-key-hex", daemon.public_key.hex()],
    )

    assert result.exit_code == 0, result.output

    config_file = tmp_path / "config.toml"
    config = tomllib.loads(config_file.read_text())

    assert set(config) == {
        "deployment_id",
        "voprf_key_version",
        "voprf_public_key",
    }
    assert set(tmp_path.iterdir()) == {config_file}

    saved = config_file.read_bytes()

    result = CliRunner().invoke(
        app,
        ["init", "--public-key-hex", "ff" * 32],
    )

    assert result.exit_code == 0
    assert config_file.read_bytes() == saved


def test_init_without_daemon(daemon, tmp_path, monkeypatch):
    from typer.testing import CliRunner

    from omneum.cli import app

    monkeypatch.setenv("OMNEUM_CONFIG_DIR", str(tmp_path))
    monkeypatch.setenv(
        "OMNEUM_DAEMON_SOCKET",
        str(tmp_path / "missing.sock"),
    )
    monkeypatch.setenv("OMNEUM_DAEMON_UID", str(os.getuid()))

    result = CliRunner().invoke(
        app,
        ["init", "--public-key-hex", daemon.public_key.hex()],
    )

    assert result.exit_code == 1
    assert not (tmp_path / "config.toml").exists()
    assert not (tmp_path / "keys").exists()


def test_init_public_key(daemon, tmp_path, monkeypatch):
    import tomllib

    from typer.testing import CliRunner

    from omneum.base64url import encode_unpadded
    from omneum.cli import app

    monkeypatch.setenv("OMNEUM_CONFIG_DIR", str(tmp_path))
    monkeypatch.setenv("OMNEUM_DAEMON_SOCKET", str(daemon.socket))
    monkeypatch.setenv("OMNEUM_DAEMON_UID", str(os.getuid()))

    result = CliRunner().invoke(app, ["init"])

    assert result.exit_code == 0, result.output

    config_file = tmp_path / "config.toml"
    config = tomllib.loads(config_file.read_text())

    assert config["voprf_public_key"] == encode_unpadded(
        daemon.public_key,
        expected_length=32,
    )

    saved = config_file.read_bytes()

    monkeypatch.setenv("OMNEUM_DAEMON_UID", str(os.getuid() + 1))

    assert CliRunner().invoke(app, ["init"]).exit_code == 0
    assert config_file.read_bytes() == saved


def test_init_peer_uid(daemon, tmp_path, monkeypatch):
    from typer.testing import CliRunner

    from omneum.cli import app

    monkeypatch.setenv("OMNEUM_CONFIG_DIR", str(tmp_path))
    monkeypatch.setenv("OMNEUM_DAEMON_SOCKET", str(daemon.socket))
    monkeypatch.setenv("OMNEUM_DAEMON_UID", str(os.getuid() + 1))

    assert CliRunner().invoke(app, ["init"]).exit_code == 1
    assert not (tmp_path / "config.toml").exists()


def test_config_write_refuses_existing_pin(tmp_path, monkeypatch):
    from omneum.deployment import DeploymentConfig, save_config

    monkeypatch.setenv("OMNEUM_CONFIG_DIR", str(tmp_path))

    path = tmp_path / "config.toml"
    path.write_bytes(b"existing pin")

    with pytest.raises(FileExistsError):
        save_config(
            DeploymentConfig(
                "deployment",
                1,
                "replacement",
            )
        )

    assert path.read_bytes() == b"existing pin"