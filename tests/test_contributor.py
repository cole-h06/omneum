"""Local MCP adapter delegates to the existing SDK, without live Network calls."""
import asyncio
from datetime import datetime, timezone

import pytest

from omneum.contributor import AssertionInput, evaluate, network_configuration
from omneum.contribution.network import OmneumNetwork
from omneum.client import OmneumClient
from test_local_persistence import runtime
from test_storage_evaluation import computed
from test_client_contribution import network


@pytest.mark.parametrize('environ', [{}, {'OMNEUM_API_KEY': 'unused'},
    {'OMNEUM_NETWORK_CONTRIBUTION': 'false', 'OMNEUM_API_KEY': 'unused'}])
def test_opt_out_never_constructs_network(environ, monkeypatch):
    monkeypatch.setattr(OmneumNetwork, 'pseudonymous', lambda **kw: pytest.fail('opt-out contacted Network'))
    assert network_configuration(environ) is None


def test_opt_in_uses_existing_factory(monkeypatch):
    expected = object()
    calls = []
    def factory(**kw):
        calls.append(kw)
        return expected
    monkeypatch.setattr(OmneumNetwork, 'pseudonymous', factory)
    assert network_configuration({'OMNEUM_NETWORK_CONTRIBUTION': 'true',
                                  'OMNEUM_API_KEY': 'disposable-test-key'}) is expected
    assert calls == [dict(api_key='disposable-test-key')]


@pytest.mark.parametrize('environ', [{'OMNEUM_NETWORK_CONTRIBUTION': 'true'},
    {'OMNEUM_NETWORK_CONTRIBUTION': 'yes', 'OMNEUM_API_KEY': 'disposable-test-key'}])
def test_incomplete_opt_in_fails_closed(environ):
    with pytest.raises(ValueError):
        network_configuration(environ)


def test_unprovisioned_network_fails_closed(monkeypatch):
    monkeypatch.setattr('omneum.contribution.network._PRODUCTION_NETWORK', None)
    with pytest.raises(RuntimeError, match='not provisioned'):
        network_configuration({'OMNEUM_NETWORK_CONTRIBUTION': 'true', 'OMNEUM_API_KEY': 'disposable-test-key'})


def inputs(observations):
    return [AssertionInput(observation_id=o.observation_id,
        source_kind=o.source.kind, source_identifier=o.source.identifier,
        entity_namespace=o.claim.entity_namespace, entity=o.claim.entity,
        attribute=o.claim.attribute, value=o.claim.value,
        observed_at=o.observed_at) for o in observations]


def test_enabled_adapter_uses_real_pipeline(runtime, network):
    client = OmneumClient(runtime[0], runtime[1], local_persistence=None, network_contribution=network[0])
    result = asyncio.run(evaluate(client, inputs(runtime[2]), runtime[3], True))
    assert result['network_contribution'] == 'submitted'
    assert len(network[2]) == 1
    # Only occurrences supplied to this call enter the allowlisted payload.
    assert len(network[2][0].observations) == len(runtime[2])


def test_network_outage_preserves_local_context(runtime, network, tmp_path):
    from omneum.local_persistence import LocalPersistenceConfig
    from omneum.storage import SQLiteStorage
    import sqlite3
    path = tmp_path / 'context.db'
    async def unavailable(**kw):
        raise RuntimeError('private-credential')
    # Network evaluator failure happens after local persistence.
    from dataclasses import replace
    class Unavailable:
        evaluate = staticmethod(unavailable)
    config = replace(network[0], evaluator=Unavailable())
    client = OmneumClient(runtime[0], runtime[1],
        local_persistence=LocalPersistenceConfig(storage=SQLiteStorage(path)), network_contribution=config)
    result = asyncio.run(evaluate(client, inputs(runtime[2]), runtime[3], True))
    assert result['network_contribution'] == 'failed_or_uncertain'
    assert result['source_reliability']
    assert not network[2]
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT count(*) FROM observations').fetchone()[0] == len(runtime[2])
    assert 'private-credential' not in str(result)


def test_adapter_input_rejects_export_and_unallowlisted_fields():
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        AssertionInput(observation_id='new', source_kind='url', source_identifier='https://example.test',
            entity_namespace='url', entity='https://example.test', attribute='title', value='test',
            observed_at=datetime.now(timezone.utc), export_context_graph=True)


@pytest.mark.parametrize('enabled', [False, True])
def test_real_mcp_adapter_keeps_local_results(tmp_path, computed, enabled):
    import os
    import sys
    from mcp import ClientSession, StdioServerParameters, stdio_client
    from stdio_state import isolated_deployment_environment
    from test_client import DEPLOYMENT_ID, PRIVATE_KEY
    import json

    environment, _, _ = isolated_deployment_environment(tmp_path, DEPLOYMENT_ID, PRIVATE_KEY)
    environment['XDG_DATA_HOME'] = str(tmp_path / 'data')
    environment['OMNEUM_NETWORK_CONTRIBUTION'] = 'true' if enabled else 'false'
    environment['OMNEUM_API_KEY'] = 'disposable-test-key'
    # Mock only Network provisioning/I/O. Local stdio, VOPRF, inference and
    # SQLite persistence run for real. No paid calls or production pins.
    script = '''
import sys
from mcp import StdioServerParameters
from omneum.contributor import create_server, local_environment
from omneum.contribution.network import OmneumNetwork
from omneum.contribution.config import NetworkContributionConfig, HTTPSContributionTransport
from omneum.contribution.linkage import NetworkLinkageConfig
from omneum.daemon import DaemonServerContext
import os
class Offline:
    async def evaluate(self, **kw):
        raise RuntimeError('Network unavailable')
if os.environ['OMNEUM_NETWORK_CONTRIBUTION'] == 'true':
    # Independent Network key supplied by a disposable fixture outside this process.
    import base64
    key = base64.urlsafe_b64decode(os.environ['TEST_NETWORK_KEY'] + '==')
    OmneumNetwork.pseudonymous = staticmethod(lambda **kw: NetworkContributionConfig(
        linkage=NetworkLinkageConfig(1, key), evaluator=Offline(),
        transport=HTTPSContributionTransport('https://unused.example.test', kw['api_key'])))
create_server(parameters=StdioServerParameters(command=sys.executable, args=['-m', 'omneum.server'], env=local_environment())).run()
'''
    from daemon_support import FixtureDaemon
    from omneum.base64url import encode_unpadded
    remote = FixtureDaemon(b'\x02' + bytes(31))
    environment['TEST_NETWORK_KEY'] = encode_unpadded(remote.public_key, expected_length=32)
    async def run():
        parameters = StdioServerParameters(command=sys.executable, args=['-c', script], env=environment)
        async with stdio_client(parameters) as (read, write), ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            assert [tool.name for tool in tools.tools] == ['evaluate_observations']
            from dataclasses import asdict
            result = await session.call_tool('evaluate_observations', {
                'observations': [item.model_dump(mode='json') for item in inputs(computed[4])],
                'estimator': asdict(computed[3]),
            })
            assert not result.isError, result
            value = result.structuredContent or json.loads(result.content[0].text)
            assert value['network_contribution'] == ('failed_or_uncertain' if enabled else 'disabled')
            assert value['source_reliability'] and value['claim_support']
    try:
        asyncio.run(run())
        import sqlite3
        databases = list(tmp_path.rglob('context.db'))
        assert len(databases) == 1
        with sqlite3.connect(databases[0]) as db:
            assert db.execute('SELECT count(*) FROM observations').fetchone()[0] == len(computed[4])
    finally:
        remote.close()


def test_local_backend_never_receives_network_credential(monkeypatch):
    from omneum.contributor import local_environment
    monkeypatch.setenv('OMNEUM_API_KEY', 'disposable-private-key')
    monkeypatch.setenv('OMNEUM_NETWORK_CONTRIBUTION', 'true')
    monkeypatch.setenv('OMNEUM_CONFIG_DIR', '/disposable/config')
    environment = local_environment()
    assert environment['OMNEUM_CONFIG_DIR'] == '/disposable/config'
    assert 'OMNEUM_API_KEY' not in environment
    assert 'OMNEUM_NETWORK_CONTRIBUTION' not in environment


@pytest.mark.parametrize('settings', [
    {'OMNEUM_NETWORK_CONTRIBUTION': 'true'},
    {'OMNEUM_NETWORK_CONTRIBUTION': 'true', 'OMNEUM_API_KEY': 'private-token\ninvalid'},
    {'OMNEUM_NETWORK_CONTRIBUTION': 'true', 'OMNEUM_API_KEY': 'disposable-valid-format'},
    {'OMNEUM_NETWORK_CONTRIBUTION': 'invalid', 'OMNEUM_API_KEY': 'private-token'},
])
def test_configuration_failure_retains_local_evaluation(runtime, settings, monkeypatch):
    from omneum.contributor import create_server
    monkeypatch.setattr('omneum.contribution.network._PRODUCTION_NETWORK', None)
    for name in ('OMNEUM_NETWORK_CONTRIBUTION', 'OMNEUM_API_KEY'):
        monkeypatch.delenv(name, raising=False)
    for name, value in settings.items():
        monkeypatch.setenv(name, value)
    server = create_server(runtime[0])
    # Run the same registered tool against a real SDK client; stdio coverage
    # below also exercises the default command and managed local backend.
    client = OmneumClient(runtime[0], runtime[1], local_persistence=None)
    # Inject only the session context so no installed service is required.
    from contextlib import asynccontextmanager
    @asynccontextmanager
    async def open_client(*args, **kwargs):
        assert kwargs['network_contribution'] is None
        yield client
    monkeypatch.setattr('omneum.contributor.open_stdio_client', open_client)
    async def call():
        async with server.settings.lifespan(server):
            tool = server._tool_manager.get_tool('evaluate_observations')
            result = await tool.fn(inputs(runtime[2]), runtime[3])
            assert result['source_reliability']
            assert result['network_contribution'] == 'configuration_unavailable'
    asyncio.run(call())


def test_tool_errors_do_not_echo_secrets(runtime, monkeypatch, caplog):
    from dataclasses import asdict
    from omneum.contributor import create_server
    monkeypatch.setenv('OMNEUM_NETWORK_CONTRIBUTION', 'false')
    server = create_server(runtime[0])
    arguments = {'observations': [item.model_dump(mode='json') for item in inputs(runtime[2])],
                 'estimator': asdict(runtime[3])}
    arguments['observations'][0]['api_key'] = 'private-secret-in-validation-input'
    result = asyncio.run(server.call_tool('evaluate_observations', arguments))
    assert result.isError
    assert 'private-secret-in-validation-input' not in result.model_dump_json() + caplog.text
    assert server._tool_manager.get_tool('evaluate_observations').parameters['additionalProperties'] is False


@pytest.mark.parametrize('failure', ['authentication', 'proof'])
def test_network_rejection_never_uploads_raw_data_or_breaks_local_result(runtime, network, failure, monkeypatch):
    from omneum.oprf import VOPRFEvaluation
    original = network[0].evaluator.evaluate
    blinded = []
    async def reject(**kw):
        blinded.append(kw['blinded_element'])
        if failure == 'authentication':
            raise RuntimeError('HTTP 401 private-disposable-token')
        response = await original(**kw)
        return VOPRFEvaluation(response.evaluated_element, b'\xff' * 64)
    monkeypatch.setattr(network[0].evaluator, 'evaluate', reject)
    client = OmneumClient(runtime[0], runtime[1], local_persistence=None, network_contribution=network[0])
    result = asyncio.run(evaluate(client, inputs(runtime[2]), runtime[3], True))
    assert result['network_contribution'] == 'failed_or_uncertain'
    assert result['claim_support']
    assert all(len(value) == 32 for value in blinded)
    assert not network[2]
    assert 'private-disposable-token' not in str(result)


def test_current_occurrences_only_and_wire_privacy(runtime, network, tmp_path):
    from omneum.local_persistence import LocalPersistenceConfig
    from omneum.storage import SQLiteStorage
    from dataclasses import replace
    storage = LocalPersistenceConfig(storage=SQLiteStorage(tmp_path / 'context.db'))
    # Seed history through the normal pipeline with Network disabled.
    from omneum.information import Claim
    old = tuple(replace(o, claim=Claim(o.claim.entity_namespace, o.claim.entity,
        o.claim.attribute, 'historic-' + str(o.claim.value))) for o in runtime[2])
    asyncio.run(OmneumClient(runtime[0], runtime[1], local_persistence=storage).evaluate_context(old, estimator=runtime[3]))
    client = OmneumClient(runtime[0], runtime[1], local_persistence=storage, network_contribution=network[0])
    asyncio.run(evaluate(client, inputs(runtime[2]), runtime[3], True))
    assert len(network[2]) == 1
    wire = network[2][0].model_dump_json()
    assert len(network[2][0].observations) == len(runtime[2])
    for observation in runtime[2]:
        for private in (observation.source.identifier,
                        observation.claim.entity, str(observation.claim.value), 'historic-',
                        'metadata', 'retrieved_text'):
            assert private not in wire


@pytest.mark.parametrize('mode', ['local', 'missing', 'invalid', 'unprovisioned'])
def test_documented_mcp_json_runs_entrypoint(tmp_path, computed, mode):
    """Launch the console entrypoint from an ordinary MCP JSON configuration."""
    import json
    import os
    from pathlib import Path
    import sys
    import tomllib
    from dataclasses import asdict
    from mcp import ClientSession, StdioServerParameters, stdio_client
    from stdio_state import isolated_deployment_environment
    from test_client import DEPLOYMENT_ID, PRIVATE_KEY

    environment, _, config_file = isolated_deployment_environment(tmp_path, DEPLOYMENT_ID, PRIVATE_KEY)
    environment['OMNEUM_CONFIG_DIR'] = str(config_file.parent)
    # Generate the normal console-script launcher from the declared package
    # entrypoint, without modifying the user's installed runtime.
    target = tomllib.loads(Path('pyproject.toml').read_text())['project']['scripts']['omneum-contributor']
    module, function = target.split(':')
    bin_dir = tmp_path / 'bin'
    bin_dir.mkdir()
    command = bin_dir / 'omneum-contributor'
    command.write_text(f'#!{sys.executable}\nfrom {module} import {function}\n{function}()\n')
    command.chmod(0o700)
    environment['PATH'] = str(bin_dir) + os.pathsep + environment['PATH']
    flag = 'false' if mode == 'local' else 'true'
    settings = {'OMNEUM_NETWORK_CONTRIBUTION': flag}
    if mode in ('invalid', 'unprovisioned'):
        settings['OMNEUM_API_KEY'] = 'invalid-private-test-token\n' if mode == 'invalid' else 'YOUR_NETWORK_API_CREDENTIAL'
    import re
    section = Path('docs/guides/configuration.md').read_text().split('### Enable Network contribution (MCP)', 1)[1].split('### Enable Network contribution (Python SDK)', 1)[0]
    examples = re.findall(r'```json\n(.*?)\n```', section, flags=re.S)
    config = json.loads(examples[0 if mode == 'local' else 1])
    if mode in ('invalid', 'missing'):
        config['mcpServers']['omneum']['env'] = settings
    else:
        assert config['mcpServers']['omneum']['env'] == settings
    # Same JSON shape and command as docs. Production pins intentionally remain
    # unprovisioned; this must not stop the local MCP service.
    selected = json.loads(json.dumps(config))['mcpServers']['omneum']
    parameters = StdioServerParameters(command=selected['command'], env={**environment, **selected['env']})
    async def run():
        with (tmp_path / 'stderr.log').open('w') as stderr:
            async with stdio_client(parameters, errlog=stderr) as (read, write), ClientSession(read, write) as session:
                await session.initialize()
                tools = await session.list_tools()
                assert [tool.name for tool in tools.tools] == ['evaluate_observations']
                result = await session.call_tool('evaluate_observations', {
                    'observations': [item.model_dump(mode='json') for item in inputs(computed[4])],
                    'estimator': asdict(computed[3]),
                })
                assert not result.isError, result
                value = result.structuredContent or json.loads(result.content[0].text)
                assert value['network_contribution'] == ('disabled' if mode == 'local' else 'configuration_unavailable')
                assert value['source_reliability'] and value['claim_support']
                bad = await session.call_tool('evaluate_observations', {
                    'observations': [dict(inputs(computed[4])[0].model_dump(mode='json'),
                                          api_key='unexpected-private-key')],
                    'estimator': asdict(computed[3]),
                })
                assert bad.isError
                assert 'unexpected-private-key' not in bad.model_dump_json()
        assert 'unexpected-private-key' not in (tmp_path / 'stderr.log').read_text()
        assert 'invalid-private-test-token' not in (tmp_path / 'stderr.log').read_text()
    asyncio.run(run())
