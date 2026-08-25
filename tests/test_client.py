from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from mcp.types import CallToolResult

import omneum
import omneum.client as client_module
from omneum.base64url import decode_unpadded, encode_unpadded
from omneum.client import (
    EvaluationRejectedError,
    EvaluationResponseError,
    EvaluationTransportError,
    EvaluationVerificationError,
    OmneumClient,
    OmneumClientConfig,
    _MCPOmneumEvaluator,
    open_stdio_client,
)
from omneum.models import EvaluateVOPRFRequest
from omneum.oprf import VOPRFServer


DEPLOYMENT_ID = "urn:uuid:8d96fc18-f40f-4ec7-8ae8-f3711d88b741"
PRIVATE_KEY = b"\x01" + b"\x00" * 31


def test_package_exports() -> None:
    assert omneum.__all__ == [
        "AssertionSource",
        "ContextMapper",
        "Claim",
        "ClaimSupportResult",
        "ConflictingClaimResult",
        "ConvergenceMetadata",
        "AssertionEvaluation",
        "DependencyCluster",
        "DependencyEvidence",
        "DependencyEstimatorConfig",
        "DependencySignalScores",
        "EvaluationRejectedError",
        "EvaluationResponseError",
        "EvaluationTransportError",
        "EvaluationVerificationError",
        "AssertionEvaluationMappingError",
        "AssertionEvaluationRejectedError",
        "AssertionEvaluationResponseError",
        "AssertionEvaluationTransportError",
        "LinkageToken",
    "Observation",
    "PairwiseDependencyResult",
    "Retrieval",
    "Source",
        "SourceEvaluation",
        "SourceReference",
        "SupportingSourceResult",
        "StructuredAssertion",
        "OmneumClient",
        "OmneumClientConfig",
        "OmneumClientConfigurationError",
        "OmneumClientError",
        "explain_claim",
        "explain_dependency",
        "observe",
        "open_stdio_client",
        "reference",
        "retrieval",
    ]


def make_server(tmp_path: Path) -> VOPRFServer:
    key = tmp_path / "voprf.key"
    key.write_bytes(PRIVATE_KEY)
    return VOPRFServer(key)


def make_config(oprf_server: VOPRFServer) -> OmneumClientConfig:
    return OmneumClientConfig(
        deployment_id=DEPLOYMENT_ID,
        voprf_key_version=1,
        voprf_mode="voprf",
        voprf_ciphersuite="ristretto255-SHA512",
        linkage_encoding_version=1,
        voprf_public_key=oprf_server.public_key,
    )


class LocalEvaluator:
    def __init__(self, oprf_server: VOPRFServer) -> None:
        self.server = oprf_server
        self.requests: list[EvaluateVOPRFRequest] = []

    async def evaluate_voprf(
        self,
        request: EvaluateVOPRFRequest,
    ) -> CallToolResult:
        self.requests.append(request)
        evaluation = self.server.evaluate(
            decode_unpadded(
                request.blinded_element,
                expected_length=32,
            )
        )
        return success_result(
            evaluated_element=encode_unpadded(
                evaluation.evaluated_element,
                expected_length=32,
            ),
            proof=encode_unpadded(
                evaluation.proof,
                expected_length=64,
            ),
        )


class FixedEvaluator:
    def __init__(self, result: CallToolResult) -> None:
        self.result = result

    async def evaluate_voprf(
        self,
        request: EvaluateVOPRFRequest,
    ) -> CallToolResult:
        return self.result


def success_result(**changes: object) -> CallToolResult:
    content: dict[str, object] = {
        "protocol_version": "v1",
        "deployment_id": DEPLOYMENT_ID,
        "voprf_key_version": 1,
        "voprf_mode": "voprf",
        "voprf_ciphersuite": "ristretto255-SHA512",
        "linkage_encoding_version": 1,
        "evaluated_element": encode_unpadded(
            b"e" * 32,
            expected_length=32,
        ),
        "proof": encode_unpadded(
            b"p" * 64,
            expected_length=64,
        ),
    }
    content.update(changes)
    return CallToolResult(
        content=[],
        structuredContent=content,
        isError=False,
    )


def error_result(content: object) -> CallToolResult:
    return CallToolResult(
        content=[],
        structuredContent=content,
        isError=True,
    )


def test_linkage(tmp_path: Path) -> None:
    async def run() -> None:
        oprf_server = make_server(tmp_path)
        evaluator = LocalEvaluator(oprf_server)
        client = OmneumClient(
            make_config(oprf_server),
            evaluator,
        )
        source = await client.link_source(
            "web_publisher",
            " https://Example.COM./ ",
        )
        attribute = await client.link_attribute(
            "service",
            " Example ",
            " Display Name ",
        )
        claim = await client.link_claim(
            "service",
            " Example ",
            " Display Name ",
            " Alice ",
        )
        repeated = await client.link_claim(
            "service",
            "example",
            "display_name",
            "Alice",
        )
        assert source.value != attribute.value != claim.value
        assert claim.value == repeated.value
        assert len(claim.value) == 64
        assert len(claim.to_base64url()) == 86
        assert all(
            request.deployment_id == DEPLOYMENT_ID
            for request in evaluator.requests
        )
        assert all(
            request.linkage_encoding_version == 1
            for request in evaluator.requests
        )
        assert set(evaluator.requests[0].model_dump()) == {
            "protocol_version",
            "deployment_id",
            "voprf_key_version",
            "voprf_mode",
            "voprf_ciphersuite",
            "linkage_encoding_version",
            "blinded_element",
        }

    asyncio.run(run())


@pytest.mark.parametrize(
    "changes",
    [
        {"protocol_version": "v2", "evaluated_element": "invalid"},
        {"deployment_id": "urn:uuid:01234567-89ab-cdef-0123-456789abcdef"},
        {"voprf_key_version": 2},
        {"voprf_mode": "oprf"},
        {"voprf_ciphersuite": "other"},
        {"linkage_encoding_version": 2},
        {"unknown": "field"},
        {"evaluated_element": "invalid"},
        {"proof": "invalid"},
    ],
)
def test_invalid_response(
    tmp_path: Path,
    changes: dict[str, object],
) -> None:
    async def run() -> None:
        oprf_server = make_server(tmp_path)
        client = OmneumClient(
            make_config(oprf_server),
            FixedEvaluator(success_result(**changes)),
        )
        with pytest.raises(EvaluationResponseError):
            await client.link_source(
                "web_publisher",
                "https://example.com",
            )

    asyncio.run(run())


@pytest.mark.parametrize(
    "content",
    [
        None,
        {"message": "secret"},
        {"message": "secret", "omneum_code": "future_code"},
        {"message": "secret", "omneum_code": "server_busy", "extra": True},
    ],
)
def test_invalid_error(
    tmp_path: Path,
    content: object,
) -> None:
    async def run() -> None:
        oprf_server = make_server(tmp_path)
        client = OmneumClient(
            make_config(oprf_server),
            FixedEvaluator(error_result(content)),
        )
        with pytest.raises(EvaluationResponseError):
            await client.link_source(
                "web_publisher",
                "https://example.com",
            )

    asyncio.run(run())


def test_rejected_error(tmp_path: Path) -> None:
    async def run() -> None:
        oprf_server = make_server(tmp_path)
        result = error_result(
            {
                "message": "arbitrary secret",
                "omneum_code": "server_busy",
            }
        )
        client = OmneumClient(
            make_config(oprf_server),
            FixedEvaluator(result),
        )
        with pytest.raises(EvaluationRejectedError) as caught:
            await client.link_source(
                "web_publisher",
                "https://example.com",
            )
        assert str(caught.value) == "VOPRF evaluation was rejected."
        assert caught.value.omneum_code == "server_busy"
        assert "secret" not in repr(caught.value)

    asyncio.run(run())


def test_invalid_proof(tmp_path: Path) -> None:
    async def run() -> None:
        oprf_server = make_server(tmp_path)
        client = OmneumClient(
            make_config(oprf_server),
            FixedEvaluator(success_result()),
        )
        with pytest.raises(EvaluationVerificationError):
            await client.link_source(
                "web_publisher",
                "https://example.com",
            )

    asyncio.run(run())


def test_adapter_errors() -> None:
    class Session:
        def __init__(self, failure: BaseException) -> None:
            self.failure = failure

        async def call_tool(
            self,
            name: str,
            arguments: dict,
        ):
            raise self.failure

    async def run() -> None:
        request = EvaluateVOPRFRequest(
            protocol_version="v1",
            deployment_id=DEPLOYMENT_ID,
            voprf_key_version=1,
            voprf_mode="voprf",
            voprf_ciphersuite="ristretto255-SHA512",
            linkage_encoding_version=1,
            blinded_element=encode_unpadded(
                b"b" * 32,
                expected_length=32,
            ),
        )
        cancelled = _MCPOmneumEvaluator(
            Session(asyncio.CancelledError())
        )
        with pytest.raises(asyncio.CancelledError):
            await cancelled.evaluate_voprf(request)
        broken = _MCPOmneumEvaluator(
            Session(OSError("lost"))
        )
        with pytest.raises(EvaluationTransportError) as caught:
            await broken.evaluate_voprf(request)
        assert caught.value.uncertain is True

    asyncio.run(run())


def test_tool_discovery(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Context:
        def __init__(self, value: object) -> None:
            self.value = value
            self.exited = False

        async def __aenter__(self):
            return self.value

        async def __aexit__(self, *args: object) -> None:
            self.exited = True

    class Session:
        def __init__(self) -> None:
            self.list_calls = 0

        async def initialize(self) -> None:
            return None

        async def list_tools(self):
            self.list_calls += 1
            return type("Tools", (), {"tools": []})()

    async def run() -> None:
        oprf_server = make_server(tmp_path)
        session = Session()
        transport = Context((object(), object()))
        session_context = Context(session)
        monkeypatch.setattr(
            client_module,
            "stdio_client",
            lambda parameters: transport,
        )
        monkeypatch.setattr(
            client_module,
            "ClientSession",
            lambda read, write: session_context,
        )
        with pytest.raises(EvaluationResponseError):
            async with open_stdio_client(
                make_config(oprf_server),
                object(),
            ):
                raise AssertionError("unavailable tool was accepted")
        assert session.list_calls == 1
        assert session_context.exited
        assert transport.exited

    asyncio.run(run())
