from __future__ import annotations

import asyncio
import json
import threading
from concurrent.futures import ThreadPoolExecutor

from mcp.types import CallToolResult, TextContent

from verity.base64url import decode_unpadded, encode_unpadded
from verity.config import (
    PROTOCOL_VERSION,
    VOPRF_MODE,
    DeploymentState,
)
from verity.linkage import ENCODING_VERSION
from verity.models import (
    EvaluateVOPRFRequest,
    EvaluateVOPRFResponse,
    VerityErrorResponse,
)
from verity.oprf import (
    CIPHERSUITE,
    ELEMENT_LENGTH,
    PROOF_LENGTH,
    InvalidBlindedElementError,
    OPRFProtocolError,
)


class EvaluationService:
    """Bounded, stateless access to one long-lived VOPRF server."""

    def __init__(
        self,
        state: DeploymentState,
    ) -> None:
        self._state = state
        self._timeout_seconds = (
            state.voprf_evaluation_timeout_ms / 1_000
        )
        self._executor = ThreadPoolExecutor(
            max_workers=state.voprf_max_concurrency,
            thread_name_prefix="verity-voprf",
        )
        self._capacity = state.voprf_max_concurrency
        self._active = 0
        self._closed = False
        self._lock = threading.Lock()

    async def evaluate(
        self,
        request: EvaluateVOPRFRequest,
    ) -> CallToolResult:
        mismatch = self._metadata_error(request)
        if mismatch is not None:
            return mismatch

        try:
            blinded_element = _decode_blinded_element(
                request.blinded_element
            )
        except ValueError:
            return error_result(
                "The blinded element is invalid.",
                "invalid_blinded_element",
            )

        try:
            future = self._submit(blinded_element)
        except Exception:
            return error_result(
                "An internal server error occurred.",
                "internal_error",
            )
        if future is None:
            return error_result(
                "Evaluation capacity is exhausted.",
                "server_busy",
            )

        try:
            evaluation = await asyncio.wait_for(
                asyncio.shield(
                    asyncio.wrap_future(future)
                ),
                timeout=self._timeout_seconds,
            )
        except TimeoutError:
            return error_result(
                "Evaluation exceeded its deadline.",
                "request_timeout",
            )
        except InvalidBlindedElementError:
            return error_result(
                "The blinded element is invalid.",
                "invalid_blinded_element",
            )
        except OPRFProtocolError:
            return error_result(
                "Evaluation failed.",
                "evaluation_failed",
            )
        except Exception:
            return error_result(
                "An internal server error occurred.",
                "internal_error",
            )

        try:
            response = EvaluateVOPRFResponse(
                protocol_version=PROTOCOL_VERSION,
                deployment_id=self._state.deployment_id,
                voprf_key_version=(
                    self._state.voprf_key_version
                ),
                voprf_mode=VOPRF_MODE,
                voprf_ciphersuite=CIPHERSUITE,
                linkage_encoding_version=ENCODING_VERSION,
                evaluated_element=encode_unpadded(
                    evaluation.evaluated_element,
                    expected_length=ELEMENT_LENGTH,
                ),
                proof=encode_unpadded(
                    evaluation.proof,
                    expected_length=PROOF_LENGTH,
                ),
            )
        except Exception:
            return error_result(
                "Evaluation failed.",
                "evaluation_failed",
            )

        return success_result(response)

    def close(self) -> None:
        with self._lock:
            self._closed = True
        self._executor.shutdown(
            wait=True,
            cancel_futures=True,
        )

    def _submit(self, blinded_element: bytes):
        with self._lock:
            if (
                self._closed
                or self._active >= self._capacity
            ):
                return None
            self._active += 1

        try:
            future = self._executor.submit(
                self._state.voprf_server.evaluate,
                blinded_element,
            )
        except Exception:
            self._release()
            raise

        future.add_done_callback(
            lambda _future: self._release()
        )
        return future

    def _release(self) -> None:
        with self._lock:
            self._active -= 1

    def _metadata_error(
        self,
        request: EvaluateVOPRFRequest,
    ) -> CallToolResult | None:
        comparisons = (
            (
                request.protocol_version,
                PROTOCOL_VERSION,
                "The protocol version is unsupported.",
                "unsupported_protocol_version",
            ),
            (
                request.deployment_id,
                self._state.deployment_id,
                "The deployment does not match.",
                "deployment_mismatch",
            ),
            (
                request.voprf_key_version,
                self._state.voprf_key_version,
                "The VOPRF key version does not match.",
                "voprf_key_version_mismatch",
            ),
            (
                request.voprf_mode,
                VOPRF_MODE,
                "The VOPRF mode is unsupported.",
                "unsupported_voprf_mode",
            ),
            (
                request.voprf_ciphersuite,
                CIPHERSUITE,
                "The VOPRF ciphersuite is unsupported.",
                "unsupported_voprf_ciphersuite",
            ),
            (
                request.linkage_encoding_version,
                ENCODING_VERSION,
                "The linkage encoding version is unsupported.",
                "unsupported_linkage_encoding_version",
            ),
        )
        for actual, expected, message, code in comparisons:
            if actual != expected:
                return error_result(message, code)
        return None


def invalid_request_result() -> CallToolResult:
    return error_result(
        "Request validation failed.",
        "invalid_request",
    )


def error_result(
    message: str,
    verity_code: str,
) -> CallToolResult:
    response = VerityErrorResponse(
        message=message,
        verity_code=verity_code,
    ).model_dump(mode="json")
    return CallToolResult(
        content=[
            TextContent(
                type="text",
                text=json.dumps(
                    response,
                    separators=(",", ":"),
                    sort_keys=True,
                ),
            )
        ],
        structuredContent=response,
        isError=True,
    )


def success_result(
    response: EvaluateVOPRFResponse,
) -> CallToolResult:
    content = response.model_dump(mode="json")
    return CallToolResult(
        content=[
            TextContent(
                type="text",
                text=json.dumps(
                    content,
                    separators=(",", ":"),
                    sort_keys=True,
                ),
            )
        ],
        structuredContent=content,
        isError=False,
    )


def _decode_blinded_element(value: str) -> bytes:
    return decode_unpadded(
        value,
        expected_length=ELEMENT_LENGTH,
    )
