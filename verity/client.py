from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from mcp import ClientSession, StdioServerParameters, stdio_client
from mcp.types import CallToolResult
from pydantic import ValidationError

from .base64url import decode_unpadded, encode_unpadded
from .canonicalization import (
    canonicalize_attribute,
    canonicalize_entity,
    canonicalize_source,
    canonicalize_value,
)
from .config import PROTOCOL_VERSION, VOPRF_MODE
from .graph import CredibilityGraph
from .linkage import (
    ENCODING_VERSION,
    LinkageBlindResult,
    LinkageClient,
    LinkagePurpose,
)
from .models import (
    EvaluateVOPRFRequest,
    EvaluateVOPRFResponse,
    VerityErrorResponse,
)
from .oprf import (
    CIPHERSUITE,
    ELEMENT_LENGTH,
    OUTPUT_LENGTH,
    PROOF_LENGTH,
    OPRFError,
    VOPRFClient,
    VOPRFEvaluation,
)


class VerityClientError(Exception):
    """Base class for high-level Verity client failures."""


class VerityClientConfigurationError(VerityClientError, ValueError):
    """Authenticated pinned client configuration is invalid."""


class EvaluationTransportError(VerityClientError):
    """The evaluator transport failed."""

    def __init__(self, *, uncertain: bool) -> None:
        super().__init__("VOPRF evaluation transport failed.")
        self.uncertain = uncertain


class EvaluationRejectedError(VerityClientError):
    """The evaluator returned a valid version-1 Verity failure."""

    def __init__(self, verity_code: str) -> None:
        super().__init__("VOPRF evaluation was rejected.")
        self.verity_code = verity_code


class EvaluationResponseError(VerityClientError):
    """The evaluator response was malformed or inconsistent."""


class EvaluationVerificationError(VerityClientError):
    """The VOPRF proof or finalization result was invalid."""


@dataclass(frozen=True, slots=True)
class VerityClientConfig:
    """Authenticated deployment metadata and VOPRF public-key pin."""

    deployment_id: str
    voprf_key_version: int
    voprf_mode: str
    voprf_ciphersuite: str
    linkage_encoding_version: int
    voprf_public_key: bytes = field(repr=False)

    def __post_init__(self) -> None:
        _validate_deployment_id(self.deployment_id)
        if (
            type(self.voprf_key_version) is not int
            or not 1 <= self.voprf_key_version <= 2**32 - 1
        ):
            raise VerityClientConfigurationError(
                "VOPRF key version is invalid."
            )
        if self.voprf_mode != VOPRF_MODE:
            raise VerityClientConfigurationError(
                "VOPRF mode is unsupported."
            )
        if self.voprf_ciphersuite != CIPHERSUITE:
            raise VerityClientConfigurationError(
                "VOPRF ciphersuite is unsupported."
            )
        if self.linkage_encoding_version != ENCODING_VERSION:
            raise VerityClientConfigurationError(
                "Linkage encoding version is unsupported."
            )
        if (
            type(self.voprf_public_key) is not bytes
            or len(self.voprf_public_key) != ELEMENT_LENGTH
        ):
            raise VerityClientConfigurationError(
                "VOPRF public-key pin is invalid."
            )

    @classmethod
    def from_base64url(
        cls,
        *,
        deployment_id: str,
        voprf_key_version: int,
        voprf_mode: str,
        voprf_ciphersuite: str,
        linkage_encoding_version: int,
        voprf_public_key: str,
    ) -> VerityClientConfig:
        try:
            public_key = decode_unpadded(
                voprf_public_key,
                expected_length=ELEMENT_LENGTH,
            )
        except ValueError:
            raise VerityClientConfigurationError(
                "VOPRF public-key pin is invalid."
            ) from None
        return cls(
            deployment_id=deployment_id,
            voprf_key_version=voprf_key_version,
            voprf_mode=voprf_mode,
            voprf_ciphersuite=voprf_ciphersuite,
            linkage_encoding_version=linkage_encoding_version,
            voprf_public_key=public_key,
        )


@dataclass(frozen=True, slots=True)
class LinkageToken:
    deployment_id: str
    voprf_key_version: int
    voprf_mode: str
    voprf_ciphersuite: str
    linkage_encoding_version: int
    purpose: LinkagePurpose
    value: bytes = field(repr=False)

    def __post_init__(self) -> None:
        if type(self.value) is not bytes or len(self.value) != OUTPUT_LENGTH:
            raise ValueError("linkage token must be 64 bytes")

    def to_base64url(self) -> str:
        return encode_unpadded(
            self.value,
            expected_length=OUTPUT_LENGTH,
        )


@runtime_checkable
class _VOPRFEvaluator(Protocol):
    async def evaluate_voprf(
        self,
        request: EvaluateVOPRFRequest,
    ) -> CallToolResult:
        ...


class VerityClient:
    """Async client for local, pinned Verity linkage evaluation."""

    def __init__(
        self,
        config: VerityClientConfig,
        evaluator: _VOPRFEvaluator,
    ) -> None:
        if type(config) is not VerityClientConfig:
            raise TypeError("config must be a VerityClientConfig")
        if not isinstance(evaluator, _VOPRFEvaluator):
            raise TypeError("evaluator must implement the evaluator protocol")
        try:
            oprf_client = VOPRFClient(config.voprf_public_key)
        except OPRFError:
            raise VerityClientConfigurationError(
                "VOPRF public-key pin is invalid."
            ) from None
        self._config = config
        self._evaluator = evaluator
        self._linkage = LinkageClient(oprf_client)

    async def link_source(
        self,
        kind: str,
        identifier: str,
    ) -> LinkageToken:
        canonical = canonicalize_source(kind, identifier)
        return await self._evaluate(
            self._linkage.blind_source(kind, canonical)
        )

    async def link_attribute(
        self,
        entity_namespace: str,
        entity: str,
        attribute: str,
    ) -> LinkageToken:
        canonical_entity = canonicalize_entity(
            entity_namespace, entity
        )
        canonical_attribute = canonicalize_attribute(attribute)
        return await self._evaluate(
            self._linkage.blind_attribute(
                entity_namespace,
                canonical_entity,
                canonical_attribute,
            )
        )

    async def link_claim(
        self,
        entity_namespace: str,
        entity: str,
        attribute: str,
        value: Any,
    ) -> LinkageToken:
        canonical_entity = canonicalize_entity(
            entity_namespace, entity
        )
        canonical_attribute = canonicalize_attribute(attribute)
        canonical_value = canonicalize_value(value)
        return await self._evaluate(
            self._linkage.blind_claim(
                entity_namespace,
                canonical_entity,
                canonical_attribute,
                canonical_value,
            )
        )

    async def infer_credibility(self, graph: CredibilityGraph):
        """Inference remains outside the implemented SDK milestone."""
        raise NotImplementedError

    async def _evaluate(
        self,
        blind: LinkageBlindResult,
    ) -> LinkageToken:
        request = EvaluateVOPRFRequest(
            protocol_version=PROTOCOL_VERSION,
            deployment_id=self._config.deployment_id,
            voprf_key_version=self._config.voprf_key_version,
            voprf_mode=self._config.voprf_mode,
            voprf_ciphersuite=self._config.voprf_ciphersuite,
            linkage_encoding_version=(
                self._config.linkage_encoding_version
            ),
            blinded_element=encode_unpadded(
                blind.blinded_element,
                expected_length=ELEMENT_LENGTH,
            ),
        )
        result = await self._evaluator.evaluate_voprf(request)
        response = self._validate_response(result)
        try:
            evaluation = VOPRFEvaluation(
                evaluated_element=decode_unpadded(
                    response.evaluated_element,
                    expected_length=ELEMENT_LENGTH,
                ),
                proof=decode_unpadded(
                    response.proof,
                    expected_length=PROOF_LENGTH,
                ),
            )
        except ValueError:
            raise EvaluationResponseError(
                "VOPRF response contains invalid protocol values."
            ) from None
        try:
            value = self._linkage.finalize(blind, evaluation)
        except OPRFError:
            raise EvaluationVerificationError(
                "VOPRF proof verification or finalization failed."
            ) from None
        return LinkageToken(
            deployment_id=self._config.deployment_id,
            voprf_key_version=self._config.voprf_key_version,
            voprf_mode=self._config.voprf_mode,
            voprf_ciphersuite=self._config.voprf_ciphersuite,
            linkage_encoding_version=(
                self._config.linkage_encoding_version
            ),
            purpose=blind.purpose,
            value=value,
        )

    def _validate_response(
        self,
        result: CallToolResult,
    ) -> EvaluateVOPRFResponse:
        if not isinstance(result, CallToolResult):
            raise EvaluationResponseError(
                "Evaluator returned an invalid response."
            )
        if result.isError:
            try:
                error = VerityErrorResponse.model_validate(
                    result.structuredContent,
                    strict=True,
                )
            except ValidationError:
                raise EvaluationResponseError(
                    "Evaluator returned an invalid structured error."
                ) from None
            raise EvaluationRejectedError(error.verity_code)
        try:
            response = EvaluateVOPRFResponse.model_validate(
                result.structuredContent,
                strict=True,
            )
        except ValidationError:
            raise EvaluationResponseError(
                "Evaluator returned an invalid success response."
            ) from None
        comparisons = (
            (response.protocol_version, PROTOCOL_VERSION),
            (response.deployment_id, self._config.deployment_id),
            (
                response.voprf_key_version,
                self._config.voprf_key_version,
            ),
            (response.voprf_mode, self._config.voprf_mode),
            (
                response.voprf_ciphersuite,
                self._config.voprf_ciphersuite,
            ),
            (
                response.linkage_encoding_version,
                self._config.linkage_encoding_version,
            ),
        )
        if any(actual != expected for actual, expected in comparisons):
            raise EvaluationResponseError(
                "Evaluator response metadata does not match the pin."
            )
        return response


class _MCPVOPRFEvaluator:
    def __init__(self, session: ClientSession) -> None:
        self._session = session
        self._closed = False

    async def evaluate_voprf(
        self,
        request: EvaluateVOPRFRequest,
    ) -> CallToolResult:
        if self._closed:
            raise EvaluationTransportError(uncertain=False)
        try:
            return await self._session.call_tool(
                "evaluate_voprf",
                request.model_dump(mode="json"),
            )
        except Exception:
            raise EvaluationTransportError(uncertain=True) from None

    def close(self) -> None:
        self._closed = True


@asynccontextmanager
async def open_stdio_client(
    config: VerityClientConfig,
    server: StdioServerParameters,
) -> AsyncIterator[VerityClient]:
    """Open and own one local MCP stdio subprocess and client session."""
    async with stdio_client(server) as (read, write):
        async with ClientSession(read, write) as session:
            try:
                await session.initialize()
                tools = await session.list_tools()
            except Exception:
                raise EvaluationTransportError(uncertain=False) from None
            if not any(tool.name == "evaluate_voprf" for tool in tools.tools):
                raise EvaluationResponseError(
                    "The evaluate_voprf tool is unavailable."
                )
            evaluator = _MCPVOPRFEvaluator(session)
            try:
                yield VerityClient(config, evaluator)
            finally:
                evaluator.close()


def _validate_deployment_id(value: object) -> None:
    if type(value) is not str or not value.startswith("urn:uuid:"):
        raise VerityClientConfigurationError(
            "Deployment ID must be a canonical UUID URN."
        )
    try:
        parsed = uuid.UUID(value[9:])
    except ValueError:
        raise VerityClientConfigurationError(
            "Deployment ID must be a canonical UUID URN."
        ) from None
    if value != f"urn:uuid:{parsed}":
        raise VerityClientConfigurationError(
            "Deployment ID must be a canonical UUID URN."
        )
