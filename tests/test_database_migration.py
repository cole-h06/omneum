import asyncio
from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
import sqlite3
import subprocess
import sys

import pytest

from omneum import LocalPersistenceConfig, OmneumClient, SQLiteStorage
from test_local_persistence import runtime
from test_storage_evaluation import computed


def legacy_database(runtime, tmp_path, monkeypatch):
    target = tmp_path / 'omneum.db'
    legacy = tmp_path / 'context.db'
    monkeypatch.setattr('omneum.paths.get_context_db_path', lambda: target)
    config, evaluator, observations, estimator = runtime
    client = OmneumClient(config, evaluator, local_persistence=LocalPersistenceConfig(SQLiteStorage(legacy)))
    asyncio.run(client._evaluate_context(observations, estimator=estimator))
    with SQLiteStorage(legacy).transaction() as connection:
        connection.execute('DROP TABLE execution_history')
        connection.execute('DELETE FROM schema_migrations WHERE version=4')
    return legacy, target


def records(path):
    with sqlite3.connect(path) as connection:
        tables = [r[0] for r in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        return {name: connection.execute('SELECT * FROM ' + name + ' ORDER BY rowid').fetchall()
                for name in tables if name not in ('schema_migrations', 'execution_history')}


def test_legacy_backup_preserves_all_data_and_restart(runtime, tmp_path, monkeypatch):
    legacy, target = legacy_database(runtime, tmp_path, monkeypatch)
    before = records(legacy)
    with SQLiteStorage().transaction() as connection:
        assert connection.execute('SELECT count(*) FROM execution_history').fetchone() == (0,)
        assert connection.execute('SELECT version FROM schema_migrations ORDER BY version').fetchall() == [(1,), (2,), (3,), (4,)]
    assert legacy.exists() and target.exists()
    assert records(target) == before == records(legacy)
    with SQLiteStorage().transaction() as connection:
        assert connection.execute('PRAGMA quick_check').fetchone() == ('ok',)
    assert records(target) == before
    assert target.stat().st_mode & 0o777 == 0o600


def test_backup_includes_committed_wal(runtime, tmp_path, monkeypatch):
    legacy, target = legacy_database(runtime, tmp_path, monkeypatch)
    with sqlite3.connect(legacy) as writer:
        writer.execute('PRAGMA wal_autocheckpoint=0')
        writer.execute('UPDATE source_scores SET reliability_score=0.314159')
        writer.commit()
        assert Path(str(legacy) + '-wal').stat().st_size > 0
        before = records(legacy)
        with SQLiteStorage().transaction():
            pass
        assert records(target) == before
    with SQLiteStorage().transaction() as connection:
        assert connection.execute('SELECT DISTINCT reliability_score FROM source_scores').fetchall() == [(0.314159,)]


def test_failed_migration_keeps_original(runtime, tmp_path, monkeypatch):
    legacy, target = legacy_database(runtime, tmp_path, monkeypatch)
    before = records(legacy)

    def fail(connection):
        raise RuntimeError('injected migration failure')

    with monkeypatch.context() as patch:
        patch.setattr(SQLiteStorage, '_migrate', staticmethod(fail))
        with pytest.raises(RuntimeError, match='injected'):
            with SQLiteStorage().transaction():
                pass
    assert records(legacy) == before
    assert not target.exists()
    assert not list(tmp_path.glob('.database-copy-*'))
    with SQLiteStorage().transaction():
        pass
    assert records(target) == before


def test_two_existing_databases_fail_without_overwrite(runtime, tmp_path, monkeypatch):
    legacy, target = legacy_database(runtime, tmp_path, monkeypatch)
    with SQLiteStorage(target).transaction():
        pass
    before = records(target)
    with pytest.raises(ValueError, match='conflict'):
        with SQLiteStorage().transaction():
            pass
    assert records(target) == before
    assert records(legacy)['evaluation_runs']


def test_explicit_legacy_path_is_unchanged(runtime, tmp_path, monkeypatch):
    legacy, target = legacy_database(runtime, tmp_path, monkeypatch)
    before = records(legacy)
    with SQLiteStorage(legacy).transaction() as connection:
        assert connection.execute('SELECT count(*) FROM execution_history').fetchone() == (0,)
    assert records(legacy) == before
    assert not target.exists()
    assert not (tmp_path / '.context-db-migration').exists()


def test_active_writer_prevents_snapshot(runtime, tmp_path, monkeypatch):
    legacy, target = legacy_database(runtime, tmp_path, monkeypatch)
    with sqlite3.connect(legacy) as writer:
        writer.execute('BEGIN IMMEDIATE')
        writer.execute('UPDATE source_scores SET reliability_score=0.25')
        with pytest.raises(sqlite3.OperationalError, match='locked'):
            with SQLiteStorage(timeout_seconds=0.02).transaction():
                pass
        assert not target.exists()
    with SQLiteStorage().transaction():
        pass
    assert records(target) == records(legacy)


def test_later_legacy_writes_are_reported(runtime, tmp_path, monkeypatch):
    legacy, target = legacy_database(runtime, tmp_path, monkeypatch)
    with SQLiteStorage().transaction():
        pass
    before = records(target)
    with sqlite3.connect(legacy) as writer:
        writer.execute('UPDATE source_scores SET reliability_score=0.25')
    with pytest.raises(ValueError, match='conflict'):
        with SQLiteStorage().transaction():
            pass
    assert records(target) == before
    assert records(legacy) != before


def test_concurrent_process_migration(runtime, tmp_path, monkeypatch):
    legacy, target = legacy_database(runtime, tmp_path, monkeypatch)
    before = records(legacy)
    script = '''
from pathlib import Path
from omneum import paths, SQLiteStorage
paths.get_context_db_path = lambda: Path(%r)
with SQLiteStorage().transaction() as connection:
    assert connection.execute('SELECT count(*) FROM evaluation_runs').fetchone() == (1,)
''' % str(target)

    def run(_):
        return subprocess.run([sys.executable, '-c', script], capture_output=True, text=True)

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(run, range(4)))
    assert all(r.returncode == 0 for r in results), [(r.stdout, r.stderr) for r in results]
    assert records(target) == before
    assert records(legacy) == before


def test_default_resolution_is_lazy_and_shared(tmp_path, monkeypatch):
    from omneum import paths
    from omneum.paths import get_context_db_path
    monkeypatch.setattr(paths, 'get_context_db_path', get_context_db_path)
    monkeypatch.setattr(Path, 'home', classmethod(lambda cls: tmp_path))
    if sys.platform != 'darwin':
        monkeypatch.delenv('XDG_DATA_HOME', raising=False)
    path = get_context_db_path()
    assert path.name == 'omneum.db' and not path.exists()
    with SQLiteStorage().transaction():
        pass
    identity = path.stat().st_ino
    with SQLiteStorage().transaction() as connection:
        assert connection.execute('SELECT count(*) FROM execution_history').fetchone() == (0,)
    assert path.stat().st_ino == identity


def test_interrupted_publication_requires_explicit_recovery(runtime, tmp_path, monkeypatch):
    legacy, target = legacy_database(runtime, tmp_path, monkeypatch)
    before = records(legacy)
    original = os.open

    def fail_receipt(path, *args, **kwargs):
        if Path(path).name == '.context-db-migration':
            raise OSError('injected receipt failure')
        return original(path, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(os, 'open', fail_receipt)
        with pytest.raises(OSError, match='receipt'):
            with SQLiteStorage().transaction():
                pass
    assert records(legacy) == before == records(target)
    with pytest.raises(ValueError, match='conflict'):
        with SQLiteStorage().transaction():
            pass
    with SQLiteStorage(target).transaction() as connection:
        assert connection.execute('PRAGMA quick_check').fetchone() == ('ok',)


def test_default_legacy_symlink_is_rejected(tmp_path, monkeypatch):
    target = tmp_path / 'omneum.db'
    other = tmp_path / 'unrelated.db'
    other.write_bytes(b'keep')
    (tmp_path / 'context.db').symlink_to(other)
    monkeypatch.setattr('omneum.paths.get_context_db_path', lambda: target)
    with pytest.raises(ValueError, match='symlink'):
        with SQLiteStorage().transaction():
            pass
    assert other.read_bytes() == b'keep'
    assert not target.exists()


def test_every_migration_connection_is_hardened_before_use(runtime, tmp_path, monkeypatch):
    from omneum.storage.sqlite import _expected_schema
    legacy, target = legacy_database(runtime, tmp_path, monkeypatch)
    opened = []
    connect = sqlite3.connect

    class CheckedConnection(sqlite3.Connection):
        def execute(self, sql, *args, **kwargs):
            if sql != 'PRAGMA trusted_schema=OFF':
                assert super().execute('PRAGMA trusted_schema').fetchone() == (0,), 'migration trusts database schema'
                with pytest.raises(sqlite3.OperationalError, match='not authorized'):
                    super().execute("SELECT load_extension('forbidden')")
                if hasattr(self, 'getconfig'):
                    assert self.getconfig(sqlite3.SQLITE_DBCONFIG_DEFENSIVE)
            return super().execute(sql, *args, **kwargs)

    def checked_connect(database, *args, **kwargs):
        opened.append(str(database))
        return connect(database, *args, factory=CheckedConnection, **kwargs)

    _expected_schema.cache_clear()
    monkeypatch.setattr(sqlite3, 'connect', checked_connect)
    with SQLiteStorage().transaction():
        pass
    assert str(legacy) in opened  # writer guard
    assert legacy.as_uri() + '?mode=ro' in opened  # snapshot reader
    assert any('.database-copy-' in path for path in opened)  # migration destination
    assert ':memory:' in opened  # bundled expected-schema construction
    assert str(target) in opened  # normal SDK connection after publication
