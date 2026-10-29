"""Observation envelopes remain extensible; assertion consumers are fail-closed."""
import asyncio
from dataclasses import replace
from datetime import datetime, timezone
from hashlib import sha256
import sqlite3
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from omneum import Claim, Observation, Source
from omneum.contribution.builder import build_contribution
from omneum.storage import SQLiteStorage
from omneum.storage.schema import APPLICATION_ID, MIGRATIONS
from test_storage import token
from omneum.linkage import LinkagePurpose


@pytest.fixture
def assertion():
    return Observation('assertion', Source('web_document', 'https://example.com/a'),
        Claim('service', 'entity', 'status', {'healthy': True}),
        datetime(2026, 1, 1, tzinfo=timezone.utc), upstream_sources=(),
        parent_observation_ids=(), metadata={'private': 'value'})


def persist(storage, workspace, assertion):
    return storage.persist_observation(workspace_id=workspace, observation=assertion,
        source_token=token(LinkagePurpose.SOURCE), claim_token=token(LinkagePurpose.CLAIM, 2))


def test_round_trip_restart_and_future_exclusion(tmp_path, assertion):
    storage = SQLiteStorage(tmp_path / 'context.db')
    workspace = uuid4()
    row = persist(storage, workspace, assertion)
    with storage.transaction() as c:
        assert 'claim_id' not in {r[1] for r in c.execute('PRAGMA table_info(observations)')}
        assert c.execute('SELECT observation_type FROM observations').fetchone() == ('assertion',)
        assert c.execute('SELECT * FROM assertion_observations').fetchone() == (str(row.observation_id), str(row.claim_id))
        c.execute("INSERT INTO observations(id,workspace_id,source_id,observation_type,observed_at,metadata) VALUES (?,?,?,?,?,?)",
            ('future', str(workspace), str(row.source_id), 'measurement', assertion.observed_at.isoformat(), '{"unit":"m"}'))
        # Even an assertion envelope with a missing subtype must not be loaded.
        c.execute("INSERT INTO observations(id,workspace_id,source_id,observed_at) VALUES (?,?,?,?)",
            ('incomplete', str(workspace), str(row.source_id), assertion.observed_at.isoformat()))
        assert storage.load_assertions(workspace_id=workspace) == (assertion,)
        c.execute("DELETE FROM observations WHERE id='incomplete'")
    restarted = SQLiteStorage(storage.path)
    assert restarted.load_assertions(workspace_id=workspace) == (assertion,)
    assert restarted.load_assertions(workspace_id=uuid4()) == ()
    with restarted.transaction() as c:
        assert c.execute("SELECT observation_type,metadata FROM observations WHERE id='future'").fetchone() == ('measurement', '{"unit":"m"}')
        with pytest.raises(sqlite3.IntegrityError):
            c.execute('INSERT INTO assertion_observations VALUES (?,?)', ('future', str(row.claim_id)))


def test_subtype_foreign_keys_workspace_and_immutability(tmp_path, assertion):
    storage = SQLiteStorage(tmp_path / 'context.db')
    workspace = uuid4()
    row = persist(storage, workspace, assertion)
    other = persist(storage, uuid4(), assertion)
    with storage.transaction() as c:
        for oid, cid in [('missing', str(row.claim_id)), ('new', 'missing'), ('new', str(other.claim_id))]:
            if oid == 'new':
                c.execute("INSERT OR IGNORE INTO observations(id,workspace_id,source_id,observed_at) VALUES (?,?,?,?)",
                    (oid, str(workspace), str(row.source_id), assertion.observed_at.isoformat()))
            with pytest.raises(sqlite3.IntegrityError):
                c.execute('INSERT INTO assertion_observations VALUES (?,?)', (oid, cid))
        c.execute("DELETE FROM observations WHERE id='new'")
        with pytest.raises(sqlite3.IntegrityError):
            c.execute('DELETE FROM assertion_observations')
        with pytest.raises(sqlite3.IntegrityError):
            c.execute('UPDATE assertion_observations SET claim_id=?', (str(other.claim_id),))
        with pytest.raises(sqlite3.IntegrityError):
            c.execute("UPDATE observations SET observation_type='future'")
        with pytest.raises(sqlite3.IntegrityError):
            c.execute("INSERT INTO observations(id,workspace_id,observed_at) VALUES ('no-source',?,?)", (str(workspace), assertion.observed_at.isoformat()))
        with pytest.raises(sqlite3.IntegrityError):
            c.execute('UPDATE claims SET workspace_id=? WHERE id=?', (str(uuid4()), str(row.claim_id)))
        # The required delete cascade also works for subtype rows.
        c.execute('DELETE FROM observations WHERE id=?', (str(row.observation_id),))
        assert c.execute('SELECT count(*) FROM assertion_observations WHERE observation_id=?', (str(row.observation_id),)).fetchone() == (0,)


def test_subtype_insert_failure_and_outer_rollback(tmp_path, assertion):
    storage = SQLiteStorage(tmp_path / 'context.db')
    workspace = uuid4()
    with storage.transaction() as c:
        c.execute("CREATE TRIGGER fail_subtype BEFORE INSERT ON assertion_observations BEGIN SELECT RAISE(ABORT,'fail'); END;")
        with pytest.raises(sqlite3.IntegrityError):
            persist(storage, workspace, assertion)
        for table in ('observations', 'assertion_observations', 'sources', 'claims'):
            assert c.execute(f'SELECT count(*) FROM {table}').fetchone() == (0,)
        c.execute('DROP TRIGGER fail_subtype')
    with pytest.raises(RuntimeError):
        with storage.transaction():
            persist(storage, workspace, assertion)
            raise RuntimeError('rollback')
    with storage.transaction() as c:
        assert c.execute('SELECT count(*) FROM observations').fetchone() == (0,)
        assert c.execute('SELECT count(*) FROM assertion_observations').fetchone() == (0,)


def test_lossless_version_one_migration(tmp_path):
    path = tmp_path / 'legacy.db'
    version, script = MIGRATIONS[0]
    workspace = str(uuid4())
    with sqlite3.connect(path) as c:
        c.executescript(script)
        c.execute('''CREATE TABLE schema_migrations (
            version INTEGER PRIMARY KEY, checksum TEXT NOT NULL,
            applied_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
        )''')
        c.execute('INSERT INTO schema_migrations(version,checksum) VALUES (?,?)',
                  (version, sha256(script.encode()).hexdigest()))
        c.execute(f'PRAGMA application_id={APPLICATION_ID}')
        c.execute('INSERT INTO sources VALUES (?,?,?,?,?,?,?)', ('s', workspace, 'deployment', 1, b's'*64, 'web_document', 'https://example.com/a'))
        c.execute('INSERT INTO claims VALUES (?,?,?,?,?,?,?,?,?)', ('c', workspace, 'deployment', 1, b'c'*64, 'service', 'entity', 'status', '"ok"'))
        c.execute('''INSERT INTO observations(id,workspace_id,local_observation_id,source_id,claim_id,
            observed_at,upstream_known,citations_known,parents_known,retrievals_known,metadata,dependency_signals)
            VALUES ('o',?,'old','s','c','2026-01-01T00:00:00+00:00',1,0,1,0,'{"keep":true}','{}')''', (workspace,))
        c.execute("INSERT INTO observation_source_references VALUES ('o','upstream',0,'web_document','https://example.com/upstream')")
        c.execute("INSERT INTO evaluation_runs(id,workspace_id,algorithm,algorithm_version,status,parameters) VALUES ('run',?,'BRAID','v','completed','{}')", (workspace,))
        c.execute("UPDATE observations SET evaluation_run_id='run' WHERE id='o'")
        c.execute('INSERT INTO observation_parents VALUES (?, ?, ?, ?, ?)', (workspace, 'o', 0, 'old', 'o'))
        before = c.execute('SELECT * FROM observations').fetchone()
        oldcols = [r[1] for r in c.execute('PRAGMA table_info(observations)')]
    storage = SQLiteStorage(path)
    with storage.transaction() as c:
        cols = ','.join(x for x in oldcols if x != 'claim_id')
        assert c.execute(f'SELECT {cols} FROM observations').fetchone() == tuple(v for k,v in zip(oldcols,before) if k != 'claim_id')
        assert c.execute('SELECT observation_type FROM observations').fetchone() == ('assertion',)
        assert c.execute('SELECT * FROM assertion_observations').fetchone() == ('o','c')
        assert c.execute('SELECT count(*) FROM observation_source_references').fetchone() == (1,)
        assert c.execute('PRAGMA foreign_key_check').fetchall() == []
    loaded = SQLiteStorage(path).load_assertions(workspace_id=UUID(workspace))
    assert loaded[0].claim.value == 'ok'
    assert loaded[0].parent_observation_ids == ('old',)
    assert loaded[0].upstream_sources[0].identifier == 'https://example.com/upstream'


@pytest.mark.parametrize('invalid', ['future', 'missing', 'duck'])
def test_invalid_contribution_subtypes(assertion, invalid):
    if invalid == 'duck':
        observation = SimpleNamespace(observation_type='assertion', claim=assertion.claim)
    else:
        observation = replace(assertion)
        object.__setattr__(observation, 'observation_type' if invalid == 'future' else 'claim',
            'measurement' if invalid == 'future' else None)
    with pytest.raises(ValueError, match='valid assertion'):
        asyncio.run(build_contribution(None, None, (observation,), None))


def test_assertion_dto_rejects_future_type(assertion):
    with pytest.raises(ValueError, match='assertion'):
        replace(assertion, observation_type='measurement')


def test_assertion_evaluation_rejects_future_envelope(assertion):
    from omneum.dependency import estimate_dependencies
    from test_dependency import config
    future = replace(assertion)
    object.__setattr__(future, 'observation_type', 'measurement')
    with pytest.raises(TypeError, match='Observation'):
        estimate_dependencies((future.source,), (future,), config())


def test_direct_sql_commit_requires_subtype_and_can_be_repaired(tmp_path, assertion):
    storage = SQLiteStorage(tmp_path / 'context.db')
    workspace = uuid4()
    row = persist(storage, workspace, assertion)
    with sqlite3.connect(storage.path, isolation_level=None) as c:
        c.execute('PRAGMA foreign_keys=ON')
        c.execute('BEGIN')
        c.execute('SAVEPOINT nested')
        c.execute("INSERT INTO observations(id,workspace_id,source_id,observed_at) VALUES ('direct',?,?,?)",
            (str(workspace), str(row.source_id), assertion.observed_at.isoformat()))
        c.execute('RELEASE nested')  # Nested savepoints may contain incomplete assertions.
        assert c.execute("SELECT observation_id FROM assertion_observation_requirements WHERE observation_id='direct'").fetchone() == ('direct',)
        with pytest.raises(sqlite3.IntegrityError, match='FOREIGN KEY'):
            c.execute('COMMIT')
        assert c.in_transaction  # A failed deferred-FK commit leaves SQLite's transaction open.
        c.execute('INSERT INTO assertion_observations VALUES (?,?)', ('direct', str(row.claim_id)))
        c.execute('COMMIT')
        assert c.execute('PRAGMA foreign_key_check').fetchall() == []
        with pytest.raises(sqlite3.IntegrityError):
            c.execute('INSERT INTO assertion_observations VALUES (?,?)', ('direct', str(row.claim_id)))
        for statement in ("DELETE FROM assertion_observation_requirements WHERE observation_id='direct'",
                          "UPDATE assertion_observation_requirements SET observation_id='other' WHERE observation_id='direct'"):
            with pytest.raises(sqlite3.IntegrityError):
                c.execute(statement)
        # Autocommit cannot publish an envelope separately from its subtype.
        with pytest.raises(sqlite3.IntegrityError, match='FOREIGN KEY'):
            c.execute("INSERT INTO observations(id,workspace_id,source_id,observed_at) VALUES ('autocommit',?,?,?)",
                (str(workspace), str(row.source_id), assertion.observed_at.isoformat()))
        assert c.execute("SELECT count(*) FROM observations WHERE id='autocommit'").fetchone() == (0,)


def test_incomplete_assertion_rolls_back_adapter_transaction(tmp_path, assertion):
    storage = SQLiteStorage(tmp_path / 'context.db')
    workspace = uuid4()
    row = persist(storage, workspace, assertion)
    with pytest.raises(sqlite3.IntegrityError, match='FOREIGN KEY'):
        with storage.transaction() as c:
            c.execute("INSERT INTO observations(id,workspace_id,source_id,observed_at) VALUES ('rollback',?,?,?)",
                (str(workspace), str(row.source_id), assertion.observed_at.isoformat()))
    with storage.transaction() as c:
        assert c.execute("SELECT count(*) FROM observations WHERE id='rollback'").fetchone() == (0,)
        assert c.execute("SELECT count(*) FROM assertion_observation_requirements WHERE observation_id='rollback'").fetchone() == (0,)
        # Future envelopes need no assertion requirement and survive restart.
        c.execute("INSERT INTO observations(id,workspace_id,source_id,observation_type,observed_at) VALUES ('future-event',?,?, 'event',?)",
            (str(workspace), str(row.source_id), assertion.observed_at.isoformat()))
        with pytest.raises(sqlite3.IntegrityError):
            c.execute("INSERT INTO assertion_observation_requirements VALUES ('future-event')")
    with SQLiteStorage(storage.path).transaction() as c:
        assert c.execute("SELECT observation_type FROM observations WHERE id='future-event'").fetchone() == ('event',)
        assert c.execute("SELECT count(*) FROM assertion_observation_requirements WHERE observation_id='future-event'").fetchone() == (0,)


def test_version_two_upgrade_rejects_orphan_without_data_loss(tmp_path, assertion, monkeypatch):
    import omneum.storage.sqlite as adapter
    storage = SQLiteStorage(tmp_path / 'version-two.db')
    workspace = uuid4()
    with monkeypatch.context() as old:
        old.setattr(adapter, 'MIGRATIONS', MIGRATIONS[:2])
        row = persist(storage, workspace, assertion)
        with storage.transaction() as c:
            c.execute("INSERT INTO observations(id,workspace_id,source_id,local_observation_id,observed_at) VALUES ('legacy-orphan',?,?,'orphan',?)",
                (str(workspace), str(row.source_id), assertion.observed_at.isoformat()))
    with pytest.raises(ValueError, match='foreign key integrity'):
        with storage.transaction():
            pass
    with sqlite3.connect(storage.path) as c:
        assert c.execute('SELECT version FROM schema_migrations').fetchall() == [(1,), (2,)]
        assert c.execute('SELECT count(*) FROM observations').fetchone() == (2,)
        assert not c.execute("SELECT 1 FROM sqlite_master WHERE name='assertion_observation_requirements'").fetchone()
        # Explicitly supply the missing semantic data, then retry the migration.
        c.execute('PRAGMA foreign_keys=ON')
        c.execute("INSERT INTO assertion_observations VALUES ('legacy-orphan',?)", (str(row.claim_id),))
    with storage.transaction() as c:
        assert c.execute('SELECT count(*) FROM assertion_observation_requirements').fetchone() == (2,)
        assert c.execute('SELECT version FROM schema_migrations').fetchall() == [(1,), (2,), (3,), (4,)]
