"""Build the separately labelled test daemon; never install it as omneumd."""
import os
from pathlib import Path
import pytest
from daemon_support import FixtureDaemon, build_daemon


@pytest.fixture(scope="session", autouse=True)
def compiled_daemon():
    build_daemon()


@pytest.fixture
def example_daemon(tmp_path, monkeypatch):
    from omneum.base64url import encode_unpadded
    daemon = FixtureDaemon(b"\x01" + b"\0" * 31)
    monkeypatch.setenv("OMNEUM_CONFIG_DIR", str(tmp_path))
    monkeypatch.setenv("OMNEUM_DAEMON_SOCKET", str(daemon.socket))
    monkeypatch.setenv("OMNEUM_DAEMON_UID", str(os.getuid()))
    (tmp_path / "config.toml").write_text(
        'deployment_id = "urn:uuid:8d96fc18-f40f-4ec7-8ae8-f3711d88b741"\n'
        'voprf_key_version = 1\n'
        f'voprf_public_key = "{encode_unpadded(daemon.public_key, expected_length=32)}"\n'
    )
    yield daemon
    daemon.close()


@pytest.fixture(autouse=True)
def isolated_context_db(tmp_path, monkeypatch):
    """Default persistence in tests must never touch the real user's database."""
    monkeypatch.setattr("omneum.paths.get_context_db_path", lambda: tmp_path / "local-context" / "omneum.db")
