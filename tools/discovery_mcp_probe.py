"""Real MCPB connector + protected foreground-daemon probe, inside disposable container only."""
import asyncio
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import pwd

from mcp import ClientSession, StdioServerParameters, stdio_client
from omneum import (ContextMapper, DependencyEstimatorConfig, OmneumClientConfig,
                    Source, open_stdio_client)


async def main():
    assert os.geteuid() == pwd.getpwnam('omneum-mcp').pw_uid
    assert __import__('importlib.metadata', fromlist=['version']).version('omneum') == '1.0.3'
    key = Path('/var/lib/omneumd/voprf.key')
    try:
        key.open('rb')
    except PermissionError:
        pass
    else:
        raise AssertionError('MCP principal can read the evaluator private key')
    directory = '/opt/omneum-discovery/mcpb'
    manifest = json.loads(Path(directory, 'manifest.json').read_text())
    command = manifest['server']['mcp_config']
    args = [value.replace('${__dirname}', directory).replace(
        '${user_config.server_path}', '/opt/omneum-discovery/omneum-server') for value in command['args']]
    server = StdioServerParameters(command=command['command'], args=args,
        env={'OMNEUM_CONFIG_DIR': os.environ['OMNEUM_CONFIG_DIR']})
    async with stdio_client(server) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            names = sorted(t.name for t in tools.tools)
            assert names == ['evaluate_context', 'evaluate_voprf', 'ping'], names
            await session.list_resources()
            await session.list_prompts()
            result = await session.call_tool('ping')
            assert not result.isError and result.structuredContent['status'] == 'ok'
    config = OmneumClientConfig.from_local_deployment()
    mapper = ContextMapper(source=lambda r: Source(kind='web_document', identifier=r['url']),
        entity_namespace=lambda r: 'discovery', entity=lambda r: 'probe',
        attribute=lambda r: 'status', value='value', observation_id='id',
        observed_at=lambda r: datetime.now(timezone.utc))
    records = [{'id': 'discovery-a', 'url': 'https://example.com/a', 'value': 'verified'},
               {'id': 'discovery-b', 'url': 'https://example.org/b', 'value': 'verified'}]
    estimator = DependencyEstimatorConfig(upstream_weight=.25, citation_weight=.20,
        assertion_lineage_weight=.20, ownership_weight=.10, temporal_weight=.10,
        graph_weight=.15, temporal_window_seconds=7200.)
    async with open_stdio_client(config, server=server) as client:
        assert client._network_contribution is None
        result = await client.evaluate_mapped(records, mapper, estimator=estimator)
        assert result.claim_support and len(result.source_reliability) == 2
    print(json.dumps({'status': 'passed', 'tools': names, 'transport': 'stdio',
        'private_key_read': 'denied', 'network_contribution': 'disabled',
        'mode': 'protected foreground; no test-daemon feature', 'evaluation': 'verified VOPRF and context', 'package_version': '1.0.3',
        'configuration_source': 'manifest substitutions', 'architecture': __import__('platform').machine()}))


if __name__ == '__main__':
    asyncio.run(main())
