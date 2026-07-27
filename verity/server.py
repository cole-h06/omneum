"""
Verity MCP Server.

Application entry point for the Verity MCP server.
"""

import logging
import sys

from verity.transport.mcp import create_server


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    stream=sys.stderr,
)

logger = logging.getLogger(__name__)


def main() -> None:
    """
    Initialize and start the Verity MCP server over stdio.
    """

    logger.info("Starting Verity MCP server over stdio...")

    server = create_server()

    try:
        server.run()

    except KeyboardInterrupt:
        logger.info("Server shutdown requested.")

    except Exception:
        logger.exception("Unexpected server failure.")
        raise


if __name__ == "__main__":
    main()