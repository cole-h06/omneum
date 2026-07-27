"""
Verity Ping Tool.

Provides a health check for MCP clients.
"""


async def handle_ping() -> dict[str, str]:
    """
    Return the current server status.
    """

    return {
        "status": "ok",
        "protocol_version": "v1",
        "algorithm_version": "verity-v1",
    }