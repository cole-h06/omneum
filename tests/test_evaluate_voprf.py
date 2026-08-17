from __future__ import annotations

import asyncio
import base64
import json
import threading

import pytest

from omneum.config import DeploymentState
from omneum.models import EvaluateVOPRFRequest
from omneum.oprf import (
    InvalidBlindedElementError,
    OPRFProtocolError,
    VOPRFEvaluation,
)
from omneum.tools.evaluate_voprf import EvaluationService
from omneum.transport.mcp import create_server


DEPLOYMENT_ID = (
    "urn:uuid:8d96fc18-f40f-4ec7-8ae8-f3711d88b741"
)
BLINDED_BYTES = b"b" * 32
BLINDED_ELEMENT = base64.urlsafe_b64encode(
    BLINDED_BYTES
).rstrip(b"=").decode("ascii")


class FakeServer:
    def __init__(
        self,
        *,
        evaluation: VOPRFEvaluation | None = None,
        failure: Exception | None = None,
    ) -> None:
        self.evaluation = evaluation or VOPRFEvaluation(
            evaluated_element=b"e" * 32,
            proof=b"p" * 64,
        )
        self.failure = failure
        self.calls = 0

    def evaluate(
        self,
        blinded_element: bytes,
    ) -> VOPRFEvaluation:
        self.calls += 1
        assert blinded_element == BLINDED_BYTES
        if self.failure is not None:
            raise self.failure
        return self.evaluation


class BlockingServer(FakeServer):
    def __init__(self) -> None:
        super().__init__()
        self.started = threading.Event()
        self.release = threading.Event()

    def evaluate(
        self,
        blinded_element: bytes,
    ) -> VOPRFEvaluation:
        self.started.set()
        self.release.wait(timeout=5)
        return super().evaluate(blinded_element)


def make_state(
    server: FakeServer,
    *,
    concurrency: int = 1,
    timeout_ms: int = 1_000,
) -> DeploymentState:
    return DeploymentState(
        deployment_id=DEPLOYMENT_ID,
        voprf_key_version=1,
        configuration_fingerprint="f" * 64,
        voprf_server=server,
        voprf_max_concurrency=concurrency,
        voprf_evaluation_timeout_ms=timeout_ms,
    )


def request(
    **changes: object,
) -> EvaluateVOPRFRequest:
    values = {
        "protocol_version": "v1",
        "deployment_id": DEPLOYMENT_ID,
        "voprf_key_version": 1,
        "voprf_mode": "voprf",
        "voprf_ciphersuite": "ristretto255-SHA512",
        "linkage_encoding_version": 1,
        "blinded_element": BLINDED_ELEMENT,
    }
    values.update(changes)
    return EvaluateVOPRFRequest.model_validate(values)


def code(result) -> str:
    assert result.isError
    assert result.structuredContent is not None
    assert set(result.structuredContent) == {
        "message",
        "omneum_code",
    }
    assert json.loads(result.content[0].text) == (
        result.structuredContent
    )
    return result.structuredContent["omneum_code"]


def test_request_schema() -> None:
    schema = EvaluateVOPRFRequest.model_json_schema()
    fields = {
        "protocol_version",
        "deployment_id",
        "voprf_key_version",
        "voprf_mode",
        "voprf_ciphersuite",
        "linkage_encoding_version",
        "blinded_element",
    }
    assert schema["additionalProperties"] is False
    assert set(schema["properties"]) == fields
    assert set(schema["required"]) == fields


@pytest.mark.parametrize(
    "changes",
    [
        {"voprf_key_version": True},
        {"voprf_key_version": "1"},
        {"voprf_key_version": 0},
        {"voprf_key_version": 2**32},
        {"linkage_encoding_version": True},
        {"deployment_id": "8d96fc18-f40f-4ec7-8ae8-f3711d88b741"},
        {"deployment_id": DEPLOYMENT_ID.upper()},
    ],
)
def test_strict_request_validation(
    changes: dict[str, object],
) -> None:
    values = request().model_dump()
    values.update(changes)
    with pytest.raises(ValueError):
        EvaluateVOPRFRequest.model_validate(values)


@pytest.mark.parametrize(
    ("field", "value", "expected"),
    [
        (
            "protocol_version",
            "v3",
            "unsupported_protocol_version",
        ),
        (
            "deployment_id",
            "urn:uuid:01234567-89ab-cdef-0123-456789abcdef",
            "deployment_mismatch",
        ),
        (
            "voprf_key_version",
            2,
            "voprf_key_version_mismatch",
        ),
        (
            "voprf_mode",
            "oprf",
            "unsupported_voprf_mode",
        ),
        (
            "voprf_ciphersuite",
            "other",
            "unsupported_voprf_ciphersuite",
        ),
        (
            "linkage_encoding_version",
            2,
            "unsupported_linkage_encoding_version",
        ),
    ],
)
def test_metadata_mismatch(
    field: str,
    value: object,
    expected: str,
) -> None:
    async def run() -> None:
        server = FakeServer()
        service = EvaluationService(make_state(server))
        try:
            result = await service.evaluate(
                request(**{field: value})
            )
            assert code(result) == expected
            assert server.calls == 0
        finally:
            service.close()

    asyncio.run(run())


def test_metadata_precedes_blinded_element() -> None:
    async def run() -> None:
        server = FakeServer()
        service = EvaluationService(make_state(server))
        try:
            result = await service.evaluate(
                request(
                    protocol_version="v2",
                    blinded_element="not base64!",
                )
            )
            assert code(result) == (
                "unsupported_protocol_version"
            )
            assert server.calls == 0
        finally:
            service.close()

    asyncio.run(run())


@pytest.mark.parametrize(
    "value",
    [
        "",
        "A" * 42,
        "A" * 44,
        BLINDED_ELEMENT + "=",
        BLINDED_ELEMENT[:-1] + "+",
        BLINDED_ELEMENT[:-1] + " ",
    ],
)
def test_invalid_base64url(value: str) -> None:
    async def run() -> None:
        server = FakeServer()
        service = EvaluationService(make_state(server))
        try:
            result = await service.evaluate(
                request(blinded_element=value)
            )
            assert code(result) == "invalid_blinded_element"
            assert server.calls == 0
        finally:
            service.close()

    asyncio.run(run())


@pytest.mark.parametrize(
    ("failure", "expected"),
    [
        (
            InvalidBlindedElementError("invalid"),
            "invalid_blinded_element",
        ),
        (
            OPRFProtocolError("failed"),
            "evaluation_failed",
        ),
        (
            RuntimeError("secret detail"),
            "internal_error",
        ),
    ],
)
def test_evaluation_failures(
    failure: Exception,
    expected: str,
) -> None:
    async def run() -> None:
        service = EvaluationService(
            make_state(FakeServer(failure=failure))
        )
        try:
            result = await service.evaluate(request())
            assert code(result) == expected
            assert "secret detail" not in result.content[0].text
        finally:
            service.close()

    asyncio.run(run())


@pytest.mark.parametrize(
    "evaluation",
    [
        VOPRFEvaluation(
            evaluated_element=b"e" * 31,
            proof=b"p" * 64,
        ),
        VOPRFEvaluation(
            evaluated_element=b"e" * 32,
            proof=b"p" * 63,
        ),
    ],
)
def test_invalid_native_result_sizes(
    evaluation: VOPRFEvaluation,
) -> None:
    async def run() -> None:
        service = EvaluationService(
            make_state(
                FakeServer(evaluation=evaluation)
            )
        )
        try:
            result = await service.evaluate(request())
            assert code(result) == "evaluation_failed"
        finally:
            service.close()

    asyncio.run(run())


def test_success() -> None:
    async def run() -> None:
        service = EvaluationService(
            make_state(FakeServer())
        )
        try:
            result = await service.evaluate(request())
            assert not result.isError
            content = result.structuredContent
            assert content is not None
            assert content["protocol_version"] == "v1"
            assert content["deployment_id"] == DEPLOYMENT_ID
            assert content["voprf_key_version"] == 1
            assert content["voprf_mode"] == "voprf"
            assert (
                content["voprf_ciphersuite"]
                == "ristretto255-SHA512"
            )
            assert content["linkage_encoding_version"] == 1
            assert len(
                base64.urlsafe_b64decode(
                    content["evaluated_element"] + "="
                )
            ) == 32
            assert len(
                base64.urlsafe_b64decode(
                    content["proof"] + "=="
                )
            ) == 64
        finally:
            service.close()

    asyncio.run(run())


def test_overload_and_recovery() -> None:
    async def run() -> None:
        server = BlockingServer()
        service = EvaluationService(make_state(server))
        try:
            first = asyncio.create_task(
                service.evaluate(request())
            )
            await asyncio.to_thread(
                server.started.wait,
                1,
            )
            assert code(
                await service.evaluate(request())
            ) == "server_busy"
            server.release.set()
            assert not (await first).isError
            assert not (
                await service.evaluate(request())
            ).isError
        finally:
            server.release.set()
            service.close()

    asyncio.run(run())


def test_timeout_keeps_capacity_until_completion() -> None:
    async def run() -> None:
        server = BlockingServer()
        service = EvaluationService(
            make_state(server, timeout_ms=10)
        )
        try:
            assert code(
                await service.evaluate(request())
            ) == "request_timeout"
            assert code(
                await service.evaluate(request())
            ) == "server_busy"
            server.release.set()
            for _ in range(100):
                result = await service.evaluate(request())
                if not result.isError:
                    break
                assert code(result) == "server_busy"
                await asyncio.sleep(0.01)
            else:
                raise AssertionError(
                    "evaluation capacity was not released"
                )
        finally:
            server.release.set()
            service.close()

    asyncio.run(run())


def test_fastmcp_rejects_unknown_fields() -> None:
    async def run() -> None:
        server = create_server(
            make_state(FakeServer())
        )
        tool = server._tool_manager.get_tool(
            "evaluate_voprf"
        )
        assert tool is not None
        assert (
            tool.parameters["additionalProperties"]
            is False
        )
        result = await server.call_tool(
            "evaluate_voprf",
            {
                **request().model_dump(),
                "unknown": "value",
            },
        )
        assert code(result) == "invalid_request"

    asyncio.run(run())
