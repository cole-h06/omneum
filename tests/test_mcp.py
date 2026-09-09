from __future__ import annotations

from daemon_support import VOPRFServer

import asyncio
import base64
import logging
import subprocess
import sys
from pathlib import Path

import pytest
from mcp import (
    ClientSession,
    StdioServerParameters,
    stdio_client,
)

import omneum.server as server_module
from omneum.config import ConfigurationError
from omneum.oprf import (
    VOPRFClient,
    VOPRFEvaluation,
)
from stdio_state import isolated_deployment_environment


DEPLOYMENT_ID = (
    "urn:uuid:8d96fc18-f40f-4ec7-8ae8-f3711d88b741"
)
# Scalar 1 encoded as a fixed test key. Never use in production.
PRIVATE_KEY = b"\x01" + b"\x00" * 31


def provisioning(tmp_path: Path):
    return isolated_deployment_environment(
        tmp_path, DEPLOYMENT_ID, PRIVATE_KEY
    )


def test_ping(tmp_path: Path) -> None:
    async def call_ping():
        root = Path(__file__).parents[1]
        environment, public_key, _ = provisioning(tmp_path)
        parameters = StdioServerParameters(
            command=sys.executable,
            args=["-m", "omneum.server"],
            cwd=root,
            env=environment,
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
                listed_tools = {
                    tool.name: tool
                    for tool in tools.tools
                }
                assert "ping" in listed_tools
                assert "evaluate_voprf" in listed_tools
                assert "evaluate_assertion" in listed_tools
                evaluate_schema = listed_tools[
                    "evaluate_voprf"
                ].inputSchema
                assert (
                    evaluate_schema["additionalProperties"]
                    is False
                )
                assert set(
                    evaluate_schema["required"]
                ) == {
                    "protocol_version",
                    "deployment_id",
                    "voprf_key_version",
                    "voprf_mode",
                    "voprf_ciphersuite",
                    "linkage_encoding_version",
                    "blinded_element",
                }
                assertion_schema = listed_tools[
                    "evaluate_assertion"
                ].inputSchema
                assert (
                    assertion_schema["additionalProperties"]
                    is False
                )
                assert set(assertion_schema["required"]) == {
                    "protocol_version",
                    "deployment_id",
                    "voprf_key_version",
                    "voprf_mode",
                    "voprf_ciphersuite",
                    "linkage_encoding_version",
                    "assertions",
                    "source_pairs",
                }
                assert (
                    assertion_schema["$defs"]["Assertion"]
                    ["additionalProperties"]
                    is False
                )
                assert (
                    assertion_schema["$defs"]["SourcePair"]
                    ["additionalProperties"]
                    is False
                )

                result = await session.call_tool("ping")
                assert not result.isError

                content = result.structuredContent
                assert content is not None
                assert content["status"] == "ok"
                assert content["protocol_version"] == "v1"
                assert content["algorithm_version"] == "omneum-v2"
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

                client = VOPRFClient(public_key)
                input_data = b"stdio evaluation"
                blind = client.blind(input_data)
                blinded_element = (
                    base64.urlsafe_b64encode(
                        blind.blinded_element
                    )
                    .rstrip(b"=")
                    .decode("ascii")
                )
                arguments = {
                    "protocol_version": "v1",
                    "deployment_id": DEPLOYMENT_ID,
                    "voprf_key_version": 1,
                    "voprf_mode": "voprf",
                    "voprf_ciphersuite": (
                        "ristretto255-SHA512"
                    ),
                    "linkage_encoding_version": 1,
                    "blinded_element": blinded_element,
                }
                evaluated = await session.call_tool(
                    "evaluate_voprf",
                    arguments,
                )
                assert not evaluated.isError
                evaluation_content = (
                    evaluated.structuredContent
                )
                assert evaluation_content is not None
                assert "server_public_key" not in (
                    evaluation_content
                )
                assert "client_state" not in evaluation_content
                evaluation = VOPRFEvaluation(
                    evaluated_element=(
                        base64.urlsafe_b64decode(
                            evaluation_content[
                                "evaluated_element"
                            ]
                            + "="
                        )
                    ),
                    proof=base64.urlsafe_b64decode(
                        evaluation_content["proof"] + "=="
                    ),
                )
                output = client.finalize(
                    input_data=input_data,
                    client_state=blind.client_state,
                    evaluation=evaluation,
                )
                assert len(output) == 64

                repeated = await session.call_tool(
                    "evaluate_voprf",
                    arguments,
                )
                assert not repeated.isError
                repeated_content = repeated.structuredContent
                assert repeated_content is not None
                repeated_evaluation = VOPRFEvaluation(
                    evaluated_element=(
                        base64.urlsafe_b64decode(
                            repeated_content[
                                "evaluated_element"
                            ]
                            + "="
                        )
                    ),
                    proof=base64.urlsafe_b64decode(
                        repeated_content["proof"] + "=="
                    ),
                )
                assert client.finalize(
                    input_data=input_data,
                    client_state=blind.client_state,
                    evaluation=repeated_evaluation,
                ) == output

                invalid = await session.call_tool(
                    "evaluate_voprf",
                    {
                        **arguments,
                        "unknown": "value",
                    },
                )
                assert invalid.isError
                assert invalid.structuredContent == {
                    "message": "Request validation failed.",
                    "omneum_code": "invalid_request",
                }

                for malformed in (
                    {
                        key: value
                        for key, value in arguments.items()
                        if key != "protocol_version"
                    },
                    {
                        **arguments,
                        "voprf_key_version": True,
                    },
                ):
                    invalid = await session.call_tool(
                        "evaluate_voprf",
                        malformed,
                    )
                    assert invalid.isError
                    assert invalid.structuredContent == {
                        "message": (
                            "Request validation failed."
                        ),
                        "omneum_code": "invalid_request",
                    }

                mismatch = await session.call_tool(
                    "evaluate_voprf",
                    {
                        **arguments,
                        "voprf_key_version": 2,
                    },
                )
                assert mismatch.isError
                assert mismatch.structuredContent == {
                    "message": (
                        "The VOPRF key version does not match."
                    ),
                    "omneum_code": (
                        "voprf_key_version_mismatch"
                    ),
                }

    asyncio.run(call_ping())


def test_invalid_provisioning(tmp_path: Path) -> None:
    root = Path(__file__).parents[1]
    environment, _, config_path = provisioning(tmp_path)
    config_path.write_text(
        config_path.read_text().replace(
            "voprf_key_version = 1", "voprf_key_version = 0"
        )
    )

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "omneum.server",
        ],
        cwd=root,
        env=environment,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )

    assert result.returncode != 0
    assert "Starting Omneum MCP server" not in result.stderr
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


def test_mcp_logs_suppressed():
    records = []

    class Capture(logging.Handler):
        def emit(self, record):
            records.append(record)

    root_logger = logging.getLogger()
    original_level = root_logger.level
    handler = Capture()
    root_logger.addHandler(handler)
    root_logger.setLevel(logging.DEBUG)
    try:
        server_module._suppress_mcp_logging()
        logging.getLogger("mcp.server.lowlevel.server").warning(
            "protocol-value"
        )
        root_record = logging.LogRecord(
            "root",
            logging.WARNING,
            str(
                server_module._MCP_PACKAGE_ROOT
                / "shared"
                / "session.py"
            ),
            1,
            "malformed protocol-value",
            (),
            None,
        )
        root_logger.handle(root_record)
        logging.getLogger("omneum.test").debug("application-value")
    finally:
        root_logger.removeHandler(handler)
        root_logger.setLevel(original_level)

    messages = [record.getMessage() for record in records]
    assert not any("protocol-value" in message for message in messages)
    assert "application-value" in messages
