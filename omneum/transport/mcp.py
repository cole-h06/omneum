"""
Omneum MCP Transport.

Configures the FastMCP server and registers the Omneum protocol tools.
"""

from contextlib import asynccontextmanager

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from mcp.types import CallToolResult
from pydantic import ValidationError

from omneum.config import DeploymentState
from omneum.models import (
    Assertion,
    EvaluateVOPRFRequest,
    EvaluateAssertionRequest,
    SourcePair,
)
from omneum.tools.evaluate_voprf import (
    EvaluationService,
    invalid_request_result,
)
from omneum.tools.evaluate_context import AssertionEvaluationService
from omneum.tools.ping import handle_ping


class OmneumFastMCP(FastMCP):
    """FastMCP server with stable Omneum validation failures."""

    async def call_tool(
        self,
        name: str,
        arguments: dict,
    ):
        try:
            return await super().call_tool(name, arguments)
        except ToolError:
            if name in {
                "evaluate_voprf",
                "evaluate_context",
            }:
                return invalid_request_result()
            raise


def create_server(state: DeploymentState) -> FastMCP:
    """
    Create and configure the Omneum MCP server.
    """

    evaluation_service = EvaluationService(state)
    assertion_service = AssertionEvaluationService(state)

    @asynccontextmanager
    async def lifespan(_server):
        try:
            yield None
        finally:
            assertion_service.close()
            evaluation_service.close()

    mcp = OmneumFastMCP(
        "Omneum",
        lifespan=lifespan,
    )

    @mcp.tool(
        name="ping",
        description=(
            "Verify that the Omneum MCP server is reachable."
        ),
    )
    async def ping() -> dict[str, str | int]:
        """
        Verify that the Omneum MCP server is reachable.
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

    @mcp.tool(
        name="evaluate_context",
        description=(
            "Evaluate opaque assertions and return information-quality signals."
        ),
    )
    async def evaluate_context(
        protocol_version: str,
        deployment_id: str,
        voprf_key_version: int,
        voprf_mode: str,
        voprf_ciphersuite: str,
        linkage_encoding_version: int,
        assertions: list[Assertion],
        source_pairs: list[SourcePair],
    ) -> CallToolResult:
        try:
            request = EvaluateAssertionRequest(
                protocol_version=protocol_version,
                deployment_id=deployment_id,
                voprf_key_version=voprf_key_version,
                voprf_mode=voprf_mode,
                voprf_ciphersuite=voprf_ciphersuite,
                linkage_encoding_version=(
                    linkage_encoding_version
                ),
                assertions=assertions,
                source_pairs=source_pairs,
            )
        except ValidationError:
            return invalid_request_result()
        return await assertion_service.evaluate(request)

    assertion_tool = mcp._tool_manager.get_tool(
        "evaluate_context"
    )
    if assertion_tool is None:  # pragma: no cover
        raise RuntimeError(
            "evaluate_context registration failed"
        )
    assertion_tool.fn_metadata.arg_model.model_config.update(
        extra="forbid",
        strict=True,
    )
    assertion_tool.fn_metadata.arg_model.model_rebuild(force=True)
    assertion_tool.parameters = (
        EvaluateAssertionRequest.model_json_schema()
    )

    return mcp
