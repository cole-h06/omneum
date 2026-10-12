"""User-owned SQLite Context Graph. Connections exist only inside transactions."""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from contextlib import contextmanager
from dataclasses import asdict, is_dataclass
from hashlib import sha256
from functools import lru_cache
import json
import math
import os
from pathlib import Path
import sqlite3
import stat
from threading import RLock, local
from time import monotonic, sleep
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from .. import paths
from ..canonicalization import canonicalize_source, canonicalize_entity
from ..dependency import DependencyEstimatorConfig
from ..information import Claim, Observation, Source
from ..linkage import LinkagePurpose
from .base import PersistedObservation
from .filesystem import require_local_filesystem, require_safe_acl, private_directory
from .schema import APPLICATION_ID, MIGRATIONS


class SQLiteRuntimeError(RuntimeError):
    """The local runtime lacks a known SQLite data-integrity fix."""


def require_safe_sqlite():
    # https://sqlite.org/wal.html#walresetbug: patched maintenance branches and mainline.
    version = sqlite3.sqlite_version_info
    if not (version >= (3, 51, 3) or (3, 50, 7) <= version < (3, 51, 0)
            or (3, 44, 6) <= version < (3, 45, 0)):
        raise SQLiteRuntimeError("Local Context Graph requires SQLite with the WAL-reset fix "
                                 "(3.51.3+ or patched 3.50.7/3.44.6 branches). "
                                 "Use a current Python runtime with patched SQLite; "
                                 "no existing graph files were changed.")


_MIGRATION_TABLE = '''CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY, checksum TEXT NOT NULL,
    applied_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
)'''


def _schema(connection):
    # Include autoindexes as well as triggers/views: the migration ledger alone
    # does not prove that constraints or executable schema objects are intact.
    rows = connection.execute(
        "SELECT type, name, tbl_name, sql FROM sqlite_master "
        "WHERE name NOT GLOB 'sqlite_*' OR type='index' ORDER BY type, name")
    return tuple((*row[:3], None if row[3] is None else ' '.join(row[3].split())) for row in rows)


@lru_cache(maxsize=len(MIGRATIONS) + 1)
def _expected_schema(count):
    connection = sqlite3.connect(':memory:')
    try:
        connection.execute(_MIGRATION_TABLE)
        for _, script in MIGRATIONS[:count]:
            connection.executescript(script)
        return _schema(connection)
    finally:
        connection.close()

if TYPE_CHECKING:
    from ..client import ContextEvaluation, LinkageToken


def _json(value):
    def default(item):
        if is_dataclass(item) and not isinstance(item, type):
            return asdict(item)
        raise TypeError("local field is not JSON serializable")
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False, default=default)


def _source(source):
    return source.kind, canonicalize_source(source.kind, source.identifier)


def _context(token):
    return token.deployment_id, token.voprf_key_version


def _check_token(token, purpose):
    from ..client import LinkageToken
    if type(token) is not LinkageToken or token.purpose != purpose:
        raise ValueError("invalid local linkage token")


class SQLiteStorage:
    _init_lock = RLock()
    """Lazy filesystem adapter, safe for threads and independent local processes.

    Every outer transaction opens/closes its own connection. BEGIN IMMEDIATE
    serializes writers, including first-use migrations. WAL permits concurrent
    readers. Nested writes use savepoints; outer callers retain commit control.
    Use a local filesystem (SQLite WAL does not support network filesystems).
    """

    def __init__(self, path: str | os.PathLike | None = None, *, timeout_seconds: float = 10.0):
        if (type(timeout_seconds) not in (int, float) or not math.isfinite(timeout_seconds)
                or timeout_seconds <= 0):
            raise ValueError("invalid SQLite busy timeout")
        selected = paths.get_context_db_path() if path is None else Path(path).expanduser()
        if '..' in selected.parts:
            raise ValueError('SQLite path must not contain traversal')
        self.path = selected.absolute()
        if os.name == 'nt' and str(self.path).startswith('\\\\'):
            raise ValueError('SQLite requires a local filesystem path')
        self.timeout_seconds = float(timeout_seconds)
        self._state = local()

    @contextmanager
    def transaction(self):
        # Closing our validation descriptors must not release another thread's
        # SQLite POSIX locks. Keep validation and connection lifetime together.
        # Processes still coordinate through SQLite's normal WAL/busy handling.
        with type(self)._init_lock:
            with self._transaction() as connection:
                yield connection

    @contextmanager
    def _transaction(self):
        require_safe_sqlite()
        existing = getattr(self._state, 'connection', None)
        if existing is not None:
            name = 's' + uuid4().hex
            existing.execute(f'SAVEPOINT {name}')
            try:
                yield existing
                existing.execute(f'RELEASE SAVEPOINT {name}')
            except BaseException:
                existing.execute(f'ROLLBACK TO SAVEPOINT {name}')
                existing.execute(f'RELEASE SAVEPOINT {name}')
                raise
            return

        with type(self)._init_lock:
            # Validate ancestors before creating anything. Descriptor walking
            # rejects caller aliases instead of silently resolving them.
            with private_directory(self.path.parent, create=True) as (directory_path, directory_fd):
                require_local_filesystem(directory_path)
                path = directory_path / self.path.name
                self._prepare_file(path, create=True)
                for suffix in ('-wal', '-shm', '-journal'):
                    self._prepare_file(Path(str(path) + suffix))
                connection = sqlite3.connect(
                    path,
                    timeout=self.timeout_seconds,
                    isolation_level=None,
                )

        try:
            connection.execute('PRAGMA trusted_schema=OFF')
            # Extensions are disabled by default; explicitly retain that boundary
            # on Python builds supporting loadable extensions.
            if hasattr(connection, 'enable_load_extension'):
                connection.enable_load_extension(False)
            if hasattr(connection, 'setconfig'):
                connection.setconfig(sqlite3.SQLITE_DBCONFIG_DEFENSIVE, True)
            connection.execute('PRAGMA foreign_keys=ON')
            if connection.execute('PRAGMA foreign_keys').fetchone()[0] != 1:
                raise RuntimeError('SQLite foreign keys unavailable')
            connection.execute(f'PRAGMA busy_timeout={int(self.timeout_seconds * 1000)}')
            # Only the legacy envelope rebuild needs FK enforcement suspended.
            # Ordinary connections and new databases keep it enabled throughout.
            if (connection.execute('PRAGMA application_id').fetchone()[0] == APPLICATION_ID
                    and _schema(connection) == _expected_schema(1)):
                connection.execute('PRAGMA foreign_keys=OFF')
            connection.execute('BEGIN IMMEDIATE')
            migrated = self._migrate(connection)
            if migrated and connection.execute('PRAGMA foreign_key_check').fetchone() is not None:
                raise ValueError('SQLite migration violated foreign key integrity')
            # Schema creation commits separately: a failed evaluation rolls back
            # all data, while leaving a usable, initialized local database.
            connection.commit()
            connection.execute('PRAGMA foreign_keys=ON')
            if connection.execute('PRAGMA foreign_keys').fetchone()[0] != 1:
                raise RuntimeError('SQLite foreign keys unavailable')
            # Every opener initializes/verifies WAL after ownership validation.
            # A crashed creator may have left an empty or DELETE-mode database.
            deadline = monotonic() + self.timeout_seconds
            while True:
                try:
                    mode = connection.execute('PRAGMA journal_mode=WAL').fetchone()[0]
                    if mode != 'wal':
                        raise ValueError('SQLite requires a WAL-capable local filesystem')
                    break
                except sqlite3.OperationalError as error:
                    if (getattr(error, 'sqlite_errorcode', 0) & 0xff != sqlite3.SQLITE_BUSY
                            or monotonic() >= deadline):
                        raise
                    sleep(0.01)
            connection.execute('BEGIN IMMEDIATE')
            self._state.connection = connection
            try:
                yield connection
                connection.commit()
            except BaseException:
                connection.rollback()
                raise
        finally:
            self._state.connection = None
            connection.close()

    @staticmethod
    def _prepare_file(path, *, create=False):
        flags = os.O_RDWR | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0)
        if create:
            flags |= os.O_CREAT
        if path.is_symlink():
            raise ValueError('SQLite files must not be symlinks')
        try:
            fd = os.open(path, flags, 0o600)
        except FileNotFoundError:
            if create:
                raise
            return
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode):
                raise ValueError('SQLite files must be regular and unshared')
            # SQLite removes WAL/SHM files when the last connection closes.
            # A sidecar unlinked after open is no longer a pathname to validate.
            if not create and info.st_nlink == 0:
                return
            if info.st_nlink != 1:
                raise ValueError('SQLite files must be regular and unshared')
            if os.name == 'posix':
                if info.st_uid != os.getuid():
                    raise ValueError('SQLite files must be user-owned')
                require_safe_acl(fd)
                os.fchmod(fd, 0o600)
        finally:
            os.close(fd)

    @staticmethod
    def _migrate(connection):
        application_id = connection.execute('PRAGMA application_id').fetchone()[0]
        if application_id not in (0, APPLICATION_ID):
            raise ValueError('not an Omneum local database')
        if application_id == 0 and connection.execute('PRAGMA user_version').fetchone()[0] != 0:
            raise ValueError('refusing to initialize an existing unrelated database')
        objects = {row[0] for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE name NOT GLOB 'sqlite_*'")}
        if objects and (application_id != APPLICATION_ID or 'schema_migrations' not in objects):
            raise ValueError('refusing to initialize an existing unrelated database')
        connection.execute(_MIGRATION_TABLE)
        # Validate objects before querying the ledger: a replaced ledger view
        # could itself execute attacker SQL or exhaust resources.
        actual_schema = _schema(connection)
        if actual_schema not in tuple(_expected_schema(n) for n in range(len(MIGRATIONS) + 1)):
            raise ValueError('unsupported or modified SQLite schema')
        applied = dict(connection.execute('SELECT version, checksum FROM schema_migrations'))
        expected = {version: sha256(script.encode()).hexdigest() for version, script in MIGRATIONS}
        if any(version not in expected or checksum != expected[version]
               for version, checksum in applied.items()):
            raise ValueError('unsupported or modified SQLite schema migration')
        if sorted(applied) != [v for v, _ in MIGRATIONS[:len(applied)]]:
            raise ValueError('SQLite migration history is incomplete')
        if _schema(connection) != _expected_schema(len(applied)):
            raise ValueError('unsupported or modified SQLite schema')
        for version, script in MIGRATIONS:
            if version in applied:
                continue
            statement = ''
            for line in script.splitlines(keepends=True):
                statement += line
                if sqlite3.complete_statement(statement):
                    connection.execute(statement)
                    statement = ''
            if statement.strip():
                raise ValueError('incomplete SQLite migration')
            connection.execute('INSERT INTO schema_migrations(version, checksum) VALUES (?, ?)',
                               (version, expected[version]))
        if _schema(connection) != _expected_schema(len(MIGRATIONS)):
            raise ValueError('unsupported or modified SQLite schema')
        connection.execute(f'PRAGMA application_id={APPLICATION_ID}')
        return len(applied) != len(MIGRATIONS)

    def persist_observation(self, *, workspace_id: UUID, observation: Observation,
                            source_token: LinkageToken, claim_token: LinkageToken) -> PersistedObservation:
        if not isinstance(workspace_id, UUID) or type(observation) is not Observation or observation.observation_type != 'assertion':
            raise TypeError('invalid observation persistence arguments')
        _check_token(source_token, LinkagePurpose.SOURCE)
        _check_token(claim_token, LinkagePurpose.CLAIM)
        if _context(source_token) != _context(claim_token):
            raise ValueError('local tokens must use the same deployment and key version')
        ws = str(workspace_id)
        with self.transaction() as connection:
            source_id = self._identity(connection, 'sources', ws, source_token,
                ('source_kind', 'identifier'), _source(observation.source))
            claim = observation.claim
            claim_id = self._identity(connection, 'claims', ws, claim_token,
                ('entity_namespace', 'entity', 'attribute', 'value'),
                (claim.entity_namespace, canonicalize_entity(claim.entity_namespace, claim.entity),
                 claim.attribute, _json(claim.value)))
            oid = str(uuid4())
            connection.execute('''INSERT INTO observations
                (id, workspace_id, local_observation_id, source_id, observation_type, source_owner_id,
                 observed_at, source_modified_at, upstream_known, citations_known, parents_known,
                 retrievals_known, metadata, dependency_signals)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                (oid, ws, observation.observation_id, source_id, 'assertion', observation.source.owner_id,
                 observation.observed_at.isoformat(),
                 None if observation.source_modified_at is None else observation.source_modified_at.isoformat(),
                 observation.upstream_sources is not None, observation.cited_sources is not None,
                 observation.parent_observation_ids is not None, observation.retrievals is not None,
                 _json(observation.metadata), _json(observation.dependency_signals)))
            connection.execute('INSERT INTO assertion_observations VALUES (?, ?)', (oid, claim_id))
            for relationship, references in (('upstream', observation.upstream_sources),
                                              ('citation', observation.cited_sources)):
                for index, reference in enumerate(references or ()):
                    connection.execute('INSERT INTO observation_source_references VALUES (?, ?, ?, ?, ?)',
                                       (oid, relationship, index, *_source(reference)))
            for index, parent in enumerate(observation.parent_observation_ids or ()):
                connection.execute('INSERT INTO observation_parents VALUES (?, ?, ?, ?, NULL)',
                                   (ws, oid, index, parent))
            for index, retrieval in enumerate(observation.retrievals or ()):
                connection.execute('INSERT INTO observation_retrievals VALUES (?, ?, ?, ?, ?, ?, ?)',
                    (oid, index, retrieval.retrieval_id, retrieval.kind, retrieval.resource_id,
                     retrieval.retrieved_at.isoformat(), _json(retrieval.fields)))
        return PersistedObservation(workspace_id, UUID(source_id), UUID(claim_id), UUID(oid))

    def load_assertions(self, *, workspace_id: UUID, evaluation_run_id: UUID | None = None) -> tuple[Observation, ...]:
        """Reconstruct assertion history, explicitly excluding future/missing subtypes."""
        from datetime import datetime
        from ..information import Retrieval, SourceReference

        if not isinstance(workspace_id, UUID):
            raise TypeError('workspace_id must be a UUID')
        if evaluation_run_id is not None and not isinstance(evaluation_run_id, UUID):
            raise TypeError('evaluation_run_id must be a UUID')
        with self.transaction() as connection:
            cursor = connection.execute('''SELECT o.*, s.source_kind, s.identifier,
                c.entity_namespace, c.entity, c.attribute, c.value
                FROM assertion_observation_envelopes o
                JOIN sources s ON s.id=o.source_id
                JOIN claims c ON c.id=o.claim_id AND c.workspace_id=o.workspace_id
                WHERE o.workspace_id=? AND (? IS NULL OR o.evaluation_run_id=?)
                ORDER BY o.created_at, o.id''',
                (str(workspace_id), None if evaluation_run_id is None else str(evaluation_run_id),
                 None if evaluation_run_id is None else str(evaluation_run_id)))
            cursor.row_factory = sqlite3.Row
            result = []
            for row in cursor.fetchall():
                oid = row['id']
                def references(relationship, known):
                    if not row[known]:
                        return None
                    return tuple(SourceReference(*r) for r in connection.execute(
                        'SELECT source_kind, identifier FROM observation_source_references '
                        'WHERE observation_id=? AND relationship=? ORDER BY position', (oid, relationship)))
                parents = None if not row['parents_known'] else tuple(r[0] for r in connection.execute(
                    'SELECT local_parent_id FROM observation_parents WHERE observation_id=? ORDER BY position', (oid,)))
                retrievals = None if not row['retrievals_known'] else tuple(
                    Retrieval(r[0], r[1], r[2], datetime.fromisoformat(r[3]), json.loads(r[4]))
                    for r in connection.execute('SELECT local_retrieval_id, kind, resource_id, retrieved_at, fields '
                        'FROM observation_retrievals WHERE observation_id=? ORDER BY position', (oid,)))
                result.append(Observation(
                    observation_id=row['local_observation_id'],
                    source=Source(row['source_kind'], row['identifier'], owner_id=row['source_owner_id']),
                    claim=Claim(row['entity_namespace'], row['entity'], row['attribute'], json.loads(row['value'])),
                    observed_at=datetime.fromisoformat(row['observed_at']),
                    source_modified_at=None if row['source_modified_at'] is None else datetime.fromisoformat(row['source_modified_at']),
                    upstream_sources=references('upstream', 'upstream_known'),
                    cited_sources=references('citation', 'citations_known'),
                    parent_observation_ids=parents, retrievals=retrievals,
                    metadata=json.loads(row['metadata']), dependency_signals=json.loads(row['dependency_signals']),
                ))
            return tuple(result)

    @staticmethod
    def _identity(connection, table, workspace, token, columns, semantics):
        # Identifiers cannot be bound as values: enforce the complete allowlist.
        allowed = {'sources': ('source_kind', 'identifier'),
                   'claims': ('entity_namespace', 'entity', 'attribute', 'value')}
        if table not in allowed or columns != allowed[table]:
            raise ValueError('unsupported SQLite identity columns')
        column_names = ', '.join(columns)
        row = connection.execute(f'''SELECT id, {column_names} FROM {table}
            WHERE workspace_id=? AND deployment_id=? AND key_version=? AND {table[:-1]}_token=?''',
            (workspace, *_context(token), token.value)).fetchone()
        if row is not None:
            if tuple(row[1:]) != semantics:
                raise ValueError('local linkage identity has inconsistent semantics')
            return row[0]
        identity = str(uuid4())
        placeholders = ', '.join('?' for _ in range(5 + len(columns)))
        connection.execute(f'''INSERT INTO {table}
            (id, workspace_id, deployment_id, key_version, {table[:-1]}_token, {column_names})
            VALUES ({placeholders})''', (identity, workspace, *_context(token), token.value, *semantics))
        return identity

    def persist_evaluation(self, *, workspace_id: UUID, evaluation: ContextEvaluation,
                           source_tokens: Mapping[Source, LinkageToken],
                           claim_tokens: Mapping[Claim, LinkageToken],
                           estimator: DependencyEstimatorConfig) -> UUID:
        from ..client import ContextEvaluation
        if not isinstance(workspace_id, UUID) or type(evaluation) is not ContextEvaluation:
            raise TypeError('invalid evaluation persistence arguments')
        if type(estimator) is not DependencyEstimatorConfig:
            raise TypeError('invalid dependency estimator')
        if estimator.dependency_cluster_threshold != evaluation.dependency_cluster_threshold:
            raise ValueError('estimator threshold does not match evaluation')
        sources = {_source(source): token for source, token in source_tokens.items()}
        if len(sources) != len(source_tokens) or set(sources) != {_source(r.source) for r in evaluation.source_reliability}:
            raise ValueError('source tokens must exactly cover evaluation sources')
        if set(claim_tokens) != {r.claim for r in evaluation.claim_support}:
            raise ValueError('claim tokens must exactly cover evaluation claims')
        contexts = set()
        for tokens, purpose in ((sources.values(), LinkagePurpose.SOURCE),
                                (claim_tokens.values(), LinkagePurpose.CLAIM)):
            values = set()
            for token in tokens:
                _check_token(token, purpose)
                if token.value in values:
                    raise ValueError('distinct identities share a local linkage token')
                values.add(token.value)
                contexts.add(_context(token))
        if len(contexts) != 1:
            raise ValueError('local tokens must use the same deployment and key version')
        ws, run = str(workspace_id), str(uuid4())
        with self.transaction() as connection:
            def lookup(table, token):
                if table not in ('sources', 'claims'):
                    raise ValueError('unsupported SQLite identity table')
                row = connection.execute(f'''SELECT id FROM {table}
                    WHERE workspace_id=? AND deployment_id=? AND key_version=? AND {table[:-1]}_token=?''',
                    (ws, *_context(token), token.value)).fetchone()
                if row is None:
                    raise ValueError('evaluation identity is not persisted in this workspace')
                return row[0]
            source_ids = {key: lookup('sources', token) for key, token in sources.items()}
            claim_ids = {claim: lookup('claims', token) for claim, token in claim_tokens.items()}
            parameters = _json({'estimator': asdict(estimator), 'convergence': asdict(evaluation.convergence),
                                'evaluation_latency_ms': evaluation.evaluation_latency_ms})
            connection.execute('''INSERT INTO evaluation_runs
                (id, workspace_id, algorithm, algorithm_version, status, parameters)
                VALUES (?, ?, 'BRAID', ?, 'completed', ?)''',
                (run, ws, evaluation.convergence.algorithm_version, parameters))
            for result in evaluation.source_reliability:
                connection.execute('INSERT INTO source_scores VALUES (?, ?, ?, ?)',
                    (ws, run, source_ids[_source(result.source)], result.reliability))
            for result in evaluation.claim_support:
                cid = claim_ids[result.claim]
                connection.execute('INSERT INTO claim_scores VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                    (ws, run, cid, result.support, result.agreement_weight, result.is_attribute_max_support,
                     result.supporting_source_count, result.estimated_independent_support_count,
                     None if result.dependency_clusters is None else len(result.dependency_clusters),
                     result.dependency_signal_coverage))
                for supporter in result.supporting_sources:
                    connection.execute('INSERT INTO claim_support_sources VALUES (?, ?, ?, ?, ?, ?)',
                        (ws, run, cid, source_ids[_source(supporter.source)],
                         supporter.independence, supporter.contribution))
                for conflict in result.conflicting_claims:
                    connection.execute('INSERT INTO claim_conflicts VALUES (?, ?, ?, ?, ?)',
                        (ws, run, cid, claim_ids[conflict.claim], conflict.support))
            for pair in evaluation.pairwise_dependencies:
                a, b = source_ids[_source(pair.source_a)], source_ids[_source(pair.source_b)]
                evidence = None if pair.evidence is None else asdict(pair.evidence)
                if a > b:
                    a, b = b, a
                    if evidence is not None:
                        for left, right in (('source_a_upstream_of_source_b', 'source_b_upstream_of_source_a'),
                                            ('source_a_cites_source_b', 'source_b_cites_source_a'),
                                            ('source_a_parent_count', 'source_b_parent_count')):
                            evidence[left], evidence[right] = evidence[right], evidence[left]
                connection.execute('INSERT INTO source_dependencies VALUES (?, ?, ?, ?, ?, ?, ?)',
                    (ws, run, a, b, pair.dependency, pair.weighted_signal_coverage,
                     _json({'signals': asdict(pair.signals), 'evidence': evidence})))
        return UUID(run)

    def persist_context(self, *, evaluation, workspace_id, occurrences,
                        source_tokens, claim_tokens, estimator) -> None:
        with self.transaction() as connection:
            stored = [self.persist_observation(workspace_id=workspace_id, observation=observation,
                      source_token=source, claim_token=claim) for observation, source, claim in occurrences]
            run = self.persist_evaluation(workspace_id=workspace_id, evaluation=evaluation,
                source_tokens=source_tokens, claim_tokens=claim_tokens, estimator=estimator)
            local_ids = {o.observation_id: str(s.observation_id)
                         for (o, _, _), s in zip(occurrences, stored, strict=True)}
            if len(local_ids) != len(stored):
                raise ValueError('observation IDs must be unique within an evaluation')
            for (observation, _, _), persisted in zip(occurrences, stored, strict=True):
                oid = str(persisted.observation_id)
                connection.execute('UPDATE observations SET evaluation_run_id=? WHERE id=?', (str(run), oid))
                for parent in observation.parent_observation_ids or ():
                    connection.execute('''UPDATE observation_parents SET parent_observation_id=?
                        WHERE observation_id=? AND local_parent_id=?''', (local_ids.get(parent), oid, parent))
