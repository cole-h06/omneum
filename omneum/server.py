"""
Omneum MCP Server.

Application entry point for the Omneum MCP server.
"""

import logging
from pathlib import Path
import sys

import mcp

from omneum.config import load_deployment_state
from omneum.transport.mcp import create_server


_MCP_PACKAGE_ROOT = Path(mcp.__file__).resolve().parent


class _MCPLogFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if record.name == "mcp" or record.name.startswith("mcp."):
            return False
        try:
            return not Path(record.pathname).resolve().is_relative_to(
                _MCP_PACKAGE_ROOT
            )
        except (OSError, RuntimeError, ValueError):
            return True


def _suppress_mcp_logging() -> None:
    root_logger = logging.getLogger()
    if not any(
        isinstance(item, _MCPLogFilter)
        for item in root_logger.filters
    ):
        root_logger.addFilter(_MCPLogFilter())

    mcp_logger = logging.getLogger("mcp")
    mcp_logger.handlers.clear()
    mcp_logger.propagate = False
    for name, item in logging.Logger.manager.loggerDict.items():
        if (
            (name == "mcp" or name.startswith("mcp."))
            and isinstance(item, logging.Logger)
        ):
            item.handlers.clear()
            item.disabled = True


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    stream=sys.stderr,
)
_suppress_mcp_logging()

logger = logging.getLogger(__name__)


def main() -> None:
    """
    Initialize and start the Omneum MCP server over stdio.
    """

    state = load_deployment_state()
    server = create_server(state)

    try:
        logger.info("Starting Omneum MCP server over stdio...")
        server.run()

    except KeyboardInterrupt:
        logger.info("Server shutdown requested.")

    except Exception:
        logger.exception("Unexpected server failure.")
        raise


if __name__ == "__main__":
    main()
