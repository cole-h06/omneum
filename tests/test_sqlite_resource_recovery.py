"""Bounded WAL/disk-full probes against new temporary graphs only."""
from contextlib import closing
import sqlite3
from uuid import uuid4

import pytest

from omneum import SQLiteStorage


def insert_source(database, index, text='fixture'):
    database.execute('''INSERT INTO sources
        (id, workspace_id, deployment_id, key_version, source_token, source_kind, identifier)
        VALUES (?, ?, ?, 1, ?, 'web_document', ?)''',
        (str(uuid4()), str(uuid4()), 'fixture', index.to_bytes(64, 'big'), text))


def test_sqlite_full_rolls_back_and_can_reopen(tmp_path):
    storage = SQLiteStorage(tmp_path / 'graph/omneum.db')
    with storage.transaction() as database:
        insert_source(database, 1)
    with pytest.raises(sqlite3.OperationalError, match='full'):
        with storage.transaction() as database:
            pages = database.execute('PRAGMA page_count').fetchone()[0]
            database.execute(f'PRAGMA max_page_count={pages + 4}')
            # Logical SQLite page limit, not actual filesystem exhaustion.
            insert_source(database, 2, 'x' * 100_000)
    with SQLiteStorage(storage.path).transaction() as database:
        assert database.execute('SELECT count(*) FROM sources').fetchone() == (1,)
        assert database.execute('PRAGMA integrity_check').fetchone() == ('ok',)
        assert not database.execute('PRAGMA foreign_key_check').fetchall()
        insert_source(database, 3)
    with storage.transaction() as database:
        assert database.execute('SELECT count(*) FROM sources').fetchone() == (2,)


def test_long_reader_pins_wal_until_released(tmp_path):
    storage = SQLiteStorage(tmp_path / 'graph/omneum.db')
    with storage.transaction() as database:
        assert database.execute('PRAGMA journal_mode').fetchone() == ('wal',)
        insert_source(database, 1)
    with closing(sqlite3.connect(storage.path, isolation_level=None)) as reader:
        reader.execute('BEGIN')
        assert reader.execute('SELECT count(*) FROM sources').fetchone() == (1,)
        # Eight small transactions are sufficient to expose checkpoint starvation.
        for index in range(2, 10):
            with storage.transaction() as database:
                insert_source(database, index)
        assert reader.execute('SELECT count(*) FROM sources').fetchone() == (1,)
        with closing(sqlite3.connect(storage.path, isolation_level=None, timeout=.01)) as checkpoint:
            assert checkpoint.execute('PRAGMA wal_checkpoint(TRUNCATE)').fetchone()[0] == 1
            reader.rollback()
            assert checkpoint.execute('PRAGMA wal_checkpoint(TRUNCATE)').fetchone() == (0, 0, 0)
    with storage.transaction() as database:
        assert database.execute('SELECT count(*) FROM sources').fetchone() == (9,)
        assert database.execute('PRAGMA integrity_check').fetchone() == ('ok',)
