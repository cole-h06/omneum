from __future__ import annotations

import asyncio
import base64
import os
import subprocess
from pathlib import Path

import pytest
from mcp import (
    ClientSession,
    StdioServerParameters,
    stdio_client,
)

import verity.server as server_module
from verity.config import ConfigurationError
from verity.oprf import VOPRFServer


DEPLOYMENT_ID = (
    "urn:uuid:8d96fc18-f40f-4ec7-8ae8-f3711d88b741"
)
# Scalar 1 encoded as a fixed test key. Never use in production.
PRIVATE_KEY = b"\x01" + b"\x00" * 31


def provisioning(tmp_path: Path) -> dict[str, str]:
    private_key_file = tmp_path / "voprf.key"
    private_key_file.write_bytes(PRIVATE_KEY)
    public_key = VOPRFServer(PRIVATE_KEY).public_key
    encoded_public_key = base64.urlsafe_b64encode(
        public_key
    ).rstrip(b"=").decode("ascii")
    return {
        **os.environ,
        "VERITY_DEPLOYMENT_ID": DEPLOYMENT_ID,
        "VERITY_VOPRF_KEY_VERSION": "1",
        "VERITY_VOPRF_PUBLIC_KEY": encoded_public_key,
        "VERITY_VOPRF_PRIVATE_KEY_FILE": str(
            private_key_file
        ),
    }


def test_ping(tmp_path: Path) -> None:
    async def call_ping():
        root = Path(__file__).parents[1]
        parameters = StdioServerParameters(
            command=str(root / ".venv/bin/python"),
            args=["-m", "verity.server"],
            cwd=root,
            env=provisioning(tmp_path),
        )

        async with stdio_client(parameters) as (
            read,
            write,
        ):
            async with ClientSession(
                read,
                write,
            ) as session:
                await session.initialize()

                tools = await session.list_tools()
                assert "ping" in {
                    tool.name
                    for tool in tools.tools
                }

                result = await session.call_tool("ping")
                assert not result.isError

                content = result.structuredContent
                assert content is not None
                assert content["status"] == "ok"
                assert content["protocol_version"] == "v1"
                assert content["algorithm_version"] == "verity-v1"
                assert content["deployment_id"] == DEPLOYMENT_ID
                assert content["voprf_key_version"] == 1
                assert content["voprf_mode"] == "voprf"
                assert (
                    content["voprf_ciphersuite"]
                    == "ristretto255-SHA512"
                )
                assert (
                    content["linkage_encoding_version"]
                    == 1
                )
                assert len(
                    content["configuration_fingerprint"]
                ) == 64
                assert "voprf_public_key" not in content

    asyncio.run(call_ping())


def test_invalid_provisioning(tmp_path: Path) -> None:
    root = Path(__file__).parents[1]
    environment = provisioning(tmp_path)
    environment["VERITY_VOPRF_KEY_VERSION"] = "0"

    result = subprocess.run(
        [
            str(root / ".venv/bin/python"),
            "-m",
            "verity.server",
        ],
        cwd=root,
        env=environment,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )

    assert result.returncode != 0
    assert "Starting Verity MCP server" not in result.stderr
    assert PRIVATE_KEY.hex() not in result.stderr


def test_validation_precedes_server(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    constructed = False

    def invalid_state():
        raise ConfigurationError(
            "Invalid provisioning."
        )

    def create_server(state):
        nonlocal constructed
        constructed = True

    monkeypatch.setattr(
        server_module,
        "load_deployment_state",
        invalid_state,
    )
    monkeypatch.setattr(
        server_module,
        "create_server",
        create_server,
    )

    with pytest.raises(ConfigurationError):
        server_module.main()

    assert not constructed
