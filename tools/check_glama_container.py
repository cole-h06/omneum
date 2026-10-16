"""Exercise a disposable Glama image: real MCP, VOPRF proof, and key isolation."""
import argparse
import asyncio
from datetime import timedelta
import json
from pathlib import Path
import subprocess
import tomllib
import uuid

from omneum.base64url import decode_unpadded, encode_unpadded
from omneum.config import PROTOCOL_VERSION
from omneum.linkage import ENCODING_VERSION
from omneum.mcp import ClientSession, StdioServerParameters, stdio_client
from omneum.oprf import VOPRFClient, VOPRFEvaluation


def docker(*args):
    return subprocess.run(["docker", *args], check=True, capture_output=True,
                          text=True, timeout=30).stdout


async def check(image, expected_tools):
    root = Path(__file__).resolve().parents[1]
    version = tomllib.loads((root / "pyproject.toml").read_text())["project"]["version"]
    upstream = json.loads((root / "omneum/mcp/UPSTREAM.json").read_text())
    # Bypass the entry point to verify the built image contains no private key.
    docker("run", "--rm", "--network", "none", "--entrypoint", "python", image, "-I", "-c",
           "from pathlib import Path; assert not Path('/var/lib/omneumd/voprf.key').exists()")
    name = "omneum-glama-check-" + uuid.uuid4().hex[:12]
    parameters = StdioServerParameters(command="docker", args=[
        "run", "--rm", "--network", "none", "-i", "--name", name, image,
    ])
    try:
        async with asyncio.timeout(90):
            async with stdio_client(parameters) as (read, write):
                async with ClientSession(read, write, read_timeout_seconds=timedelta(seconds=45)) as session:
                    await session.initialize()
                    tools = (await session.list_tools()).model_dump(mode="json", exclude_none=True)["tools"]
                    assert {tool["name"] for tool in tools} == {"ping", "evaluate_voprf", "evaluate_context"}
                    if expected_tools is not None:
                        assert tools == expected_tools, "Container changed the real tool definitions"
                    ping = await session.call_tool("ping")
                    assert not ping.isError and ping.structuredContent["status"] == "ok"
                    code = """
import json, os, pwd
from dataclasses import asdict
from importlib import metadata, resources
from omneum.deployment import load_config
assert os.getuid() > 0
assert os.getuid() != pwd.getpwnam('omneum-crypto').pw_uid
try:
    descriptor = os.open('/var/lib/omneumd/voprf.key', os.O_RDONLY)
except PermissionError:
    pass
else:
    os.close(descriptor)
    raise AssertionError('MCP user can open the private evaluator key')
upstream = json.loads(resources.files('omneum.mcp').joinpath('UPSTREAM.json').read_text())
print(json.dumps({'config': asdict(load_config()), 'version': metadata.version('omneum'),
                  'sdk': upstream['version'], 'revision': upstream['revision']}))
"""
                    details = json.loads(docker("exec", "--user", "omneum-mcp", "--env", "HOME=/var/lib/omneum",
                                                name, "python", "-I", "-c", code))
                    assert details["version"] == version
                    assert details["sdk"] == upstream["version"] and details["revision"] == upstream["revision"]
                    config = details["config"]
                    client = VOPRFClient(decode_unpadded(config["voprf_public_key"], expected_length=32))
                    message = b"Glama protected evaluator acceptance"
                    blinded = client.blind(message)
                    request = dict(protocol_version=PROTOCOL_VERSION, deployment_id=config["deployment_id"],
                                   voprf_key_version=config["voprf_key_version"], voprf_mode="voprf",
                                   voprf_ciphersuite="ristretto255-SHA512", linkage_encoding_version=ENCODING_VERSION,
                                   blinded_element=encode_unpadded(blinded.blinded_element, expected_length=32))
                    result = await session.call_tool("evaluate_voprf", request)
                    assert not result.isError, result
                    data = result.structuredContent
                    evaluation = VOPRFEvaluation(
                        decode_unpadded(data["evaluated_element"], expected_length=32),
                        decode_unpadded(data["proof"], expected_length=64))
                    assert len(client.finalize(input_data=message, client_state=blinded.client_state,
                                               evaluation=evaluation)) == 64
                    rejected = await session.call_tool("evaluate_voprf", {**request, "blinded_element": "invalid"})
                    assert rejected.isError
        print("PASS: offline container MCP initialize/tools/list/ping, VOPRF proof, invalid-request rejection, "
              "separate service identities, private-key denial, and no key in the image")
    finally:
        # Remove only this invocation's disposable container if the probe failed.
        subprocess.run(["docker", "rm", "--force", name], capture_output=True, timeout=15)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", default="omneum-glama:1.1.3")
    parser.add_argument("--expected-tools", type=Path, help="JSON array captured from a real 1.1.3 tools/list")
    args = parser.parse_args()
    expected = json.loads(args.expected_tools.read_text()) if args.expected_tools else None
    asyncio.run(check(args.image, expected))
