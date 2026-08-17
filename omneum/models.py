import uuid
from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
)


OmneumCode = Literal[
    "request_too_large",
    "invalid_request",
    "authentication_required",
    "permission_denied",
    "unsupported_protocol_version",
    "deployment_mismatch",
    "voprf_key_version_mismatch",
    "unsupported_voprf_mode",
    "unsupported_voprf_ciphersuite",
    "unsupported_linkage_encoding_version",
    "invalid_blinded_element",
    "invalid_graph",
    "rate_limited",
    "server_busy",
    "request_timeout",
    "evaluation_failed",
    "assertion_evaluation_failed",
    "internal_error",
]


def _canonical_deployment_id(value: str) -> str:
    prefix = "urn:uuid:"
    if not value.startswith(prefix):
        raise ValueError("deployment_id must be a canonical UUID URN")
    try:
        parsed = uuid.UUID(value[len(prefix):])
    except ValueError:
        raise ValueError(
            "deployment_id must be a canonical UUID URN"
        ) from None
    if value != f"{prefix}{parsed}":
        raise ValueError("deployment_id must be a canonical UUID URN")
    return value


class EvaluateVOPRFRequest(BaseModel):
    """Single-element RFC 9497 VOPRF evaluation request."""

    model_config = ConfigDict(
        extra="forbid",
        strict=True,
    )

    protocol_version: str
    deployment_id: str
    voprf_key_version: int = Field(
        ge=1,
        le=2**32 - 1,
    )
    voprf_mode: str
    voprf_ciphersuite: str
    linkage_encoding_version: int
    blinded_element: str

    @field_validator("deployment_id")
    @classmethod
    def validate_deployment_id(cls, value: str) -> str:
        return _canonical_deployment_id(value)


class EvaluateVOPRFResponse(BaseModel):
    """Single-element RFC 9497 VOPRF evaluation response."""

    model_config = ConfigDict(
        extra="forbid",
        strict=True,
    )

    protocol_version: str
    deployment_id: str
    voprf_key_version: int = Field(ge=1, le=2**32 - 1)
    voprf_mode: str
    voprf_ciphersuite: str
    linkage_encoding_version: int
    evaluated_element: str
    proof: str

    @field_validator("deployment_id")
    @classmethod
    def validate_deployment_id(cls, value: str) -> str:
        return _canonical_deployment_id(value)


class OmneumErrorResponse(BaseModel):
    """Stable structured tool failure."""

    model_config = ConfigDict(
        extra="forbid",
        strict=True,
    )

    message: str
    omneum_code: OmneumCode


class _StrictModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
    )


class Assertion(_StrictModel):
    source_id: str
    attribute_id: str
    claim_id: str


class SourcePair(_StrictModel):
    source_a_id: str
    source_b_id: str
    dependency: float
    weighted_signal_coverage: float


class EvaluateAssertionRequest(_StrictModel):
    protocol_version: str
    deployment_id: str
    voprf_key_version: int = Field(
        ge=1,
        le=2**32 - 1,
    )
    voprf_mode: str
    voprf_ciphersuite: str
    linkage_encoding_version: int
    assertions: list[Assertion]
    source_pairs: list[SourcePair]

    @field_validator("deployment_id")
    @classmethod
    def validate_deployment_id(cls, value: str) -> str:
        return _canonical_deployment_id(value)


class SourceReliability(_StrictModel):
    source_id: str
    reliability: float = Field(ge=0, allow_inf_nan=False)


class ConflictingClaim(_StrictModel):
    claim_id: str
    support: float = Field(ge=0, allow_inf_nan=False)


class SupportingSource(_StrictModel):
    source_id: str
    independence: float = Field(
        ge=0,
        le=1,
        allow_inf_nan=False,
    )
    contribution: float = Field(ge=0, allow_inf_nan=False)


class ClaimSupport(_StrictModel):
    attribute_id: str
    claim_id: str
    support: float = Field(ge=0, allow_inf_nan=False)
    agreement_weight: float = Field(
        ge=0,
        le=1,
        allow_inf_nan=False,
    )
    is_attribute_max_support: bool
    supporting_source_count: int = Field(ge=1)
    estimated_independent_support_count: float = Field(
        ge=1,
        allow_inf_nan=False,
    )
    dependency_confidence: float | None = Field(
        ge=0,
        le=1,
        allow_inf_nan=False,
    )
    supporting_sources: list[SupportingSource]
    conflicting_claims: list[ConflictingClaim]


class Summary(_StrictModel):
    source_count: int = Field(ge=1, le=64)
    claim_count: int = Field(ge=1, le=4096)
    assertion_count: int = Field(ge=1, le=4096)


class Metadata(_StrictModel):
    algorithm_version: str
    iterations: int = Field(ge=1, le=1000)
    converged: bool
    convergence_tolerance: float = Field(
        ge=0,
        allow_inf_nan=False,
    )
    convergence_delta: float = Field(
        ge=0,
        allow_inf_nan=False,
    )


class EvaluateAssertionResponse(_StrictModel):
    protocol_version: str
    deployment_id: str
    voprf_key_version: int = Field(ge=1, le=2**32 - 1)
    voprf_mode: str
    voprf_ciphersuite: str
    linkage_encoding_version: int
    summary: Summary
    source_reliability: list[SourceReliability]
    claim_support: list[ClaimSupport]
    metadata: Metadata

    @field_validator("deployment_id")
    @classmethod
    def validate_deployment_id(cls, value: str) -> str:
        return _canonical_deployment_id(value)


class PingResponse(BaseModel):

    status: str

    protocol_version: str
    algorithm_version: str
    deployment_id: str
    voprf_key_version: int
    voprf_mode: str
    voprf_ciphersuite: str
    linkage_encoding_version: int
    configuration_fingerprint: str
