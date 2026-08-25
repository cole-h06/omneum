from __future__ import annotations

import asyncio
import json
from pathlib import Path

from mcp import ClientSession, StdioServerParameters, stdio_client

from omneum.base64url import encode_unpadded
from stdio_state import isolated_deployment_environment


DEPLOYMENT_ID = (
    "urn:uuid:8d96fc18-f40f-4ec7-8ae8-f3711d88b741"
)
PRIVATE_KEY = b"\x01" + b"\x00" * 31
VECTOR_PATH = (
    Path(__file__).parent
    / "vectors"
    / "reliability_v1.json"
)


def token(value):
    return encode_unpadded(
        value.to_bytes(64, "big"),
        expected_length=64,
    )


def provisioning(tmp_path):
    return isolated_deployment_environment(
        tmp_path, DEPLOYMENT_ID, PRIVATE_KEY
    )[0]


def golden_request():
    vector = json.loads(VECTOR_PATH.read_text(encoding="utf-8"))
    groups = (
        ("source_id", 1),
        ("attribute_id", 101),
        ("claim_id", 201),
    )
    mapping = {}
    for field, offset in groups:
        identifiers = sorted({
            item[field]
            for item in vector["assertions"]
        })
        mapping.update({
            identifier: token(offset + index)
            for index, identifier in enumerate(identifiers)
        })

    assertions = sorted(
        (
            {
                "source_id": mapping[item["source_id"]],
                "attribute_id": mapping[item["attribute_id"]],
                "claim_id": mapping[item["claim_id"]],
            }
            for item in vector["assertions"]
        ),
        key=lambda item: (
            item["source_id"],
            item["attribute_id"],
            item["claim_id"],
        ),
    )
    pairs = sorted(
        (
            {
                "source_a_id": mapping[item["source_a_id"]],
                "source_b_id": mapping[item["source_b_id"]],
                "dependency": item["dependency"],
                "weighted_signal_coverage": (
                    item["weighted_signal_coverage"]
                ),
            }
            for item in vector["source_pairs"]
        ),
        key=lambda item: (
            item["source_a_id"],
            item["source_b_id"],
        ),
    )
    return {
        "protocol_version": "v1",
        "deployment_id": DEPLOYMENT_ID,
        "voprf_key_version": 1,
        "voprf_mode": "voprf",
        "voprf_ciphersuite": "ristretto255-SHA512",
        "linkage_encoding_version": 1,
        "assertions": assertions,
        "source_pairs": pairs,
    }


def test_infer_stdio(tmp_path):
    async def run():
        root = Path(__file__).parents[1]
        parameters = StdioServerParameters(
            command=str(root / ".venv/bin/python"),
            args=["-m", "omneum.server"],
            cwd=root,
            env=provisioning(tmp_path),
        )
        async with stdio_client(parameters) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                tools = await session.list_tools()
                assert "evaluate_assertion" in {
                    tool.name for tool in tools.tools
                }

                arguments = golden_request()
                first = await session.call_tool(
                    "evaluate_assertion",
                    arguments,
                )
                second = await session.call_tool(
                    "evaluate_assertion",
                    arguments,
                )
                assert not first.isError
                assert first.structuredContent == second.structuredContent
                content = first.structuredContent
                assert content is not None
                assert content["summary"] == {
                    "source_count": 5,
                    "claim_count": 6,
                    "assertion_count": 15,
                }
                assert content["metadata"] == {
                    "algorithm_version": "omneum-v1",
                    "iterations": 9,
                    "converged": True,
                    "convergence_tolerance": 1e-8,
                    "convergence_delta": (
                        6.582017357363579e-09
                    ),
                }

                invalid = await session.call_tool(
                    "evaluate_assertion",
                    {
                        **arguments,
                        "assertions": [
                            {
                                **arguments["assertions"][0],
                                "source_id": (
                                    arguments["assertions"][0]
                                    ["source_id"]
                                    + "="
                                ),
                            }
                        ],
                        "source_pairs": [],
                    },
                )
                assert invalid.isError
                assert invalid.structuredContent == {
                    "message": "The assertion graph is invalid.",
                    "omneum_code": "invalid_graph",
                }

    asyncio.run(run())
