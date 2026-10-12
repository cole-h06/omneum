"""Fresh disposable CI host acceptance against installed wheel and prepared assets.

The download boundary is replaced with this run's unpublished release bytes.
Everything after download (checksum, extraction, sudo, services, init, MCP) is real.
Never run on a developer machine or an existing deployment.
"""
import asyncio
import importlib.util
from datetime import datetime, timezone
import os
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
                result = await session.call_tool('ping')
                assert not result.isError and result.structuredContent['status'] == 'ok'
        async with open_stdio_client(config, server=server) as client:
            assert client._network_contribution is None
            result = await client.evaluate_mapped(records, mapper, estimator=estimator)
            assert result.claim_support
    asyncio.run(acceptance())
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
    asyncio.run(acceptance())
    assert count() == initial + 1
    print('PASS: real CLI installation, protected VOPRF, MCP ping/assertions, private key denial, SQLite persistence, restart, repeat installation, Network disabled')


if __name__ == '__main__':
    main(Path(sys.argv[1]).resolve())
