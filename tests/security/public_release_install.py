"""Fresh disposable CI host acceptance against installed wheel and prepared assets.

The download boundary is replaced with this run's unpublished release bytes.
Everything after download (checksum, extraction, sudo, services, init, MCP) is real.
Never run on a developer machine or an existing deployment.
"""
import asyncio
import importlib.util
from datetime import datetime, timezone
import os
import json
import hashlib
import socket
import stat
import tempfile
import platform
from pathlib import Path
import sqlite3
import subprocess
import sys
from unittest.mock import patch

from click.testing import CliRunner
from omneum.mcp import ClientSession, StdioServerParameters, stdio_client
from typer.main import get_command
from omneum import ContextMapper, DependencyEstimatorConfig, OmneumClientConfig, Source, open_stdio_client
from omneum import installation
from omneum.cli import app
from omneum.paths import get_context_db_path


def main(assets):
    assert importlib.util.find_spec('mcp') is None, 'core install must use the bundled SDK'
    assert importlib.util.find_spec('cryptography') is None, 'core install must not acquire a crypto backend'
    assert os.geteuid() != 0, 'run as original login user on a fresh disposable CI host'
    key = Path('/var/lib/omneumd/voprf.key' if sys.platform == 'linux' else
               '/Library/Application Support/OmneumCrypto/voprf.key')
    binary = Path('/usr/local/libexec/omneumd' if sys.platform == 'linux' else '/Library/Omneum/omneumd')
    assert not binary.exists(), 'existing installation: use a fresh disposable host'
    assert not Path('/opt/omneum').exists(), 'existing runtime: use a fresh disposable host'
    target = installation.detect_platform()
    version = installation.package_version('omneum')
    _, manifest_url, archive_url = installation.release_assets(version, target)
    def download(url, limit):
        assert url in (manifest_url, archive_url)
        data = (assets / url.rsplit('/', 1)[1]).read_bytes()
        assert len(data) <= limit
        return data
    def install():
        with patch.object(installation, 'download', download):
            result = CliRunner().invoke(get_command(app), ['install'])
        print(result.output, end='')
        assert result.exit_code == 0, result.exception
        assert 'Omneum is ready.' in result.output
    install()
    path = get_context_db_path()
    assert path.is_file(), 'install must automatically create the user Context Graph'
    assert graph_snapshot()['evaluation_runs'] == []
    run_child('--evaluate')
    baseline = graph_snapshot()
    assert len(baseline['sources']) == 2 and len(baseline['claims']) == 1
    assert len(baseline['observations']) == 2 and len(baseline['evaluation_runs']) == 1
    assert baseline == json.loads(run_child('--snapshot')), 'fresh process must reopen identical records'
    verify_migrations(path)
    config = OmneumClientConfig.from_local_deployment()
    path = get_context_db_path()
    def count():
        with sqlite3.connect(path) as database:
            assert not database.execute('PRAGMA foreign_key_check').fetchall()
            return database.execute('SELECT count(*) FROM evaluation_runs').fetchone()[0]
    initial = count()
    assert initial == 1
    assert path.stat().st_mode & 0o777 == 0o600
    stat_command = (['sudo', '-n', '/usr/bin/stat', '-c', '%a', str(key)] if sys.platform == 'linux'
                    else ['sudo', '-n', '/usr/bin/stat', '-f', '%Lp', str(key)])
    assert subprocess.check_output(stat_command, text=True, timeout=10).strip() == '600'
    try:
        key.open('rb')
    except PermissionError:
        pass
    else:
        raise AssertionError('login user can open private evaluator key')
    command = (['sudo', '-n', 'systemctl', 'restart', 'omneumd.service'] if sys.platform == 'linux'
               else ['sudo', '-n', 'launchctl', 'kickstart', '-k', 'system/ai.omneum.omneumd'])
    subprocess.run(command, check=True, timeout=30)
    # Reinstallation waits for readiness, and must preserve the existing key.
    install()
    assert OmneumClientConfig.from_local_deployment() == config
    assert graph_snapshot() == baseline, 'daemon restart/reinstall changed existing graph records'
    assert baseline == json.loads(run_child('--snapshot'))
    run_child('--evaluate')
    assert count() == initial + 1
    # A WAL reader retains its snapshot while four independent writers commit.
    with sqlite3.connect(path) as reader:
        reader.execute('BEGIN')
        before = reader.execute('SELECT count(*) FROM evaluation_runs').fetchone()[0]
        processes = [subprocess.Popen(child_command('--evaluate'), stdout=subprocess.PIPE,
                                     stderr=subprocess.PIPE, text=True) for _ in range(4)]
        for process in processes:
            output, errors = process.communicate(timeout=120)
            assert process.returncode == 0, output + errors
        assert reader.execute('SELECT count(*) FROM evaluation_runs').fetchone()[0] == before
    final = graph_snapshot()
    assert len(final['evaluation_runs']) == 6 and len(final['observations']) == 12
    assert len(final['sources']) == 2 and len(final['claims']) == 1
    for table, rows in baseline.items():
        assert set(rows) <= set(final[table]), (table, 'original records changed')
    assert final == json.loads(run_child('--snapshot'))
    report = dict(platform=platform.system(), architecture=platform.machine(),
                  python=platform.python_version(), result='PASS', automatic_graph_creation=True,
                  source_claim_observation_evaluation=True, daemon_restart=True,
                  process_restart=True, records_intact=True, permissions=True,
                  migrations=True, concurrent_readers_writers=True, network_required=False)
    report_path = os.environ.get('OMNEUM_ACCEPTANCE_REPORT')
    if report_path:
        Path(report_path).write_text(json.dumps(report, indent=2) + '\n')
    print('CONTEXT_GRAPH_ACCEPTANCE ' + json.dumps(report, sort_keys=True))
    print('PASS: real CLI installation, protected VOPRF, MCP ping/assertions, private key denial, SQLite persistence, restart, repeat installation, Network disabled')


TABLES = ('sources', 'claims', 'observations', 'evaluation_runs', 'source_scores',
          'claim_scores', 'source_dependencies')


def local_only():
    from omneum.contribution.network import _PRODUCTION_NETWORK
    from omneum.onboarding import _PRODUCTION_ONBOARDING
    assert _PRODUCTION_NETWORK is None and _PRODUCTION_ONBOARDING is None
    assert not any(name.startswith('OMNEUM_NETWORK') or name == 'OMNEUM_API_KEY'
                   for name in os.environ), 'acceptance requires no Network configuration/credentials'
    def audit(event, args):
        if event == 'socket.connect' and args[0].family in (socket.AF_INET, socket.AF_INET6):
            raise AssertionError('local Context Graph attempted a Network connection')
        if event == 'urllib.Request':
            raise AssertionError('local Context Graph attempted an HTTP request')
    sys.addaudithook(audit)


def child_command(mode):
    return [sys.executable, '-I', str(Path(__file__).resolve()), mode]


def run_child(mode):
    result = subprocess.run(child_command(mode), check=True, capture_output=True,
                            text=True, timeout=120)
    return result.stdout


def graph_snapshot():
    from omneum import SQLiteStorage
    from omneum.storage.schema import APPLICATION_ID, MIGRATIONS
    path = get_context_db_path()
    with SQLiteStorage().transaction() as database:
        assert database.execute('PRAGMA application_id').fetchone() == (APPLICATION_ID,)
        assert database.execute('PRAGMA journal_mode').fetchone() == ('wal',)
        assert database.execute('PRAGMA integrity_check').fetchone() == ('ok',)
        assert not database.execute('PRAGMA foreign_key_check').fetchall()
        assert dict(database.execute('SELECT version, checksum FROM schema_migrations')) == {
            version: hashlib.sha256(script.encode()).hexdigest() for version, script in MIGRATIONS}
        rows = {table: sorted(repr(tuple(row)) for row in database.execute('SELECT * FROM ' + table))
                for table in TABLES}
        for file in (path, Path(str(path) + '-wal'), Path(str(path) + '-shm')):
            if file.exists():
                assert file.stat().st_uid == os.getuid()
                assert stat.S_IMODE(file.stat().st_mode) == 0o600, file
        assert path.parent.stat().st_uid == os.getuid()
        assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700
    return rows


def verify_migrations(path):
    from omneum import SQLiteStorage
    from omneum.storage.schema import APPLICATION_ID, MIGRATIONS
    from omneum.storage.sqlite import _MIGRATION_TABLE
    # Upgrade an actual legacy schema containing a real source from this graph.
    with tempfile.TemporaryDirectory(dir=path.parent, prefix='migration-acceptance-') as temporary:
        legacy = Path(temporary) / 'context.db'
        with sqlite3.connect(path) as source, sqlite3.connect(legacy) as database:
            database.execute(_MIGRATION_TABLE)
            database.executescript(MIGRATIONS[0][1])
            database.execute('INSERT INTO schema_migrations(version,checksum) VALUES (?,?)',
                             (1, hashlib.sha256(MIGRATIONS[0][1].encode()).hexdigest()))
            database.execute('PRAGMA application_id=' + str(APPLICATION_ID))
            row = source.execute('SELECT * FROM sources LIMIT 1').fetchone()
            database.execute('INSERT INTO sources VALUES (' + ','.join('?' for _ in row) + ')', row)
        legacy.chmod(0o600)
        for _ in range(2):
            with SQLiteStorage(legacy).transaction() as database:
                assert tuple(database.execute('SELECT * FROM sources').fetchone()) == row
                assert [r[0] for r in database.execute('SELECT version FROM schema_migrations ORDER BY version')] == [v for v, _ in MIGRATIONS]
                assert not database.execute('PRAGMA foreign_key_check').fetchall()
        with sqlite3.connect(legacy) as database:
            database.execute("UPDATE schema_migrations SET checksum='tampered' WHERE version=1")
        try:
            with SQLiteStorage(legacy).transaction():
                pass
        except ValueError:
            pass
        else:
            raise AssertionError('modified migration history was accepted')
        with sqlite3.connect(legacy) as database:
            assert database.execute('SELECT * FROM sources').fetchone() == row
            assert database.execute('SELECT checksum FROM schema_migrations WHERE version=1').fetchone() == ('tampered',)


def evaluate_local_graph():
    config = OmneumClientConfig.from_local_deployment()
    server = StdioServerParameters(command=str(Path(sys.executable).parent / 'omneum-server'))
    mapper = ContextMapper(source=lambda r: Source(kind='web_document', identifier=r['url']),
                           entity_namespace=lambda r: 'release', entity=lambda r: 'acceptance',
                           attribute=lambda r: 'status', value='value', observation_id='id',
                           observed_at=lambda r: datetime.now(timezone.utc))
    records = [{'id': 'release-1', 'url': 'https://example.com/release-a', 'value': 'verified'},
               {'id': 'release-2', 'url': 'https://example.org/release-b', 'value': 'verified'}]
    estimator = DependencyEstimatorConfig(upstream_weight=0.25, citation_weight=0.20,
        assertion_lineage_weight=0.20, ownership_weight=0.10, temporal_weight=0.10,
        graph_weight=0.15, temporal_window_seconds=7200.0)
    async def acceptance():
        async with stdio_client(server) as (reader, writer):
            async with ClientSession(reader, writer) as session:
                await session.initialize()
                tools = await session.list_tools()
                assert {tool.name for tool in tools.tools} == {'ping', 'evaluate_voprf', 'evaluate_context'}
                result = await session.call_tool('ping')
                assert not result.isError and result.structuredContent['status'] == 'ok'
        async with open_stdio_client(config, server=server) as client:
            assert client._network_contribution is None
            result = await client.evaluate_mapped(records, mapper, estimator=estimator)
            assert result.claim_support
    asyncio.run(acceptance())


if __name__ == '__main__':
    local_only()
    if sys.argv[1] == '--evaluate':
        evaluate_local_graph()
    elif sys.argv[1] == '--snapshot':
        print(json.dumps(graph_snapshot()))
    else:
        try:
            main(Path(sys.argv[1]).resolve())
        except BaseException as error:
            report = dict(platform=platform.system(), architecture=platform.machine(),
                          python=platform.python_version(), result='FAIL',
                          failure_type=type(error).__name__, network_required=False)
            if os.environ.get('OMNEUM_ACCEPTANCE_REPORT'):
                Path(os.environ['OMNEUM_ACCEPTANCE_REPORT']).write_text(json.dumps(report, indent=2) + '\n')
            print('CONTEXT_GRAPH_ACCEPTANCE ' + json.dumps(report, sort_keys=True))
            raise
