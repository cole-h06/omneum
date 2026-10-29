"""Tool discovery metadata must preserve the existing evaluation wire contract."""
import asyncio
import json
import os
import sys

from jsonschema import Draft202012Validator
import pytest

from omneum.base64url import decode_unpadded, encode_unpadded
from omneum.config import DeploymentState, load_deployment_state
from omneum.daemon import DaemonBusyError
from omneum.mcp import ClientSession, StdioServerParameters, stdio_client
from omneum.models import (
    EvaluateAssertionRequest,
    EvaluateAssertionResponse,
    EvaluateVOPRFRequest,
    EvaluateVOPRFResponse,
    OmneumErrorResponse,
)
from omneum.oprf import VOPRFClient, VOPRFEvaluation
from omneum.transport.mcp import create_server


DEPLOYMENT_ID = "urn:uuid:8d96fc18-f40f-4ec7-8ae8-f3711d88b741"
COMMON = {
    "protocol_version": "v1",
    "deployment_id": DEPLOYMENT_ID,
    "voprf_key_version": 1,
    "voprf_mode": "voprf",
    "voprf_ciphersuite": "ristretto255-SHA512",
    "linkage_encoding_version": 1,
}
DESCRIPTIONS = {
    "evaluate_voprf": (
        "Evaluate one RFC 9497 blinded element using this deployment’s VOPRF key. "
        "Use the Omneum SDK for blinding, proof verification, and local finalization. "
        "Supply matching deployment metadata and a canonical base64url-encoded "
        "32-byte blinded element. Returns a 32-byte evaluated element and 64-byte "
        "proof, both encoded as unpadded base64url. Evaluation uses the initialized "
        "local daemon and does not receive the original plaintext. Capacity or "
        "deadline failures return isError=true with message and omneum_code."
    ),
    "evaluate_context": (
        "Evaluate relative source reliability and claim support from a "
        "caller-prepared graph of opaque linkage tokens and pairwise evidence "
        "dependencies. Use the Omneum SDK to prepare canonically ordered inputs "
        "and map returned tokens back to local context. Returns source reliability, "
        "claim support, conflicting claims, and estimated independent support for "
        "context selection. The server does not inspect source text, fetch sources, "
        "or independently determine factual truth or freshness. Graphs are evaluated "
        "without persistence; failures return isError=true with message and omneum_code."
    ),
}


def token(number):
    return encode_unpadded(number.to_bytes(64, "big"), expected_length=64)


def context_arguments():
    sources = sorted([token(1), token(2)])
    return {
        **COMMON,
        "assertions": [
            {"source_id": source, "attribute_id": token(101), "claim_id": token(201)}
            for source in sources
        ],
        "source_pairs": [{
            "source_a_id": sources[0], "source_b_id": sources[1],
            "dependency": 0.25, "weighted_signal_coverage": 0.5,
        }],
    }


def assert_wire_result(result, validator, *, code=None):
    payload = result.structuredContent
    validator.validate(payload)
    assert len(result.content) == 1 and result.content[0].type == "text"
    assert result.content[0].text == json.dumps(payload, separators=(",", ":"), sort_keys=True)
    assert result.isError is (code is not None)
    if code is not None:
        assert set(payload) == {"message", "omneum_code"}
        assert payload["omneum_code"] == code


def assert_metadata(tools):
    assert set(tools) == {"ping", *DESCRIPTIONS}
    for name, request_model in (
        ("evaluate_voprf", EvaluateVOPRFRequest),
        ("evaluate_context", EvaluateAssertionRequest),
    ):
        tool = tools[name]
        assert tool.description == DESCRIPTIONS[name]
        assert tool.inputSchema == request_model.model_json_schema()
        assert tool.inputSchema["additionalProperties"] is False
        assert set(tool.inputSchema["required"]) == set(tool.inputSchema["properties"])
        assert all(field.get("description") for field in tool.inputSchema["properties"].values())
        Draft202012Validator.check_schema(tool.outputSchema)
        assert tool.outputSchema["type"] == "object"
        assert "OmneumErrorResponse" in tool.outputSchema["$defs"]

    voprf = tools["evaluate_voprf"].inputSchema["properties"]
    assert "43 characters" in voprf["blinded_element"]["description"]
    assert voprf["voprf_key_version"]["minimum"] == 1
    assert voprf["voprf_key_version"]["maximum"] == 2**32 - 1
    context = tools["evaluate_context"].inputSchema
    for name in ("Assertion", "SourcePair"):
        definition = context["$defs"][name]
        assert definition["additionalProperties"] is False
        assert all(field.get("description") for field in definition["properties"].values())
    pair = context["$defs"]["SourcePair"]
    assert pair["properties"]["exact_equivalence"]["default"] is False
    assert "exact_equivalence" not in pair["required"]
    # These constraints remain service checks; adding Field bounds would change error codes.
    assert set(pair["properties"]["dependency"]) == {"title", "type", "description"}
    assert set(pair["properties"]["weighted_signal_coverage"]) == {"title", "type", "description"}
    assert "16384" in context["properties"]["assertions"]["description"]
    assert "n*(n-1)/2" in context["properties"]["source_pairs"]["description"]
    assert "86 characters" in context["$defs"]["Assertion"]["properties"]["source_id"]["description"]
    ping = tools["ping"].model_dump(mode="json", exclude_none=True)
    assert ping == {
        "name": "ping",
        "description": "Verify that the Omneum MCP server is reachable.",
        "inputSchema": {"properties": {}, "title": "pingArguments", "type": "object"},
        "outputSchema": {
            "additionalProperties": {"anyOf": [{"type": "string"}, {"type": "integer"}]},
            "title": "pingDictOutput", "type": "object",
        },
    }


def test_tools_list_metadata_and_error_schema():
    async def run():
        state = DeploymentState(
            deployment_id=DEPLOYMENT_ID, voprf_key_version=1,
            configuration_fingerprint="f" * 64, voprf_server=object(),
        )
        server = create_server(state)
        async with server.settings.lifespan(server):
            tools = {tool.name: tool for tool in await server.list_tools()}
            assert_metadata(tools)
            assert {tool.name: tool for tool in await server.list_tools()} == tools
            for name in DESCRIPTIONS:
                registered = server._tool_manager.get_tool(name)
                assert registered.fn_metadata.output_schema is None
                assert registered.fn_metadata.output_model is None
                validator = Draft202012Validator(tools[name].outputSchema)
                for code in OmneumErrorResponse.model_fields["omneum_code"].annotation.__args__:
                    validator.validate({"message": "Failure", "omneum_code": code})
                assert not validator.is_valid({"message": "Missing error code"})
                assert not validator.is_valid({"result": {"message": "Wrapped", "omneum_code": "invalid_request"}})

    asyncio.run(run())


def test_voprf_busy_error_survives_output_schema():
    class BusyBackend:
        def evaluate(self, _blinded_element):
            raise DaemonBusyError("Busy")

    async def run():
        server = create_server(DeploymentState(
            deployment_id=DEPLOYMENT_ID, voprf_key_version=1,
            configuration_fingerprint="f" * 64, voprf_server=BusyBackend(),
        ))
        async with server.settings.lifespan(server):
            tool = next(tool for tool in await server.list_tools() if tool.name == "evaluate_voprf")
            result = await server.call_tool("evaluate_voprf", {
                **COMMON, "blinded_element": encode_unpadded(b"b" * 32, expected_length=32),
            })
            assert_wire_result(result, Draft202012Validator(tool.outputSchema), code="server_busy")
            assert result.structuredContent["message"] == "Evaluation capacity is exhausted."

    asyncio.run(run())


def test_metadata_and_results_over_stdio(example_daemon):
    async def run():
        state = load_deployment_state()
        parameters = StdioServerParameters(
            command=sys.executable, args=["-m", "omneum.server"], env=os.environ.copy(),
        )
        async with stdio_client(parameters) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                tools = {tool.name: tool for tool in (await session.list_tools()).tools}
                assert_metadata(tools)
                validators = {name: Draft202012Validator(tools[name].outputSchema) for name in DESCRIPTIONS}
                client = VOPRFClient(example_daemon.public_key)
                message = b"MCP metadata compatibility"
                blinded = client.blind(message)
                requests = {
                    "evaluate_voprf": {
                        **COMMON, "blinded_element": encode_unpadded(blinded.blinded_element, expected_length=32),
                    },
                    "evaluate_context": context_arguments(),
                }
                voprf = await session.call_tool("evaluate_voprf", requests["evaluate_voprf"])
                assert_wire_result(voprf, validators["evaluate_voprf"])
                EvaluateVOPRFResponse.model_validate(voprf.structuredContent)
                evaluation = VOPRFEvaluation(
                    decode_unpadded(voprf.structuredContent["evaluated_element"], expected_length=32),
                    decode_unpadded(voprf.structuredContent["proof"], expected_length=64),
                )
                assert len(client.finalize(input_data=message, client_state=blinded.client_state, evaluation=evaluation)) == 64
                context = await session.call_tool("evaluate_context", requests["evaluate_context"])
                assert_wire_result(context, validators["evaluate_context"])
                EvaluateAssertionResponse.model_validate(context.structuredContent)
                assert context.structuredContent["summary"] == {"source_count": 2, "claim_count": 1, "assertion_count": 2}
                assert context.structuredContent["claim_support"][0]["estimated_independent_support_count"] == pytest.approx(1.6)
                assert context.structuredContent["deployment_id"] == state.deployment_id
                repeated = await session.call_tool("evaluate_context", requests["evaluate_context"])
                assert repeated.structuredContent["evaluation_latency_ms"] >= 0
                assert context.structuredContent["evaluation_latency_ms"] >= 0
                assert {k: v for k, v in repeated.structuredContent.items() if k != "evaluation_latency_ms"} == {
                    k: v for k, v in context.structuredContent.items() if k != "evaluation_latency_ms"
                }
                for name, request in requests.items():
                    for changes, code in (
                        ({"unknown": "value"}, "invalid_request"),
                        ({"voprf_key_version": True}, "invalid_request"),
                        ({"protocol_version": "v2"}, "unsupported_protocol_version"),
                        ({"voprf_key_version": 2}, "voprf_key_version_mismatch"),
                    ):
                        result = await session.call_tool(name, {**request, **changes})
                        assert_wire_result(result, validators[name], code=code)
                malformed = await session.call_tool("evaluate_voprf", {**requests["evaluate_voprf"], "blinded_element": "invalid"})
                assert_wire_result(malformed, validators["evaluate_voprf"], code="invalid_blinded_element")
                invalid_graph = requests["evaluate_context"] | {"source_pairs": []}
                result = await session.call_tool("evaluate_context", invalid_graph)
                assert_wire_result(result, validators["evaluate_context"], code="invalid_graph")
                assert not validators["evaluate_voprf"].is_valid(voprf.structuredContent | {"extra": True})
                assert not validators["evaluate_context"].is_valid(context.structuredContent | {"metadata": {}})

    asyncio.run(run())
