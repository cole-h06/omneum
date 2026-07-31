"""
Verity MCP Transport.

Configures the FastMCP server and registers the Verity protocol tools.
"""

from contextlib import asynccontextmanager

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from mcp.types import CallToolResult
from pydantic import ValidationError

from verity.config import DeploymentState
from verity.models import EvaluateVOPRFRequest
from verity.tools.evaluate_voprf import (
    EvaluationService,
    invalid_request_result,
)
from verity.tools.ping import handle_ping


class VerityFastMCP(FastMCP):
    """FastMCP server with stable Verity validation failures."""

    async def call_tool(
        self,
        name: str,
        arguments: dict,
    ):
        try:
            return await super().call_tool(name, arguments)
        except ToolError:
            if name == "evaluate_voprf":
                return invalid_request_result()
            raise


def create_server(state: DeploymentState) -> FastMCP:
    """
    Create and configure the Verity MCP server.
    """

    evaluation_service = EvaluationService(state)

    @asynccontextmanager
    async def lifespan(_server):
        try:
            yield None
        finally:
            evaluation_service.close()

    mcp = VerityFastMCP(
        "Verity",
        lifespan=lifespan,
    )

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

    @mcp.tool(
        name="evaluate_voprf",
        description=(
            "Evaluate one RFC 9497 VOPRF blinded element."
        ),
    )
    async def evaluate_voprf(
        protocol_version: str,
        deployment_id: str,
        voprf_key_version: int,
        voprf_mode: str,
        voprf_ciphersuite: str,
        linkage_encoding_version: int,
        blinded_element: str,
    ) -> CallToolResult:
        try:
            request = EvaluateVOPRFRequest(
                protocol_version=protocol_version,
                deployment_id=deployment_id,
                voprf_key_version=voprf_key_version,
                voprf_mode=voprf_mode,
                voprf_ciphersuite=voprf_ciphersuite,
                linkage_encoding_version=(
                    linkage_encoding_version
                ),
                blinded_element=blinded_element,
            )
        except ValidationError:
            return invalid_request_result()
        return await evaluation_service.evaluate(request)

    tool = mcp._tool_manager.get_tool("evaluate_voprf")
    if tool is None:  # pragma: no cover
        raise RuntimeError(
            "evaluate_voprf registration failed"
        )
    tool.fn_metadata.arg_model.model_config.update(
        extra="forbid",
        strict=True,
    )
    tool.fn_metadata.arg_model.model_rebuild(force=True)
    tool.parameters = (
        EvaluateVOPRFRequest.model_json_schema()
    )

    return mcp
