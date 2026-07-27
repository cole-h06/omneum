from __future__ import annotations

import asyncio
from pathlib import Path

from mcp import (
    ClientSession,
    StdioServerParameters,
    stdio_client,
)


def test_ping() -> None:
    async def call_ping():
        root = Path(__file__).parents[1]
        parameters = StdioServerParameters(
            command=str(root / ".venv/bin/python"),
            args=["-m", "verity.server"],
            cwd=root,
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

    asyncio.run(call_ping())
