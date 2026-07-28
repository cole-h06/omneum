"""
Verity MCP Transport.

Configures the FastMCP server and registers the Verity protocol tools.
"""

from mcp.server.fastmcp import FastMCP

from verity.config import DeploymentState
from verity.tools.ping import handle_ping


def create_server(state: DeploymentState) -> FastMCP:
    """
    Create and configure the Verity MCP server.
    """

    mcp = FastMCP("Verity")

    @mcp.tool(
        name="ping",
        description=(
            "Verify that the Verity MCP server is reachable."
        ),
    )
    async def ping() -> dict[str, str | int]:
        """
        Verify that the Verity MCP server is reachable.
        """

        return await handle_ping(state)

    return mcp
