"""Exercise an installed core wheel with a disposable same-UID fixture daemon.

Run with a fresh venv's python -I outside the checkout. This is a functional
stdio/VOPRF probe, not protected service installation or isolation acceptance.
"""
import argparse
import asyncio
from importlib import metadata, util
import inspect
from dataclasses import fields, is_dataclass
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import re
import runpy
from unittest.mock import patch


def public_signature(value):
    # Callable defaults identify the function, not a process-specific address.
    return re.sub(r'<function (\w+) at 0x[0-9a-fA-F]+>', r'\1', str(inspect.signature(value)))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--daemon", type=Path, required=True)
    parser.add_argument("--fixture-helper", type=Path, required=True)
    parser.add_argument("--allow-crypto", action="store_true", help="independent official-SDK interoperability probe")
    parser.add_argument("--repository", type=Path, help="also exercise this checkout's README examples")
    parser.add_argument("--report", type=Path, help="write interface schemas and acceptance results to a new file")
    args = parser.parse_args()
    if args.report and args.report.exists():
        parser.error("report destination must be a new file")
    import omneum
    import omneum.mcp
    import omneum_oprf
    from omneum.base64url import encode_unpadded, decode_unpadded
    from omneum.oprf import VOPRFClient, VOPRFEvaluation
    from omneum._crypto import CryptoDependencyError
    from omneum.mcp.client.auth.extensions.client_credentials import SignedJWTParameters
    assert metadata.version("omneum") == omneum.__version__
    for module in (omneum, omneum.mcp, omneum_oprf):
        assert Path(module.__file__).resolve().is_relative_to(Path(sys.prefix).resolve()), module.__file__
    if args.allow_crypto:
        from mcp import ClientSession, StdioServerParameters, stdio_client
    else:
        from omneum.mcp import ClientSession, StdioServerParameters, stdio_client
        assert util.find_spec("mcp") is None
        assert util.find_spec("cryptography") is None
        try:
            asyncio.run(SignedJWTParameters(issuer="client", subject="client", signing_key="unused")
                        .create_assertion_provider()("https://account.example.test"))
        except CryptoDependencyError:
            pass
        else:
            raise AssertionError("missing crypto backend did not fail explicitly")
    os.environ["OMNEUM_TEST_DAEMON"] = str(args.daemon.resolve())
    spec = util.spec_from_file_location("fixture_daemon", args.fixture_helper)
    helper = util.module_from_spec(spec)
    spec.loader.exec_module(helper)
    fixture = helper.FixtureDaemon(b"\x01" + b"\0" * 31)
    report = {"sdk_exports": {}, "client_methods": {name: public_signature(value)
              for name, value in inspect.getmembers(omneum.OmneumClient, inspect.isfunction)
              if not name.startswith('_')}}
    for name in omneum.__all__:
        value = getattr(omneum, name)
        try:
            signature = public_signature(value)
        except (TypeError, ValueError):
            signature = None
        report['sdk_exports'][name] = dict(module=getattr(value, '__module__', None), signature=signature)
        if inspect.isclass(value) and is_dataclass(value):
            report['sdk_exports'][name]['fields'] = {field.name: str(field.type) for field in fields(value)}
    try:
        with tempfile.TemporaryDirectory(prefix="omneum-core-probe-") as temporary:
            root = Path(temporary).resolve()
            root.chmod(0o700)
            config = root / "config"
            config.mkdir(mode=0o700)
            deployment = "urn:uuid:8d96fc18-f40f-4ec7-8ae8-f3711d88b741"
            (config / "config.toml").write_text(
                f'deployment_id = "{deployment}"\nvoprf_key_version = 1\n'
                f'voprf_public_key = "{encode_unpadded(fixture.public_key, expected_length=32)}"\n')
            environment = {key: value for key, value in os.environ.items()
                           if not key.startswith(("OMNEUM_", "PYTHON"))}
            environment.update(OMNEUM_CONFIG_DIR=str(config), OMNEUM_DAEMON_SOCKET=str(fixture.socket),
                               OMNEUM_DAEMON_UID=str(os.getuid()))
            environment['PATH'] = str(Path(sys.executable).parent) + os.pathsep + environment.get('PATH', '')
            parameters = StdioServerParameters(command=sys.executable, args=["-I", "-m", "omneum.server"],
                                               env=environment, cwd=root)

            async def probe():
                async with stdio_client(parameters) as (read, write):
                    async with ClientSession(read, write) as session:
                        initialized = await session.initialize()
                        assert initialized.serverInfo.name == "Omneum"
                        tools = await session.list_tools()
                        report['mcp_tools'] = [tool.model_dump(mode='json') for tool in tools.tools]
                        assert {tool.name for tool in tools.tools} == {"ping", "evaluate_voprf", "evaluate_context"}
                        ping = await session.call_tool("ping")
                        assert not ping.isError and ping.structuredContent["status"] == "ok"
                        client = VOPRFClient(fixture.public_key)
                        message = b"fresh public-wheel MCP probe"
                        blinded = client.blind(message)
                        request = dict(protocol_version="1", deployment_id=deployment, voprf_key_version=1,
                                       voprf_mode="voprf", voprf_ciphersuite="ristretto255-SHA512",
                                       linkage_encoding_version="1",
                                       blinded_element=encode_unpadded(blinded.blinded_element, expected_length=32))
                        # Read the exact existing contract constants, not a second protocol definition.
                        from omneum.config import PROTOCOL_VERSION
                        from omneum.linkage import ENCODING_VERSION
                        request.update(protocol_version=PROTOCOL_VERSION, linkage_encoding_version=ENCODING_VERSION)
                        result = await session.call_tool("evaluate_voprf", request)
                        assert not result.isError, result
                        data = result.structuredContent
                        evaluated = VOPRFEvaluation(
                            evaluated_element=decode_unpadded(data["evaluated_element"], expected_length=32),
                            proof=decode_unpadded(data["proof"], expected_length=64))
                        assert len(client.finalize(input_data=message, client_state=blinded.client_state,
                                                   evaluation=evaluated)) == 64
                        rejected = await session.call_tool("evaluate_voprf", {**request, "blinded_element": "invalid"})
                        assert rejected.isError
                from omneum import OmneumClientConfig, open_stdio_client
                client_config = OmneumClientConfig(deployment_id=deployment, voprf_key_version=1,
                    voprf_mode="voprf", voprf_ciphersuite="ristretto255-SHA512",
                    linkage_encoding_version=ENCODING_VERSION, voprf_public_key=fixture.public_key)
                from omneum.contributor import create_server
                with patch.dict(os.environ, environment, clear=True):
                    contributor = create_server(config=client_config, parameters=parameters)
                    report['contributor_tools'] = [tool.model_dump(mode='json')
                                                   for tool in await contributor.list_tools()]
                async with open_stdio_client(client_config, parameters, local_persistence=None) as client:
                    linked = await client.link_claim("service", "probe", "status", "verified")
                    assert len(linked.value) == 64
                if args.repository:
                    from omneum import paths, SQLiteStorage
                    blocks = re.findall(r'```python\n(.*?)```', (args.repository / 'README.md').read_text(), re.S)
                    namespace = {'__name__': 'installed_readme'}
                    # Execute the actual mapping and preparation quick-start,
                    # routing its default graph into this disposable directory.
                    # Route the documented stdio command to this fixture's
                    # explicit environment, never the host's installed service.
                    parameter_type = omneum.mcp.StdioServerParameters
                    def fixture_parameters(**kwargs):
                        assert kwargs == {'command': 'omneum-server'}
                        if sys.platform == 'darwin':
                            return parameter_type(command=str(Path(sys.executable).parent / 'omneum-server'),
                                                  env=environment, cwd=root)
                        return parameters
                    with patch.dict(os.environ, environment, clear=True), patch.object(
                            paths, 'get_context_db_path', lambda: root / 'graph/omneum.db'), patch.object(
                            omneum.mcp, 'StdioServerParameters', fixture_parameters):
                        exec(compile(blocks[0], 'README.md:mapping', 'exec'), namespace)
                        exec(compile(blocks[1], 'README.md:preparation', 'exec'), namespace)
                        await namespace['main']()
                        await namespace['main']()  # close/reopen the same persisted graph
                        exec(compile(blocks[2], 'README.md:routing', 'exec'), namespace)
                        demo = runpy.run_path(str(args.repository / 'examples/context_quality_demo/before_after.py'))
                        result = demo['main']()
                        assert (len(result['raw_rag']['selected_chunk_ids']), result['raw_rag']['token_usage']) == (3, 75)
                        assert (len(result['omneum']['selected_chunk_ids']), result['omneum']['token_usage']) == (2, 51)
                        with SQLiteStorage(root / 'graph/omneum.db').transaction() as database:
                            assert database.execute('PRAGMA integrity_check').fetchone() == ('ok',)
                            assert not database.execute('PRAGMA foreign_key_check').fetchall()
                            assert database.execute('SELECT count(*) FROM evaluation_runs').fetchone() == (2,)
                            assert database.execute('SELECT count(*) FROM execution_history').fetchone() == (2,)
                            report['sqlite_tables'] = [row[0] for row in database.execute(
                                "SELECT name FROM sqlite_schema WHERE type='table' ORDER BY name")]

            asyncio.run(probe())
            subprocess.run([str(Path(sys.executable).parent / "omneum"), "--help"],
                           cwd=root, env=environment, check=True, capture_output=True, timeout=30)
            for command in ('init', 'install', 'network'):
                subprocess.run([str(Path(sys.executable).parent / 'omneum'), command, '--help'],
                               cwd=root, env=environment, check=True, capture_output=True, timeout=30)
            report['entry_points'] = {entry.name: entry.value for entry in
                metadata.distribution('omneum').entry_points if entry.group == 'console_scripts'}
            for entry in metadata.distribution('omneum').entry_points:
                if entry.group == 'console_scripts':
                    assert callable(entry.load())
            report.update({"python": sys.version.split()[0], "machine": __import__('platform').machine(),
                "version": metadata.version('omneum'),
                "installed_core": True, "official_peer": args.allow_crypto,
                "initialize": True, "tools_list": True, "tools_call": True,
                "voprf_finalize": True, "invalid_request_rejected": True,
                "high_level_client": True, "cli_help": True,
                "readme_and_persistence": bool(args.repository),
                "protected_installation": "not exercised"})
            if args.report:
                with args.report.open('x') as output:
                    output.write(json.dumps(report, indent=2) + '\n')
            print(json.dumps({key: value for key, value in report.items()
                              if key not in ('sdk_exports', 'client_methods', 'mcp_tools', 'sqlite_tables', 'contributor_tools')}))
    finally:
        fixture.close()


if __name__ == "__main__":
    main()
