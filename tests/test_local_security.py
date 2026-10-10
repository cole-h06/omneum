"""Regressions for live schema tampering and mode-independent macOS ACLs."""
import os
from pathlib import Path
import sqlite3
import subprocess
import sys

import pytest

from omneum.storage import SQLiteStorage


@pytest.mark.parametrize('tamper', [
    "CREATE TRIGGER injected AFTER INSERT ON evaluation_runs BEGIN DELETE FROM sources; END",
    "CREATE TRIGGER sqliteXhidden AFTER INSERT ON evaluation_runs BEGIN DELETE FROM sources; END",
    'DROP INDEX observations_source_idx',
    'DROP VIEW assertion_observation_envelopes',
    'ALTER TABLE sources ADD COLUMN injected TEXT',
    'CREATE TABLE unexpected(secret TEXT)',
])
def test_schema_drift_rejected_with_unchanged_migration_checksums(tmp_path, tamper):
    path = tmp_path / 'context.db'
    with SQLiteStorage(path).transaction():
        pass
    with sqlite3.connect(path) as connection:
        history = connection.execute('SELECT version, checksum FROM schema_migrations').fetchall()
        # Discover the adapter-owned index without depending on its name.
        if tamper.startswith('DROP INDEX'):
            index = connection.execute("SELECT name FROM sqlite_master WHERE type='index' AND sql IS NOT NULL LIMIT 1").fetchone()[0]
            tamper = 'DROP INDEX "' + index + '"'
        connection.execute(tamper)
    with pytest.raises(ValueError, match='modified SQLite schema'):
        with SQLiteStorage(path).transaction():
            pytest.fail('tampered schema reached caller')
    with sqlite3.connect(path) as connection:
        assert connection.execute('SELECT version, checksum FROM schema_migrations').fetchall() == history


def test_sqlite_connection_distrusts_schema_and_disables_extensions(tmp_path):
    with SQLiteStorage(tmp_path / 'context.db').transaction() as connection:
        assert connection.execute('PRAGMA trusted_schema').fetchone() == (0,)
        with pytest.raises(sqlite3.OperationalError, match='not authorized'):
            connection.execute("SELECT load_extension('forbidden')")
        if hasattr(connection, 'getconfig'):
            assert connection.getconfig(sqlite3.SQLITE_DBCONFIG_DEFENSIVE)


@pytest.mark.skipif(sys.platform != 'darwin', reason='native Darwin extended ACLs')
@pytest.mark.parametrize('target', ['directory', 'ancestor', '', '-wal', '-shm', '-journal'])
def test_macos_acl_grants_rejected_before_sqlite_open(tmp_path, target, monkeypatch):
    ancestor = tmp_path / 'ancestor'
    directory = ancestor / 'graph'
    directory.mkdir(mode=0o700, parents=True)
    path = directory / 'context.db'
    victim = ancestor if target == 'ancestor' else directory if target == 'directory' else Path(str(path) + target)
    if target not in ('directory', 'ancestor'):
        victim.touch(mode=0o600)
    grant = 'everyone allow add_file' if target == 'ancestor' else 'everyone allow read'
    subprocess.run(['chmod', '+a', grant, str(victim)], check=True, capture_output=True)
    def forbidden(*args, **kwargs):
        pytest.fail('SQLite opened a path with unsafe ACL grants')
    monkeypatch.setattr(sqlite3, 'connect', forbidden)
    try:
        with pytest.raises(ValueError, match='ACL'):
            with SQLiteStorage(path).transaction():
                pass
    finally:
        subprocess.run(['chmod', '-N', str(victim)], check=True, capture_output=True)


@pytest.mark.skipif(sys.platform != 'darwin', reason='native Darwin extended ACLs')
def test_macos_deny_acl_remains_supported(tmp_path):
    subprocess.run(['chmod', '+a', 'everyone deny delete', str(tmp_path)], check=True, capture_output=True)
    try:
        with SQLiteStorage(tmp_path / 'context.db').transaction():
            pass
    finally:
        subprocess.run(['chmod', '-N', str(tmp_path)], check=True, capture_output=True)


@pytest.mark.skipif(sys.platform != 'darwin', reason='native Darwin extended ACLs')
def test_operator_credential_output_rejects_acl_directory(tmp_path):
    from omneum.network_operator import private_output
    subprocess.run(['chmod', '+a', 'everyone allow read,file_inherit,directory_inherit', str(tmp_path)],
                   check=True, capture_output=True)
    path = tmp_path / 'credential'
    try:
        with pytest.raises(ValueError, match='ACL'):
            private_output(path)
        assert not path.exists()
    finally:
        subprocess.run(['chmod', '-N', str(tmp_path)], check=True, capture_output=True)


def test_replaced_migration_ledger_is_rejected_before_execution(tmp_path):
    path = tmp_path / 'context.db'
    with SQLiteStorage(path).transaction():
        pass
    with sqlite3.connect(path) as connection:
        connection.execute('DROP TABLE schema_migrations')
        # An invocation would fail with no-such-function instead of our explicit
        # integrity error. Recursive/resource-heavy views must also never run.
        connection.execute('CREATE VIEW schema_migrations AS SELECT unexpected_function() AS version, 0 AS checksum')
    with pytest.raises(ValueError, match='modified SQLite schema'):
        with SQLiteStorage(path).transaction():
            pass
