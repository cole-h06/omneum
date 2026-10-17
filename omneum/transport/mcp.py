"""
Omneum MCP Transport.

Configures the FastMCP server and registers the Omneum protocol tools.
"""

from contextlib import asynccontextmanager

from omneum.mcp.server.fastmcp import FastMCP
from omneum.mcp.server.fastmcp.exceptions import ToolError
from omneum.mcp.server.stdio import stdio_server
from omneum.mcp.types import CallToolResult, Tool
from pydantic import TypeAdapter, ValidationError

from omneum.config import DeploymentState
from omneum.models import (
    Assertion,
    EvaluateVOPRFRequest,
    EvaluateVOPRFResponse,
    EvaluateAssertionRequest,
    EvaluateAssertionResponse,
    OmneumErrorResponse,
    SourcePair,
)
from omneum.tools.evaluate_voprf import (
    EvaluationService,
    invalid_request_result,
)
from omneum.tools.evaluate_context import AssertionEvaluationService
from omneum.tools.ping import handle_ping
from omneum.transport.stdio import BoundedStdin


class OmneumFastMCP(FastMCP):
    """FastMCP server with stable Omneum validation failures."""

    async def list_tools(self) -> list[Tool]:
        tools = await super().list_tools()
        response_models = {
            "evaluate_voprf": EvaluateVOPRFResponse,
            "evaluate_context": EvaluateAssertionResponse,
        }
        for tool in tools:
            response_model = response_models.get(tool.name)
            if response_model is not None:
                # Advertise both existing payload forms without enabling FastMCP's
                # return-value conversion or changing CallToolResult serialization.
                tool.outputSchema = {
                    "type": "object",
                    **TypeAdapter(response_model | OmneumErrorResponse).json_schema(),
                }
        return tools

    async def run_stdio_async(self) -> None:
        # Shared by socket-activated, direct-socket and foreground sessions.
        # A framing error escapes the transport task group and ends the session.
        async with stdio_server(stdin=BoundedStdin()) as (read, write):
            await self._mcp_server.run(
                read, write, self._mcp_server.create_initialization_options(),
            )

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
            "Evaluate one RFC 9497 blinded element using this deployment’s VOPRF key. "
            "Use the Omneum SDK for blinding, proof verification, and local finalization. "
            "Supply matching deployment metadata and a canonical base64url-encoded "
            "32-byte blinded element. Returns a 32-byte evaluated element and 64-byte "
            "proof, both encoded as unpadded base64url. Evaluation uses the initialized "
            "local daemon and does not receive the original plaintext. Capacity or "
            "deadline failures return isError=true with message and omneum_code."
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
            "Evaluate relative source reliability and claim support from a "
            "caller-prepared graph of opaque linkage tokens and pairwise evidence "
            "dependencies. Use the Omneum SDK to prepare canonically ordered inputs "
            "and map returned tokens back to local context. Returns source reliability, "
            "claim support, conflicting claims, and estimated independent support for "
            "context selection. The server does not inspect source text, fetch sources, "
            "or independently determine factual truth or freshness. Graphs are evaluated "
            "without persistence; failures return isError=true with message and omneum_code."
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
