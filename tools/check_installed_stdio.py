"""Exercise an installed core wheel with a disposable same-UID fixture daemon.

Run with a fresh venv's python -I outside the checkout. This is a functional
stdio/VOPRF probe, not protected service installation or isolation acceptance.
"""
import argparse
import asyncio
from importlib import metadata, util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--daemon", type=Path, required=True)
    parser.add_argument("--fixture-helper", type=Path, required=True)
    parser.add_argument("--allow-crypto", action="store_true", help="independent official-SDK interoperability probe")
    args = parser.parse_args()
    import omneum
    import omneum.mcp
    import omneum_oprf
    from omneum.base64url import encode_unpadded, decode_unpadded
    from omneum.oprf import VOPRFClient, VOPRFEvaluation
    from omneum._crypto import CryptoDependencyError
    from omneum.mcp.client.auth.extensions.client_credentials import SignedJWTParameters
    assert metadata.version("omneum") == "1.0.3"
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
            parameters = StdioServerParameters(command=sys.executable, args=["-I", "-m", "omneum.server"],
                                               env=environment, cwd=root)

            async def probe():
                async with stdio_client(parameters) as (read, write):
                    async with ClientSession(read, write) as session:
                        initialized = await session.initialize()
                        assert initialized.serverInfo.name == "Omneum"
                        tools = await session.list_tools()
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
                async with open_stdio_client(client_config, parameters, local_persistence=None) as client:
                    linked = await client.link_claim("service", "probe", "status", "verified")
                    assert len(linked.value) == 64

            asyncio.run(probe())
            subprocess.run([str(Path(sys.executable).parent / "omneum"), "--help"],
                           cwd=root, env=environment, check=True, capture_output=True, timeout=30)
            print(json.dumps({"python": sys.version.split()[0], "machine": __import__('platform').machine(),
                "installed_core": True, "official_peer": args.allow_crypto,
                "initialize": True, "tools_list": True, "tools_call": True,
                "voprf_finalize": True, "invalid_request_rejected": True,
                "high_level_client": True, "cli_help": True,
                "protected_installation": "not exercised"}))
    finally:
        fixture.close()


if __name__ == "__main__":
    main()
