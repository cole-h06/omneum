"""Regressions for live schema tampering and mode-independent macOS ACLs."""
import os
from pathlib import Path
import sqlite3
import subprocess
import sys

import pytest

from omneum.storage import SQLiteStorage


def test_private_path_rejects_traversal(tmp_path):
    with pytest.raises(ValueError, match='traversal'):
        SQLiteStorage(tmp_path / 'nested' / '..' / 'context.db')


def test_unsafe_parent_directory(tmp_path):
    ancestor = tmp_path / 'shared'
    ancestor.mkdir()
    ancestor.chmod(0o777)
    try:
        with pytest.raises(ValueError, match='ancestor'):
            with SQLiteStorage(ancestor / 'new' / 'graph' / 'context.db').transaction():
                pass
        assert not (ancestor / 'new').exists()
    finally:
        ancestor.chmod(0o700)


def test_dynamic_sql_identifiers_are_allowlisted(tmp_path):
    with SQLiteStorage(tmp_path / 'context.db').transaction() as connection:
        for table, columns in [('sources; DROP TABLE claims;--', ('source_kind', 'identifier')),
                               ('sources', ('identifier); DROP TABLE claims;--',))]:
            with pytest.raises(ValueError, match='unsupported SQLite identity'):
                SQLiteStorage._identity(connection, table, 'workspace', None, columns, ())
        assert connection.execute('SELECT count(*) FROM claims').fetchone() == (0,)


@pytest.mark.parametrize('suffix', ['', '-wal', '-shm', '-journal'])
def test_unexpected_file_owner_rejected_before_mutation(tmp_path, monkeypatch, suffix):
    path = tmp_path / ('context.db'+suffix)
    path.touch(mode=0o600)
    inode = path.stat().st_ino
    fstat = os.fstat
    def foreign_owner(fd):
        info = fstat(fd)
        if info.st_ino == inode:
            fields = list(info)
            fields[4] = os.getuid()+1
            return os.stat_result(fields)
        return info
    monkeypatch.setattr(os, 'fstat', foreign_owner)
    with pytest.raises(ValueError, match='user-owned'):
        SQLiteStorage._prepare_file(path, create=suffix == '')
    assert path.stat().st_size == 0 and path.stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize('attack', ["'; DROP TABLE sources; --", '"; ATTACH DATABASE \'/tmp/stolen\' AS evil; --',
                                   "'); SELECT load_extension('/tmp/evil'); --", 'UNION SELECT sqlite_version()'])
def test_observation_strings_are_bound_values(tmp_path, example_daemon, attack):
    from datetime import datetime, timezone
    from uuid import uuid4
    from omneum import Claim, Observation, Source, Retrieval, SourceReference
    from omneum.client import OmneumClient
    from test_client import make_config, LocalEvaluator
    import asyncio
    from omneum.oprf import VOPRFServer
    # Linkage is real; every persisted string-bearing observation field carries
    # SQL metacharacters. The SQLite adapter round-trips them as data.
    server = VOPRFServer(example_daemon.context)
    client = OmneumClient(make_config(server), LocalEvaluator(server), local_persistence=None)
    from urllib.parse import quote
    source = Source('web_document', 'https://example.test/' + quote(attack, safe="';()-"), attack)
    claim = Claim(attack, attack, attack, {attack: [attack]})
    now = datetime.now(timezone.utc)
    observation = Observation(attack, source, claim, now, upstream_sources=(SourceReference(source.kind, source.identifier),),
        cited_sources=(SourceReference(source.kind, source.identifier),), parent_observation_ids=(attack,),
        retrievals=(Retrieval(attack, attack, attack, now, {attack: attack}),),
        metadata={attack: attack}, dependency_signals={attack: attack})
    async def tokens():
        return await client.link_source(source.kind, source.identifier), await client.link_claim(
            claim.entity_namespace, claim.entity, claim.attribute, claim.value)
    source_token, claim_token = asyncio.run(tokens())
    storage, workspace = SQLiteStorage(tmp_path / 'context.db'), uuid4()
    storage.persist_observation(workspace_id=workspace, observation=observation,
                               source_token=source_token, claim_token=claim_token)
    restored = storage.load_assertions(workspace_id=workspace)[0]
    from omneum.canonicalization import canonicalize_entity
    expected_claim = Claim(claim.entity_namespace, canonicalize_entity(claim.entity_namespace, claim.entity),
                           claim.attribute, claim.value)
    assert restored.observation_id == attack and restored.source == source and restored.claim == expected_claim
    assert restored.metadata == {attack: attack} and restored.retrievals[0].fields == {attack: attack}
    assert restored.dependency_signals == {attack: attack}


@pytest.mark.parametrize('tamper', [
    "CREATE TRIGGER injected AFTER INSERT ON evaluation_runs BEGIN DELETE FROM sources; END",
    "CREATE TRIGGER sqliteXhidden AFTER INSERT ON evaluation_runs BEGIN DELETE FROM sources; END",
    'DROP INDEX observations_source_idx',
    'DROP VIEW assertion_observation_envelopes',
    'ALTER TABLE sources ADD COLUMN injected TEXT',
    'CREATE TABLE unexpected(secret TEXT)',
])
def test_schema_drift(tmp_path, tamper):
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


def test_sqlite_hardening(tmp_path):
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
