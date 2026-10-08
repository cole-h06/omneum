"""Default local SQLite, adapter invariants and network independence."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import json
import os
import socket
import stat
from pathlib import Path
import sqlite3
import subprocess
import sys
from uuid import uuid4

import pytest

from omneum import (Claim, LocalPersistenceConfig, LocalPersistenceError,
                    OmneumClient, SQLiteStorage, Retrieval)
from omneum.canonicalization import canonicalize_source
from omneum.local_persistence import DEFAULT_LOCAL_WORKSPACE_ID
from omneum.paths import get_context_db_path
from test_local_persistence import runtime
from test_storage_evaluation import computed
from test_client_contribution import network


TABLES = ('sources', 'claims', 'observations', 'evaluation_runs', 'source_scores',
          'claim_scores', 'source_dependencies')


def evaluate(runtime, **options):
    config, evaluator, observations, estimator = runtime
    return asyncio.run(OmneumClient(config, evaluator, **options).evaluate_context(
        observations, estimator=estimator))


def counts(path):
    with sqlite3.connect(path) as connection:
        return {table: connection.execute(f'SELECT count(*) FROM {table}').fetchone()[0] for table in TABLES}


def test_default_first_use(runtime):
    from omneum import paths
    path = paths.get_context_db_path()
    client = OmneumClient(*runtime[:2])
    assert not path.exists()
    result = asyncio.run(client.evaluate_context(runtime[2], estimator=runtime[3]))
    assert result.claim_support
    assert path.is_file()
    assert counts(path) == dict(sources=2, claims=2, observations=3, evaluation_runs=1,
        source_scores=2, claim_scores=2, source_dependencies=1)
    with sqlite3.connect(path) as connection:
        assert connection.execute('SELECT version FROM schema_migrations').fetchall() == [(1,), (2,), (3,)]
        assert connection.execute('PRAGMA journal_mode').fetchone() == ('wal',)
        assert not connection.execute('PRAGMA foreign_key_check').fetchall()
        assert connection.execute('SELECT count(*) FROM observations WHERE evaluation_run_id IS NULL').fetchone()[0] == 0
        assert connection.execute('SELECT identifier FROM sources').fetchall()
        assert json.loads(connection.execute('SELECT value FROM claims LIMIT 1').fetchone()[0]).startswith('private-')


@pytest.mark.parametrize('platform,variables,parts', [
    ('darwin', {}, ('Library', 'Application Support', 'Omneum', 'context.db')),
    ('linux', {}, ('.local', 'share', 'omneum', 'context.db')),
    ('linux', {'XDG_DATA_HOME': 'custom-data'}, ('custom-data', 'omneum', 'context.db')),
    ('linux', {'XDG_DATA_HOME': 'relative'}, ('.local', 'share', 'omneum', 'context.db')),
    ('win32', {'LOCALAPPDATA': 'local-app-data'}, ('local-app-data', 'Omneum', 'context.db')),
    ('win32', {}, ('AppData', 'Local', 'Omneum', 'context.db')),
    ('win32', {'LOCALAPPDATA': 'relative'}, ('AppData', 'Local', 'Omneum', 'context.db')),
])
def test_native_paths(tmp_path, monkeypatch, platform, variables, parts):
    import omneum.paths as module
    monkeypatch.setattr(module.sys, 'platform', platform)
    monkeypatch.setattr(Path, 'home', classmethod(lambda cls: tmp_path))
    for name in ('XDG_DATA_HOME', 'LOCALAPPDATA'):
        monkeypatch.delenv(name, raising=False)
    for name, value in variables.items():
        monkeypatch.setenv(name, value if value == 'relative' else str(tmp_path / value))
    assert get_context_db_path() == tmp_path.joinpath(*parts)
    assert not get_context_db_path().parent.exists()


def test_custom_path_and_restart(runtime, tmp_path):
    path = tmp_path / 'custom' / 'context.db'
    for _ in range(2):
        # A new client and adapter use the same stable workspace on each restart.
        evaluate(runtime, local_persistence=LocalPersistenceConfig(SQLiteStorage(path)))
    assert counts(path) == dict(sources=2, claims=2, observations=6, evaluation_runs=2,
        source_scores=4, claim_scores=4, source_dependencies=2)
    with sqlite3.connect(path) as connection:
        assert connection.execute('SELECT count(DISTINCT source_id) FROM observations').fetchone()[0] == 2
        assert connection.execute('SELECT count(DISTINCT claim_id) FROM assertion_observations').fetchone()[0] == 2
        assert connection.execute('SELECT count(DISTINCT evaluation_run_id) FROM observations').fetchone()[0] == 2
    result = subprocess.run([sys.executable, '-c',
        'import sqlite3,sys; c=sqlite3.connect(sys.argv[1]); '
        'assert c.execute("SELECT count(*) FROM evaluation_runs").fetchone()[0] == 2; '
        'assert c.execute("SELECT count(*) FROM observations").fetchone()[0] == 6',
        str(path)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_disabled_never_creates_database(runtime, monkeypatch):
    from omneum import paths
    path = paths.get_context_db_path()
    def forbidden(*args, **kwargs):
        pytest.fail('SQLite was opened when explicitly disabled')
    monkeypatch.setattr(SQLiteStorage, 'transaction', forbidden)
    assert evaluate(runtime, local_persistence=None).claim_support
    assert not path.exists()


def test_default_needs_no_postgres_driver():
    script = '''
import importlib.abc, sys
class BlockPostgres(importlib.abc.MetaPathFinder):
    def find_spec(self, name, *args):
        if name == "psycopg" or name.startswith("psycopg."):
            raise ModuleNotFoundError("PostgreSQL driver absent")
sys.meta_path.insert(0, BlockPostgres())
import pytest
sys.exit(pytest.main(["-q", "tests/test_sqlite_storage.py::test_default_first_use"]))
'''
    result = subprocess.run([sys.executable, '-c', script], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr


def test_foreign_keys_and_outer_rollback(tmp_path):
    storage = SQLiteStorage(tmp_path / 'context.db')
    with storage.transaction() as connection:
        assert connection.execute('PRAGMA foreign_keys').fetchone() == (1,)
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute('INSERT INTO source_scores VALUES (?, ?, ?, ?)', ('workspace', 'missing', 'missing', 0.5))
    with pytest.raises(RuntimeError):
        with storage.transaction() as connection:
            connection.execute('''INSERT INTO evaluation_runs(id,workspace_id,algorithm,algorithm_version,status,parameters)
                VALUES ('run', 'workspace', 'BRAID', 'version', 'completed', '{}')''')
            with storage.transaction() as nested:
                assert nested is connection
            raise RuntimeError('rollback')
    assert counts(storage.path)['evaluation_runs'] == 0


def test_full_local_semantics_and_lineage(runtime, tmp_path):
    path = tmp_path / 'private-local.db'
    observations = tuple(replace(o, retrievals=(Retrieval('secret-retrieval', 'document',
        'secret-resource', o.observed_at, {'text': 'private retrieved text'}),),
        metadata={'customer': 'private customer'}) for o in runtime[2])
    evaluate((*runtime[:2], observations, runtime[3]), local_persistence=LocalPersistenceConfig(SQLiteStorage(path)))
    with sqlite3.connect(path) as connection:
        assert connection.execute('SELECT count(*) FROM observation_retrievals').fetchone() == (3,)
        assert json.loads(connection.execute('SELECT fields FROM observation_retrievals LIMIT 1').fetchone()[0]) == {'text': 'private retrieved text'}
        assert json.loads(connection.execute('SELECT metadata FROM observations LIMIT 1').fetchone()[0]) == {'customer': 'private customer'}
        assert connection.execute('SELECT count(*) FROM observation_parents WHERE parent_observation_id IS NOT NULL').fetchone() == (1,)
        # Relational OBSERVED edges and recursive local lineage traversal.
        rows = connection.execute('''SELECT s.identifier, c.value FROM observations o
            JOIN sources s ON s.id=o.source_id JOIN assertion_observations a ON a.observation_id=o.id
            JOIN claims c ON c.id=a.claim_id WHERE o.observation_type='assertion'
            ''').fetchall()
        assert len(rows) == 3
        assert connection.execute('''WITH RECURSIVE lineage(id) AS (
            SELECT id FROM observations WHERE local_observation_id='b1'
            UNION SELECT p.parent_observation_id FROM observation_parents p JOIN lineage l ON p.observation_id=l.id
            WHERE p.parent_observation_id IS NOT NULL
        ) SELECT count(*) FROM lineage''').fetchone() == (2,)

    restored = {o.observation_id: o for o in SQLiteStorage(path).load_assertions(
        workspace_id=DEFAULT_LOCAL_WORKSPACE_ID)}
    for original in observations:
        loaded = restored[original.observation_id]
        assert loaded.claim == original.claim
        assert loaded.metadata == original.metadata
        assert loaded.retrievals == original.retrievals
        assert loaded.parent_observation_ids == original.parent_observation_ids
        assert (loaded.cited_sources is None) == (original.cited_sources is None)
        assert tuple((r.kind, canonicalize_source(r.kind, r.identifier)) for r in loaded.cited_sources or ()) == tuple(
            (r.kind, canonicalize_source(r.kind, r.identifier)) for r in original.cited_sources or ())


def test_complete_rollback_preserves_previous_history(runtime, tmp_path, monkeypatch):
    storage = SQLiteStorage(tmp_path / 'context.db')
    local = LocalPersistenceConfig(storage)
    evaluate(runtime, local_persistence=local)
    before = counts(storage.path)
    original = SQLiteStorage.persist_evaluation
    def fail(self, **kwargs):
        original(self, **kwargs)
        raise RuntimeError('private SQL and path')
    monkeypatch.setattr(SQLiteStorage, 'persist_evaluation', fail)
    with pytest.raises(LocalPersistenceError) as caught:
        evaluate(runtime, local_persistence=local)
    assert caught.value.evaluation.claim_support
    assert 'private' not in str(caught.value)
    assert counts(storage.path) == before


def test_concurrent_thread_writers(computed, tmp_path):
    evaluation, sources, claims, estimator, observations = computed
    storage = SQLiteStorage(tmp_path / 'context.db')
    def write(_):
        storage.persist_context(evaluation=evaluation, workspace_id=DEFAULT_LOCAL_WORKSPACE_ID,
            occurrences=tuple((o, sources[o.source], claims[o.claim]) for o in observations),
            source_tokens=sources, claim_tokens=claims, estimator=estimator)
    with ThreadPoolExecutor(max_workers=6) as pool:
        list(pool.map(write, range(12)))
    assert counts(storage.path) == dict(sources=2, claims=2, observations=36, evaluation_runs=12,
        source_scores=24, claim_scores=24, source_dependencies=12)


def test_concurrent_sidecar_processes(tmp_path):
    path = tmp_path / 'context.db'
    script = '''
from datetime import datetime, timezone
import sys
from omneum import Claim, Observation, Source, LinkageToken
from omneum.linkage import LinkagePurpose
from omneum.canonicalization import canonicalize_source
from omneum.local_persistence import DEFAULT_LOCAL_WORKSPACE_ID
from omneum.storage import SQLiteStorage
def token(purpose, value):
    return LinkageToken("urn:uuid:8d96fc18-f40f-4ec7-8ae8-f3711d88b741", 1,
        "voprf", "ristretto255-SHA512", 1, purpose, bytes([value]) * 64)
s = SQLiteStorage(sys.argv[1])
for index in range(3):
    s.persist_observation(workspace_id=DEFAULT_LOCAL_WORKSPACE_ID,
        observation=Observation("id", Source("web_document", "https://example.com/private-source"),
            Claim("service", "entity", "attribute", "private-value"), datetime.now(timezone.utc)),
        source_token=token(LinkagePurpose.SOURCE, 1), claim_token=token(LinkagePurpose.CLAIM, 2))
'''
    processes = [subprocess.Popen([sys.executable, '-c', script, str(path)],
                  stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for _ in range(4)]
    for process in processes:
        output, errors = process.communicate(timeout=30)
        assert process.returncode == 0, output + errors
    assert counts(path) == dict(sources=1, claims=1, observations=12, evaluation_runs=0,
        source_scores=0, claim_scores=0, source_dependencies=0)


@pytest.mark.parametrize('enabled', [False, True])
@pytest.mark.parametrize('contribute', [False, True])
def test_sqlite_network_independence(runtime, network, tmp_path, enabled, contribute):
    path = tmp_path / 'sensitive-filesystem-path' / 'context.db'
    local = LocalPersistenceConfig(SQLiteStorage(path)) if enabled else None
    evaluate(runtime, local_persistence=local, network_contribution=network[0] if contribute else None)
    assert path.exists() is enabled
    assert len(network[2]) == int(contribute)
    if contribute:
        wire = network[2][0].model_dump_json()
        for forbidden in (str(path), 'sensitive-filesystem-path', 'context.db', 'private-', 'metadata', 'https://'):
            assert forbidden not in wire


def test_default_storage_does_not_enable_network(runtime, network):
    evaluate(runtime)
    assert network[1:] == ([], [])


def test_default_storage_with_explicit_contribution(runtime, network):
    from omneum import paths
    evaluate(runtime, network_contribution=network[0])
    assert counts(paths.get_context_db_path())['evaluation_runs'] == 1
    assert len(network[2]) == 1


def test_default_stdio_sqlite(runtime, computed, tmp_path):
    from mcp import StdioServerParameters
    from test_client import DEPLOYMENT_ID, PRIVATE_KEY
    from stdio_state import isolated_deployment_environment
    from omneum import OmneumClientConfig, open_stdio_client, paths
    directory = tmp_path / 'stdio'
    directory.mkdir()
    env, key, _ = isolated_deployment_environment(directory, DEPLOYMENT_ID, PRIVATE_KEY)
    params = StdioServerParameters(command=sys.executable, args=['-m', 'omneum.server'],
                                   cwd=Path(__file__).resolve().parents[1], env=env)
    config = OmneumClientConfig(DEPLOYMENT_ID, 1, 'voprf', 'ristretto255-SHA512', 1, key)
    async def run():
        async with open_stdio_client(config, params) as client:
            return await client.evaluate_context(computed[4], estimator=computed[3])
    assert asyncio.run(run()).claim_support
    assert counts(paths.get_context_db_path())['evaluation_runs'] == 1


def test_migrations_fail_closed(tmp_path):
    storage = SQLiteStorage(tmp_path / 'context.db')
    with storage.transaction() as connection:
        connection.execute("UPDATE schema_migrations SET checksum='modified'")
    with pytest.raises(ValueError, match='migration'):
        with storage.transaction():
            pass
    with sqlite3.connect(storage.path) as connection:
        assert connection.execute('SELECT checksum FROM schema_migrations').fetchone() == ('modified',)


def test_existing_unrelated_database_is_not_overwritten(tmp_path):
    path = tmp_path / 'other.db'
    with sqlite3.connect(path) as connection:
        connection.execute('CREATE TABLE caller_data (value TEXT)')
        connection.execute("INSERT INTO caller_data VALUES ('keep')")
    with pytest.raises(ValueError, match='unrelated'):
        with SQLiteStorage(path).transaction():
            pass
    with sqlite3.connect(path) as connection:
        assert connection.execute('SELECT value FROM caller_data').fetchone() == ('keep',)
        assert not connection.execute("SELECT name FROM sqlite_master WHERE name='schema_migrations'").fetchall()


@pytest.mark.skipif(os.name != 'posix', reason='POSIX permissions')
def test_private_files_with_permissive_umask(tmp_path):
    path = tmp_path / 'graph' / 'context.db'
    before = stat.S_IMODE(tmp_path.stat().st_mode)
    mask = os.umask(0)
    try:
        with SQLiteStorage(path).transaction() as connection:
            assert connection.execute('PRAGMA busy_timeout').fetchone() == (10000,)
            assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700
            for name in (path, Path(str(path) + '-wal'), Path(str(path) + '-shm')):
                assert stat.S_IMODE(name.stat().st_mode) == 0o600
    finally:
        os.umask(mask)
    assert stat.S_IMODE(tmp_path.stat().st_mode) == before


@pytest.mark.skipif(os.name != 'posix', reason='POSIX permissions')
@pytest.mark.parametrize('mode', [0o755, 0o770, 0o777])
def test_unsafe_directory_is_not_chmodded(tmp_path, mode):
    directory = tmp_path / 'caller-directory'
    directory.mkdir(mode=mode)
    directory.chmod(mode)
    with pytest.raises(ValueError, match='owner-only'):
        with SQLiteStorage(directory / 'context.db').transaction():
            pass
    assert stat.S_IMODE(directory.stat().st_mode) == mode
    assert not (directory / 'context.db').exists()


@pytest.mark.skipif(os.name != 'posix', reason='POSIX permissions')
def test_existing_files_are_private(tmp_path, monkeypatch):
    path = tmp_path / 'context.db'
    # An empty file left by a creator that exited before SQLite initialization.
    for suffix in ('', '-wal', '-shm', '-journal'):
        name = Path(str(path) + suffix)
        name.touch()
        name.chmod(0o666)
    connect = sqlite3.connect
    def checked(*args, **kwargs):
        for suffix in ('', '-wal', '-shm', '-journal'):
            assert stat.S_IMODE(Path(str(path) + suffix).stat().st_mode) == 0o600
        return connect(*args, **kwargs)
    monkeypatch.setattr(sqlite3, 'connect', checked)
    with SQLiteStorage(path).transaction() as connection:
        assert connection.execute('PRAGMA journal_mode').fetchone() == ('wal',)


@pytest.mark.skipif(os.name != 'posix', reason='POSIX symlinks')
@pytest.mark.parametrize('suffix', ['', '-wal', '-shm', '-journal'])
def test_symlink_file_rejected(tmp_path, suffix):
    path = tmp_path / 'context.db'
    target = tmp_path / 'caller-file'
    target.write_bytes(b'keep')
    target.chmod(0o644)
    Path(str(path) + suffix).symlink_to(target)
    with pytest.raises(ValueError, match='symlink'):
        with SQLiteStorage(path).transaction():
            pass
    assert target.read_bytes() == b'keep'
    assert stat.S_IMODE(target.stat().st_mode) == 0o644


@pytest.mark.skipif(os.name != 'posix', reason='POSIX symlinks')
def test_symlink_directory_rejected(tmp_path):
    target = tmp_path / 'caller-directory'
    target.mkdir()
    alias = tmp_path / 'alias'
    alias.symlink_to(target, target_is_directory=True)
    with pytest.raises(ValueError, match='symlink'):
        with SQLiteStorage(alias / 'context.db').transaction():
            pass
    assert not (target / 'context.db').exists()


@pytest.mark.skipif(os.name != 'posix', reason='POSIX hardlinks')
def test_hardlink_rejected(tmp_path):
    target = tmp_path / 'caller-file'
    target.write_bytes(b'keep')
    target.chmod(0o644)
    path = tmp_path / 'context.db'
    os.link(target, path)
    with pytest.raises(ValueError, match='unshared'):
        with SQLiteStorage(path).transaction():
            pass
    assert target.read_bytes() == b'keep'
    assert stat.S_IMODE(target.stat().st_mode) == 0o644


@pytest.mark.skipif(os.name != 'posix', reason='POSIX permissions')
def test_writable_ancestor_rejected(tmp_path):
    parent = tmp_path / 'shared'
    parent.mkdir(mode=0o777)
    parent.chmod(0o777)
    path = parent / 'private' / 'context.db'
    with pytest.raises(ValueError, match='unsafe ancestor'):
        with SQLiteStorage(path).transaction():
            pass
    assert not path.exists()
    assert stat.S_IMODE(parent.stat().st_mode) == 0o777


@pytest.mark.parametrize('schema', [
    'CREATE TABLE schema_migrations(version INTEGER PRIMARY KEY, checksum TEXT NOT NULL)',
    'CREATE VIEW caller_view AS SELECT 1',
])
def test_unowned_schema_rejected(tmp_path, schema):
    path = tmp_path / 'other.db'
    with sqlite3.connect(path) as connection:
        connection.execute(schema)
    before = path.read_bytes()
    with pytest.raises(ValueError, match='unrelated'):
        with SQLiteStorage(path).transaction():
            pass
    assert path.read_bytes() == before
    with sqlite3.connect(path) as connection:
        assert connection.execute('PRAGMA application_id').fetchone() == (0,)
        assert connection.execute('PRAGMA journal_mode').fetchone() == ('delete',)


def test_existing_database_gets_wal(tmp_path):
    path = tmp_path / 'context.db'
    with SQLiteStorage(path).transaction():
        pass
    with sqlite3.connect(path) as connection:
        assert connection.execute('PRAGMA journal_mode=DELETE').fetchone() == ('delete',)
    with SQLiteStorage(path).transaction() as connection:
        assert connection.execute('PRAGMA journal_mode').fetchone() == ('wal',)
        assert connection.execute('PRAGMA foreign_keys').fetchone() == (1,)


def test_persistence_without_tcp(runtime, tmp_path, monkeypatch, caplog):
    connect = socket.socket.connect
    def local_only(self, address):
        if self.family in (socket.AF_INET, socket.AF_INET6):
            pytest.fail('local persistence attempted a network connection')
        return connect(self, address)
    monkeypatch.setattr(socket.socket, 'connect', local_only)
    for name in ('DATABASE_URL', 'PGHOST', 'PGPASSWORD'):
        monkeypatch.setenv(name, 'production-secret-sentinel')
    path = tmp_path / 'private-path' / 'context.db'
    observations = tuple(replace(o, metadata={'secret': 'private-metadata'},
        retrievals=(Retrieval('private-retrieval', 'document', 'private-resource',
                             o.observed_at, {'text': 'private-text'}),)) for o in runtime[2])
    evaluate((*runtime[:2], observations, runtime[3]),
             local_persistence=LocalPersistenceConfig(SQLiteStorage(path)))
    assert counts(path)['observations'] == 3
    for secret in (str(path), 'private-', 'production-secret-sentinel'):
        assert secret not in caplog.text



def test_normal_connections_keep_foreign_keys(tmp_path, monkeypatch):
    connect = sqlite3.connect
    statements = []
    def traced(*args, **kwargs):
        connection = connect(*args, **kwargs)
        connection.set_trace_callback(statements.append)
        return connection
    monkeypatch.setattr(sqlite3, 'connect', traced)
    storage = SQLiteStorage(tmp_path / 'context.db')
    for _ in range(2):
        with storage.transaction() as connection:
            assert connection.execute('PRAGMA foreign_keys').fetchone() == (1,)
    assert 'PRAGMA foreign_keys=OFF' not in statements


@pytest.mark.skipif(os.name != 'posix', reason='POSIX no-follow open')
def test_symlink_swap_rejected(tmp_path, monkeypatch):
    path = tmp_path / 'context.db'
    target = tmp_path / 'caller-file'
    target.write_bytes(b'keep')
    target.chmod(0o644)
    opened = os.open
    def swapped(name, flags, *args, **kwargs):
        if Path(name) == path:
            path.symlink_to(target)
        return opened(name, flags, *args, **kwargs)
    monkeypatch.setattr(os, 'open', swapped)
    with pytest.raises(OSError):
        with SQLiteStorage(path).transaction():
            pass
    assert target.read_bytes() == b'keep'
    assert stat.S_IMODE(target.stat().st_mode) == 0o644


def test_unowned_versioned_database_rejected(tmp_path):
    path = tmp_path / 'other.db'
    with sqlite3.connect(path) as connection:
        connection.execute('PRAGMA user_version=42')
    before = path.read_bytes()
    with pytest.raises(ValueError, match='unrelated'):
        with SQLiteStorage(path).transaction():
            pass
    assert path.read_bytes() == before


@pytest.mark.skipif(os.name != 'posix', reason='POSIX symlinks and permissions')
def test_canonical_directory_is_not_resolved_again_after_validation(tmp_path, monkeypatch):
    safe = tmp_path / 'safe'
    unsafe = tmp_path / 'unsafe'
    safe.mkdir(mode=0o700)
    unsafe.mkdir(mode=0o777)
    unsafe.chmod(0o777)
    for parent in (safe, unsafe):
        (parent / 'graph').mkdir(mode=0o700)
    alias = tmp_path / 'alias'
    alias.symlink_to(safe, target_is_directory=True)
    supplied = alias / 'graph'
    resolve = Path.resolve
    calls = []
    def swapped(self, *args, **kwargs):
        resolved = resolve(self, *args, **kwargs)
        if self == supplied:
            calls.append(resolved)
            if len(calls) == 1:
                alias.unlink()
                alias.symlink_to(unsafe, target_is_directory=True)
        return resolved
    monkeypatch.setattr(Path, 'resolve', swapped)
    with SQLiteStorage(supplied / 'context.db').transaction():
        pass
    assert calls == [safe / 'graph']
    assert (safe / 'graph' / 'context.db').is_file()
    assert not (unsafe / 'graph' / 'context.db').exists()


@pytest.mark.skipif(os.name != 'posix', reason='POSIX unlink semantics')
@pytest.mark.parametrize('suffix', ['-wal', '-shm'])
def test_disappearing_sidecar_does_not_reject_concurrent_open(tmp_path, monkeypatch, suffix):
    path = tmp_path / 'context.db'
    sidecar = Path(str(path) + suffix)
    sidecar.touch(mode=0o600)
    fstat = os.fstat
    removed = []
    def disappearing(fd):
        info = fstat(fd)
        if not removed and sidecar.exists() and info.st_ino == sidecar.stat().st_ino:
            sidecar.unlink()
            removed.append(True)
            return fstat(fd)
        return info
    monkeypatch.setattr(os, 'fstat', disappearing)
    with SQLiteStorage(path).transaction() as connection:
        assert connection.execute('PRAGMA journal_mode').fetchone() == ('wal',)
    assert removed == [True]


@pytest.mark.skipif(os.name != 'posix', reason='POSIX directory permissions')
def test_new_macos_config_directory_is_compatible_with_default_graph(tmp_path, monkeypatch):
    from omneum import paths
    from omneum.storage import filesystem
    monkeypatch.setattr(filesystem, '_darwin_is_local', lambda path: True)
    monkeypatch.setattr(paths.sys, 'platform', 'darwin')
    monkeypatch.setattr(Path, 'home', classmethod(lambda cls: tmp_path))
    monkeypatch.delenv('OMNEUM_CONFIG_DIR', raising=False)
    expected = tmp_path / 'Library' / 'Application Support' / 'Omneum'
    monkeypatch.setattr(paths, 'user_config_path', lambda app: expected)
    # Undo the test isolation resolver so the platform's actual mapping is used.
    monkeypatch.setattr(paths, 'get_context_db_path', get_context_db_path)
    before = stat.S_IMODE(tmp_path.stat().st_mode)
    mask = os.umask(0o022)
    try:
        assert paths.get_config_dir() == expected
        with SQLiteStorage().transaction():
            pass
    finally:
        os.umask(mask)
    assert stat.S_IMODE(expected.stat().st_mode) == 0o700
    assert stat.S_IMODE((expected / 'context.db').stat().st_mode) == 0o600
    assert stat.S_IMODE(tmp_path.stat().st_mode) == before
